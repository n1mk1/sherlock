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


def targets(card: dict) -> list[str]:
    """Columns a driver analysis can explain: two to twenty values, or numbers; never IDs, text or
    empty columns. The DataCard's target candidates come first."""
    ok = [c["name"] for c in card["columns"]
          if c["role"] not in ("id", "free_text", "empty", "time") and c["type"] in ("bool", "category", "int", "float")
          and (c["type"] in ("int", "float") or 2 <= (c.get("distinct") or 0) <= 20)]
    first = [t for t in card.get("target_candidates") or [] if t in ok]
    return first + [t for t in ok if t not in first]


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
