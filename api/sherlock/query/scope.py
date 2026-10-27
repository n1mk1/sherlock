"""The scope of an ML request or a chat chart (TRD §6.3): the columns it reads and the rows it keeps."""

from pydantic import BaseModel, ConfigDict, Field


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
