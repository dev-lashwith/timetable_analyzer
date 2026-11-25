import re
from dataclasses import dataclass

import pymupdf


ROMAN = r"I{1,3}|IV|V|VI{0,3}|IX|XI{0,2}"
ORDINALS = r"(?:st|nd|rd|th)?"
MODIFIERS = r"odd|even|fall|spring|winter|summer"
SEMESTER_WORD = r"(?:semester|sem\.)"

_VALUE_AFTER = re.compile(
    rf"\b{SEMESTER_WORD}\b[\s:.\-–—]*({ROMAN}|\d{{1,2}}|{MODIFIERS})\b",
    re.IGNORECASE,
)
_VALUE_BEFORE = re.compile(
    rf"\b({ROMAN}|\d{{1,2}}|{MODIFIERS}){ORDINALS}\s+(?:semester|sem\.)\b",
    re.IGNORECASE,
)
_MODIFIER_BEFORE = re.compile(
    rf"\b({MODIFIERS})\s+{SEMESTER_WORD}\b[\s:.\-–—]*(\d{{4}}(?:[-/]\d{{2,4}})?)?",
    re.IGNORECASE,
)
_MODIFIER_ONLY = re.compile(rf"\b({MODIFIERS})\b[\s:.\-–—]*(\d{{4}}(?:[-/]\d{{2,4}})?)?", re.IGNORECASE)

MAX_SEMESTER_LENGTH = 80


@dataclass(frozen=True)
class SemesterGuess:
    name: str | None
    confidence: str  # "high", "low", or "none"


def _normalise(value: str) -> str:
    text = " ".join(value.replace("_", " ").split()).strip(" .,:;-–—")
    return text[:MAX_SEMESTER_LENGTH]


def guess_semester_from_text(text: str) -> SemesterGuess:
    """Guess a semester label from embedded PDF text without inventing one."""
    if not text or not text.strip():
        return SemesterGuess(None, "none")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        match = _MODIFIER_BEFORE.search(line)
        if match:
            suffix = f" {match.group(2)}" if match.group(2) else ""
            return SemesterGuess(_normalise(f"Semester {match.group(1)}{suffix}"), "high")
        match = _VALUE_AFTER.search(line)
        if match:
            return SemesterGuess(_normalise(f"Semester {match.group(1)}"), "high")
        match = _VALUE_BEFORE.search(line)
        if match:
            return SemesterGuess(_normalise(f"Semester {match.group(1)}"), "high")

    for line in lines:
        if len(line) > 80:
            continue
        match = _MODIFIER_ONLY.search(line)
        if match:
            suffix = f" {match.group(2)}" if match.group(2) else ""
            return SemesterGuess(_normalise(f"{match.group(1).title()}{suffix}"), "low")

    return SemesterGuess(None, "none")


def guess_semester_from_page(page: pymupdf.Page) -> SemesterGuess:
    try:
        text = page.get_text("text") or ""
    except Exception:
        return SemesterGuess(None, "none")
    return guess_semester_from_text(text)
