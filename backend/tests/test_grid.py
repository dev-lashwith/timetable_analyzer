import cv2
import numpy as np

from app.grid import analyze_table_grid


def make_perspective_grid():
    width, height = 300, 240
    x_lines = [20, 80, 140, 200, 260]
    y_lines = [20, 65, 110, 155, 200]
    table = np.full((height, width, 3), 255, dtype=np.uint8)

    for boundary, y in enumerate(y_lines):
        for column in range(len(x_lines) - 1):
            if boundary == 1 and column < 2:
                continue
            if boundary == 2 and column == 2:
                continue
            cv2.line(table, (x_lines[column], y), (x_lines[column + 1], y), (0, 0, 0), 2)
    for row in range(len(y_lines) - 1):
        for boundary, x in enumerate(x_lines):
            if row == 0 and boundary == 1:
                continue
            cv2.line(table, (x, y_lines[row]), (x, y_lines[row + 1]), (0, 0, 0), 2)
    cv2.putText(table, "MERGED", (26, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)

    source = np.float32([[20, 20], [260, 20], [260, 200], [20, 200]])
    target = np.float32([[27, 15], [273, 24], [263, 216], [17, 203]])
    transform = cv2.getPerspectiveTransform(source, target)
    return cv2.warpPerspective(table, transform, (width, height), borderValue=(255, 255, 255))


def make_double_rule_grid(width: int, height: int, vertical: bool):
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    if vertical:
        x_lines = [40, 200, 400, 408, 600, 800, 1000, width - 40]
        y_lines = [30, height // 4, height // 2, 3 * height // 4, height - 30]
    else:
        x_lines = [40, width // 4, width // 2, 3 * width // 4, width - 40]
        y_lines = [30, 200, 400, 408, 600, 800, 1000, height - 30]
    for x in x_lines:
        cv2.line(image, (x, y_lines[0]), (x, y_lines[-1]), (0, 0, 0), 2)
    for y in y_lines:
        cv2.line(image, (x_lines[0], y), (x_lines[-1], y), (0, 0, 0), 2)
    return image


def test_merges_close_double_vertical_rules_on_wide_tables():
    grid = analyze_table_grid(make_double_rule_grid(1200, 600, vertical=True))

    assert grid.column_count == 6
    assert min(grid.column_widths) > 8


def test_merges_close_double_horizontal_rules_on_tall_tables():
    grid = analyze_table_grid(make_double_rule_grid(600, 1200, vertical=False))

    assert grid.row_count == 6
    assert min(grid.row_heights) > 8


def test_detects_grid_dimensions_and_merged_cells_from_rules():
    grid = analyze_table_grid(make_perspective_grid())
    assert grid.row_count == 4
    assert grid.column_count == 4
    assert len(grid.cells) == 12
    assert len(grid.column_widths) == grid.column_count
    assert len(grid.row_heights) == grid.row_count
    assert len(set(grid.column_widths)) > 1
    assert (0, 0, 2, 2) in {
        (cell.row, cell.column, cell.rowspan, cell.colspan) for cell in grid.cells
    }
    assert (1, 2, 2, 1) in {
        (cell.row, cell.column, cell.rowspan, cell.colspan) for cell in grid.cells
    }
