"""TRD §7.1 steps 1–2: store the raw upload, check it, transcode, read it all-VARCHAR with DuckDB,
add `_row_id` and `_quarantine_reason`, write `versions/v1.parquet` and record the dataset.

The raw upload is kept unmodified as `raw.csv` (Rule 3); the UTF-8 copy is temporary.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import duckdb

from sherlock.config import Settings
from sherlock.db import datasets as datasets_repo
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.ingest import sniff
from sherlock.ingest.options import ImportOptions, ResolvedOptions
from sherlock.storage import (
    dataset_dir,
    folder_bytes,
    new_duckdb,
    raw_path,
    remove_folder,
    sql_path,
    version_path,
)

MB = 1024 * 1024
RESERVED_COLUMNS = ("_row_id", "_quarantine_reason")
NO_DATA = "This file has no data rows."


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def column_names(header: list[str], count: int) -> list[str]:
    """User column names (App Flow §3.2): trimmed; blanks → `col_N`; duplicates and the two
    system names get `_2`, `_3`…; columns beyond the header (or no header) → `col_N`."""
    names: list[str] = []
    taken = set(RESERVED_COLUMNS)
    for index in range(count):
        base = header[index].strip() if index < len(header) else ""
        base = base or f"col_{index + 1}"
        name, n = base, 1
        while name in taken:
            n += 1
            name = f"{base}_{n}"
        taken.add(name)
        names.append(name)
    return names


def _save_upload(src: BinaryIO, dest: Path, limit_mb: int) -> int:
    total = 0
    with dest.open("wb") as out:
        while chunk := src.read(MB):
            total += len(chunk)
            if total > limit_mb * MB:
                raise ApiError(413, "too_large", f"This file is over {limit_mb} MB. The limit is {limit_mb} MB.")
            out.write(chunk)
    return total


def _read_to_parquet(
    settings: Settings, utf8: Path, folder: Path, resolved: ResolvedOptions
) -> tuple[int, list[str]]:
    skip = resolved.skip_rows + max(resolved.header_row - 1, 0)
    has_header = resolved.header_row > 0
    tmp = folder / ".tmp"
    tmp.mkdir(exist_ok=True)
    conn = new_duckdb(settings, temp_dir=tmp)
    try:
        conn.execute(
            "CREATE VIEW src AS SELECT * FROM read_csv("
            f"{sql_path(utf8)}, delim={_quote_str(resolved.delimiter)}, "
            f"header={'true' if has_header else 'false'}, skip={skip}, "
            "all_varchar=true, null_padding=true)"
        )
        source_columns = [row[0] for row in conn.execute("DESCRIBE src").fetchall()]
        if not source_columns:
            raise ApiError(422, "invalid", NO_DATA)
        if len(source_columns) > settings.max_columns:
            raise ApiError(413, "too_large", f"This file has {len(source_columns):,} columns. The limit is {settings.max_columns:,}.")
        header = sniff.header_names(utf8, resolved.delimiter, skip) if has_header else []
        names = column_names(header, len(source_columns))
        select = ", ".join(f"src.{_quote_ident(s)} AS {_quote_ident(n)}" for s, n in zip(source_columns, names))
        conn.execute(
            "CREATE TABLE t AS SELECT row_number() OVER ()::BIGINT AS _row_id, "
            f"NULL::VARCHAR AS _quarantine_reason, {select} FROM src"
        )
        rows = conn.execute("SELECT count(*) FROM t").fetchone()[0]
        any_value = " OR ".join(f"{_quote_ident(n)} IS NOT NULL" for n in names)
        if rows == 0 or conn.execute(f"SELECT count(*) FROM t WHERE {any_value}").fetchone()[0] == 0:
            raise ApiError(422, "invalid", NO_DATA)  # no rows, or only empty ones
        if rows > settings.max_rows:
            raise ApiError(413, "too_large", f"This file has {rows:,} rows. The limit is {settings.max_rows:,}.")
        parquet = version_path(folder, 1)
        parquet.parent.mkdir(parents=True, exist_ok=True)
        conn.execute(f"COPY t TO {sql_path(parquet)} (FORMAT PARQUET, COMPRESSION ZSTD)")
        return rows, names
    except duckdb.Error as exc:
        first = str(exc).strip().splitlines()[0][:300]
        raise ApiError(422, "invalid", f"Couldn't read this file as CSV: {first}") from None
    finally:
        conn.close()
        remove_folder(tmp)


def import_csv(
    settings: Settings,
    db: sqlite3.Connection,
    user_id: str,
    src: BinaryIO,
    filename: str,
    options: ImportOptions,
    *,
    name: str | None = None,
    is_sample: bool = False,
) -> sqlite3.Row:
    """Create a dataset from an uploaded file. Nothing is recorded unless every check passes."""
    dataset_id = new_id("ds")
    folder = dataset_dir(settings, user_id, dataset_id)
    folder.mkdir(parents=True)
    try:
        raw = raw_path(folder)
        size = _save_upload(src, raw, settings.max_upload_mb)
        if size == 0:
            raise ApiError(422, "invalid", NO_DATA)
        head = sniff.check_text(raw)

        user_chose = options.encoding is not None
        encoding = sniff.codec_for(options.encoding) if user_chose else sniff.detect_encoding(raw, head)
        utf8 = folder / ".ingest.utf8.csv"
        encoding = sniff.transcode_with_fallback(raw, utf8, encoding, user_chose)

        sniffed = sniff.sniff(utf8)
        resolved = ResolvedOptions(
            delimiter=options.delimiter or sniffed["delimiter"],
            encoding=encoding,
            header_row=options.header_row if options.header_row is not None else (1 if sniffed["has_header"] else 0),
            skip_rows=options.skip_rows if options.skip_rows is not None else sniffed["skip_rows"],
        )
        rows, names = _read_to_parquet(settings, utf8, folder, resolved)
        utf8.unlink(missing_ok=True)

        used = folder_bytes(folder)
        stored = db.execute("SELECT storage_bytes FROM users WHERE id = ?", (user_id,)).fetchone()[0]
        if stored + used > settings.user_storage_mb * MB:
            raise ApiError(
                413, "too_large",
                f"Your CSVs would use {(stored + used) / MB:.0f} MB. The limit is {settings.user_storage_mb} MB; delete a CSV first.",
            )

        now = now_iso()
        expires = (datetime.now(UTC) + timedelta(days=settings.dataset_ttl_days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        columns = [{"name": "_row_id", "type": "BIGINT"}, {"name": "_quarantine_reason", "type": "VARCHAR"}]
        columns += [{"name": n, "type": "VARCHAR"} for n in names]
        db.execute("BEGIN IMMEDIATE")
        try:
            datasets_repo.insert(
                db,
                id=dataset_id,
                user_id=user_id,
                name=name or Path(filename).name or "upload.csv",
                original_filename=Path(filename).name or "upload.csv",
                is_sample=is_sample,
                status="profiling",
                current_version=1,
                row_count=rows,
                column_count=len(names),
                import_options_json=resolved.model_dump_json(),
                expires_at=expires,
                folder_bytes=used,
                next_row_id=rows + 1,
                created_at=now,
            )
            db.execute(
                "INSERT INTO versions (dataset_id, version, parquet_path, row_count, column_count, "
                "columns_json, step_id, effective_step_ids_json, created_at) "
                "VALUES (?, 1, ?, ?, ?, ?, NULL, '[]', ?)",
                (dataset_id, "versions/v1.parquet", rows, len(names), json.dumps(columns), now),
            )
            db.execute("UPDATE users SET storage_bytes = storage_bytes + ? WHERE id = ?", (used, user_id))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        return datasets_repo.get(db, user_id, dataset_id)
    except BaseException:
        remove_folder(folder)
        raise
