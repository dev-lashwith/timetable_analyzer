# Timetable Extractor

A small local-first app that finds and straightens a timetable box, detects its row, column, and merge geometry with OpenCV, and sends only that crop to an Ollama vision model to transcribe cell text. The editable result preserves blank cells and merged cells and can be exported as an `.xlsx` workbook.

## Project layout

- `frontend/` — Next.js and React interface
- `backend/` — FastAPI, OpenCV crop and grid detection, Ollama transcription, validation, and Excel export

## Requirements

- Node.js 20.9 or newer and npm
- Python 3.10 or newer
- Ollama running locally with a vision-capable model installed

The app does not choose a model for you. Select an image-capable Ollama model already installed in your instance and set its exact model name in `backend/.env`. The model transcribes text; OpenCV supplies the fixed row, column, and merge positions.

## Run locally

### 1. Configure Ollama

Copy `backend/.env.example` to `backend/.env`, then set `OLLAMA_MODEL` to an installed vision model name. Keep `OLLAMA_BASE_URL` pointed at the Ollama server (usually `http://localhost:11434`). Start Ollama before extracting a timetable.

The API health endpoint at `http://localhost:8000/api/health` reports whether Ollama is reachable, the configured model, and installed model names. A model must support image input; the app cannot reliably infer vision capability from the model list.

### 2. Start the API

From the repository root, create a virtual environment and install backend dependencies:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` to set `OLLAMA_MODEL`, then start the API:

```powershell
uvicorn app.main:app --reload --port 8000
```

### 3. Start the web app

In another terminal, from the repository root:

```powershell
cd frontend
npm install
Copy-Item .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`. `NEXT_PUBLIC_API_URL` can point the frontend to a different API address.

## Workflow

1. Upload or drag in a PNG, JPEG, or WebP image.
2. OpenCV crops and straightens the ruled table, then detects row boundaries, column boundaries, and merged cell spans. The crop preview shows the detected row/column/cell counts.
3. Review the crop and grid counts, then send only nonblank cell crops from the table to the configured Ollama model for text transcription.
4. Review or edit the cells in the table below the uploader.
5. Download an Excel workbook. Cell positions, empty cells, `rowspan`/`colspan` merges, and detected row/column proportions are carried into the sheet.

The backend rejects an image if it cannot identify a separate timetable crop rather than forwarding the full page. The model cannot add or change rows, columns, or merges. If it omits a cell's text, the API leaves that cell blank and shows a review warning. Grid overlaps, malformed JSON, missing models, and unreachable Ollama servers return clear errors.

## Validation

From the `backend/` directory, run the focused checks:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Limitations

- Crop detection targets printed or scanned timetables with visible horizontal and vertical rules. Skewed, curved, borderless, faint, or heavily decorated layouts may need manual preprocessing or a future crop adjustment step.
- OpenCV grid detection targets clear, ruled timetables. Faint, broken, curved, borderless, or tightly packed lines can produce incorrect boundaries; check the row and column counts in the crop preview.
- The vision model may misread small text or miss text in a cell. Review and edit the extracted table before using it; omitted text and unreadable cells are flagged.
- The editor preserves merged cell spans. This MVP does not provide controls for adding/removing rows, columns, or changing merge geometry.
- Excel styling is intentionally plain. The exported workbook preserves structure and text, not the original image's colors, fonts, or exact pixel dimensions.
- Images are handled locally by the frontend/backend and sent to the configured local Ollama server. No external vision service is called.
