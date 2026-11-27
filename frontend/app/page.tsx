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
  semester?: string | null;
  academic_session?: string | null;
  room?: string | null;
};
type Constraints = {
  className: string; stream: string; section: string;
  semester: string; academicSession: string; room: string;
};
type Validation = { valid: boolean; errors: string[]; warnings: string[] };
type CropInfo = {
  x: number;
  y: number;
  width: number;
  height: number;
  grid: { row_count: number; column_count: number; cell_count: number; width: number; height: number; column_widths?: number[]; row_heights?: number[] };
  source_page?: number | null;
  source_page_count?: number | null;
  confidence?: number | null;
  review_required?: boolean;
  original_width?: number;
  original_height?: number;
};
type PageChoice = {
  id: string; page_number: number; width: number; height: number;
  crop: { x: number; y: number; width: number; height: number } | null;
  crop_confidence: number | null; crop_status: string; grid: CropInfo["grid"] | null;
  image_url: string; crop_url: string | null; timetable_id: string | null;
};
type SavedTimetable = {
  id: string; document_name: string; page_number: number;
  metadata: Record<string, string | null>; crop_status: string;
  verification_status: string;
};
type PageExtraction = {
  data: {
    subjects: Array<{ name: string; code: string; confidence: number; evidence: string; verification_status: string }>;
    faculty: Array<{ name: string; abbreviation: string; confidence: number; evidence: string; verification_status: string }>;
    relationships: Array<{ subject_name: string; subject_code: string; faculty_name: string; faculty_abbreviation: string; confidence: number; evidence: string; verification_status: string }>;
    page_details: Array<{ class_name: string; semester: string; academic_session: string; room: string; confidence: number; evidence: string; verification_status: string }>;
  };
  confidence: number | null; verification_status: string; model: string; source_page: number;
  ocr_source?: string; prompt_version?: string;
};
type DistinctValueRow = { value: string; categories: string[] };
const EMPTY_GRID: CropInfo["grid"] = { row_count: 0, column_count: 0, cell_count: 0, width: 0, height: 0 };

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

export default function Home() {
  const inputRef = useRef<HTMLInputElement>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const autoAnalyzedTimetable = useRef("");
  const [file, setFile] = useState<File | null>(null);
  const [pdfName, setPdfName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [cropUrl, setCropUrl] = useState("");
  const [cropInfo, setCropInfo] = useState<CropInfo | null>(null);
  const [table, setTable] = useState<TableData | null>(null);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [loading, setLoading] = useState<"preview" | "extract" | "export" | "document" | "save" | "approve" | "analyze" | "load" | "" >("");
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [constraints, setConstraints] = useState<Constraints>({ className: "", stream: "", section: "", semester: "", academicSession: "", room: "" });
  const [toast, setToast] = useState("");
  const [modelInfo, setModelInfo] = useState<{ model: string | null; reachable: boolean } | null>(null);
  const [teachers, setTeachers] = useState<string[]>([]);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [teacherSelection, setTeacherSelection] = useState("");
  const [subjectSelection, setSubjectSelection] = useState("");
  const [documentPages, setDocumentPages] = useState<PageChoice[]>([]);
  const [selectedPage, setSelectedPage] = useState<PageChoice | null>(null);
  const [selectedTimetableId, setSelectedTimetableId] = useState("");
  const [savedTimetables, setSavedTimetables] = useState<SavedTimetable[]>([]);
  const [pageExtraction, setPageExtraction] = useState<PageExtraction | null>(null);
  const [showFacultyJson, setShowFacultyJson] = useState(false);
  const [showTimetableJson, setShowTimetableJson] = useState(false);
  const [verificationStatus, setVerificationStatus] = useState("unverified");
  const [cropCoordinates, setCropCoordinates] = useState({ x: 0, y: 0, width: 0, height: 0 });

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
    void refreshSavedTimetables();
  }, []);

  useEffect(() => {
    fetch(`${API_URL}/api/health`).then((response) => response.json()).then((data) => {
      setModelInfo({ model: data.configured_model, reachable: data.ollama_reachable });
    }).catch(() => setModelInfo({ model: null, reachable: false }));
  }, []);

  useEffect(() => {
    if (!selectedTimetableId || !table || pageExtraction || autoAnalyzedTimetable.current === selectedTimetableId) return;
    autoAnalyzedTimetable.current = selectedTimetableId;
    void analyzePageFor(selectedTimetableId);
  }, [selectedTimetableId, table, pageExtraction]);

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
  const everyDistinctValueRows = useMemo(() => {
    const values = new Map<string, { value: string; categories: Set<string> }>();
    function add(rawValue: string, category: string) {
      const value = rawValue.trim();
      if (!value) return;
      const key = value.toLocaleLowerCase();
      const current = values.get(key) || { value, categories: new Set<string>() };
      current.categories.add(category);
      values.set(key, current);
    }
    for (const value of uniqueValues) add(value, "Timetable value");
    for (const value of teachers) add(value, "Teacher");
    for (const value of subjects) add(value, "Subject");
    for (const member of pageExtraction?.data.faculty ?? []) add(member.name, "Teacher");
    return Array.from(values.values()).map((item): DistinctValueRow => ({
      value: item.value,
      categories: Array.from(item.categories),
    }));
  }, [uniqueValues, teachers, subjects, pageExtraction]);
  const facultyJson = useMemo(() => pageExtraction ? JSON.stringify({
    timetable_id: selectedTimetableId,
    source_document: pdfName || null,
    source_page: pageExtraction.source_page,
    model: pageExtraction.model,
    prompt_version: pageExtraction.prompt_version || null,
    confidence: pageExtraction.confidence,
    verification_status: pageExtraction.verification_status,
    ocr_source: pageExtraction.ocr_source || null,
    data: pageExtraction.data,
  }, null, 2) : "", [selectedTimetableId, pdfName, pageExtraction]);
  const timetableJson = useMemo(() => table ? JSON.stringify({
    record_type: "timetable",
    timetable_id: selectedTimetableId || null,
    source_document: pdfName || null,
    source_page: selectedPage?.page_number ?? cropInfo?.source_page ?? null,
    verification_status: verificationStatus,
    data: table,
  }, null, 2) : "", [table, selectedTimetableId, pdfName, selectedPage?.page_number, cropInfo?.source_page, verificationStatus]);
  const extractedValues = uniqueValues;
  const assignedValues = useMemo(
    () => new Set([...teachers, ...subjects].map((value) => value.toLocaleLowerCase())),
    [teachers, subjects],
  );
  const facultyNames = useMemo(() => {
    const seen = new Set<string>();
    return (pageExtraction?.data.faculty ?? []).flatMap((item) => {
      const name = item.name.trim();
      const key = name.toLocaleLowerCase();
      if (!name || seen.has(key)) return [];
      seen.add(key);
      return [name];
    });
  }, [pageExtraction]);
  const teacherOptions = useMemo(() => {
    const seen = new Set<string>();
    return [...facultyNames, ...extractedValues].filter((value) => {
      const key = value.toLocaleLowerCase();
      if (assignedValues.has(key) || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [facultyNames, extractedValues, assignedValues]);
  const subjectOptions = useMemo(
    () => extractedValues.filter((value) => !assignedValues.has(value.toLocaleLowerCase())),
    [extractedValues, assignedValues],
  );
  const availableValueCount = new Set([...teacherOptions, ...subjectOptions]).size;

  useEffect(() => {
    if (teacherSelection && !teacherOptions.includes(teacherSelection)) setTeacherSelection("");
    if (subjectSelection && !subjectOptions.includes(subjectSelection)) setSubjectSelection("");
  }, [teacherOptions, subjectOptions, teacherSelection, subjectSelection]);

  function addValue(kind: "teacher" | "subject", value: string) {
    const selected = value.trim();
    const options = kind === "teacher" ? teacherOptions : subjectOptions;
    if (!selected || !options.includes(selected)) return;
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

  async function refreshSavedTimetables() {
    try {
      const response = await fetch(`${API_URL}/api/timetables`);
      if (!response.ok) return;
      const data = await response.json();
      setSavedTimetables(data.timetables || []);
    } catch {
      // The library is optional while the API is offline; the upload flow reports its own error.
    }
  }

  function activatePage(page: PageChoice, pageCount = documentPages.length) {
    setSelectedPage(page);
    setSelectedTimetableId(page.timetable_id || "");
    setSourceUrl(`${API_URL}${page.image_url}`);
    setCropUrl(page.crop_url ? `${API_URL}${page.crop_url}` : "");
    setCropInfo(page.crop ? {
      ...page.crop,
      grid: page.grid || EMPTY_GRID,
      source_page: page.page_number,
      source_page_count: pageCount || undefined,
      confidence: page.crop_confidence,
      review_required: page.crop_status === "review_required",
      original_width: page.width,
      original_height: page.height,
    } : null);
    setCropCoordinates(page.crop || {
      x: Math.round(page.width * 0.1), y: Math.round(page.height * 0.1),
      width: Math.round(page.width * 0.8), height: Math.round(page.height * 0.8),
    });
    setTable(null);
    setValidation(null);
    setPageExtraction(null);
    setShowFacultyJson(false);
    setShowTimetableJson(false);
    setVerificationStatus("unverified");
    setTeachers([]);
    setSubjects([]);
    setTeacherSelection("");
    setSubjectSelection("");
  }

  async function loadSavedTimetable(timetableId: string) {
    if (!timetableId) return;
    setError("");
    setLoading("load");
    try {
      const response = await fetch(`${API_URL}/api/timetables/${timetableId}`);
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      const page: PageChoice = {
        ...data.page,
        timetable_id: timetableId,
        grid: null,
      };
      setFile(null);
      setDocumentPages([]);
      setSelectedPage(page);
      setSelectedTimetableId(timetableId);
      setPdfName(data.page.document_name);
      setSourceUrl(`${API_URL}${data.page.image_url}`);
      setCropUrl(data.page.crop_url ? `${API_URL}${data.page.crop_url}` : "");
      setCropInfo(data.page.crop ? {
        ...data.page.crop, grid: EMPTY_GRID, source_page: data.page.page_number,
        confidence: data.page.crop_confidence, review_required: data.page.crop_status === "review_required",
        original_width: data.page.width, original_height: data.page.height,
      } : null);
      setCropCoordinates(data.page.crop || { x: 0, y: 0, width: data.page.width, height: data.page.height });
      const metadata = data.metadata || {};
      setConstraints({
        className: metadata.class_name || "", stream: metadata.stream || "", section: metadata.section || "",
        semester: metadata.semester || "", academicSession: metadata.academic_session || "", room: metadata.room || "",
      });
      setTable(data.table || null);
      setValidation(null);
      setShowFacultyJson(false);
      setShowTimetableJson(false);
      setPageExtraction(data.page_extraction ? {
        data: data.page_extraction.data, confidence: data.page_extraction.confidence,
        verification_status: data.page_extraction.verification_status,
        model: data.page_extraction.model, source_page: data.page.page_number,
        ocr_source: data.page_extraction.ocr?.source, prompt_version: data.page_extraction.prompt_version,
      } : null);
      setVerificationStatus(data.version?.verification_status || "unverified");
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

  async function applyManualCrop() {
    if (!selectedPage) return;
    setError("");
    setLoading("preview");
    try {
      const response = await fetch(`${API_URL}/api/pages/${selectedPage.id}/crop`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...cropCoordinates, class_name: constraints.className, stream: constraints.stream,
          section: constraints.section, semester: constraints.semester, academic_session: constraints.academicSession, room: constraints.room }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      const updated = { ...selectedPage, crop: data.crop, crop_url: data.crop_url, crop_status: data.crop_status,
        crop_confidence: data.crop_confidence, timetable_id: data.timetable_id, grid: data.grid };
      setSelectedPage(updated);
      setDocumentPages((pages) => pages.map((page) => page.id === updated.id ? updated : page));
      setSelectedTimetableId(data.timetable_id);
      setCropUrl(`${API_URL}${data.crop_url}`);
      setCropInfo({ ...data.crop, grid: data.grid || EMPTY_GRID, source_page: updated.page_number,
        source_page_count: documentPages.length || undefined, confidence: 1, review_required: false,
        original_width: updated.width, original_height: updated.height });
      setTable(null);
      setPageExtraction(null);
      setShowFacultyJson(false);
      setShowTimetableJson(false);
      await refreshSavedTimetables();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  async function prepareFile(nextFile: File) {
    if (!constraintsReady) {
      showToast("Please fill in class, stream, and section above before uploading the timetable.");
      return;
    }
    setError("");
    setTable(null);
    setValidation(null);
    setCropInfo(null);
    setFile(nextFile);
    setPdfName(isPdfFile(nextFile) ? nextFile.name : "");
    setDocumentPages([]);
    setSelectedPage(null);
    setSelectedTimetableId("");
    setPageExtraction(null);
    setShowFacultyJson(false);
    setShowTimetableJson(false);
    setVerificationStatus("unverified");
    setTeachers([]);
    setSubjects([]);
    setTeacherSelection("");
    setSubjectSelection("");
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    if (cropUrl) URL.revokeObjectURL(cropUrl);
    // PDFs are saved and split by the backend; image uploads retain the original quick preview flow.
    setSourceUrl(isPdfFile(nextFile) ? "" : URL.createObjectURL(nextFile));
    setCropUrl("");
    setLoading(isPdfFile(nextFile) ? "document" : "preview");
    try {
      const form = new FormData();
      form.append("file", nextFile);
      form.append("class_name", constraints.className.trim());
      form.append("stream", constraints.stream.trim());
      form.append("section", constraints.section.trim());
      form.append("semester", constraints.semester.trim());
      form.append("academic_session", constraints.academicSession.trim());
      form.append("room", constraints.room.trim());
      if (isPdfFile(nextFile)) {
        const response = await fetch(`${API_URL}/api/documents/upload`, { method: "POST", body: form });
        const data = await response.json();
        if (!response.ok) throw new Error(getApiError(data));
        const pages: PageChoice[] = data.pages || [];
        setDocumentPages(pages);
        setPdfName(data.filename);
        const preferred = pages.find((page) => page.timetable_id) || pages[0];
        if (preferred) activatePage(preferred, pages.length);
        if (!pages.some((page) => page.timetable_id)) {
          setError("The PDF was saved and split, but no timetable was detected. Select a page and set its crop coordinates below.");
        }
        await refreshSavedTimetables();
        return;
      }
      const response = await fetch(`${API_URL}/api/preview`, { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      if (data.source_png_base64) {
        const sourceBlob = await fetch(`data:image/png;base64,${data.source_png_base64}`).then((result) => result.blob());
        setSourceUrl(URL.createObjectURL(sourceBlob));
      }
      const cropBlob = await fetch(`data:image/png;base64,${data.crop_png_base64}`).then((result) => result.blob());
      setCropUrl(URL.createObjectURL(cropBlob));
      setCropInfo({
        ...data.crop,
        grid: data.grid,
        source_page: data.source_page,
        source_page_count: data.source_page_count,
        confidence: data.crop_confidence,
        review_required: data.crop_review_required,
        original_width: data.original.width,
        original_height: data.original.height,
      });
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

  async function extract() {
    if ((!file && !selectedTimetableId) || !cropUrl) return;
    setError("");
    setLoading("extract");
    try {
      let response: Response;
      if (selectedTimetableId) {
        response = await fetch(`${API_URL}/api/timetables/${selectedTimetableId}/extract`, { method: "POST" });
      } else {
        const form = new FormData();
        form.append("file", file as File);
        form.append("class_name", constraints.className.trim());
        form.append("stream", constraints.stream.trim());
        form.append("section", constraints.section.trim());
        const meta = await fetch(`${API_URL}/api/extract`, { method: "POST", body: form });
        response = meta;
      }
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      setTable(data.table);
      setValidation(data.validation);
      setVerificationStatus("unverified");
      setTeachers([]);
      setSubjects([]);
      setTeacherSelection("");
      setSubjectSelection("");
      if (selectedTimetableId) void refreshSavedTimetables();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  async function saveCorrections() {
    if (!table || !selectedTimetableId) return;
    setError("");
    setLoading("save");
    try {
      const response = await fetch(`${API_URL}/api/timetables/${selectedTimetableId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ table, metadata: {
          class_name: constraints.className, stream: constraints.stream, section: constraints.section,
          semester: constraints.semester, academic_session: constraints.academicSession, room: constraints.room,
        } }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      setTable(data.table);
      setVerificationStatus(data.verification_status);
      showToast("Corrections saved as a new timetable version.");
      await refreshSavedTimetables();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  async function approveTimetable() {
    if (!table || !selectedTimetableId) return;
    setError("");
    setLoading("approve");
    try {
      const response = await fetch(`${API_URL}/api/timetables/${selectedTimetableId}/approve`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ table, metadata: {
          class_name: constraints.className, stream: constraints.stream, section: constraints.section,
          semester: constraints.semester, academic_session: constraints.academicSession, room: constraints.room,
        } }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      setTable(data.table);
      setVerificationStatus(data.verification_status);
      showToast("This timetable version is approved.");
      await refreshSavedTimetables();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  async function analyzePageFor(timetableId: string) {
    setError("");
    setLoading("analyze");
    try {
      const response = await fetch(`${API_URL}/api/timetables/${timetableId}/analyze-page`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      setPageExtraction({ data: data.data, confidence: data.confidence,
        verification_status: data.verification_status, model: data.model, source_page: data.source_page,
        ocr_source: data.ocr?.source, prompt_version: data.prompt_version });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  async function analyzeOriginalPage() {
    if (!selectedTimetableId) return;
    autoAnalyzedTimetable.current = selectedTimetableId;
    await analyzePageFor(selectedTimetableId);
  }

  async function verifyOriginalPage(status: "verified" | "needs_review") {
    if (!selectedTimetableId || !pageExtraction) return;
    setError("");
    setLoading("save");
    try {
      const response = await fetch(`${API_URL}/api/timetables/${selectedTimetableId}/page-extraction/verify`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verification_status: status, data: pageExtraction.data }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(getApiError(data));
      if (pageExtraction) {
        const updated = { ...pageExtraction, data: data.data, verification_status: status };
        setPageExtraction(updated);
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading("");
    }
  }

  async function copyFacultyJson() {
    if (!facultyJson) return;
    try {
      await navigator.clipboard.writeText(facultyJson);
      showToast("Faculty JSON copied.");
    } catch {
      setError("Could not copy JSON here. Use Download JSON to save a shareable file.");
    }
  }

  function downloadFacultyJson() {
    if (!facultyJson || !pageExtraction) return;
    const fileBase = (pdfName || "timetable").replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "-") || "timetable";
    const blob = new Blob([facultyJson], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${fileBase}-page-${pageExtraction.source_page}-faculty.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function copyTimetableJson() {
    if (!timetableJson) return;
    try {
      await navigator.clipboard.writeText(timetableJson);
      showToast("Timetable JSON copied.");
    } catch {
      setError("Could not copy JSON here. Use Download JSON to save a shareable file.");
    }
  }

  function downloadTimetableJson() {
    if (!timetableJson) return;
    const fileBase = (pdfName || "timetable").replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "-") || "timetable";
    const pageNumber = selectedPage?.page_number ?? cropInfo?.source_page;
    const pageSuffix = pageNumber ? `-page-${pageNumber}` : "";
    const blob = new Blob([timetableJson], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${fileBase}${pageSuffix}-timetable.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
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
    options: string[],
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
            disabled={options.length === 0}
          >
            <option value="">
              {options.length > 0 ? `Choose a ${label}` : "No values left to add"}
            </option>
            {options.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <button type="submit" className="button button-primary classification-add" disabled={!selection || !options.includes(selection)}>Add</button>
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
          <label className="constraint-field">
            <span>Semester</span>
            <input value={constraints.semester} onChange={(event) => updateConstraint("semester", event.target.value)} placeholder="e.g. 7th" maxLength={40} autoComplete="off" />
          </label>
          <label className="constraint-field">
            <span>Academic session</span>
            <input value={constraints.academicSession} onChange={(event) => updateConstraint("academicSession", event.target.value)} placeholder="e.g. 2026–2027" maxLength={80} autoComplete="off" />
          </label>
          <label className="constraint-field">
            <span>Room</span>
            <input value={constraints.room} onChange={(event) => updateConstraint("room", event.target.value)} placeholder="e.g. CV 400" maxLength={80} autoComplete="off" />
          </label>
        </div>
      </section>

      {savedTimetables.length > 0 && <section className="saved-library" aria-label="Saved timetables">
        <label className="constraint-field">
          <span>Saved timetables</span>
          <select value={selectedTimetableId} onChange={(event) => void loadSavedTimetable(event.target.value)} disabled={loading !== ""}>
            <option value="">Choose a saved timetable</option>
            {savedTimetables.map((item) => <option key={item.id} value={item.id}>
              {item.document_name} · page {item.page_number} · {item.metadata.class_name || "Class unset"} · {item.verification_status}
            </option>)}
          </select>
        </label>
      </section>}

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
        <div className="upload-foot"><span>{constraintsReady ? "PDFs are stored locally, split into pages, and analyzed with Ollama on this computer." : "Add class, stream, and section above to enable upload."}</span><span className="step-label">01 <i /> 02 <i /> 03</span></div>
      </section>

      {error && <div className="error-banner" role="alert"><span className="error-mark">!</span><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}

      {toast && <div className="toast" role="alert" aria-live="assertive"><span className="toast-mark">!</span><span className="toast-text">{toast}</span><button className="toast-close" aria-label="Dismiss message" onClick={dismissToast}>×</button></div>}

      {(sourceUrl || loading === "preview" || loading === "document") && <section className="preview-section" aria-live="polite">
        <div className="section-heading"><div><div className="section-kicker">STEP 1 <span>·</span> CHECK THE CROP</div><h2>{cropUrl ? "Review the detected timetable." : "Choose the timetable area."}</h2></div>{cropInfo && <div className="crop-dimensions">{cropInfo.grid.row_count ? `${cropInfo.grid.row_count} rows × ${cropInfo.grid.column_count} columns · ${cropInfo.grid.cell_count} cells · ` : ""}{cropInfo.source_page ? `page ${cropInfo.source_page}${cropInfo.source_page_count ? ` of ${cropInfo.source_page_count}` : ""} · ` : ""}{cropInfo.confidence != null ? `${Math.round(cropInfo.confidence * 100)}% crop confidence` : ""}</div>}</div>
        {documentPages.length > 1 && <div className="page-picker">
          <label className="constraint-field"><span>Source page</span><select value={selectedPage?.id || ""} onChange={(event) => {
            const next = documentPages.find((page) => page.id === event.target.value);
            if (next) activatePage(next);
          }}>
            {documentPages.map((page) => <option key={page.id} value={page.id}>Page {page.page_number} · {page.crop_status.replaceAll("_", " ")}</option>)}
          </select></label>
          <span className="unique-hint">All {documentPages.length} PDF pages are saved. Each page is checked separately.</span>
        </div>}
        <div className="preview-grid">
          <article className="preview-card source-card"><div className="preview-card-head"><span>ORIGINAL SOURCE PAGE</span><span className="mini-tag">{pdfName ? `Page ${selectedPage?.page_number || cropInfo?.source_page || ""}` : "Source"}</span></div><ZoomImage src={sourceUrl} alt="Original timetable source page" className="source-frame">{pdfName ? <div className="pdf-source-placeholder"><span className="pdf-badge">PDF</span><strong>{pdfName}</strong><span>{loading === "document" ? "Splitting pages…" : "Source page preview"}</span></div> : <div className="crop-empty">The source preview will appear here.</div>}</ZoomImage></article>
          <article className="preview-card crop-card"><div className="preview-card-head"><span>TIMETABLE CROP</span><span className="mini-tag mini-tag-blue">Table only</span></div><ZoomImage src={cropUrl} alt="Detected timetable crop" className="crop-frame">{loading === "preview" ? <div className="loading-state"><span className="spinner" />Finding table borders…</div> : <div className="crop-empty">No crop yet. Review the source and enter its timetable bounds below.</div>}</ZoomImage></article>
        </div>
        {selectedPage && selectedPage.crop_status === "review_required" && <div className="review-notice">Automatic detection is uncertain for this page. Check the crop preview or adjust the rectangle to keep only the timetable.</div>}
        {selectedPage && (selectedPage.crop_status !== "detected") && <div className="crop-review-form">
          <div><strong>Crop review</strong><span>Page coordinates in pixels · source is {selectedPage.width} × {selectedPage.height}</span></div>
          {(["x", "y", "width", "height"] as const).map((key) => <label className="constraint-field" key={key}><span>{key}</span>
            <input type="number" min={0} value={cropCoordinates[key]} onChange={(event) => setCropCoordinates((current) => ({ ...current, [key]: Number(event.target.value) }))} />
          </label>)}
          <button className="button button-secondary" onClick={() => void applyManualCrop()} disabled={loading !== "" || !selectedPage}>Confirm / apply crop</button>
        </div>}
        {cropUrl && <div className="action-row"><p>Check that the crop includes the full table and nothing extra.</p><button className="button button-primary" onClick={() => void extract()} disabled={loading !== "" || selectedPage?.crop_status === "review_required"}>{loading === "extract" ? <><span className="spinner spinner-white" /> Reading timetable…</> : selectedPage?.crop_status === "review_required" ? <>Confirm the crop before extraction</> : <>Extract timetable <span aria-hidden="true">→</span></>}</button></div>}
      </section>}

      {table && <section className="editor-section" aria-live="polite">
        <div className="section-heading editor-heading">
          <div><div className="section-kicker">STEP 2 <span>·</span> REVIEW & EDIT</div><h2>Your editable timetable.</h2></div>
          <div className="editor-heading-tools">
            <div className="table-stats"><span>{table.row_count} rows</span><span className="stats-separator">·</span><span>{table.column_count} columns</span><span className="stats-separator">·</span><span>{table.cells.length} cells</span></div>
            <button className="button button-secondary" onClick={() => setShowTimetableJson((open) => !open)}>{showTimetableJson ? "Hide JSON" : "View timetable JSON"}</button>
          </div>
        </div>
        <div className="constraint-summary" aria-label="Saved timetable details">
          <span className="constraint-summary-label">Timetable details</span>
          <span className="constraint-chip"><span>Class</span><strong>{table.class_name || constraints.className.trim() || "—"}</strong></span>
          <span className="constraint-chip"><span>Stream</span><strong>{table.stream || constraints.stream.trim() || "—"}</strong></span>
          <span className="constraint-chip"><span>Section</span><strong>{table.section || constraints.section.trim() || "—"}</strong></span>
          <span className="constraint-chip"><span>Semester</span><strong>{table.semester || constraints.semester.trim() || "—"}</strong></span>
          <span className="constraint-chip"><span>Session</span><strong>{table.academic_session || constraints.academicSession.trim() || "—"}</strong></span>
          <span className="constraint-chip"><span>Room</span><strong>{table.room || constraints.room.trim() || "—"}</strong></span>
          {selectedPage && <span className="constraint-chip"><span>Source</span><strong>Page {selectedPage.page_number}{selectedPage.crop_confidence != null ? ` · ${Math.round(selectedPage.crop_confidence * 100)}% crop` : ""}</strong></span>}
          {selectedTimetableId && <span className="constraint-chip"><span>Verification</span><strong>{verificationStatus.replaceAll("_", " ")}</strong></span>}
        </div>
        {validation && (validation.warnings.length > 0 || validation.errors.length > 0) && <div className={`validation-box ${validation.errors.length ? "validation-error" : ""}`}><span className="validation-icon">{validation.errors.length ? "!" : "✓"}</span><div><strong>{validation.errors.length ? "Review needed" : "Structure checked"}</strong>{[...validation.errors, ...validation.warnings].map((warning, index) => <p key={index}>{warning}</p>)}</div></div>}
        <div className="table-wrap"><table className="editable-table" style={{ width: `${table.column_widths.reduce((sum, width) => sum + width, 0) * displayScale}px` }}><colgroup>{table.column_widths.map((width, index) => <col key={index} style={{ width: `${width / table.column_widths.reduce((sum, value) => sum + value, 0) * 100}%` }} />)}</colgroup><tbody>{Array.from({ length: table.row_count }, (_, row) => <tr key={row} style={{ height: `${table.row_heights[row] * displayScale}px` }}>{Array.from({ length: table.column_count }, (_, column) => {
          const key = `${row},${column}`;
          if (cellMap.covered.has(key)) return null;
          const cell = cellMap.origins.get(key);
          if (!cell) return <td key={key} className="unresolved-cell"><textarea aria-label={`Row ${row + 1}, column ${column + 1}`} value="" placeholder="Blank" onChange={(event) => updateCell(row, column, event.target.value)} /></td>;
          return <td key={key} rowSpan={cell.rowspan} colSpan={cell.colspan}><textarea aria-label={`Row ${row + 1}, column ${column + 1}${cell.rowspan > 1 || cell.colspan > 1 ? ", merged cell" : ""}`} value={cell.text} placeholder="Blank" onChange={(event) => updateCell(cell.row, cell.column, event.target.value)} /></td>;
        })}</tr>)}</tbody></table></div>
        {showTimetableJson && <section className="json-viewer-panel timetable-json-panel" aria-label="Editable timetable JSON">
          <div className="json-viewer-heading">
            <div><div className="section-kicker">CURRENT EDITOR DATA <span>·</span> JSON VIEW</div><h3>Timetable data</h3></div>
            <div className="editor-actions json-viewer-actions">
              <button className="button button-secondary" onClick={() => void copyTimetableJson()}>Copy JSON</button>
              <button className="button button-secondary" onClick={downloadTimetableJson}>Download JSON</button>
              <button className="button button-secondary" onClick={() => setShowTimetableJson(false)}>Close</button>
            </div>
          </div>
          <p className="unique-hint">This is the table currently shown in the editor. Save corrections to store edits as a new timetable version; the original AI extraction remains separate.</p>
          <pre className="json-viewer-code">{timetableJson}</pre>
        </section>}
        {selectedTimetableId && <section className="page-data-section faculty-results" aria-label="Faculty extracted from the full source page">
          <div className="section-heading unique-heading">
            <div><div className="section-kicker">FULL SOURCE PAGE <span>·</span> FACULTY EXTRACTION</div><h2>Faculty table.</h2></div>
            <div className="editor-actions faculty-actions">
              {pageExtraction && <button className="button button-secondary" onClick={() => setShowFacultyJson((open) => !open)}>
                {showFacultyJson ? "Hide JSON" : "View JSON"}
              </button>}
              <button className="button button-secondary" onClick={() => void analyzeOriginalPage()} disabled={loading !== ""}>
                {loading === "analyze" ? <><span className="spinner" />Reading full page…</> : pageExtraction ? "Re-analyze faculty" : "Analyze faculty table"}
              </button>
            </div>
          </div>
          <p className="unique-hint">After timetable extraction, MiniCPM-V checks the entire original page and lists only rows from its faculty table.</p>
          {pageExtraction && <div className="page-analysis-status">Page {pageExtraction.source_page} · {pageExtraction.model} · OCR: {pageExtraction.ocr_source || "not available"} · {pageExtraction.confidence == null ? "No confidence score" : `${Math.round(pageExtraction.confidence * 100)}% average confidence`}</div>}
          <div className="classification-card faculty-table-card">
            <div className="classification-card-head"><div><div className="section-kicker">FACULTY DIRECTORY</div><h3>Faculty & abbreviations</h3></div><span className="classification-count">{pageExtraction?.data.faculty.length ?? 0}</span></div>
            <div className="table-wrap unique-wrap"><table className="unique-table faculty-table">
              <thead><tr><th scope="col">Faculty name</th><th scope="col">Abbreviation</th><th scope="col">Confidence</th><th scope="col">Source page</th><th scope="col">Verification</th><th scope="col">Evidence</th></tr></thead>
              <tbody>{pageExtraction?.data.faculty.length ? pageExtraction.data.faculty.map((item, index) => <tr key={`${item.name}-${item.abbreviation}-${index}`}>
                <td className="unique-value">{item.name || "Unresolved"}</td><td>{item.abbreviation || "—"}</td><td>{Math.round(item.confidence * 100)}%</td>
                <td>Page {pageExtraction.source_page}</td><td>{item.verification_status.replaceAll("_", " ")}</td><td>{item.evidence || "—"}</td>
              </tr>) : <tr><td colSpan={6} className="classification-empty">{pageExtraction ? "No faculty entries were found on this page." : loading === "analyze" ? "Reading the full source page…" : "Faculty details will appear here after analysis."}</td></tr>}</tbody>
            </table></div>
          </div>
          {pageExtraction && showFacultyJson && <section className="json-viewer-panel" aria-label="Faculty extraction JSON">
            <div className="json-viewer-heading">
              <div><div className="section-kicker">SAVED RECORD <span>·</span> JSON VIEW</div><h3>Faculty extraction data</h3></div>
              <div className="editor-actions json-viewer-actions">
                <button className="button button-secondary" onClick={() => void copyFacultyJson()}>Copy JSON</button>
                <button className="button button-secondary" onClick={downloadFacultyJson}>Download JSON</button>
                <button className="button button-secondary" onClick={() => setShowFacultyJson(false)}>Close</button>
              </div>
            </div>
            <p className="unique-hint">The data object matches the stored extraction JSON. The app keeps the record in its local database; Download JSON creates a standalone file to share.</p>
            <pre className="json-viewer-code">{facultyJson}</pre>
          </section>}
          {pageExtraction && <div className="verification-actions"><span>Faculty values: <strong>{pageExtraction.verification_status.replaceAll("_", " ")}</strong></span>
            <button className="button button-secondary" onClick={() => void verifyOriginalPage("needs_review")} disabled={loading !== ""}>Needs review</button>
            <button className="button button-primary" onClick={() => void verifyOriginalPage("verified")} disabled={loading !== ""}>Mark faculty verified</button>
          </div>}
        </section>}
        {everyDistinctValueRows.length > 0 && <section className="unique-section" aria-label="Unique timetable, teacher, and subject values">
          <div className="section-heading unique-heading">
            <div>
              <div className="section-kicker">FROM THE CROPPED TIMETABLE <span>·</span> UNIQUE VALUES</div>
              <h2>Every distinct value.</h2>
            </div>
            <span className="unique-count">{everyDistinctValueRows.length} {everyDistinctValueRows.length === 1 ? "value" : "values"}</span>
          </div>
          <p className="unique-hint">Includes timetable-cell values, extracted teacher names, and values classified as teachers or subjects. Duplicate text appears once with each matching category.</p>
          <div className="table-wrap unique-wrap"><table className="unique-table">
            <thead><tr><th scope="col">#</th><th scope="col">Category</th><th scope="col">Value</th></tr></thead>
            <tbody>{everyDistinctValueRows.map((item, index) => <tr key={`${item.value}-${index}`}>
              <td className="unique-index">{index + 1}</td>
              <td>{item.categories.join(" · ")}</td><td className="unique-value">{item.value}</td>
            </tr>)}</tbody>
          </table></div>
        </section>}
        {extractedValues.length > 0 && <section className="classification-section" aria-label="Teachers and subjects">
          <div className="section-heading unique-heading">
            <div>
              <div className="section-kicker">EXTRACTED VALUES <span>·</span> CLASSIFY</div>
              <h2>Teachers and subjects.</h2>
            </div>
            <span className="unique-count">{availableValueCount} available</span>
          </div>
          <p className="unique-hint">Teacher choices include names extracted from the full page. Subject choices come from the timetable values. A value added to one list is removed from the other.</p>
          <div className="classification-grid">
            {classificationCard("teacher", "TEACHERS", teachers, teacherOptions, teacherSelection, setTeacherSelection)}
            {classificationCard("subject", "SUBJECTS", subjects, subjectOptions, subjectSelection, setSubjectSelection)}
          </div>
        </section>}
        <div className="editor-footer"><p><span className="edit-dot" /> Click any cell to edit. Merged cells are preserved.</p><div className="editor-actions">
          {selectedTimetableId && <><button className="button button-secondary" onClick={() => void saveCorrections()} disabled={loading !== ""}>{loading === "save" ? "Saving…" : "Save corrections"}</button><button className="button button-secondary" onClick={() => void approveTimetable()} disabled={loading !== "" || verificationStatus === "approved"}>{loading === "approve" ? "Approving…" : verificationStatus === "approved" ? "Approved" : "Approve timetable"}</button></>}
          <button className="button button-primary export-button" onClick={() => void exportXlsx()} disabled={loading !== ""}>{loading === "export" ? <><span className="spinner spinner-white" /> Preparing file…</> : <><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M10 3v9m0 0 3.3-3.3M10 12 6.7 8.7M4 14v2.5h12V14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg> Download Excel</>}</button>
        </div></div>
      </section>}

      <footer className="page-footer"><span>Made for schedules, built to keep their shape.</span><span className={`model-status ${modelInfo?.reachable ? "model-online" : ""}`}><span className="status-dot" /> {modelInfo?.model ? `Ollama · ${modelInfo.model}` : modelInfo?.reachable ? "Ollama is ready · set a vision model" : "Waiting for local Ollama"}</span></footer>
    </main>
  );
}
