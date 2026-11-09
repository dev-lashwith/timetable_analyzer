import cv2
import numpy as np
import pytest

from app.crop import CropDetectionError, detect_timetable_crop


def make_test_page():
    page = np.full((700, 900, 3), 255, dtype=np.uint8)
    x0, y0, x1, y1 = 130, 115, 770, 590
    for x in [x0, 260, 390, 515, 640, x1]:
        cv2.line(page, (x, y0), (x, y1), (0, 0, 0), 2)
    for y in [y0, 185, 265, 345, 425, 505, y1]:
        cv2.line(page, (x0, y), (x1, y), (0, 0, 0), 2)
    cv2.putText(page, "MONDAY", (145, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 1)
    return page, (x0, y0, x1, y1)


def test_crops_table_region_and_excludes_page_margins():
    page, (x0, y0, x1, y1) = make_test_page()
    crop = detect_timetable_crop(page)
    assert crop.x >= x0 - 12 and crop.y >= y0 - 12
    assert crop.x + crop.width <= x1 + 12
    assert crop.y + crop.height <= y1 + 12
    assert crop.width * crop.height < page.shape[0] * page.shape[1] * 0.65


def test_fails_when_no_ruled_table_is_found():
    with pytest.raises(CropDetectionError, match="Could not find a timetable box"):
        detect_timetable_crop(np.full((600, 800, 3), 255, dtype=np.uint8))
