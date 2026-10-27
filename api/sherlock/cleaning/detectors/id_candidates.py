"""ID candidates: columns that identify rows (almost all values distinct and present).

Amounts aren't IDs however unique (TRD §7.1): a float column, or text that mostly reads as amounts
("36.74", "$4.20", `infer.measure_like`), is a measure, unless its role is already `id` (its name).
"""

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, examples
from sherlock.cleaning.detectors.fixtures import clean_frame
from sherlock.profile.infer import measure_like

UNIQUE = 0.98
PRESENT = 0.95


def detect(frame: Frame) -> list[Finding]:
    findings = []
    rows = frame.rows
    for name, col in frame.columns.items():
        if not rows or col.text.empty:
            continue
        unique_ratio = col.text.nunique() / len(col.text)
        unique = unique_ratio >= UNIQUE and len(col.text) >= PRESENT * rows and rows >= 20
        if col.role == "id" or (unique and col.type != "float" and not measure_like(col.text)):
            findings.append(Finding(
                "id_candidates", name, len(col.text),
                "Use this column to identify rows; keep it out of charts and models.",
                examples(col.text.tolist()), {"unique_ratio": round(float(unique_ratio), 4)},
            ))
    return findings


SPEC = DetectorSpec(
    "id_candidates", "looks like an ID", "Columns that identify rows: almost every value distinct and present.",
    group="other", weight=0.2, default_level=None, scope="column", detect=detect, depth=2,
    never_change="Looks like an ID column, so it is left as is", skip_text="left as is",
    found_fixture=clean_frame,
)
