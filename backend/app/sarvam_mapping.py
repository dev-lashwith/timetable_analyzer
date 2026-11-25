"""Map Sarvam doc-AI JSON into the timetable shape used by the application.

Sarvam is the only extraction provider. This module performs no OCR or model
inference: it only converts the JSON returned by Sarvam into editable grid cells
and header metadata.
"""

import re
from typing import Any

from .normalization import DAY_NAMES, canonical_clock


DAY_ORDER = list(dict.fromkeys(DAY_NAMES.values()))
_SEMESTER_LABEL = re.compile(
    r"\b(?:sem(?:ester)?\s*)?("
    r"1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th|11th|12th|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|"
    r"I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|[1-9]|1[0-2]"
    r")\s*(?:sem(?:ester)?)?\b",
    re.IGNORECASE,
)
_SEMESTER_WORD = re.compile(r"\bsem(?:ester)?\b", re.IGNORECASE)
_SECTION_SUFFIX = re.compile(r"[-–]\s*([A-Za-z0-9]{1,4})\s*$")


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _first(record: Any, *keys: str) -> str | None:
    if not isinstance(record, dict):
        return None
    for key in keys:
        if value := _text(record.get(key)):
            return value
    return None


def _room_key(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _day(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    return DAY_NAMES.get(" ".join(text.casefold().split()))


def _clock(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    # Sarvam sometimes returns a trailing dash from the printed time range.
    candidate = text.strip(" -–—").replace(" ", "")
    return canonical_clock(candidate) if re.fullmatch(r"\d{1,2}:\d{2}(?:am|pm)?", candidate, re.I) else candidate.casefold()


def _slot_key(item: Any) -> tuple[str, str] | None:
    start = _clock(item.get("start_time")) if isinstance(item, dict) else None
    end = _clock(item.get("end_time")) if isinstance(item, dict) else None
    if not start and not end:
        return None
    return start or "", end or ""


def _slot_label(item: Any) -> str:
    start = _clock(item.get("start_time")) if isinstance(item, dict) else None
    end = _clock(item.get("end_time")) if isinstance(item, dict) else None
    if start and end:
        return f"{start}-{end}"
    return start or end or ""


def _semester(value: str | None) -> str | None:
    text = _text(value)
    if not text or not _SEMESTER_WORD.search(text):
        return None
    match = _SEMESTER_LABEL.search(text)
    return f"Semester {match.group(1)}" if match else text


def _page_number(value: Any, fallback: int = 1) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else fallback


def _class_parts(class_value: str | None, program: str | None) -> tuple[str | None, str | None]:
    section = None
    if class_value and (match := _SECTION_SUFFIX.search(class_value)):
        section = match.group(1)
    if program:
        return program, section
    if not class_value:
        return None, section
    name = re.sub(r"\b(?:\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|[IVXLCDM]+)\s*sem(?:ester)?\b", " ", class_value, flags=re.I)
    if section:
        name = _SECTION_SUFFIX.sub("", name)
    name = re.sub(r"[()]", " ", name)
    name = " ".join(name.split()) or None
    return name, section


def _map_metadata(record: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    class_value = _first(record, "class")
    program = _first(record, "program_or_specialization") or _first(fallback, "program_or_specialization")
    class_name, section = _class_parts(class_value, program)
    semester = _semester(_first(record, "semester") or _first(record, "class"))
    return {
        "academic_year": _first(record, "academic_year", "session") or _first(fallback, "academic_year", "session"),
        "semester": semester or _semester(_first(fallback, "semester", "class")),
        "class_name": class_name or _first(fallback, "class_name"),
        "section": _first(record, "section") or section or _first(fallback, "section"),
        "stream": _first(record, "stream", "department", "department_name")
        or _first(fallback, "department_name"),
        "room": _first(record, "room_no", "room_number", "room") or _first(fallback, "room_number"),
        "source_page": _page_number(
            record.get("page_number") if isinstance(record, dict) else None,
            _page_number(fallback.get("page_number"), 1),
        ),
        "issue": _first(record, "issue"),
    }


def metadata_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("department_and_academic_information")
    if isinstance(records, list) and records:
        return [_map_metadata(record, payload) for record in records]
    return [_map_metadata(payload, payload)]


def _group_schedule(
    schedule: list[dict[str, Any]],
    metadata: list[dict[str, Any]],
    warnings: list[str],
) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = [[] for _ in metadata]
    unmatched_warned = False
    for item in schedule:
        if len(metadata) == 1:
            groups[0].append(item)
            continue
        room = _room_key(_first(item, "room"))
        matches = [
            position for position, values in enumerate(metadata)
            if room and _room_key(values.get("room")) == room
        ]
        if matches:
            for index in matches:
                groups[index].append(item)
        elif not room:
            # Breaks and shared classes have no room; Sarvam repeats them per
            # page, so they apply to every timetable in the document.
            for group in groups:
                group.append(item)
        else:
            if not unmatched_warned:
                warnings.append(
                    "Sarvam returned schedule rows whose room did not match any page header; "
                    "unmatched rows were placed on the first timetable. Review the page assignment."
                )
                unmatched_warned = True
            groups[0].append(item)
    return groups


def _time_slots(payload: dict[str, Any], schedule: list[dict[str, Any]]) -> list[tuple[tuple[str, str], str]]:
    slots: dict[tuple[str, str], str] = {}
    candidates = [*payload.get("time_slot", []), *schedule]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        key = _slot_key(item)
        label = _slot_label(item)
        if key and label:
            slots.setdefault(key, label)
    return sorted(slots.items(), key=lambda entry: (entry[0][0], entry[0][1]))


def _cell_text(entries: list[dict[str, Any]]) -> str:
    values: list[str] = []
    for entry in entries:
        slot_type = _first(entry, "slot_type")
        if slot_type and re.search(r"break", slot_type, re.I):
            label = slot_type.upper()
        else:
            label = _first(entry, "subject_abbreviation", "subject", "subject_name", "session_type", "slot_type")
        group = _first(entry, "group", "student_group")
        if label and group and group.casefold() not in label.casefold():
            label = f"{label} ({group})"
        if label and label not in values:
            values.append(label)
    return " / ".join(values[:3])


def _add_geometry(table: dict[str, Any]) -> None:
    widths = table["column_widths"]
    heights = table["row_heights"]
    for cell in table["cells"]:
        row, column = cell["row"], cell["column"]
        x = sum(widths[:column])
        y = sum(heights[:row])
        width = sum(widths[column:column + cell["colspan"]])
        height = sum(heights[row:row + cell["rowspan"]])
        cell["x"] = x
        cell["y"] = y
        cell["width"] = width
        cell["height"] = height
        cell["source_bbox"] = {
            "x": x, "y": y, "width": width, "height": height,
            "coordinate_space": "synthesized_table_grid_pixels",
        }


def build_timetables(payload: dict[str, Any], warnings: list[str] | None = None) -> list[dict[str, Any]]:
    """Convert a Sarvam result into one or more editable timetable dictionaries."""
    warnings = warnings if warnings is not None else []
    raw_schedule = payload.get("weekly_schedule")
    schedule = [item for item in raw_schedule if isinstance(item, dict)] if isinstance(raw_schedule, list) else []
    if not schedule and not payload.get("time_slot"):
        warnings.append("Sarvam did not return a weekly schedule or time slots for this document.")
        return []

    metadata = metadata_rows(payload)
    groups = _group_schedule(schedule, metadata, warnings)
    slots = _time_slots(payload, schedule)
    days = sorted(
        {day for item in schedule if (day := _day(item.get("day")))},
        key=lambda day: DAY_ORDER.index(day) if day in DAY_ORDER else len(DAY_ORDER),
    )
    if len(days) > 7 or len(slots) + 1 > 40 or (len(days) + 1) * (len(slots) + 1) > 2000:
        warnings.append("Sarvam returned a schedule larger than the supported grid; some slots were ignored.")
        days = days[:7]
        slots = slots[:39]

    column_count = len(slots) + 1
    row_count = len(days) + 1
    column_widths = [130, *([110] * len(slots))]
    row_heights = [40] * row_count
    tables: list[dict[str, Any]] = []
    for index, values in enumerate(metadata):
        if not groups[index] and not slots:
            continue
        cells: list[dict[str, Any]] = [{
            "row": 0, "column": 0, "rowspan": 1, "colspan": 1, "text": "Day",
        }]
        for column, (_, label) in enumerate(slots, start=1):
            cells.append({"row": 0, "column": column, "rowspan": 1, "colspan": 1, "text": label})
        for row, day in enumerate(days, start=1):
            cells.append({"row": row, "column": 0, "rowspan": 1, "colspan": 1, "text": day.title()})
            for column, (key, _) in enumerate(slots, start=1):
                entries = [
                    item for item in groups[index]
                    if _day(item.get("day")) == day and _slot_key(item) == key
                ]
                cells.append({
                    "row": row, "column": column, "rowspan": 1, "colspan": 1,
                    "text": _cell_text(entries),
                })
        table = {
            "row_count": row_count,
            "column_count": column_count,
            "column_widths": column_widths,
            "row_heights": row_heights,
            "cells": cells,
            **{key: value for key, value in values.items() if key not in {"issue"}},
        }
        table["warnings"] = [values["issue"]] if values.get("issue") else []
        _add_geometry(table)
        tables.append(table)
    return tables
