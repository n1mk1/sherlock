"""JSON schemas for structured calls (TRD §3.5): one pydantic model per call shape. The client sends
`model_json_schema()` as a strict `response_format` and validates the reply against the model.

The Cleaner's three calls (TRD §7.2) are here now; the dashboard, story and chat shapes join them
with the work that uses them (Implementation Plan D4, D6). Route and Story are the shapes the Day 1
smoke test passed.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sherlock.llm.text import has_digits


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Cleaner (TRD §7.2) -----------------------------------------------------------------------


class Diagnosis(Strict):
    cause: str = Field(description="the likely cause of the issue, one sentence")
    approach_options: list[str] = Field(min_length=2, max_length=3, description="two or three ways to fix it")
    preferred_option: int = Field(ge=0, le=2, description="index into approach_options of the safest good fix")
    risk: Literal["low", "medium", "high"] = Field(description="risk of changing data that is actually right")
    leave_as_is: bool = Field(description="true when the values are legitimate and should not be changed")


class Candidate(Strict):
    label: str = Field(description="short name of the approach")
    code: str = Field(description="pandas code: reads df, leaves the cleaned DataFrame in `result`")
    expected_effect: str = Field(description="what the code changes, one sentence")


class Candidates(Strict):
    candidates: list[Candidate] = Field(min_length=1, max_length=3)


class Critique(Strict):
    changed_something_it_shouldnt: bool
    concerns: list[str] = Field(max_length=5)


# --- Chat routing (TRD §8.1) ------------------------------------------------------------------


class Clarification(Strict):
    question: str
    options: list[str] = Field(min_length=2, max_length=3)


class Entity(Strict):
    text: str
    kind: Literal["column", "value", "widget", "card"]


INTENTS = Literal[
    "ask_data", "find_rows", "explain_widget", "ask_history", "ask_why", "ask_stats",
    "ask_model", "ask_meaning", "app_help", "create_widget", "update_widget", "ask_story",
]


class Route(Strict):
    intents: list[INTENTS] = Field(min_length=1, max_length=2)
    ambiguous: bool
    clarification: Clarification | None = None
    multi_step: bool
    entities: list[Entity]


# --- Story runs (TRD §7.4): numbers are chips, names are labels, prose has no digits ---------


class TextRun(Strict):
    text: str

    @model_validator(mode="after")
    def no_digits(self) -> "TextRun":
        if has_digits(self.text):
            raise ValueError(f"digits in a text run: {self.text!r}")
        return self


class ChipRun(Strict):
    chip: str


class LabelRun(Strict):
    label: str


Run = TextRun | ChipRun | LabelRun  # a union, so strict decoding enforces one kind per run


class Story(Strict):
    headline: list[Run] = Field(min_length=1)
    body: list[Run] = Field(min_length=1)
