from app.metadata import merge_metadata, normalize_room
from app.normalization import normalized_cell_text


def test_merge_metadata_prefers_the_first_source_and_cleans_values():
    result = merge_metadata(
        {"academic_year": " 2025-26 ", "semester": None, "class_name": None, "section": None, "stream": None, "room": None},
        {"academic_year": "2024-25", "semester": "Semester II", "class_name": "II Year", "room": "Lab 2"},
    )
    assert result["academic_year"] == "2025-26"
    assert result["semester"] == "Semester II"
    assert result["class_name"] == "II Year"
    assert result["room"] == "Lab 2"


def test_common_day_and_time_slots_normalize_to_shared_labels():
    assert normalized_cell_text("Mon") == "monday"
    assert normalized_cell_text("09:00 - 10:00") == "09:00-10:00"
    assert normalized_cell_text("9:00 AM to 10:00 am") == "09:00-10:00"


def test_room_normalization_rejects_bare_labels_and_keeps_numbered_rooms():
    assert normalize_room("CV") is None
    assert normalize_room("Room CV") is None
    assert normalize_room("Room No: C-204") == "C-204"
    assert normalize_room("CV 301") == "CV 301"
    assert merge_metadata({"room": "CV"}, {"room": "CV"})["room"] is None
    assert merge_metadata({"room": None}, {"room": "Room 204"})["room"] == "204"
