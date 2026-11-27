import pytest

from app.ollama_client import OllamaError, _parse_faculty_response


def faculty_row(name="R. Kumar", abbreviation="RK"):
    return {"name": name, "abbreviation": abbreviation, "confidence": 0.9, "evidence": f"{abbreviation} - {name}"}


def test_parse_faculty_response_accepts_fenced_json_with_preamble():
    content = "Faculty table found:\n```json\n{\"faculty\": [{\"name\": \"R. Kumar\", \"abbreviation\": \"RK\", \"confidence\": 0.9, \"evidence\": \"RK - R. Kumar\"}]}\n```"

    assert _parse_faculty_response(content) == {"faculty": [faculty_row()]}


def test_parse_faculty_response_accepts_wrapped_and_python_style_objects():
    content = "Result: {'data': {'faculty': [{'name': 'R. Kumar', 'abbreviation': 'RK', 'confidence': 0.9, 'evidence': 'RK - R. Kumar'}]}}"

    assert _parse_faculty_response(content) == {"faculty": [faculty_row()]}


def test_parse_faculty_response_accepts_a_direct_list():
    assert _parse_faculty_response([faculty_row()]) == {"faculty": [faculty_row()]}


def test_parse_faculty_response_reports_missing_faculty_list():
    with pytest.raises(OllamaError, match="did not contain a faculty list"):
        _parse_faculty_response("{\"subjects\": []}")
