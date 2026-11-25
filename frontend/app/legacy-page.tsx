"use client";

import { ChangeEvent, DragEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

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
  semester?: string | null;
  source_page?: number | null;
};
type Constraints = { className: string; stream: string; section: string };
type Validation = { valid: boolean; errors: string[]; warnings: string[] };
type Candidate = {
  id: string;
  page: number | null;
  semester: string;
  confidence: string;
  selected: boolean;
  cropSrc: string;
  sourceSrc: string;
};
type TimetableTab = {
  id: string;
  table: TableData;
  validation: Validation | null;
  teachers: string[];
  subjects: string[];
  teacherSelection: string;
  subjectSelection: string;
};
type ExtractedResult = {
  id: string | null;
  page: number | null;
  semester: string | null;
  table: TableData;
  validation: Validation;
};

const ACCEPTED_FILE_TYPES = "image/png,image/jpeg,image/webp,application/pdf,.pdf";

function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

function isPdfFile(file: File) {
  return file.type === "application/pdf" || /\.pdf$/i.test(file.name);
}

function isSupportedFile(file: File) {
  return file.type.startsWith("image/") || isPdfFile(file);
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

function plural(count: number, word: string) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function dataUrl(base64: string | null | undefined) {
  return base64 ? `data:image/png;base64,${base64}` : "";
}

export default function Home() {
  const inputRef = useRef<HTMLInputElement>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [isPdf, setIsPdf] = useState(false);
  const [pdfName, setPdfName] = useState("");
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [scannedPages, setScannedPages] = useState(0);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [tabs, setTabs] = useState<TimetableTab[]>([]);
  const [activeTabId, setActiveTabId] = useState("");
  const [loading, setLoading] = useState<"discover" | "extract" | "export" | "">("");
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [constraints, setConstraints] = useState<Constraints>({ className: "", stream: "", section: "" });
  const [toast, setToast] = useState("");
  const [sarvamConfigured, setSarvamConfigured] = useState<boolean | null>(null);

  const constraintsReady = Boolean(
    constraints.className.trim() && constraints.stream.trim() && constraints.section.trim(),
  );
  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? tabs[0] ?? null;
  const table = activeTab?.table ?? null;
  const selectedCandidates = candidates.filter((candidate) => candidate.selected);

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
      setSarvamConfigured(Boolean(data.api_key_configured));
    }).catch(() => setSarvamConfigured(false));
  }, []);

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

  const totalWidth = table?.column_widths.reduce((sum, width) => sum + width, 0) ?? 0;
  const displayScale = table && totalWidth
    ? Math.max(900, Math.round(totalWidth * 0.78)) / totalWidth
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

  const assignedValues = useMemo(
    () => new Set([...(activeTab?.teachers ?? []), ...(activeTab?.subjects ?? [])]),
    [activeTab],
  );
  const availableValues = useMemo(
    () => uniqueValues.filter((value) => !assignedValues.has(value)),
    [uniqueValues, assignedValues],
  );
  const teacherSelection = activeTab && availableValues.includes(activeTab.teacherSelection)
    ? activeTab.teacherSelection
    : "";
  const subjectSelection = activeTab && availableValues.includes(activeTab.subjectSelection)
    ? activeTab.subjectSelection
    : "";

  function updateCandidate(id: string, patch: Partial<Candidate>) {
    setCandidates((current) => current.map((candidate) => candidate.id === id ? { ...candidate, ...patch } : candidate));
  }

  function updateTab(id: string, patch: Partial<TimetableTab>) {
    setTabs((current) => current.map((tab) => tab.id === id ? { ...tab, ...patch } : tab));
  }

  function addValue(kind: "teacher" | "subject", value: string) {
    if (!activeTab) return;
    const selected = value.trim();
    if (!selected || !availableValues.includes(selected)) return;
    if (kind === "teacher") {
      updateTab(activeTab.id, {
        teachers: [...activeTab.teachers.filter((item) => item !== selected), selected],
        teacherSelection: "",
        subjectSelection: subjectSelection === selected ? "" : activeTab.subjectSelection,
      });
    } else {
      updateTab(activeTab.id, {
        subjects: [...activeTab.subjects.filter((item) => item !== selected), selected],
        subjectSelection: "",
        teacherSelection: teacherSelection === selected ? "" : activeTab.teacherSelection,
      });
    }
  }

  function removeValue(kind: "teacher" | "subject", value: string) {
    if (!activeTab) return;
    if (kind === "teacher") {
      updateTab(activeTab.id, { teachers: activeTab.teachers.filter((item) => item !== value) });
    } else {
      updateTab(activeTab.id, { subjects: activeTab.subjects.filter((item) => item !== value) });
    }
  }

  function updateCell(row: number, column: number, text: string) {
    if (!table || !activeTab) return;
    updateTab(activeTab.id, {
      table: {
        ...table,
        cells: table.cells.map((cell) => cell.row === row && cell.column === column ? { ...cell, text } : cell),
      },
    });
  }

  async function prepareFile(nextFile: File) {
    if (!constraintsReady) {
      showToast("Please fill in class, stream, and section above before uploading the timetable.");
      return;
    }
    setError("");
    setTabs([]);
    setActiveTabId("");
    setCandidates([]);
    setPageCount(null);
    setScannedPages(0);
    setFile(nextFile);
    setIsPdf(isPdfFile(nextFile));
    setPdfName(isPdfFile(nextFile) ? nextFile.name : "");
    setLoading("discover");
    try {
      const form = new FormData();
      form.append("file", nextFile);
      form.append("class_name", constraints.className.trim());
      form.append("stream", constraints.stream.trim());
      form.append("section", constraints.section.trim());
      const response = await fetch(`${API_URL}/api/discover`, { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      const found: Candidate[] = (data.timetables || []).map((item: any, index: number) => ({
        id: String(item.page ?? index + 1),
        page: item.page ?? null,
        semester: item.semester_guess ?? "",
        confidence: item.semester_confidence ?? "none",
        selected: true,
        cropSrc: dataUrl(item.crop_png_base64),
        sourceSrc: dataUrl(item.source_png_base64),
      }));
      setCandidates(found);
      setIsPdf(Boolean(data.is_pdf));
      setPageCount(data.page_count ?? null);
      setScannedPages(data.scanned_pages ?? found.length);
      if (found.length === 0) {
        setError("No timetables were found. Check that every timetable has clear ruled lines, then try another file.");
      } else {
        showToast(`Found ${plural(found.length, "timetable")}. Check the crops and semester names, then choose which ones to read.`);
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const nextFile = event.target.files?.[0];
    if (nextFile) void prepareFile(nextFile);
    event.target.value = "";
  }

  function chooseFile() {
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
    if (nextFile && isSupportedFile(nextFile)) void prepareFile(nextFile);
    else setError("Choose a PNG, JPEG, WebP image, or PDF.");
  }

  async function extractSelected() {
    if (!file || selectedCandidates.length === 0) return;
    const missingNames = selectedCandidates.filter((candidate) => !candidate.semester.trim());
    if (missingNames.length > 0) {
      setError(`Type a semester name for ${plural(missingNames.length, "selected timetable")} before reading.`);
      return;
    }
    setError("");
    setLoading("extract");
    try {
      const targets = selectedCandidates.map((candidate) => ({
        id: candidate.id,
        page: candidate.page,
        semester: candidate.semester.trim(),
      }));
      const form = new FormData();
      form.append("file", file);
      form.append("targets", JSON.stringify(targets));
      form.append("class_name", constraints.className.trim());
      form.append("stream", constraints.stream.trim());
      form.append("section", constraints.section.trim());
      const response = await fetch(`${API_URL}/api/extract-many`, { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));

      const results = new Map<string, ExtractedResult>();
      for (const item of (data.tables || []) as ExtractedResult[]) {
        results.set(String(item.id ?? ""), item);
      }
      const nextTabs: TimetableTab[] = selectedCandidates
        .filter((candidate) => results.has(candidate.id))
        .map((candidate) => {
          const result = results.get(candidate.id)!;
          return {
            id: candidate.id,
            table: result.table,
            validation: result.validation,
            teachers: [],
            subjects: [],
            teacherSelection: "",
            subjectSelection: "",
          };
        });
      setTabs(nextTabs);
      setActiveTabId(nextTabs[0]?.id ?? "");

      const failures = (data.failures || []) as { page: number | null; message: string }[];
      if (failures.length > 0) {
        const labels = failures.map((failure) => failure.page ? `page ${failure.page}` : "the image");
        setError(`${plural(failures.length, "timetable")} could not be read (${labels.join(", ")}): ${failures[0].message}`);
      } else if (nextTabs.length > 0) {
        showToast(`Read ${plural(nextTabs.length, "timetable")}. Review each tab, then download the Excel file.`);
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  async function exportXlsx() {
    if (tabs.length === 0) return;
    setError("");
    setLoading("export");
    try {
      const response = await fetch(`${API_URL}/api/export-all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tables: tabs.map((tab) => tab.table) }),
      });
      if (!response.ok) throw new Error(getApiError(await response.json()));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      const details = tabs[0].table;
      const parts = [
        details.class_name || constraints.className,
        details.stream || constraints.stream,
        details.section || constraints.section,
      ]
        .map((part) => part.trim().replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, ""))
        .filter(Boolean);
      anchor.download = parts.length ? `timetables_${parts.join("_")}.xlsx` : "timetables.xlsx";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  function onTabKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (tabs.length < 2 || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
    event.preventDefault();
    const current = tabs.findIndex((tab) => tab.id === activeTab?.id);
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next = tabs[(current + step + tabs.length) % tabs.length];
    setActiveTabId(next.id);
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
        <div className="eyebrow"><span className="eyebrow-line" /> IMAGE / PDF TO SPREADSHEET</div>
        <h1>Every timetable,<br /><span>ready to edit.</span></h1>
      </section>

      <section className="constraint-card" aria-label="Timetable details">
        <div className="constraint-head">
          <div>
            <div className="section-kicker">TIMETABLE DETAILS <span>·</span> REQUIRED</div>
            <h2>Which timetables are you uploading?</h2>
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

      <section className={`upload-card ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} aria-label="Upload timetable image or PDF">
        <div className="upload-main">
          <div className="upload-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 15v4a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg></div>
          <div className="upload-copy">
            <strong>{file ? file.name : "Drop your timetable image or PDF here"}</strong>
            <span>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · PNG, JPG, WebP or PDF` : "PNG, JPG, WebP or PDF · up to 20 MB"}</span>
          </div>
          <button className={`button button-secondary choose-button ${constraintsReady ? "" : "button-locked"}`} onClick={chooseFile} disabled={loading !== ""} aria-disabled={!constraintsReady} title={constraintsReady ? undefined : "Fill in class, stream, and section first"}>{file ? "Choose another" : "Choose file"}</button>
          <input ref={inputRef} className="visually-hidden" type="file" accept={ACCEPTED_FILE_TYPES} onChange={onFileChange} />
        </div>
        <div className="upload-foot"><span>{constraintsReady ? "Every page is checked for a timetable; only detected crops are sent to the local reader." : "Add class, stream, and section above to enable upload."}</span><span className="step-label">01 <i /> 02 <i /> 03</span></div>
      </section>

      {error && <div className="error-banner" role="alert"><span className="error-mark">!</span><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}

      {toast && <div className="toast" role="alert" aria-live="assertive"><span className="toast-mark">!</span><span className="toast-text">{toast}</span><button className="toast-close" aria-label="Dismiss message" onClick={dismissToast}>×</button></div>}

      {(candidates.length > 0 || loading === "discover") && <section className="discovery-section" aria-live="polite">
        <div className="section-heading">
          <div>
            <div className="section-kicker">STEP 1 <span>·</span> FIND EVERY TIMETABLE</div>
            <h2>{loading === "discover" ? "Checking every page…" : `We found ${plural(candidates.length, "timetable")}.`}</h2>
          </div>
          <div className="crop-dimensions">
            {isPdf && pageCount ? `${plural(scannedPages, "page")} scanned of ${pageCount}` : "Image source"}
          </div>
        </div>
        {loading === "discover" ? (
          <div className="discovery-loading"><span className="spinner" /> Looking for ruled tables on every page…</div>
        ) : (
          <>
            <div className="discovery-toolbar">
              <p>Tick the timetables you want, check each crop, and confirm the semester name. Missing names must be typed before reading.</p>
              <div className="selection-controls">
                <button type="button" className="text-button" onClick={() => setCandidates((current) => current.map((candidate) => ({ ...candidate, selected: true })))}>Select all</button>
                <button type="button" className="text-button" onClick={() => setCandidates((current) => current.map((candidate) => ({ ...candidate, selected: false })))}>Clear all</button>
              </div>
            </div>
            {candidates.length === 0 ? (
              <div className="empty-state">No ruled timetables were detected in this file. Try a clearer image or PDF.</div>
            ) : (
              <div className="selection-grid">
                {candidates.map((candidate) => (
                  <article key={candidate.id} className={`timetable-card ${candidate.selected ? "is-selected" : ""}`}>
                    <label className="card-check">
                      <input
                        type="checkbox"
                        checked={candidate.selected}
                        onChange={(event) => updateCandidate(candidate.id, { selected: event.target.checked })}
                      />
                      <span>Include this timetable</span>
                    </label>
                    <div className="card-preview">
                      {candidate.cropSrc ? (
                        <ZoomImage src={candidate.cropSrc} alt={`Detected timetable crop${candidate.page ? ` on page ${candidate.page}` : ""}`} className="card-frame" />
                      ) : (
                        <div className="crop-empty">Crop preview unavailable.</div>
                      )}
                    </div>
                    <div className="card-meta">
                      <span className="mini-tag mini-tag-blue">{candidate.page ? `Page ${candidate.page}` : "Image"}</span>
                      <span className="card-confidence">
                        {candidate.confidence === "high" ? "Semester detected" : candidate.confidence === "low" ? "Best guess — please confirm" : "Semester not found"}
                      </span>
                    </div>
                    <label className="semester-field">
                      <span>Semester name</span>
                      <input
                        value={candidate.semester}
                        onChange={(event) => updateCandidate(candidate.id, { semester: event.target.value })}
                        placeholder="e.g. Semester III"
                        maxLength={80}
                        autoComplete="off"
                      />
                    </label>
                  </article>
                ))}
              </div>
            )}
            {candidates.length > 0 && <div className="action-row">
              <p>Check that each crop includes the full table and nothing extra. {plural(selectedCandidates.length, "timetable")} selected.</p>
              <button className="button button-primary" onClick={() => void extractSelected()} disabled={loading !== "" || selectedCandidates.length === 0}>
                {loading === "extract" ? <><span className="spinner spinner-white" /> Reading timetables…</> : <>Read selected timetables <span aria-hidden="true">→</span></>}
              </button>
            </div>}
          </>
        )}
      </section>}

      {tabs.length > 0 && table && activeTab && <section className="editor-section" aria-live="polite">
        <div className="section-heading editor-heading">
          <div>
            <div className="section-kicker">STEP 2 <span>·</span> REVIEW & EDIT</div>
            <h2>Your timetables, ready to edit.</h2>
          </div>
          <div className="table-stats"><span>{plural(tabs.length, "tab")}</span><span className="stats-separator">·</span><span>{table.row_count} rows</span><span className="stats-separator">·</span><span>{table.column_count} columns</span><span className="stats-separator">·</span><span>{table.cells.length} cells</span></div>
        </div>

        <div className="tabs-bar" role="tablist" aria-label="Semester timetables" onKeyDown={onTabKeyDown}>
          {tabs.map((tab, index) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`timetable-tab-${tab.id}`}
              aria-selected={tab.id === activeTab.id}
              aria-controls="timetable-panel"
              tabIndex={tab.id === activeTab.id ? 0 : -1}
              className={`tab-button ${tab.id === activeTab.id ? "is-active" : ""}`}
              onClick={() => setActiveTabId(tab.id)}
            >
              <span className="tab-index">{String(index + 1).padStart(2, "0")}</span>
              <span className="tab-text">
                <strong>{tab.table.semester || "Untitled timetable"}</strong>
                <small>{tab.table.source_page ? `Page ${tab.table.source_page}` : "Image"} · {tab.table.row_count}×{tab.table.column_count}</small>
              </span>
            </button>
          ))}
        </div>

        <div id="timetable-panel" role="tabpanel" aria-labelledby={`timetable-tab-${activeTab.id}`} className="tab-panel">
          <div className="constraint-summary" aria-label="Saved timetable details">
            <span className="constraint-summary-label">Timetable details</span>
            <span className="constraint-chip"><span>Class</span><strong>{table.class_name || constraints.className.trim() || "—"}</strong></span>
            <span className="constraint-chip"><span>Stream</span><strong>{table.stream || constraints.stream.trim() || "—"}</strong></span>
            <span className="constraint-chip"><span>Section</span><strong>{table.section || constraints.section.trim() || "—"}</strong></span>
            <span className="constraint-chip"><span>Semester</span><strong>{table.semester || "—"}</strong></span>
            <span className="constraint-chip"><span>Page</span><strong>{table.source_page ?? "Image"}</strong></span>
          </div>
          {activeTab.validation && (activeTab.validation.warnings.length > 0 || activeTab.validation.errors.length > 0) && <div className={`validation-box ${activeTab.validation.errors.length ? "validation-error" : ""}`}><span className="validation-icon">{activeTab.validation.errors.length ? "!" : "✓"}</span><div><strong>{activeTab.validation.errors.length ? "Review needed" : "Structure checked"}</strong>{[...activeTab.validation.errors, ...activeTab.validation.warnings].map((warning, index) => <p key={index}>{warning}</p>)}</div></div>}
          <div className="table-wrap"><table className="editable-table" style={{ width: `${totalWidth * displayScale}px` }}><colgroup>{table.column_widths.map((width, index) => <col key={index} style={{ width: `${width / totalWidth * 100}%` }} />)}</colgroup><tbody>{Array.from({ length: table.row_count }, (_, row) => <tr key={row} style={{ height: `${table.row_heights[row] * displayScale}px` }}>{Array.from({ length: table.column_count }, (_, column) => {
            const key = `${row},${column}`;
            if (cellMap.covered.has(key)) return null;
            const cell = cellMap.origins.get(key);
            if (!cell) return <td key={key} className="unresolved-cell"><textarea aria-label={`Row ${row + 1}, column ${column + 1}`} value="" placeholder="Blank" onChange={(event) => updateCell(row, column, event.target.value)} /></td>;
            return <td key={key} rowSpan={cell.rowspan} colSpan={cell.colspan}><textarea aria-label={`Row ${row + 1}, column ${column + 1}${cell.rowspan > 1 || cell.colspan > 1 ? ", merged cell" : ""}`} value={cell.text} placeholder="Blank" onChange={(event) => updateCell(cell.row, cell.column, event.target.value)} /></td>;
          })}</tr>)}</tbody></table></div>
          {uniqueValues.length > 0 && <section className="unique-section" aria-label="Unique timetable values">
            <div className="section-heading unique-heading">
              <div>
                <div className="section-kicker">FROM THIS CROPPED TIMETABLE <span>·</span> UNIQUE VALUES</div>
                <h2>Every distinct value.</h2>
              </div>
              <span className="unique-count">{uniqueValues.length} {uniqueValues.length === 1 ? "value" : "values"}</span>
            </div>
            <p className="unique-hint">Values are taken directly from this timetable's cells, exactly as read from the crop. Edits in the table above update this list.</p>
            <div className="table-wrap unique-wrap"><table className="unique-table">
              <thead><tr><th scope="col">#</th><th scope="col">Value</th></tr></thead>
              <tbody>{uniqueValues.map((value, index) => <tr key={`${value}-${index}`}>
                <td className="unique-index">{index + 1}</td>
                <td className="unique-value">{value}</td>
              </tr>)}</tbody>
            </table></div>
          </section>}
          {uniqueValues.length > 0 && <section className="classification-section" aria-label="Teachers and subjects">
            <div className="section-heading unique-heading">
              <div>
                <div className="section-kicker">EXTRACTED VALUES <span>·</span> CLASSIFY</div>
                <h2>Teachers and subjects.</h2>
              </div>
              <span className="unique-count">{availableValues.length} available</span>
            </div>
            <p className="unique-hint">These lists are kept separately for {table.semester || "this timetable"}. Choose from this tab's values; a value added to one list is removed from the other.</p>
            <div className="classification-grid">
              {classificationCard("teacher", "TEACHERS", activeTab.teachers, teacherSelection, (value) => activeTab && updateTab(activeTab.id, { teacherSelection: value }))}
              {classificationCard("subject", "SUBJECTS", activeTab.subjects, subjectSelection, (value) => activeTab && updateTab(activeTab.id, { subjectSelection: value }))}
            </div>
          </section>}
        </div>

        <div className="editor-footer"><p><span className="edit-dot" /> Click any cell to edit. Merged cells are preserved. Each semester becomes its own Excel sheet.</p><button className="button button-primary export-button" onClick={() => void exportXlsx()} disabled={loading !== ""}>{loading === "export" ? <><span className="spinner spinner-white" /> Preparing file…</> : <><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 3v9m0 0 3.3-3.3M10 12 6.7 8.7M4 14v2.5h12V14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg> Download Excel</>}</button></div>
      </section>}

      <footer className="page-footer"><span>Made for schedules, built to keep their shape.</span><span className={`model-status ${sarvamConfigured ? "model-online" : ""}`}><span className="status-dot" /> {sarvamConfigured === null ? "Checking Sarvam" : sarvamConfigured ? "Sarvam doc AI is configured" : "Set SARVAM_API_KEY in backend/.env"}</span></footer>
    </main>
  );
}
