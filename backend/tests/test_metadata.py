from app.metadata import merge_metadata, metadata_from_text
from app.normalization import normalized_cell_text


def test_detects_explicit_department_timetable_metadata():
    values = metadata_from_text(
        "Academic Year: 2025-26\nSemester: IV\nClass: Third Year\nSection: B\n"
        "Department: AIML\nRoom No: C-204"
    )
    assert values == {
        "academic_year": "2025-26",
        "semester": "Semester IV",
        "class_name": "Third Year",
        "section": "B",
        "stream": "AIML",
        "room": "C-204",
    }


def test_metadata_fallback_uses_vision_values_only_when_text_is_missing():
    result = merge_metadata(
        {"academic_year": "2025-26", "semester": None, "class_name": None, "section": None, "stream": None, "room": None},
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
