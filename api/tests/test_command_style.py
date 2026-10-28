"""Plain code for chat commands (docs/plans/chat-commands-refinements.md, R6): the style check, the one repair it
buys on the first draft, and a before/after preview that shows each kind of change before repeats. Recorded model
replies (`command_style.json`)."""

import shutil
from pathlib import Path

import duckdb
import pytest

from sherlock.agent import commands
from sherlock.config import get_settings
from sherlock.sandbox.static_check import style
from sherlock.steps.diff import BEFORE_AFTER, Diff, diff_versions
from tests.test_chat import send
from tests.test_chat_commands import API, ready  # noqa: F401  (fixture)
from tests.test_jobs import db_rows

LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture(autouse=True)
def mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    shutil.copy(LLM / "command_style.json", folder / "command_style.json")
    monkeypatch.setenv("LLM_MOCK", str(folder))
    get_settings.cache_clear()


# --- style() -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("code, word", [
    ('result = df.copy()\nfor i in result.index:\n    result.loc[i, "a"] = 1', "for loop"),
    ("result = df.copy()\nwhile False:\n    pass", "while loop"),
    ('result = df.copy()\nrows = list(result.iterrows())', "iterrows"),
    ('result = df.copy()\nrows = list(result.itertuples())', "itertuples"),
    ('result = df.copy()\nresult["c"] = result.apply(lambda r: r["a"] + r["b"], axis=1)', "axis=1"),
    ('result = df.copy()\nresult["c"] = result.apply(lambda r: r["a"], axis="columns")', "axis=1"),
])
def test_style_flags_row_loops_and_tells_the_fix(code, word):
    found = style(code)
    assert len(found) == 1 and word in found[0] and "no row loops" in found[0]


def test_style_flags_a_long_block_and_lets_clean_code_pass():
    long = "result = df.copy()\n" + "\n".join(f'result["c{i}"] = 1' for i in range(15))
    assert style(long) == ["Make it shorter: 16 lines, at most 15. Drop what the request doesn't need and use whole-column operations"]
    blanks = "result = df.copy()\n\n" + "\n\n".join(f'result["c{i}"] = 1' for i in range(14))  # 15 non-empty lines
    assert style(blanks) == []
    clean = ('result = df.copy()\nresult["name"] = result["name"].str.strip()\n'
             'result.loc[result["fare"] > 500, "fare"] = 500\n'
             'result["x"] = [v * 2 for v in result["fare"].fillna(0)]\n'  # a comprehension is fine
             'result["y"] = result["a"].apply(lambda v: v)\n')  # apply on a column is fine
    assert style(clean) == []
    assert style("def (") == []  # a syntax error is the safety check's to report


# --- the repair --------------------------------------------------------------------------------------------------

def test_a_row_loop_in_the_first_draft_is_repaired_to_whole_column_code_before_any_sandbox_run(client, ready, monkeypatch):  # noqa: F811
    ran = []
    real = commands.dry_run
    monkeypatch.setattr(commands, "dry_run", lambda *a, **k: ran.append(a[3]) or real(*a, **k))
    _, msg = send(client, ready["id"], "title-case the sex column")
    p = msg["proposal"]
    assert p["code"].endswith('result["sex"] = result["sex"].str.title()') and "iterrows" not in p["code"]
    assert p["impact"]["cells_changed"] == 1309 and p["before_after"][0]["new"] in ("Male", "Female")
    assert len(ran) == 1 and "iterrows" not in ran[0]  # the loop never reached the sandbox
    calls = db_rows("SELECT repaired FROM llm_calls WHERE dataset_id = ? AND purpose = 'step'", ready["id"])
    assert [c["repaired"] for c in calls] == [0, 1]


def test_a_second_draft_that_still_loops_still_gets_a_card(client, ready):  # noqa: F811
    _, msg = send(client, ready["id"], "lower-case the embarked column")
    p = msg["proposal"]
    assert "for col in" in p["code"] and p["code"].endswith("result[col].str.lower()")  # the second draft, loop and all
    assert p["status"] == "pending" and p["impact"]["cells_changed"] > 0
    calls = db_rows("SELECT repaired FROM llm_calls WHERE dataset_id = ? AND purpose = 'step'", ready["id"])
    assert [c["repaired"] for c in calls] == [0, 1]


# --- before_after -----------------------------------------------------------------------------------------------

def test_before_after_lists_each_distinct_pattern_once_before_any_repeat():
    lineage = [(i, "sex", "male", "Male", None) for i in range(1, 9)]            # 8 x male -> Male, rows 1-8
    lineage += [(i, "sex", "female", "Female", None) for i in range(9, 12)]       # 3 x female -> Female, rows 9-11
    lineage += [(12, "embarked", "s", "S", None), (13, "embarked", "c", "C", None)]  # 1 each, rows 12 and 13
    lineage += [(14, "_row", None, "quarantined", "quarantined")]                  # not a cell
    diff = Diff(14, 14, [], [], ["sex", "embarked"], lineage=lineage)
    got = [(c["column"], c["old"], c["new"], c["row_id"]) for c in diff.before_after]
    assert got[:4] == [("sex", "male", "Male", 1), ("sex", "female", "Female", 9),
                       ("embarked", "s", "S", 12), ("embarked", "c", "C", 13)]  # most frequent first, ties in row order
    assert [c[3] for c in got[4:]] == [2, 3, 4, 5, 6, 7, 8, 10, 11]            # then the rest in row order
    assert set(diff.before_after[0]) == {"row_id", "column", "old", "new"}


def test_before_after_is_capped_and_many_patterns_keep_the_most_frequent(tmp_path):
    conn = duckdb.connect(":memory:")  # x0..x9 twice, x10..x29 once
    for name, expr in (("o", "'x' || (i % 30)"), ("n", "'X' || (i % 30)")):
        conn.execute(f"COPY (SELECT i + 1 AS _row_id, NULL::VARCHAR AS _quarantine_reason, {expr} AS v FROM range(40) t(i)) "
                     f"TO '{(tmp_path / (name + '.parquet')).as_posix()}' (FORMAT parquet)")
    conn.close()
    diff = diff_versions(tmp_path / "o.parquet", tmp_path / "n.parquet")
    shown = diff.before_after
    assert diff.cells_changed == 40 and len(shown) == BEFORE_AFTER
    assert [c["old"] for c in shown] == [f"x{i}" for i in range(10)] + [f"x{i}" for i in range(10, 20)]
    assert len({(c["old"], c["new"]) for c in shown}) == BEFORE_AFTER
