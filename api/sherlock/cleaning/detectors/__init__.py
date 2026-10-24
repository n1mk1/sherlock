"""The 16 detectors of PRD §7.3.2, with the severity weights of TRD §7.1 step 4.

Severity = affected share of rows × the detector's weight.
"""

from sherlock.cleaning.detectors import (
    ambiguous_dates,
    cross_column,
    duplicates,
    functional_dependency,
    id_candidates,
    impossible_values,
    leakage,
    missing,
    mixed_types,
    mojibake,
    near_duplicate_categories,
    numbers_as_text,
    outliers,
    sentinels,
    unit_mixes,
    whitespace_case,
)
from sherlock.cleaning.detectors.base import Finding, Frame

WEIGHTS = {
    "leakage": 1.0,
    "mixed_types": 0.9,
    "duplicates": 0.8,
    "sentinels": 0.7,
    "impossible_values": 0.7,
    "numbers_as_text": 0.6,
    "ambiguous_dates": 0.6,
    "mojibake": 0.6,
    "cross_column": 0.6,
    "missing": 0.5,
    "near_duplicate_categories": 0.5,
    "unit_mixes": 0.5,
    "functional_dependency": 0.5,
    "whitespace_case": 0.4,
    "outliers": 0.3,
    "id_candidates": 0.2,
}

DETECTORS = (
    leakage, mixed_types, duplicates, sentinels, impossible_values, numbers_as_text,
    ambiguous_dates, mojibake, cross_column, missing, near_duplicate_categories, unit_mixes,
    functional_dependency, whitespace_case, outliers, id_candidates,
)


def severity(finding: Finding, rows: int) -> float:
    share = min(finding.count / rows, 1.0) if rows else 0.0
    return round(share * WEIGHTS[finding.detector], 4)


def run_all(frame: Frame) -> list[tuple[Finding, float]]:
    """Every detector's findings with severities, most severe first."""
    results = []
    for module in DETECTORS:
        for finding in module.detect(frame):
            if finding.count > 0:
                results.append((finding, severity(finding, frame.rows)))
    results.sort(key=lambda pair: pair[1], reverse=True)
    return results
