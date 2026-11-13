import { extractTeacherNames, type TimetableLike } from "./teacher-names";

const DAY_ALIASES = new Set([
  "mon",
  "monday",
  "tue",
  "tues",
  "tuesday",
  "wed",
  "wednesday",
  "thu",
  "thur",
  "thurs",
  "thursday",
  "fri",
  "friday",
  "sat",
  "saturday",
  "sun",
  "sunday",
]);

const PLACEHOLDER = /^(blank|nil|none|n\/?a|-|\u2013|\u2014|\.)$/i;

const HEADER =
  /^(subjects?|subject name|teachers?|faculty|staff|names?|period|p|slot|time|day|days|date|class|section|stream)$/i;

const MODE_WORD =
  /^(lab|labs|laboratory|theory|theories|tutorial|tutorials|practical|practicals|practice|activity|activities|program|programme|programmes|session|sessions|class|classes|sem|semester)$/i;

const ROMAN = /^(i|ii|iii|iv|v|vi|vii|viii|ix|x)\.?$/i;
const ROOM_CODE = /^[a-z]{1,2}\d{1,2}$/i;
const HAS_LETTER = /[A-Za-z]/;

const DEPT_CODE =
  /^(cs|it|ece|eee|me|cse|aids|aiml|ee&cs|ce&cs|cs&eng|cse&eng|ecm|mba|mca)$/i;

const IGNORED_SUBJECT =
  /^(asn|asgn|assignment|assignments|lib|library|free|free period|break|lunch|recess|interval|assembly|note|notes|remark|remarks|exam|exams|test|tests)$/i;

const CANONICAL: Record<string, string> = {
  math: "Maths",
  maths: "Maths",
  mathematics: "Maths",
  eng: "English",
  english: "English",
};

const HONORIFIC_NAME =
  /\b(?:mr|mrs|ms|miss|mister|madam|madame|dr|prof|professor|sir|shri|sri|smt|smti)\.?\s+[A-Za-z][A-Za-z.'\u2019-]*(?:\s+[A-Za-z][A-Za-z.'\u2019-]*){0,3}/gi;

function clean(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function normalizeCell(value: string) {
  return value
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .filter(Boolean)
    .join("\n");
}

function stripEdge(value: string) {
  return clean(value).replace(/^[\s.,:;/\u2013\u2014|*-]+|[\s.,:;/\u2013\u2014|*-]+$/g, "");
}

export function subjectKey(value: string) {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "");
}

function isDay(value: string) {
  return DAY_ALIASES.has(stripEdge(value).toLowerCase());
}

function isTimeLabel(value: string) {
  const text = clean(value);
  if (/^(period|slot|time)\s*[-.:]?\s*[a-z0-9]+$/i.test(text)) return true;
  if (/^p\s*[-.:]?\s*\d+[a-z]?$/i.test(text)) return true;
  if (/^\d{1,2}([:.]\d{2})?\s*(?:-|\u2013|\u2014|to)\s*\d{1,2}([:.]\d{2})?(\s*(am|pm))?$/i.test(text)) {
    return true;
  }
  if (/^\d{1,2}[:.]\d{2}(\s*(am|pm))?$/i.test(text)) return true;
  if (/^\d{1,2}\s*(am|pm)$/i.test(text)) return true;
  if (/^\d{1,2}(st|nd|rd|th)?$/i.test(text)) return true;
  return ROMAN.test(text);
}

function stripTeacherNames(text: string, teacherNames: string[]): string {
  let value = text.replace(HONORIFIC_NAME, " ");
  for (const name of teacherNames) {
    if (name.length < 2) continue;
    const pattern = new RegExp(
      name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+"),
      "gi",
    );
    value = value.replace(pattern, " ");
  }
  return value;
}

function cleanSubject(value: string): string | null {
  let text = clean(value.replace(/\([^)]*\)/g, " "));
  if (!text) return null;

  let tokens = text.split(/\s+/).filter(Boolean);
  const modeIndex = tokens.findIndex((token) => MODE_WORD.test(token) || /^[a-z]+lab$/i.test(token));
  if (modeIndex === 0) return null;
  if (modeIndex > 0) tokens = tokens.slice(0, modeIndex);

  tokens = tokens.filter((token) => {
    if (token === "&") return true;
    if (!HAS_LETTER.test(token)) return false;
    if (ROMAN.test(token)) return false;
    if (ROOM_CODE.test(token)) return false;
    return true;
  });

  while (tokens.length > 1 && DEPT_CODE.test(tokens[tokens.length - 1])) tokens.pop();

  text = stripEdge(tokens.join(" "));
  if (!text || !HAS_LETTER.test(text)) return null;
  if (IGNORED_SUBJECT.test(text) || HEADER.test(text) || PLACEHOLDER.test(text)) return null;
  if (isDay(text) || isTimeLabel(text)) return null;

  const key = subjectKey(text);
  return CANONICAL[key] ?? text;
}

export function extractSubjectNames(table: TimetableLike): string[] {
  const cells = table.cells
    .map((cell) => ({ ...cell, text: normalizeCell(cell.text) }))
    .filter((cell) => cell.text.length > 0);

  if (cells.length === 0) return [];

  const teacherNames = extractTeacherNames(table);
  const teacherKeys = new Set(teacherNames.map((name) => subjectKey(name)).filter(Boolean));
  const teacherPatterns = new Set(teacherNames.map(clean).filter(Boolean));

  const subjects = new Map<string, string>();

  for (const cell of cells) {
    const value = stripEdge(cell.text);
    if (!value) continue;
    if (isDay(value) || isTimeLabel(value) || PLACEHOLDER.test(value) || HEADER.test(value)) continue;
    if (teacherPatterns.has(value) || teacherKeys.has(subjectKey(value))) continue;

    const segments = cell.text
      .split(/\n+|\s*[/|;]\s*|\s*[\u2013\u2014]\s*|\s+-\s+/)
      .map(stripEdge)
      .filter(Boolean);

    for (const segment of segments) {
      const withoutTeachers = stripTeacherNames(segment, teacherNames);
      if (!withoutTeachers || !HAS_LETTER.test(withoutTeachers)) continue;

      const subject = cleanSubject(withoutTeachers);
      if (!subject) continue;

      const key = subjectKey(subject);
      if (!key || teacherKeys.has(key)) continue;
      if (!subjects.has(key)) subjects.set(key, subject);
    }
  }

  return Array.from(subjects.values()).sort((first, second) =>
    first.localeCompare(second, undefined, { numeric: true, sensitivity: "base" }),
  );
}
