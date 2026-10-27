"""The 16 built-in detectors of PRD §7.3.2, one module each, each exporting its `DetectorSpec`.

`BUILTINS` is the order they run in; `cleaning/registry.py` registers them (PRD CLEAN-12).
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
from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame

BUILTINS = tuple(m.SPEC for m in (
    leakage, mixed_types, duplicates, sentinels, impossible_values, numbers_as_text,
    ambiguous_dates, mojibake, cross_column, missing, near_duplicate_categories, unit_mixes,
    functional_dependency, whitespace_case, outliers, id_candidates,
))
