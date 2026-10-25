"""Binary check, encoding detection and UTF-8 transcoding, delimiter and header detection."""

import codecs
import csv
import io
import re
from pathlib import Path

import duckdb
from charset_normalizer import from_bytes, from_path

from sherlock.errors import ApiError
from sherlock.ingest.options import ENCODINGS
from sherlock.storage import sql_path

HEAD_BYTES = 64 * 1024
DETECT_BYTES = 1024 * 1024
CHUNK = 1024 * 1024
DELIMITERS = ",;\t|"

NOT_TEXT = "Couldn't read this as text. Is it a spreadsheet or a zip? Export it as CSV first."


def looks_utf16(head: bytes) -> str | None:
    """The UTF-16 variant if the head is UTF-16 (BOM, or NULs in every other byte), else None."""
    if head.startswith(codecs.BOM_UTF16_LE) or head.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"
    sample = head[:4096]
    if len(sample) < 4:
        return None
    even, odd = sample[0::2], sample[1::2]
    if odd.count(0) > 0.4 * len(odd) and even.count(0) < 0.05 * len(even):
        return "utf-16-le"
    if even.count(0) > 0.4 * len(even) and odd.count(0) < 0.05 * len(odd):
        return "utf-16-be"
    return None


def check_text(raw: Path) -> bytes:
    """Return the first 64 KB; refuse binary files (NUL bytes outside UTF-16)."""
    with raw.open("rb") as fh:
        head = fh.read(HEAD_BYTES)
    if b"\x00" in head and looks_utf16(head) is None:
        raise ApiError(422, "invalid", NOT_TEXT)
    return head


PREFERRED_ON_TIE = ("cp1252", "latin_1", "iso8859_15")


def pick_encoding(results) -> str:
    """charset-normalizer's best guess, but among equally plausible candidates (same chaos and
    coherence as the best) prefer Windows-1252, the commonest legacy CSV encoding and the one the
    import preview offers. Short files often tie between several single-byte codepages."""
    best = results.best()
    if best is None:
        return "cp1252"
    for match in results:
        tied = abs(match.chaos - best.chaos) < 1e-9 and abs(match.coherence - best.coherence) < 1e-9
        if tied and (match.encoding in PREFERRED_ON_TIE or set(match.could_be_from_charset) & set(PREFERRED_ON_TIE)):
            return "cp1252"
    return best.encoding


_CJK = re.compile(r"[⺀-鿿가-힯豈-﫿＀-￯]")
_IN_ASCII_WORD = re.compile(r"(?<=[A-Za-z])[⺀-鿿가-힯豈-﫿＀-￯](?=[A-Za-z])")


def is_single_byte(encoding: str) -> bool:
    probe = bytes(range(0x80, 0x100))
    return len(probe.decode(encoding, errors="replace")) == len(probe)


def cjk_inside_ascii_words(text: str) -> bool:
    """True when most CJK characters sit between two ASCII letters ("K荂e" for "Käse"): the mark
    of Western single-byte text decoded as a multi-byte CJK encoding. Real CJK text puts them
    next to other CJK characters, punctuation or delimiters."""
    total = len(_CJK.findall(text))
    return total > 0 and len(_IN_ASCII_WORD.findall(text)) >= 0.5 * total


def choose_encoding(sample: bytes, results) -> str:
    """`pick_encoding`, overruled to Windows-1252 when its multi-byte pick decodes into CJK
    characters wedged inside ASCII words (short Western files fool the detector into CJK)."""
    choice = pick_encoding(results)
    if not is_single_byte(choice):
        decoded = sample.decode(choice, errors="replace")
        if cjk_inside_ascii_words(decoded):
            return "cp1252"
    return choice


def detect_encoding(raw: Path, head: bytes) -> str:
    """BOM first, then strict UTF-8 on the first MB, then charset-normalizer."""
    if head.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    utf16 = looks_utf16(head)
    if utf16:
        return utf16
    with raw.open("rb") as fh:
        sample = fh.read(DETECT_BYTES)
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
        return "utf-8"
    except UnicodeDecodeError:
        pass
    return choose_encoding(sample, from_bytes(sample))


def codec_for(name: str) -> str:
    codec = ENCODINGS.get(name.lower(), name)
    try:
        codecs.lookup(codec)
    except LookupError:
        raise ApiError(422, "invalid", f"Unknown encoding {name!r}.") from None
    return codec


def transcode(raw: Path, out: Path, encoding: str) -> None:
    """Stream-decode the upload with `encoding` and write UTF-8 (no BOM) for DuckDB."""
    decoder = codecs.getincrementaldecoder(encoding)()
    with raw.open("rb") as src, out.open("w", encoding="utf-8", newline="") as dst:
        while chunk := src.read(CHUNK):
            dst.write(decoder.decode(chunk))
        dst.write(decoder.decode(b"", final=True))


def transcode_with_fallback(raw: Path, out: Path, encoding: str, user_chose: bool) -> str:
    """Transcode; if an auto-detected encoding fails later in the file, re-detect on the whole file."""
    try:
        transcode(raw, out, encoding)
        return encoding
    except UnicodeDecodeError:
        if user_chose:
            raise ApiError(
                422, "invalid",
                f"Couldn't read this file as {encoding}. Pick another encoding in the import preview.",
            ) from None
    with raw.open("rb") as fh:
        sample = fh.read(DETECT_BYTES)
    fallback = choose_encoding(sample, from_path(raw))
    try:
        transcode(raw, out, fallback)
    except UnicodeDecodeError:
        raise ApiError(422, "invalid", "Couldn't work out this file's encoding. Pick one in the import preview.") from None
    return fallback


def sniff(utf8: Path) -> dict:
    """DuckDB's sniffer, checked against csv.Sniffer; on disagreement DuckDB wins (TRD §7.1)."""
    conn = duckdb.connect(":memory:")
    try:
        delimiter, skip_rows, has_header = conn.execute(
            f"SELECT Delimiter, SkipRows, HasHeader FROM sniff_csv({sql_path(utf8)})"
        ).fetchone()
    except duckdb.Error:
        delimiter, skip_rows, has_header = None, 0, True
    finally:
        conn.close()
    with utf8.open(encoding="utf-8", newline="") as fh:
        text = fh.read(HEAD_BYTES)
    try:
        python_delimiter = csv.Sniffer().sniff(text, delimiters=DELIMITERS).delimiter
    except csv.Error:
        python_delimiter = None
    chosen = delimiter or python_delimiter or ","
    chosen = present_delimiter(text, int(skip_rows or 0), chosen)
    return {
        "delimiter": chosen,
        "skip_rows": int(skip_rows or 0),
        "has_header": bool(has_header),
        "agreed": delimiter == python_delimiter,
    }


SAMPLE_LINES = 50


def present_delimiter(text: str, skip: int, chosen: str) -> str:
    """Overrule a delimiter that barely occurs in the lines when another occurs on nearly all of them.
    A few ragged rows (one with an extra field, or some short ones) make DuckDB's sniffer guess `|`,
    and the file would import as one column named `a,b,c` (Day 2 review)."""
    lines = [ln for ln in text.splitlines()[skip:] if ln.strip()][:SAMPLE_LINES]
    if len(lines) < 2:
        return chosen
    share = {d: sum(d in ln for ln in lines) / len(lines) for d in DELIMITERS}
    if share[chosen] >= 0.5:
        return chosen
    best = max(DELIMITERS, key=lambda d: share[d])
    return best if share[best] >= 0.9 else chosen


def max_fields(utf8: Path, delimiter: str, skip: int) -> int:
    """The most fields any record has after `skip` lines (quote-aware; blank lines count as none)."""
    with utf8.open(encoding="utf-8", newline="") as fh:
        for _ in range(skip):
            if not fh.readline():
                return 0
        return max((len(r) for r in csv.reader(fh, delimiter=delimiter)), default=0)


def header_names(utf8: Path, delimiter: str, skip: int) -> list[str]:
    """The raw header record after `skip` lines, parsed with the chosen delimiter."""
    with utf8.open(encoding="utf-8", newline="") as fh:
        for _ in range(skip):
            if not fh.readline():
                return []
        line = fh.readline()
    if not line.strip():
        return []
    return next(csv.reader(io.StringIO(line), delimiter=delimiter), [])
