"""The dashboard builder (TRD §7.3), run by the `build_dashboard` job.

Candidates → scored in code → a shortlist of 14 → the model (`medium`, schema `Curation`) picks
6–10, orders and titles them and names the accent → each is validated by running it → layout. If
the model fails, the top 8 by score are used with templated titles. A dataset that already has
widgets keeps them: a data change never rebuilds the dashboard (PRD DASH-11).
"""

import json
import sqlite3

from sherlock.dashboard import prompts
from sherlock.dashboard.candidates import Candidate, generate
from sherlock.dashboard.scoring import rank_columns, score
from sherlock.errors import ApiError
from sherlock.jobs.runner import JobContext
from sherlock.llm.client import BudgetExceeded, CallScope, LLMClient, LLMUnavailable, StructuredOutputError, fence
from sherlock.llm.schemas import Curation
from sherlock.llm.text import has_digits
from sherlock.profile import service as profile_service
from sherlock.storage import dataset_dir
from sherlock.widgets import layout as wl
from sherlock.widgets import service as ws

SHORTLIST = 14
KPI_RESERVE = 3
PICK_MIN, PICK_MAX = 6, 10
FALLBACK_COUNT = 8


def shortlist(scored: list[Candidate]) -> list[Candidate]:
    """The 14 best by score, with up to three KPI tiles always among them (row count first)."""
    kpis = sorted([c for c in scored if c.view == "kpi"], key=lambda c: (c.kind != "kpi_rows", c.kind != "kpi_rate", -c.score))
    reserved = kpis[:KPI_RESERVE]
    rest = [c for c in scored if c not in reserved][: SHORTLIST - len(reserved)]
    return sorted(reserved + rest, key=lambda c: -c.score)


def fallback(short: list[Candidate]) -> list[tuple[Candidate, str, dict | None]]:
    kpis = [c for c in short if c.view == "kpi"][:KPI_RESERVE]
    charts = [c for c in short if c.view != "kpi"]
    chosen = kpis + charts[: FALLBACK_COUNT - len(kpis)]
    return [(c, c.title, c.point) for c in _ordered(chosen)]


def _ordered(cands: list[Candidate]) -> list[Candidate]:
    return [c for c in cands if c.view == "kpi"] + [c for c in cands if c.view != "kpi"]


def summary(card: dict) -> str:
    lines = [f"File: {card['row_count']} usable rows, {card['column_count']} columns."]
    for c in card["columns"]:
        lines.append(f"- {c['name']} · {c['type']} · {c['role']} · {c['missing_pct']}% missing · {c['distinct']} distinct")
    return "Columns:\n" + fence("\n".join(lines))


def _line(i: int, c: Candidate) -> str:
    elements = ", ".join((c.facts.get("elements") or [])[:12]) or "-"
    return f"{i} · {c.view} · {c.title} · {c.score:.2f} · {elements}"


def curate(llm: LLMClient, scope: CallScope, card: dict, short: list[Candidate]) -> tuple[list, bool]:
    """[(candidate, title, point)] in dashboard order, and whether the model chose them."""
    if not short:
        return [], False
    low, high = min(PICK_MIN, len(short)), min(PICK_MAX, len(short))

    def check(value: Curation) -> None:
        idx = [p.candidate for p in value.picks]
        if any(i >= len(short) for i in idx):
            raise ValueError(f"candidate index out of range (0–{len(short) - 1})")
        if len(set(idx)) != len(idx):
            raise ValueError("each candidate may be picked once")
        if not low <= len(idx) <= high:
            raise ValueError(f"pick between {low} and {high} candidates")

    messages = [
        {"role": "system", "content": prompts.SYSTEM},
        {"role": "user", "content": prompts.CURATE.format(
            low=low, high=high, datacard=summary(card),
            candidates=fence("\n".join(_line(i, c) for i, c in enumerate(short))))},
    ]
    try:
        out = llm.structured("medium", messages, Curation, purpose="curate", scope=scope, validate=check).value
    except (StructuredOutputError, LLMUnavailable, BudgetExceeded):
        return fallback(short), False
    picks = []
    for p in out.picks:
        c = short[p.candidate]
        title = p.title.strip()
        if not title or has_digits(title) or len(title) > 80:
            title = c.title  # a failing title falls back to the templated one
        point = c.point
        if p.point and p.point in (c.facts.get("elements") or []):
            point = {**(c.point or {"kind": "bar"}), "key": p.point}
        picks.append((c, title, point))
    kpis = [x for x in picks if x[0].view == "kpi"]
    return kpis + [x for x in picks if x[0].view != "kpi"], True


def driver_widget(env: ws.Env, dataset: sqlite3.Row, card: dict) -> sqlite3.Row | None:
    """"What drives this?" on the top target candidate when there are enough rows (TRD §7.3 step 5).
    Its run is queued; the widget shows the progress until the importance arrives."""
    from sherlock.ml.plan import MIN_ROWS

    targets = card.get("target_candidates") or []
    if not targets or (card.get("row_count") or 0) < MIN_ROWS:
        return None
    spec = {"scope": {"columns": {"target": targets[0]}}, "op": {"type": "ml", "recipe": "driver_analysis"},
            "view": {"type": "importance"}}
    try:
        return ws.create(env, dataset, spec, title=f"What drives {targets[0]}?", created_by="builder")
    except ApiError:
        return None  # e.g. fewer than 100 rows with the target filled in


def build(ctx: JobContext) -> dict:
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (ctx.dataset_id,)).fetchone()
    if dataset is None or dataset["deleted_at"]:
        return {"skipped": "dataset deleted"}
    if dataset["status"] != "building":
        ctx.set_dataset_status("building")
    existing = ws.live_count(ctx.db, dataset["id"])
    if existing:
        ctx.progress(1, 1, "Keeping the dashboard")
        ctx.set_dataset_status("ready")
        return {"version": dataset["current_version"], "widgets": existing, "kept": True}

    card = profile_service.get_or_build(ctx.settings, ctx.db, ctx.cache, dataset)
    ctx.progress(1, 3, "Choosing charts")
    vrow = ws.version_row(ctx.db, dataset["id"], dataset["current_version"])
    folder = dataset_dir(ctx.settings, dataset["user_id"], dataset["id"])
    with ctx.cache.connection(dataset["id"], vrow["version"], folder / vrow["parquet_path"]) as conn:
        keep = rank_columns(conn, card)
        scored = score(conn, card, generate(card, keep))
    ctx.check_cancel()

    ctx.progress(2, 3, "Picking the story")
    scope = CallScope(user_id=dataset["user_id"], dataset_id=dataset["id"], job_id=ctx.id,
                      on_wait=lambda text: ctx.log(text, icon="wait"))
    picks, by_model = curate(LLMClient(ctx.settings), scope, card, shortlist(scored))
    ctx.check_cancel()

    env = ws.Env(ctx.settings, ctx.db, ctx.cache, ctx.bus)
    made: list[sqlite3.Row] = []
    for i, (cand, title, point) in enumerate(picks, 1):
        ctx.progress(3, 3, f"Adding widgets · {i} of {len(picks)}", pct=round(66.7 + 33.3 * (i - 1) / len(picks), 1))
        try:
            made.append(ws.create(env, dataset, cand.spec(), title=title, created_by="builder", score=cand.score, point=point))
        except ApiError:
            continue  # validation (TRD §7.3 step 4): a widget whose query fails is dropped
        ctx.check_cancel()
    driver = driver_widget(env, dataset, card)  # TRD §7.3 step 5
    if driver is not None:
        made.append(driver)
    wl.save(ctx.db, dataset["id"], wl.pack([(r["id"], json.loads(r["spec_json"])["view"]["type"]) for r in made]))
    ctx.set_dataset_status("ready")
    if made:
        from sherlock.jobs.stories import queue_stories

        queue_stories(ctx.db, dataset, None, "build")  # TRD §7.3 step 7
        ctx.runner.wake()
    result = {"version": dataset["current_version"], "widgets": len(made), "candidates": len(scored),
              "curated_by": "model" if by_model else "fallback"}
    if keep is not None:
        result["columns_used"] = len(keep)
    return result
