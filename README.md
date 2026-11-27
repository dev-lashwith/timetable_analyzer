# Timetable Analyzer

Timetable Analyzer is a local-first application for turning timetable PDFs into editable, reviewable timetable data. It keeps the source PDF and page images, detects timetable regions with OpenCV, reads cropped timetable cells with a local Ollama vision model, and lets you correct, approve, export, and inspect the resulting data.

Faculty information is analyzed as a separate step after timetable extraction. That analysis uses the full original page so the faculty legend is not lost when the timetable itself is cropped.

## Features

- Upload and retain the original PDF; render and store its pages individually.
- Automatically find likely timetable regions with OpenCV and flag uncertain crops for review.
- Adjust a crop manually when automatic detection misses part of the timetable or selects the wrong region.
- Extract the timetable from the cropped image with `minicpm-v4.6:latest` running locally in Ollama.
- Review and edit the timetable in a grid that preserves detected rows, columns, and merged cells.
- Keep the original AI extraction separate from corrected and approved timetable versions.
- Analyze the complete original source page for faculty names and abbreviations after extracting a timetable.
- Review faculty entries in a separate table, including source page, confidence, evidence, and verification status.
- See every distinct timetable-cell value and extracted teacher name below the timetable, then classify values with teacher and subject dropdowns.
- View, copy, or download JSON for the current editable timetable and for the latest faculty extraction.
- Export the timetable and its class details to an Excel workbook.
- Store documents, page images, crops, timetable versions, faculty extractions, and verification history locally in SQLite and the document storage folder.

## How extraction works

1. Enter any known class details. Class, stream, and section are supported, along with optional semester, academic session, and room information.
2. Upload a PDF. The app stores the original file and renders each page to an image. OpenCV looks for ruled table geometry and uses available positioned PDF text to help rank timetable crop candidates.
3. Select a page and check its crop. Low-confidence or incomplete detections require review. Adjust the crop coordinates if needed and apply the crop before continuing.
4. Extract the timetable. OpenCV analyzes grid geometry, including merged cells, and the configured local Ollama vision model reads the cropped cell images. The result opens in the editable timetable grid.
5. Correct cells and details. For a saved timetable, use **Save corrections** to create a corrected version or **Approve timetable** to create an approved version. The original AI version remains stored separately.
6. After a timetable is available, choose **Analyze faculty table**. MiniCPM-V analyzes the complete original page, with positioned PDF text or optional Tesseract OCR and line-layout cues as supporting information. Faculty results appear in their own table below the timetable. Re-run the analysis or mark its latest results as verified or needing review.
7. Review the distinct-values table. It combines values found in timetable cells with names extracted from the faculty table. Use the teacher and subject dropdowns to classify values; a value cannot be in both lists at once.
8. Use **View timetable JSON** to inspect, copy, or download the current editor data. Use the faculty section's **View JSON** option to inspect, copy, or download the latest faculty extraction. Excel export is available below the editor.

### What the JSON views contain

- **Timetable JSON** reflects the timetable currently displayed in the editor, along with its record type, timetable ID when available, source document and page when available, and verification status. It follows unsaved cell edits. Saving corrections or approving a timetable creates a stored version; the initial AI extraction is retained separately in the database.
- **Faculty JSON** reflects the latest full-page faculty extraction and includes its source page, model, prompt version, confidence, verification status, OCR source, and extracted faculty data.
- **Copy JSON** copies the formatted JSON to the clipboard. **Download JSON** creates a standalone `.json` file for sharing or inspection. These downloads are exports; the application stores its records in its local database.

The current faculty-only analysis produces faculty names and abbreviations. Teacher options include those extracted names and timetable values; subject options come from timetable values. These teacher/subject classifications are currently held in the open editor session and are not stored as a separate database record. Check values against the source before relying on them.

## Technology

- **Frontend:** Next.js 16, React 19, and TypeScript.
- **Backend:** FastAPI on Python, with OpenCV, PyMuPDF, and SQLite.
- **Vision model:** Ollama running the local `minicpm-v4.6:latest` model. No Sarvam AI integration is required.
- **OCR:** Embedded positioned text is used for digitally generated PDFs. Tesseract is an optional executable dependency for OCR of scanned pages.
- **Export:** Excel workbooks are generated with `openpyxl`.

## Requirements

- Windows PowerShell (commands below), or equivalent Python and Node.js environments.
- Python 3.10 or newer and `pip`.
- Node.js 20.9 or newer and npm.
- Ollama installed and running locally, with the `minicpm-v4.6:latest` vision model available.
- Tesseract OCR on `PATH` for OCR support on scanned PDFs. The app can still send the page image and geometric layout cues to the model without Tesseract.

Download the model once:

```powershell
ollama pull minicpm-v4.6:latest
```

If Ollama does not start automatically with Windows, run `ollama serve` in a separate terminal. Keep it running while using the application.

## Run locally

Start the backend first.

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uvicorn app.main:app --reload --port 8000
```

The API is available at `http://localhost:8000`; its health and Ollama status endpoint is `http://localhost:8000/api/health`.

### Frontend

Open another terminal from the project root:

```powershell
cd frontend
npm ci
if (-not (Test-Path .env.local)) { Copy-Item .env.local.example .env.local }
npm run dev
```

Open `http://localhost:3000`. The sample frontend configuration points to `http://localhost:8000`. If the backend runs at another address, set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` and restart the frontend.

## Configuration

Backend settings are read from `backend/.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Base URL of the local Ollama server. |
| `OLLAMA_MODEL` | `minicpm-v4.6:latest` | Model used for timetable and faculty extraction. |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | Request timeout for model calls. |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Allowed frontend origin; multiple origins can be comma-separated. |
| `PDF_RENDER_DPI` | `200` | Resolution used to render PDF pages. |
| `MAX_PDF_PAGES` | `100` | Maximum number of pages in an uploaded PDF. |
| `TIMETABLE_STORAGE_DIR` | `backend/data` | Directory for the SQLite database and saved document files. |

Frontend settings are read from `frontend/.env.local`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | URL of the FastAPI backend. |

The API limits uploads to 20 MB and decoded images to 40 megapixels. Increase storage capacity or adjust deployment settings in the backend configuration if your documents need more space or have more pages.

## Local storage and data versions

The default storage directory is `backend/data/`. Set `TIMETABLE_STORAGE_DIR` to move it elsewhere. A document folder contains the retained PDF, rendered page images, and timetable crops. SQLite stores document/page provenance, crop coordinates and confidence, timetable metadata, versioned timetable JSON, page-level faculty extractions, and verification history.

The database is initialized on the first API request that needs it, and numbered SQL migrations under `backend/migrations/` are applied automatically. The first migration is `0001_document_timetable_store.sql`.

Typical layout:

```text
backend/data/
├── timetable_analyzer.sqlite3
└── <document-id>/
    ├── original.pdf
    ├── pages/
    │   ├── page_0001.png
    │   └── page_0002.png
    └── crops/
        └── page_0001.png
```

Each timetable version records whether it came from the original AI extraction, a correction, or approval. Faculty extraction records keep their own model, prompt version, OCR/layout source, confidence, and verification status. The source PDF and page number remain linked to both kinds of extraction.

This is a local application with no authentication. Keep the storage directory on a trusted computer and back it up if the extracted records matter.

## API overview

The interactive frontend uses these main FastAPI routes:

| Method and route | Purpose |
| --- | --- |
| `GET /api/health` | Check backend and Ollama availability. |
| `POST /api/documents/upload` | Store a PDF, render its pages, and register crop candidates. |
| `GET /api/documents` | List uploaded documents. |
| `GET /api/timetables` | List saved timetable pages and their latest status. |
| `GET /api/timetables/{id}` | Load a timetable, source-page details, and extraction records. |
| `POST /api/pages/{id}/crop` | Save a manually reviewed timetable crop. |
| `POST /api/timetables/{id}/extract` | Extract and store a new original AI timetable version. |
| `PUT /api/timetables/{id}` | Save a corrected timetable version. |
| `POST /api/timetables/{id}/approve` | Save an approved timetable version. |
| `POST /api/timetables/{id}/analyze-page` | Analyze the original page for faculty entries. |
| `POST /api/timetables/{id}/page-extraction/verify` | Mark the latest faculty extraction verified or needing review. |
| `POST /api/export` | Download a timetable as an Excel workbook. |

The legacy one-shot image/PDF preview and extraction routes, `POST /api/preview` and `POST /api/extract`, are also available.

## Development checks

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

## Troubleshooting

- **Ollama is unavailable:** Check that Ollama is running, `OLLAMA_BASE_URL` is correct, and `ollama list` shows `minicpm-v4.6:latest`. Check `http://localhost:8000/api/health` after starting the backend.
- **Model missing or different:** Run `ollama pull minicpm-v4.6:latest`, or set `OLLAMA_MODEL` to the exact installed vision-model tag and restart the backend.
- **Model response cannot be read:** Check the backend terminal for the extraction error. Confirm the selected Ollama model supports image input and that the configured model name is correct. A larger or unusually dense source image may require a reviewed crop or another extraction attempt.
- **Crop is wrong or needs review:** Select the source page, adjust the crop to include only the timetable, and apply it before extracting. Do not include a separate faculty legend in the timetable crop; faculty analysis reads the full source page later.
- **Faculty table is empty or incomplete:** Confirm timetable extraction has completed, then run **Analyze faculty table**. For scanned PDFs, install Tesseract and make sure `tesseract` is available on `PATH`. Review the source page and mark uncertain entries as needing review.
- **Frontend cannot reach the API:** Confirm the backend is running on port 8000 and `NEXT_PUBLIC_API_URL` points to it. Restart Next.js after changing `.env.local`.

## Known limitations

- The primary upload flow is designed for PDFs; the API also retains one-shot image/PDF routes for preview and extraction.
- PDFs are limited to 100 pages and uploads to 20 MB by default.
- Automatic crop detection works best with ruled timetable grids. Borderless, faint, skewed, or heavily decorated layouts may need manual crop adjustment.
- Scanned-page OCR depends on the separate Tesseract executable. Without it, full-page vision and geometric cues remain available, but text-based OCR support is not.
- Extraction confidence is a review aid and is not calibrated. Check names, abbreviations, and cell text against the source before relying on them.
- The faculty step extracts faculty names and abbreviations from the page; it does not currently establish faculty-to-subject relationships automatically. Use the teacher and subject classification controls to review extracted values.
- Excel export preserves cell text and merge geometry, not the visual styling of the original PDF.
