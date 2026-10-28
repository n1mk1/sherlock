"""Outside context next to a dated answer (docs/plans/tavily.md §3.6).

When an `ask_data` answer is a time series with one clear jump, the reply offers one button, "What happened
around <period>?". Code finds the jump (`find_jump`) and makes everything the press needs: the period's label
("March 2024" or "2020") and its start and end dates. The model is never asked which period, and a button's
period isn't taken from free text: the press names the message and the button, and the server reads the period
from the offer it saved on that message (`loop.Agent._period_offer`).

Pressing it runs `period_context`: one `news` search with `start_date` / `end_date` set to the period, whose query
is built from the user's words and the measure's column name, then the same cited, digit-free answer as
`web_context`: labelled "not from your data", no causal wording (the wording check rejects it), sources listed.
The period's year is the only number a query may add, because code made it; `check_query` is given the label
as part of the message so that year (and no other digit) passes, and a value of the file is still refused.
"""

import datetime as dt
import re
import statistics
from dataclasses import dataclass

from sherlock.agent import web as aw
from sherlock.agent.answerers import CantAnswer, Result, Toolkit
from sherlock.agent.compose import NUMBER_TYPE, text_block
from sherlock.llm.client import StructuredOutputError, fence
from sherlock.llm.schemas import WebQuery
from sherlock.web.client import WebClient, WebUnavailable

# A jump is the largest step between two consecutive points when it is big in itself and next to the rest of the
# series. Both must hold, so a series that is noisy all through, or one that moves a hair, offers no button.
MIN_POINTS = 4          # fewer points have no "usual" step to compare with
MIN_STEP_SHARE = 0.25   # the step is at least a quarter of the earlier point's value
MIN_STEP_VS_MEDIAN = 2.0  # and at least twice the series' median absolute step
LEAD_WEEKS = 2          # a month's search window starts this many weeks before the month and ends as many after
MAX_SPAN_DAYS = 400     # `period_context` refuses a window longer than a year and a bit

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
YEAR_NAMES = frozenset({"year", "yr", "years"})
MONTH_NAMES = frozenset({"month", "mon", "months", "month_no", "month_number"})
ISO_TIME = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2})(?:[T ].*)?)?)?$")
INT_TYPE = re.compile(r"^U?(TINY|SMALL|BIG|HUGE)?INT(EGER)?\b", re.I)
DATE_TYPE = re.compile(r"^(DATE|TIMESTAMP)", re.I)

PERIOD_QUERY = """Write one web news search query for what was happening in the world around {period}, about the subject of the user's question.

Rules:
- Use the question's own words and the measure's column name. Don't write the period: the app adds it.
- Never add a value, a number or a name that isn't in the question. You can't see the data, and nothing from it may be searched for.
- One short line, plain words.

The measure's column name:
{measure}

The file's column names:
{columns}

Question:
{message}"""


@dataclass(frozen=True)
class Jump:
    label: str        # "March 2024" or "2020"
    start_date: str   # ISO, the search window
    end_date: str
    measure: str      # the result's measure column


def period_label(start: dt.date, end: dt.date) -> str:
    """A window's name: its year when it spans a whole year, else the month at its middle ("March 2024")."""
    if (start.month, start.day, end.month, end.day) == (1, 1, 12, 31) and start.year == end.year:
        return str(start.year)
    mid = start + (end - start) / 2
    return f"{MONTHS[mid.month - 1]} {mid.year}"


def window(point: dt.date, grain: str) -> tuple[dt.date, dt.date]:
    """The search window around a point: its year, or its month with `LEAD_WEEKS` weeks either side."""
    if grain == "year":
        return dt.date(point.year, 1, 1), dt.date(point.year, 12, 31)
    first = point.replace(day=1)
    last = (first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1)) - dt.timedelta(days=1)
    pad = dt.timedelta(weeks=LEAD_WEEKS)
    return first - pad, last + pad


def _parse(value) -> tuple[dt.date, str] | None:
    """(date, grain) for a date, an ISO timestamp, "YYYY-MM" or "YYYY"; grain is "year" or "month"."""
    m = ISO_TIME.match(str(value).strip()) if value is not None else None
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
    try:
        return dt.date(year, month, day), ("month" if m.group(2) else "year")
    except ValueError:
        return None


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def series(res: Result) -> tuple[str, list[tuple[dt.date, float]], str] | None:
    """(the measure's column name, the points oldest first, the grain) when the result is one numeric
    measure over time: a date, timestamp or ISO text column, or a year (and month) column, and nothing else.
    Two points at one time, or a column of another kind beside them, make it a different answer, not a series."""
    if res.selection_id or res.truncated or len(res.rows) < MIN_POINTS:
        return None
    cols = res.columns
    names = [str(c["name"]).lower() for c in cols]
    types = [str(c.get("type") or "") for c in cols]

    def column(i):
        return [r[i] for r in res.rows]

    year_i = next((i for i, n in enumerate(names) if n in YEAR_NAMES and INT_TYPE.match(types[i])
                   and all(_is_number(v) and 1800 <= v <= 2200 for v in column(i) if v is not None)), None)
    month_i = next((i for i, n in enumerate(names) if year_i is not None and n in MONTH_NAMES and INT_TYPE.match(types[i])
                    and all(_is_number(v) and 1 <= v <= 12 for v in column(i) if v is not None)), None)
    if year_i is not None:
        time_cols = [year_i] + ([month_i] if month_i is not None else [])
        grain = "month" if month_i is not None else "year"

        def when(row):
            y, mo = row[year_i], row[month_i] if month_i is not None else 1
            return dt.date(int(y), int(mo), 1) if _is_number(y) and _is_number(mo) else None
    else:
        t = next((i for i, c in enumerate(types) if DATE_TYPE.match(c)), None)
        if t is None:  # text such as "2024-03" from strftime / date_trunc
            t = next((i for i in range(len(cols)) if not NUMBER_TYPE.match(types[i])
                      and all(_parse(v) for v in column(i) if v is not None) and any(v is not None for v in column(i))), None)
        if t is None:
            return None
        time_cols = [t]
        grains = {g for v in column(t) if v is not None and (p := _parse(v)) for g in [p[1]]}
        grain = "year" if grains == {"year"} else "month"

        def when(row):
            p = _parse(row[t])
            return p[0] if p else None
    rest = [i for i in range(len(cols)) if i not in time_cols]
    if len(rest) != 1 or not NUMBER_TYPE.match(types[rest[0]]):
        return None
    m = rest[0]
    points = [(d, float(r[m])) for r in res.rows if (d := when(r)) is not None and _is_number(r[m])]
    if len({d for d, _ in points}) != len(points) or len(points) < MIN_POINTS:
        return None
    return str(cols[m]["name"]), sorted(points), grain


def find_jump(res: Result, today: dt.date | None = None) -> Jump | None:
    """The result's largest step change between consecutive points, when it is a jump (the constants at the
    top): at least `MIN_STEP_SHARE` of the earlier point and `MIN_STEP_VS_MEDIAN` times the median step.
    The period is the later point's month (or year, for yearly points). None when it isn't a dated series,
    nothing jumps, or the period hasn't started yet."""
    found = series(res)
    if found is None:
        return None
    measure, points, grain = found
    steps = [abs(b - a) for (_, a), (_, b) in zip(points, points[1:], strict=False)]
    top = max(range(len(steps)), key=lambda i: steps[i])
    before = points[top][1]
    if steps[top] == 0 or before == 0 or steps[top] < MIN_STEP_SHARE * abs(before):
        return None
    if steps[top] < MIN_STEP_VS_MEDIAN * statistics.median(steps):
        return None
    point = points[top + 1][0]
    start, end = window(point, grain)
    if start > (today or dt.date.today()):
        return None
    return Jump(period_label(start, end), start.isoformat(), end.isoformat(), measure)


def offer(res: Result, today: dt.date | None = None) -> dict | None:
    """The button for a result, as a message action, or None. `label` is the button's text and what the press
    sends back; the dates and the measure stay on the saved message."""
    jump = find_jump(res, today)
    if jump is None:
        return None
    return {"kind": "ask_period", "label": f"What happened around {jump.label}?", "period": jump.label,
            "start_date": jump.start_date, "end_date": jump.end_date, "measure": jump.measure, "result": res.id}


# --- the press ---------------------------------------------------------------------------------

def _date(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(text))
    except ValueError:
        raise CantAnswer("I couldn't tell which period that button meant, so I didn't search the web.") from None


def period_context(kit: Toolkit, web: WebClient, question: str, measure_column: str, columns: list[str],
                   start_date: str, end_date: str):
    """The news around a period: one dated `news` search, then Super's cited answer from the snippets. Every
    failure is one line in place of the web block, as in `web_context`; nothing here raises past CantAnswer."""
    from sherlock.agent.insight import Reply

    if not web.enabled:
        raise CantAnswer(WebUnavailable("off").note)
    start, end = _date(start_date), _date(end_date)
    if end < start or (end - start).days > MAX_SPAN_DAYS:
        raise CantAnswer("I couldn't tell which period that button meant, so I didn't search the web.")
    label = period_label(start, end)
    # The measure counts only if it's a column of the file: a result's alias is the model's word, not metadata.
    measure = measure_column if measure_column in columns else ""
    prompt = PERIOD_QUERY.format(period=label, measure=fence(measure or "none"), columns=fence(", ".join(columns)),
                                 message=fence(question))
    try:
        drafted = " ".join(kit.llm.structured("medium", kit._messages(prompt), WebQuery, purpose="period_query",
                                              scope=kit.scope).value.query.split())
    except StructuredOutputError:
        drafted = measure.replace("_", " ").strip()  # the code template: the measure's name and the period
    query = drafted if label.lower() in drafted.lower() else f"{drafted} {label}".strip()
    try:
        # The label's year is code's, so it may go out; any other digit, and any value of the file, may not.
        aw.check_query(query, f"{question} {label}", columns, aw.file_values(kit.env.db, kit.dataset["id"]))
    except aw.QueryRefused:
        raise CantAnswer("I didn't search the web: the search would have included values from your file.") from None
    try:
        resp = web.search(query, scope=kit.scope, purpose="period_context", topic="news",
                          start_date=start.isoformat(), end_date=end.isoformat())
    except WebUnavailable as exc:
        raise CantAnswer(exc.note) from None
    found = aw.keep(resp)
    searched = aw.sources_block(query, found, resp)
    focus = {"web_query": query}
    if not found:
        return Reply(blocks=[text_block([{"type": "text", "text": "I searched the news for that period but found nothing that answers it."}]),
                             searched], focus=focus)
    asked = f"What was in the news around {label}, as it bears on this question: {question}"
    answer = aw._write(kit, aw.ANSWER.format(message=fence(asked), results=fence(aw.results_text(found))), "web_answer", len(found))
    if answer is None:
        runs = [{"type": "text", "text": "I couldn't write an answer from what the web search found; the sources are below."}]
    else:
        runs = aw.to_runs(answer, found)
    return Reply(blocks=[aw.web_block(aw.WEB_LEAD, runs), searched], sources=aw.message_sources(found), focus=focus)
