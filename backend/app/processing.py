from __future__ import annotations

from typing import Any

import numpy as np

from .grid import analyze_table_grid
from .ollama_client import OllamaError, extract_cell_texts
from .validation import apply_cell_texts, validate_and_complete_table


def decode_model_json(content: str) -> Any:
    import json

    candidate = content.strip()
    if candidate.startswith("```"):
        candidate = candidate.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as error:
        raise OllamaError(f"The model response was not valid JSON near character {error.pos}.") from error


async def extract_table_from_crop(image: np.ndarray, metadata: dict | None = None) -> tuple[dict, list[str], float]:
    grid = analyze_table_grid(image)
    content = await extract_cell_texts(grid.image, grid.cells)
    raw_texts = decode_model_json(content)
    geometry = {
        "row_count": grid.row_count,
        "column_count": grid.column_count,
        "column_widths": grid.column_widths,
        "row_heights": grid.row_heights,
        "cells": [
            {"row": cell.row, "column": cell.column, "rowspan": cell.rowspan,
             "colspan": cell.colspan, "text": ""}
            for cell in grid.cells
        ],
    }
    with_text, text_warnings = apply_cell_texts(geometry, raw_texts)
    table, warnings = validate_and_complete_table(with_text)
    table.update(metadata or {})
    warnings.extend(text_warnings)
    confidence = max(0.2, min(0.95, 0.9 - 0.07 * len(warnings)))
    return table, warnings, round(confidence, 3)
