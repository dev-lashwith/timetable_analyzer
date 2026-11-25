from unittest.mock import patch

from app.sarvam_client import SarvamError, extract_documents
from app.sarvam_mapping import build_timetables


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        return self.payload


def test_client_submits_polls_and_unwraps_sarvam_results(monkeypatch, sarvam_payload):
    monkeypatch.setattr("app.sarvam_client.SARVAM_API_KEY", "test-key")
    monkeypatch.setattr("app.sarvam_client.SARVAM_POLL_INTERVAL_SECONDS", 0)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "POST":
            return FakeResponse({"job_id": "job-1"})
        if url.endswith("/status"):
            return FakeResponse({"status": "processing" if len(calls) == 2 else "completed"})
        return FakeResponse({"data": sarvam_payload})

    with patch("app.sarvam_client.requests.request", side_effect=fake_request), \
         patch("app.sarvam_client.time.sleep"):
        result = extract_documents([("timetable.pdf", b"%PDF-test", "application/pdf")])

    assert result.status == "completed"
    assert result.data == sarvam_payload
    assert [name for name, _, _ in calls] == ["POST", "GET", "GET", "GET"]
    assert calls[0][1].endswith("/job/extract")
    assert calls[0][2]["headers"] == {"api-subscription-key": "test-key"}
    assert '"type": "object"' in calls[0][2]["data"]["schema"]


def test_client_requires_an_api_key(monkeypatch):
    monkeypatch.setattr("app.sarvam_client.SARVAM_API_KEY", "")
    try:
        extract_documents([("timetable.pdf", b"%PDF-test", "application/pdf")])
    except SarvamError as error:
        assert "SARVAM_API_KEY" in str(error)
    else:
        raise AssertionError("Expected SarvamError when no API key is configured")


def test_mapping_groups_schedule_rows_by_room_and_builds_editable_grid():
    payload = {
        "time_slot": [{"start_time": "08:00", "end_time": "09:00"}],
        "weekly_schedule": [
            {"day": "Monday", "start_time": "08:00", "end_time": "09:00",
             "subject_abbreviation": "DSA", "room": "CV 301"},
            {"day": "Monday", "start_time": "08:00", "end_time": "09:00",
             "subject_abbreviation": "OS", "room": "CV 302"},
        ],
        "department_and_academic_information": [
            {"class": "3rd semester (AINDS)-A", "room_no": "CV 301", "session": "AY 2026-2027",
             "page_number": "1"},
            {"class": "3rd semester (AINDS)-B", "room_no": "CV 302", "session": "AY 2026-2027",
             "page_number": "2"},
        ],
    }
    warnings: list[str] = []
    tables = build_timetables(payload, warnings)

    assert warnings == []
    assert [table["source_page"] for table in tables] == [1, 2]
    assert [table["room"] for table in tables] == ["CV 301", "CV 302"]
    assert tables[0]["class_name"] == "AINDS"
    assert tables[0]["section"] == "A"
    assert tables[0]["semester"] == "Semester 3rd"
    assert tables[0]["row_count"] == 2
    assert tables[0]["column_count"] == 2
    texts = [cell["text"] for cell in tables[0]["cells"]]
    assert texts == ["Day", "08:00-09:00", "Monday", "DSA"]
    assert [cell["text"] for cell in tables[1]["cells"]][-1] == "OS"
    assert tables[0]["cells"][-1]["source_bbox"]["width"] == 110


def test_mapping_deduplicates_trailing_dash_time_slots_and_shares_roomless_rows():
    payload = {
        "time_slot": [
            {"start_time": "08:00", "end_time": "09:00 AM"},
            {"start_time": "08:00-", "end_time": "09:00 AM"},
        ],
        "weekly_schedule": [
            {"day": "Monday", "start_time": "08:00", "end_time": "09:00 AM",
             "subject": "SHORT BREAK", "slot_type": "short break"},
        ],
        "department_and_academic_information": [
            {"class": "3rd semester (AINDS)-A", "room_no": "CV 301", "page_number": "1"},
            {"class": "3rd semester (AINDS)-B", "room_no": "CV 302", "page_number": "2"},
        ],
    }
    warnings: list[str] = []
    tables = build_timetables(payload, warnings)

    assert warnings == []
    assert all(table["column_count"] == 2 for table in tables)
    assert all(table["cells"][1]["text"] == "08:00-09:00" for table in tables)
    assert all(table["cells"][-1]["text"] == "SHORT BREAK" for table in tables)
