"""Outliers by robust statistics: |x − median| / (1.4826 · MAD) > 5, or outside 3 × IQR when MAD is 0.
Skewed non-negative measures (skew > 2) are scored on log(1 + x)."""

import numpy as np

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector, examples
from sherlock.cleaning.detectors.fixtures import clean_frame

ROBUST_Z = 5.0
FENCE = 3.0
MIN_VALUES = 20
SKEWED = 2.0


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        if col.role != "measure" or col.numeric is None:
            continue
        values = col.numeric
        finite = values[np.isfinite(values)]
        if len(finite) < MIN_VALUES:
            continue
        if finite.min() >= 0 and finite.skew() > SKEWED:
            # Right-skewed non-negative measures (prices, incomes) are judged on a log scale.
            values, finite = np.log1p(values), np.log1p(finite)
        median = finite.median()
        mad = (finite - median).abs().median()
        if mad > 0:
            mask = ((values - median).abs() / (1.4826 * mad)) > ROBUST_Z
            method = "robust_z"
        else:
            q1, q3 = finite.quantile(0.25), finite.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            mask = (values < q1 - FENCE * iqr) | (values > q3 + FENCE * iqr)
            method = "iqr"
        mask = mask.fillna(False)
        if mask.any():
            findings.append(Finding(
                "outliers", name, int(mask.sum()),
                "Check these extreme values; they stay in unless they're errors.",
                examples(col.raw[mask].tolist()), {"method": method},
            ))
    return findings


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen number made fifty times larger."""
    return {(i, column): f"{float(df.at[i, column]) * 50:g}" for i in rows}


SPEC = DetectorSpec(
    "outliers", "outliers", "Extreme values in a measure, by robust statistics.",
    group="outliers", weight=0.3, default_level="check", scope="column", detect=detect,
    injectors={"extreme": Injector(damage, share=0.03)}, clean_fixture=lambda: (clean_frame(), "amount"),
)
