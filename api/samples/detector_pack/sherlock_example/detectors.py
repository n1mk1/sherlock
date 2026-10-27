"""An example detector pack (TRD §7.1 step 4, `api/sherlock/cleaning/detectors/README.md`): one detector,
`single_value`, that finds a column holding the same value on every row, which no chart or model can
use. A pack exports `SPECS`, a sequence of `DetectorSpec`, through the entry point group
`sherlock.detectors` in its own `pyproject.toml`."""

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.fixtures import clean_frame

MIN_ROWS = 20


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        if frame.rows < MIN_ROWS or col.missing or col.text.empty:
            continue
        if col.text.nunique() == 1:
            findings.append(Finding("single_value", name, len(col.text),
                                    "Keep this column out of charts and models; every row holds the same value.",
                                    [col.text.iloc[0]]))
    return findings


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Every row of the column made the first chosen row's value."""
    value = df.at[rows[0], column]
    return {(i, column): value for i in range(len(df)) if df.at[i, column] != value}


SPECS = (
    DetectorSpec(
        "single_value", "the same value on every row", "Columns that hold one value on every row.",
        group="other", weight=0.3, default_level="cosmetic", scope="column", detect=detect,
        injectors={"constant": Injector(damage, share=0.01)}, clean_fixture=lambda: (clean_frame(), "category"),
    ),
)
