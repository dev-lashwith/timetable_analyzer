"use client";

import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from "react";

import ZoomImage from "./zoom-image";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

type Cell = { row: number; column: number; rowspan: number; colspan: number; text: string };
type TableData = {
  row_count: number;
  column_count: number;
  column_widths: number[];
  row_heights: number[];
  cells: Cell[];
  class_name?: string | null;
  stream?: string | null;
  section?: string | null;
};
type Constraints = { className: string; stream: string; section: string };
type Validation = { valid: boolean; errors: string[]; warnings: string[] };
type CropInfo = {
  x: number;
  y: number;
  width: number;
  height: number;
  grid: { row_count: number; column_count: number; cell_count: number; width: number; height: number };
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
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [cropUrl, setCropUrl] = useState("");
  const [cropInfo, setCropInfo] = useState<CropInfo | null>(null);
  const [table, setTable] = useState<TableData | null>(null);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [loading, setLoading] = useState<"preview" | "extract" | "export" | "" >("");
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [constraints, setConstraints] = useState<Constraints>({ className: "", stream: "", section: "" });
  const [toast, setToast] = useState("");
  const [modelInfo, setModelInfo] = useState<{ model: string | null; reachable: boolean } | null>(null);
  const [teachers, setTeachers] = useState<string[]>([]);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [teacherSelection, setTeacherSelection] = useState("");
  const [subjectSelection, setSubjectSelection] = useState("");

  const constraintsReady = Boolean(
    constraints.className.trim() && constraints.stream.trim() && constraints.section.trim(),
  );

  function showToast(message: string) {
    setToast(message);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 4000);
  }

  function dismissToast() {
    setToast("");
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = null;
  }

  useEffect(() => {
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    };
  }, []);

  useEffect(() => {
    fetch(`${API_URL}/api/health`).then((response) => response.json()).then((data) => {
      setModelInfo({ model: data.configured_model, reachable: data.ollama_reachable });
    }).catch(() => setModelInfo({ model: null, reachable: false }));
  }, []);

  // Revoke each URL only when that specific URL is replaced or the app unmounts.
  // A shared effect would revoke the source URL when the crop URL changes, which
  // breaks anything that reloads the image (like the zoom background).
  useEffect(() => {
    return () => {
      if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    };
  }, [sourceUrl]);

  useEffect(() => {
    return () => {
      if (cropUrl) URL.revokeObjectURL(cropUrl);
    };
  }, [cropUrl]);

  const cellMap = useMemo(() => {
    const origins = new Map<string, Cell>();
    const covered = new Set<string>();
    if (table) {
      for (const cell of table.cells) {
        origins.set(`${cell.row},${cell.column}`, cell);
        for (let row = cell.row; row < cell.row + cell.rowspan; row += 1) {
          for (let column = cell.column; column < cell.column + cell.colspan; column += 1) {
            if (row !== cell.row || column !== cell.column) covered.add(`${row},${column}`);
          }
        }
      }
    }
    return { origins, covered };
  }, [table]);
  const displayScale = table
    ? Math.max(900, Math.round(table.column_widths.reduce((sum, width) => sum + width, 0) * 0.78))
      / table.column_widths.reduce((sum, width) => sum + width, 0)
    : 1;
  const uniqueValues = useMemo(() => {
    if (!table) return [];
    const seen = new Set<string>();
    const values: string[] = [];
    for (const cell of table.cells) {
      const value = (cell.text ?? "").trim();
      // Keep the cell text exactly as read (only outer whitespace is ignored).
      if (!value || seen.has(value)) continue;
      seen.add(value);
      values.push(value);
    }
    return values;
  }, [table]);
  const extractedValues = uniqueValues;
  const assignedValues = useMemo(() => new Set([...teachers, ...subjects]), [teachers, subjects]);
  const availableValues = useMemo(
    () => extractedValues.filter((value) => !assignedValues.has(value)),
    [extractedValues, assignedValues],
  );

  useEffect(() => {
    if (teacherSelection && !availableValues.includes(teacherSelection)) setTeacherSelection("");
    if (subjectSelection && !availableValues.includes(subjectSelection)) setSubjectSelection("");
  }, [availableValues, teacherSelection, subjectSelection]);

  function addValue(kind: "teacher" | "subject", value: string) {
    const selected = value.trim();
    if (!selected || !availableValues.includes(selected)) return;
    if (kind === "teacher") {
      setTeachers((current) => [...current, selected]);
      setTeacherSelection("");
      if (subjectSelection === selected) setSubjectSelection("");
    } else {
      setSubjects((current) => [...current, selected]);
      setSubjectSelection("");
      if (teacherSelection === selected) setTeacherSelection("");
    }
  }

  function removeValue(kind: "teacher" | "subject", value: string) {
    if (kind === "teacher") setTeachers((current) => current.filter((item) => item !== value));
    else setSubjects((current) => current.filter((item) => item !== value));
  }

  async function prepareImage(nextFile: File) {
    if (!constraintsReady) {
      showToast("Please fill in class, stream, and section above before uploading the timetable.");
      return;
    }
    setError("");
    setTable(null);
    setValidation(null);
    setCropInfo(null);
    setFile(nextFile);
    setTeachers([]);
    setSubjects([]);
    setTeacherSelection("");
    setSubjectSelection("");
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    if (cropUrl) URL.revokeObjectURL(cropUrl);
    const nextSource = URL.createObjectURL(nextFile);
    setSourceUrl(nextSource);
    setCropUrl("");
    setLoading("preview");
    try {
      const form = new FormData();
      form.append("file", nextFile);
      form.append("class_name", constraints.className.trim());
      form.append("stream", constraints.stream.trim());
      form.append("section", constraints.section.trim());
      const response = await fetch(`${API_URL}/api/preview`, { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      const cropBlob = await fetch(`data:image/png;base64,${data.crop_png_base64}`).then((result) => result.blob());
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

  function chooseImage() {
    if (!constraintsReady) {
      showToast("Please fill in class, stream, and section above before uploading the timetable.");
      return;
    }
    inputRef.current?.click();
  }

  function updateConstraint(key: keyof Constraints, value: string) {
    setConstraints((current) => ({ ...current, [key]: value }));
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (!constraintsReady) {
      showToast("Please fill in class, stream, and section above before uploading the timetable.");
      return;
    }
    const nextFile = event.dataTransfer.files[0];
    if (nextFile && nextFile.type.startsWith("image/")) void prepareImage(nextFile);
    else setError("Choose a PNG, JPEG, or WebP image.");
  }

  async function extract() {
    if (!file || !cropUrl) return;
    setError("");
    setLoading("extract");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("class_name", constraints.className.trim());
      form.append("stream", constraints.stream.trim());
      form.append("section", constraints.section.trim());
      const response = await fetch(`${API_URL}/api/extract`, { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      setTable(data.table);
      setValidation(data.validation);
      setTeachers([]);
      setSubjects([]);
      setTeacherSelection("");
      setSubjectSelection("");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  function updateCell(row: number, column: number, text: string) {
    setTable((current) => current ? {
      ...current,
      cells: current.cells.map((cell) => cell.row === row && cell.column === column ? { ...cell, text } : cell),
    } : current);
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
      const parts = [table.class_name, table.stream, table.section]
        .map((part) => part?.replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, ""))
        .filter((part): part is string => Boolean(part));
      anchor.download = parts.length ? `timetable_${parts.join("_")}.xlsx` : "timetable.xlsx";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  function classificationCard(
    kind: "teacher" | "subject",
    title: string,
    values: string[],
    selection: string,
    setSelection: (value: string) => void,
  ) {
    const label = kind === "teacher" ? "teacher" : "subject";
    return (
      <article className="classification-card">
        <div className="classification-card-head">
          <div>
            <div className="section-kicker">{title}</div>
            <h3>{title.charAt(0) + title.slice(1).toLowerCase()}</h3>
          </div>
          <span className="classification-count">{values.length}</span>
        </div>
        <form className="classification-form" onSubmit={(event) => { event.preventDefault(); addValue(kind, selection); }}>
          <select
            value={selection}
            onChange={(event) => setSelection(event.target.value)}
            aria-label={`Select a ${label} from extracted values`}
            disabled={availableValues.length === 0}
          >
            <option value="">
              {availableValues.length > 0 ? `Choose a ${label}` : "No values left to add"}
            </option>
            {availableValues.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <button type="submit" className="button button-primary classification-add" disabled={!selection || !availableValues.includes(selection)}>Add</button>
        </form>
        <div className="table-wrap classification-wrap"><table className="classification-table">
          <thead><tr><th scope="col">#</th><th scope="col">{title}</th><th scope="col"><span className="visually-hidden">Remove</span></th></tr></thead>
          <tbody>{values.length > 0 ? values.map((value, index) => <tr key={value}>
            <td className="classification-index">{index + 1}</td>
            <td className="classification-value">{value}</td>
            <td className="classification-action"><button type="button" onClick={() => removeValue(kind, value)} aria-label={`Remove ${value} from ${title}`} title="Remove">×</button></td>
          </tr>) : <tr><td colSpan={3} className="classification-empty">No {label}s added yet.</td></tr>}</tbody>
        </table></div>
      </article>
    );
  }

  return (
    <main className="page-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="FeelIQ Technologies Timetable Extractor home">
          <img className="brand-logo" src="/feeliq-logo.png" alt="FeelIQ Technologies" />
        </a>
        
      </header>

      <section className="intro" id="top">
        <div className="eyebrow"><span className="eyebrow-line" /> IMAGE TO SPREADSHEET</div>
        <h1>Your timetable,<br /><span>ready to edit.</span></h1>
        
      </section>

      <section className="constraint-card" aria-label="Timetable details">
        <div className="constraint-head">
          <div>
            <div className="section-kicker">TIMETABLE DETAILS <span>·</span> REQUIRED</div>
            <h2>Which timetable are you uploading?</h2>
          </div>
          
        </div>
        <div className="constraint-fields">
          <label className="constraint-field">
            <span>Class</span>
            <input value={constraints.className} onChange={(event) => updateConstraint("className", event.target.value)} placeholder="Type the class" maxLength={20} autoComplete="off" required />
          </label>
          <label className="constraint-field">
            <span>Stream</span>
            <input value={constraints.stream} onChange={(event) => updateConstraint("stream", event.target.value)} placeholder="Type the stream" maxLength={40} autoComplete="off" required />
          </label>
          <label className="constraint-field">
            <span>Section</span>
            <input value={constraints.section} onChange={(event) => updateConstraint("section", event.target.value)} placeholder="Type the section" maxLength={20} autoComplete="off" required />
          </label>
        </div>
      </section>

      <section className={`upload-card ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} aria-label="Upload timetable image">
        <div className="upload-main">
          <div className="upload-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 15v4a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg></div>
          <div className="upload-copy">
            <strong>{file ? file.name : "Drop your timetable image here"}</strong>
            <span>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · PNG, JPG or WebP` : "PNG, JPG or WebP · up to 20 MB"}</span>
          </div>
          <button className={`button button-secondary choose-button ${constraintsReady ? "" : "button-locked"}`} onClick={chooseImage} disabled={loading !== ""} aria-disabled={!constraintsReady} title={constraintsReady ? undefined : "Fill in class, stream, and section first"}>{file ? "Choose another" : "Choose image"}</button>
          <input ref={inputRef} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp" onChange={onFileChange} />
        </div>
        <div className="upload-foot"><span>{constraintsReady ? "Only the detected timetable crop is sent to the local vision model." : "Add class, stream, and section above to enable image upload."}</span><span className="step-label">01 <i /> 02 <i /> 03</span></div>
      </section>

      {error && <div className="error-banner" role="alert"><span className="error-mark">!</span><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}

      {toast && <div className="toast" role="alert" aria-live="assertive"><span className="toast-mark">!</span><span className="toast-text">{toast}</span><button className="toast-close" aria-label="Dismiss message" onClick={dismissToast}>×</button></div>}

      {(sourceUrl || loading === "preview") && <section className="preview-section" aria-live="polite">
        <div className="section-heading"><div><div className="section-kicker">STEP 1 <span>·</span> CHECK THE CROP</div><h2>We found your table.</h2></div>{cropInfo && <div className="crop-dimensions">{cropInfo.grid.row_count} rows × {cropInfo.grid.column_count} columns · {cropInfo.grid.cell_count} cells</div>}</div>
        <div className="preview-grid">
          <article className="preview-card source-card"><div className="preview-card-head"><span>ORIGINAL IMAGE</span><span className="mini-tag">Source</span></div><ZoomImage src={sourceUrl} alt="Uploaded timetable source" className="source-frame" /></article>
          <article className="preview-card crop-card"><div className="preview-card-head"><span>DETECTED TIMETABLE</span><span className="mini-tag mini-tag-blue">Crop only</span></div><ZoomImage src={cropUrl} alt="Detected timetable crop" className="crop-frame">{loading === "preview" ? <div className="loading-state"><span className="spinner" />Finding table borders…</div> : <div className="crop-empty">The table crop preview will appear here.</div>}</ZoomImage></article>
        </div>
        {cropUrl && <div className="action-row"><p>Check that the crop includes the full table and nothing extra.</p><button className="button button-primary" onClick={() => void extract()} disabled={loading !== ""}>{loading === "extract" ? <><span className="spinner spinner-white" /> Reading timetable…</> : <>Extract timetable <span aria-hidden="true">→</span></>}</button></div>}
      </section>}

      {table && <section className="editor-section" aria-live="polite">
        <div className="section-heading editor-heading"><div><div className="section-kicker">STEP 2 <span>·</span> REVIEW & EDIT</div><h2>Your editable timetable.</h2></div><div className="table-stats"><span>{table.row_count} rows</span><span className="stats-separator">·</span><span>{table.column_count} columns</span><span className="stats-separator">·</span><span>{table.cells.length} cells</span></div></div>
        <div className="constraint-summary" aria-label="Saved timetable details">
          <span className="constraint-summary-label">Timetable details</span>
          <span className="constraint-chip"><span>Class</span><strong>{table.class_name || constraints.className.trim() || "—"}</strong></span>
          <span className="constraint-chip"><span>Stream</span><strong>{table.stream || constraints.stream.trim() || "—"}</strong></span>
          <span className="constraint-chip"><span>Section</span><strong>{table.section || constraints.section.trim() || "—"}</strong></span>
        </div>
        {validation && (validation.warnings.length > 0 || validation.errors.length > 0) && <div className={`validation-box ${validation.errors.length ? "validation-error" : ""}`}><span className="validation-icon">{validation.errors.length ? "!" : "✓"}</span><div><strong>{validation.errors.length ? "Review needed" : "Structure checked"}</strong>{[...validation.errors, ...validation.warnings].map((warning, index) => <p key={index}>{warning}</p>)}</div></div>}
        <div className="table-wrap"><table className="editable-table" style={{ width: `${table.column_widths.reduce((sum, width) => sum + width, 0) * displayScale}px` }}><colgroup>{table.column_widths.map((width, index) => <col key={index} style={{ width: `${width / table.column_widths.reduce((sum, value) => sum + value, 0) * 100}%` }} />)}</colgroup><tbody>{Array.from({ length: table.row_count }, (_, row) => <tr key={row} style={{ height: `${table.row_heights[row] * displayScale}px` }}>{Array.from({ length: table.column_count }, (_, column) => {
          const key = `${row},${column}`;
          if (cellMap.covered.has(key)) return null;
          const cell = cellMap.origins.get(key);
          if (!cell) return <td key={key} className="unresolved-cell"><textarea aria-label={`Row ${row + 1}, column ${column + 1}`} value="" placeholder="Blank" onChange={(event) => updateCell(row, column, event.target.value)} /></td>;
          return <td key={key} rowSpan={cell.rowspan} colSpan={cell.colspan}><textarea aria-label={`Row ${row + 1}, column ${column + 1}${cell.rowspan > 1 || cell.colspan > 1 ? ", merged cell" : ""}`} value={cell.text} placeholder="Blank" onChange={(event) => updateCell(cell.row, cell.column, event.target.value)} /></td>;
        })}</tr>)}</tbody></table></div>
        {uniqueValues.length > 0 && <section className="unique-section" aria-label="Unique timetable values">
          <div className="section-heading unique-heading">
            <div>
              <div className="section-kicker">FROM THE CROPPED TIMETABLE <span>·</span> UNIQUE VALUES</div>
              <h2>Every distinct value.</h2>
            </div>
            <span className="unique-count">{uniqueValues.length} {uniqueValues.length === 1 ? "value" : "values"}</span>
          </div>
          <p className="unique-hint">Values are taken directly from the timetable cells, exactly as read from the crop. Edits in the table above update this list.</p>
          <div className="table-wrap unique-wrap"><table className="unique-table">
            <thead><tr><th scope="col">#</th><th scope="col">Value</th></tr></thead>
            <tbody>{uniqueValues.map((value, index) => <tr key={`${value}-${index}`}>
              <td className="unique-index">{index + 1}</td>
              <td className="unique-value">{value}</td>
            </tr>)}</tbody>
          </table></div>
        </section>}
        {extractedValues.length > 0 && <section className="classification-section" aria-label="Teachers and subjects">
          <div className="section-heading unique-heading">
            <div>
              <div className="section-kicker">EXTRACTED VALUES <span>·</span> CLASSIFY</div>
              <h2>Teachers and subjects.</h2>
            </div>
            <span className="unique-count">{availableValues.length} available</span>
          </div>
          <p className="unique-hint">Choose from the values found in the crop. A value added to one table is removed from the other.</p>
          <div className="classification-grid">
            {classificationCard("teacher", "TEACHERS", teachers, teacherSelection, setTeacherSelection)}
            {classificationCard("subject", "SUBJECTS", subjects, subjectSelection, setSubjectSelection)}
          </div>
        </section>}
        <div className="editor-footer"><p><span className="edit-dot" /> Click any cell to edit. Merged cells are preserved.</p><button className="button button-primary export-button" onClick={() => void exportXlsx()} disabled={loading !== ""}>{loading === "export" ? <><span className="spinner spinner-white" /> Preparing file…</> : <><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 3v9m0 0 3.3-3.3M10 12 6.7 8.7M4 14v2.5h12V14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg> Download Excel</>}</button></div>
      </section>}

      <footer className="page-footer"><span>Made for schedules, built to keep their shape.</span><span className={`model-status ${modelInfo?.reachable ? "model-online" : ""}`}><span className="status-dot" /> {modelInfo?.model ? `Ollama · ${modelInfo.model}` : modelInfo?.reachable ? "Ollama is ready · set a vision model" : "Waiting for local Ollama"}</span></footer>
    </main>
  );
}
