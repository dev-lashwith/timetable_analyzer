"""Normalization helpers for metadata returned by Sarvam or edited during review.

No metadata is inferred from raw document text here: Sarvam is the only
extraction provider. These helpers only clean and validate values before they
are stored or displayed.
"""

import re


ROOM_CODE = re.compile(r"[A-Z0-9]+(?:[-/][A-Z0-9]+)*\Z", re.I)
ROOM = re.compile(
    r"\b(?:room|hall|lab(?:oratory)?)\s*(?:no\.?|number)?\s*[:#=\-–—]?\s*"
    r"(?:[A-Z]{1,6}\s+\d{1,4}[A-Z]?|\d{1,4}[A-Z]?|[A-Z0-9][A-Z0-9/-]{0,15})\b",
    re.I,
)
LIMITS = {
    "academic_year": 80,
    "semester": 80,
    "class_name": 80,
    "section": 80,
    "stream": 80,
    "room": 100,
}


def normalize_label(value: str | None) -> str | None:
    return " ".join((value or "").split()) or None


def normalize_room(value: str | None) -> str | None:
    """Accept only room-like identifiers containing a digit."""
    candidate = normalize_label(value)
    if not candidate:
        return None
    compound_room = re.match(r"^([A-Z]{1,6})\s+(\d{1,4}[A-Z]?)\b", candidate, re.I)
    if compound_room and compound_room.group(1).casefold() not in {
        "class", "hall", "lab", "room", "year", "semester", "section", "stream", "branch",
    }:
        return f"{compound_room.group(1).upper()} {compound_room.group(2).upper()}"
    lab_name = re.fullmatch(r"(lab(?:oratory)?)\s+(?:no\.?\s*)?([A-Z0-9][A-Z0-9/-]{0,15})", candidate, re.I)
    if lab_name:
        token = lab_name.group(2)
        if not any(char.isdigit() for char in token) or not ROOM_CODE.fullmatch(token):
            return None
        return f"{lab_name.group(1).title()} {token}"
    candidate = re.sub(r"^(?:class\s*room|room|hall)(?:\s*(?:no\.?|number))?\s*[:#-]?\s*", "", candidate, flags=re.I)
    compound_room = re.match(r"^([A-Z]{1,6})\s+(\d{1,4}[A-Z]?)\b", candidate, re.I)
    if compound_room and compound_room.group(1).casefold() not in {
        "class", "hall", "lab", "room", "year", "semester", "section", "stream", "branch",
    }:
        return f"{compound_room.group(1).upper()} {compound_room.group(2).upper()}"
    token = candidate.split()[0].strip(".,;:") if candidate else ""
    if not token or not any(char.isdigit() for char in token) or not ROOM_CODE.fullmatch(token):
        return None
    if re.fullmatch(r"(?:19|20)\d{2}(?:[-/]\d{2,4})?", token):
        return None
    return token


def merge_metadata(primary: dict, secondary: dict) -> dict[str, str | None]:
    """Clean and combine already-extracted values, preferring the first source."""
    result: dict[str, str | None] = {}
    for key, limit in LIMITS.items():
        value = primary.get(key) or secondary.get(key)
        cleaned = normalize_label(value) if isinstance(value, str) else None
        if key == "room":
            cleaned = normalize_room(cleaned)
            if not cleaned:
                for source in (primary, secondary):
                    for candidate in ROOM.finditer(" ".join(
                        str(item) for item in source.values() if isinstance(item, str)
                    )):
                        if cleaned := normalize_room(candidate.group(0)):
                            break
                    if cleaned:
                        break
        result[key] = cleaned[:limit] if cleaned else None
    return result
