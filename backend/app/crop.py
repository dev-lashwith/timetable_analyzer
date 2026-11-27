from dataclasses import dataclass

import cv2
import numpy as np
import pymupdf

from .config import MAX_PDF_PAGES, PDF_RENDER_DPI


class CropDetectionError(ValueError):
    """Raised when a table boundary cannot be distinguished from the page."""


@dataclass(frozen=True)
class CropResult:
    image: np.ndarray
    x: int
    y: int
    width: int
    height: int
    original_width: int
    original_height: int
    confidence: float = 0.5
    review_required: bool = True


def decode_image(data: bytes) -> np.ndarray:
    encoded = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise CropDetectionError("The uploaded file is not a readable PNG, JPEG, WebP image, or PDF.")
    return image


@dataclass(frozen=True)
class DecodedUpload:
    image: np.ndarray
    # PDF-only details, used for the source preview and status labels.
    page: int | None = None
    page_count: int | None = None
    source_png: bytes | None = None


def _line_mask(gray: np.ndarray) -> np.ndarray:
    height, width = gray.shape[:2]
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    block = max(15, min(41, (min(height, width) // 20) | 1))
    binary = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block, 9
    )
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, width // 35), 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, height // 35)))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
    return cv2.bitwise_or(horizontal, vertical)


def _contour_candidates(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    height, width = mask.shape[:2]
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[int, tuple[int, int, int, int]]] = []
    page_area = height * width
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if w < width * 0.12 or h < height * 0.10:
            continue
        if area < page_area * 0.012 or area > page_area * 0.965:
            continue
        roi = mask[y : y + h, x : x + w]
        line_density = cv2.countNonZero(roi) / max(1, area)
        if line_density < 0.004:
            continue
        candidates.append((area, (x, y, w, h)))
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    distinct: list[tuple[int, int, int, int]] = []
    for _, bounds in candidates:
        x, y, width, height = bounds
        area = width * height
        if any(
            max(0, min(x + width, other_x + other_width) - max(x, other_x))
            * max(0, min(y + height, other_y + other_height) - max(y, other_y))
            / max(1, min(area, other_width * other_height))
            > 0.88
            for other_x, other_y, other_width, other_height in distinct
        ):
            continue
        distinct.append(bounds)
    return distinct


def _weekday_matches(bounds: tuple[int, int, int, int], text_words: list[dict] | None) -> int:
    if not text_words:
        return 0
    x, y, width, height = bounds
    weekday_names = {"mon", "monday", "tue", "tues", "tuesday", "wed", "wednesday", "thu", "thur", "thurs", "thursday", "fri", "friday", "sat", "saturday", "sun", "sunday"}
    matches: set[str] = set()
    for word in text_words:
        text = str(word.get("text", "")).strip().lower().rstrip(":")
        box = word.get("bbox")
        if text not in weekday_names or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        center_x, center_y = (float(box[0]) + float(box[2])) / 2, (float(box[1]) + float(box[3])) / 2
        if x <= center_x <= x + width and y <= center_y <= y + height:
            matches.add(text)
    return len(matches)


def _candidate_score(
    image: np.ndarray,
    bounds: tuple[int, int, int, int],
    text_words: list[dict] | None,
) -> float:
    x, y, width, height = bounds
    try:
        from .grid import GridDetectionError, analyze_table_grid

        grid = analyze_table_grid(image[y : y + height, x : x + width])
        rows, columns = grid.row_count, grid.column_count
    except (GridDetectionError, ValueError):
        rows, columns = 0, 0
    ratio = width / max(1, height)
    score = 0.22 + min(columns, 7) * 0.035 + min(rows, 8) * 0.025
    if columns >= 5:
        score += 0.12
    if rows >= 5:
        score += 0.08
    if 0.85 <= ratio <= 2.5:
        score += 0.08
    elif 0.55 <= ratio <= 3.2:
        score += 0.04
    score += min(4, _weekday_matches(bounds, text_words)) * 0.04
    if not rows or not columns:
        score = min(score, 0.58)
    return round(min(0.99, score), 3)


def _hough_bounds(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    height, width = gray.shape[:2]
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=max(35, min(height, width) // 15),
        minLineLength=max(30, min(height, width) // 7),
        maxLineGap=max(8, min(height, width) // 50),
    )
    if lines is None:
        return None
    horizontal: list[tuple[int, int]] = []
    vertical: list[tuple[int, int]] = []
    for line in lines[:, 0, :]:
        x1, y1, x2, y2 = (int(value) for value in line)
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dx >= min(width * 0.12, max(30, height * 0.1)) and dy <= max(8, dx * 0.06):
            horizontal.append((min(x1, x2), max(x1, x2)))
        elif dy >= min(height * 0.10, max(30, width * 0.1)) and dx <= max(8, dy * 0.06):
            vertical.append((min(y1, y2), max(y1, y2)))
    if len(horizontal) < 2 or len(vertical) < 2:
        return None
    x1 = min(start for start, _ in horizontal)
    x2 = max(end for _, end in horizontal)
    y1 = min(start for start, _ in vertical)
    y2 = max(end for _, end in vertical)
    w, h = x2 - x1, y2 - y1
    area = w * h
    if w < width * 0.12 or h < height * 0.10 or area < width * height * 0.012 or area > width * height * 0.965:
        return None
    return x1, y1, w, h


def detect_timetable_crop(image: np.ndarray, text_words: list[dict] | None = None) -> CropResult:
    """Find a ruled table boundary and crop it without sending the full page onward."""
    original_height, original_width = image.shape[:2]
    scale = min(1.0, 2200 / max(original_width, original_height))
    if scale < 1.0:
        working = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        working_words = [
            {**word, "bbox": [round(float(value) * scale) for value in word.get("bbox", [])]}
            for word in (text_words or [])
        ]
    else:
        working = image
        working_words = text_words
    gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    candidates = _contour_candidates(_line_mask(gray))
    if not candidates:
        hough = _hough_bounds(gray)
        candidates = [hough] if hough is not None else []
    if not candidates:
        raise CropDetectionError(
            "Could not find a timetable box. Upload a clearer image with visible horizontal and vertical table lines."
        )

    candidates.sort(key=lambda bounds: _candidate_score(working, bounds, working_words), reverse=True)
    x, y, width, height = candidates[0]
    confidence = _candidate_score(working, candidates[0], working_words)
    # Keep a small border around the detected table so its outer rule is not clipped.
    pad = max(3, round(min(working.shape[:2]) * 0.004))
    x1, y1 = max(0, x - pad), max(0, y - pad)
    x2 = min(working.shape[1], x + width + pad)
    y2 = min(working.shape[0], y + height + pad)

    if scale < 1.0:
        x1, y1 = round(x1 / scale), round(y1 / scale)
        x2, y2 = round(x2 / scale), round(y2 / scale)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(original_width, x2), min(original_height, y2)
    crop = image[y1:y2, x1:x2].copy()
    if crop.size == 0 or crop.shape[1] * crop.shape[0] >= original_width * original_height * 0.99:
        raise CropDetectionError(
            "The table boundary is too close to the image edges to crop safely. Use an image with visible page margin around the timetable."
        )
    return CropResult(
        crop,
        x1,
        y1,
        x2 - x1,
        y2 - y1,
        original_width,
        original_height,
        confidence,
        confidence < 0.72,
    )


def is_pdf(data: bytes) -> bool:
    """Detect a PDF by its header rather than trusting the browser's MIME type."""
    return data[:1024].lstrip().startswith(b"%PDF-")


def _render_pdf_page(page: pymupdf.Page, scale: float) -> np.ndarray:
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def decode_upload(data: bytes) -> DecodedUpload:
    """Decode an image, or rasterize the PDF page that contains the timetable."""
    if not is_pdf(data):
        return DecodedUpload(decode_image(data))

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as error:
        raise CropDetectionError(
            "The uploaded PDF could not be opened. Make sure it is a valid, unprotected PDF."
        ) from error

    with document:
        page_count = document.page_count
        if page_count == 0:
            raise CropDetectionError("The uploaded PDF has no pages.")

        scale = PDF_RENDER_DPI / 72
        chosen: tuple[int, np.ndarray] | None = None
        for index in range(min(page_count, MAX_PDF_PAGES)):
            try:
                image = _render_pdf_page(document.load_page(index), scale)
            except Exception as error:
                raise CropDetectionError(f"Could not read page {index + 1} of the PDF.") from error
            try:
                detect_timetable_crop(image)
            except CropDetectionError:
                # Keep the first readable page as a fallback so the final error
                # still explains that no ruled table was found.
                if chosen is None:
                    chosen = (index, image)
                continue
            chosen = (index, image)
            break

        if chosen is None:
            raise CropDetectionError("No readable pages were found in the PDF.")
        index, image = chosen
        preview_scale = min(1.0, 1200 / max(image.shape[:2]))
        preview = cv2.resize(image, None, fx=preview_scale, fy=preview_scale, interpolation=cv2.INTER_AREA)
        success, encoded = cv2.imencode(".png", preview)
        source_png = encoded.tobytes() if success else None
        return DecodedUpload(image, index + 1, page_count, source_png)
