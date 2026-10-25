// Client-side import preview (App Flow §3.2): parse the first part of the local file with Papa Parse
// so the user can check delimiter, encoding and header before anything is uploaded. The server
// re-detects everything; only settings the user changed are sent as import options.
import Papa from "papaparse";

export const MAX_UPLOAD_MB = 50;
export const SAMPLE_BYTES = 256 * 1024;
export const PREVIEW_ROWS = 20;

export const ENCODINGS = [
  { value: "utf-8", label: "UTF-8" },
  { value: "utf-8-sig", label: "UTF-8 with BOM" },
  { value: "latin-1", label: "Latin-1" },
  { value: "windows-1252", label: "Windows-1252" },
  { value: "utf-16", label: "UTF-16" },
] as const;

export const DELIMITERS = [
  { value: ",", label: "Comma" },
  { value: "\t", label: "Tab" },
  { value: ";", label: "Semicolon" },
  { value: "|", label: "Pipe" },
] as const;

export interface PreviewSettings {
  delimiter: string; // "" = auto
  encoding: string;
  headerRow: number; // 1-based line after skipRows holding the names; 0 = no header
  skipRows: number;
}

export interface Preview {
  columns: string[];
  rows: string[][];
  delimiter: string;
  estimatedRows: number;
  notes: string[];
  error: string | null;
}

export function sizeError(bytes: number): string | null {
  if (bytes === 0) return "This file has no data rows.";
  const mb = bytes / (1024 * 1024);
  if (mb <= MAX_UPLOAD_MB) return null;
  return `This file is ${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB. The limit is ${MAX_UPLOAD_MB} MB.`;
}

function hasUtf16Bom(b: Uint8Array) {
  return b.length >= 2 && ((b[0] === 0xff && b[1] === 0xfe) || (b[0] === 0xfe && b[1] === 0xff));
}

/** NUL bytes in the first 64 KB outside UTF-16 mean it isn't a delimited text file (App Flow §3.2). */
export function looksBinary(b: Uint8Array): boolean {
  if (hasUtf16Bom(b)) return false;
  const head = b.subarray(0, 64 * 1024);
  let nuls = 0;
  for (const byte of head) if (byte === 0) nuls++;
  if (!nuls) return false;
  // UTF-16 without a BOM: about every other byte is NUL.
  return nuls < head.length * 0.3;
}

export function detectEncoding(b: Uint8Array): string {
  if (b.length >= 3 && b[0] === 0xef && b[1] === 0xbb && b[2] === 0xbf) return "utf-8-sig";
  if (hasUtf16Bom(b)) return "utf-16";
  try {
    // A sample can end mid-character; drop up to three trailing bytes before the strict check.
    new TextDecoder("utf-8", { fatal: true }).decode(trimPartial(b));
    return "utf-8";
  } catch {
    return "windows-1252";
  }
}

function trimPartial(b: Uint8Array): Uint8Array {
  let end = b.length;
  for (let i = 1; i <= 3 && end - i >= 0; i++) {
    const byte = b[end - i];
    if ((byte & 0xc0) === 0xc0) return b.subarray(0, end - i); // a lead byte cut short
    if ((byte & 0x80) === 0) break;
  }
  return b;
}

export function decode(b: Uint8Array, encoding: string): string {
  const label =
    encoding === "utf-8-sig" ? "utf-8"
    : encoding === "latin-1" ? "iso-8859-1"
    : encoding === "utf-16" ? (b[0] === 0xfe ? "utf-16be" : "utf-16le")
    : encoding;
  try {
    return new TextDecoder(label).decode(b);
  } catch {
    return new TextDecoder("utf-8").decode(b);
  }
}

/** Column names as the server makes them (TRD §7.1): trimmed, blanks named col_N, duplicates suffixed. */
export function columnNames(header: string[] | null, width: number): { names: string[]; renamed: boolean } {
  const names: string[] = [];
  const seen = new Set<string>(["_row_id", "_quarantine_reason"]);
  let renamed = false;
  for (let i = 0; i < width; i++) {
    let name = (header?.[i] ?? "").trim() || `col_${i + 1}`;
    if (seen.has(name)) {
      let n = 2;
      while (seen.has(`${name}_${n}`)) n++;
      name = `${name}_${n}`;
      renamed = true;
    }
    seen.add(name);
    names.push(name);
  }
  return { names, renamed };
}

export function buildPreview(text: string, s: PreviewSettings, fileBytes: number, sampleBytes: number): Preview {
  const truncated = fileBytes > sampleBytes;
  // Skipped lines go before parsing, so a preamble ("report v2") doesn't confuse delimiter detection.
  const body = text.split(/\r?\n/).slice(s.skipRows).join("\n");
  const parsed = Papa.parse<string[]>(body, { delimiter: s.delimiter, skipEmptyLines: "greedy" });
  let afterSkip = parsed.data;
  if (truncated && afterSkip.length > 1) afterSkip = afterSkip.slice(0, -1); // the sample can end mid-row
  const lines = afterSkip;
  const delimiter = s.delimiter || parsed.meta.delimiter || ",";
  const header = s.headerRow > 0 ? afterSkip[s.headerRow - 1] ?? null : null;
  const data = afterSkip.slice(Math.max(s.headerRow, 0));
  const width = Math.max(header?.length ?? 0, ...data.slice(0, 200).map((r) => r.length), 0);
  const { names, renamed } = columnNames(header, width);
  const notes: string[] = [];
  if (renamed) notes.push("Some column names repeat, so the later ones get a suffix (name_2).");
  const perRow = lines.length ? (truncated ? sampleBytes : fileBytes) / lines.length : 0;
  const estimatedRows = truncated && perRow ? Math.round(fileBytes / perRow) - s.skipRows - (s.headerRow > 0 ? 1 : 0) : data.length;
  let error: string | null = null;
  if (!width || !data.length) error = "This file has no data rows.";
  return { columns: names, rows: data.slice(0, PREVIEW_ROWS), delimiter, estimatedRows: Math.max(estimatedRows, data.length), notes, error };
}

/** Only the settings the user changed from what was detected go to the server. */
export function changedOptions(detected: PreviewSettings, chosen: PreviewSettings) {
  const out: { delimiter?: string; encoding?: string; header_row?: number; skip_rows?: number } = {};
  if (chosen.delimiter && chosen.delimiter !== detected.delimiter) out.delimiter = chosen.delimiter;
  if (chosen.encoding !== detected.encoding) out.encoding = chosen.encoding;
  if (chosen.headerRow !== detected.headerRow) out.header_row = chosen.headerRow;
  if (chosen.skipRows !== detected.skipRows) out.skip_rows = chosen.skipRows;
  return out;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
