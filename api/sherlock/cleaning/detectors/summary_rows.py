"""Summary rows: totals and subtotals written into the data ("Total", "Grand total", "North subtotal"),
so a sum counts them twice. A row is one when a text value is a total label as a whole; a column where
such labels are common holds data, not summaries. Examples are `_row_id`s."""

import re

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.fixtures import clean_frame

LABEL = re.compile(r"^(?:(?:grand|sub)[\s-]?)?totals?\s*:?$|^.+\s(?:sub[\s-]?)?totals?\s*:?$|^totals?\s*[:-]\s*.+$", re.I)
MAX_SHARE = 0.2


def detect(frame: Frame) -> list[Finding]:
    hits = pd.Series(False, index=frame.df.index)
    where = []
    for name, col in frame.columns.items():
        if col.type not in ("category", "text") or col.text.empty:
            continue
        labelled = col.text.str.match(LABEL)
        if labelled.any() and labelled.mean() <= MAX_SHARE:
            hits.loc[labelled[labelled].index] = True
            where.append(name)
    if not hits.any():
        return []
    rows = hits[hits].index
    return [Finding(
        "summary_rows", None, len(rows),
        "Quarantine the total and subtotal rows, so sums and counts include each record once.",
        [int(i) for i in rows[:5]], {"columns": where},
    )]


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen row's label made a total ("Total", "Grand total" or "<value> subtotal")."""
    out = {}
    for i in rows:
        value = df.at[i, column]
        out[(i, column)] = rng.choice(["Total", "Grand total", f"{value} subtotal"])
    return out


SPEC = DetectorSpec(
    "summary_rows", "total rows", "Rows that hold a total or subtotal of other rows rather than a record.",
    group="records", weight=0.8, default_level="breaks", scope="rows", detect=detect, depth=3,
    injectors={"total": Injector(damage, share=0.03)}, clean_fixture=lambda: (clean_frame(), "category"),
)
