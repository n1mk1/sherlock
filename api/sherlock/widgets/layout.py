"""Dashboard layout (TRD §4.5, UI/UX brief §3.3): react-grid-layout items per breakpoint.

Only `lg` (12 columns) is generated here: KPI tiles first, 3 × 3 each, then the other widgets in
order at their default sizes, packed left to right. `md` and `sm` are derived by the web app and
saved once the user touches them.
"""

import json
import sqlite3

from pydantic import BaseModel, ConfigDict, Field

from sherlock.db.util import now_iso

COLS = 12
DEFAULT_SIZE = {
    "kpi": (3, 3), "bar": (6, 7), "line": (6, 7), "area": (6, 7), "pie": (6, 7), "ring": (6, 7),
    "gauge": (3, 3), "scatter": (6, 7), "histogram": (6, 7), "box": (6, 7), "heatmap": (6, 8), "table": (6, 8),
    "importance": (8, 8), "confusion": (6, 8), "roc": (6, 7), "residuals": (6, 7), "coefficients": (8, 8),
}
MIN_W, MIN_H = 3, 5  # KPI tiles may be 3 × 3


class Item(BaseModel):
    model_config = ConfigDict(extra="ignore")
    i: str
    x: int = Field(ge=0, le=COLS - 1)
    y: int = Field(ge=0, le=10_000)
    w: int = Field(ge=1, le=COLS)
    h: int = Field(ge=1, le=100)
    collapsed: bool = False


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lg: list[Item] = Field(default_factory=list, max_length=500)
    md: list[Item] | None = None
    sm: list[Item] | None = None


def size_of(view_type: str) -> tuple[int, int]:
    return DEFAULT_SIZE.get(view_type, (6, 7))


def pack(widgets: list[tuple[str, str]]) -> dict:
    """`widgets` is `[(id, view_type)]` in order. KPIs go first in a row of their own."""
    items: list[dict] = []
    y = 0
    kpis = [w for w in widgets if w[1] == "kpi"]
    others = [w for w in widgets if w[1] != "kpi"]
    x = 0
    for wid, view in kpis:
        w, h = size_of(view)
        if x + w > COLS:
            x, y = 0, y + h
        items.append({"i": wid, "x": x, "y": y, "w": w, "h": h})
        x += w
    if kpis:
        y += size_of("kpi")[1]
    x, row_h = 0, 0
    for wid, view in others:
        w, h = size_of(view)
        if x + w > COLS:
            x, y, row_h = 0, y + row_h, 0
        items.append({"i": wid, "x": x, "y": y, "w": w, "h": h})
        x += w
        row_h = max(row_h, h)
    return {"lg": items}


def append(layout: dict, widget_id: str, view_type: str) -> dict:
    """Place a new widget under everything else."""
    w, h = size_of(view_type)
    bottom = max((it["y"] + it["h"] for it in layout.get("lg", [])), default=0)
    out = {**layout, "lg": [*layout.get("lg", []), {"i": widget_id, "x": 0, "y": bottom, "w": w, "h": h}]}
    for bp in ("md", "sm"):
        if out.get(bp) is not None:
            cols = 8 if bp == "md" else 4
            b = max((it["y"] + it["h"] for it in out[bp]), default=0)
            out[bp] = [*out[bp], {"i": widget_id, "x": 0, "y": b, "w": min(w, cols), "h": h}]
    return out


def stored(db: sqlite3.Connection, dataset_id: str) -> dict | None:
    row = db.execute("SELECT layout_json FROM layouts WHERE dataset_id = ?", (dataset_id,)).fetchone()
    return json.loads(row[0]) if row else None


def save(db: sqlite3.Connection, dataset_id: str, layout: dict) -> dict:
    db.execute(
        "INSERT INTO layouts (dataset_id, layout_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT (dataset_id) DO UPDATE SET layout_json = excluded.layout_json, updated_at = excluded.updated_at",
        (dataset_id, json.dumps(layout), now_iso()),
    )
    return layout


def current(db: sqlite3.Connection, dataset_id: str, live: list[tuple[str, str]]) -> dict:
    """The stored layout for the live widgets: items of deleted widgets are left out (they come back
    in place on restore), and any live widget the layout lacks is appended."""
    layout = stored(db, dataset_id)
    if layout is None:
        return pack(live)
    ids = {wid for wid, _ in live}
    out = {bp: [it for it in items if it["i"] in ids] for bp, items in layout.items() if items is not None}
    placed = {it["i"] for it in out.get("lg", [])}
    for wid, view in live:
        if wid not in placed:
            out = append(out, wid, view)
    return out
