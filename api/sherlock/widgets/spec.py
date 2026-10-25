"""The WidgetSpec (TRD §6.3): scope (columns and rows) + op (SQL or an ML recipe) + view.

The spec is what a widget *is*; its title, status and layout are stored beside it. `spec_hash` is
the sha1 of the canonical JSON and is part of the data cache key (TRD §9).
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

VIEW_TYPES = (
    "bar", "line", "area", "pie", "ring", "gauge", "scatter", "heatmap", "histogram", "box", "kpi", "table",
    "importance", "confusion", "roc", "residuals", "coefficients",
)
# Views the web app draws: Bklit's (D4.7) and the custom visx charts (D6.5). The builder only proposes
# these; gauges render as a KPI tile.
P0_VIEWS = ("bar", "line", "area", "pie", "ring", "kpi", "table", "histogram", "heatmap", "box", "scatter")
AGGS = ("count", "sum", "avg", "min", "max", "median", "rate")

ViewType = Literal[
    "bar", "line", "area", "pie", "ring", "gauge", "scatter", "heatmap", "histogram", "box", "kpi", "table",
    "importance", "confusion", "roc", "residuals", "coefficients",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Columns(_Model):
    x: str | None = None
    y: str | None = None
    agg: str | None = None
    series: str | None = None
    target: str | None = None
    features: list[str] | None = None
    exclude: list[str] = Field(default_factory=list)


class Rows(_Model):
    predicate: str | None = None
    selection_id: str | None = None
    inherit_global_filters: bool = True


class Scope(_Model):
    columns: Columns = Field(default_factory=Columns)
    rows: Rows = Field(default_factory=Rows)


class SqlOp(_Model):
    type: Literal["sql"] = "sql"
    sql: str = Field(min_length=1, max_length=20_000)


class MlOp(_Model):
    type: Literal["ml"]
    recipe: str
    method: str = "auto"
    params: dict = Field(default_factory=dict)


class View(_Model):
    type: ViewType
    from_: str = Field(default="result", alias="from")
    options: dict = Field(default_factory=dict)


class WidgetSpec(_Model):
    scope: Scope = Field(default_factory=Scope)
    op: Annotated[SqlOp | MlOp, Field(discriminator="type")]
    view: View

    def dump(self) -> dict:
        return self.model_dump(by_alias=True)


def canonical(spec: dict) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"))


def spec_hash(spec: dict) -> str:
    return hashlib.sha1(canonical(spec).encode()).hexdigest()


def merge(base: dict, patch: dict) -> dict:
    """A partial spec over a full one (PATCH /widgets/{wid}): objects merge, anything else replaces."""
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out
