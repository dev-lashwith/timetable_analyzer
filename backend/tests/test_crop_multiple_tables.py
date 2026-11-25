import cv2
import numpy as np

from app.crop import detect_ruled_table_crops


def test_detects_separate_ruled_tables_on_one_page():
    image = np.full((900, 900, 3), 255, dtype=np.uint8)
    for y0, y1 in ((35, 385), (505, 855)):
        x0, x1 = 110, 790
        for x in (x0, 280, 450, 620, x1):
            cv2.line(image, (x, y0), (x, y1), (0, 0, 0), 2)
        for y in range(y0, y1 + 1, 70):
            cv2.line(image, (x0, y), (x1, y), (0, 0, 0), 2)

    crops = detect_ruled_table_crops(image)

    assert len(crops) == 2
    assert crops[0].y < crops[1].y
    assert all(crop.width < image.shape[1] and crop.height < image.shape[0] for crop in crops)
