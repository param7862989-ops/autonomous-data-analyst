/**
 * Split a statement into text and figures, mirroring the backend grounding check
 * (backend/app/agent/grounding.py), so verified figures can be highlighted and unverified ones
 * flagged. Dates, quarter labels, result ids, years, small counts and digits inside names from
 * the results ("Monitor 27in") are not figures.
 */

const SKIP =
  /\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b|\b\d{4}-(?:\d{2}|Q[1-4]|W\d{2})\b|\bQ[1-4]\b|\b[rc]\d+\b/gi;
const NUMBER =
  /(?<![\w.])([-−])?([$€£₹])?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:\s?(%|percent\b|k\b|K\b|M\b|B\b|bn\b|million\b|billion\b|thousand\b))?/g;

export type Segment = { text: string; figure: "verified" | "unverified" | null };

function normalize(token: string): string {
  return token.trim().replace(/^[-−]/, "");
}

/** Text cells that are names containing digits: they start with a letter, as in the backend. */
export function namesWithDigits(results: { table: { rows: unknown[][] } }[]): string[] {
  const names = new Set<string>();
  for (const value of results.flatMap((result) => result.table.rows.flat())) {
    if (typeof value === "string" && /^\p{L}/u.test(value) && /\d/.test(value)) names.add(value);
  }
  return [...names];
}

export function splitFigures(text: string, unverified: string[], names: string[] = []): Segment[] {
  const skipped: [number, number][] = [];
  for (const name of names) {
    for (let at = text.indexOf(name); at !== -1; at = text.indexOf(name, at + 1)) {
      const around = `${text[at - 1] ?? " "}${text[at + name.length] ?? " "}`;
      if (!/[\p{L}\p{N}_]/u.test(around)) skipped.push([at, at + name.length]);
    }
  }
  for (const match of text.matchAll(SKIP)) {
    skipped.push([match.index, match.index + match[0].length]);
  }
  const flagged = new Set(unverified.map(normalize));
  const segments: Segment[] = [];
  let last = 0;
  for (const match of text.matchAll(NUMBER)) {
    const start = match.index;
    const end = start + match[0].length;
    if (skipped.some(([s, e]) => start < e && end > s)) continue;
    const [, , currency, integer, decimals, suffix] = match;
    const value = Number(integer.replace(/,/g, "") + (decimals ?? ""));
    const plain = !decimals && !suffix && !currency;
    if (plain && (value <= 10 || (value >= 1900 && value <= 2100 && !integer.includes(",")))) {
      continue;
    }
    if (start > last) segments.push({ text: text.slice(last, start), figure: null });
    segments.push({
      text: match[0],
      figure: flagged.has(normalize(match[0])) ? "unverified" : "verified",
    });
    last = end;
  }
  if (last < text.length) segments.push({ text: text.slice(last), figure: null });
  return segments;
}
