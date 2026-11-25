import re

from .semester import guess_semester_from_text


ACADEMIC_YEAR = re.compile(r"\b(?:19|20)\d{2}\s*(?:[-–/]\s*(?:\d{2}|(?:19|20)\d{2}))?\b")
ROOM = re.compile(r"\b(?:room|hall|lab(?:oratory)?)\s*(?:no\.?|number)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{0,15})\b", re.I)
CLASS = re.compile(r"\b(?:class|year|programme|program|course)\s*(?:no\.?|number)?\s*[:#-]\s*([^\r\n,;]{1,80})", re.I)
SECTION = re.compile(r"\bsection\s*[:#-]\s*([A-Z0-9-]{1,20})\b", re.I)
STREAM = re.compile(r"\b(?:branch|stream|department|dept\.?)\s*[:#-]\s*([^\r\n,;]{1,80})", re.I)


def normalize_label(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def metadata_from_text(text: str) -> dict[str, str | None]:
    semester = guess_semester_from_text(text).name
    academic_year = ACADEMIC_YEAR.search(text or "")
    room = ROOM.search(text or "")
    class_match = CLASS.search(text or "")
    section = SECTION.search(text or "")
    stream = STREAM.search(text or "")
    return {
        "academic_year": normalize_label(academic_year.group(0)) if academic_year else None,
        "semester": semester,
        "class_name": normalize_label(class_match.group(1)) if class_match else None,
        "section": normalize_label(section.group(1)) if section else None,
        "stream": normalize_label(stream.group(1)) if stream else None,
        "room": normalize_label(room.group(1)) if room else None,
    }


def merge_metadata(text_values: dict, vision_values: dict) -> dict[str, str | None]:
    """Prefer explicit page text, then vision model output, with missing values left blank."""
    limits = {"academic_year": 80, "semester": 80, "class_name": 80, "section": 80, "stream": 80, "room": 100}
    return {
        key: (text_values.get(key) or normalize_label(vision_values.get(key)) or None)[:limit]
        if (text_values.get(key) or normalize_label(vision_values.get(key))) else None
        for key, limit in limits.items()
    }
