"""Mojibake: text decoded with the wrong encoding somewhere upstream ("CafÃ©" for "Café")."""

from ftfy import fix_text
from ftfy.badness import is_bad

from sherlock.cleaning.detectors.base import Finding, Frame, examples

TEXT_TYPES = ("category", "text", "id")


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        if col.type not in TEXT_TYPES or col.text.empty:
            continue
        unique = col.text.drop_duplicates()
        bad_values = {v for v in unique if is_bad(v) and fix_text(v) != v}
        if bad_values:
            mask = col.text.isin(bad_values)
            fixed = [[v, fix_text(v)] for v in list(bad_values)[:5]]
            findings.append(Finding(
                "mojibake", name, int(mask.sum()),
                "Repair the garbled characters (ftfy) and keep the originals in lineage.",
                examples(col.text[mask].tolist()), {"fixes": fixed},
            ))
    return findings
