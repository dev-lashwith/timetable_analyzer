from dataclasses import dataclass
from typing import Any


@dataclass
class TableValidationError(ValueError):
    message: str
    errors: list[str]

    def __str__(self) -> str:
        return self.message


def validate_and_complete_table(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """Check geometry, report structural problems, and explicitly fill omitted blanks."""
    if not isinstance(raw, dict):
        raise TableValidationError("The model response must be a JSON object.", ["Expected an object."])
    try:
        row_count = int(raw.get("row_count", raw.get("rows")))
        column_count = int(raw.get("column_count", raw.get("columns")))
    except (TypeError, ValueError):
        raise TableValidationError(
            "The model did not return row_count and column_count.",
            ["row_count and column_count must be integers."],
        )
    if not 1 <= row_count <= 80 or not 1 <= column_count <= 40 or row_count * column_count > 2000:
        raise TableValidationError(
            "The detected table dimensions are outside the supported range.",
            ["Supported tables have 1–80 rows, 1–40 columns, and at most 2,000 grid positions."],
        )

    def dimension_values(key: str, expected_length: int, default: int) -> list[int]:
        raw_values = raw.get(key)
        if raw_values is None:
            return [default] * expected_length
        if not isinstance(raw_values, list) or len(raw_values) != expected_length:
            raise TableValidationError(
                f"The extracted {key.replace('_', ' ')} do not match the detected grid.",
                [f"{key} must contain exactly {expected_length} positive pixel values."],
            )
        try:
            values = [int(value) for value in raw_values]
        except (TypeError, ValueError):
            raise TableValidationError(
                f"The extracted {key.replace('_', ' ')} are invalid.",
                [f"Every {key} entry must be a positive integer."],
            )
        if any(value < 1 or value > 5000 for value in values):
            raise TableValidationError(
                f"The extracted {key.replace('_', ' ')} are outside the supported range.",
                [f"Every {key} entry must be between 1 and 5,000 pixels."],
            )
        return values

    column_widths = dimension_values("column_widths", column_count, 100)
    row_heights = dimension_values("row_heights", row_count, 40)
    raw_cells = raw.get("cells")
    if not isinstance(raw_cells, list) or len(raw_cells) > 2000:
        raise TableValidationError("The model did not return a usable cells list.", ["cells must be an array."])

    cells: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw_cells):
        if not isinstance(item, dict):
            errors.append(f"Cell {index + 1} is not an object.")
            continue
        try:
            row = int(item.get("row"))
            column = int(item.get("column", item.get("col")))
            rowspan = int(item.get("rowspan", 1))
            colspan = int(item.get("colspan", 1))
        except (TypeError, ValueError):
            errors.append(f"Cell {index + 1} is missing a valid row or column position.")
            continue
        text = item.get("text", "")
        if text is None:
            text = ""
        elif not isinstance(text, str):
            text = str(text)
        if row < 0 or column < 0 or rowspan < 1 or colspan < 1:
            errors.append(f"Cell {index + 1} has a negative position or non-positive span.")
            continue
        if row + rowspan > row_count or column + colspan > column_count:
            errors.append(f"Cell {index + 1} extends beyond the declared table dimensions.")
            continue
        cells.append({
            "row": row,
            "column": column,
            "rowspan": rowspan,
            "colspan": colspan,
            "text": text,
        })
    if errors:
        raise TableValidationError("The extracted cell layout failed validation.", errors)

    occupied: dict[tuple[int, int], int] = {}
    for index, cell in enumerate(cells):
        for row in range(cell["row"], cell["row"] + cell["rowspan"]):
            for column in range(cell["column"], cell["column"] + cell["colspan"]):
                position = (row, column)
                if position in occupied:
                    errors.append(
                        f"Cells {occupied[position] + 1} and {index + 1} overlap at row {row + 1}, column {column + 1}."
                    )
                else:
                    occupied[position] = index
    if errors:
        raise TableValidationError("The extracted cell layout failed validation.", errors)

    missing = [(row, column) for row in range(row_count) for column in range(column_count) if (row, column) not in occupied]
    for row, column in missing:
        cells.append({"row": row, "column": column, "rowspan": 1, "colspan": 1, "text": ""})
    cells.sort(key=lambda cell: (cell["row"], cell["column"]))
    warnings: list[str] = []
    if missing:
        warnings.append(
            f"The model omitted {len(missing)} empty grid position(s); blank editable cells were added. Review the crop and layout."
        )
    unclear = sum("[unclear]" in cell["text"].lower() for cell in cells)
    if unclear:
        warnings.append(f"The model marked {unclear} cell(s) as unclear. Check them against the crop.")
    return {
        "row_count": row_count,
        "column_count": column_count,
        "column_widths": column_widths,
        "row_heights": row_heights,
        "cells": cells,
    }, warnings


def apply_cell_texts(table: dict[str, Any], raw: Any) -> tuple[dict[str, Any], list[str]]:
    """Attach OCR text by immutable grid-cell id without accepting model geometry."""
    if not isinstance(raw, dict):
        raise TableValidationError("The model response must be a JSON object.", ["Expected a texts array."])
    entries = raw.get("texts")
    if not isinstance(entries, list):
        raise TableValidationError("The model did not return a texts array.", ["Expected {\"texts\":[{\"id\":0,\"text\":\"...\"}]}."])

    lookup: dict[int, str] = {}
    warnings: list[str] = []
    errors: list[str] = []
    cell_count = len(table["cells"])
    unknown_ids = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            warnings.append(f"The model returned an unreadable text entry at position {index + 1}; it was left blank.")
            continue
        try:
            cell_id = int(entry.get("id"))
        except (TypeError, ValueError):
            warnings.append(f"The model returned a text entry without a valid id at position {index + 1}; it was ignored.")
            continue
        if not 0 <= cell_id < cell_count:
            unknown_ids += 1
            continue
        if cell_id in lookup:
            errors.append(f"The model returned cell id {cell_id} more than once.")
            continue
        text = entry.get("text", "")
        lookup[cell_id] = "" if text is None else text if isinstance(text, str) else str(text)
    if errors:
        raise TableValidationError("The extracted text failed validation.", errors)

    completed = {**table, "cells": [dict(cell) for cell in table["cells"]]}
    for cell_id, cell in enumerate(completed["cells"]):
        cell["text"] = lookup.get(cell_id, "")
    missing_ids = cell_count - len(lookup)
    if missing_ids:
        warnings.append(f"The model omitted text for {missing_ids} cell(s); those cells were left blank. Review the crop.")
    if unknown_ids:
        warnings.append(f"The model returned {unknown_ids} unknown cell id(s); they were ignored.")
    visible_ids = raw.get("visible_ids", [])
    if isinstance(visible_ids, list):
        blank_visible = sum(
            isinstance(cell_id, int) and cell_id in lookup and not lookup[cell_id].strip()
            for cell_id in visible_ids
        )
        if blank_visible:
            warnings.append(f"The model returned blank text for {blank_visible} cell(s) with visible marks. Check them against the crop.")
    return completed, warnings
