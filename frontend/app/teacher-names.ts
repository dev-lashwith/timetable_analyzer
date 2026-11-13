export type TimetableCellLike = { row: number; column: number; text: string };
export type TimetableLike = {
  row_count: number;
  column_count: number;
  cells: TimetableCellLike[];
};

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

const TEACHER_HEADER =
  /^(teachers?|faculty|staff|names?|teacher names?|name of (?:the )?teacher)$/i;

const HONORIFIC_TOKEN =
  /^(mr|mrs|ms|miss|mister|madam|madame|dr|prof|professor|sir|shri|sri|smt|smti)\.?$/i;

const PLACEHOLDER = /^(blank|nil|none|n\/?a|-|–|—|\.)$/i;

const IGNORED_LABEL =
  /^(period|p|slot|time|date|class|section|stream|room|hall|break|lunch|recess|interval|assembly|free|free period|theory|practical|practicals|tutorial|tutorials|revision|exam|exams|test|tests|assessment|assignment|assignments|project|projects|lab|laboratory|labs|library|lib|sports?|games?|activity|activity period|note|notes|remark|remarks|admin|program|programme|python|java|oop|asn|nss|ic|cad|cons|think|blank)$/i;
const IGNORED_PREFIX = /^(class|section|stream|room|hall|break|lunch|recess|interval|assembly)\b/i;
const CLASS_CODE = /^(?:[a-z]{1,3}\d+|\d+[a-z]{1,3})$/i;

const SUBJECT_WORD =
  /^(?:math|maths|mathematics|algebra|geometry|trigonometry|calculus|statistics|english|grammar|literature|composition|spelling|handwriting|science|physics|chemistry|biology|botany|zoology|social|studies|study|history|geography|civics|civic|economics|commerce|accountancy|accounts|account|business|entrepreneurship|computer|computers|information|technology|applications?|programming|coding|hindi|telugu|tamil|kannada|malayalam|marathi|bengali|urdu|sanskrit|french|german|spanish|arabic|art|arts|fine|music|dance|drama|theatre|physical|education|sport|sports|game|games|library|moral|values?|value|evs|environmental|psychology|sociology|political|home|agriculture|engineering|drawing|painting|craft|crafts|work|health|yoga|general|knowledge|sst|ss|sci|eng|phy|chem|bio|comp|hist|geog|geo|eco|econ|pol|psy|soc|hin|tel|san|ict|cs|pe|robotics|reasoning|aptitude|language|languages|first|second|third)$/i;
const SUBJECT_PHRASE =
  /\b(math|maths|mathematics|algebra|geometry|trigonometry|calculus|statistics|english|grammar|literature|composition|science|physics|chemistry|biology|botany|zoology|social studies|social|studies|history|geography|civics|economics|commerce|accountancy|accounts|business|entrepreneurship|computer|information technology|programming|coding|hindi|telugu|tamil|kannada|malayalam|marathi|bengali|urdu|sanskrit|french|german|spanish|arabic|fine arts|arts?|music|dance|drama|physical education|physical|sports?|games?|library|moral|values?|evs|environmental|psychology|sociology|political|home science|agriculture|engineering|drawing|painting|crafts?|work|health|yoga|robotics|reasoning|aptitude|language)\b/i;
const CONNECTOR = /^(and|&|of|the)$/i;

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
  return clean(value).replace(/^[\s.,:;/\-–—|]+|[\s.,:;/\-–—|]+$/g, "");
}

function isDay(text: string) {
  const value = stripEdge(text).toLowerCase();
  return DAY_ALIASES.has(value);
}

function isTeacherHeader(text: string) {
  return TEACHER_HEADER.test(stripEdge(text));
}

function isTimeLabel(text: string) {
  const value = clean(text);
  if (/^(period|slot|time)\s*[-.:]?\s*[a-z0-9]+$/i.test(value)) return true;
  if (/^p\s*[-.:]?\s*\d+[a-z]?$/i.test(value)) return true;
  if (/^\d{1,2}([:.]\d{2})?\s*(?:-|–|—|to)\s*\d{1,2}([:.]\d{2})?(\s*(am|pm))?$/i.test(value)) return true;
  if (/^\d{1,2}[:.]\d{2}(\s*(am|pm))?$/i.test(value)) return true;
  if (/^\d{1,2}\s*(am|pm)$/i.test(value)) return true;
  if (/^\d{1,2}(st|nd|rd|th)?$/i.test(value)) return true;
  return /^(i|ii|iii|iv|v|vi|vii|viii|ix|x)$/i.test(value);
}

function isNameToken(token: string) {
  if (SUBJECT_WORD.test(token) || IGNORED_LABEL.test(token)) return false;
  return /^[A-Za-z][A-Za-z.'’-]*\.?$/.test(token);
}

function splitCell(text: string): string[] {
  return text
    .split(/\n+/)
    .flatMap((line) => line.split(/(?<!\d):(?!\d)|\s*[|(),;]\s*|\s+[-–—]\s*|\s*[-–—]\s+/))
    .map(clean)
    .filter(Boolean);
}

function nameFromTokens(tokens: string[], start: number): string | null {
  const collected = [tokens[start]];
  for (let index = start + 1; index < tokens.length && collected.length < 5; index += 1) {
    if (!isNameToken(tokens[index])) break;
    collected.push(tokens[index]);
  }
  if (collected.length < 2) return null;
  return clean(collected.join(" "));
}

function honorificName(part: string): string | null {
  const tokens = clean(part).split(/\s+/).filter(Boolean);
  for (let index = 0; index < tokens.length; index += 1) {
    if (!HONORIFIC_TOKEN.test(tokens[index])) continue;
    const name = nameFromTokens(tokens, index);
    if (name) return name;
  }
  return null;
}

function baseKey(name: string) {
  return clean(name)
    .split(/\s+/)
    .filter((token) => !HONORIFIC_TOKEN.test(token))
    .join(" ")
    .replace(/[.'’]/g, "")
    .toLocaleLowerCase();
}

function hasHonorific(name: string) {
  return clean(name).split(/\s+/).some((token) => HONORIFIC_TOKEN.test(token));
}

type Occurrence = { name: string; fromHeader: boolean };

function splitNames(text: string): string[] {
  return text
    .split(/\n+|\s*[/|,;]\s*/)
    .map(stripEdge)
    .filter(Boolean);
}

function isPersonName(text: string): boolean {
  const value = stripEdge(text);
  if (!value || PLACEHOLDER.test(value)) return false;
  if (/\d/.test(value)) return false;
  if (isDay(value) || isTimeLabel(value) || CLASS_CODE.test(value) || isTeacherHeader(value)) return false;
  const tokens = value.split(/\s+/).filter(Boolean);
  if (tokens.length === 0 || tokens.length > 6) return false;
  if (tokens.some((token) => SUBJECT_WORD.test(token) || SUBJECT_PHRASE.test(token))) return false;

  let meaningful = 0;
  for (const token of tokens) {
    if (HONORIFIC_TOKEN.test(token)) continue;
    if (!isNameToken(token)) return false;
    meaningful += 1;
  }
  return meaningful > 0;
}

function namesFromTeacherRole(text: string): string[] {
  const names: string[] = [];
  for (const part of splitNames(text)) {
    if (isPersonName(part)) {
      names.push(stripEdge(part));
      continue;
    }
    const candidate = splitSubjectPrefix(part);
    if (candidate && isPersonName(candidate)) names.push(candidate);
  }
  return names;
}

function detectTeacherColumns(cells: TimetableCellLike[]): Set<number> {
  const columns = new Set<number>();
  const content = new Map<number, string[]>();

  for (const cell of cells) {
    if (isTeacherHeader(cell.text)) {
      columns.add(cell.column);
      continue;
    }
    if (isDay(cell.text) || isTimeLabel(cell.text) || PLACEHOLDER.test(stripEdge(cell.text))) continue;
    const list = content.get(cell.column) ?? [];
    list.push(cell.text);
    content.set(cell.column, list);
  }

  for (const [column, texts] of content) {
    let nameCells = 0;
    for (const text of texts) {
      if (splitNames(text).some(isPersonName)) nameCells += 1;
    }
    if (nameCells >= 2 && nameCells / texts.length >= 0.5) columns.add(column);
  }

  return columns;
}

function splitSubjectPrefix(part: string): string | null {
  const tokens = clean(part).split(/\s+/);
  const start = tokens.findIndex((token) => SUBJECT_WORD.test(token) || CONNECTOR.test(token));
  if (start === -1) return null;
  let end = start;
  while (
    end + 1 < tokens.length &&
    (SUBJECT_WORD.test(tokens[end + 1]) || CONNECTOR.test(tokens[end + 1]) || isTimeLabel(tokens[end + 1]))
  ) {
    end += 1;
  }
  const before = tokens.slice(0, start).join(" ");
  const after = tokens.slice(end + 1).join(" ");
  for (const candidate of [after, before]) {
    if (candidate.split(/\s+/).length < 2) continue;
    if (isPersonName(candidate)) return stripEdge(candidate);
  }
  return null;
}

function hasSubstantialNameToken(name: string): boolean {
  return clean(name)
    .split(/\s+/)
    .some((token) => !HONORIFIC_TOKEN.test(token) && token.replace(/[.'’]/g, "").length >= 4);
}

function namesFromCell(text: string): Occurrence[] {
  const parts = splitCell(text);
  const occurrences: Occurrence[] = [];

  for (const part of parts) {
    const name = honorificName(part);
    if (name) occurrences.push({ name, fromHeader: false });
  }
  if (occurrences.length > 0) return occurrences;

  const personParts = parts.filter((part) => isPersonName(part) && hasSubstantialNameToken(part));
  if (personParts.length > 0 && personParts.length < parts.length) {
    return personParts.map((part) => ({ name: stripEdge(part), fromHeader: false }));
  }

  for (const part of parts.filter((item) => SUBJECT_PHRASE.test(item))) {
    const name = splitSubjectPrefix(part);
    if (name) occurrences.push({ name, fromHeader: false });
  }
  return occurrences;
}

function mergeNames(occurrences: Occurrence[]): string[] {
  const groups = new Map<
    string,
    { titled: Map<string, string>; bare: Map<string, string> }
  >();

  for (const occurrence of occurrences) {
    const name = stripEdge(occurrence.name);
    if (!name) continue;
    const key = baseKey(name);
    if (!key) continue;
    const group = groups.get(key) ?? { titled: new Map(), bare: new Map() };
    const bucket = hasHonorific(name) ? group.titled : group.bare;
    const displayKey = clean(name).toLocaleLowerCase();
    if (!bucket.has(displayKey)) bucket.set(displayKey, name);
    groups.set(key, group);
  }

  const merged: string[] = [];
  for (const group of groups.values()) {
    if (group.titled.size === 1) {
      merged.push(Array.from(group.titled.values())[0]);
      continue;
    }
    if (group.titled.size > 1) {
      merged.push(...group.titled.values());
      continue;
    }
    merged.push(...group.bare.values());
  }

  return merged.sort((first, second) =>
    first.localeCompare(second, undefined, { numeric: true, sensitivity: "base" }),
  );
}

export function extractTeacherNames(table: TimetableLike): string[] {
  const cells = table.cells
    .map((cell) => ({ ...cell, text: normalizeCell(cell.text) }))
    .filter((cell) => cell.text.length > 0);

  const teacherColumns = detectTeacherColumns(cells);
  const teacherRows = new Set<number>();
  for (const cell of cells) {
    if (cell.column === 0 && cell.row > 0 && isTeacherHeader(cell.text)) teacherRows.add(cell.row);
  }

  const occurrences: Occurrence[] = [];
  for (const cell of cells) {
    if (isTeacherHeader(cell.text) || isDay(cell.text) || isTimeLabel(cell.text)) continue;
    if (IGNORED_LABEL.test(cell.text) || IGNORED_PREFIX.test(cell.text)) continue;

    if (teacherColumns.has(cell.column) || teacherRows.has(cell.row)) {
      for (const name of namesFromTeacherRole(cell.text)) {
        occurrences.push({ name, fromHeader: true });
      }
      continue;
    }

    occurrences.push(...namesFromCell(cell.text));
  }

  return mergeNames(occurrences);
}
