from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

import cv2
import pymupdf
from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import MAX_IMAGE_PIXELS, MAX_PDF_PAGES, MAX_UPLOAD_BYTES, OLLAMA_MODEL, PDF_RENDER_DPI, STORAGE_ROOT
from .crop import CropDetectionError, _render_pdf_page, detect_timetable_crop, is_pdf
from .database import database
from .grid import GridDetectionError, analyze_table_grid
from .ollama_client import OllamaError, extract_page_entities
from .page_analysis import analyze_page_layout, normalize_page_extraction
from .processing import extract_table_from_crop
from .validation import TableValidationError, validate_and_complete_table


router = APIRouter(prefix="/api")


class CropCoordinates(BaseModel):
    x: int
    y: int
    width: int
    height: int
    class_name: str | None = None
    stream: str | None = None
    section: str | None = None
    semester: str | None = None
    academic_session: str | None = None
    room: str | None = None


def _metadata(
    class_name: str | None,
    stream: str | None,
    section: str | None,
    semester: str | None,
    academic_session: str | None,
    room: str | None,
) -> dict:
    result = {}
    for key, value, limit in (
        ("class_name", class_name, 80), ("stream", stream, 80), ("section", section, 80),
        ("semester", semester, 40), ("academic_session", academic_session, 80), ("room", room, 80),
    ):
        cleaned = " ".join((value or "").split())
        if len(cleaned) > limit:
            raise HTTPException(status_code=422, detail=f"{key.replace('_', ' ').title()} is too long.")
        result[key] = cleaned or None
    return result


def _metadata_from_payload(value: object, fallback: dict) -> dict:
    if value is None:
        return fallback
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="metadata must be an object.")
    return _metadata(value.get("class_name"), value.get("stream"), value.get("section"),
                     value.get("semester"), value.get("academic_session"), value.get("room"))


def _ensure_timetable(page_id: str, metadata: dict) -> str:
    with database() as connection:
        row = connection.execute("SELECT id FROM timetables WHERE page_id = ?", (page_id,)).fetchone()
        if row:
            timetable_id = row["id"]
            connection.execute(
                "UPDATE timetables SET metadata_json = ? WHERE id = ?",
                (json.dumps(metadata), timetable_id),
            )
            return timetable_id
        timetable_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO timetables(id, page_id, metadata_json) VALUES (?, ?, ?)",
            (timetable_id, page_id, json.dumps(metadata)),
        )
        return timetable_id


def _get_timetable_row(timetable_id: str):
    with database() as connection:
        row = connection.execute(
            """SELECT t.id AS timetable_id, t.page_id, t.metadata_json, p.document_id,
                      p.page_number, p.image_path, p.crop_path, p.crop_json,
                      p.crop_confidence, p.crop_status, p.width, p.height,
                      d.filename, d.storage_dir
               FROM timetables t JOIN pages p ON p.id = t.page_id
               JOIN documents d ON d.id = p.document_id WHERE t.id = ?""",
            (timetable_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Timetable not found.")
    return row


def _latest_version(connection, timetable_id: str, source: str | None = None):
    if source:
        return connection.execute(
            "SELECT * FROM timetable_versions WHERE timetable_id = ? AND source = ? ORDER BY version_number DESC LIMIT 1",
            (timetable_id, source),
        ).fetchone()
    return connection.execute(
        "SELECT * FROM timetable_versions WHERE timetable_id = ? ORDER BY version_number DESC LIMIT 1",
        (timetable_id,),
    ).fetchone()


def _snapshot(timetable_id: str) -> dict:
    row = _get_timetable_row(timetable_id)
    metadata = json.loads(row["metadata_json"])
    with database() as connection:
        latest = _latest_version(connection, timetable_id)
        original = _latest_version(connection, timetable_id, "ai_original")
        extraction = connection.execute(
            "SELECT * FROM page_extractions WHERE timetable_id = ? ORDER BY id DESC LIMIT 1",
            (timetable_id,),
        ).fetchone()
    return {
        "id": timetable_id,
        "metadata": metadata,
        "page": {
            "id": row["page_id"], "document_id": row["document_id"], "document_name": row["filename"],
            "page_number": row["page_number"], "width": row["width"], "height": row["height"],
            "crop": json.loads(row["crop_json"]) if row["crop_json"] else None,
            "crop_confidence": row["crop_confidence"], "crop_status": row["crop_status"],
            "image_url": f"/api/pages/{row['page_id']}/image",
            "crop_url": f"/api/pages/{row['page_id']}/crop" if row["crop_path"] else None,
        },
        "table": json.loads(latest["table_json"]) if latest else None,
        "version": dict(latest) if latest else None,
        "original_extraction": json.loads(original["table_json"]) if original else None,
        "page_extraction": {
            "id": extraction["id"], "model": extraction["model"],
            "ocr": json.loads(extraction["ocr_json"]),
            "data": json.loads(extraction["extraction_json"]),
            "confidence": extraction["confidence"],
            "verification_status": extraction["verification_status"],
            "created_at": extraction["created_at"],
        } if extraction else None,
    }


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    class_name: str | None = Form(None),
    stream: str | None = Form(None),
    section: str | None = Form(None),
    semester: str | None = Form(None),
    academic_session: str | None = Form(None),
    room: str | None = Form(None),
) -> dict:
    metadata = _metadata(class_name, stream, section, semester, academic_session, room)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large. Maximum upload size is 20 MB.")
    if not data or not is_pdf(data):
        raise HTTPException(status_code=415, detail="Upload a valid PDF to save and split its pages.")

    try:
        source_pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception as error:
        raise HTTPException(status_code=422, detail="The uploaded PDF could not be opened.") from error

    document_id = str(uuid.uuid4())
    document_dir = STORAGE_ROOT / document_id
    page_dir, crop_dir = document_dir / "pages", document_dir / "crops"
    page_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)
    original_path = document_dir / "original.pdf"
    original_path.write_bytes(data)
    filename = Path(str(file.filename or "timetable.pdf").replace("\\", "/")).name or "timetable.pdf"
    page_count = source_pdf.page_count
    if source_pdf.is_encrypted:
        source_pdf.close()
        shutil.rmtree(document_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail="Password-protected PDFs are not supported.")
    if not page_count:
        source_pdf.close()
        shutil.rmtree(document_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail="The uploaded PDF has no pages.")
    if page_count > MAX_PDF_PAGES:
        source_pdf.close()
        shutil.rmtree(document_dir, ignore_errors=True)
        raise HTTPException(status_code=413, detail=f"PDF has {page_count} pages; the current limit is {MAX_PDF_PAGES}.")

    page_results: list[dict] = []
    try:
        for index in range(page_count):
            pdf_page = source_pdf.load_page(index)
            image = _render_pdf_page(pdf_page, PDF_RENDER_DPI / 72)
            height, width = image.shape[:2]
            if height * width > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail=f"Rendered page {index + 1} exceeds the 40 megapixel limit.")
            page_id = str(uuid.uuid4())
            image_path = page_dir / f"page_{index + 1:04d}.png"
            if not cv2.imwrite(str(image_path), image):
                raise HTTPException(status_code=500, detail=f"Could not save rendered page {index + 1}.")
            layout = analyze_page_layout(image, pdf_page)
            crop_path = None
            crop_json = None
            crop_confidence = None
            crop_status = "not_found"
            timetable_id = None
            grid_info = None
            try:
                crop = detect_timetable_crop(image, layout["words"])
                crop_path = crop_dir / f"page_{index + 1:04d}.png"
                if not cv2.imwrite(str(crop_path), crop.image):
                    raise HTTPException(status_code=500, detail=f"Could not save page {index + 1}'s crop.")
                crop_json = {"x": crop.x, "y": crop.y, "width": crop.width, "height": crop.height}
                crop_confidence = crop.confidence
                crop_status = "review_required" if crop.review_required else "detected"
                try:
                    grid = analyze_table_grid(crop.image)
                    grid_info = {
                        "row_count": grid.row_count, "column_count": grid.column_count,
                        "cell_count": len(grid.cells), "width": grid.image.shape[1], "height": grid.image.shape[0],
                        "column_widths": grid.column_widths, "row_heights": grid.row_heights,
                    }
                except GridDetectionError:
                    crop_status = "review_required"
            except CropDetectionError:
                pass

            with database() as connection:
                connection.execute(
                    """INSERT INTO documents(id, filename, storage_dir, sha256, page_count)
                       VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
                    (document_id, filename, str(document_dir), hashlib.sha256(data).hexdigest(), page_count),
                ) if index == 0 else None
                connection.execute(
                    """INSERT INTO pages(id, document_id, page_number, image_path, width, height,
                       crop_path, crop_json, crop_confidence, crop_status, ocr_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (page_id, document_id, index + 1, str(image_path), width, height,
                     str(crop_path) if crop_path else None, json.dumps(crop_json) if crop_json else None,
                     crop_confidence, crop_status, json.dumps(layout, ensure_ascii=False)),
                )
            if crop_path:
                timetable_id = _ensure_timetable(page_id, metadata)
            page_results.append({
                "id": page_id, "page_number": index + 1, "width": width, "height": height,
                "crop": crop_json, "crop_confidence": crop_confidence, "crop_status": crop_status,
                "grid": grid_info,
                "image_url": f"/api/pages/{page_id}/image",
                "crop_url": f"/api/pages/{page_id}/crop" if crop_path else None,
                "timetable_id": timetable_id,
            })
    except Exception:
        source_pdf.close()
        with database() as connection:
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        shutil.rmtree(document_dir, ignore_errors=True)
        raise
    finally:
        if not source_pdf.is_closed:
            source_pdf.close()

    return {
        "id": document_id, "filename": filename, "page_count": page_count,
        "original_pdf_stored": True, "pages": page_results,
    }


@router.get("/documents")
async def list_documents() -> dict:
    with database() as connection:
        rows = connection.execute("SELECT id, filename, page_count, uploaded_at FROM documents ORDER BY uploaded_at DESC").fetchall()
    return {"documents": [dict(row) for row in rows]}


@router.get("/timetables")
async def list_timetables() -> dict:
    with database() as connection:
        rows = connection.execute(
            """SELECT t.id, t.metadata_json, d.filename, p.page_number, p.crop_status,
                      p.crop_confidence, p.id AS page_id,
                      (SELECT verification_status FROM timetable_versions v WHERE v.timetable_id = t.id
                       ORDER BY version_number DESC LIMIT 1) AS verification_status
               FROM timetables t JOIN pages p ON p.id = t.page_id
               JOIN documents d ON d.id = p.document_id
               WHERE p.crop_path IS NOT NULL ORDER BY d.uploaded_at DESC, p.page_number"""
        ).fetchall()
    return {"timetables": [
        {"id": row["id"], "metadata": json.loads(row["metadata_json"]), "document_name": row["filename"],
         "page_number": row["page_number"], "page_id": row["page_id"], "crop_status": row["crop_status"],
         "crop_confidence": row["crop_confidence"], "verification_status": row["verification_status"] or "unverified"}
        for row in rows
    ]}


@router.get("/pages/{page_id}/image")
async def get_page_image(page_id: str) -> FileResponse:
    with database() as connection:
        row = connection.execute("SELECT image_path FROM pages WHERE id = ?", (page_id,)).fetchone()
    if not row or not Path(row["image_path"]).is_file():
        raise HTTPException(status_code=404, detail="Page image not found.")
    return FileResponse(row["image_path"], media_type="image/png")


@router.get("/pages/{page_id}/crop")
async def get_page_crop(page_id: str) -> FileResponse:
    with database() as connection:
        row = connection.execute("SELECT crop_path FROM pages WHERE id = ?", (page_id,)).fetchone()
    if not row or not row["crop_path"] or not Path(row["crop_path"]).is_file():
        raise HTTPException(status_code=404, detail="No timetable crop has been saved for this page.")
    return FileResponse(row["crop_path"], media_type="image/png")


@router.post("/pages/{page_id}/crop")
async def save_manual_crop(page_id: str, coordinates: CropCoordinates) -> dict:
    with database() as connection:
        page = connection.execute("SELECT * FROM pages WHERE id = ?", (page_id,)).fetchone()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found.")
    x, y, width, height = coordinates.x, coordinates.y, coordinates.width, coordinates.height
    if x < 0 or y < 0 or width < 40 or height < 40 or x + width > page["width"] or y + height > page["height"]:
        raise HTTPException(status_code=422, detail="Crop coordinates must stay inside the source page and include at least 40 by 40 pixels.")
    if width * height >= page["width"] * page["height"] * 0.99:
        raise HTTPException(status_code=422, detail="Select only the timetable area, leaving some page margin outside the crop.")
    image = cv2.imread(page["image_path"])
    if image is None:
        raise HTTPException(status_code=500, detail="Could not read the saved page image.")
    cropped = image[y : y + height, x : x + width]
    document_dir = Path(page["image_path"]).parent.parent
    crop_path = document_dir / "crops" / f"page_{page['page_number']:04d}_manual.png"
    if not cv2.imwrite(str(crop_path), cropped):
        raise HTTPException(status_code=500, detail="Could not save the manual crop.")
    metadata = _metadata(coordinates.class_name, coordinates.stream, coordinates.section,
                         coordinates.semester, coordinates.academic_session, coordinates.room)
    with database() as connection:
        timetable = connection.execute("SELECT id, metadata_json FROM timetables WHERE page_id = ?", (page_id,)).fetchone()
        if timetable:
            timetable_id = timetable["id"]
            metadata = json.loads(timetable["metadata_json"])
            if any(getattr(coordinates, key) for key in ("class_name", "stream", "section", "semester", "academic_session", "room")):
                metadata = _metadata(coordinates.class_name, coordinates.stream, coordinates.section,
                                     coordinates.semester, coordinates.academic_session, coordinates.room)
                connection.execute("UPDATE timetables SET metadata_json = ? WHERE id = ?",
                                   (json.dumps(metadata), timetable_id))
        else:
            timetable_id = str(uuid.uuid4())
            connection.execute("INSERT INTO timetables(id, page_id, metadata_json) VALUES (?, ?, ?)",
                               (timetable_id, page_id, json.dumps(metadata)))
        connection.execute(
            "UPDATE pages SET crop_path = ?, crop_json = ?, crop_confidence = 1.0, crop_status = 'manually_reviewed' WHERE id = ?",
            (str(crop_path), json.dumps({"x": x, "y": y, "width": width, "height": height}), page_id),
        )
    try:
        grid = analyze_table_grid(cropped)
        grid_info = {"row_count": grid.row_count, "column_count": grid.column_count,
                     "cell_count": len(grid.cells), "width": grid.image.shape[1], "height": grid.image.shape[0],
                     "column_widths": grid.column_widths, "row_heights": grid.row_heights}
    except GridDetectionError:
        grid_info = None
    return {"timetable_id": timetable_id, "crop": {"x": x, "y": y, "width": width, "height": height},
            "crop_confidence": 1.0, "crop_status": "manually_reviewed", "crop_url": f"/api/pages/{page_id}/crop",
            "metadata": metadata, "grid": grid_info}


@router.get("/timetables/{timetable_id}")
async def get_timetable(timetable_id: str) -> dict:
    return _snapshot(timetable_id)


@router.post("/timetables/{timetable_id}/extract")
async def extract_timetable(timetable_id: str) -> dict:
    row = _get_timetable_row(timetable_id)
    if not row["crop_path"] or not Path(row["crop_path"]).is_file():
        raise HTTPException(status_code=422, detail="This page needs a timetable crop before extraction.")
    image = cv2.imread(row["crop_path"])
    if image is None:
        raise HTTPException(status_code=500, detail="Could not read the saved timetable crop.")
    try:
        table, warnings, confidence = await extract_table_from_crop(image, json.loads(row["metadata_json"]))
    except (GridDetectionError, TableValidationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except OllamaError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    with database() as connection:
        version_number = connection.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 AS next FROM timetable_versions WHERE timetable_id = ?",
            (timetable_id,),
        ).fetchone()["next"]
        connection.execute(
            """INSERT INTO timetable_versions(timetable_id, version_number, source, verification_status, confidence, table_json)
               VALUES (?, ?, 'ai_original', 'unverified', ?, ?)""",
            (timetable_id, version_number, confidence, json.dumps(table, ensure_ascii=False)),
        )
    return {"table": table, "original_extraction": table, "version": version_number,
            "verification_status": "unverified", "confidence": confidence,
            "validation": {"valid": True, "errors": [], "warnings": warnings}}


@router.put("/timetables/{timetable_id}")
async def save_corrected_timetable(timetable_id: str, payload: dict = Body(...)) -> dict:
    timetable_row = _get_timetable_row(timetable_id)
    metadata = _metadata_from_payload(payload.get("metadata"), json.loads(timetable_row["metadata_json"]))
    raw = payload.get("table", payload)
    try:
        checked, warnings = validate_and_complete_table(raw)
    except TableValidationError as error:
        raise HTTPException(status_code=422, detail={"message": error.message, "errors": error.errors}) from error
    checked.update(metadata)
    with database() as connection:
        connection.execute("UPDATE timetables SET metadata_json = ? WHERE id = ?", (json.dumps(metadata), timetable_id))
        previous = _latest_version(connection, timetable_id)
        version_number = (previous["version_number"] if previous else 0) + 1
        connection.execute(
            """INSERT INTO timetable_versions(timetable_id, version_number, source, verification_status, confidence, table_json)
               VALUES (?, ?, 'corrected', 'reviewed', ?, ?)""",
            (timetable_id, version_number, previous["confidence"] if previous else None,
             json.dumps(checked, ensure_ascii=False)),
        )
        connection.execute(
            "INSERT INTO verification_log(timetable_id, item_type, status, details_json) VALUES (?, 'timetable', 'reviewed', ?)",
            (timetable_id, json.dumps({"version": version_number})),
        )
    return {"table": checked, "version": version_number, "verification_status": "reviewed", "warnings": warnings}


@router.post("/timetables/{timetable_id}/approve")
async def approve_timetable(timetable_id: str, payload: dict | None = Body(default=None)) -> dict:
    timetable_row = _get_timetable_row(timetable_id)
    metadata = _metadata_from_payload(payload.get("metadata") if payload else None,
                                      json.loads(timetable_row["metadata_json"]))
    with database() as connection:
        previous = _latest_version(connection, timetable_id)
        if not previous and not (payload and payload.get("table")):
            raise HTTPException(status_code=422, detail="Extract or save a timetable before approving it.")
        raw = payload.get("table") if payload and payload.get("table") else json.loads(previous["table_json"])
        try:
            checked, warnings = validate_and_complete_table(raw)
        except TableValidationError as error:
            raise HTTPException(status_code=422, detail={"message": error.message, "errors": error.errors}) from error
        checked.update(metadata)
        version_number = (previous["version_number"] if previous else 0) + 1
        connection.execute("UPDATE timetables SET metadata_json = ? WHERE id = ?", (json.dumps(metadata), timetable_id))
        connection.execute(
            """INSERT INTO timetable_versions(timetable_id, version_number, source, verification_status, confidence, table_json)
               VALUES (?, ?, 'approved', 'approved', ?, ?)""",
            (timetable_id, version_number, previous["confidence"] if previous else None,
             json.dumps(checked, ensure_ascii=False)),
        )
        connection.execute(
            "INSERT INTO verification_log(timetable_id, item_type, status, details_json) VALUES (?, 'timetable', 'approved', ?)",
            (timetable_id, json.dumps({"version": version_number})),
        )
    return {"table": checked, "version": version_number, "verification_status": "approved", "warnings": warnings}


@router.post("/timetables/{timetable_id}/analyze-page")
async def analyze_original_page(timetable_id: str) -> dict:
    row = _get_timetable_row(timetable_id)
    image = cv2.imread(row["image_path"])
    if image is None:
        raise HTTPException(status_code=500, detail="Could not read the original source page.")
    pdf_path = Path(row["storage_dir"]) / "original.pdf"
    try:
        with pymupdf.open(pdf_path) as document:
            pdf_page = document.load_page(row["page_number"] - 1)
            ocr_layout = analyze_page_layout(image, pdf_page)
        raw = await extract_page_entities(image, ocr_layout)
        extraction = normalize_page_extraction(raw)
        extraction["subjects"] = []
        extraction["relationships"] = []
        extraction["page_details"] = []
    except OllamaError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=502, detail=f"The page extraction could not be validated: {error}") from error
    confidence_values = [item["confidence"] for item in extraction["faculty"]]
    confidence = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else None
    with database() as connection:
        connection.execute(
            """INSERT INTO page_extractions(timetable_id, model, prompt_version, ocr_json, extraction_json,
               confidence, verification_status) VALUES (?, ?, 'faculty-only-v1', ?, ?, ?, 'unverified')""",
            (timetable_id, OLLAMA_MODEL, json.dumps(ocr_layout, ensure_ascii=False),
             json.dumps(extraction, ensure_ascii=False), confidence),
        )
        connection.execute(
            "INSERT INTO verification_log(timetable_id, item_type, status, details_json) VALUES (?, 'page_extraction', 'unverified', ?)",
            (timetable_id, json.dumps({"model": OLLAMA_MODEL, "ocr_source": ocr_layout["source"]})),
        )
    return {"data": extraction, "confidence": confidence, "verification_status": "unverified",
            "model": OLLAMA_MODEL, "source_page": row["page_number"], "ocr": ocr_layout}


@router.post("/timetables/{timetable_id}/page-extraction/verify")
async def verify_page_extraction(timetable_id: str, payload: dict = Body(...)) -> dict:
    _get_timetable_row(timetable_id)
    status = payload.get("verification_status")
    if status not in {"verified", "needs_review"}:
        raise HTTPException(status_code=422, detail="verification_status must be 'verified' or 'needs_review'.")
    with database() as connection:
        previous = connection.execute(
            "SELECT * FROM page_extractions WHERE timetable_id = ? ORDER BY id DESC LIMIT 1", (timetable_id,)
        ).fetchone()
        if not previous:
            raise HTTPException(status_code=422, detail="Analyze the original page before verifying its values.")
        extraction = json.loads(previous["extraction_json"])
        if payload.get("data") is not None:
            try:
                extraction = normalize_page_extraction(payload["data"])
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        extraction["subjects"] = []
        extraction["relationships"] = []
        extraction["page_details"] = []
        for key in ("subjects", "faculty", "relationships", "page_details"):
            for item in extraction[key]:
                item["verification_status"] = status
        connection.execute(
            """INSERT INTO page_extractions(timetable_id, model, prompt_version, ocr_json, extraction_json,
               confidence, verification_status) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (timetable_id, previous["model"], previous["prompt_version"], previous["ocr_json"],
             json.dumps(extraction, ensure_ascii=False), previous["confidence"], status),
        )
        connection.execute(
            "INSERT INTO verification_log(timetable_id, item_type, status, details_json) VALUES (?, 'page_extraction', ?, ?)",
            (timetable_id, status, json.dumps({"extraction_id": previous["id"]})),
        )
    return {"data": extraction, "verification_status": status}
