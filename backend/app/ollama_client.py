import asyncio
import base64
import ast
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np

from .config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS
from .grid import GridCell


class OllamaError(RuntimeError):
    pass


EXTRACTION_PROMPT = (
    "This image is a crop of one timetable cell. Transcribe exactly the text visible in this cell. "
    "Output only the text, preserving punctuation and line breaks. Do not add a label or explanation. "
    "If the cell is blank, output [blank]. If the text cannot be read, output [unclear]."
)


def _cell_crop(image: np.ndarray, cell: GridCell) -> tuple[bytes, bool]:
    height, width = image.shape[:2]
    inset_x = min(8, max(4, round(cell.width * 0.06)))
    inset_y = min(8, max(4, round(cell.height * 0.08)))
    inner_x0 = max(0, cell.x + inset_x)
    inner_y0 = max(0, cell.y + inset_y)
    inner_x1 = min(width, cell.x + cell.width - inset_x)
    inner_y1 = min(height, cell.y + cell.height - inset_y)
    if inner_x1 <= inner_x0 or inner_y1 <= inner_y0:
        inner_x0, inner_y0 = cell.x, cell.y
        inner_x1, inner_y1 = cell.x + cell.width, cell.y + cell.height
    interior = image[inner_y0:inner_y1, inner_x0:inner_x1]
    gray = cv2.cvtColor(interior, cv2.COLOR_BGR2GRAY)
    block_size = min(31, max(5, (min(gray.shape[:2]) // 3) | 1))
    ink = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gray, (3, 3), 0),
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        6,
    )
    visible_text = cv2.countNonZero(ink) >= max(7, round(gray.size * 0.002))
    if not visible_text:
        return b"", False

    # Keep the full cell in the OCR crop; some timetable headers align symbols at the rule edge.
    roi = image[cell.y:cell.y + cell.height, cell.x:cell.x + cell.width]
    max_side = max(roi.shape[:2])
    scale = min(6.0, max(1.5, 480 / max(1, max_side)))
    enlarged = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    padded = cv2.copyMakeBorder(enlarged, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    success, encoded = cv2.imencode(".png", padded)
    if not success:
        return b"", False
    return encoded.tobytes(), True


def _call_ollama(cell_image: bytes) -> str:
    if not OLLAMA_MODEL:
        raise OllamaError(
            "No Ollama vision model is configured. Set OLLAMA_MODEL in backend/.env to a model installed in your Ollama instance."
        )
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 256},
        "messages": [{
            "role": "user",
            "content": EXTRACTION_PROMPT,
            "images": [base64.b64encode(cell_image).decode("ascii")],
        }],
    }
    request = Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        if error.code == 404:
            raise OllamaError(
                f"Ollama could not find model '{OLLAMA_MODEL}'. Check the name and pull a vision model first. {detail}"
            ) from error
        raise OllamaError(f"Ollama returned HTTP {error.code}: {detail}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise OllamaError(
            f"Could not reach Ollama at {OLLAMA_BASE_URL}. Start Ollama and check OLLAMA_BASE_URL."
        ) from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OllamaError("Ollama returned an unreadable response.") from error

    try:
        content = result["message"]["content"]
    except (KeyError, TypeError) as error:
        raise OllamaError("Ollama's response did not contain message.content.") from error
    if not isinstance(content, str) or not content.strip():
        if result.get("message", {}).get("thinking"):
            raise OllamaError(
                "The selected model returned reasoning but no final cell transcription. "
                "Try a vision model that follows JSON output instructions."
            )
        raise OllamaError("Ollama returned an empty extraction.")
    return content


PAGE_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "faculty": {"type": "array", "items": {"$ref": "#/$defs/faculty"}},
    },
    "required": ["faculty"],
    "additionalProperties": False,
    "$defs": {
        "faculty": {
            "type": "object", "properties": {
                "name": {"type": "string"}, "abbreviation": {"type": "string"},
                "confidence": {"type": "number"}, "evidence": {"type": "string"},
            }, "required": ["name", "abbreviation", "confidence", "evidence"], "additionalProperties": False,
        },
    },
}


def _parse_faculty_response(content: object) -> dict:
    """Accept JSON, fenced JSON, or a JSON object embedded in model prose."""
    if isinstance(content, dict):
        parsed: object = content
    elif isinstance(content, list):
        if all(isinstance(item, dict) for item in content):
            parsed = {"faculty": content}
        else:
            content = "\n".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
            parsed = None
    else:
        parsed = None

    if parsed is None:
        if not isinstance(content, str) or not content.strip():
            raise OllamaError("Ollama returned empty faculty data.")
        candidate = re.sub(r"<think>.*?</think>", "", content.strip(), flags=re.DOTALL).strip()
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE).strip()
        decoder = json.JSONDecoder()
        candidates = [candidate]
        candidates.extend(candidate[index:] for index, char in enumerate(candidate) if char in "{[")
        for fragment in candidates:
            try:
                parsed, _ = decoder.raw_decode(fragment)
                break
            except json.JSONDecodeError:
                continue
        if parsed is None:
            for fragment in candidates:
                try:
                    parsed = ast.literal_eval(fragment)
                    break
                except (SyntaxError, ValueError):
                    continue

    if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        parsed = {"faculty": parsed}
    if isinstance(parsed, dict):
        for wrapper in ("data", "result", "output"):
            nested = parsed.get(wrapper)
            if isinstance(nested, dict) and "faculty" in nested:
                parsed = nested
                break
        if "faculty" not in parsed and isinstance(parsed.get("faculty_members"), list):
            parsed = {"faculty": parsed["faculty_members"]}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("faculty"), list):
        raise OllamaError("Ollama response did not contain a faculty list. Re-analyze the source page.")
    return parsed


def _extract_page_entities(image: np.ndarray, ocr_layout: dict) -> dict:
    if not OLLAMA_MODEL:
        raise OllamaError("Set OLLAMA_MODEL to minicpm-v4.6:latest in backend/.env.")
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise OllamaError("Could not encode the original page for whole-page analysis.")
    evidence = {
        "ocr_source": ocr_layout.get("source"),
        "ocr_text": str(ocr_layout.get("text", ""))[:6000],
        "ocr_word_positions": ocr_layout.get("words", [])[:500],
        "layout": ocr_layout.get("layout", {}),
    }
    prompt = (
        "Analyze the complete original source page and extract faculty table data only. Ignore the timetable schedule, subjects, "
        "course codes, rooms, class details, and unrelated page text. Find the separate faculty/instructor list or legend wherever "
        "it appears on the page, including below, beside, or above the timetable. For each distinct row, extract the faculty name "
        "and its visible abbreviation. Preserve an abbreviation even if the full name is unreadable; leave an unknown field empty. "
        "Do not infer faculty from timetable cells or invent names/abbreviations. Use positioned OCR words to read small text and "
        "verify each row against the page image. Return each faculty entry once, with a confidence from 0 to 1 and a short evidence "
        "snippet from the faculty table.\nSupporting OCR and layout evidence:\n"
        + json.dumps(evidence, ensure_ascii=False)
    )
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "format": PAGE_EXTRACTION_SCHEMA,
        "options": {"temperature": 0, "num_predict": 4096},
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [base64.b64encode(encoded.tobytes()).decode("ascii")],
        }],
    }
    request = Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            response_body = response.read().decode("utf-8")
        result = json.loads(response_body)
        if not isinstance(result, dict):
            raise OllamaError("Ollama returned an invalid chat response envelope.")
        if result.get("error"):
            raise OllamaError(f"Ollama could not analyze the source page: {result['error']}")
        message = result.get("message")
        content = message.get("content") if isinstance(message, dict) else result.get("response")
        return _parse_faculty_response(content)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        if error.code == 404:
            raise OllamaError(f"Ollama could not find model '{OLLAMA_MODEL}'. Run `ollama pull {OLLAMA_MODEL}`. {detail}") from error
        raise OllamaError(f"Ollama returned HTTP {error.code}: {detail}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise OllamaError(f"Could not reach Ollama at {OLLAMA_BASE_URL}. Start Ollama and check OLLAMA_BASE_URL.") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OllamaError("Ollama returned an invalid whole-page response. Re-analyze the source page.") from error


async def extract_page_entities(image: np.ndarray, ocr_layout: dict) -> dict:
    return await asyncio.to_thread(_extract_page_entities, image, ocr_layout)


def _transcribe_cells(image: np.ndarray, cells: list[GridCell]) -> str:
    blank_ids: list[int] = []
    visible_cells: list[tuple[int, bytes]] = []
    for cell_id, cell in enumerate(cells):
        cell_image, visible_text = _cell_crop(image, cell)
        if visible_text:
            visible_cells.append((cell_id, cell_image))
        else:
            blank_ids.append(cell_id)

    texts: dict[int, str] = {cell_id: "" for cell_id in blank_ids}
    visible_ids = [cell_id for cell_id, _ in visible_cells]
    for cell_id, cell_image in visible_cells:
        content = _call_ollama(cell_image).strip()
        if content.lower() in {"[blank]", "blank", "[empty]", "empty"}:
            content = ""
        texts[cell_id] = content
    result = {
        "texts": [{"id": cell_id, "text": texts[cell_id]} for cell_id in sorted(texts)],
        "visible_ids": visible_ids,
    }
    return json.dumps(result, ensure_ascii=False)


async def extract_cell_texts(image: np.ndarray, cells: list[GridCell]) -> str:
    return await asyncio.to_thread(_transcribe_cells, image, cells)


async def ollama_status() -> dict:
    def read_models() -> list[str] | None:
        request = Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        try:
            with urlopen(request, timeout=2) as response:
                result = json.loads(response.read().decode("utf-8"))
            return [model.get("name", "") for model in result.get("models", []) if model.get("name")]
        except Exception:
            return None

    models = await asyncio.to_thread(read_models)
    return {
        "ollama_reachable": models is not None,
        "base_url": OLLAMA_BASE_URL,
        "configured_model": OLLAMA_MODEL or None,
        "installed_models": models or [],
    }
