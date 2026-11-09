from dataclasses import dataclass

import cv2
import numpy as np


class GridDetectionError(ValueError):
    """Raised when table rules do not define a usable row/column grid."""


@dataclass(frozen=True)
class GridCell:
    row: int
    column: int
    rowspan: int
    colspan: int
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class TableGrid:
    image: np.ndarray
    row_count: int
    column_count: int
    cells: list[GridCell]
    column_widths: list[int]
    row_heights: list[int]


def _gray_threshold(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    short_side = min(gray.shape[:2])
    block_size = max(15, min(41, (short_side // 20) | 1))
    binary = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gray, (3, 3), 0),
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        9,
    )
    return gray, binary


def _rectify(image: np.ndarray) -> np.ndarray:
    """Perspective-correct the outer ruled rectangle before projecting its grid lines."""
    _, binary = _gray_threshold(image)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image
    contour = max(contours, key=cv2.contourArea)
    image_area = image.shape[0] * image.shape[1]
    if cv2.contourArea(contour) < image_area * 0.15:
        return image
    perimeter = cv2.arcLength(contour, True)
    corners = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
    if len(corners) != 4:
        return image

    points = corners.reshape(4, 2).astype(np.float32)
    sums = points.sum(axis=1)
    differences = points[:, 0] - points[:, 1]
    top_left = points[np.argmin(sums)]
    bottom_right = points[np.argmax(sums)]
    top_right = points[np.argmax(differences)]
    bottom_left = points[np.argmin(differences)]
    source = np.float32([top_left, top_right, bottom_right, bottom_left])
    width = round(max(np.linalg.norm(top_right - top_left), np.linalg.norm(bottom_right - bottom_left)))
    height = round(max(np.linalg.norm(bottom_left - top_left), np.linalg.norm(bottom_right - top_right)))
    if width < 100 or height < 80:
        return image
    destination = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    transform = cv2.getPerspectiveTransform(source, destination)
    return cv2.warpPerspective(
        image,
        transform,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )


def _line_masks(binary: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    height, width = binary.shape[:2]
    horizontal_axis = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, width // 25), 1)),
    )
    vertical_axis = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(18, height // 30))),
    )
    horizontal_segments = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(7, min(15, width // 80)), 1)),
    )
    vertical_segments = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(7, min(15, height // 45)))),
    )
    return horizontal_axis, vertical_axis, horizontal_segments, vertical_segments


def _find_boundaries(mask: np.ndarray, axis: int) -> list[int]:
    height, width = mask.shape[:2]
    projection = np.count_nonzero(mask, axis=1 if axis == 0 else 0)
    if projection.size == 0 or projection.max() == 0:
        return []
    span = width if axis == 0 else height
    absolute_floor = span * (0.055 if axis == 0 else 0.025)
    relative_floor = projection.max() * (0.085 if axis == 0 else 0.07)
    threshold = max(absolute_floor, relative_floor)
    active = np.flatnonzero(projection >= threshold)
    if active.size == 0:
        return []
    groups = np.split(active, np.flatnonzero(np.diff(active) > 2) + 1)
    boundaries: list[tuple[int, int]] = []
    for group in groups:
        weights = projection[group].astype(np.float64)
        center = int(round(np.average(group, weights=weights)))
        boundaries.append((center, int(weights.max())))

    min_separation = max(8, round(span * 0.009))
    filtered: list[tuple[int, int]] = []
    for candidate in boundaries:
        if filtered and candidate[0] - filtered[-1][0] < min_separation:
            if candidate[1] > filtered[-1][1]:
                filtered[-1] = candidate
        else:
            filtered.append(candidate)
    return [coordinate for coordinate, _ in filtered]


def _vertical_rule_present(mask: np.ndarray, x: int, y0: int, y1: int) -> bool:
    margin = min(3, max(1, (y1 - y0) // 8))
    start, end = y0 + margin, y1 - margin
    if end <= start:
        start, end = y0, y1
    x0, x1 = max(0, x - 3), min(mask.shape[1], x + 4)
    strip = mask[start:end, x0:x1]
    if strip.size == 0:
        return False
    coverage = np.count_nonzero(np.any(strip > 0, axis=1)) / strip.shape[0]
    return coverage >= 0.48


def _horizontal_rule_present(mask: np.ndarray, y: int, x0: int, x1: int) -> bool:
    margin = min(3, max(1, (x1 - x0) // 8))
    start, end = x0 + margin, x1 - margin
    if end <= start:
        start, end = x0, x1
    y0, y1 = max(0, y - 3), min(mask.shape[0], y + 4)
    strip = mask[y0:y1, start:end]
    if strip.size == 0:
        return False
    coverage = np.count_nonzero(np.any(strip > 0, axis=0)) / strip.shape[1]
    return coverage >= 0.48


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def analyze_table_grid(image: np.ndarray) -> TableGrid:
    """Recover physical row/column rules and merged cell spans from the table image."""
    if image is None or image.size == 0:
        raise GridDetectionError("The cropped timetable image is empty.")
    rectified = _rectify(image)
    _, binary = _gray_threshold(rectified)
    horizontal_axis, vertical_axis, horizontal_segments, vertical_segments = _line_masks(binary)
    y_lines = _find_boundaries(horizontal_axis, axis=0)
    x_lines = _find_boundaries(vertical_axis, axis=1)
    height, width = rectified.shape[:2]

    if len(y_lines) < 3 or len(x_lines) < 3:
        raise GridDetectionError(
            "Could not read the timetable grid lines. Use a sharper image with visible horizontal and vertical rules."
        )
    if y_lines[0] > height * 0.08 or height - y_lines[-1] > height * 0.08:
        raise GridDetectionError("Could not locate the timetable's top and bottom borders.")
    if x_lines[0] > width * 0.08 or width - x_lines[-1] > width * 0.08:
        raise GridDetectionError("Could not locate the timetable's left and right borders.")

    row_count, column_count = len(y_lines) - 1, len(x_lines) - 1
    if row_count > 80 or column_count > 40 or row_count * column_count > 2000:
        raise GridDetectionError(
            f"The detected grid is unusually large ({row_count} rows × {column_count} columns). Check the crop."
        )
    if min(np.diff(y_lines)) < max(8, round(height * 0.008)):
        raise GridDetectionError("The row boundaries are too close together to separate reliably.")
    if min(np.diff(x_lines)) < max(8, round(width * 0.008)):
        raise GridDetectionError("The column boundaries are too close together to separate reliably.")

    components = _UnionFind(row_count * column_count)
    for row in range(row_count):
        y0, y1 = y_lines[row], y_lines[row + 1]
        for boundary in range(1, column_count):
            if not _vertical_rule_present(vertical_segments, x_lines[boundary], y0, y1):
                components.union(row * column_count + boundary - 1, row * column_count + boundary)
    for boundary in range(1, row_count):
        y = y_lines[boundary]
        for column in range(column_count):
            x0, x1 = x_lines[column], x_lines[column + 1]
            if not _horizontal_rule_present(horizontal_segments, y, x0, x1):
                components.union((boundary - 1) * column_count + column, boundary * column_count + column)

    groups: dict[int, list[tuple[int, int]]] = {}
    for row in range(row_count):
        for column in range(column_count):
            root = components.find(row * column_count + column)
            groups.setdefault(root, []).append((row, column))

    cells: list[GridCell] = []
    for positions in groups.values():
        row0 = min(row for row, _ in positions)
        row1 = max(row for row, _ in positions) + 1
        column0 = min(column for _, column in positions)
        column1 = max(column for _, column in positions) + 1
        if len(positions) != (row1 - row0) * (column1 - column0):
            raise GridDetectionError("The detected merged cell borders do not form rectangular cells. Check the crop.")
        cells.append(GridCell(
            row=row0,
            column=column0,
            rowspan=row1 - row0,
            colspan=column1 - column0,
            x=x_lines[column0],
            y=y_lines[row0],
            width=x_lines[column1] - x_lines[column0],
            height=y_lines[row1] - y_lines[row0],
        ))
    cells.sort(key=lambda cell: (cell.row, cell.column))
    return TableGrid(
        rectified,
        row_count,
        column_count,
        cells,
        [int(right - left) for left, right in zip(x_lines, x_lines[1:])],
        [int(bottom - top) for top, bottom in zip(y_lines, y_lines[1:])],
    )
