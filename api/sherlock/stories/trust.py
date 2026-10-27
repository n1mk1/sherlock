"""The trustworthy-source rule (TRD §7.4): which story cards may feed another output.

A card is usable when it is `ready`, it and its widget aren't deleted, and its numbers hold on the
dataset's current version: its fact sheet was computed on that version, or nothing that changed since
reads a column the sheet depends on. A synthesis or answer card without a sheet of its own is usable
when every card its chips cite is. The overview, a synthesis, `ask_story` and the notebook read cards
only through this rule, and `audit` marks any `ready` card that breaks it `outdated` after a cascade,
so no stale number passes for current.
"""

import json
import logging
import sqlite3

from sherlock.db.util import now_iso

log = logging.getLogger("sherlock.stories")

WORDS = {"outdated": "outdated", "updating": "being updated", "sources_changed": "its sources changed",
         "building": "still being written", "failed": "failed"}
WIDGET_DELETED = "its widget was deleted"
CITES_STALE, CITES_UPDATING = "it cites a card that's out of date", "it cites a card that's being updated"
# Reasons that pass on their own (a card being written now); `audit` leaves them alone.
TRANSIENT = {WORDS["updating"], WORDS["building"], CITES_UPDATING, WIDGET_DELETED}


class Trust:
    """The rule for one dataset at one version, with the changes since each sheet's version memoised."""

    def __init__(self, db: sqlite3.Connection, dataset: sqlite3.Row) -> None:
        self.db, self.dataset = db, dataset
        self.version = dataset["current_version"]
        self._changes: dict[int, tuple[set[str], bool]] = {}
        self._why: dict[str, str | None] = {}

    def _changed_since(self, version: int) -> tuple[set[str], bool]:
        from sherlock.jobs.cascade import changes

        if version not in self._changes:
            self._changes[version] = changes(self.db, self.dataset["id"], version, self.version)
        return self._changes[version]

    def stale_sheet(self, sheet: dict) -> bool:
        """The sheet's numbers may not hold on the current version: it's older, and what changed since
        meets the columns it depends on (or changed everything)."""
        if sheet["version"] >= self.version:
            return False
        columns, everything = self._changed_since(sheet["version"])
        return everything or bool(columns & set(sheet["depends_columns"]))

    def why_not(self, card: sqlite3.Row) -> str | None:
        """None when the card is usable; otherwise why not, in a few words ("outdated", "written on
        version 3")."""
        if card["id"] not in self._why:
            self._why[card["id"]] = None  # a cycle of citations reads as usable here; each card is checked itself
            self._why[card["id"]] = self._reason(card)
        return self._why[card["id"]]

    def usable(self, card: sqlite3.Row) -> bool:
        return self.why_not(card) is None

    def _reason(self, card: sqlite3.Row) -> str | None:
        from sherlock.stories import service as stories

        if card["deleted_at"]:
            return "deleted"
        if card["widget_id"]:
            w = self.db.execute("SELECT deleted_at FROM widgets WHERE id = ?", (card["widget_id"],)).fetchone()
            if w is None or w["deleted_at"]:
                return WIDGET_DELETED
        if card["status"] != "ready":
            return WORDS.get(card["status"], card["status"])
        sheet = stories.get_sheet(self.db, card["fact_sheet_id"])
        if sheet is not None:
            return f"written on version {sheet['version']}" if self.stale_sheet(sheet) else None
        reason = None
        for key in cited(card):  # a synthesis or answer card stands on the cards it cites
            source = self.db.execute("SELECT * FROM cards WHERE id = ? AND dataset_id = ?",
                                     (key.partition(".")[0], self.dataset["id"])).fetchone()
            why = self.why_not(source) if source is not None else "deleted"
            if why == WIDGET_DELETED or why is None:  # a deleted widget's card still holds its numbers (Restore)
                continue
            if why in TRANSIENT:
                reason = CITES_UPDATING
            else:
                return CITES_STALE
        return reason


def cited(card: sqlite3.Row) -> list[str]:
    """The `<card_id>.<fact key>` chip keys of a card without a sheet of its own."""
    keys = []
    for part in (json.loads(card["headline_json"]), json.loads(card["body_json"])):
        for b in part.get("blocks", []):
            keys += [r["key"] for r in b["runs"] if r.get("type") == "chip" and r.get("key") and "." in r["key"]]
    return keys


def usable_cards(db: sqlite3.Connection, dataset: sqlite3.Row) -> list[sqlite3.Row]:
    """The dataset's cards that may feed another output."""
    t = Trust(db, dataset)
    rows = db.execute("SELECT * FROM cards WHERE dataset_id = ? AND deleted_at IS NULL ORDER BY created_at",
                      (dataset["id"],)).fetchall()
    return [r for r in rows if t.usable(r)]


def outdate_citing(db: sqlite3.Connection, bus, dataset: sqlite3.Row, job_id: str | None = None) -> int:
    """`ready` synthesis and answer cards without a sheet that cite a card that's out of date become
    `outdated` (Ask first marks the cards; their syntheses follow). Returns how many changed."""
    return _outdate(db, bus, dataset, job_id, "AND fact_sheet_id IS NULL")


def audit(db: sqlite3.Connection, bus, dataset: sqlite3.Row, job_id: str | None = None) -> int:
    """The invariant after a cascade: no `ready` card shows numbers that may not hold. A `ready` card
    whose sheet is older than the current version and depends on a column that changed since (or a
    synthesis or answer card citing such a card) becomes `outdated` with `card.updated`; one only being
    written now is left alone. Returns how many changed: 0 when the cascade did its job."""
    n = _outdate(db, bus, dataset, job_id, "")
    if n:
        log.warning("stories: audit marked %d ready card(s) of %s outdated", n, dataset["id"])
    return n


def _outdate(db: sqlite3.Connection, bus, dataset: sqlite3.Row, job_id: str | None, only: str) -> int:
    from sherlock.stories import service as stories

    t = Trust(db, dataset)
    rows = db.execute(f"SELECT * FROM cards WHERE dataset_id = ? AND deleted_at IS NULL AND status = 'ready' {only}",  # noqa: S608
                      (dataset["id"],)).fetchall()
    stale = [r for r in rows if (why := t.why_not(r)) and why not in TRANSIENT]
    for r in stale:
        db.execute("UPDATE cards SET status = 'outdated', updated_at = ? WHERE id = ? AND status = 'ready'", (now_iso(), r["id"]))
        stories.emit_card(db, bus, dataset, r["id"], job_id)
    if stale:
        db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (dataset["id"],))
    return len(stale)
