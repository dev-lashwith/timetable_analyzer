from __future__ import annotations

import csv
import io
import shutil
import subprocess

import cv2
import numpy as np
import pymupdf


def analyze_page_layout(image: np.ndarray, pdf_page: pymupdf.Page) -> dict:
    """Collect positioned PDF text, optional OCR text, and table-line layout cues."""
    words: list[dict] = []
    source = "pdf_text"
    scale_x = image.shape[1] / max(1, pdf_page.rect.width)
    scale_y = image.shape[0] / max(1, pdf_page.rect.height)
    for item in pdf_page.get_text("words"):
        if len(item) < 5 or not str(item[4]).strip():
            continue
        words.append({
            "text": str(item[4]),
            "bbox": [
                round(item[0] * scale_x),
                round(item[1] * scale_y),
                round(item[2] * scale_x),
                round(item[3] * scale_y),
            ],
        })

    if not words:
        source = "unavailable"
        executable = shutil.which("tesseract")
        success, encoded = cv2.imencode(".png", image)
        if executable and success:
            try:
                result = subprocess.run(
                    [executable, "stdin", "stdout", "--psm", "6", "tsv"],
                    input=encoded.tobytes(), capture_output=True, timeout=60, check=False,
                )
                if result.returncode == 0:
                    source = "tesseract"
                    reader = csv.DictReader(io.StringIO(result.stdout.decode("utf-8", errors="replace")), delimiter="\t")
                    for item in reader:
                        text = str(item.get("text", "")).strip()
                        if not text or item.get("level") != "5":
                            continue
                        x, y = int(item["left"]), int(item["top"])
                        words.append({"text": text, "bbox": [x, y, x + int(item["width"]), y + int(item["height"])]})
            except (OSError, ValueError, subprocess.TimeoutExpired):
                source = "unavailable"

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8
    )
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, image.shape[1] // 40), 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, image.shape[0] // 40)))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
    horizontal_count = len(cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0])
    vertical_count = len(cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0])
    return {
        "source": source,
        "text": " ".join(item["text"] for item in words),
        "words": words[:2500],
        "layout": {
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
            "horizontal_rule_regions": horizontal_count,
            "vertical_rule_regions": vertical_count,
        },
    }


def normalize_page_extraction(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("The page analysis must be a JSON object.")

    def clean_items(key: str, fields: tuple[str, ...]) -> list[dict]:
        value = raw.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"{key} must be an array.")
        result: list[dict] = []
        seen: set[tuple[str, ...]] = set()
        for item in value[:500]:
            if not isinstance(item, dict):
                continue
            cleaned = {field: " ".join(str(item.get(field) or "").split()) for field in fields}
            identity = tuple(cleaned[field].casefold() for field in fields)
            if not any(identity) or identity in seen:
                continue
            seen.add(identity)
            confidence = item.get("confidence", 0.5)
            try:
                cleaned["confidence"] = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError):
                cleaned["confidence"] = 0.5
            cleaned["evidence"] = " ".join(str(item.get("evidence") or "").split())[:500]
            cleaned["verification_status"] = "unverified"
            result.append(cleaned)
        return result

    subjects = clean_items("subjects", ("name", "code"))
    faculty = clean_items("faculty", ("name", "abbreviation"))
    relationships = clean_items(
        "relationships",
        ("subject_name", "subject_code", "faculty_name", "faculty_abbreviation"),
    )
    return {
        "subjects": subjects,
        "faculty": faculty,
        "relationships": relationships,
        "page_details": clean_items("page_details", ("class_name", "semester", "academic_session", "room")),
        "verification_status": "unverified",
    }
