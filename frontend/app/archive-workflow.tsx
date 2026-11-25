"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

type Status = "queued" | "processing" | "review" | "verified" | "published" | "failed";
type DocumentRow = { id: string; filename: string; status: Status; page_count: number | null; table_count: number; error_message?: string | null; processing_warnings?: string[]; created_at: string };
type Cell = { row: number; column: number; rowspan: number; colspan: number; text: string; raw_text?: string; coordinates?: { x: number; y: number; width: number; height: number; source_page_bbox?: Record<string, unknown> } };
type Timetable = {
  id: string; document_id: string; source_page: number; table_index: number; table_type: string; status: Status;
  academic_year: string | null; semester: string | null; class_name: string | null; section: string | null; stream: string | null; room: string | null;
  row_count: number; column_count: number; column_widths: number[]; row_heights: number[]; source_bbox: Record<string, number>;
  page_size: Record<string, number>; raw_page_text: string; metadata_confidence: Record<string, string>; warnings: string[]; cells: Cell[];
};
type DocumentDetail = { id: string; filename: string; status: Status; page_count: number | null; size_bytes: number; error_message: string | null; processing_warnings: string[]; tables: Timetable[] };
type Option = { id: number; label: string; name?: string; section?: string };
type Options = { semesters: Option[]; classes: Option[]; academic_years: Option[]; rooms: Option[] };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : "The request could not be completed. Check the API and database setup.");
  return body as T;
}

function statusLabel(status: Status) {
  return ({ queued: "Queued", processing: "Processing", review: "Needs review", verified: "Verified", published: "Published", failed: "Failed" })[status] || status;
}

export default function ArchiveWorkflow() {
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [activeDocumentId, setActiveDocumentId] = useState("");
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [reviewId, setReviewId] = useState("");
  const [selected, setSelected] = useState<Timetable | null>(null);
  const [options, setOptions] = useState<Options>({ semesters: [], classes: [], academic_years: [], rooms: [] });
  const [semesterId, setSemesterId] = useState("");
  const [classId, setClassId] = useState("");
  const [yearId, setYearId] = useState("");
  const [roomId, setRoomId] = useState("");
  const [optionsRefresh, setOptionsRefresh] = useState(0);
  const [matches, setMatches] = useState<{ id: string; source_page: number; class_name: string; section: string; academic_year: string }[]>([]);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const review = useMemo(() => detail?.tables.find((table) => table.id === reviewId) || null, [detail, reviewId]);

  const refreshDocuments = useCallback(async () => {
    try { setDocuments(await api<DocumentRow[]>("/api/documents")); } catch { /* The API may still be starting. */ }
  }, []);

  useEffect(() => {
    void refreshDocuments();
    const timer = window.setInterval(() => void refreshDocuments(), 2500);
    return () => window.clearInterval(timer);
  }, [refreshDocuments]);

  const refreshDetail = useCallback(async (id: string) => {
    try {
      const next = await api<DocumentDetail>(`/api/documents/${id}`);
      setDetail(next);
      setReviewId((current) => next.tables.some((table) => table.id === current) ? current : next.tables[0]?.id || "");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load document."); }
  }, []);

  useEffect(() => {
    if (!activeDocumentId) { setDetail(null); setReviewId(""); return; }
    void refreshDetail(activeDocumentId);
    const row = documents.find((doc) => doc.id === activeDocumentId);
    if (row && ["queued", "processing"].includes(row.status)) {
      const timer = window.setInterval(() => void refreshDetail(activeDocumentId), 2500);
      return () => window.clearInterval(timer);
    }
  }, [activeDocumentId, documents, refreshDetail]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (semesterId) params.set("semester_id", semesterId);
    if (classId) params.set("class_id", classId);
    if (yearId) params.set("academic_year_id", yearId);
    let ignore = false;
    api<Options>(`/api/options?${params.toString()}`).then((data) => { if (!ignore) setOptions(data); }).catch(() => undefined);
    return () => { ignore = true; };
  }, [semesterId, classId, yearId, optionsRefresh]);

  useEffect(() => {
    if (!(semesterId && classId && yearId && roomId)) { setMatches([]); setSelected(null); return; }
    const params = new URLSearchParams({ semester_id: semesterId, class_id: classId, academic_year_id: yearId, room_id: roomId });
    let ignore = false;
    api<{ id: string; source_page: number; class_name: string; section: string; academic_year: string }[]>(`/api/timetables/search?${params.toString()}`)
      .then((rows) => { if (!ignore) { setMatches(rows); if (!rows.some((row) => row.id === selected?.id)) setSelected(null); } })
      .catch(() => { if (!ignore) setMatches([]); });
    return () => { ignore = true; };
  }, [semesterId, classId, yearId, roomId, selected?.id, optionsRefresh]);

  async function uploadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") { setError("Choose a department timetable PDF."); return; }
    setError(""); setMessage(""); setUploading(true);
    try {
      const form = new FormData(); form.append("file", file);
      const result = await api<{ id: string; status: Status }>("/api/documents", { method: "POST", body: form });
      setActiveDocumentId(result.id); setMessage("PDF stored. Page extraction is running in the background."); await refreshDocuments();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Upload failed."); }
    finally { setUploading(false); }
  }

  async function deleteDocument(doc: DocumentRow) {
    if (["queued", "processing"].includes(doc.status)) return;
    const accepted = window.confirm(`Delete “${doc.filename}”, its original PDF, and all extracted timetable records? This cannot be undone.`);
    if (!accepted) return;
    setBusy(`delete:${doc.id}`); setError(""); setMessage("");
    try {
      await api<null>(`/api/documents/${doc.id}`, { method: "DELETE" });
      setDocuments((current) => current.filter((item) => item.id !== doc.id));
      if (activeDocumentId === doc.id) { setActiveDocumentId(""); setDetail(null); setReviewId(""); }
      if (selected?.document_id === doc.id) setSelected(null);
      setOptionsRefresh((value) => value + 1);
      setMessage(`Deleted ${doc.filename} and its stored timetable records.`);
      await refreshDocuments();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not delete this document."); }
    finally { setBusy(""); }
  }

  function updateField(field: keyof Timetable, value: string) {
    if (!review || !detail) return;
    const next = { ...review, [field]: value || null } as Timetable;
    setDetail({ ...detail, tables: detail.tables.map((table) => table.id === review.id ? next : table) });
  }

  function updateCell(index: number, text: string) {
    if (!review || !detail) return;
    const cells = review.cells.map((cell, cellIndex) => cellIndex === index ? { ...cell, text } : cell);
    const next = { ...review, cells };
    setDetail({ ...detail, tables: detail.tables.map((table) => table.id === review.id ? next : table) });
  }

  async function saveReview() {
    if (!review) return;
    setBusy("save"); setError("");
    try {
      const saved = await api<Timetable>(`/api/timetables/${review.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ academic_year: review.academic_year, semester: review.semester, class_name: review.class_name,
          section: review.section, stream: review.stream, room: review.room,
          cells: review.cells.map((cell) => ({ row: cell.row, column: cell.column, text: cell.text })) }),
      });
      if (detail) setDetail({ ...detail, tables: detail.tables.map((table) => table.id === saved.id ? saved : table) });
      setMessage("Review changes saved."); await refreshDocuments();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not save the review."); }
    finally { setBusy(""); }
  }

  async function transition(action: "verify" | "publish") {
    if (!review) return;
    setBusy(action); setError("");
    try {
      if (action === "verify") await saveReview();
      const saved = await api<Timetable>(`/api/timetables/${review.id}/${action}`, { method: "POST" });
      if (detail) setDetail({ ...detail, tables: detail.tables.map((table) => table.id === saved.id ? saved : table) });
      setMessage(action === "verify" ? "Timetable verified. Publish it when ready." : "Timetable published and available in the filters.");
      if (action === "publish") setOptionsRefresh((value) => value + 1);
      await refreshDocuments();
    } catch (caught) { setError(caught instanceof Error ? caught.message : `Could not ${action} timetable.`); }
    finally { setBusy(""); }
  }

  async function openPublished(id: string) {
    try { setSelected(await api<Timetable>(`/api/timetables/${id}`)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load timetable."); }
  }

  const activeDocument = documents.find((doc) => doc.id === activeDocumentId);

  return (
    <main className="archive-shell">
      <header className="archive-header">
        <a className="brand" href="#archive" aria-label="FeelIQ Technologies home"><img className="brand-logo" src="/feeliq-logo.png" alt="FeelIQ Technologies" /></a>
        <span className="archive-local">DEPARTMENT TIMETABLE ARCHIVE</span>
      </header>
      <section className="archive-intro" id="archive">
        <div className="eyebrow"><span className="eyebrow-line" /> PDF TO SEARCHABLE TIMETABLES</div>
        <h1>One archive,<br /><span>every class and room.</span></h1>
        <p>Upload a department PDF. Pages are processed in the background, class timetable metadata is saved for review, and published timetables become available through dependent filters.</p>
      </section>

      <section className="archive-card" aria-label="Upload department timetable PDF">
        <div><div className="section-kicker">01 <span>·</span> STORE & PROCESS</div><h2>Upload department PDF</h2>
          <p>The original PDF stays in the local archive. Extracted tables keep their page and cell coordinates.</p></div>
        <label className={`button button-primary archive-upload ${uploading ? "is-busy" : ""}`}>
          {uploading ? <><span className="spinner spinner-white" /> Uploading…</> : "Choose PDF"}
          <input type="file" accept="application/pdf,.pdf" onChange={(event) => void uploadFile(event)} disabled={uploading} />
        </label>
      </section>
      {error && <div className="error-banner"><span className="error-mark">!</span><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss">×</button></div>}
      {message && <div className="archive-message" role="status">✓ {message}<button onClick={() => setMessage("")} aria-label="Dismiss">×</button></div>}

      <section className="archive-section">
        <div className="section-heading"><div><div className="section-kicker">02 <span>·</span> PROCESSING & REVIEW</div><h2>Stored documents</h2></div><span className="crop-dimensions">{documents.length} PDF{documents.length === 1 ? "" : "s"}</span></div>
        {documents.length ? <div className="document-list">{documents.map((doc) => <article key={doc.id} className={`document-row ${activeDocumentId === doc.id ? "is-selected" : ""}`}>
          <button className="document-open" onClick={() => { setActiveDocumentId(doc.id); setMessage(""); setError(""); }}>
            <span className="document-icon">PDF</span><span className="document-title"><strong>{doc.filename}</strong><small>{doc.page_count ? `${doc.page_count} pages · ` : ""}{doc.table_count} main timetable{doc.table_count === 1 ? "" : "s"}</small></span><span className={`status-pill status-${doc.status}`}>{["queued", "processing"].includes(doc.status) && <i className="status-spinner" />}{statusLabel(doc.status)}</span>
          </button>
          <button className="document-delete" onClick={() => void deleteDocument(doc)} disabled={busy !== "" || ["queued", "processing"].includes(doc.status)} title={["queued", "processing"].includes(doc.status) ? "Wait for processing to finish" : "Delete stored PDF and timetable records"} aria-label={`Delete ${doc.filename}`}>
            {busy === `delete:${doc.id}` ? "Deleting…" : "Delete"}
          </button>
        </article>)}</div> : <div className="archive-empty">Uploaded PDFs will appear here with their processing and review status.</div>}
      </section>

      {activeDocument && detail && <section className="archive-section review-panel">
        <div className="section-heading"><div><div className="section-kicker">03 <span>·</span> METADATA & TABLE REVIEW</div><h2>{detail.filename}</h2></div><div className="review-links"><a className="button button-secondary" href={`${API_URL}/api/documents/${detail.id}/original`}>Original PDF</a><a className="button button-secondary" href={`${API_URL}/api/documents/${detail.id}/json`}>Download JSON</a></div></div>
        {detail.error_message && <div className="archive-warning">{detail.error_message}</div>}
        {detail.processing_warnings?.map((warning, index) => <div className="archive-warning" key={`processing-${index}`}>{warning}</div>)}
        {["queued", "processing"].includes(detail.status) && <div className="archive-loading"><span className="spinner" /> Processing pages, recognizing metadata and table cells… You can keep this page open and review the results when they are ready.</div>}
        {detail.tables.length > 0 && <>
          <div className="review-table-list">{detail.tables.map((table) => <button key={table.id} className={`review-table-chip ${reviewId === table.id ? "is-active" : ""}`} onClick={() => setReviewId(table.id)}>
            <span>Page {table.source_page} · Main timetable</span><strong>{table.semester || "Timetable"}</strong><small>{statusLabel(table.status)}</small>
          </button>)}</div>
          {review && <>
            <div className="review-meta-grid">
              <label>Semester<input value={review.semester || ""} onChange={(event) => updateField("semester", event.target.value)} placeholder="Detected semester" /></label>
              <label>Class<input value={review.class_name || ""} onChange={(event) => updateField("class_name", event.target.value)} placeholder="Detected class or year" /></label>
              <label>Academic year / session<input value={review.academic_year || ""} onChange={(event) => updateField("academic_year", event.target.value)} placeholder="e.g. 2025–26" /></label>
              <label>Room<input value={review.room || ""} onChange={(event) => updateField("room", event.target.value)} placeholder="Detected room" /></label>
              <label>Section<input value={review.section || ""} onChange={(event) => updateField("section", event.target.value)} placeholder="Section" /></label>
              <label>Stream / department<input value={review.stream || ""} onChange={(event) => updateField("stream", event.target.value)} placeholder="Department or stream" /></label>
            </div>
            <div className="archive-table-title"><div><span className="section-kicker">PAGE {review.source_page} <span>·</span> MAIN TIMETABLE</span><h3>Review detected cells</h3></div><span className={`status-pill status-${review.status}`}>{statusLabel(review.status)}</span></div>
            {review.warnings.map((warning, index) => <div className="archive-warning" key={index}>{warning}</div>)}
            <div className="archive-grid-wrap"><table className="archive-grid"><tbody>{Array.from({ length: review.row_count }, (_, row) => <tr key={row}>{Array.from({ length: review.column_count }, (_, column) => {
              const cellIndex = review.cells.findIndex((cell) => cell.row === row && cell.column === column);
              if (cellIndex < 0) {
                const covered = review.cells.some((cell) => row >= cell.row && row < cell.row + cell.rowspan && column >= cell.column && column < cell.column + cell.colspan);
                return covered ? null : <td key={`${row}-${column}`} className="archive-grid-empty" />;
              }
              const cell = review.cells[cellIndex];
              return <td key={`${row}-${column}`} rowSpan={cell.rowspan} colSpan={cell.colspan}>
                <textarea aria-label={`Page ${review.source_page}, row ${row + 1}, column ${column + 1}`} value={cell.text} onChange={(event) => updateCell(cellIndex, event.target.value)} />
              </td>;
            })}</tr>)}</tbody></table></div>
            <details className="source-details"><summary>Source timetable text and geometry</summary><p>Page {review.source_page} · crop x {review.source_bbox.x}, y {review.source_bbox.y}, width {review.source_bbox.width}, height {review.source_bbox.height} · page {review.page_size.width} × {review.page_size.height} pixels</p><pre>{review.raw_page_text || "No embedded PDF text; the page was read from its image."}</pre><p>Cell-level raw text and coordinates are included in the JSON download.</p></details>
            <div className="review-actions"><p>Check extracted values and metadata before publishing. Merged cells and cell coordinates stay attached to the source page.</p><div><button className="button button-secondary" onClick={() => void saveReview()} disabled={busy !== ""}>{busy === "save" ? "Saving…" : "Save review"}</button><button className="button button-primary" onClick={() => void transition("verify")} disabled={busy !== "" || review.status === "published"}>{busy === "verify" ? "Verifying…" : "Verify timetable"}</button><button className="button button-primary" onClick={() => void transition("publish")} disabled={busy !== "" || review.status !== "verified"}>{busy === "publish" ? "Publishing…" : "Publish"}</button></div></div>
          </>}
        </>}
      </section>}

      <section className="archive-section finder-panel">
        <div className="section-heading"><div><div className="section-kicker">04 <span>·</span> PUBLISHED TIMETABLES</div><h2>Find a timetable</h2></div></div>
        <p className="archive-help">Choose each value in order. The next list updates to match the previous selections. “Session” is stored as the academic year.</p>
        <div className="filter-grid">
          <label>Semester<select value={semesterId} onChange={(event) => { setSemesterId(event.target.value); setClassId(""); setYearId(""); setRoomId(""); }}><option value="">Select semester</option>{options.semesters.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label>Class<select value={classId} disabled={!semesterId} onChange={(event) => { setClassId(event.target.value); setYearId(""); setRoomId(""); }}><option value="">Select class</option>{options.classes.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label>Academic year / session<select value={yearId} disabled={!classId} onChange={(event) => { setYearId(event.target.value); setRoomId(""); }}><option value="">Select academic year</option>{options.academic_years.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label>Room<select value={roomId} disabled={!yearId} onChange={(event) => setRoomId(event.target.value)}><option value="">Select room</option>{options.rooms.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        </div>
        {matches.length > 0 && <div className="published-list">{matches.map((match) => <button key={match.id} className="published-result" onClick={() => void openPublished(match.id)}>Open timetable · Page {match.source_page}<span>{match.class_name}{match.section ? ` · Section ${match.section}` : ""} · {match.academic_year}</span></button>)}</div>}
        {selected && <article className="published-table"><div className="archive-table-title"><div><span className="section-kicker">VERIFIED & PUBLISHED <span>·</span> PAGE {selected.source_page}</span><h3>{selected.semester} · {selected.class_name}{selected.section ? ` · ${selected.section}` : ""} · {selected.room}</h3></div><a className="button button-secondary" href={`${API_URL}/api/documents/${selected.document_id}/json`}>Download JSON</a></div><div className="archive-grid-wrap"><table className="archive-grid"><tbody>{Array.from({ length: selected.row_count }, (_, row) => <tr key={row}>{Array.from({ length: selected.column_count }, (_, column) => { const cell = selected.cells.find((item) => item.row === row && item.column === column); if (!cell) { const covered = selected.cells.some((item) => row >= item.row && row < item.row + item.rowspan && column >= item.column && column < item.column + item.colspan); return covered ? null : <td key={`${row}-${column}`} className="archive-grid-empty" />; } return <td key={`${row}-${column}`} rowSpan={cell.rowspan} colSpan={cell.colspan}>{cell.text}</td>; })}</tr>)}</tbody></table></div></article>}
        {semesterId && classId && yearId && roomId && matches.length === 0 && <div className="archive-empty">No published timetable matches all four selected values.</div>}
      </section>
      <footer className="page-footer"><span>Original PDF + PostgreSQL records + downloadable JSON</span><span className="model-status"><span className="status-dot" /> Review each extraction before publishing</span></footer>
    </main>
  );
}
