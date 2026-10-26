"""Near-duplicate categories: values one or two typos apart ("New York" / "New Yrok").

A pair the merge rule refuses isn't one (plan 2.5, `helpers._merge_refusal`): values that differ
only in their numbers ("Region 1" / "Region 2") or that are both common (each on 5% of the rows or
more, "Austria" / "Australia") are categories of their own, unless one is the other with an inner
letter left out ("Wst" / "West", `helpers._dropped_letter`). `details.pairs` lists the pairs that
may merge, [rare, common], and goes to the diagnose and propose prompts; `details.review_pairs` lists
those of them that are both common, and the step that merges them is flagged for review (TRD §7.2).
Values need four characters, or three letters ("Wst").
"""

from rapidfuzz import fuzz

from sherlock.cleaning.detectors.base import Finding, Frame, examples
from sherlock.cleaning.helpers import _COMMON_SHARE, _merge_key, _merge_refusal

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
        values = [v for v in counts.index if (len(v) >= MIN_LENGTH or (len(v) == 3 and v.isalpha()))
                  and not v.replace(".", "").isdigit()]
        keys = col.text.map(_merge_key).value_counts().to_dict()
        often = max(2, _COMMON_SHARE * frame.rows)  # `_merge_refusal`'s "common"
        pairs, review, minority = [], [], set()
        for i, a in enumerate(values):
            for b in values[i + 1:]:
                if fuzz.ratio(a, b) >= SIMILARITY and _merge_refusal(a, b, keys, frame.rows) is None:
                    rare = a if counts[a] < counts[b] else b
                    common = b if rare == a else a
                    pairs.append([rare, common])
                    minority.add(rare)
                    if min(keys.get(_merge_key(a), 0), keys.get(_merge_key(b), 0)) >= often:
                        review.append(pairs[-1])
        if minority:
            mask = col.text.str.casefold().isin(minority)
            findings.append(Finding(
                "near_duplicate_categories", name, int(mask.sum()),
                "Merge each rare spelling into its common neighbour after review.",
                examples(col.text[mask].tolist()),
                {"pairs": pairs[:20], **({"review_pairs": review[:20]} if review else {})},
            ))
    return findings
