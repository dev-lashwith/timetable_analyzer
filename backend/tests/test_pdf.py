import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pymupdf

from app.main import app


def make_pdf(page_count: int = 1, table_on_page: int = 0) -> bytes:
    document = pymupdf.open()
    for index in range(page_count):
        page = document.new_page(width=612, height=792)
        if index != table_on_page:
            page.insert_text((72, 72), "This page has no timetable.")
            continue
        x0, y0, x1, y1 = 60, 90, 552, 690
        for x in [x0, 178, 296, 414, x1]:
            page.draw_line((x, y0), (x, y1), color=(0, 0, 0), width=2)
        for y in [y0, 190, 290, 390, 490, 590, y1]:
            page.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=2)
    output = document.tobytes()
    document.close()
    return output


async def post_pdf(path: str, payload: bytes, data: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            path,
            files={"file": ("timetable.pdf", payload, "application/pdf")},
            data=data or {},
        )


def test_preview_rasterizes_pdf_and_returns_page_preview():
    response = asyncio.run(post_pdf("/api/preview", make_pdf()))

    assert response.status_code == 200
    body = response.json()
    assert body["source_page"] == 1
    assert body["source_page_count"] == 1
    assert body["source_png_base64"]
    assert body["crop"]["width"] < body["original"]["width"]
    assert body["grid"]["row_count"] >= 2
    assert body["grid"]["column_count"] >= 2


def test_preview_selects_pdf_page_containing_the_table():
    response = asyncio.run(post_pdf("/api/preview", make_pdf(page_count=3, table_on_page=1)))

    assert response.status_code == 200
    assert response.json()["source_page"] == 2
    assert response.json()["source_page_count"] == 3


def test_extract_sends_the_selected_pdf_page_to_sarvam(completed_extraction):
    with patch("app.main.extract_documents_async", new_callable=AsyncMock) as mocked_extract:
        mocked_extract.return_value = completed_extraction
        response = asyncio.run(post_pdf(
            "/api/extract", make_pdf(page_count=2, table_on_page=1), {"page": "2"}
        ))

    assert response.status_code == 200
    files = mocked_extract.await_args.args[0]
    assert files[0][0] == "timetable_page_2.png"
    assert response.json()["table"]["source_page"] == 2


def test_invalid_pdf_returns_validation_error():
    response = asyncio.run(post_pdf("/api/preview", b"%PDF-1.7 not really a pdf"))

    assert response.status_code == 422
    assert "PDF" in response.json()["detail"]
