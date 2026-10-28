"""The 24 built-in detectors of PRD §7.3.2, one module each, each exporting its `DetectorSpec`.

`BUILTINS` is the order they run in; `cleaning/registry.py` registers them (PRD CLEAN-12).
"""

from sherlock.cleaning.detectors import (
    ambiguous_dates,
    arithmetic_mismatch,
    blank_rows,
    conflicting_keys,
    cross_column,
    date_sequence,
    duplicates,
    functional_dependency,
    header_rows,
    id_candidates,
    impossible_values,
    label_conflicts,
    leakage,
    missing,
    mixed_types,
    mojibake,
    near_duplicate_categories,
    numbers_as_text,
    outliers,
    sentinels,
    summary_rows,
    time_gaps,
    unit_mixes,
    whitespace_case,
)
from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame

BUILTINS = tuple(m.SPEC for m in (
    leakage, mixed_types, duplicates, sentinels, impossible_values, numbers_as_text,
    ambiguous_dates, mojibake, cross_column, missing, near_duplicate_categories, unit_mixes,
    functional_dependency, whitespace_case, outliers, id_candidates,
    header_rows, blank_rows, summary_rows, conflicting_keys, arithmetic_mismatch, date_sequence, label_conflicts,
    time_gaps,
))
