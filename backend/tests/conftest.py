import pytest

from app.sarvam_client import SarvamExtraction


@pytest.fixture
def sarvam_payload():
    """A small Sarvam doc-AI style result used by extraction tests."""
    return {
        "department_name": "DEPARTMENT OF ARTIFICIAL INTELLIGENCE & DATA SCIENCE",
        "academic_year": "AY 2026-2027",
        "session": "AY 2026-2027",
        "class": "3rd semester (AINDS)-A",
        "program_or_specialization": "AINDS",
        "room_number": "CV 301",
        "time_slot": [
            {"start_time": "08:00", "end_time": "09:00"},
            {"start_time": "09:00", "end_time": "10:00"},
        ],
        "weekly_schedule": [
            {
                "day": "Monday", "start_time": "08:00", "end_time": "09:00",
                "subject_abbreviation": "DSA", "subject_name": "Data Structures",
                "room": "CV 301",
            },
            {
                "day": "Monday", "start_time": "09:00", "end_time": "10:00",
                "subject_abbreviation": "OS", "room": "CV 301",
            },
            {
                "day": "Tuesday", "start_time": "08:00", "end_time": "09:00",
                "slot_type": "SHORT BREAK", "room": "CV 301",
            },
        ],
        "department_and_academic_information": [{
            "department": "DEPARTMENT OF ARTIFICIAL INTELLIGENCE & DATA SCIENCE",
            "class": "3rd semester (AINDS)-A",
            "room_no": "CV 301",
            "session": "AY 2026-2027",
            "page_number": "1",
        }],
    }


@pytest.fixture
def completed_extraction(sarvam_payload):
    return SarvamExtraction(status="completed", data=sarvam_payload, raw=sarvam_payload)
