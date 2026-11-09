from dataclasses import dataclass

import cv2
import numpy as np


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
        raise CropDetectionError("The uploaded file is not a readable PNG, JPEG, or WebP image.")
    return image


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


def _contour_bounds(mask: np.ndarray) -> tuple[int, int, int, int] | None:
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
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


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
