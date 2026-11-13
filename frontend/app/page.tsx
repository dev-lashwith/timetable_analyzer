"use client";

import { ChangeEvent, DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { extractTeacherNames } from "./teacher-names";
import { extractSubjectNames, subjectKey } from "./subject-names";

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
  const [manualTeachers, setManualTeachers] = useState<string[]>([]);
  const [teacherInput, setTeacherInput] = useState("");
  const [teacherFormError, setTeacherFormError] = useState("");
  const [removedSubjects, setRemovedSubjects] = useState<string[]>([]);
  const [subjectTeachers, setSubjectTeachers] = useState<Record<string, string[]>>({});
  const [teacherSelection, setTeacherSelection] = useState<Record<string, string>>({});

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
  const teacherNames = useMemo(() => {
    if (!table) return [];
    const seen = new Map<string, string>();
    for (const value of [...extractTeacherNames(table), ...manualTeachers]) {
      const name = value.replace(/\s+/g, " ").trim();
      if (!name) continue;
      const key = name.toLocaleLowerCase();
      if (!seen.has(key)) seen.set(key, name);
    }
    return Array.from(seen.values()).sort((first, second) =>
      first.localeCompare(second, undefined, { numeric: true, sensitivity: "base" }),
    );
  }, [table, manualTeachers]);
  const subjects = useMemo(() => {
    if (!table) return [];
    const removed = new Set(removedSubjects);
    return extractSubjectNames(table).filter((subject) => !removed.has(subjectKey(subject)));
  }, [table, removedSubjects]);
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
    setManualTeachers([]);
    setTeacherInput("");
    setTeacherFormError("");
    setRemovedSubjects([]);
    setSubjectTeachers({});
    setTeacherSelection({});
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
      setManualTeachers([]);
      setTeacherInput("");
      setTeacherFormError("");
      setRemovedSubjects([]);
      setSubjectTeachers({});
      setTeacherSelection({});
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

  function removeSubject(subject: string) {
    const key = subjectKey(subject);
    setRemovedSubjects((current) => (current.includes(key) ? current : [...current, key]));
    setSubjectTeachers((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
    setTeacherSelection((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function assignTeacher(subject: string, teacher: string) {
    const key = subjectKey(subject);
    const name = teacher.trim();
    if (!name) return;
    setSubjectTeachers((current) => {
      const assigned = current[key] ?? [];
      if (assigned.some((item) => item.toLocaleLowerCase() === name.toLocaleLowerCase())) {
        return current;
      }
      return { ...current, [key]: [...assigned, name] };
    });
    setTeacherSelection((current) => ({ ...current, [key]: "" }));
  }

  function unassignTeacher(subject: string, teacher: string) {
    const key = subjectKey(subject);
    setSubjectTeachers((current) => {
      const assigned = (current[key] ?? []).filter((item) => item !== teacher);
      const next = { ...current };
      if (assigned.length > 0) next[key] = assigned;
      else delete next[key];
      return next;
    });
  }

  function addTeachers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const names = teacherInput
      .split(/\n|,|\/|;/)
      .map((name) => name.replace(/\s+/g, " ").trim())
      .filter((name) => /[A-Za-z]/.test(name));
    if (names.length === 0) {
      setTeacherFormError("Type a teacher name before adding.");
      return;
    }
    setManualTeachers((current) => {
      const seen = new Set(current.map((name) => name.toLocaleLowerCase()));
      const next = [...current];
      for (const name of names) {
        const key = name.toLocaleLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        next.push(name);
      }
      return next;
    });
    setTeacherInput("");
    setTeacherFormError("");
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
          <article className="preview-card source-card"><div className="preview-card-head"><span>ORIGINAL IMAGE</span><span className="mini-tag">Source</span></div><div className="image-frame source-frame">{sourceUrl && <img src={sourceUrl} alt="Uploaded timetable source" />}</div></article>
          <article className="preview-card crop-card"><div className="preview-card-head"><span>DETECTED TIMETABLE</span><span className="mini-tag mini-tag-blue">Crop only</span></div><div className="image-frame crop-frame">{loading === "preview" ? <div className="loading-state"><span className="spinner" />Finding table borders…</div> : cropUrl ? <img src={cropUrl} alt="Detected timetable crop" /> : <div className="crop-empty">The table crop preview will appear here.</div>}</div></article>
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
        {subjects.length > 0 && (
          <div className="subjects-section">
            <div className="subjects-head">
              <div>
                <div className="section-kicker">EXTRACTED <span>·</span> SUBJECTS</div>
                <h3>Subjects</h3>
              </div>
              <span className="subjects-count">{subjects.length} {subjects.length === 1 ? "subject" : "subjects"}</span>
            </div>
            <p className="subjects-hint">Assign one or more teachers to each subject.</p>
            <ul className="subject-list">
              {subjects.map((subject, index) => {
                const key = subjectKey(subject);
                const assigned = subjectTeachers[key] ?? [];
                const options = teacherNames.filter(
                  (name) => !assigned.some((item) => item.toLocaleLowerCase() === name.toLocaleLowerCase()),
                );
                return (
                  <li key={subject} className="subject-card">
                    <div className="subject-card-head">
                      <span className="teacher-index">{index + 1}</span>
                      <span className="subject-name">{subject}</span>
                      <button
                        type="button"
                        className="chip-remove"
                        onClick={() => removeSubject(subject)}
                        aria-label={`Remove ${subject}`}
                        title={`Remove ${subject}`}
                      >
                        &times;
                      </button>
                    </div>
                    <div className="subject-teachers">
                      {assigned.length > 0 ? assigned.map((teacher) => (
                        <span key={teacher} className="subject-teacher">
                          {teacher}
                          <button
                            type="button"
                            onClick={() => unassignTeacher(subject, teacher)}
                            aria-label={`Remove ${teacher} from ${subject}`}
                            title={`Remove ${teacher}`}
                          >
                            &times;
                          </button>
                        </span>
                      )) : <span className="subject-teacher-empty">No teacher assigned</span>}
                    </div>
                    <div className="subject-assign">
                      <select
                        value={teacherSelection[key] ?? ""}
                        onChange={(event) =>
                          setTeacherSelection((current) => ({ ...current, [key]: event.target.value }))
                        }
                        aria-label={`Assign a teacher to ${subject}`}
                        disabled={options.length === 0}
                      >
                        <option value="">
                          {options.length > 0
                            ? "Choose teacher"
                            : teacherNames.length > 0
                              ? "All teachers assigned"
                              : "Add teacher names first"}
                        </option>
                        {options.map((name) => <option key={name} value={name}>{name}</option>)}
                      </select>
                      <button
                        type="button"
                        className="assign-button"
                        onClick={() => assignTeacher(subject, teacherSelection[key] ?? "")}
                        disabled={!teacherSelection[key]}
                      >
                        Assign
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        <div className="teachers-section">
          <div className="teachers-head">
            <div>
              <div className="section-kicker">{teacherNames.length > 0 ? <>EXTRACTED <span>·</span> TEACHERS</> : <>TEACHERS <span>·</span> ADD NAMES</>}</div>
              <h3>{teacherNames.length > 0 ? "Teacher names" : "Add teacher names"}</h3>
            </div>
            {teacherNames.length > 0 && (
              <span className="teachers-count">{teacherNames.length} {teacherNames.length === 1 ? "teacher" : "teachers"}</span>
            )}
          </div>
          {teacherNames.length > 0 ? (
            <ul className="teacher-list">
              {teacherNames.map((name, index) => (
                <li key={`${index}-${name}`} className="teacher-chip">
                  <span className="teacher-index">{index + 1}</span>
                  <span className="teacher-name">{name}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="teachers-empty">No teacher name was found in this timetable. Add one below and it will appear here.</p>
          )}
          <form className="teacher-form" onSubmit={addTeachers}>
            <input
              className="teacher-input"
              value={teacherInput}
              onChange={(event) => {
                setTeacherInput(event.target.value);
                if (teacherFormError) setTeacherFormError("");
              }}
              placeholder="Add teacher name — use commas or / for several"
              aria-label="Add teacher names"
            />
            <button type="submit" className="button button-primary teacher-submit">Add teacher</button>
          </form>
          {teacherFormError && <p className="teacher-form-error" role="alert">{teacherFormError}</p>}
        </div>
        <div className="editor-footer"><p><span className="edit-dot" /> Click any cell to edit. Merged cells are preserved.</p><button className="button button-primary export-button" onClick={() => void exportXlsx()} disabled={loading !== ""}>{loading === "export" ? <><span className="spinner spinner-white" /> Preparing file…</> : <><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 3v9m0 0 3.3-3.3M10 12 6.7 8.7M4 14v2.5h12V14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg> Download Excel</>}</button></div>
      </section>}

      <footer className="page-footer"><span>Made for schedules, built to keep their shape.</span><span className={`model-status ${modelInfo?.reachable ? "model-online" : ""}`}><span className="status-dot" /> {modelInfo?.model ? `Ollama · ${modelInfo.model}` : modelInfo?.reachable ? "Ollama is ready · set a vision model" : "Waiting for local Ollama"}</span></footer>
    </main>
  );
}
