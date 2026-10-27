"""Mojibake: text decoded with the wrong encoding somewhere upstream ("CafÃ©" for "Café")."""

from ftfy import fix_text
from ftfy.badness import is_bad

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector, examples
from sherlock.cleaning.detectors.fixtures import with_column

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


def damage(df, column: str, rows: list[int], rng) -> dict:
    """UTF-8 read as Latin-1 ("Café" becomes "CafÃ©"); a value with no accent stays."""
    out = {}
    for i in rows:
        v = str(df.at[i, column])
        garbled = v.encode("utf-8").decode("latin-1", errors="replace")
        if garbled != v:
            out[(i, column)] = garbled
    return out


PLACES = ["Zürich", "Genève", "München", "Québec", "Köln", "Montréal"]


SPEC = DetectorSpec(
    "mojibake", "garbled characters", "Text decoded with the wrong encoding somewhere upstream.",
    group="text", weight=0.6, default_level="splits", scope="column", detect=detect,
    applies_to=frozenset(("category", "text", "id")),
    injectors={"mojibake": Injector(damage)},
    clean_fixture=lambda: (with_column("place", [PLACES[i % len(PLACES)] for i in range(200)]), "place"),
)
