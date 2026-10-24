"""Near-duplicate categories: values one or two typos apart ("New York" / "New Yrok")."""

from rapidfuzz import fuzz

from sherlock.cleaning.detectors.base import Finding, Frame, examples

MAX_DISTINCT = 200
MIN_LENGTH = 4
SIMILARITY = 85  # one swap or typo in an 8-letter value scores 87.5


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        if col.type not in ("category", "text") or col.role not in ("dimension", "target_like"):
            continue
        counts = col.text.str.casefold().value_counts()
        if not 3 <= len(counts) <= MAX_DISTINCT:
            continue
        values = [v for v in counts.index if len(v) >= MIN_LENGTH and not v.replace(".", "").isdigit()]
        pairs, minority = [], set()
        for i, a in enumerate(values):
            for b in values[i + 1:]:
                if fuzz.ratio(a, b) >= SIMILARITY:
                    rare = a if counts[a] < counts[b] else b
                    common = b if rare == a else a
                    pairs.append([rare, common])
                    minority.add(rare)
        if minority:
            mask = col.text.str.casefold().isin(minority)
            findings.append(Finding(
                "near_duplicate_categories", name, int(mask.sum()),
                "Merge each rare spelling into its common neighbour after review.",
                examples(col.text[mask].tolist()), {"pairs": pairs[:20]},
            ))
    return findings
