# Timetable Extractor

A timetable extraction app backed entirely by the Sarvam doc Intelligence API. The archive stores original department PDFs, sends each document to Sarvam once, and maps the returned JSON into editable timetables with review and publication status in PostgreSQL. No local models, OCR models, or other extraction providers are used. Published timetables can be found through dependent Semester → Class → Academic year/session → Room filters and downloaded as JSON.

The Manual crop editor remains available for the existing image/PDF crop review, cell editing, merged-cell handling, and Excel export workflow.

## Project layout

- `frontend/` — Next.js and React archive UI plus the original manual crop editor
- `backend/` — FastAPI, Sarvam doc-AI client and JSON mapping, OpenCV previews only, PostgreSQL models, migrations, archive API
- `backend/uploads/` — retained source PDFs (created on first upload; excluded from source control)
- `docker-compose.yml` — local PostgreSQL 16 service

## Requirements

- Node.js 20.9 or newer and npm
- Python 3.10 or newer
- Docker Desktop or a PostgreSQL 14+ server
- A Sarvam API subscription key with access to the doc Intelligence API

## Run locally

### 1. Start PostgreSQL

From the repository root:

```powershell
docker compose up -d db
```

This starts a local database named `timetable_extractor` on port 5432. If using another PostgreSQL server, set `DATABASE_URL` in `backend/.env`.

### 2. Configure and migrate the API

From the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `SARVAM_API_KEY` in `backend/.env`. The default `SARVAM_BASE_URL` points to `https://api.sarvam.ai/doc-ai/v1`. The default `DATABASE_URL` matches the included Docker Compose database. `STORAGE_DIR` defaults to `backend/uploads` when the API is launched from `backend/`.

Apply the PostgreSQL schema migration and start the API:

```powershell
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

The API health check is at `http://localhost:8000/api/health` (also available at `http://localhost:8000/health`). `GET /v1/models` returns a minimal OpenAI-compatible listing that identifies Sarvam doc AI as the configured extraction provider; no local models are exposed.

### 3. Start the web app

In another terminal, from the repository root:

```powershell
cd frontend
npm install
Copy-Item .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`. `NEXT_PUBLIC_API_URL` can point the frontend to another API address.

## Archive workflow

1. Upload a department PDF. The API saves the original file, its hash, and upload status to PostgreSQL before returning.
2. A background task submits the PDF once to Sarvam doc AI with the configured extraction schema, polls the job, and reads its JSON result. `app/sarvam_mapping.py` converts `weekly_schedule`, `time_slot`, and `department_and_academic_information` into editable day/time grids and header metadata. No local OCR or model inference is involved.
3. Review each returned timetable, its Sarvam metadata, warnings, source page, and the JSON-backed cell text. Faculty-allocation data is not imported into the main timetables. Cell coordinates, spans, raw text, normalized text, and page references are retained.
4. Save review changes, verify the required semester/class/academic year metadata, then publish. The document and tables move through `queued`, `processing`, `review`, `verified`, and `published` states; failed uploads or extraction attempts are marked `failed` with a message.
5. Download the document JSON or browse published timetables with dependent filters: Semester → Class → Academic year/session → Room. The session field represents the academic year.

### Persistence model

- Original PDFs are kept in `STORAGE_DIR`; PostgreSQL stores the path, filename, content hash, upload status, and page count.
- Normalized PostgreSQL tables store academic years, semesters, class groups, rooms, shared cell text, common time slots, timetable records, and cell geometry/text. Faculty and faculty-allocation tables remain in the schema for compatibility with older records, but the archive does not import or display faculty-allocation grids.
- JSON exports include each page/table, metadata, merged-cell geometry, raw and normalized cell text, cell coordinates, and page references.

## API additions

- `POST /api/documents` — store a PDF and queue background processing
- `GET /api/documents` and `GET /api/documents/{id}` — poll document and table status
- `GET /api/documents/{id}/original` — download the retained PDF
- `GET /api/documents/{id}/json` — download the extracted JSON
- `DELETE /api/documents/{id}` — delete a stored PDF and all of its extracted tables; processing documents cannot be deleted
- `PATCH /api/timetables/{id}` — save metadata and cell review changes
- `POST /api/timetables/{id}/verify` and `/publish` — move a reviewed table through approval states
- `GET /api/options` and `GET /api/timetables/search` — retrieve dependent filter choices and matches
- `GET /api/timetables/{id}` — display one published table

The original `/api/discover`, `/api/extract-many`, `/api/export`, and `/api/export-all` endpoints remain available to the Manual crop editor.

## Tests

From `backend/`, install the development dependencies and run the suite:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```

The suite covers the existing crop/grid/export flow, multi-table detection, metadata normalization, and review-to-publish filtering through an isolated test database. The running app uses PostgreSQL after applying the migration.

## Current limitations

- Background work runs in the FastAPI process. A server restart can interrupt an in-flight PDF; run one API worker for this local MVP.
- Table detection targets separate, visibly ruled tables. Borderless, faint, skewed, crowded, or joined tables may need manual preprocessing. The original manual crop editor remains available for those cases.
- Extraction depends on the remote Sarvam API and a valid `SARVAM_API_KEY`; failed or partial jobs are surfaced as document errors or warnings. Review values carefully, especially for scanned or low-resolution pages.
- With `uvicorn --reload`, editing source code while an upload is processing cancels its background task. Interrupted documents are marked failed and are never automatically resubmitted, so a restart cannot bill the same PDF twice. Wait for a document to reach `review`/`failed` before editing code, then upload again if it was interrupted.
- Sarvam returns semantic JSON rather than pixel geometry, so the grid is reconstructed from its days and time slots. Cell coordinates are generated for editing and export; the grid editor does not yet let reviewers add or remove rows, columns, or merges.
- The original PDF is stored on the local filesystem and the database keeps its path. Back up both PostgreSQL and `STORAGE_DIR` together.
