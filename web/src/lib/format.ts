// Number formatting for widgets and tables, the same rules as the server's chat chips
// (sherlock/agent/compose.py): rates and shares between 0 and 1 as percentages, integers with
// separators, other numbers to two decimals (none past 1,000, three significant figures under 1).
const PCT_NAME = /(rate|share|pct|percent|ratio|proportion|fraction)/i;

export function isPctColumn(name: string, values: unknown[]) {
  return PCT_NAME.test(name) && values.every((v) => v == null || (typeof v === "number" && v >= 0 && v <= 1));
}

export function formatNumber(v: number, pct = false) {
  if (!Number.isFinite(v)) return String(v);
  if (pct) return `${(v * 100).toFixed(1)}%`;
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  const a = Math.abs(v);
  if (a >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (a >= 1) return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return Number(v.toPrecision(3)).toString();
}

export function formatCell(v: unknown, pct = false): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return formatNumber(v, pct);
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

/** A period from a date-truncated query ("2024-03-01") as a short label. */
export function formatPeriod(v: unknown) {
  const d = new Date(String(v));
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}
