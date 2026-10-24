"""Fetch the Titanic sample (OpenML 40945) and write api/samples/titanic3.csv.

The file is bundled in the repo (OpenML lists the dataset's licence as "Public"; source:
Frank E. Harrell Jr. and Thomas Cason, Vanderbilt Biostatistics). This script rebuilds it
reproducibly: it downloads the ARFF, checks OpenML's MD5, keeps every value's original
text, and writes ARFF's `?` missing marker as an empty cell, as in the original titanic3.csv.

    uv run --no-project python scripts/fetch_sample.py
"""

import csv
import hashlib
import io
import sys
import urllib.request
from pathlib import Path

URL = "https://openml.org/data/v1/download/16826755/Titanic.arff"
MD5 = "60ac7205eee0ba5045c90b3bba95b1c4"
OUT = Path(__file__).resolve().parents[1] / "api" / "samples" / "titanic3.csv"
EXPECTED_ROWS = 1309


def parse_arff(text: str) -> tuple[list[str], list[list[str]]]:
    header, _, data = text.partition("@data")
    columns = []
    for line in header.splitlines():
        if line.lower().startswith("@attribute"):
            name = line.split(None, 2)[1]
            columns.append(name.strip("'\""))
    rows = []
    for row in csv.reader(io.StringIO(data.strip()), quotechar='"', skipinitialspace=True):
        if row:
            rows.append(["" if value == "?" else value for value in row])
    return columns, rows


def main() -> int:
    raw = urllib.request.urlopen(URL, timeout=60).read()
    digest = hashlib.md5(raw).hexdigest()
    if digest != MD5:
        print(f"MD5 mismatch: got {digest}, expected {MD5}", file=sys.stderr)
        return 1
    columns, rows = parse_arff(raw.decode("utf-8"))
    if len(rows) != EXPECTED_ROWS or any(len(r) != len(columns) for r in rows):
        print(f"unexpected shape: {len(rows)} rows", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} rows, {len(columns)} columns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
