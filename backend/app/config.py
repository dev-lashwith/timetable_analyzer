import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

SARVAM_BASE_URL = os.getenv(
    "SARVAM_BASE_URL", "https://api.sarvam.ai/doc-ai/v1"
).rstrip("/")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
SARVAM_REQUEST_TIMEOUT_SECONDS = float(os.getenv("SARVAM_REQUEST_TIMEOUT_SECONDS", "60"))
SARVAM_POLL_INTERVAL_SECONDS = float(os.getenv("SARVAM_POLL_INTERVAL_SECONDS", "2"))
SARVAM_JOB_TIMEOUT_SECONDS = float(os.getenv("SARVAM_JOB_TIMEOUT_SECONDS", "900"))
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "200"))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "20"))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/timetable_extractor",
)
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(Path(__file__).resolve().parents[1] / "uploads")))
