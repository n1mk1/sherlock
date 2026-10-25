"""Story cards (TRD §4.6, §7.4): fact sheets, relations, narration and the cards themselves.

`tell()` is the pipeline the `stories` job and the cascade share: for each widget, compute and store
its fact sheet on the current version, verify it, narrate it (in parallel, four at a time) and store
the card, emitting `card.updated` as each one is ready; then the overview. With cut 6 applied there
is no material-change check: every affected card is narrated again. A card the user edited keeps its
text and gets the new narration as a suggestion; with "Story updates: Ask first", a cascade marks
cards outdated instead of narrating them.
"""

import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError, not_found
from sherlock.jobs.events import emit
from sherlock.llm.client import CallScope, LLMClient
from sherlock.stories import facts as fx
from sherlock.stories import narrate as nr
from sherlock.widgets import compile as wc
from sherlock.widgets import service as ws

WORKERS = 4
NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")


# --- fact sheets ----------------------------------------------------------------------------------

def rows_sql(env: ws.Env, dataset: sqlite3.Row, spec: dict, version: int) -> str:
    types = ws.user_types(env, dataset, version)
    rows = spec.get("scope", {}).get("rows", {})
    predicate = wc.validate_predicate(rows["predicate"], list(types)) if rows.get("predicate") else None
    selection = ws.selection_sql(env.db, dataset["id"], rows["selection_id"]) if rows.get("selection_id") else None
    return wc.rows_clause(predicate, selection, None)


def build_sheet(env: ws.Env, dataset: sqlite3.Row, widget: sqlite3.Row, version: int) -> dict:
    """Compute, verify and store a widget's fact sheet on `version`."""
    spec = json.loads(widget["spec_json"])
    if spec["op"]["type"] != "sql":
        return _store_sheet(env.db, dataset["id"], widget["id"], version, {}, [])
    sql = ws.compiled(env, dataset, spec, version, [])
    data = ws.data(env, dataset, widget, [], version)
    src = fx.Source(sql=sql, rows_sql=rows_sql(env, dataset, spec, version), spec=spec, title=widget["title"],
                    columns=data["columns"], rows=data["rows"])
    with ws.connection(env, dataset, version) as conn:
        facts = fx.compute(conn, src)
        stale = fx.verify(conn, facts, list(facts))
        if stale:  # never narrate from values that don't hold (TRD §7.4 step 4)
            facts = {k: f for k, f in facts.items() if k not in stale}
    return _store_sheet(env.db, dataset["id"], widget["id"], version, facts, fx.depends_on(spec, sql))


def _store_sheet(db, dataset_id, widget_id, version, facts, depends) -> dict:
    sheet_id = new_id("fs")
    db.execute(
        "INSERT INTO fact_sheets (id, dataset_id, widget_id, version, facts_json, depends_columns_json, material_hash, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
        (sheet_id, dataset_id, widget_id, version, json.dumps(facts, default=str), json.dumps(depends), now_iso()),
    )
    return {"id": sheet_id, "widget_id": widget_id, "version": version, "facts": facts, "depends": depends}


def get_sheet(db: sqlite3.Connection, sheet_id: str | None) -> dict | None:
    if not sheet_id:
        return None
    r = db.execute("SELECT * FROM fact_sheets WHERE id = ?", (sheet_id,)).fetchone()
    if r is None:
        return None
    return {"id": r["id"], "widget_id": r["widget_id"], "version": r["version"], "facts": json.loads(r["facts_json"]),
            "depends_columns": json.loads(r["depends_columns_json"]), "computed_at": r["created_at"]}


# --- relations (TRD §7.4 step 2) ------------------------------------------------------------------

def relations(db: sqlite3.Connection, dataset_id: str, version: int, sheets: dict[str, dict], target: str | None) -> None:
    """Shared columns 0.5, same target 0.3; pairs at 0.4 or more, at most four per widget."""
    db.execute("DELETE FROM relations WHERE dataset_id = ? AND version = ?", (dataset_id, version))
    ids = list(sheets)
    edges = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ca, cb = set(sheets[a]["depends"]), set(sheets[b]["depends"])
            shared = sorted(ca & cb)
            weight, kinds = 0.0, []
            if shared:
                weight += 0.5
                kinds.append(("shared_column", {"columns": shared}))
            if target and target in ca and target in cb:
                weight += 0.3
                kinds.append(("same_target", {"column": target}))
            if weight >= 0.4:
                edges.append((a, b, weight, kinds))
    count: dict[str, int] = {}
    for a, b, weight, kinds in sorted(edges, key=lambda e: -e[2]):
        if count.get(a, 0) >= 4 or count.get(b, 0) >= 4:
            continue
        count[a] = count.get(a, 0) + 1
        count[b] = count.get(b, 0) + 1
        for kind, detail in kinds:
            db.execute("INSERT OR REPLACE INTO relations (dataset_id, version, a_widget, b_widget, kind, weight, detail_json) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)", (dataset_id, version, a, b, kind, weight, json.dumps(detail)))


def related_ids(db: sqlite3.Connection, dataset_id: str, widget_id: str) -> list[str]:
    rows = db.execute(
        "SELECT a_widget, b_widget, max(weight) AS w FROM relations WHERE dataset_id = ? AND version = "
        "(SELECT max(version) FROM relations WHERE dataset_id = ?) AND (a_widget = ? OR b_widget = ?) "
        "GROUP BY a_widget, b_widget ORDER BY w DESC", (dataset_id, dataset_id, widget_id, widget_id)).fetchall()
    return [r["b_widget"] if r["a_widget"] == widget_id else r["a_widget"] for r in rows][:4]


# --- cards ----------------------------------------------------------------------------------------

def to_card(db: sqlite3.Connection, r: sqlite3.Row) -> dict:
    """A card in the TRD §4.6 shape, plus its fact values (`facts`: key → {formatted, label}) so chips
    render from the latest sheet, and the related widgets."""
    sheet = get_sheet(db, r["fact_sheet_id"])
    related = []
    if r["widget_id"]:
        for wid in related_ids(db, r["dataset_id"], r["widget_id"]):
            w = db.execute("SELECT id, title FROM widgets WHERE id = ? AND deleted_at IS NULL", (wid,)).fetchone()
            if w:
                related.append({"widget_id": w["id"], "title": w["title"]})
    return {
        "id": r["id"], "dataset_id": r["dataset_id"], "kind": r["kind"], "widget_id": r["widget_id"],
        "source_card_ids": json.loads(r["source_card_ids_json"]) if r["source_card_ids_json"] else None,
        "job_id": r["job_id"], "headline": json.loads(r["headline_json"]), "body": json.loads(r["body_json"]),
        "fact_sheet_id": r["fact_sheet_id"], "status": r["status"], "edited_by_user": bool(r["edited_by_user"]),
        "changed_badge": bool(r["changed_badge"]),
        "suggestion": json.loads(r["suggestion_json"]) if r["suggestion_json"] else None,
        "version": r["version"], "narrated_by": r["narrated_by"], "updated_at": r["updated_at"],
        "facts": {k: {"formatted": f["formatted"], "label": f["label"]} for k, f in (sheet["facts"] if sheet else {}).items()},
        "related": related,
    }


def card_row(db: sqlite3.Connection, card_id: str) -> sqlite3.Row:
    r = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if r is None:
        raise not_found("Card not found")
    return r


def emit_card(db, bus, dataset: sqlite3.Row, card_id: str, job_id: str | None = None) -> dict:
    card = to_card(db, card_row(db, card_id))
    emit(db, bus, dataset["id"], dataset["user_id"], "card.updated", card, job_id=job_id)
    return card


def _bump(db, dataset_id):
    db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (dataset_id,))


def _upsert(db, dataset_id: str, kind: str, widget_id: str | None, headline: dict, body: dict, sheet_id: str,
            version: int, narrated_by: str | None, changed: bool) -> str:
    now = now_iso()
    q = ("SELECT * FROM cards WHERE dataset_id = ? AND kind = 'overview' AND deleted_at IS NULL" if kind == "overview"
         else "SELECT * FROM cards WHERE dataset_id = ? AND widget_id = ? AND deleted_at IS NULL")
    existing = db.execute(q, (dataset_id,) if kind == "overview" else (dataset_id, widget_id)).fetchone()
    if existing is None:
        card_id = new_id("crd")
        db.execute(
            "INSERT INTO cards (id, dataset_id, kind, widget_id, headline_json, body_json, fact_sheet_id, status, version, "
            "narrated_by, verified_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?)",
            (card_id, dataset_id, kind, widget_id, json.dumps(headline), json.dumps(body), sheet_id, version, narrated_by,
             now, now, now))
        return card_id
    if existing["edited_by_user"]:
        db.execute("UPDATE cards SET suggestion_json = ?, fact_sheet_id = ?, changed_badge = ?, status = 'ready', "
                   "updated_at = ? WHERE id = ?",
                   (json.dumps({"headline": headline, "body": body}), sheet_id, int(changed), now, existing["id"]))
    else:
        db.execute("UPDATE cards SET headline_json = ?, body_json = ?, fact_sheet_id = ?, status = 'ready', version = ?, "
                   "narrated_by = ?, verified_at = ?, changed_badge = ?, updated_at = ? WHERE id = ?",
                   (json.dumps(headline), json.dumps(body), sheet_id, version, narrated_by, now,
                    int(changed or existing["changed_badge"]), now, existing["id"]))
    return existing["id"]


def _set_status(db, dataset_id: str, widget_id: str, status: str) -> str | None:
    r = db.execute("SELECT id FROM cards WHERE dataset_id = ? AND widget_id = ? AND deleted_at IS NULL",
                   (dataset_id, widget_id)).fetchone()
    if r:
        db.execute("UPDATE cards SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), r["id"]))
        return r["id"]
    return None


def tell(env: ws.Env, llm: LLMClient, scope: CallScope, dataset: sqlite3.Row, widget_ids: list[str] | None, *,
         reason: str, ask_first: bool = False, progress=lambda *_: None, check_cancel=lambda: None) -> dict:
    """Fact sheets and cards for the widgets (all when None), then the overview. `reason` is
    "build" (a new dashboard), "widget" (one added or changed), "cascade" or "refresh"."""
    db = env.db
    version = dataset["current_version"]
    rows = db.execute("SELECT * FROM widgets WHERE dataset_id = ? AND deleted_at IS NULL ORDER BY order_no",
                      (dataset["id"],)).fetchall()
    chosen = [r for r in rows if widget_ids is None or r["id"] in widget_ids]
    card = _datacard(env, dataset)
    dataset_columns = [c["name"] for c in card["columns"]]
    target = (card.get("target_candidates") or [None])[0]

    if reason == "cascade" and ask_first:
        marked = []
        for w in chosen:
            cid = _set_status(db, dataset["id"], w["id"], "outdated")
            if cid:
                emit_card(db, env.bus, dataset, cid, scope.job_id)
                marked.append(cid)
        _bump(db, dataset["id"])
        return {"cards": 0, "outdated": len(marked)}

    sheets: dict[str, dict] = {}
    failed: set[str] = set()
    for i, w in enumerate(chosen, 1):
        check_cancel()
        progress(i, len(chosen) + 1, f"Reading the facts · {i} of {len(chosen)}")
        cid = _set_status(db, dataset["id"], w["id"], "updating")
        if cid:
            emit_card(db, env.bus, dataset, cid, scope.job_id)
        try:
            sheets[w["id"]] = build_sheet(env, dataset, w, version)
        except ApiError:
            failed.add(w["id"])  # a widget whose query fails on this version has no story until it works again
    all_sheets = dict(sheets)
    if widget_ids is not None:  # relations need every widget's sheet; reuse the latest of the others
        for w in rows:
            if w["id"] not in all_sheets:
                prev = db.execute("SELECT id FROM fact_sheets WHERE widget_id = ? ORDER BY created_at DESC LIMIT 1",
                                  (w["id"],)).fetchone()
                s = get_sheet(db, prev["id"]) if prev else None
                if s:
                    all_sheets[w["id"]] = {**s, "depends": s["depends_columns"]}
    relations(db, dataset["id"], version, all_sheets, target)

    titles = {w["id"]: w["title"] for w in rows}
    jobs = []
    for w in chosen:
        if w["id"] not in sheets or not sheets[w["id"]]["facts"]:
            continue
        spec = json.loads(w["spec_json"])
        related = [titles[r] for r in related_ids(db, dataset["id"], w["id"]) if r in titles]
        jobs.append((w, sheets[w["id"]], dict(title=w["title"], widget_id=w["id"], spec=spec, facts=sheets[w["id"]]["facts"],
                                               widget_columns=sheets[w["id"]]["depends"], dataset_columns=dataset_columns,
                                               related=related)))
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [(w, sheet, pool.submit(nr.narrate, llm, scope, **kw)) for w, sheet, kw in jobs]
        for w, sheet, fut in futures:
            check_cancel()
            try:
                headline, body, by_model = fut.result()
            except Exception:  # noqa: BLE001 - any failure leaves the card as the fact sheet's bullets
                (headline, body), by_model = nr.fallback(w["title"], w["id"], sheet["facts"]), False
            existed = db.execute("SELECT 1 FROM cards WHERE dataset_id = ? AND widget_id = ? AND deleted_at IS NULL",
                                 (dataset["id"], w["id"])).fetchone() is not None
            cid = _upsert(db, dataset["id"], "widget", w["id"], headline, body, sheet["id"], version,
                          llm.settings.model_medium if by_model else None, changed=existed and reason == "cascade")
            emit_card(db, env.bus, dataset, cid, scope.job_id)
            done += 1
    told = {w["id"] for w, _, _ in jobs}
    for w in chosen:  # never leave a card spinning: a failed query asks for Refresh, no facts keeps the text
        if w["id"] not in told:
            cid = _set_status(db, dataset["id"], w["id"], "outdated" if w["id"] in failed else "ready")
            if cid:
                emit_card(db, env.bus, dataset, cid, scope.job_id)
    progress(len(chosen) + 1, len(chosen) + 1, "Writing the overview")
    tell_overview(env, llm, scope, dataset, rows, dataset_columns, changed=reason == "cascade")
    _bump(db, dataset["id"])
    return {"cards": done, "widgets": len(chosen)}


class _Offline:
    """A client that is never reachable, for the overview's code-written fallback."""
    def structured(self, *a, **k):
        from sherlock.llm.client import LLMUnavailable

        raise LLMUnavailable("offline")


def tell_overview(env: ws.Env, llm: LLMClient, scope: CallScope, dataset: sqlite3.Row, rows, dataset_columns, changed=False):
    db = env.db
    widgets = []
    for i, w in enumerate(rows, 1):
        r = db.execute("SELECT c.fact_sheet_id FROM cards c WHERE c.widget_id = ? AND c.deleted_at IS NULL", (w["id"],)).fetchone()
        sheet = get_sheet(db, r["fact_sheet_id"]) if r else None
        if sheet and sheet["facts"]:
            widgets.append({"prefix": f"w{i}", "title": w["title"], "facts": sheet["facts"], "score": w["score"],
                            "widget_id": w["id"]})
    if not widgets:
        return None
    try:
        merged, body, by_model = nr.overview(llm, scope, widgets, dataset_columns)
    except Exception:  # noqa: BLE001 - the overview is never worth failing the job
        merged, body, by_model = nr.overview(_Offline(), scope, widgets, dataset_columns)
    sheet = _store_sheet(db, dataset["id"], None, dataset["current_version"], merged, [])
    headline = {"blocks": [{"type": "paragraph", "runs": [{"type": "text", "text": "What stands out"}]}]}
    cid = _upsert(db, dataset["id"], "overview", None, headline, body, sheet["id"], dataset["current_version"],
                  llm.settings.model_medium if by_model else None, changed=changed)
    return emit_card(db, env.bus, dataset, cid, scope.job_id)


def _datacard(env: ws.Env, dataset: sqlite3.Row) -> dict:
    from sherlock.profile import service as profile_service

    return profile_service.get_or_build(env.settings, env.db, env.cache, dataset)


# --- edits by the user (TRD §4.6, PRD STORY-7) ------------------------------------------------------

def mark_unverified(body: dict) -> dict:
    """Numbers typed by hand become chips marked unverified ("Typed by you, not computed")."""
    out = {"blocks": []}
    n = 0
    for block in body.get("blocks", []):
        runs = []
        for run in block.get("runs", []):
            if run.get("type") != "text" or not NUMBER.search(run.get("text", "")):
                runs.append(run)
                continue
            text, pos = run["text"], 0
            for m in NUMBER.finditer(text):
                if m.start() > pos:
                    runs.append({"type": "text", "text": text[pos:m.start()]})
                n += 1
                runs.append({"type": "chip", "id": f"u{n}", "key": None, "value": m.group(0), "unverified": True})
                pos = m.end()
            if pos < len(text):
                runs.append({"type": "text", "text": text[pos:]})
        out["blocks"].append({"type": block.get("type", "paragraph"), "runs": runs})
    return out


def find_chip(card: dict, chip_id: str) -> dict | None:
    for part in (card["headline"], card["body"], *(card["suggestion"].values() if card["suggestion"] else [])):
        for block in part.get("blocks", []):
            for run in block.get("runs", []):
                if run.get("type") == "chip" and run.get("id") == chip_id:
                    return run
    return None
