import base64
import re
import time
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import BaseModel, TypeAdapter, ValidationError

from .archive_api import mark_interrupted_documents_failed, router as archive_router
from .config import FRONTEND_ORIGIN, MAX_IMAGE_PIXELS, MAX_UPLOAD_BYTES
from .crop import (
    CropDetectionError,
    DecodedUpload,
    DiscoveredPage,
    decode_upload,
    detect_timetable_crop,
    encode_preview,
    find_pdf_timetable_pages,
    is_pdf,
)
from .grid import GridDetectionError, analyze_table_grid
from .sarvam_client import SarvamError, extract_documents_async, sarvam_status
from .sarvam_mapping import _add_geometry, build_timetables
from .validation import TableValidationError, validate_and_complete_table


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mark_interrupted_documents_failed()
    yield


app = FastAPI(title="Timetable Extractor API", version="3.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in FRONTEND_ORIGIN.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(archive_router)


class Cell(BaseModel):
    row: int
    column: int
    rowspan: int = 1
    colspan: int = 1
    text: str = ""


class Table(BaseModel):
    row_count: int
    column_count: int
    column_widths: list[int] | None = None
    row_heights: list[int] | None = None
    cells: list[Cell]
    academic_year: str | None = None
    class_name: str | None = None
    stream: str | None = None
    section: str | None = None
    semester: str | None = None
    source_page: int | None = None


class ExtractionTarget(BaseModel):
    id: str | None = None
    page: int | None = None
    semester: str | None = None


class ExportRequest(BaseModel):
    tables: list[Table]


MAX_CONSTRAINT_LENGTH = 80
EXTRACTION_TARGETS = TypeAdapter(list[ExtractionTarget])


def _clean_constraint(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if len(cleaned) > MAX_CONSTRAINT_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"The {label} is too long. Maximum length is {MAX_CONSTRAINT_LENGTH} characters.",
        )
    return cleaned or None


def _read_constraints(class_name: str | None, stream: str | None, section: str | None) -> dict:
    return {
        "class_name": _clean_constraint(class_name, "class"),
        "stream": _clean_constraint(stream, "stream"),
        "section": _clean_constraint(section, "section"),
    }


def _error_message(error: Exception) -> str:
    if isinstance(error, TableValidationError):
        return " ".join([error.message, *error.errors])
    return str(error)


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large. Maximum upload size is 20 MB.")
    if not data:
        raise HTTPException(status_code=400, detail="Choose an image or PDF first.")
    return data


def _image_from_upload(data: bytes, page: int | None = None) -> DecodedUpload:
    try:
        decoded = decode_upload(data, page)
    except CropDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if decoded.image.shape[0] * decoded.image.shape[1] > MAX_IMAGE_PIXELS:
        raise HTTPException(status_code=413, detail="Image dimensions are too large. Maximum is 40 megapixels.")
    return decoded


def _sarvam_upload(
    data: bytes, filename: str, mime: str | None, page: int | None
) -> tuple[list[tuple[str, bytes, str]], int | None]:
    """Send the selected PDF page (or the uploaded image) to Sarvam."""
    if page is not None and is_pdf(data):
        decoded = _image_from_upload(data, page)
        success, encoded = cv2.imencode(".png", decoded.image)
        if not success:
            raise SarvamError("The selected PDF page could not be prepared for Sarvam.")
        name = f"{Path(filename or 'timetable').stem}_page_{decoded.page}.png"
        return [(name, encoded.tobytes(), "image/png")], decoded.page
    return [(filename or "timetable", data, mime or "application/octet-stream")], page


async def _extract_table(
    data: bytes,
    filename: str,
    mime: str | None,
    page: int | None,
    constraints: dict,
    semester: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract one timetable through Sarvam and map its JSON to an editable grid."""
    files, selected_page = _sarvam_upload(data, filename, mime, page)
    extraction = await extract_documents_async(files)
    warnings: list[str] = []
    if extraction.status == "partially_completed":
        warnings.append("Sarvam completed this extraction with partial results. Review every cell.")
    payload = extraction.data
    if not isinstance(payload, dict):
        raise SarvamError("Sarvam did not return a JSON object for this upload.")
    tables = build_timetables(payload, warnings)
    if not tables:
        raise SarvamError("Sarvam did not return a usable timetable for this upload.")
    checked, validation_warnings = validate_and_complete_table(tables[0])
    checked.update({key: value for key, value in tables[0].items() if key not in checked})
    _add_geometry(checked)
    for key, value in constraints.items():
        if value:
            checked[key] = value
    if semester:
        checked["semester"] = semester
    checked["source_page"] = selected_page or checked.get("source_page")
    warnings.extend(validation_warnings)
    return checked, {"valid": True, "errors": [], "warnings": warnings}


def _fill_table_sheet(sheet: Worksheet, checked: dict[str, Any]) -> None:
    thin = Side(style="thin", color="536273")
    for row in range(checked["row_count"]):
        sheet.row_dimensions[row + 1].height = max(12, checked["row_heights"][row] * 0.75)
        for column in range(checked["column_count"]):
            cell = sheet.cell(row + 1, column + 1)
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.font = Font(name="Aptos", size=11)
    for column, pixel_width in enumerate(checked["column_widths"], start=1):
        sheet.column_dimensions[sheet.cell(1, column).column_letter].width = max(3, pixel_width / 7)
    for item in checked["cells"]:
        row, column = item["row"] + 1, item["column"] + 1
        sheet.cell(row, column).value = item["text"]
        if item["rowspan"] > 1 or item["colspan"] > 1:
            sheet.merge_cells(
                start_row=row,
                start_column=column,
                end_row=row + item["rowspan"] - 1,
                end_column=column + item["colspan"] - 1,
            )


_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _sheet_title(value: str | None, fallback: str, used: set[str]) -> str:
    base = _INVALID_SHEET_CHARS.sub(" ", value or "").strip(" '")[:31] or fallback[:31]
    title = base
    suffix = 2
    while title in used:
        tail = f" ({suffix})"
        title = f"{base[:31 - len(tail)]}{tail}"
        suffix += 1
    used.add(title)
    return title


def _filename_parts(parts: list[str | None]) -> list[str]:
    return [
        cleaned
        for part in parts
        if part
        if (cleaned := re.sub(r"[^A-Za-z0-9]+", "-", part).strip("-"))
    ]


def _workbook_response(workbook: Workbook, filename: str) -> StreamingResponse:
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@app.get("/health", include_in_schema=False)
@app.get("/api/health")
async def health() -> dict:
    return await sarvam_status()


@app.get("/v1/models", include_in_schema=False)
async def models() -> dict:
    """Minimal OpenAI-compatible listing for clients that probe for models.

    Sarvam doc AI is an extraction API, not a chat model; this entry only tells
    such clients which provider is configured. No local models are exposed.
    """
    status = await sarvam_status()
    return {
        "object": "list",
        "data": [{
            "id": "sarvam-doc-ai",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "sarvam",
            "configured": status["configured"],
        }],
    }


@app.post("/api/discover")
async def discover(
    file: UploadFile = File(...),
    class_name: str | None = Form(None),
    stream: str | None = Form(None),
    section: str | None = Form(None),
) -> dict:
    """Find every ruled timetable in an uploaded image or PDF."""
    constraints = _read_constraints(class_name, stream, section)
    data = await _read_upload(file)
    try:
        if is_pdf(data):
            scan = find_pdf_timetable_pages(data)
            found = scan.pages
            page_count: int | None = scan.page_count
            scanned_pages = scan.scanned_pages
        else:
            decoded = _image_from_upload(data)
            crop = detect_timetable_crop(decoded.image)
            found = [DiscoveredPage(
                page=None,
                source_png=encode_preview(decoded.image),
                crop_png=encode_preview(crop.image),
                crop={"x": crop.x, "y": crop.y, "width": crop.width, "height": crop.height},
                original={"width": crop.original_width, "height": crop.original_height},
                text="",
            )]
            page_count = None
            scanned_pages = 1
    except CropDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    candidates = []
    for item in found:
        candidates.append({
            "page": item.page,
            "semester_guess": None,
            "semester_confidence": "sarvam",
            "crop_png_base64": base64.b64encode(item.crop_png).decode("ascii"),
            "source_png_base64": base64.b64encode(item.source_png).decode("ascii"),
            "crop": item.crop,
            "original": item.original,
        })
    return {
        "is_pdf": is_pdf(data),
        "page_count": page_count,
        "scanned_pages": scanned_pages,
        "timetables": candidates,
        "constraints": constraints,
    }


@app.post("/api/preview")
async def preview(
    file: UploadFile = File(...),
    class_name: str | None = Form(None),
    stream: str | None = Form(None),
    section: str | None = Form(None),
    page: int | None = Form(None),
) -> dict:
    constraints = _read_constraints(class_name, stream, section)
    data = await _read_upload(file)
    decoded = _image_from_upload(data, page)
    try:
        crop = detect_timetable_crop(decoded.image)
        grid = analyze_table_grid(crop.image)
    except CropDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except GridDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "crop_png_base64": base64.b64encode(encode_preview(crop.image, 2200)).decode("ascii"),
        "crop": {"x": crop.x, "y": crop.y, "width": crop.width, "height": crop.height},
        "original": {"width": crop.original_width, "height": crop.original_height},
        "grid": {
            "row_count": grid.row_count,
            "column_count": grid.column_count,
            "cell_count": len(grid.cells),
            "width": grid.image.shape[1],
            "height": grid.image.shape[0],
            "column_widths": grid.column_widths,
            "row_heights": grid.row_heights,
        },
        "constraints": constraints,
        "source_page": decoded.page,
        "source_page_count": decoded.page_count,
        "source_png_base64": (
            base64.b64encode(decoded.source_png).decode("ascii") if decoded.source_png else None
        ),
    }


@app.post("/api/extract")
async def extract(
    file: UploadFile = File(...),
    class_name: str | None = Form(None),
    stream: str | None = Form(None),
    section: str | None = Form(None),
    page: int | None = Form(None),
    semester: str | None = Form(None),
) -> dict:
    constraints = _read_constraints(class_name, stream, section)
    cleaned_semester = _clean_constraint(semester, "semester")
    data = await _read_upload(file)
    if not is_pdf(data):
        _image_from_upload(data)
    try:
        table, validation = await _extract_table(
            data, file.filename or "timetable", file.content_type, page, constraints, cleaned_semester
        )
    except CropDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except TableValidationError as error:
        raise HTTPException(status_code=422, detail={"message": error.message, "errors": error.errors}) from error
    except SarvamError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"table": table, "validation": validation}


@app.post("/api/extract-many")
async def extract_many(
    file: UploadFile = File(...),
    targets: str = Form(...),
    class_name: str | None = Form(None),
    stream: str | None = Form(None),
    section: str | None = Form(None),
) -> dict:
    """Extract several chosen pages from one upload; a bad page does not block the others."""
    constraints = _read_constraints(class_name, stream, section)
    try:
        parsed_targets = EXTRACTION_TARGETS.validate_json(targets)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=f"Invalid extraction targets: {error}") from error
    if not parsed_targets:
        return {"tables": [], "failures": []}

    data = await _read_upload(file)
    tables: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for target in parsed_targets:
        cleaned_semester = _clean_constraint(target.semester, "semester")
        try:
            table, validation = await _extract_table(
                data, file.filename or "timetable", file.content_type, target.page,
                constraints, cleaned_semester,
            )
            tables.append({
                "id": target.id,
                "page": table.get("source_page"),
                "semester": cleaned_semester,
                "table": table,
                "validation": validation,
            })
        except (CropDetectionError, GridDetectionError, TableValidationError, SarvamError) as error:
            failures.append({
                "id": target.id,
                "page": target.page,
                "message": _error_message(error),
            })
    return {"tables": tables, "failures": failures}


@app.post("/api/export")
async def export(table: Table) -> StreamingResponse:
    raw = table.model_dump()
    try:
        checked, _ = validate_and_complete_table(raw)
    except TableValidationError as error:
        raise HTTPException(status_code=422, detail={"message": error.message, "errors": error.errors}) from error

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Timetable"
    _fill_table_sheet(sheet, checked)
    details = workbook.create_sheet("Details")
    details["A1"] = "Timetable details"
    details["A1"].font = Font(name="Aptos", size=13, bold=True)
    for index, (label, value) in enumerate(
        (("Class", table.class_name), ("Stream", table.stream), ("Section", table.section)),
        start=3,
    ):
        details.cell(index, 1, label).font = Font(name="Aptos", size=11, bold=True)
        details.cell(index, 2, value or "")
    details.column_dimensions["A"].width = 14
    details.column_dimensions["B"].width = 32
    parts = _filename_parts([table.class_name, table.stream, table.section])
    filename = f"timetable_{'_'.join(parts)}.xlsx" if parts else "timetable.xlsx"
    return _workbook_response(workbook, filename)


@app.post("/api/export-all")
async def export_all(payload: ExportRequest) -> StreamingResponse:
    if not payload.tables:
        raise HTTPException(status_code=422, detail="Choose at least one timetable to export.")

    workbook = Workbook()
    workbook.remove(workbook.active)
    used_titles = {"Details"}
    details_rows: list[list[Any]] = []
    for index, table in enumerate(payload.tables):
        try:
            checked, _ = validate_and_complete_table(table.model_dump())
        except TableValidationError as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"Timetable {index + 1} failed validation.",
                    "errors": [error.message, *error.errors],
                },
            ) from error
        fallback = f"Timetable {index + 1}"
        title = _sheet_title(table.semester or (f"Page {table.source_page}" if table.source_page else None), fallback, used_titles)
        sheet = workbook.create_sheet(title)
        _fill_table_sheet(sheet, checked)
        details_rows.append([
            table.semester or fallback,
            table.class_name or "",
            table.stream or "",
            table.section or "",
            table.source_page or "",
            checked["row_count"],
            checked["column_count"],
        ])

    details = workbook.create_sheet("Details")
    headers = ["Semester", "Class", "Stream", "Section", "Source page", "Rows", "Columns"]
    for column, label in enumerate(headers, start=1):
        cell = details.cell(1, column, label)
        cell.font = Font(name="Aptos", size=11, bold=True)
    for row in details_rows:
        details.append(row)
    for column, width in zip("ABCDEFG", (30, 16, 20, 14, 13, 9, 10)):
        details.column_dimensions[column].width = width

    parts = _filename_parts([
        payload.tables[0].class_name,
        payload.tables[0].stream,
        payload.tables[0].section,
    ])
    filename = f"timetables_{'_'.join(parts)}.xlsx" if parts else "timetables.xlsx"
    return _workbook_response(workbook, filename)
