import re
from datetime import datetime


TIME_RANGE = re.compile(
    r"\b(\d{1,2}:\d{2}\s*(?:am|pm)?)\s*(?:-|–|to)\s*(\d{1,2}:\d{2}\s*(?:am|pm)?)\b",
    re.I,
)
DAY_NAMES = {
    "mon": "monday", "monday": "monday", "tue": "tuesday", "tues": "tuesday", "tuesday": "tuesday",
    "wed": "wednesday", "wednesday": "wednesday", "thu": "thursday", "thur": "thursday", "thurs": "thursday", "thursday": "thursday",
    "fri": "friday", "friday": "friday", "sat": "saturday", "saturday": "saturday", "sun": "sunday", "sunday": "sunday",
}


def clean_text(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def canonical_clock(value: str) -> str:
    text = re.sub(r"\s+", "", value).casefold()
    for pattern in ("%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(text, pattern).strftime("%H:%M")
        except ValueError:
            continue
    return text


def normalized_cell_text(value: str | None) -> str:
    text = clean_text(value).strip(" .,:;")
    if text in DAY_NAMES:
        return DAY_NAMES[text]
    match = TIME_RANGE.search(text)
    if match and match.span() == (0, len(text)):
        return f"{canonical_clock(match.group(1))}-{canonical_clock(match.group(2))}"
    return text
