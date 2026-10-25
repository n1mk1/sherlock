import { describe, expect, it } from "vitest";
import {
  buildPreview, changedOptions, columnNames, decode, detectEncoding, looksBinary, sizeError,
} from "./importPreview";

const enc = (s: string) => new TextEncoder().encode(s);

describe("import preview", () => {
  it("detects encodings", () => {
    expect(detectEncoding(enc("a,b\n1,2\n"))).toBe("utf-8");
    expect(detectEncoding(new Uint8Array([0xef, 0xbb, 0xbf, 0x61]))).toBe("utf-8-sig");
    expect(detectEncoding(new Uint8Array([0xff, 0xfe, 0x61, 0x00]))).toBe("utf-16");
    expect(detectEncoding(new Uint8Array([0x63, 0x61, 0x66, 0xe9, 0x0a]))).toBe("windows-1252"); // café in Latin-1
    expect(decode(new Uint8Array([0x63, 0x61, 0x66, 0xe9]), "windows-1252")).toBe("café");
    // A UTF-8 sample cut mid-character is still UTF-8.
    expect(detectEncoding(enc("café").subarray(0, 4))).toBe("utf-8");
  });

  it("spots binary files and size limits", () => {
    expect(looksBinary(new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00, 0x14, 0x61, 0x62, 0x63, 0x64]))).toBe(true);
    expect(looksBinary(enc("plain,text\n"))).toBe(false);
    expect(sizeError(0)).toBe("This file has no data rows.");
    expect(sizeError(73 * 1024 * 1024)).toBe("This file is 73 MB. The limit is 50 MB.");
    expect(sizeError(10)).toBeNull();
  });

  it("parses with header row and skip rows", () => {
    const text = "report v2\nname;age\nAnn;30\nBob;41\n";
    const auto = buildPreview(text, { delimiter: "", encoding: "utf-8", headerRow: 1, skipRows: 1 }, text.length, text.length);
    expect(auto.delimiter).toBe(";");
    expect(auto.columns).toEqual(["name", "age"]);
    expect(auto.rows).toEqual([["Ann", "30"], ["Bob", "41"]]);
    const noHeader = buildPreview(text, { delimiter: ";", encoding: "utf-8", headerRow: 0, skipRows: 2 }, text.length, text.length);
    expect(noHeader.columns).toEqual(["col_1", "col_2"]);
    const empty = buildPreview("a,b\n", { delimiter: "", encoding: "utf-8", headerRow: 1, skipRows: 0 }, 4, 4);
    expect(empty.error).toBe("This file has no data rows.");
  });

  it("names columns like the server", () => {
    expect(columnNames(["name", " ", "name", "_row_id"], 5)).toEqual({
      names: ["name", "col_2", "name_2", "_row_id_2", "col_5"], renamed: true,
    });
  });

  it("sends only the settings the user changed", () => {
    const detected = { delimiter: ",", encoding: "utf-8", headerRow: 1, skipRows: 0 };
    expect(changedOptions(detected, detected)).toEqual({});
    expect(changedOptions(detected, { ...detected, delimiter: ";", skipRows: 2 })).toEqual({ delimiter: ";", skip_rows: 2 });
  });
});
