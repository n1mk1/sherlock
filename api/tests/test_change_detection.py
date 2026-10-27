"""Change detection (TRD §7.5, §7.8): the gaps through which a change could miss the runs that read
it. Each test failed on the code before the fix."""

import json

from sherlock.db.connection import connect
from sherlock.db.util import new_id, now_iso
from sherlock.ml.runner import depends
from sherlock.steps.diff import Diff
from sherlock.steps.lineage import changes
from sherlock.steps.undo import undo_impact
from tests.test_jobs import TEXT_CSV, upload


def test_an_undo_counts_the_rows_it_restores_and_quarantines():
    """A3: the undo's impact said `quarantined: 0` and nothing of restored rows whatever the diff held."""
    diff = Diff(rows_in=4, rows_out=4, columns_added=[], columns_removed=[], changed_columns=[], quarantined=2,
                lineage=[(1, "_row", None, "quarantined", "quarantined"), (2, "_row", None, "quarantined", "quarantined"),
                         (3, "_row", None, "restored", None)])
    impact = undo_impact(4, 4, diff)
    assert impact["quarantined"] == 2 and impact["rows_restored"] == 1 and impact["rows_in"] == impact["rows_out"] == 4


def _step(db, ds, no, kind, to_version, *, impact=None, edits=None, undone=None):
    sid = new_id("stp")
    db.execute("INSERT INTO steps (id, dataset_id, no, kind, from_version, to_version, summary, column_targets_json, "
               "notebook_code, impact_json, edits_json, undone_step_id, created_by, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, 's', '[]', '#', ?, ?, ?, 'user', ?)",
               (sid, ds, no, kind, to_version - 1, to_version, json.dumps(impact or {}), json.dumps(edits) if edits else None,
                undone, now_iso()))
    return sid


def test_changes_see_restored_rows_and_an_undone_restore(client):
    """A3, A19: undoing an edit that restored rows quarantines them again, which affects every run;
    `changes()` read `restore_row_ids` on the step but not on the step an undo undid. A step whose impact
    counts restored rows affects every run too."""
    ds = upload(client, TEXT_CSV)["id"]
    db = connect(client.app.state.settings)
    try:
        restore = _step(db, ds, 90, "edit", 11, edits={"edits": [], "restore_row_ids": [2]})
        _step(db, ds, 91, "undo", 12, undone=restore)
        assert changes(db, ds, 11, 12) == (set(), True)
        _step(db, ds, 92, "undo", 13, impact={"rows_restored": 1})
        assert changes(db, ds, 12, 13) == (set(), True)
        _step(db, ds, 93, "edit", 14, impact={"cells_changed": 1})
        assert changes(db, ds, 13, 14) == (set(), False)
    finally:
        db.close()


def test_a_run_reads_its_selections_columns(client):
    """A5: a run on a selection read the selection's predicate columns without saying so, so editing
    one didn't outdate it."""
    ds = upload(client, TEXT_CSV)["id"]
    db = connect(client.app.state.settings)
    try:
        sel = new_id("sel")
        db.execute("INSERT INTO selections (id, dataset_id, version, predicate, row_count, created_at) "
                   "VALUES (?, ?, 1, ?, 2, ?)", (sel, ds, "city = 'Paris' OR city = 'Lyon'", now_iso()))
        row = {"target": "name", "features_json": "[]", "dataset_id": ds,
               "scope_json": json.dumps({"rows": {"predicate": None, "selection_id": sel}})}
        assert depends(row, db) == {"name", "city"}
        assert depends(row) == {"name"}  # without the database the selection can't be read
    finally:
        db.close()
