# Timetable Analyzer

A local-first timetable extraction app. The existing Next.js editor, OpenCV grid detection, Ollama vision client, and Excel export are retained. Uploaded PDFs are stored locally, split into page images, and checked for timetable crops. Uncertain crops can be reviewed and adjusted before extraction.

## Requirements

- Node.js 20.9 or newer and npm
- Python 3.10 or newer
- Ollama with the vision model `minicpm-v4.6:latest`
- Tesseract OCR installed and available on `PATH` for scanned PDFs. Digitally generated PDFs use their embedded positioned text without Tesseract.

Install the model once:

```powershell
ollama pull minicpm-v4.6:latest
```

## Run locally

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uvicorn app.main:app --reload --port 8000
```

If `backend/.env` already exists, keep it and check that `OLLAMA_MODEL=minicpm-v4.6:latest`. The example selects that model by default. Set `OLLAMA_BASE_URL` if Ollama is running elsewhere. Set `TIMETABLE_STORAGE_DIR` to move saved originals, page images, crops, and the SQLite database outside `backend/data`.

### Frontend

In another terminal:

```powershell
cd frontend
npm install
Copy-Item .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`. Set `NEXT_PUBLIC_API_URL` if the API uses a different address.

## MVP workflow

1. Enter class, stream, and section; semester, academic session, and room are optional metadata.
2. Upload a PDF. The original is retained and each page is rendered as its own PNG. OpenCV ranks table candidates using grid geometry and any positioned weekday text; low confidence or incomplete grids are marked for review.
3. Select a page and review its crop. Enter pixel coordinates to replace or refine an uncertain crop. The faculty legend is not sent to stage one.
4. Extract the timetable. OpenCV fixes row, column, and merged-cell geometry; the configured local Ollama model reads the cropped cell images. The result opens in the existing editable grid.
5. Save corrections or approve a version. The original AI extraction remains unchanged, and every later version is retained with its confidence and verification state. Excel export remains available.
6. After timetable extraction, the app analyzes that timetable's complete original source page with MiniCPM-V. Positioned PDF text, optional Tesseract OCR, and detected line layout support faculty-table recognition. The faculty-only table appears directly below the editable timetable with names, abbreviations, source page, confidence, evidence, and verification state. Use **Re-analyze faculty** to run it again, then mark the faculty values verified or in need of review.

## Storage and migrations

SQLite is used because the current application has no database or deployment service to reuse. Numbered SQL migrations live in `backend/migrations/` and run automatically on first API access. The default local store is:

```text
backend/data/
├── timetable_analyzer.sqlite3
└── <document-id>/
    ├── original.pdf
    ├── pages/page_0001.png
    └── crops/page_0001.png
```

The database keeps documents, page provenance, crop confidence, timetable metadata, immutable AI extractions, corrected/approved versions, whole-page entity results, and verification history. Storage is local and has no authentication; keep the data directory on a trusted machine.

## Validation

From `backend/`:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

From `frontend/`:

```powershell
npm run typecheck
npm run build
```

The API health endpoint is `http://localhost:8000/api/health`.

## MVP boundaries

- PDF ingestion currently supports up to 100 pages per file and uploads up to 20 MB.
- OpenCV is tuned for ruled timetable grids. Borderless, faint, or highly decorated layouts may need the manual crop review.
- Scanned page OCR requires the separate Tesseract executable. If it is unavailable, page analysis still receives the full image and geometric layout cues.
- The app records extraction confidence as a review aid; model confidence is not calibrated. Verify the original page before relying on extracted relationships.
- Excel export preserves cell text and merge geometry; it does not reproduce the source page's original styling.
