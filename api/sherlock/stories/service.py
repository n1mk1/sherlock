"""Story cards (TRD §4.6, §7.4): fact sheets, relations, narration and the cards themselves.

`tell()` is the pipeline the `stories` job and the cascade share: for each widget, compute and store
its fact sheet on the current version, verify it, narrate it (in parallel, four at a time) and store
the card, emitting `card.updated` as each one is ready; then the overview. With cut 6 applied there
is no material-change check: every affected card is narrated again. A card the user edited keeps its
text and gets the new narration as a suggestion; with "Story updates: Ask first", a cascade marks
cards outdated instead of narrating them.

Every card write is conditional on the version it was told on still being the dataset's current
version (`_upsert`, `_set_status`): a tell that a newer version overtook writes nothing, and the
newer version's cascade (which waits for it, `runner.SERIAL_KINDS`) tells the cards again.
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
# A number a user types: digits, or one spelled out ("zero", "twice": the narrator's list). Not Roman
# numerals: in a user's sentence "XL" is more often a size than forty.
TYPED = re.compile(f"{NUMBER.pattern}|{nr.NUMBER_WORDS.pattern}", re.I)


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
        # An analysis widget tells its run's facts (from the model card, TRD §7.5 step 10).
        run = env.db.execute("SELECT fact_sheet_id FROM runs WHERE id = ? AND status IN ('done', 'outdated')",
                             (widget["run_id"],)).fetchone() if widget["run_id"] else None
        sheet = get_sheet(env.db, run["fact_sheet_id"]) if run else None
        if sheet is None:
            return _store_sheet(env.db, dataset["id"], widget["id"], version, {}, [])
        return _store_sheet(env.db, dataset["id"], widget["id"], version, sheet["facts"], sheet["depends_columns"])
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
    if sheet:
        facts = {k: {"formatted": f["formatted"], "label": f["label"]} for k, f in sheet["facts"].items()}
    else:  # a synthesis or answer card cites its sources' facts as `<card_id>.<fact key>`
        facts = {}
        for part in (json.loads(r["headline_json"]), json.loads(r["body_json"])):
            for run in (run for b in part.get("blocks", []) for run in b["runs"]):
                if run["type"] == "chip" and run.get("key") and "." in run["key"]:
                    f = fact_for(db, r["dataset_id"], run["key"])
                    if f:
                        facts[run["key"]] = {"formatted": f["formatted"], "label": f["label"]}
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
        "facts": facts,
        "related": related,
    }


def fact_for(db: sqlite3.Connection, dataset_id: str, key: str) -> dict | None:
    """The fact a `<card_id>.<fact key>` chip names, from that card's current fact sheet."""
    cid, _, fkey = key.partition(".")
    r = db.execute("SELECT fact_sheet_id FROM cards WHERE id = ? AND dataset_id = ?", (cid, dataset_id)).fetchone()
    sheet = get_sheet(db, r["fact_sheet_id"]) if r else None
    return sheet["facts"].get(fkey) if sheet else None


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


# A write guard: the version a card was told on is still the dataset's current version.
CURRENT = "? = (SELECT current_version FROM datasets WHERE id = ?)"


def _upsert(db, dataset_id: str, kind: str, widget_id: str | None, headline: dict, body: dict, sheet_id: str,
            version: int, narrated_by: str | None, changed: bool) -> str | None:
    """Store a told card; None (nothing written) when `version` is no longer the current one."""
    now = now_iso()
    q = ("SELECT * FROM cards WHERE dataset_id = ? AND kind = 'overview' AND deleted_at IS NULL" if kind == "overview"
         else "SELECT * FROM cards WHERE dataset_id = ? AND widget_id = ? AND deleted_at IS NULL")
    existing = db.execute(q, (dataset_id,) if kind == "overview" else (dataset_id, widget_id)).fetchone()
    if existing is None:
        card_id = new_id("crd")
        cur = db.execute(
            "INSERT INTO cards (id, dataset_id, kind, widget_id, headline_json, body_json, fact_sheet_id, status, version, "
            "narrated_by, verified_at, created_at, updated_at) "
            f"SELECT ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ? WHERE {CURRENT}",
            (card_id, dataset_id, kind, widget_id, json.dumps(headline), json.dumps(body), sheet_id, version, narrated_by,
             now, now, now, version, dataset_id))
        return card_id if cur.rowcount else None
    if existing["edited_by_user"]:
        cur = db.execute("UPDATE cards SET suggestion_json = ?, fact_sheet_id = ?, changed_badge = ?, status = 'ready', "
                         f"updated_at = ? WHERE id = ? AND {CURRENT}",
                         (json.dumps({"headline": headline, "body": body}), sheet_id, int(changed), now, existing["id"],
                          version, dataset_id))
    else:
        cur = db.execute("UPDATE cards SET headline_json = ?, body_json = ?, fact_sheet_id = ?, status = 'ready', version = ?, "
                         f"narrated_by = ?, verified_at = ?, changed_badge = ?, updated_at = ? WHERE id = ? AND {CURRENT}",
                         (json.dumps(headline), json.dumps(body), sheet_id, version, narrated_by, now,
                          int(changed or existing["changed_badge"]), now, existing["id"], version, dataset_id))
    return existing["id"] if cur.rowcount else None


def _set_status(db, dataset_id: str, widget_id: str, status: str, version: int) -> str | None:
    """A widget card's status, when `version` is still the current one; its id if it was written.
    `outdated` is always written: it's true of any card whatever version it was told on."""
    r = db.execute("SELECT id FROM cards WHERE dataset_id = ? AND widget_id = ? AND deleted_at IS NULL",
                   (dataset_id, widget_id)).fetchone()
    if r:
        guard = "" if status == "outdated" else f" AND {CURRENT}"
        cur = db.execute(f"UPDATE cards SET status = ?, updated_at = ? WHERE id = ?{guard}",
                         (status, now_iso(), r["id"], *((version, dataset_id) if guard else ())))
        return r["id"] if cur.rowcount else None
    return None


def settle_updating(db: sqlite3.Connection, bus, dataset_id: str, job_id: str | None = None,
                    widget_ids: list[str] | None = None) -> int:
    """Cards a failed or cancelled job left `updating` become `outdated`, so they offer Refresh instead of
    spinning (the cascade's and the stories job's failure hooks). `widget_ids`: only those widgets' cards.
    An analysis card whose run is still queued or running stays `updating`: the run's story tells it, or
    the run's own failure hook marks it outdated. Returns how many changed."""
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if dataset is None:
        return 0
    changed = 0
    for r in db.execute(
            "SELECT c.id, c.widget_id FROM cards c WHERE c.dataset_id = ? AND c.deleted_at IS NULL AND c.status = 'updating' "
            "AND NOT EXISTS (SELECT 1 FROM widgets w JOIN runs r ON r.id = w.run_id WHERE w.id = c.widget_id "
            "AND r.status IN ('queued', 'running'))", (dataset_id,)).fetchall():
        if widget_ids is not None and r["widget_id"] not in widget_ids:
            continue
        db.execute("UPDATE cards SET status = 'outdated', updated_at = ? WHERE id = ?", (now_iso(), r["id"]))
        emit_card(db, bus, dataset, r["id"], job_id)
        changed += 1
    if changed:
        _bump(db, dataset_id)
    return changed


def mark_widget_card(db: sqlite3.Connection, bus, dataset: sqlite3.Row, widget_id: str, status: str,
                     job_id: str | None = None) -> str | None:
    """Set a widget's card's status and emit `card.updated`: an analysis card goes `updating` when its run
    relaunches and `outdated` when the run fails or is cancelled."""
    cid = _set_status(db, dataset["id"], widget_id, status, dataset["current_version"])
    if cid:
        emit_card(db, bus, dataset, cid, job_id)
        _bump(db, dataset["id"])
    return cid


def tell(env: ws.Env, llm: LLMClient, scope: CallScope, dataset: sqlite3.Row, widget_ids: list[str] | None, *,
         reason: str, ask_first: bool = False, progress=lambda *_: None, check_cancel=lambda: None,
         on_told=lambda _widget_id: None) -> dict:
    """Fact sheets and cards for the widgets (all when None), then the overview. `reason` is
    "build" (a new dashboard), "widget" (one added or changed), "cascade" or "refresh"."""
    db = env.db
    version = dataset["current_version"]
    rows = db.execute("SELECT * FROM widgets WHERE dataset_id = ? AND deleted_at IS NULL ORDER BY order_no",
                      (dataset["id"],)).fetchall()
    chosen = [r for r in rows if (widget_ids is None or r["id"] in widget_ids) and not _waiting_for_run(db, r)]
    card = _datacard(env, dataset)
    dataset_columns = [c["name"] for c in card["columns"]]
    target = (card.get("target_candidates") or [None])[0]

    if reason == "cascade" and ask_first:
        marked = []
        for w in chosen:
            cid = _set_status(db, dataset["id"], w["id"], "outdated", version)
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
        cid = _set_status(db, dataset["id"], w["id"], "updating", version)
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
    overtaken: set[str] = set()  # cards a newer version made stale while they were being told
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
            if cid is None:  # a newer version came in while it was told: nothing written (below)
                overtaken.add(w["id"])
                continue
            emit_card(db, env.bus, dataset, cid, scope.job_id)
            on_told(w["id"])  # the stories job's checkpoint (D8.6)
            done += 1
    told = {w["id"] for w, _, _ in jobs} - overtaken
    for w in chosen:  # never leave a card spinning: a failed query asks for Refresh, no facts keeps the text
        if w["id"] in overtaken:
            # Its numbers are for a version that's gone: outdated, which the newer version's cascade tells again.
            cid = _set_status(db, dataset["id"], w["id"], "outdated", version)
        elif w["id"] not in told:
            cid = _set_status(db, dataset["id"], w["id"], "outdated" if w["id"] in failed else "ready", version)
        else:
            continue
        if cid:
            emit_card(db, env.bus, dataset, cid, scope.job_id)
    progress(len(chosen) + 1, len(chosen) + 1, "Writing the overview")
    tell_overview(env, llm, scope, dataset, rows, dataset_columns, changed=reason == "cascade")
    from sherlock.stories import synthesis  # a synthesis citing a number that moved says so

    synthesis.check_sources(db, env.bus, dataset, scope.job_id)
    _bump(db, dataset["id"])
    return {"cards": done, "widgets": len(chosen), "overtaken": sorted(overtaken)}


def _waiting_for_run(db: sqlite3.Connection, widget: sqlite3.Row) -> bool:
    """An analysis widget without a finished run has nothing to tell yet; its run's completion queues
    its story."""
    if json.loads(widget["spec_json"])["op"]["type"] != "ml":
        return False
    run = db.execute("SELECT status FROM runs WHERE id = ?", (widget["run_id"],)).fetchone() if widget["run_id"] else None
    return run is None or run["status"] not in ("done", "outdated")


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
                            "widget_id": w["id"], "spec": json.loads(w["spec_json"]), "columns": sheet["depends_columns"]})
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
    return emit_card(db, env.bus, dataset, cid, scope.job_id) if cid else None


def _datacard(env: ws.Env, dataset: sqlite3.Row) -> dict:
    from sherlock.profile import service as profile_service

    return profile_service.get_or_build(env.settings, env.db, env.cache, dataset)


# --- edits by the user (TRD §4.6, PRD STORY-7) ------------------------------------------------------

def mark_unverified(body: dict) -> dict:
    """Numbers typed by hand, in digits or in words, become chips marked unverified ("Typed by you,
    not computed")."""
    out = {"blocks": []}
    n = 0
    for block in body.get("blocks", []):
        runs = []
        for run in block.get("runs", []):
            if run.get("type") != "text" or not TYPED.search(run.get("text", "")):
                runs.append(run)
                continue
            text, pos = run["text"], 0
            for m in TYPED.finditer(text):
                if m.start() > pos:
                    runs.append({"type": "text", "text": text[pos:m.start()]})
                n += 1
                runs.append({"type": "chip", "id": f"u{n}", "key": None, "value": m.group(0), "unverified": True})
                pos = m.end()
            if pos < len(text):
                runs.append({"type": "text", "text": text[pos:]})
        out["blocks"].append({"type": block.get("type", "paragraph"), "runs": runs})
    return out


def checked_edit(db: sqlite3.Connection, r: sqlite3.Row, body: dict) -> dict:
    """A user's edit of card `r` with nothing taken on trust from the browser (Day 6 review F3): a chip
    shows its fact's value from the card's sheet (or, on a synthesis or answer card, its source card's
    sheet), and a chip whose fact isn't there is marked unverified. A label is kept only when the card
    already had it or it names a column of the file; otherwise its text is the user's text, and a
    number in it becomes an unverified chip (`mark_unverified`)."""
    sheet = get_sheet(db, r["fact_sheet_id"])
    parts = [json.loads(r["headline_json"]), json.loads(r["body_json"])]
    if r["suggestion_json"]:
        parts += list(json.loads(r["suggestion_json"]).values())
    had = {(run.get("ref"), run.get("text")) for p in parts for b in p.get("blocks", []) for run in b.get("runs", [])
           if run.get("type") == "label"}
    v = db.execute("SELECT columns_json FROM versions v JOIN datasets d ON d.id = v.dataset_id AND v.version = d.current_version "
                   "WHERE d.id = ?", (r["dataset_id"],)).fetchone()
    columns = {c["name"] for c in json.loads(v["columns_json"])} if v else set()
    out = {"blocks": []}
    for n, block in enumerate(b for b in body.get("blocks") or [] if isinstance(b, dict)):
        runs = []
        for k, run in enumerate(x for x in block.get("runs") or [] if isinstance(x, dict)):
            kind = run.get("type")
            if kind == "chip":
                cid = run.get("id") if isinstance(run.get("id"), str) else f"e{n}_{k}"
                key = run.get("key") if isinstance(run.get("key"), str) else None
                f = None
                if key and not run.get("unverified"):
                    f = (sheet or {}).get("facts", {}).get(key) if sheet else (fact_for(db, r["dataset_id"], key) if "." in key else None)
                if f is not None:
                    runs.append({"type": "chip", "id": cid, "key": key, "value": f["formatted"], "unverified": False})
                else:
                    runs.append({"type": "chip", "id": cid, "key": None, "value": str(run.get("value") or ""), "unverified": True})
            elif kind == "label":
                ref, text = str(run.get("ref") or ""), str(run.get("text") or "")
                if (ref, text) in had or (ref.startswith("column:") and ref[7:] in columns and text == ref[7:]):
                    runs.append({"type": "label", "ref": ref, "text": text})
                elif text:
                    runs.append({"type": "text", "text": text})
            elif kind == "text" and isinstance(run.get("text"), str):
                runs.append({"type": "text", "text": run["text"]})
        out["blocks"].append({"type": block["type"] if block.get("type") in ("paragraph", "bullets") else "paragraph", "runs": runs})
    return mark_unverified(out)


def find_chip(card: dict, chip_id: str) -> dict | None:
    for part in (card["headline"], card["body"], *(card["suggestion"].values() if card["suggestion"] else [])):
        for block in part.get("blocks", []):
            for run in block.get("runs", []):
                if run.get("type") == "chip" and run.get("id") == chip_id:
                    return run
    return None
