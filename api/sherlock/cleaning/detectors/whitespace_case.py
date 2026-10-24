"""Whitespace and case variants: stray spaces, and spellings that differ only by case or spacing."""

from sherlock.cleaning.detectors.base import Finding, Frame, examples

TEXT_TYPES = ("category", "text", "id", "bool")


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        if col.type not in TEXT_TYPES:
            continue
        raw = col.raw.dropna().astype(str)
        if raw.empty:
            continue
        stray = (raw != raw.str.strip()) | raw.str.contains(r"\s{2,}", regex=True)
        key = raw.str.strip().str.replace(r"\s+", " ", regex=True).str.casefold()
        variants = raw[~stray]
        case_mask = stray & False
        if col.type != "id":
            groups = variants.groupby(key[~stray])
            for _, group in groups:
                spellings = group.value_counts()
                if len(spellings) > 1:
                    minority = spellings.index[1:]
                    case_mask |= raw.isin(minority) & ~stray
        mask = stray | case_mask
        if mask.any():
            findings.append(Finding(
                "whitespace_case", name, int(mask.sum()),
                "Trim spaces and use the most common spelling of each value.",
                examples(raw[mask].tolist()),
                {"stray_whitespace": int(stray.sum()), "case_variants": int(case_mask.sum())},
            ))
    return findings
