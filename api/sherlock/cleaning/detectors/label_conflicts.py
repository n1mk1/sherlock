"""Conflicting outcomes: rows identical in every column, IDs and text included, except the outcome, so
one record is labelled two ways and at most one label is right. Rows that only share some features are
different records and may differ honestly, so every other column must match (a missing value matches a
missing value). Examples are `_row_id`s."""

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.fixtures import clean_frame


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for target in frame.target_candidates:
        rest = [n for n in frame.columns if n != target]
        if not rest:
            continue
        known = frame.df[frame.df[target].notna()]
        df = known.astype("string").fillna("\x00")
        twins = df[df.duplicated(subset=rest, keep=False)]
        if twins.empty:
            continue
        labels = twins.groupby(rest)[target].transform("nunique")
        bad = labels[labels > 1].index
        if len(bad):
            findings.append(Finding(
                "label_conflicts", None, len(bad),
                f"Review rows that match in every other column but disagree on {target}; quarantine the ones "
                "confirmed wrong.",
                [int(i) for i in bad[:5]], {"target": target},
            ))
    return findings


def clean_fixture():
    """The clean frame, whose yes/no column is the outcome; no two rows match elsewhere."""
    return clean_frame(), "flag"


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen row made a copy of a row that isn't chosen, except for the outcome, which is flipped."""
    chosen = set(rows)
    others = [i for i in range(len(df)) if i not in chosen]
    out = {}
    for i in rows:
        source = rng.choice(others)
        for c in df.columns:
            value = df.at[source, c]
            if c == column:
                value = "no" if value == "yes" else "yes"
            if df.at[i, c] != value:
                out[(i, c)] = value
    return out


SPEC = DetectorSpec(
    "label_conflicts", "conflicting outcomes",
    "Rows identical in every column except the outcome.",
    group="records", weight=0.6, default_level="check", scope="rows", detect=detect, depth=5,
    injectors={"flipped_twin": Injector(damage, share=0.03)}, clean_fixture=clean_fixture,
)
