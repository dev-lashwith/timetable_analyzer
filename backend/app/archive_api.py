import asyncio
import hashlib
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import MAX_UPLOAD_BYTES, STORAGE_DIR
from .db import SessionLocal
from .metadata import normalize_label
from .models import (
    AcademicYear, ClassGroup, Faculty, FacultyAllocation, Room, Semester, SharedCellText, Subject,
    TimetableCell, TimetableRecord, UploadedDocument, now_utc,
)
from .normalization import DAY_NAMES, TIME_RANGE, normalized_cell_text
from .processing import _get_class_group, _get_or_create, _get_slot, _store_allocations

WEEKDAYS = set(DAY_NAMES.values())


router = APIRouter(prefix="/api")
_jobs: set[asyncio.Task] = set()


class ReviewPayload(BaseModel):
    academic_year: str | None = Field(default=None, max_length=80)
    semester: str | None = Field(default=None, max_length=80)
    class_name: str | None = Field(default=None, max_length=80)
    section: str | None = Field(default=None, max_length=80)
    stream: str | None = Field(default=None, max_length=80)
    room: str | None = Field(default=None, max_length=100)
    table_type: str | None = Field(default=None, pattern="^(timetable|faculty_allocation|other)$")
    cells: list[dict] | None = None


def _entity_values(session, record: TimetableRecord) -> dict:
    return {
        "academic_year": session.get(AcademicYear, record.academic_year_id).label if record.academic_year_id else None,
        "semester": session.get(Semester, record.semester_id).label if record.semester_id else None,
        "class_name": session.get(ClassGroup, record.class_group_id).name if record.class_group_id else None,
        "section": session.get(ClassGroup, record.class_group_id).section if record.class_group_id else None,
        "stream": session.get(ClassGroup, record.class_group_id).stream if record.class_group_id else None,
        "room": session.get(Room, record.room_id).label if record.room_id else None,
    }


def _record_json(session, record: TimetableRecord) -> dict:
    values = _entity_values(session, record)
    cells = session.scalars(select(TimetableCell).where(TimetableCell.timetable_id == record.id).order_by(
        TimetableCell.row_index, TimetableCell.column_index
    )).all()
    allocations = session.scalars(select(FacultyAllocation).where(
        FacultyAllocation.timetable_id == record.id
    ).order_by(FacultyAllocation.row_index)).all()
    return {
        "id": record.id, "document_id": record.document_id, "source_page": record.source_page,
        "table_index": record.table_index, "table_type": record.table_type, "status": record.status,
        **values,
        "entity_ids": {"academic_year": record.academic_year_id, "semester": record.semester_id,
                       "class": record.class_group_id, "room": record.room_id},
        "row_count": record.row_count, "column_count": record.column_count,
        "column_widths": record.column_widths, "row_heights": record.row_heights,
        "source_bbox": record.source_bbox, "page_size": record.page_size,
        "raw_page_text": record.raw_page_text, "metadata_confidence": record.metadata_confidence,
        "warnings": record.warnings,
        "cells": [{"row": c.row_index, "column": c.column_index, "rowspan": c.rowspan,
                   "colspan": c.colspan, "text": c.raw_text, "raw_text": c.raw_text,
                   "normalized_text": c.normalized_text,
                   "shared_text_id": c.shared_text_id, "time_slot_id": c.time_slot_id,
                   "coordinates": {"grid_bbox": {"x": c.x, "y": c.y, "width": c.width, "height": c.height,
                                                  "coordinate_space": "rectified_table_grid_pixels"},
                                   "source_page_bbox": c.source_bbox}}
                  for c in cells],
        "faculty_allocations": [{
            "row": item.row_index,
            "faculty": session.get(Faculty, item.faculty_id).name if item.faculty_id else None,
            "subject": session.get(Subject, item.subject_id).name if item.subject_id else None,
            "raw_row": item.raw_row,
        } for item in allocations],
    }


def _update_document_status(session, document_id: str) -> None:
    document = session.get(UploadedDocument, document_id)
    if not document:
        return
    records = session.scalars(select(TimetableRecord).where(TimetableRecord.document_id == document_id)).all()
    if records and all(record.status == "published" for record in records):
        document.status = "published"
    elif records and all(record.status in {"verified", "published"} for record in records):
        document.status = "verified"
    elif records:
        document.status = "review"
    document.updated_at = now_utc()


@router.post("/documents", status_code=202)
async def upload_document(file: UploadFile = File(...)) -> dict:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large. Maximum upload size is 20 MB.")
    if not data or not data.lstrip().startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="Upload a valid PDF to the timetable archive.")
    document_id = str(uuid4())
    safe_name = Path(file.filename or "department-timetable.pdf").name
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = STORAGE_DIR / f"{document_id}.pdf"
    target.write_bytes(data)
    document = UploadedDocument(
        id=document_id, filename=safe_name[:255], content_type=file.content_type or "application/pdf",
        file_path=str(target), size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), status="queued",
    )
    with SessionLocal() as session:
        session.add(document)
        session.commit()
    from .processing import process_document
    task = asyncio.create_task(process_document(document_id))
    _jobs.add(task)
    task.add_done_callback(_jobs.discard)
    return {"id": document_id, "filename": safe_name, "status": "queued"}


@router.get("/documents")
def list_documents() -> list[dict]:
    with SessionLocal() as session:
        docs = session.scalars(select(UploadedDocument).order_by(UploadedDocument.created_at.desc())).all()
        result = []
        for document in docs:
            records = session.scalars(select(TimetableRecord).where(TimetableRecord.document_id == document.id)).all()
            result.append({"id": document.id, "filename": document.filename, "status": document.status,
                           "page_count": document.page_count, "table_count": len(records),
                           "error_message": document.error_message, "processing_warnings": document.processing_warnings,
                           "created_at": document.created_at.isoformat()})
        return result


@router.get("/documents/{document_id}")
def get_document(document_id: str) -> dict:
    with SessionLocal() as session:
        document = session.get(UploadedDocument, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found.")
        records = session.scalars(select(TimetableRecord).where(TimetableRecord.document_id == document_id).order_by(
            TimetableRecord.source_page, TimetableRecord.table_index
        )).all()
        return {"id": document.id, "filename": document.filename, "status": document.status,
                "page_count": document.page_count, "size_bytes": document.size_bytes,
                "processing_warnings": document.processing_warnings,
                "error_message": document.error_message, "tables": [_record_json(session, row) for row in records]}


@router.get("/documents/{document_id}/original")
def get_original(document_id: str) -> FileResponse:
    with SessionLocal() as session:
        document = session.get(UploadedDocument, document_id)
        if not document or not Path(document.file_path).is_file():
            raise HTTPException(status_code=404, detail="Original PDF not found.")
        return FileResponse(document.file_path, media_type="application/pdf", filename=document.filename)


@router.get("/documents/{document_id}/json")
def download_document_json(document_id: str) -> JSONResponse:
    with SessionLocal() as session:
        document = session.get(UploadedDocument, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found.")
        records = session.scalars(select(TimetableRecord).where(TimetableRecord.document_id == document_id).order_by(
            TimetableRecord.source_page, TimetableRecord.table_index
        )).all()
        payload = {"document": {"id": document.id, "filename": document.filename,
                                "sha256": document.sha256, "status": document.status,
                                "page_count": document.page_count},
                   "timetables": [_record_json(session, row) for row in records]}
        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(document.filename).stem) + ".json"
        return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/options")
def timetable_options(
    semester_id: int | None = None,
    class_id: int | None = None,
    academic_year_id: int | None = None,
) -> dict:
    with SessionLocal() as session:
        semesters = session.scalars(select(Semester).join(TimetableRecord, TimetableRecord.semester_id == Semester.id)
                                    .where(TimetableRecord.status == "published", TimetableRecord.table_type == "timetable")
                                    .distinct().order_by(Semester.label)).all()
        class_query = select(ClassGroup).join(TimetableRecord, TimetableRecord.class_group_id == ClassGroup.id).where(TimetableRecord.status == "published", TimetableRecord.table_type == "timetable")
        year_query = select(AcademicYear).join(TimetableRecord, TimetableRecord.academic_year_id == AcademicYear.id).where(TimetableRecord.status == "published", TimetableRecord.table_type == "timetable")
        room_query = select(Room).join(TimetableRecord, TimetableRecord.room_id == Room.id).where(TimetableRecord.status == "published", TimetableRecord.table_type == "timetable")
        if semester_id:
            class_query = class_query.where(TimetableRecord.semester_id == semester_id)
            year_query = year_query.where(TimetableRecord.semester_id == semester_id)
            room_query = room_query.where(TimetableRecord.semester_id == semester_id)
        if class_id:
            year_query = year_query.where(TimetableRecord.class_group_id == class_id)
            room_query = room_query.where(TimetableRecord.class_group_id == class_id)
        if academic_year_id:
            room_query = room_query.where(TimetableRecord.academic_year_id == academic_year_id)
        classes = session.scalars(class_query.distinct().order_by(ClassGroup.name, ClassGroup.section)).all()
        years = session.scalars(year_query.distinct().order_by(AcademicYear.label)).all()
        rooms = session.scalars(room_query.distinct().order_by(Room.label)).all()
        return {
            "semesters": [{"id": x.id, "label": x.label} for x in semesters],
            "classes": [{"id": x.id, "label": " ".join(part for part in (x.name, x.section) if part), "name": x.name, "section": x.section} for x in classes],
            "academic_years": [{"id": x.id, "label": x.label} for x in years],
            "rooms": [{"id": x.id, "label": x.label} for x in rooms],
        }


@router.get("/timetables/search")
def search_timetables(semester_id: int, class_id: int, academic_year_id: int, room_id: int) -> list[dict]:
    with SessionLocal() as session:
        rows = session.scalars(select(TimetableRecord).where(
            TimetableRecord.status == "published", TimetableRecord.table_type == "timetable",
            TimetableRecord.semester_id == semester_id, TimetableRecord.class_group_id == class_id,
            TimetableRecord.academic_year_id == academic_year_id, TimetableRecord.room_id == room_id,
        ).order_by(TimetableRecord.source_page)).all()
        return [{"id": row.id, "source_page": row.source_page, "table_type": row.table_type,
                 "semester": session.get(Semester, row.semester_id).label,
                 "academic_year": session.get(AcademicYear, row.academic_year_id).label,
                 "class_name": session.get(ClassGroup, row.class_group_id).name,
                 "section": session.get(ClassGroup, row.class_group_id).section,
                 "room": session.get(Room, row.room_id).label} for row in rows]


@router.get("/timetables/{timetable_id}")
def get_timetable(timetable_id: str) -> dict:
    with SessionLocal() as session:
        record = session.get(TimetableRecord, timetable_id)
        if not record or record.status != "published":
            raise HTTPException(status_code=404, detail="Published timetable not found.")
        return _record_json(session, record)


@router.patch("/timetables/{timetable_id}")
def update_timetable(timetable_id: str, payload: ReviewPayload) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    with SessionLocal() as session:
        record = session.get(TimetableRecord, timetable_id)
        if not record:
            raise HTTPException(status_code=404, detail="Timetable not found.")
        values = _entity_values(session, record)
        values.update({key: normalize_label(value) or None for key, value in changes.items() if key in values})
        year = _get_or_create(session, AcademicYear, "normalized_label", "label", values["academic_year"])
        semester = _get_or_create(session, Semester, "normalized_label", "label", values["semester"])
        class_group = _get_class_group(session, values)
        room = _get_or_create(session, Room, "normalized_label", "label", values["room"])
        record.academic_year_id = year.id if year else None
        record.semester_id = semester.id if semester else None
        record.class_group_id = class_group.id if class_group else None
        record.room_id = room.id if room else None
        if "table_type" in changes:
            record.table_type = changes["table_type"] or record.table_type
            session.query(FacultyAllocation).filter_by(timetable_id=timetable_id).delete(synchronize_session=False)
        if "cells" in changes and changes["cells"] is not None:
            cell_map = {(cell.row_index, cell.column_index): cell for cell in session.scalars(
                select(TimetableCell).where(TimetableCell.timetable_id == timetable_id)
            ).all()}
            for item in changes["cells"]:
                key = (item.get("row"), item.get("column"))
                if key not in cell_map or not isinstance(item.get("text"), str):
                    continue
                cell_map[key].raw_text = item["text"]
                cell_map[key].normalized_text = normalized_cell_text(item["text"])
                normalized = cell_map[key].normalized_text
                shared = session.scalar(select(SharedCellText).where(SharedCellText.normalized_text == normalized)) if normalized else None
                if normalized and shared is None:
                    shared = SharedCellText(normalized_text=normalized, display_text=item["text"])
                    session.add(shared)
                    session.flush()
                cell_map[key].shared_text_id = shared.id if shared else None
                slot = _get_slot(session, item["text"]) if TIME_RANGE.fullmatch(item["text"].strip()) or normalized in WEEKDAYS else None
                cell_map[key].time_slot_id = slot.id if slot else None
        if "table_type" in changes and record.table_type == "faculty_allocation":
            source_cells = session.scalars(select(TimetableCell).where(TimetableCell.timetable_id == timetable_id)).all()
            rows: dict[int, list[dict]] = {}
            for cell in source_cells:
                rows.setdefault(cell.row_index, []).append({"row": cell.row_index, "column": cell.column_index, "text": cell.raw_text})
            _store_allocations(session, timetable_id, rows)
        record.metadata_confidence = {**(record.metadata_confidence or {}), "reviewed": "manual"}
        if record.status in {"verified", "published"}:
            record.status = "review"
            record.verified_at = None
            record.published_at = None
        _update_document_status(session, record.document_id)
        session.commit()
        return _record_json(session, record)


@router.post("/timetables/{timetable_id}/verify")
def verify_timetable(timetable_id: str) -> dict:
    with SessionLocal() as session:
        record = session.get(TimetableRecord, timetable_id)
        if not record:
            raise HTTPException(status_code=404, detail="Timetable not found.")
        class_group = session.get(ClassGroup, record.class_group_id) if record.class_group_id else None
        if not (record.academic_year_id and record.semester_id and class_group and class_group.name.strip() and record.room_id):
            raise HTTPException(status_code=422, detail="Add the academic year, semester, class, and room before verifying.")
        record.status = "verified"
        record.verified_at = now_utc()
        _update_document_status(session, record.document_id)
        session.commit()
        return _record_json(session, record)


@router.post("/timetables/{timetable_id}/publish")
def publish_timetable(timetable_id: str) -> dict:
    with SessionLocal() as session:
        record = session.get(TimetableRecord, timetable_id)
        if not record:
            raise HTTPException(status_code=404, detail="Timetable not found.")
        if record.status != "verified":
            raise HTTPException(status_code=409, detail="Verify the timetable before publishing it.")
        record.status = "published"
        record.published_at = now_utc()
        _update_document_status(session, record.document_id)
        session.commit()
        return _record_json(session, record)
