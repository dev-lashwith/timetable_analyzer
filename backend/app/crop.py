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


@dataclass(frozen=True)
class DiscoveredPage:
    """A page that contains a ruled timetable, with small previews only."""

    page: int | None
    source_png: bytes
    crop_png: bytes
    crop: dict[str, int]
    original: dict[str, int]
    text: str


@dataclass(frozen=True)
class PdfScanResult:
    page_count: int
    scanned_pages: int
    pages: list[DiscoveredPage]


def encode_preview(image: np.ndarray, max_side: int = 900) -> bytes:
    """Encode a bounded preview so discovery does not hold every page in memory."""
    scale = min(1.0, max_side / max(1, max(image.shape[:2])))
    resized = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else image
    success, encoded = cv2.imencode(".png", resized)
    if not success:
        raise CropDetectionError("Could not prepare a preview of this page.")
    return encoded.tobytes()


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


def _contour_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int]]:
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
    unique: list[tuple[int, int, int, int]] = []
    for _, box in candidates:
        x, y, w, h = box
        duplicate = False
        for ux, uy, uw, uh in unique:
            intersection = max(0, min(x + w, ux + uw) - max(x, ux)) * max(0, min(y + h, uy + uh) - max(y, uy))
            if intersection / max(1, min(w * h, uw * uh)) > 0.8:
                duplicate = True
                break
        if not duplicate:
            unique.append(box)
    return sorted(unique, key=lambda box: (box[1], box[0]))


def _contour_bounds(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    boxes = _contour_boxes(mask)
    if not boxes:
        return None
    return max(boxes, key=lambda box: box[2] * box[3])


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


def detect_timetable_crop(image: np.ndarray) -> CropResult:
    """Find a ruled table boundary and crop it without sending the full page onward."""
    original_height, original_width = image.shape[:2]
    scale = min(1.0, 2200 / max(original_width, original_height))
    if scale < 1.0:
        working = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        working = image
    gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    bounds = _contour_bounds(_line_mask(gray)) or _hough_bounds(gray)
    if bounds is None:
        raise CropDetectionError(
            "Could not find a timetable box. Upload a clearer image with visible horizontal and vertical table lines."
        )

    x, y, width, height = bounds
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
    return CropResult(crop, x1, y1, x2 - x1, y2 - y1, original_width, original_height)


def detect_ruled_table_crops(image: np.ndarray) -> list[CropResult]:
    """Find separate ruled tables on a page, ordered from top to bottom."""
    original_height, original_width = image.shape[:2]
    scale = min(1.0, 2200 / max(original_width, original_height))
    working = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image
    gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    boxes = _contour_boxes(_line_mask(gray))
    if not boxes:
        bounds = _hough_bounds(gray)
        boxes = [bounds] if bounds else []
    crops: list[CropResult] = []
    for x, y, width, height in boxes:
        pad = max(3, round(min(working.shape[:2]) * 0.004))
        x1, y1 = max(0, x - pad), max(0, y - pad)
        x2, y2 = min(working.shape[1], x + width + pad), min(working.shape[0], y + height + pad)
        if scale < 1:
            x1, y1, x2, y2 = round(x1 / scale), round(y1 / scale), round(x2 / scale), round(y2 / scale)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(original_width, x2), min(original_height, y2)
        crop = image[y1:y2, x1:x2].copy()
        if crop.size == 0 or crop.shape[1] * crop.shape[0] >= original_width * original_height * 0.99:
            continue
        crops.append(CropResult(crop, x1, y1, x2 - x1, y2 - y1, original_width, original_height))
    return crops


def is_pdf(data: bytes) -> bool:
    """Detect a PDF by its header rather than trusting the browser's MIME type."""
    return data[:1024].lstrip().startswith(b"%PDF-")


def _open_pdf(data: bytes):
    try:
        return pymupdf.open(stream=data, filetype="pdf")
    except Exception as error:
        raise CropDetectionError(
            "The uploaded PDF could not be opened. Make sure it is a valid, unprotected PDF."
        ) from error


def _render_pdf_page(page: pymupdf.Page, scale: float) -> np.ndarray:
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def decode_upload(data: bytes, page: int | None = None) -> DecodedUpload:
    """Decode an image, or rasterize a requested/auto-detected PDF page."""
    if not is_pdf(data):
        return DecodedUpload(decode_image(data))

    with _open_pdf(data) as document:
        page_count = document.page_count
        if page_count == 0:
            raise CropDetectionError("The uploaded PDF has no pages.")

        scale = PDF_RENDER_DPI / 72
        if page is not None:
            if not 1 <= page <= page_count:
                raise CropDetectionError(f"Page {page} is not in this PDF. It has {page_count} page(s).")
            if page > MAX_PDF_PAGES:
                raise CropDetectionError(
                    f"Only the first {MAX_PDF_PAGES} PDF pages can be processed. Change MAX_PDF_PAGES to allow more."
                )
            try:
                image = _render_pdf_page(document.load_page(page - 1), scale)
            except Exception as error:
                raise CropDetectionError(f"Could not read page {page} of the PDF.") from error
            return DecodedUpload(image, page, page_count, encode_preview(image, 1200))

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
        return DecodedUpload(image, index + 1, page_count, encode_preview(image, 1200))


def find_pdf_timetable_pages(data: bytes) -> PdfScanResult:
    """Scan PDF pages for ruled tables, keeping only small previews in memory."""
    with _open_pdf(data) as document:
        page_count = document.page_count
        if page_count == 0:
            raise CropDetectionError("The uploaded PDF has no pages.")

        scanned_pages = min(page_count, MAX_PDF_PAGES)
        scale = PDF_RENDER_DPI / 72
        found: list[DiscoveredPage] = []
        for index in range(scanned_pages):
            try:
                pdf_page = document.load_page(index)
                image = _render_pdf_page(pdf_page, scale)
            except Exception as error:
                raise CropDetectionError(f"Could not read page {index + 1} of the PDF.") from error
            try:
                text = pdf_page.get_text("text") or ""
            except Exception:
                text = ""
            try:
                crop = detect_timetable_crop(image)
            except CropDetectionError:
                continue
            found.append(DiscoveredPage(
                page=index + 1,
                source_png=encode_preview(image),
                crop_png=encode_preview(crop.image),
                crop={"x": crop.x, "y": crop.y, "width": crop.width, "height": crop.height},
                original={"width": crop.original_width, "height": crop.original_height},
                text=text,
            ))
        return PdfScanResult(page_count, scanned_pages, found)
