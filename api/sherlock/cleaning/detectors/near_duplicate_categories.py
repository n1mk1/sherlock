"""Near-duplicate categories: values one or two typos apart ("New York" / "New Yrok").

A pair the merge rule refuses isn't one (`helpers._merge_refusal`): values that differ
only in their numbers ("Region 1" / "Region 2") or that are both common (each on 5% of the rows or
more, "Austria" / "Australia") are categories of their own, unless one is the other with an inner
letter left out ("Wst" / "West", `helpers._dropped_letter`). `details.pairs` lists the pairs that
may merge, [rare, common], one per rare value: its most common neighbour, followed on to a value that
isn't itself a rare spelling ("srocket" goes to "sprocket", not to the typo "sproket"). It goes to the
diagnose and propose prompts; `details.review_pairs` lists those of them that are both common, and the
step that merges them is flagged for review (TRD §7.2).
Values need four characters, or three letters ("Wst").
"""

from rapidfuzz import fuzz

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector, examples
from sherlock.cleaning.detectors.fixtures import clean_frame
from sherlock.cleaning.helpers import _COMMON_SHARE, _merge_key, _merge_refusal
from sherlock.llm.schemas import Candidate

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
        nearest: dict[str, str] = {}  # rare value -> its most common neighbour
        for i, a in enumerate(values):
            for b in values[i + 1:]:
                if fuzz.ratio(a, b) >= SIMILARITY and _merge_refusal(a, b, keys, frame.rows) is None:
                    rare = a if counts[a] < counts[b] else b
                    common = b if rare == a else a
                    if rare not in nearest or counts[common] > counts[nearest[rare]]:
                        nearest[rare] = common
        pairs, review = [], []
        for rare, common in nearest.items():
            seen = {rare}
            while common in nearest and common not in seen:  # a neighbour that is a rare spelling itself
                seen.add(common)
                common = nearest[common]
            if common == rare:
                continue
            pairs.append([rare, common])
            if min(keys.get(_merge_key(rare), 0), keys.get(_merge_key(common), 0)) >= often:
                review.append(pairs[-1])
        minority = {rare for rare, _ in pairs}
        if minority:
            mask = col.text.str.casefold().isin(minority)
            findings.append(Finding(
                "near_duplicate_categories", name, int(mask.sum()),
                "Merge each rare spelling into its common neighbour after review.",
                examples(col.text[mask].tolist()),
                {"pairs": pairs[:20], **({"review_pairs": review[:20]} if review else {})},
            ))
    return findings


def merge_candidate(issue: dict) -> Candidate | None:
    """The code's own fix (PRD CLEAN-4e): each spelling of a rare value the detector paired joins the
    most frequent spelling of its common neighbour, through `canonicalize_categories`, which still
    refuses a merge its rules don't allow. The pairs come from code, so the merge isn't a guess."""
    column = issue.get("column")
    pairs = (issue.get("details") or {}).get("pairs") or []
    if column is None or not pairs:
        return None
    to = {rare: common for rare, common in pairs}
    code = (f"to = {to!r}\n"
            f"values = df[{column!r}].dropna().astype(str)\n"
            "spelling = {}\n"
            "for v in values.value_counts().index:\n"
            "    spelling.setdefault(v.strip().casefold(), v)\n"
            "mapping = {v: spelling[to[v.strip().casefold()]] for v in values.unique()\n"
            "           if v.strip().casefold() in to and to[v.strip().casefold()] in spelling}\n"
            "result = df.copy()\n"
            f"result[{column!r}] = canonicalize_categories(df[{column!r}], mapping=mapping)")
    return Candidate(label="Merge the listed pairs", code=code,
                     expected_effect="Each rare spelling becomes its common neighbour's usual spelling.")


def damage(df, column: str, rows: list[int], rng) -> dict:
    """One inner letter dropped from each chosen value; a value under five characters is lowercased."""
    out = {}
    for i in rows:
        v = str(df.at[i, column])
        if len(v) < 5:
            out[(i, column)] = v.lower()
        else:
            k = rng.randrange(1, len(v) - 1)
            out[(i, column)] = v[:k] + v[k + 1:]
    return out


SPEC = DetectorSpec(
    "near_duplicate_categories", "near-duplicate categories", "Category values that differ by a typo.",
    group="text", weight=0.5, default_level="splits", scope="column", detect=detect,
    applies_to=frozenset(("category", "text")), code_fix=merge_candidate,
    injectors={"typo": Injector(damage)}, clean_fixture=lambda: (clean_frame(), "category"),
)
