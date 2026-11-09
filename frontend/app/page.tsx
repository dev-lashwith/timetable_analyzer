"use client";

import {
  ChangeEvent,
  DragEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/$/, "");

type Cell = {
  row: number;
  column: number;
  rowspan: number;
  colspan: number;
  text: string;
};
type TableData = {
  row_count: number;
  column_count: number;
  column_widths: number[];
  row_heights: number[];
  cells: Cell[];
};
type Validation = { valid: boolean; errors: string[]; warnings: string[] };
type CropInfo = {
  x: number;
  y: number;
  width: number;
  height: number;
  grid: {
    row_count: number;
    column_count: number;
    cell_count: number;
    width: number;
    height: number;
  };
};

function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

function getApiError(payload: unknown) {
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (typeof detail === "object" && detail !== null && "message" in detail) {
      const data = detail as { message: string; errors?: string[] };
      return [data.message, ...(data.errors || [])].join(" ");
    }
  }
  return "The request failed. Check the backend and try again.";
}

export default function Home() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [cropUrl, setCropUrl] = useState("");
  const [cropInfo, setCropInfo] = useState<CropInfo | null>(null);
  const [table, setTable] = useState<TableData | null>(null);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [loading, setLoading] = useState<"preview" | "extract" | "export" | "">(
    "",
  );
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [modelInfo, setModelInfo] = useState<{
    model: string | null;
    reachable: boolean;
  } | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/api/health`)
      .then((response) => response.json())
      .then((data) => {
        setModelInfo({
          model: data.configured_model,
          reachable: data.ollama_reachable,
        });
      })
      .catch(() => setModelInfo({ model: null, reachable: false }));
  }, []);

  useEffect(() => {
    return () => {
      if (sourceUrl) URL.revokeObjectURL(sourceUrl);
      if (cropUrl) URL.revokeObjectURL(cropUrl);
    };
  }, [sourceUrl, cropUrl]);

  const cellMap = useMemo(() => {
    const origins = new Map<string, Cell>();
    const covered = new Set<string>();
    if (table) {
      for (const cell of table.cells) {
        origins.set(`${cell.row},${cell.column}`, cell);
        for (let row = cell.row; row < cell.row + cell.rowspan; row += 1) {
          for (
            let column = cell.column;
            column < cell.column + cell.colspan;
            column += 1
          ) {
            if (row !== cell.row || column !== cell.column)
              covered.add(`${row},${column}`);
          }
        }
      }
    }
    return { origins, covered };
  }, [table]);
  const displayScale = table
    ? Math.max(
        900,
        Math.round(
          table.column_widths.reduce((sum, width) => sum + width, 0) * 0.78,
        ),
      ) / table.column_widths.reduce((sum, width) => sum + width, 0)
    : 1;

  async function prepareImage(nextFile: File) {
    setError("");
    setTable(null);
    setValidation(null);
    setCropInfo(null);
    setFile(nextFile);
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    if (cropUrl) URL.revokeObjectURL(cropUrl);
    const nextSource = URL.createObjectURL(nextFile);
    setSourceUrl(nextSource);
    setCropUrl("");
    setLoading("preview");
    try {
      const form = new FormData();
      form.append("file", nextFile);
      const response = await fetch(`${API_URL}/api/preview`, {
        method: "POST",
        body: form,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      const cropBlob = await fetch(
        `data:image/png;base64,${data.crop_png_base64}`,
      ).then((result) => result.blob());
      setCropUrl(URL.createObjectURL(cropBlob));
      setCropInfo({ ...data.crop, grid: data.grid });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const nextFile = event.target.files?.[0];
    if (nextFile) void prepareImage(nextFile);
    event.target.value = "";
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const nextFile = event.dataTransfer.files[0];
    if (nextFile && nextFile.type.startsWith("image/"))
      void prepareImage(nextFile);
    else setError("Choose a PNG, JPEG, or WebP image.");
  }

  async function extract() {
    if (!file || !cropUrl) return;
    setError("");
    setLoading("extract");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(`${API_URL}/api/extract`, {
        method: "POST",
        body: form,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      setTable(data.table);
      setValidation(data.validation);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  function updateCell(row: number, column: number, text: string) {
    setTable((current) =>
      current
        ? {
            ...current,
            cells: current.cells.map((cell) =>
              cell.row === row && cell.column === column
                ? { ...cell, text }
                : cell,
            ),
          }
        : current,
    );
  }

  async function exportXlsx() {
    if (!table) return;
    setError("");
    setLoading("export");
    try {
      const response = await fetch(`${API_URL}/api/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(table),
      });
      if (!response.ok) throw new Error(getApiError(await response.json()));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "timetable.xlsx";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  return (
    <main className="page-shell">
      <header className="topbar">
        <a
          className="brand"
          href="#top"
          aria-label="FeelIQ Technologies Timetable Extractor home"
        >
          <img
            className="brand-logo"
            src="/feeliq-logo.png"
            alt="FeelIQ Technologies"
          />
        </a>
      </header>

      <section className="intro" id="top">
        <div className="eyebrow">TIMETABLE TO SPREADSHEET</div>
        <h1>
          From timetable photo
          <br />
          <span>to editable spreadsheet.</span>
        </h1>
        <p className="intro-copy">
          Upload a timetable photo. We’ll detect the table, read its contents,
          and preserve its rows, columns, and merged cells.
        </p>
      </section>

      <section
        className={`upload-card ${dragging ? "is-dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        aria-label="Upload timetable image"
      >
        <div className="upload-main">
          <div className="upload-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path
                d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 15v4a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <div className="upload-copy">
            <strong>
              {file ? file.name : "Drop your timetable image here"}
            </strong>
            <span>
              {file
                ? `${(file.size / 1024 / 1024).toFixed(2)} MB · PNG, JPG or WebP`
                : "PNG, JPG or WebP · up to 20 MB"}
            </span>
          </div>
          <button
            className="button button-secondary choose-button"
            onClick={() => inputRef.current?.click()}
            disabled={loading !== ""}
          >
            {file ? "Choose another" : "Choose image"}
          </button>
          <input
            ref={inputRef}
            className="visually-hidden"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={onFileChange}
          />
        </div>
      </section>

      {error && (
        <div className="error-banner" role="alert">
          <span className="error-mark">!</span>
          <span>{error}</span>
          <button aria-label="Dismiss error" onClick={() => setError("")}>
            ×
          </button>
        </div>
      )}

      {(sourceUrl || loading === "preview") && (
        <section className="preview-section" aria-live="polite">
          <div className="section-heading">
            {cropInfo && (
              <div className="crop-dimensions">
                {cropInfo.grid.row_count} rows × {cropInfo.grid.column_count}{" "}
                columns · {cropInfo.grid.cell_count} cells
              </div>
            )}
          </div>
          <div className="preview-grid">
            <article className="preview-card source-card">
              <div className="preview-card-head">
                <span>ORIGINAL IMAGE</span>
                <span className="mini-tag">Source</span>
              </div>
              <div className="image-frame source-frame">
                {sourceUrl && (
                  <img src={sourceUrl} alt="Uploaded timetable source" />
                )}
              </div>
            </article>
            <article className="preview-card crop-card">
              <div className="preview-card-head">
                <span>DETECTED TIMETABLE</span>
                <span className="mini-tag mini-tag-blue">Crop only</span>
              </div>
              <div className="image-frame crop-frame">
                {loading === "preview" ? (
                  <div className="loading-state">
                    <span className="spinner" />
                    Finding table borders…
                  </div>
                ) : cropUrl ? (
                  <img src={cropUrl} alt="Detected timetable crop" />
                ) : (
                  <div className="crop-empty">
                    The table crop preview will appear here.
                  </div>
                )}
              </div>
            </article>
          </div>
          {cropUrl && (
            <div className="action-row">
              <button
                className="button button-primary"
                onClick={() => void extract()}
                disabled={loading !== ""}
              >
                {loading === "extract" ? (
                  <>
                    <span className="spinner spinner-white" /> Reading
                    timetable…
                  </>
                ) : (
                  <>
                    Extract timetable <span aria-hidden="true">→</span>
                  </>
                )}
              </button>
            </div>
          )}
        </section>
      )}

      {table && (
        <section className="editor-section" aria-live="polite">
          <div className="section-heading editor-heading">
            <div>
              <div className="section-kicker">
                STEP 2 <span>·</span> REVIEW & EDIT
              </div>
              <h2>Your editable timetable.</h2>
            </div>
            <div className="table-stats">
              <span>{table.row_count} rows</span>
              <span className="stats-separator">·</span>
              <span>{table.column_count} columns</span>
              <span className="stats-separator">·</span>
              <span>{table.cells.length} cells</span>
            </div>
          </div>
          {validation &&
            (validation.warnings.length > 0 ||
              validation.errors.length > 0) && (
              <div
                className={`validation-box ${validation.errors.length ? "validation-error" : ""}`}
              >
                <span className="validation-icon">
                  {validation.errors.length ? "!" : "✓"}
                </span>
                <div>
                  <strong>
                    {validation.errors.length
                      ? "Review needed"
                      : "Structure checked"}
                  </strong>
                  {[...validation.errors, ...validation.warnings].map(
                    (warning, index) => (
                      <p key={index}>{warning}</p>
                    ),
                  )}
                </div>
              </div>
            )}
          <div className="table-wrap">
            <table
              className="editable-table"
              style={{
                width: `${table.column_widths.reduce((sum, width) => sum + width, 0) * displayScale}px`,
              }}
            >
              <colgroup>
                {table.column_widths.map((width, index) => (
                  <col
                    key={index}
                    style={{
                      width: `${(width / table.column_widths.reduce((sum, value) => sum + value, 0)) * 100}%`,
                    }}
                  />
                ))}
              </colgroup>
              <tbody>
                {Array.from({ length: table.row_count }, (_, row) => (
                  <tr
                    key={row}
                    style={{
                      height: `${table.row_heights[row] * displayScale}px`,
                    }}
                  >
                    {Array.from({ length: table.column_count }, (_, column) => {
                      const key = `${row},${column}`;
                      if (cellMap.covered.has(key)) return null;
                      const cell = cellMap.origins.get(key);
                      if (!cell)
                        return (
                          <td key={key} className="unresolved-cell">
                            <textarea
                              aria-label={`Row ${row + 1}, column ${column + 1}`}
                              value=""
                              placeholder="Blank"
                              onChange={(event) =>
                                updateCell(row, column, event.target.value)
                              }
                            />
                          </td>
                        );
                      return (
                        <td
                          key={key}
                          rowSpan={cell.rowspan}
                          colSpan={cell.colspan}
                        >
                          <textarea
                            aria-label={`Row ${row + 1}, column ${column + 1}${cell.rowspan > 1 || cell.colspan > 1 ? ", merged cell" : ""}`}
                            value={cell.text}
                            placeholder="Blank"
                            onChange={(event) =>
                              updateCell(
                                cell.row,
                                cell.column,
                                event.target.value,
                              )
                            }
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="editor-footer">
            <p>
              <span className="edit-dot" /> Click any cell to edit. Merged cells
              are preserved.
            </p>
            <button
              className="button button-primary export-button"
              onClick={() => void exportXlsx()}
              disabled={loading !== ""}
            >
              {loading === "export" ? (
                <>
                  <span className="spinner spinner-white" /> Preparing file…
                </>
              ) : (
                <>
                  <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <path
                      d="M10 3v9m0 0 3.3-3.3M10 12 6.7 8.7M4 14v2.5h12V14"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>{" "}
                  Download Excel
                </>
              )}
            </button>
          </div>
        </section>
      )}

      <footer className="page-footer">
        <span>Made for schedules, built to keep their shape.</span>
        <span
          className={`model-status ${modelInfo?.reachable ? "model-online" : ""}`}
        >
          <span className="status-dot" />{" "}
          {modelInfo?.model
            ? `Ollama · ${modelInfo.model}`
            : modelInfo?.reachable
              ? "Ollama is ready · set a vision model"
              : "Waiting for local Ollama"}
        </span>
      </footer>
    </main>
  );
}
