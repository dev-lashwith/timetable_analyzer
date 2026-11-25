import json
import re
from pathlib import Path

import pymupdf
from sqlalchemy import select

from .db import SessionLocal
from .metadata import normalize_label
from .models import (
    AcademicYear, ClassGroup, Room, Semester, SharedCellText, TimeSlot, TimetableCell,
    TimetableRecord, UploadedDocument, now_utc,
)
from .normalization import DAY_NAMES, TIME_RANGE, canonical_clock, normalized_cell_text
from .sarvam_client import SarvamError, extract_documents_async
from .sarvam_mapping import _add_geometry, build_timetables
from .validation import TableValidationError, validate_and_complete_table


WEEKDAYS = set(DAY_NAMES.values())


def _norm(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _get_or_create(session, model, normalized_field: str, label_field: str, value: str | None):
    label = " ".join((value or "").split())
    if not label:
        return None
    normalized = _norm(label)
    row = session.scalar(select(model).where(getattr(model, normalized_field) == normalized))
    if row is None:
        row = model(**{label_field: label, normalized_field: normalized})
        session.add(row)
        session.flush()
    return row


def _get_class_group(session, values: dict):
    name = " ".join((values.get("class_name") or "").split())
    section = " ".join((values.get("section") or "").split())
    stream = " ".join((values.get("stream") or "").split())
    if not any((name, section, stream)):
        return None
    key = (_norm(name), _norm(section), _norm(stream))
    row = session.scalar(select(ClassGroup).where(
        ClassGroup.normalized_name == key[0], ClassGroup.normalized_section == key[1], ClassGroup.normalized_stream == key[2]
    ))
    if row is None:
        row = ClassGroup(name=name, section=section, stream=stream,
                         normalized_name=key[0], normalized_section=key[1], normalized_stream=key[2])
        session.add(row)
        session.flush()
    return row


def _get_slot(session, value: str):
    normalized = normalized_cell_text(value)
    if not normalized:
        return None
    match = TIME_RANGE.fullmatch(value.strip())
    day = normalized.title() if normalized in WEEKDAYS else None
    if not day and not match:
        return None
    row = session.scalar(select(TimeSlot).where(TimeSlot.normalized_label == normalized))
    if row:
        return row
    row = TimeSlot(normalized_label=normalized, label=" ".join(value.split()), day=day,
                   start_time=canonical_clock(match.group(1)) if match else None,
                   end_time=canonical_clock(match.group(2)) if match else None)
    session.add(row)
    session.flush()
    return row


_FACULTY_TABLE_TITLE = re.compile(
    r"\b(?:faculty|staff|teacher|instructor)[\s-]+(?:allocation|allotment|workload|load|distribution)\b"
    r"|\b(?:allocation|allotment|workload|distribution)\s+(?:of\s+)?(?:faculty|staff|teachers|instructors)\b",
    re.IGNORECASE,
)


def is_faculty_allocation_table(cells: list[dict], context_text: str = "") -> bool:
    """Recognize faculty grids so older rows and Sarvam output stay out of review."""
    text = " ".join([context_text, *(str(cell.get("text") or "") for cell in cells)])
    if _FACULTY_TABLE_TITLE.search(text):
        return True

    rows: dict[int, list[str]] = {}
    for cell in cells:
        rows.setdefault(int(cell.get("row", 0)), []).append(str(cell.get("text") or "").casefold())
    if not rows:
        return False
    first_row = " ".join(rows[min(rows)])
    second_row = " ".join(rows[min(rows) + 1]) if min(rows) + 1 in rows else ""
    header = f"{first_row} {second_row}"
    has_staff_column = bool(re.search(r"\b(faculty|teacher|staff|instructor)\b", header))
    has_name_header = bool(re.search(r"\b(name|initials|code)\b", header))
    has_subject_field = bool(re.search(r"\b(subject|course)\b", header))
    has_schedule_field = bool(re.search(r"\b(class|section|room|period|hours|workload)\b", header))
    return has_staff_column and (
        (has_name_header and (has_subject_field or has_schedule_field))
        or (has_subject_field and has_schedule_field and bool(re.search(r"\b(workload|allocation)\b", header)))
    )


def _pdf_page_count(data: bytes) -> int | None:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            return pdf.page_count
    except Exception:
        return None


def _page_geometry(data: bytes, page_number: int) -> tuple[dict, dict]:
    """Use the PDF page size for record references; Sarvam supplies all extracted data."""
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if 1 <= page_number <= pdf.page_count:
                rect = pdf.load_page(page_number - 1).rect
                page_size = {"width": round(float(rect.width), 2), "height": round(float(rect.height), 2)}
                return {"x": 0, "y": 0, **page_size, "coordinate_space": "pdf_points"}, page_size
    except Exception:
        pass
    page_size = {"width": 612, "height": 792}
    return {"x": 0, "y": 0, **page_size, "coordinate_space": "pdf_points"}, page_size


def _store_table(
    session,
    document_id: str,
    source_page: int,
    table_index: int,
    metadata: dict,
    confidence: dict,
    page_text: str,
    table_data: dict,
    warnings: list[str],
    source_bbox: dict,
    page_size: dict,
) -> TimetableRecord:
    academic_year = _get_or_create(session, AcademicYear, "normalized_label", "label", metadata.get("academic_year"))
    semester = _get_or_create(session, Semester, "normalized_label", "label", metadata.get("semester"))
    class_group = _get_class_group(session, metadata)
    room = _get_or_create(session, Room, "normalized_label", "label", metadata.get("room"))
    record = TimetableRecord(
        document_id=document_id, source_page=source_page, table_index=table_index,
        table_type="timetable", status="review",
        academic_year_id=academic_year.id if academic_year else None,
        semester_id=semester.id if semester else None,
        class_group_id=class_group.id if class_group else None,
        room_id=room.id if room else None,
        row_count=table_data["row_count"], column_count=table_data["column_count"],
        column_widths=table_data["column_widths"], row_heights=table_data["row_heights"],
        source_bbox=source_bbox, page_size=page_size,
        raw_page_text=page_text, metadata_confidence=confidence,
        warnings=warnings,
    )
    session.add(record)
    session.flush()
    for cell in table_data["cells"]:
        raw_text = cell["text"]
        normalized = normalized_cell_text(raw_text)
        shared = None
        if normalized:
            shared = session.scalar(select(SharedCellText).where(SharedCellText.normalized_text == normalized))
            if shared is None:
                shared = SharedCellText(normalized_text=normalized, display_text=raw_text)
                session.add(shared)
                session.flush()
        slot = _get_slot(session, raw_text) if TIME_RANGE.fullmatch(raw_text.strip()) or normalized in WEEKDAYS else None
        cell_bbox = cell.get("source_bbox") or {
            "x": cell.get("x", 0), "y": cell.get("y", 0),
            "width": cell.get("width", 0), "height": cell.get("height", 0),
            "coordinate_space": "synthesized_table_grid_pixels",
        }
        session.add(TimetableCell(
            timetable_id=record.id, row_index=cell["row"], column_index=cell["column"],
            rowspan=cell["rowspan"], colspan=cell["colspan"], raw_text=raw_text,
            normalized_text=normalized, x=cell.get("x", 0), y=cell.get("y", 0),
            width=cell.get("width", 0), height=cell.get("height", 0), source_bbox=cell_bbox,
            shared_text_id=shared.id if shared else None, time_slot_id=slot.id if slot else None,
        ))
    return record


def store_sarvam_payload(
    document_id: str,
    data: bytes,
    payload: dict,
    processing_warnings: list[str] | None = None,
) -> int:
    """Persist a Sarvam JSON result without making another API call.

    This is also used to recover results from a job that already completed, so
    nobody is billed twice for the same document.
    """
    warnings = list(processing_warnings or [])
    if not isinstance(payload, dict):
        raise SarvamError("Sarvam did not return a JSON object for this document.")
    tables = build_timetables(payload, warnings)
    saved_tables = 0
    for table_index, table in enumerate(tables, start=1):
        try:
            checked, validation_warnings = validate_and_complete_table(table)
            checked.update({key: value for key, value in table.items() if key not in checked})
            _add_geometry(checked)
            metadata = {
                key: normalize_label(checked.get(key))
                for key in ("academic_year", "semester", "class_name", "section", "stream", "room")
            }
            if not metadata.get("room"):
                validation_warnings.append(
                    "Room number was not extracted clearly; enter it manually before verification."
                )
            confidence = {key: "sarvam" for key, value in metadata.items() if value}
            source_page = int(checked.get("source_page") or 1)
            source_bbox, page_size = _page_geometry(data, source_page)
            raw_text = json.dumps({
                "source_page": source_page,
                "metadata": metadata,
                "weekly_schedule": payload.get("weekly_schedule", []),
            }, ensure_ascii=False)
            with SessionLocal() as session:
                _store_table(
                    session, document_id, source_page, table_index, metadata, confidence,
                    raw_text[:100000], checked,
                    [*table.get("warnings", []), *validation_warnings, *warnings],
                    source_bbox, page_size,
                )
                session.commit()
            saved_tables += 1
        except (TableValidationError, ValueError) as error:
            warnings.append(f"Timetable {table_index} needs manual review: {error}")
    with SessionLocal() as session:
        session.query(UploadedDocument).filter_by(id=document_id).update({"page_count": _pdf_page_count(data)})
        doc = session.get(UploadedDocument, document_id)
        if doc:
            doc.status = "review" if saved_tables else "failed"
            doc.error_message = None if saved_tables else (
                "Sarvam did not return a usable timetable for this PDF."
            )
            doc.processing_warnings = warnings
            doc.updated_at = now_utc()
            session.commit()
    return saved_tables


async def process_document(document_id: str) -> None:
    with SessionLocal() as session:
        document = session.get(UploadedDocument, document_id)
        if document is None:
            return
        path = Path(document.file_path)
        filename = document.filename or "timetable.pdf"
        session.query(UploadedDocument).filter_by(id=document_id).update({"status": "processing", "updated_at": now_utc()})
        session.commit()
    try:
        data = path.read_bytes()
        extraction = await extract_documents_async([(filename, data, "application/pdf")])
        warnings: list[str] = []
        if extraction.status == "partially_completed":
            warnings.append("Sarvam completed this document with partial results. Review every table carefully.")
        store_sarvam_payload(document_id, data, extraction.data, warnings)
    except Exception as error:
        with SessionLocal() as session:
            document = session.get(UploadedDocument, document_id)
            if document:
                document.status = "failed"
                document.error_message = str(error)[:1000]
                document.updated_at = now_utc()
                session.commit()
