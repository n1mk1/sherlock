"""The notebook and the report carry the sources (docs/plans/tavily.md §3.5): the "What the columns mean" cell after
the load, a step's cell that cites the page its check came from, and the report's `sources`, each page once. Nothing
here reaches the web: the cells and the report are written from the stored notes and the steps' evidence."""

import nbformat
import pytest

from sherlock.agent import web as aw
from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.notebook import cells
from sherlock.sandbox import runner as sandbox
from sherlock.steps.commit import Context, StepSpec, commit_step
from tests.test_jobs import wait_status
from tests.test_notebook import API, CLEAN_CODE, _export

NOTES = [
    {"column": "pclass", "kind": "web", "description": "Passenger class from the web.", "excerpt": None,
     "source_url": "https://web.example.org/p", "source_title": "Web page", "retrieved_at": "2026-10-26"},
    {"column": "pclass", "kind": "dictionary", "description": "Ticket class: first, second or third.",
     "excerpt": "pclass: 1 = first, 2 = second, 3 = third", "source_url": "https://codebook.example.org/vars",
     "source_title": "Codebook", "retrieved_at": "2026-10-27"},
    {"column": "embarked", "kind": "found", "description": "The port of embarkation.", "excerpt": "embarked: C, Q, S",
     "source_url": "https://found.example.org/t", "source_title": None, "retrieved_at": "2026-10-28T09:00:00.000Z"},
    {"column": "fare", "kind": "web", "description": "What the passenger paid.", "excerpt": "Fare in pounds",
     "source_url": "https://web.example.org/f", "source_title": "Fares", "retrieved_at": "2026-10-26"},
    {"column": "age", "kind": "web", "description": "Age in years.", "excerpt": None,
     "source_url": "https://web.example.org/a", "source_title": "Ages", "retrieved_at": "2026-10-26"},
]
EVIDENCE = {"url": "https://codebook.example.org/vars", "title": "Codebook", "excerpt": "embarked: C, Q or S",
            "retrieved_at": "2026-10-27"}


def _step(decisions: list[dict]) -> dict:
    """A committed cleaning step in the shape `notebook.cells.step` reads."""
    return {"no": 1, "kind": "clean", "created_by": "cleaner", "summary": "Checked embarked", "gate": "commit",
            "confidence": 0.9, "impact": {"rows_in": 3, "rows_out": 3, "cells_changed": 1}, "flag_reason": None,
            "decisions": decisions, "code": None, "notebook_code": "df = df\n"}


def test_markdown_escaping_shows_a_page_as_written_and_keeps_a_quote_on_one_line():
    assert cells.md_text("a_b *c* [d](e) &f; <g> $h$ \\ `i` | ~j~ # k") == (
        "a\\_b \\*c\\* \\[d\\](e) \\&f; \\<g\\> \\$h\\$ \\\\ \\`i\\` \\| \\~j\\~ \\# k")
    assert cells.md_text("one\n   two") == "one two"
    assert cells.md_text(None) == ""


def test_a_column_takes_its_first_kind_and_the_bullets_follow_the_file():
    [cell] = cells.column_notes(NOTES, ["fare", "age", "embarked", "pclass"])
    assert cell.cell_type == "markdown" and cell.source.startswith("## What the columns mean")
    lines = cell.source.splitlines()
    bullets = [ln for ln in lines if ln.startswith("- ")]
    assert [b.split("**")[1] for b in bullets] == ["pclass", "embarked", "fare", "age"]
    assert "Passenger class from the web." not in cell.source  # the dictionary the user linked wins pclass
    assert [ln for ln in lines if ln.startswith("*")] == [
        "*From the data dictionary you linked:*", "*From a data dictionary Sherlock found:*", "*From the web:*"]
    assert bullets[0] == ("- **pclass**: Ticket class: first, second or third. — “pclass: 1 = first, 2 = second, 3 = third” "
                          "(Codebook, https://codebook.example.org/vars, read 2026-10-27)")
    assert bullets[1] == "- **embarked**: The port of embarkation. — “embarked: C, Q, S” (https://found.example.org/t, read 2026-10-28)"


def test_web_text_is_escaped_in_the_bullet():
    note = {"column": "tax_rate", "kind": "web", "description": "Rate *as a share* of [net] income.",
            "excerpt": "tax_rate: 5%\nsee &frac34; and $x$", "source_url": "https://ex.org/a_b?x=1&y=2",
            "source_title": "Tax *guide*", "retrieved_at": "2026-10-27"}
    text = cells.column_notes([note], ["tax_rate"])[0].source
    assert [ln for ln in text.splitlines() if ln.startswith("- ")] == [
        "- **tax\\_rate**: Rate \\*as a share\\* of \\[net\\] income. — “tax\\_rate: 5% see \\&frac34; and \\$x\\$” "
        "(Tax \\*guide\\*, https://ex.org/a\\_b?x=1\\&y=2, read 2026-10-27)"]


def test_no_notes_means_no_cell():
    assert cells.column_notes([], ["pclass"]) == []


def test_a_check_taken_from_a_page_cites_it_once_and_a_check_without_one_does_not():
    decisions = [{"question": "Embarked?", "chosen": "Kept C, Q and S", "evidence": EVIDENCE},
                 {"question": "Fare?", "chosen": "Kept", "evidence": EVIDENCE},  # the same quote: shown once
                 {"question": "Age?", "chosen": "Kept"}]
    md = cells.step(_step(decisions))[0].source
    assert md.count("Checked against:") == 1
    assert "Checked against: Codebook (https://codebook.example.org/vars), read 2026-10-27: “embarked: C, Q or S”" in md
    assert "Checked against" not in cells.step(_step([{"question": "Age?", "chosen": "Kept"}]))[0].source


def _sample(client) -> str:
    ds = client.post(f"{API}/datasets/sample").json()["id"]
    wait_status(client, ds, "offer")
    client.post(f"{API}/datasets/{ds}/use-as-is")
    return ds


def _notebook(client, ds):
    out = _export(client, ds, include_data=False)
    return nbformat.reads(client.get(out["download_url"]).text, as_version=4)


def _save(ds: str, column: str, kind: str, description: str, excerpt: str | None, url: str, title: str | None, day: str):
    db = connect(get_settings())
    try:
        aw.save_note(db, ds, column, kind, description, excerpt, url, title, day)
    finally:
        db.close()


def _commit(app, ds: str, version: int, decisions: list[dict], job_id: str | None = None) -> int:
    """A cleaning step committed the way the Cleaner commits one, carrying its checks' decisions (as the notebook
    tests' `clean_step` does)."""
    settings = get_settings()
    db = connect(settings)
    try:
        def produce(old, out):
            r = sandbox.execute(settings, CLEAN_CODE, old, out)
            assert r.ok, r.error
        spec = StepSpec(kind="clean", summary="Checked embarked against the codebook", created_by="cleaner", code=CLEAN_CODE,
                        notebook_code=CLEAN_CODE + "\ndf = result\n", gate="commit", confidence=0.9,
                        helpers_used=["fill_by_group", "normalize_whitespace_case", "quarantine_rows"],
                        decisions=decisions, job_id=job_id)
        _, new = commit_step(Context(settings, db, app.state.duckdb), ds, version, spec, produce)
        return new
    finally:
        db.close()


@pytest.mark.usefixtures("run_jobs")
def test_the_notes_cell_comes_after_the_load_and_holds_each_note(client):
    ds = _sample(client)
    url = "https://codebook.example.org/vars"
    _save(ds, "pclass", "dictionary", "Ticket class, first to third.", "pclass: 1 = first", url, "Codebook", "2026-10-27")
    _save(ds, "sex", "found", "Passenger's sex.", None, "https://found.example.org/sex", None, "2026-10-28")
    _save(ds, "fare", "web", "What the passenger paid.", "Fare in pounds", "https://web.example.org/fare", "Fares", "2026-10-26")
    nb = _notebook(client, ds)
    load = next(i for i, c in enumerate(nb.cells) if "load" in c.get("metadata", {}).get("tags", []))
    notes = nb.cells[load + 1]
    assert notes.cell_type == "markdown" and notes.source.startswith("## What the columns mean")
    text = notes.source
    assert ("- **pclass**: Ticket class, first to third. — “pclass: 1 = first” "
            "(Codebook, https://codebook.example.org/vars, read 2026-10-27)") in text
    assert "- **sex**: Passenger's sex. (https://found.example.org/sex, read 2026-10-28)" in text
    assert ("- **fare**: What the passenger paid. — “Fare in pounds” "
            "(Fares, https://web.example.org/fare, read 2026-10-26)") in text
    assert (text.index("*From the data dictionary you linked:*") < text.index("*From a data dictionary Sherlock found:*")
            < text.index("*From the web:*"))
    assert sum("What the columns mean" in c.source for c in nb.cells) == 1


@pytest.mark.usefixtures("run_jobs")
def test_a_note_saved_after_an_export_is_in_the_next_one(client):
    """A new note bumps `state_rev`, so the cached export of the same version isn't served again."""
    ds = _sample(client)
    assert not any("What the columns mean" in c.source for c in _notebook(client, ds).cells)
    _save(ds, "pclass", "found", "Ticket class.", "pclass: 1 = first", "https://found.example.org/p", "Found", "2026-10-28")
    out = _export(client, ds, include_data=False)
    assert not out["cached"]
    nb = nbformat.reads(client.get(out["download_url"]).text, as_version=4)
    assert any("What the columns mean" in c.source for c in nb.cells)


def test_a_secret_looking_quote_is_redacted_and_never_blocks_the_export():
    """Web text can't fail the export's secret scan: what looks like a token in a quote is redacted, and the
    exact configured keys are still refused anywhere in the file."""
    from sherlock.notebook import scan

    note = {"column": "auth", "kind": "web", "description": "The Bearer abcdefghijklmnop header.",
            "excerpt": "send Authorization: Bearer abcdefghijklmnop or sk-ABCDEFGHIJKLMNOPQRST", "source_url": "https://ex.org/a",
            "source_title": "sk-ABCDEFGHIJKLMNOPQRST", "retrieved_at": "2026-10-27"}
    evidence = {**EVIDENCE, "excerpt": "token: Bearer abcdefghijklmnop", "title": "Bearer abcdefghijklmnop"}
    nb = nbformat.v4.new_notebook()
    nb.cells = cells.column_notes([note], ["auth"]) + cells.step(_step([{"question": "Auth?", "chosen": "Kept",
                                                                        "evidence": evidence}]))
    scan.scan(nb, secrets=[])
    text = "\n".join(c.source for c in nb.cells)
    assert "abcdefghijklmnop" not in text and "ABCDEFGHIJKLMNOPQRST" not in text and "\\[redacted\\]" in text
    key = "v1.real-configured-key-value"
    leaked = cells.column_notes([{**note, "excerpt": f"the key is {key}"}], ["auth"])
    nb.cells = leaked
    with pytest.raises(scan.ScanError, match="API key"):
        scan.scan(nb, secrets=[key])


@pytest.mark.usefixtures("run_jobs")
def test_no_notes_means_no_notes_cell(client):
    ds = _sample(client)
    nb = _notebook(client, ds)
    assert not any("What the columns mean" in c.source for c in nb.cells)


@pytest.mark.usefixtures("run_jobs")
def test_a_step_whose_check_came_from_a_page_cites_it(client):
    ds = _sample(client)
    version = client.get(f"{API}/datasets/{ds}").json()["current_version"]
    decisions = [{"question": "Embarked must be C, Q or S?", "chosen": "Kept C, Q and S", "reason": "The codebook lists them",
                  "evidence": EVIDENCE}]
    _commit(client.app, ds, version, decisions)
    nb = _notebook(client, ds)
    [step] = [c.source for c in nb.cells if c.cell_type == "markdown" and "Checked against" in c.source]
    assert step.startswith("### Step ") and "Checked embarked against the codebook" in step
    assert "Checked against: Codebook (https://codebook.example.org/vars), read 2026-10-27: “embarked: C, Q or S”" in step


@pytest.mark.usefixtures("run_jobs")
def test_the_report_lists_each_source_once_with_the_notes_first(client):
    ds = _sample(client)
    version = client.get(f"{API}/datasets/{ds}").json()["current_version"]
    url_a, url_b, url_c = "https://codebook.example.org/vars", "https://found.example.org/sex", "https://other.example.org/c"
    db = connect(get_settings())
    try:
        user_id = db.execute("SELECT user_id FROM datasets WHERE id = ?", (ds,)).fetchone()[0]
        db.execute("INSERT INTO jobs (id, dataset_id, user_id, kind, status, created_at, finished_at) "
                   "VALUES ('job_sources', ?, ?, 'clean', 'done', '2026-10-28T10:00:00.000Z', '2026-10-28T10:01:00.000Z')",
                   (ds, user_id))
    finally:
        db.close()
    _save(ds, "pclass", "dictionary", "Ticket class.", "pclass: 1 = first", url_a, "Codebook", "2026-10-27")
    _save(ds, "embarked", "web", "The port.", None, url_a, "Codebook", "2026-10-27")
    _save(ds, "sex", "found", "Sex.", None, url_b, "Found dictionary", "2026-10-26")
    decisions = [
        {"question": "Embarked?", "chosen": "Kept", "evidence": {"url": url_a, "title": "Codebook", "excerpt": "C, Q or S",
                                                                "retrieved_at": "2026-10-27"}},
        {"question": "Age?", "chosen": "Kept", "evidence": {"url": url_c, "title": "Other", "excerpt": "0 to 120",
                                                           "retrieved_at": "2026-10-28T10:00:00.000Z"}},
        {"question": "Fare?", "chosen": "Kept", "evidence": {"url": url_c, "title": "Other", "excerpt": "fares",
                                                           "retrieved_at": "2026-10-28T10:00:00.000Z"}},
        {"question": "Name?", "chosen": "Kept"},
    ]
    _commit(client.app, ds, version, decisions, job_id="job_sources")
    report = client.get(f"{API}/datasets/{ds}/report", params={"job_id": "job_sources"}).json()
    assert report["sources"] == [
        {"url": url_a, "title": "Codebook", "retrieved_at": "2026-10-27"},
        {"url": url_b, "title": "Found dictionary", "retrieved_at": "2026-10-26"},
        {"url": url_c, "title": "Other", "retrieved_at": "2026-10-28"},
    ]
