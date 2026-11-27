import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "minicpm-v4.6:latest").strip() or "minicpm-v4.6:latest"
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "200"))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "100"))
STORAGE_ROOT = Path(
    os.getenv("TIMETABLE_STORAGE_DIR", str(Path(__file__).resolve().parents[1] / "data"))
).expanduser().resolve()
