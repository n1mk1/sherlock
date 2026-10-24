"""Broken functional dependencies: A almost always determines B (city → state) but a few rows
disagree. Only checked between categorical columns, and only where A's groups carry the signal."""

from itertools import permutations

from sherlock.cleaning.detectors.base import Finding, Frame, examples

AGREEMENT = 0.95
MAX_DISTINCT = 1000
MAX_COLUMNS = 12
MIN_LIFT = 0.2


def detect(frame: Frame) -> list[Finding]:
    candidates = [
        n for n, c in frame.columns.items()
        if c.type in ("category", "text", "bool", "int") and c.role in ("dimension", "target_like")
        and 2 <= c.text.nunique() <= MAX_DISTINCT
    ][:MAX_COLUMNS]
    findings = []
    for a, b in permutations(candidates, 2):
        pair = frame.df[[a, b]].dropna()
        if pair.empty:
            continue
        a_distinct, b_distinct = pair[a].nunique(), pair[b].nunique()
        if a_distinct < 3 or a_distinct < b_distinct:
            continue
        sizes = pair.groupby(a)[b].transform("size")
        grouped = pair[sizes >= 2]
        if len(grouped) < 0.5 * len(pair):
            continue
        counts = grouped.groupby([a, b], observed=True).size()
        modes = counts.groupby(level=0).idxmax().map(lambda key: key[1])
        agrees = grouped[b] == grouped[a].map(modes)
        agreement = agrees.mean()
        baseline = pair[b].value_counts(normalize=True).iloc[0]
        if AGREEMENT <= agreement < 1 and agreement - baseline >= MIN_LIFT:
            off = grouped[~agrees]
            findings.append(Finding(
                "functional_dependency", b, int((~agrees).sum()),
                f"Each {a} almost always has one {b}; review the rows that disagree.",
                examples([f"{x} → {y}" for x, y in zip(off[a], off[b])]),
                {"determinant": a, "agreement": round(float(agreement), 4)},
            ))
    return findings
