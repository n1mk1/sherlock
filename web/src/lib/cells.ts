// Cell values in the CSV grid: display text, alignment, and whether typed text fits a column's type
// (App Flow §8.2: an invalid value is saved but flagged, so the grid only marks it).
const INT = /^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|UBIGINT)$/;
const FLOAT = /^(FLOAT|DOUBLE|REAL|DECIMAL.*)$/;

export const isNumericType = (t: string) => INT.test(t) || FLOAT.test(t);

export function fitsType(type: string, text: string): boolean {
  const v = text.trim();
  if (v === "") return true; // a blank cell is a missing value
  if (INT.test(type)) return /^[+-]?\d+$/.test(v);
  if (FLOAT.test(type)) return /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(v);
  if (type === "BOOLEAN") return /^(true|false|t|f|yes|no|y|n|1|0)$/i.test(v);
  if (type === "DATE" || type.startsWith("TIMESTAMP")) return !Number.isNaN(Date.parse(v));
  return true;
}

export function displayValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(12)));
  return String(v);
}

export function typeLabel(type: string): string {
  if (INT.test(type)) return "int";
  if (FLOAT.test(type)) return "float";
  if (type === "BOOLEAN") return "bool";
  if (type === "DATE") return "date";
  if (type.startsWith("TIMESTAMP")) return "datetime";
  return "text";
}
