"""Import options (TRD §4.2 `options`; App Flow §3.2). Missing values are auto-detected."""

from pydantic import BaseModel, ConfigDict, Field

ENCODINGS = {
    # App Flow §3.2 dropdown → Python codec
    "utf-8": "utf-8",
    "utf-8-sig": "utf-8-sig",
    "latin-1": "latin-1",
    "windows-1252": "cp1252",
    "cp1252": "cp1252",
    "utf-16": "utf-16",
}


class ImportOptions(BaseModel):
    """What the user chose in the import preview; `None` means auto-detect.

    `header_row` is the 1-based line (after `skip_rows`) holding the column names, or 0 for no
    header (columns become `col_1…`). Lines before it are skipped too.
    """

    model_config = ConfigDict(extra="forbid")

    delimiter: str | None = Field(default=None, min_length=1, max_length=1)
    encoding: str | None = None
    header_row: int | None = Field(default=None, ge=0, le=100)
    skip_rows: int | None = Field(default=None, ge=0, le=1000)


class ResolvedOptions(BaseModel):
    """The options actually used, stored as `datasets.import_options_json`."""

    delimiter: str
    encoding: str
    header_row: int
    skip_rows: int
    # Set only for ragged files (stored without nulls), so the notebook's load cell reads them alike:
    width: int | None = None          # read with this many explicit text columns (the sniffer failed)
    header_fields: int | None = None  # rows with values past this many fields were quarantined
