import asyncio
import json
from unittest.mock import AsyncMock, patch

import cv2
import httpx
import numpy as np

from app.main import app


def make_page() -> bytes:
    page = np.full((700, 900, 3), 255, dtype=np.uint8)
    x0, y0, x1, y1 = 130, 115, 770, 590
    for x in [x0, 260, 390, 515, 640, x1]:
        cv2.line(page, (x, y0), (x, y1), (0, 0, 0), 2)
    for y in [y0, 185, 265, 345, 425, 505, y1]:
        cv2.line(page, (x0, y), (x1, y), (0, 0, 0), 2)
    success, encoded = cv2.imencode(".png", page)
    assert success
    return encoded.tobytes()


async def post_api(path: str, image: bytes) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, files={"file": ("page.png", image, "image/png")})


def test_preview_returns_crop_metadata_and_image():
    response = asyncio.run(post_api("/api/preview", make_page()))
    assert response.status_code == 200
    body = response.json()
    assert body["crop"]["width"] < body["original"]["width"]
    assert body["crop"]["height"] < body["original"]["height"]
    assert body["crop_png_base64"]
    assert body["grid"]["row_count"] >= 2
    assert body["grid"]["column_count"] >= 2


def test_extract_sends_only_detected_crop_to_ollama():
    with patch("app.main.extract_cell_texts", new_callable=AsyncMock) as mocked_extract:
        mocked_extract.return_value = json.dumps({"texts": [{"id": 0, "text": "Monday"}]})
        response = asyncio.run(post_api("/api/extract", make_page()))

    assert response.status_code == 200
    sent_image = mocked_extract.await_args.args[0]
    assert sent_image.shape[0] * sent_image.shape[1] < 700 * 900 * 0.65
    assert len(mocked_extract.await_args.args[1]) > 1
    assert response.json()["table"]["cells"][0]["text"] == "Monday"
