import base64
import json
from io import BytesIO
from typing import Any

import cv2
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from pydantic import BaseModel

from .config import FRONTEND_ORIGIN, MAX_IMAGE_PIXELS, MAX_UPLOAD_BYTES
from .crop import CropDetectionError, decode_image, detect_timetable_crop
from .grid import GridDetectionError, analyze_table_grid
from .ollama_client import OllamaError, extract_cell_texts, ollama_status
from .validation import TableValidationError, apply_cell_texts, validate_and_complete_table


app = FastAPI(title="Timetable Extractor API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in FRONTEND_ORIGIN.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


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


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large. Maximum upload size is 20 MB.")
    if not data:
        raise HTTPException(status_code=400, detail="Choose an image first.")
    return data


def _image_from_upload(data: bytes):
    try:
        image = decode_image(data)
    except CropDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if image.shape[0] * image.shape[1] > MAX_IMAGE_PIXELS:
        raise HTTPException(status_code=413, detail="Image dimensions are too large. Maximum is 40 megapixels.")
    return image


def _decode_model_json(content: str) -> Any:
    candidate = content.strip()
    if candidate.startswith("```"):
        candidate = candidate.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as error:
        raise OllamaError(f"The model response was not valid JSON near character {error.pos}.") from error


@app.get("/api/health")
async def health() -> dict:
    return await ollama_status()


@app.post("/api/preview")
async def preview(file: UploadFile = File(...)) -> dict:
    data = await _read_upload(file)
    image = _image_from_upload(data)
    try:
        crop = detect_timetable_crop(image)
        grid = analyze_table_grid(crop.image)
    except CropDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except GridDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    success, encoded = cv2.imencode(".png", grid.image)
    if not success:
        raise HTTPException(status_code=500, detail="Could not prepare the cropped image preview.")
    return {
        "crop_png_base64": base64.b64encode(encoded.tobytes()).decode("ascii"),
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
    }


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)) -> dict:
    data = await _read_upload(file)
    image = _image_from_upload(data)
    try:
        crop = detect_timetable_crop(image)
        grid = analyze_table_grid(crop.image)
        content = await extract_cell_texts(grid.image, grid.cells)
        raw_texts = _decode_model_json(content)
        geometry = {
            "row_count": grid.row_count,
            "column_count": grid.column_count,
            "column_widths": grid.column_widths,
            "row_heights": grid.row_heights,
            "cells": [
                {
                    "row": cell.row,
                    "column": cell.column,
                    "rowspan": cell.rowspan,
                    "colspan": cell.colspan,
                    "text": "",
                }
                for cell in grid.cells
            ],
        }
        with_text, text_warnings = apply_cell_texts(geometry, raw_texts)
        table, warnings = validate_and_complete_table(with_text)
        warnings.extend(text_warnings)
    except CropDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except GridDetectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except TableValidationError as error:
        raise HTTPException(status_code=422, detail={"message": error.message, "errors": error.errors}) from error
    except OllamaError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {
        "table": table,
        "validation": {"valid": True, "errors": [], "warnings": warnings},
    }


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
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="timetable.xlsx"'}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
