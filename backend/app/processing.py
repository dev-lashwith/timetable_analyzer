import asyncio
import json
import re
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from sqlalchemy import select

from .config import MAX_PDF_PAGES, PDF_RENDER_DPI
from .crop import CropDetectionError, _render_pdf_page, detect_ruled_table_crops, is_pdf
from .db import SessionLocal
from .grid import GridDetectionError, analyze_table_grid
from .metadata import merge_metadata, metadata_from_text
from .models import (
    AcademicYear, ClassGroup, Faculty, FacultyAllocation, Room, Semester, SharedCellText,
    Subject, TimeSlot, TimetableCell, TimetableRecord, UploadedDocument, now_utc,
)
from .normalization import DAY_NAMES, TIME_RANGE, canonical_clock, normalized_cell_text
from .ollama_client import OllamaError, detect_page_metadata, extract_cell_texts
from .validation import apply_cell_texts, validate_and_complete_table


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


def _classify_table(cells: list[dict], page_text: str) -> str:
    visible = " ".join([page_text, *(cell["text"] for cell in cells)]).casefold()
    if re.search(r"faculty\s+allocation|staff\s+allocation|faculty\s+workload", visible):
        return "faculty_allocation"
    return "timetable"


def _store_table(session, document_id: str, page_number: int, table_index: int, crop, metadata: dict,
                 confidence: dict, page_text: str, classification_text: str, grid, table_data: dict,
                 warnings: list[str]) -> TimetableRecord:
    academic_year = _get_or_create(session, AcademicYear, "normalized_label", "label", metadata.get("academic_year"))
    semester = _get_or_create(session, Semester, "normalized_label", "label", metadata.get("semester"))
    class_group = _get_class_group(session, metadata)
    room = _get_or_create(session, Room, "normalized_label", "label", metadata.get("room"))
    cells = table_data["cells"]
    record = TimetableRecord(
        document_id=document_id, source_page=page_number, table_index=table_index,
        table_type=_classify_table(cells, classification_text), status="review",
        academic_year_id=academic_year.id if academic_year else None,
        semester_id=semester.id if semester else None,
        class_group_id=class_group.id if class_group else None,
        room_id=room.id if room else None,
        row_count=table_data["row_count"], column_count=table_data["column_count"],
        column_widths=table_data["column_widths"], row_heights=table_data["row_heights"],
        source_bbox={"x": crop.x, "y": crop.y, "width": crop.width, "height": crop.height},
        page_size={"width": crop.original_width, "height": crop.original_height},
        raw_page_text=page_text, metadata_confidence=confidence,
        warnings=warnings,
    )
    session.add(record)
    session.flush()
    cell_rows: dict[int, list[dict]] = {}
    for cell, grid_cell in zip(cells, grid.cells):
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
        corners = np.array([[[grid_cell.x, grid_cell.y],
                             [grid_cell.x + grid_cell.width, grid_cell.y],
                             [grid_cell.x, grid_cell.y + grid_cell.height],
                             [grid_cell.x + grid_cell.width, grid_cell.y + grid_cell.height]]], dtype=np.float32)
        source_corners = cv2.perspectiveTransform(corners, grid.grid_to_source)[0]
        source_x = int(round(float(source_corners[:, 0].min())))
        source_y = int(round(float(source_corners[:, 1].min())))
        source_x2 = int(round(float(source_corners[:, 0].max())))
        source_y2 = int(round(float(source_corners[:, 1].max())))
        source_bbox = {"x": crop.x + source_x, "y": crop.y + source_y,
                       "width": source_x2 - source_x, "height": source_y2 - source_y,
                       "coordinate_space": "rendered_page_pixels"}
        session.add(TimetableCell(
            timetable_id=record.id, row_index=cell["row"], column_index=cell["column"],
            rowspan=cell["rowspan"], colspan=cell["colspan"], raw_text=raw_text,
            normalized_text=normalized, x=grid_cell.x, y=grid_cell.y,
            width=grid_cell.width, height=grid_cell.height, source_bbox=source_bbox,
            shared_text_id=shared.id if shared else None, time_slot_id=slot.id if slot else None,
        ))
        cell_rows.setdefault(cell["row"], []).append(cell)
    if record.table_type == "faculty_allocation":
        _store_allocations(session, record.id, cell_rows)
    return record


def _store_allocations(session, timetable_id: str, rows: dict[int, list[dict]]) -> None:
    ordered = [sorted(items, key=lambda item: item["column"]) for _, items in sorted(rows.items())]
    if not ordered:
        return
    header = [item["text"].casefold() for item in ordered[0]]
    faculty_column = next((i for i, value in enumerate(header) if "faculty" in value or "teacher" in value or "staff" in value), None)
    subject_column = next((i for i, value in enumerate(header) if "subject" in value or "course" in value), None)
    for row_number, row in enumerate(ordered[1:], start=1):
        values = [item["text"].strip() for item in row]
        faculty_name = values[faculty_column] if faculty_column is not None and faculty_column < len(values) else None
        subject_name = values[subject_column] if subject_column is not None and subject_column < len(values) else None
        faculty = _get_or_create(session, Faculty, "normalized_name", "name", faculty_name)
        subject = _get_or_create(session, Subject, "normalized_name", "name", subject_name)
        if any((faculty, subject, *values)):
            session.add(FacultyAllocation(timetable_id=timetable_id, row_index=row_number,
                faculty_id=faculty.id if faculty else None, subject_id=subject.id if subject else None, raw_row=values))


async def process_document(document_id: str) -> None:
    with SessionLocal() as session:
        document = session.get(UploadedDocument, document_id)
        if document is None:
            return
        path = Path(document.file_path)
        session.query(UploadedDocument).filter_by(id=document_id).update({"status": "processing", "updated_at": now_utc()})
        session.commit()
    try:
        data = path.read_bytes()
        if not is_pdf(data):
            raise CropDetectionError("The archive workflow currently accepts PDF files.")
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            page_count = pdf.page_count
            scanned = min(page_count, MAX_PDF_PAGES)
            processing_warnings: list[str] = []
            if page_count > scanned:
                processing_warnings.append(f"Only the first {scanned} of {page_count} PDF pages were scanned. Increase MAX_PDF_PAGES to process more.")
            with SessionLocal() as session:
                session.query(UploadedDocument).filter_by(id=document_id).update({"page_count": page_count})
                session.commit()
            saved_tables = 0
            for index in range(scanned):
                pdf_page = pdf.load_page(index)
                page_text = pdf_page.get_text("text") or ""
                image = await asyncio.to_thread(_render_pdf_page, pdf_page, PDF_RENDER_DPI / 72)
                crops = await asyncio.to_thread(detect_ruled_table_crops, image)
                if not crops:
                    continue
                text_metadata = metadata_from_text(page_text)
                vision_metadata: dict = {}
                page_warnings: list[str] = []
                try:
                    vision_metadata = await detect_page_metadata(image)
                except OllamaError as error:
                    page_warnings.append(f"Automatic visual metadata detection needs review: {error}")
                    processing_warnings.extend(f"Page {index + 1}: {warning}" for warning in page_warnings)
                metadata = merge_metadata(text_metadata, vision_metadata)
                confidence = {
                    key: "text" if text_metadata.get(key) else "vision" if vision_metadata.get(key) else "unknown"
                    for key in metadata
                }
                for table_index, crop in enumerate(crops, start=1):
                    try:
                        grid = await asyncio.to_thread(analyze_table_grid, crop.image)
                        transcription = await extract_cell_texts(grid.image, grid.cells)
                        raw = json.loads(transcription)
                        geometry = {
                            "row_count": grid.row_count, "column_count": grid.column_count,
                            "column_widths": grid.column_widths, "row_heights": grid.row_heights,
                            "cells": [{"row": c.row, "column": c.column, "rowspan": c.rowspan,
                                       "colspan": c.colspan, "text": ""} for c in grid.cells],
                        }
                        with_text, text_warnings = apply_cell_texts(geometry, raw)
                        table_data, validation_warnings = validate_and_complete_table(with_text)
                        with SessionLocal() as session:
                            _store_table(session, document_id, index + 1, table_index, crop, metadata,
                                         confidence, page_text, page_text if len(crops) == 1 else "", grid, table_data,
                                         [*page_warnings, *text_warnings, *validation_warnings])
                            session.commit()
                        saved_tables += 1
                    except (GridDetectionError, OllamaError, json.JSONDecodeError, ValueError) as error:
                        warning = f"Table {table_index} on page {index + 1} needs manual review: {error}"
                        page_warnings.append(warning)
                        processing_warnings.append(warning)
            with SessionLocal() as session:
                doc = session.get(UploadedDocument, document_id)
                if doc:
                    doc.status = "review" if saved_tables else "failed"
                    doc.error_message = None if saved_tables else "No readable ruled timetable or faculty allocation table was found."
                    doc.processing_warnings = processing_warnings
                    doc.updated_at = now_utc()
                    session.commit()
    except Exception as error:
        with SessionLocal() as session:
            document = session.get(UploadedDocument, document_id)
            if document:
                document.status = "failed"
                document.error_message = str(error)[:1000]
                document.updated_at = now_utc()
                session.commit()
