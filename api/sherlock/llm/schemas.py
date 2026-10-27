"""JSON schemas for structured calls (TRD §3.5): one pydantic model per call shape. The client sends
`model_json_schema()` as a strict `response_format` and validates the reply against the model.

The Cleaner's calls (TRD §7.2), chat's (TRD §8.1–§8.2) and the data dictionary's (TRD §7.1.1).
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


class Rating(Strict):
    ref: str = Field(description="the finding's ref, as given (f1, f2, …)")
    level: Literal["breaks", "skews", "splits", "check", "cosmetic"]
    reason: str = Field(description="one sentence on what the finding does to an analysis, no digits")
    likely_real: bool = Field(description="true when the values look real rather than errors")


class Ratings(Strict):
    """The review's rating call (TRD §7.2, PRD CLEAN-8c): a level and a reason for each finding of a chunk."""
    ratings: list[Rating] = Field(min_length=1, max_length=40)


# --- Chat routing (TRD §8.1) ------------------------------------------------------------------


class Clarification(Strict):
    question: str
    options: list[str] = Field(min_length=2, max_length=3)


class Entity(Strict):
    text: str
    kind: Literal["column", "value"]


INTENTS = Literal[
    "ask_data", "find_rows", "ask_history", "ask_why", "ask_stats",
    "ask_model", "ask_meaning", "app_help", "edit_cells", "clean_selection", "edit_plan", "web_context",
]


class Route(Strict):
    intents: list[INTENTS] = Field(min_length=1, max_length=2)
    ambiguous: bool
    clarification: Clarification | None = None
    multi_step: bool
    entities: list[Entity]


# --- Answer runs (TRD §8.1): numbers are chips, names are labels, prose has no digits ---------


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


# --- Chat answerers and compose (TRD §8.1–§8.2) ---------------------------------------------


class SqlDraft(Strict):
    reading: str = Field(description="how you read the question's words as columns and values, e.g. '<their word> → <column>'")
    sql: str = Field(description="one DuckDB SELECT over table t that filters its rows with WHERE {{rows}}")
    answerable: bool = Field(description="false when no column in this file can answer the question")
    closest: str | None = Field(description="when not answerable: the closest question this file can answer, else null")

    @model_validator(mode="after")
    def complete(self) -> "SqlDraft":
        # An empty draft (no query, no closest question) satisfies the JSON schema but none of the prompt's
        # rules; taken as written, it tells the user no column answers a question one does. It gets the repair.
        if not self.sql.strip():
            raise ValueError("sql is empty: write the query that answers the question")
        if not self.answerable and not (self.closest or "").strip():
            raise ValueError("closest is empty: if no column can answer the question, give the closest question this file "
                             "can answer; otherwise write the query and set answerable to true")
        return self


class PredicateDraft(Strict):
    predicate: str = Field(description="a DuckDB boolean condition over the columns of t, without WHERE")
    label: str = Field(description="what the rows are, in a few plain words")


class Answer(Strict):
    # The prose comes first: with it last, Super often closed the object with an empty list.
    prose: list[Run] = Field(min_length=1, max_length=40,
                             description="required: one to three sentences answering the question; every number is a chip")
    shape: Literal["number", "table", "chart", "text"]
    number: str | None = Field(description="for shape number: the chip of the headline value, else null")
    label: str | None = Field(description="for shape number: what the value is, in words with no digits, else null")
    chart: Literal["bar", "line", "area", "pie"] | None = Field(description="for shape chart: the chart type, else null")


# --- Chat answerers, D7.3 (TRD §8.2) ---------------------------------------------------------


class StatsDraft(Strict):
    reading: str = Field(description="how you read the question's words as columns, e.g. '<two groups> → <column>'")
    outcome: str = Field(description="the column whose values are compared (a number or a category)")
    group: str = Field(description="the column that splits the rows into groups, or the second number")


class Meaning(Strict):
    general: str = Field(description="one or two sentences, no digits: what this column most likely records, "
                                     "from general knowledge; say so when unsure")

    @model_validator(mode="after")
    def no_digits(self) -> "Meaning":
        if has_digits(self.general):
            raise ValueError("write the meaning without digits")
        if not self.general.strip():
            raise ValueError("the meaning can't be empty")
        return self


# --- Chat completion, D8.5 (TRD §8.1 step 4, §8.2 actions) ------------------------------------


class CellDraft(Strict):
    row_id: int = Field(description="the _row_id of the row to change")
    column: str = Field(description="the column to change, exactly as named in the file")
    value: str | None = Field(description="the new value as text, or null to empty the cell")


class EditsDraft(Strict):
    reading: str = Field(description="which rows and columns the request means, and the new values, in a few words")
    edits: list[CellDraft] = Field(min_length=1, max_length=200)


class RuleDraft(Strict):
    """A check in plain fields (PRD CLEAN-13): the parameters its kind takes, the others null."""
    kind: Literal["range", "date_window", "allowed", "pattern", "not_missing", "unique", "order", "depends"]
    column: str = Field(description="the column the check is about, exactly as named")
    min: float | None = Field(description="range: the lowest allowed value, or null")
    max: float | None = Field(description="range: the highest allowed value, or null")
    earliest: str | None = Field(description="date_window: the earliest allowed date, YYYY-MM-DD, or null")
    latest: str | None = Field(description="date_window: the latest allowed date, YYYY-MM-DD, or null")
    values: list[str] | None = Field(description="allowed: the allowed values, or null")
    regex: str | None = Field(description="pattern: an anchored regular expression (^…$), or null")
    other: str | None = Field(description="order: the column that comes first; depends: the column that determines "
                                          "this one; else null")
    action: Literal["quarantine", "flag", "fix"]


class RuleSuggestion(Strict):
    rule: RuleDraft
    reason: str = Field(description="one sentence on why the check holds for this column, no digits")


class RuleSuggestions(Strict):
    """Suggested checks (TRD §7.2, PRD CLEAN-14): rules the model writes and code runs."""
    suggestions: list[RuleSuggestion] = Field(max_length=8)


class PlanEdit(Strict):
    op: Literal["tick", "untick", "tick_module", "untick_module", "tick_level", "untick_level", "set_instruction", "add",
                "remove", "add_rule"]
    item: str | None = Field(description="the plan item's ref (f1, f2, …) for tick, untick, set_instruction and remove; else null")
    module: str | None = Field(description="the module for tick_module and untick_module; else null")
    level: Literal["breaks", "skews", "splits", "check", "cosmetic"] | None = Field(
        description="the level for tick_level and untick_level; else null")
    rule: RuleDraft | None = Field(description="for add_rule: the check to add; else null")
    column: str | None = Field(description="for add: the column the step is about, exactly as named, or null for the rows")
    instruction: str | None = Field(description="for add and set_instruction: what to do, in plain words; null on "
                                                "set_instruction puts Sherlock's wording back")


class PlanEdits(Strict):
    """`edit_plan` (TRD §8.2, PRD CLEAN-8b): the changes a chat message asks of the open cleaning plan."""
    reading: str = Field(description="which fixes or columns the message means, in a few words")
    ops: list[PlanEdit] = Field(min_length=1, max_length=20)


class PlanStep(Strict):
    intent: INTENTS
    question: str = Field(description="this step's own question, complete on its own")


class Plan(Strict):
    steps: list[PlanStep] = Field(min_length=2, max_length=5)


# --- Web answers (TRD §3.6, §8.2 `web_context`, PRD ASK-11) ---------------------------------


class WebQuery(Strict):
    query: str = Field(description="a web search query of at most 400 characters, from the question's own words and the "
                                   "file's column names only; never a value from the file")
    recent: bool = Field(description="true only when the question asks about recent events or the latest figures")


class CiteRun(Strict):
    cite: int = Field(ge=1, le=5, description="the number of the source the sentence before it comes from")


WebRun = TextRun | CiteRun  # a union, so strict decoding enforces one kind per run


class WebAnswer(Strict):
    """What the web sources say, in text runs and citations: no digits, so a number from a page can only be
    shown inside its quoted excerpt."""
    prose: list[WebRun] = Field(min_length=1, max_length=30,
                                description="one to three plain sentences, each followed by a cite of its source")
    unanswered: bool = Field(description="true when the sources don't answer the question")


class ColumnNote(Strict):
    column: str = Field(description="a column of the file, exactly as named")
    description: str = Field(description="one plain sentence, no digits: what the column records, from the excerpt")
    excerpt: int = Field(ge=1, description="the number of the excerpt the description comes from")

    @model_validator(mode="after")
    def no_digits(self) -> "ColumnNote":
        if has_digits(self.description):
            raise ValueError(f"digits in the description of {self.column!r}: the excerpt keeps the numbers")
        if not self.description.strip():
            raise ValueError(f"the description of {self.column!r} is empty")
        return self


class ColumnNotes(Strict):
    """A data dictionary mapped to the file's columns (TRD §7.1)."""
    notes: list[ColumnNote] = Field(max_length=200, description="one note per column an excerpt describes")
