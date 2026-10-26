"""Recipe manifests (TRD §6.5, PRD ML-1): what the analysis dropdown and the setup form are generated
from. With cuts 4 and 7, `driver_analysis` runs with Auto only; the other recipes are listed
disabled with the reason, so the dropdown shows what's coming."""

DRIVER = {
    "id": "driver_analysis", "label": "What drives this?", "group": "explain",
    "roles": {"target": {"required": True, "types": ["bool", "category", "int", "float"]}, "features": {"min": 1}},
    "min_rows": 100, "needs_time": False,
    "methods": [{"id": "auto", "label": "Auto", "task": ["classification", "regression"]}],
    "params": {"type": "object", "properties": {
        "cv_folds": {"type": "integer", "default": 5, "minimum": 3, "maximum": 10, "title": "Folds"},
        "time_budget_s": {"type": "integer", "default": 60, "minimum": 10, "maximum": 300, "title": "Time budget (s)"},
    }},
    "outputs": ["importance", "partial_dependence", "model_card"],
}

STUBS = [
    {"id": "predict", "label": "Predict a column", "group": "predict", "reason": "Not in this release"},
    {"id": "kmeans", "label": "Find groups", "group": "group", "reason": "Coming later"},
    {"id": "anomalies", "label": "Find unusual rows", "group": "unusual", "reason": "Coming later"},
    {"id": "forecast", "label": "Forecast", "group": "time", "reason": "Coming later", "needs_time": True},
]


FREE_TEXT_LENGTH = 40  # mean characters per value: the profile's free-text rule (TRD §6.1)


def target_ok(c: dict) -> bool:
    """A column a driver analysis can explain: a number, or two to twenty values; never an ID, a time,
    an empty column or free text. A category whose values average more than 40 characters is free text
    even when it repeats a few values (live, a `note` column of ten pasted sentences was the last column,
    so the profile took it for an outcome: "What drives note?", live test 2026-10-26, finding 10)."""
    if c["role"] in ("id", "free_text", "empty", "time") or c["type"] not in ("bool", "category", "int", "float"):
        return False
    if c["type"] in ("int", "float"):
        return True
    mean_length = (c.get("stats") or {}).get("mean_length")
    return 2 <= (c.get("distinct") or 0) <= 20 and not (mean_length and mean_length > FREE_TEXT_LENGTH)


def targets(card: dict) -> list[str]:
    """Columns a driver analysis can explain (`target_ok`). The DataCard's target candidates come first."""
    ok = [c["name"] for c in card["columns"] if target_ok(c)]
    first = [t for t in card.get("target_candidates") or [] if t in ok]
    return first + [t for t in ok if t not in first]


def candidates(card: dict) -> list[str]:
    """The DataCard's target candidates that a driver analysis can explain, best first: what the builder
    and the stories take as the file's outcome. A card stored before `target_ok` may still list a text column."""
    ok = {c["name"] for c in card["columns"] if target_ok(c)}
    return [t for t in card.get("target_candidates") or [] if t in ok]


def manifests(card: dict, rows: int) -> list[dict]:
    """Every recipe with `compatible` and, when not, the `reason` (PRD ML-1)."""
    out = []
    t = targets(card)
    driver = {**DRIVER, "targets": t, "compatible": bool(t) and rows >= DRIVER["min_rows"]}
    if not t:
        driver["reason"] = "needs a column to explain (a yes/no, a category or a number)"
    elif rows < DRIVER["min_rows"]:
        driver["reason"] = f"needs {DRIVER['min_rows']} rows; this has {rows}"
    out.append(driver)
    has_time = any(c["role"] == "time" for c in card["columns"])
    for s in STUBS:
        reason = "needs a date column" if s.get("needs_time") and not has_time else s["reason"]
        out.append({**s, "methods": [], "compatible": False, "reason": reason})
    return out
