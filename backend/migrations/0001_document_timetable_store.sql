CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    storage_dir TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pages (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    image_path TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    crop_path TEXT,
    crop_json TEXT,
    crop_confidence REAL,
    crop_status TEXT NOT NULL DEFAULT 'not_found',
    ocr_json TEXT,
    UNIQUE(document_id, page_number)
);

CREATE TABLE timetables (
    id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL UNIQUE REFERENCES pages(id) ON DELETE CASCADE,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE timetable_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timetable_id TEXT NOT NULL REFERENCES timetables(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('ai_original', 'corrected', 'approved')),
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    confidence REAL,
    table_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(timetable_id, version_number)
);

CREATE TABLE page_extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timetable_id TEXT NOT NULL REFERENCES timetables(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    ocr_json TEXT NOT NULL,
    extraction_json TEXT NOT NULL,
    confidence REAL,
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE verification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timetable_id TEXT NOT NULL REFERENCES timetables(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    status TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX pages_document_idx ON pages(document_id, page_number);
CREATE INDEX timetable_versions_lookup_idx ON timetable_versions(timetable_id, version_number DESC);
CREATE INDEX page_extractions_lookup_idx ON page_extractions(timetable_id, id DESC);
