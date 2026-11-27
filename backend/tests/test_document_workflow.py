import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pymupdf

import app.database as database_module
import app.document_api as document_api
from app.main import app


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    storage = tmp_path / "store"
    monkeypatch.setattr(database_module, "DATABASE_PATH", storage / "timetable_analyzer.sqlite3")
    monkeypatch.setattr(database_module, "STORAGE_ROOT", storage)
    monkeypatch.setattr(database_module, "_initialized", False)
    monkeypatch.setattr(document_api, "STORAGE_ROOT", storage)


def make_pdf(with_table: bool = True) -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    if with_table:
        x0, y0, x1, y1 = 60, 90, 552, 690
        for x in [x0, 158, 256, 354, 452, x1]:
            page.draw_line((x, y0), (x, y1), color=(0, 0, 0), width=2)
        for y in [y0, 190, 290, 390, 490, 590, y1]:
            page.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=2)
    else:
        page.insert_text((72, 72), "No table on this page")
    content = document.tobytes()
    document.close()
    return content


async def request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def upload_pdf(payload: bytes):
    return asyncio.run(request(
        "POST", "/api/documents/upload",
        files={"file": ("weekly.pdf", payload, "application/pdf")},
        data={"class_name": "Year 2", "stream": "Computing", "section": "A", "semester": "4", "room": "B12"},
    ))


def test_upload_saves_original_splits_pages_and_registers_provenance():
    response = upload_pdf(make_pdf())

    assert response.status_code == 200
    body = response.json()
    assert body["original_pdf_stored"] is True
    assert len(body["pages"]) == 1
    page = body["pages"][0]
    assert page["page_number"] == 1
    assert page["crop_url"]
    assert page["timetable_id"]
    assert page["crop_confidence"] is not None

    documents = asyncio.run(request("GET", "/api/documents")).json()["documents"]
    assert documents[0]["filename"] == "weekly.pdf"
    saved_page = asyncio.run(request("GET", page["image_url"]))
    assert saved_page.status_code == 200
    assert saved_page.headers["content-type"] == "image/png"


def test_ai_extraction_and_corrected_approval_versions_are_kept_separately():
    uploaded = upload_pdf(make_pdf()).json()
    timetable_id = uploaded["pages"][0]["timetable_id"]
    initial = {
        "row_count": 1, "column_count": 1, "column_widths": [120], "row_heights": [40],
        "cells": [{"row": 0, "column": 0, "text": "AI text"}],
    }
    with patch("app.document_api.extract_table_from_crop", new_callable=AsyncMock) as extraction:
        extraction.return_value = (initial, [], 0.82)
        extracted = asyncio.run(request("POST", f"/api/timetables/{timetable_id}/extract"))
    assert extracted.status_code == 200

    corrected = {**initial, "cells": [{"row": 0, "column": 0, "text": "Corrected text"}]}
    saved = asyncio.run(request("PUT", f"/api/timetables/{timetable_id}", json={
        "table": corrected, "metadata": {"class_name": "Year 3", "stream": "Computing", "section": "B",
                                           "semester": "5", "academic_session": "2027-2028", "room": "B14"},
    }))
    assert saved.status_code == 200
    approved = asyncio.run(request("POST", f"/api/timetables/{timetable_id}/approve", json={"table": corrected}))
    assert approved.status_code == 200

    snapshot = asyncio.run(request("GET", f"/api/timetables/{timetable_id}")).json()
    assert snapshot["original_extraction"]["cells"][0]["text"] == "AI text"
    assert snapshot["table"]["cells"][0]["text"] == "Corrected text"
    assert snapshot["metadata"]["class_name"] == "Year 3"
    assert snapshot["version"]["verification_status"] == "approved"


def test_whole_page_extraction_returns_only_faculty_and_keeps_review_state():
    uploaded = upload_pdf(make_pdf()).json()
    timetable_id = uploaded["pages"][0]["timetable_id"]
    model_result = {
        "subjects": [{"name": "Databases", "code": "CS401", "confidence": 0.91, "evidence": "CS401 Databases"}],
        "faculty": [{"name": "R. Kumar", "abbreviation": "RK", "confidence": 0.86, "evidence": "RK - R. Kumar"}],
        "relationships": [{"subject_name": "Databases", "subject_code": "CS401", "faculty_name": "R. Kumar",
                           "faculty_abbreviation": "RK", "confidence": 0.8, "evidence": "CS401 — RK"}],
        "page_details": [],
    }
    with patch("app.document_api.extract_page_entities", new_callable=AsyncMock) as analyze:
        analyze.return_value = model_result
        response = asyncio.run(request("POST", f"/api/timetables/{timetable_id}/analyze-page"))
    assert response.status_code == 200
    result = response.json()
    assert result["source_page"] == 1
    assert result["data"]["subjects"] == []
    assert result["data"]["relationships"] == []
    assert result["data"]["page_details"] == []
    assert result["data"]["faculty"][0]["abbreviation"] == "RK"
    assert result["verification_status"] == "unverified"
    assert result["prompt_version"] == "faculty-only-v1"
    assert analyze.await_args.args[1]["layout"]["width"] > 0

    verified = asyncio.run(request("POST", f"/api/timetables/{timetable_id}/page-extraction/verify",
                                   json={"verification_status": "verified", "data": result["data"]}))
    assert verified.status_code == 200
    assert verified.json()["data"]["subjects"] == []
    assert verified.json()["data"]["faculty"][0]["verification_status"] == "verified"
    saved = asyncio.run(request("GET", f"/api/timetables/{timetable_id}")).json()
    assert saved["page_extraction"]["prompt_version"] == "faculty-only-v1"


def test_uncropped_pdf_page_can_be_manually_cropped():
    uploaded = upload_pdf(make_pdf(with_table=False)).json()
    page = uploaded["pages"][0]
    assert page["crop_status"] == "not_found"
    response = asyncio.run(request("POST", f"/api/pages/{page['id']}/crop", json={
        "x": 120, "y": 150, "width": 1200, "height": 1500,
        "class_name": "Year 2", "stream": "Computing", "section": "A", "semester": "4", "room": "B12",
    }))
    assert response.status_code == 200
    assert response.json()["crop_status"] == "manually_reviewed"
    assert response.json()["timetable_id"]
