"""Unit mixes: one column holding numbers with different units ("5 kg", "11 lb", "300 g")."""

import re

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector, examples
from sherlock.cleaning.detectors.fixtures import with_column

WITH_UNIT = re.compile(r"^\s*[-+]?\d+(?:[.,]\d+)?\s*([A-Za-z°µ%]+[A-Za-z0-9²³/]*)\s*$")
MAJORITY = 0.5


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        if col.type not in ("category", "text") or col.text.empty:
            continue
        units = col.text.str.extract(WITH_UNIT)[0].str.lower()
        if units.notna().mean() < MAJORITY:
            continue
        counts = units.value_counts()
        if len(counts) < 2:
            continue
        mask = units.isin(counts.index[1:])
        findings.append(Finding(
            "unit_mixes", name, int(mask.sum()),
            f"Convert every value to one unit ({counts.index[0]}) and record the conversion.",
            examples(col.text[mask].tolist()), {"units": {u: int(n) for u, n in counts.items()}},
        ))
    return findings


SMALLER = {"kg": ("g", 1000), "km": ("m", 1000), "m": ("cm", 100), "l": ("ml", 1000), "g": ("mg", 1000)}


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen "5 kg" written in a smaller unit ("5000 g"); a unit it doesn't know stays."""
    out = {}
    for i in rows:
        m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*$", str(df.at[i, column]))
        if m and m.group(2).lower() in SMALLER:
            unit, factor = SMALLER[m.group(2).lower()]
            out[(i, column)] = f"{float(m.group(1)) * factor:g} {unit}"
    return out


SPEC = DetectorSpec(
    "unit_mixes", "mixed units", "One column holding numbers written with different units.",
    group="types", weight=0.5, default_level="skews", scope="column", detect=detect,
    applies_to=frozenset(("category", "text")),
    injectors={"unit": Injector(damage)},
    clean_fixture=lambda: (with_column("weight", [f"{1 + i % 40} kg" for i in range(200)]), "weight"),
)
