"""Conflicting keys: rows that share a key but differ elsewhere, so one record has two versions.

A key is a column whose name says it identifies rows (`customer_id`, `order_no`, `sku_code`) and whose
values are mostly distinct. Rows repeated exactly are the duplicates detector's; here the rest of the
row differs. Examples are `_row_id`s."""

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.fixtures import clean_frame
from sherlock.profile.infer import ID_NAME

MIN_UNIQUE = 0.8  # below this the column is a grouping, not a key


def detect(frame: Frame) -> list[Finding]:
    df = frame.df
    findings = []
    for name, col in frame.columns.items():
        if not ID_NAME.search(name) or len(col.text) < 2 or col.text.nunique() / len(col.text) < MIN_UNIQUE:
            continue
        repeated = col.text[col.text.duplicated(keep=False)]
        if repeated.empty:
            continue
        rest = df.loc[repeated.index].drop(columns=[name]).astype("string").fillna("\x00")
        versions = pd.Series(pd.util.hash_pandas_object(rest, index=False).to_numpy(), index=repeated.index)
        varied = versions.groupby(repeated).transform("nunique") > 1
        bad = varied[varied].index
        if len(bad):
            findings.append(Finding(
                "conflicting_keys", None, len(bad),
                f"Review rows that share a {name} but differ in other columns; quarantine the versions confirmed wrong.",
                [int(i) for i in bad[:5]], {"key": name, "keys": int(repeated[varied].nunique())},
            ))
    return findings


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen row given the key of a row that isn't chosen; its other values stay its own."""
    chosen = set(rows)
    others = [i for i in range(len(df)) if i not in chosen]
    return {(i, column): df.at[rng.choice(others), column] for i in rows}


SPEC = DetectorSpec(
    "conflicting_keys", "rows sharing a key", "Rows that share a value of a key column but differ in other columns.",
    group="records", weight=0.7, default_level="skews", scope="rows", detect=detect, depth=3,
    injectors={"shared_key": Injector(damage, share=0.03)}, clean_fixture=lambda: (clean_frame(), "record_id"),
)
