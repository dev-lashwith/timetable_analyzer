import asyncio
import json
from io import BytesIO
from unittest.mock import AsyncMock, patch

import httpx
import pymupdf
from openpyxl import load_workbook

from app.main import app
from app.sarvam_client import SarvamError


def make_multi_pdf() -> bytes:
    document = pymupdf.open()
    for index in range(4):
        page = document.new_page(width=612, height=792)
        if index not in (0, 2):
            page.insert_text((72, 72), "This page has no timetable.")
            continue
        x0, y0, x1, y1 = 60, 110, 552, 690
        for x in [x0, 178, 296, 414, x1]:
            page.draw_line((x, y0), (x, y1), color=(0, 0, 0), width=2)
        for y in [y0, 210, 310, 410, 510, 610, y1]:
            page.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=2)
        label = "Semester I" if index == 0 else "Semester III"
        page.insert_text((x0 + 12, y0 - 18), label, fontsize=14)
    output = document.tobytes()
    document.close()
    return output


async def post_pdf(path: str, payload: bytes, data: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            path,
            files={"file": ("timetables.pdf", payload, "application/pdf")},
            data=data or {},
        )


def test_discover_finds_every_table_page_and_skips_blank_pages():
    body = asyncio.run(post_pdf("/api/discover", make_multi_pdf())).json()

    assert body["page_count"] == 4
    assert body["scanned_pages"] == 4
    assert [item["page"] for item in body["timetables"]] == [1, 3]
    assert all(item["semester_guess"] is None for item in body["timetables"])
    assert all(item["crop_png_base64"] for item in body["timetables"])


def test_preview_can_render_a_specific_page():
    response = asyncio.run(post_pdf("/api/preview", make_multi_pdf(), {"page": "3"}))

    assert response.status_code == 200
    assert response.json()["source_page"] == 3
    assert response.json()["grid"]["row_count"] >= 2


def test_extract_many_processes_each_selected_page(completed_extraction):
    payload = json.dumps([
        {"id": "1", "page": 1, "semester": "Semester I"},
        {"id": "3", "page": 3, "semester": "Semester III"},
    ])
    with patch("app.main.extract_documents_async", new_callable=AsyncMock) as mocked_extract:
        mocked_extract.side_effect = [completed_extraction, completed_extraction]
        response = asyncio.run(post_pdf(
            "/api/extract-many",
            make_multi_pdf(),
            {"targets": payload, "class_name": "10", "stream": "Science", "section": "A"},
        ))

    assert response.status_code == 200
    body = response.json()
    assert body["failures"] == []
    assert [item["id"] for item in body["tables"]] == ["1", "3"]
    assert [item["table"]["semester"] for item in body["tables"]] == ["Semester I", "Semester III"]
    assert [item["table"]["source_page"] for item in body["tables"]] == [1, 3]
    assert mocked_extract.await_count == 2


def test_extract_many_reports_a_failed_sarvam_job_without_losing_good_tables(completed_extraction):
    payload = json.dumps([
        {"id": "1", "page": 1, "semester": "Semester I"},
        {"id": "2", "page": 2, "semester": "Blank page"},
    ])
    with patch("app.main.extract_documents_async", new_callable=AsyncMock) as mocked_extract:
        mocked_extract.side_effect = [completed_extraction, SarvamError("Sarvam found no timetable.")]
        body = asyncio.run(post_pdf("/api/extract-many", make_multi_pdf(), {"targets": payload})).json()

    assert len(body["tables"]) == 1
    assert len(body["failures"]) == 1
    assert body["failures"][0]["id"] == "2"
    assert mocked_extract.await_count == 2


def test_export_all_writes_separate_sheets_and_details():
    def table(semester: str, page: int) -> dict:
        return {
            "row_count": 1,
            "column_count": 1,
            "column_widths": [100],
            "row_heights": [40],
            "cells": [{"row": 0, "column": 0, "text": semester}],
            "class_name": "10",
            "stream": "Science",
            "section": "A",
            "semester": semester,
            "source_page": page,
        }

    transport = httpx.ASGITransport(app=app)

    async def do_export():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/export-all", json={"tables": [
                table("Semester I", 1),
                table("Semester III", 3),
            ]})

    response = asyncio.run(do_export())
    assert response.status_code == 200
    workbook = load_workbook(BytesIO(response.content))
    assert workbook.sheetnames == ["Semester I", "Semester III", "Details"]
    assert workbook["Semester I"]["A1"].value == "Semester I"
    details = workbook["Details"]
    assert [cell.value for cell in details[1]] == [
        "Semester", "Class", "Stream", "Section", "Source page", "Rows", "Columns"
    ]
    assert [cell.value for cell in details[2]] == ["Semester I", "10", "Science", "A", 1, 1, 1]
    assert [cell.value for cell in details[3]] == ["Semester III", "10", "Science", "A", 3, 1, 1]
    assert 'filename="timetables_10_Science_A.xlsx"' in response.headers["content-disposition"]
