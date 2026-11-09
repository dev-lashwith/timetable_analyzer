import asyncio
import pytest
from io import BytesIO

from app.main import Table, export
from app.validation import TableValidationError, apply_cell_texts, validate_and_complete_table


def test_fills_omitted_empty_positions_and_keeps_merges():
    table, warnings = validate_and_complete_table({
        "row_count": 2,
        "column_count": 2,
        "cells": [
            {"row": 0, "column": 0, "rowspan": 1, "colspan": 2, "text": "Monday"},
            {"row": 1, "column": 0, "text": "09:00"},
        ],
    })
    assert table["cells"][0]["colspan"] == 2
    assert table["cells"][-1] == {"row": 1, "column": 1, "rowspan": 1, "colspan": 1, "text": ""}
    assert len(warnings) == 1


def test_rejects_overlapping_cells():
    with pytest.raises(TableValidationError, match="failed validation"):
        validate_and_complete_table({
            "row_count": 1,
            "column_count": 2,
            "cells": [
                {"row": 0, "column": 0, "colspan": 2, "text": "Merged"},
                {"row": 0, "column": 1, "text": "Overlap"},
            ],
        })


def test_rejects_cells_outside_grid():
    with pytest.raises(TableValidationError, match="failed validation"):
        validate_and_complete_table({
            "row_count": 1,
            "column_count": 1,
            "cells": [{"row": 1, "column": 0, "text": "Outside"}],
        })


def test_text_assignment_cannot_change_detected_geometry():
    detected = {
        "row_count": 1,
        "column_count": 2,
        "cells": [{"row": 0, "column": 0, "rowspan": 1, "colspan": 2, "text": ""}],
    }
    result, warnings = apply_cell_texts(detected, {
        "row_count": 99,
        "column_count": 99,
        "cells": [{"row": 0, "column": 0, "text": "wrong geometry"}],
        "texts": [{"id": 0, "text": "Merged class"}],
    })
    assert result == {
        "row_count": 1,
        "column_count": 2,
        "cells": [{"row": 0, "column": 0, "rowspan": 1, "colspan": 2, "text": "Merged class"}],
    }
    assert warnings == []


def test_xlsx_export_preserves_merged_and_empty_cells():
    from openpyxl import load_workbook

    async def make_export():
        response = await export(Table(
            row_count=2,
            column_count=2,
        column_widths=[70, 140],
        row_heights=[30, 50],
            cells=[
                {"row": 0, "column": 0, "rowspan": 1, "colspan": 2, "text": "Monday"},
                {"row": 1, "column": 0, "text": "09:00"},
                {"row": 1, "column": 1, "text": ""},
            ],
        ))
        return b"".join([part async for part in response.body_iterator])

    payload = asyncio.run(make_export())
    workbook = load_workbook(BytesIO(payload))
    sheet = workbook["Timetable"]
    assert "A1:B1" in {str(merged) for merged in sheet.merged_cells.ranges}
    assert sheet["A1"].value == "Monday"
    assert sheet["A2"].value == "09:00"
    assert sheet["B2"].value is None
    assert sheet.column_dimensions["A"].width == 10
    assert sheet.column_dimensions["B"].width == 20
    assert sheet.row_dimensions[1].height == 22.5
