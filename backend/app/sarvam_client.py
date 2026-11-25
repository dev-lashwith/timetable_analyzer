"""Client for the Sarvam doc Intelligence extraction API.

This is the only data-extraction provider used by the application. A document is
submitted once with the schema from :mod:`app.sarvam_schema`; the job is polled
until it reaches a terminal state and its JSON result is returned to the caller.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import requests

from .config import (
    SARVAM_API_KEY,
    SARVAM_BASE_URL,
    SARVAM_JOB_TIMEOUT_SECONDS,
    SARVAM_POLL_INTERVAL_SECONDS,
    SARVAM_REQUEST_TIMEOUT_SECONDS,
)
from .sarvam_schema import SCHEMA


TERMINAL_STATUSES = {"completed", "partially_completed", "failed", "rejected"}
SUCCESS_STATUSES = {"completed", "partially_completed"}


class SarvamError(RuntimeError):
    """Raised when the Sarvam API cannot produce a usable extraction."""


@dataclass
class SarvamExtraction:
    status: str
    data: dict[str, Any]
    raw: dict[str, Any]


def _headers() -> dict[str, str]:
    return {"api-subscription-key": SARVAM_API_KEY}


def _require_api_key() -> None:
    if not SARVAM_API_KEY:
        raise SarvamError(
            "Sarvam extraction is not configured. Set SARVAM_API_KEY in backend/.env."
        )


def _request(method: str, path: str, **kwargs: Any) -> requests.Response:
    try:
        response = requests.request(
            method,
            f"{SARVAM_BASE_URL}{path}",
            headers=_headers(),
            timeout=SARVAM_REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )
    except requests.RequestException as error:
        raise SarvamError(f"Could not reach the Sarvam API at {SARVAM_BASE_URL}: {error}") from error
    if not response.ok:
        raise SarvamError(
            f"Sarvam API returned HTTP {response.status_code}: {response.text[:500]}"
        )
    return response


def _decode_json(response: requests.Response, what: str) -> Any:
    try:
        return response.json()
    except ValueError as error:
        raise SarvamError(f"Sarvam returned an unreadable {what} response.") from error


def _unwrap_results(payload: Any) -> dict[str, Any]:
    """Accept both a bare result object and the common envelope keys."""
    if isinstance(payload, list):
        return {"items": payload}
    if not isinstance(payload, dict):
        raise SarvamError("Sarvam returned an unexpected results payload.")
    for key in ("extracted_data", "extracted_json", "data", "result", "results", "output"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def submit_extraction_job(files: list[tuple[str, bytes, str]]) -> str:
    """Send one or more documents to Sarvam and return the job id."""
    _require_api_key()
    if not files:
        raise SarvamError("No document was supplied to Sarvam.")
    response = _request(
        "POST",
        "/job/extract",
        data={"schema": json.dumps(SCHEMA)},
        files=[("file", (name, content, mime)) for name, content, mime in files],
    )
    payload = _decode_json(response, "job submission")
    job_id = payload.get("job_id") if isinstance(payload, dict) else None
    if not job_id:
        raise SarvamError("Sarvam did not return a job id for the extraction request.")
    return str(job_id)


def get_job_status(job_id: str) -> str:
    payload = _decode_json(_request("GET", f"/job/{job_id}/status"), "job status")
    if not isinstance(payload, dict):
        raise SarvamError("Sarvam returned an unexpected job status.")
    status = payload.get("status") or payload.get("state")
    if not status:
        raise SarvamError("Sarvam's job status response did not include a status.")
    return str(status).casefold()


def get_job_results(job_id: str) -> Any:
    return _decode_json(_request("GET", f"/job/{job_id}/results"), "job results")


def extract_documents(files: list[tuple[str, bytes, str]]) -> SarvamExtraction:
    """Submit, wait for, and read one Sarvam extraction job."""
    job_id = submit_extraction_job(files)
    deadline = time.monotonic() + max(1.0, SARVAM_JOB_TIMEOUT_SECONDS)
    while True:
        status = get_job_status(job_id)
        if status in TERMINAL_STATUSES:
            break
        if time.monotonic() >= deadline:
            raise SarvamError(
                f"Sarvam extraction job {job_id} is still {status} after "
                f"{SARVAM_JOB_TIMEOUT_SECONDS:g} seconds."
            )
        time.sleep(max(0.1, SARVAM_POLL_INTERVAL_SECONDS))

    raw = get_job_results(job_id)
    if status not in SUCCESS_STATUSES:
        detail = ""
        if isinstance(raw, dict):
            detail = str(raw.get("message") or raw.get("error") or raw.get("detail") or "")[:500]
        raise SarvamError(f"Sarvam extraction job {job_id} {status}. {detail}".strip())
    return SarvamExtraction(status=status, data=_unwrap_results(raw), raw=raw)


async def extract_documents_async(files: list[tuple[str, bytes, str]]) -> SarvamExtraction:
    """Non-blocking wrapper for FastAPI endpoints."""
    return await asyncio.to_thread(extract_documents, files)


async def sarvam_status() -> dict[str, Any]:
    """Configuration summary for /api/health; no extraction is performed here."""
    return {
        "provider": "sarvam",
        "base_url": SARVAM_BASE_URL,
        "api_key_configured": bool(SARVAM_API_KEY),
        "configured": bool(SARVAM_API_KEY),
    }
