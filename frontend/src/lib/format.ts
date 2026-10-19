const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export function formatInteger(value: number): string {
  return integer.format(value);
}

/** Numbers for tables and summaries: up to 2 decimals, compact above a million. */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1_000_000) return compact.format(value);
  const digits = Number.isInteger(value) ? 0 : Math.abs(value) < 1 ? 4 : 2;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

export function formatPercent(share: number, digits = 1): string {
  if (share > 0 && share < 0.001) return "<0.1%";
  return `${(share * 100).toFixed(digits).replace(/\.0+$/, "")}%`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}

const dateTime = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const dateOnly = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

/** A timestamp from the API (UTC, ISO 8601) in the viewer's local time. */
export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso));
}

/** A date value from the data itself. Shown in UTC, because that is how it is stored. */
export function formatDataDate(iso: string): string {
  return dateOnly.format(new Date(iso.endsWith("Z") ? iso : `${iso}Z`));
}

/** Render one cell from a data preview or result table. */
export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T00:00:00$/.test(value)) {
    return value.slice(0, 10);
  }
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value)) {
    return value.replace("T", " ");
  }
  return String(value);
}
