"""Totals that don't add up: a number column named for a total (`total`, `sum`, `subtotal`, `amount`,
`net`, `gross`) that equals the sum of two or three other number columns, or the product of two
(`quantity × price`), in almost every row, and doesn't in a few. The rule is read from the data, never
assumed from the names alone."""

import re
from itertools import combinations

import numpy as np
import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector, examples
from sherlock.cleaning.detectors.fixtures import with_column
from sherlock.profile.infer import NUMERIC_TYPES

NAME = re.compile(r"(^|[_\s])(total|sum|subtotal|amount|net|gross)($|[_\s])", re.I)
AGREEMENT = 0.95
MIN_ROWS = 20
MAX_PARTS = 8
RTOL, ATOL = 1e-4, 0.011  # a total rounded to the cent still agrees


def _rules(parts: list[str]):
    for pair in combinations(parts, 2):
        yield "sum", pair
        yield "product", pair
    for triple in combinations(parts, 3):
        yield "sum", triple


def detect(frame: Frame) -> list[Finding]:
    numbers = {n: c.numeric for n, c in frame.columns.items()
               if c.type in NUMERIC_TYPES and c.role not in ("id", "empty") and c.numeric is not None}
    findings = []
    for name, total in numbers.items():
        if not NAME.search(name):
            continue
        parts = [n for n in numbers if n != name][:MAX_PARTS]
        best = None
        for op, cols in _rules(parts):
            values = [numbers[c] for c in cols]
            known = total.notna()
            for v in values:
                known &= v.notna()
            if known.sum() < MIN_ROWS:
                continue
            got = values[0][known].copy()
            for v in values[1:]:
                got = got + v[known] if op == "sum" else got * v[known]
            agrees = pd.Series(np.isclose(got, total[known], rtol=RTOL, atol=ATOL), index=got.index)
            if agrees.mean() >= AGREEMENT and (best is None or agrees.mean() > best[0]):
                best = (agrees.mean(), op, cols, agrees)
        if best is None or best[0] == 1:
            continue
        agreement, op, cols, agrees = best
        off = agrees[~agrees].index
        rule = (" + " if op == "sum" else " × ").join(cols)
        findings.append(Finding(
            "arithmetic_mismatch", name, len(off),
            f"{name} equals {rule} in almost every row; review the rows where it doesn't.",
            examples([f"{_show(total[i])} ≠ {_show(_apply(numbers, op, cols, i))}" for i in off]),
            {"parts": list(cols), "op": op, "agreement": round(float(agreement), 4)},
        ))
    return findings


def _apply(numbers, op: str, cols, i):
    out = numbers[cols[0]][i]
    for c in cols[1:]:
        out = out + numbers[c][i] if op == "sum" else out * numbers[c][i]
    return out


def _show(v) -> str:
    return f"{float(v):.10g}"


def clean_fixture():
    """A quantity, a unit price and a line total that is their product."""
    df = with_column("qty", [str(1 + i % 7) for i in range(200)])
    df.insert(len(df.columns) - 1, "unit_price", [f"{2.5 + (i * 37 % 40) / 4:.2f}" for i in range(200)])
    df.insert(len(df.columns) - 1, "line_total",
              [f"{int(q) * float(p):.2f}" for q, p in zip(df["qty"], df["unit_price"])])
    return df, "line_total"


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen total made a tenth larger, plus one."""
    return {(i, column): f"{float(df.at[i, column]) * 1.1 + 1:.2f}" for i in rows}


SPEC = DetectorSpec(
    "arithmetic_mismatch", "totals that don't add up",
    "Rows where a total column doesn't equal the sum or product of the columns it equals in other rows.",
    group="records", weight=0.6, default_level="skews", scope="columns", detect=detect, depth=4,
    applies_to=frozenset(("int", "float")),
    injectors={"off_total": Injector(damage, share=0.03)}, clean_fixture=clean_fixture,
)
