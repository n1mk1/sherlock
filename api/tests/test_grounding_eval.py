"""The grounding eval (Implementation Plan D8.4) on the sample with recorded model replies: every chip
shows its fact, every cited fact holds, no text run carries a number; and a planted bad chip is caught."""

import shutil
from pathlib import Path

import pytest

from sherlock.config import get_settings
from sherlock.eval import grounding

LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture
def mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    for name in ("stories_titanic.json", "flow_titanic.json"):
        shutil.copy(LLM / name, folder / name)
    monkeypatch.setenv("LLM_MOCK", str(folder))
    get_settings.cache_clear()


def test_the_sample_is_grounded_and_a_bad_chip_is_caught(mocked, client):
    [t] = grounding.evaluate(client, ["titanic3.csv"])
    assert t.cards >= 8 and t.chips > 10
    assert t.chips_ok == t.chips and t.facts_stale == 0 and t.text_with_numbers == 0 and t.causal == 0, t.problems
    assert t.synthesis in ("by the model", "fallback bullets")
    # Plan 1.3's stale-reuse scenario: nothing that isn't usable passes for current.
    s = t.stale
    assert s and not s.problems, s and s.problems
    assert s.synthesis_after_delete == "sources_changed" and s.overview == "outdated" and s.outdated_cards >= 1
    assert s.audited == 0 and s.notebook_notes >= s.notes_expected > 0
    table = grounding.report([t])
    assert "| titanic3.csv |" in table and "No problems found." in table and "Stale reuse" in table

    bad = grounding.Tally("x")
    card = {"headline": {"blocks": [{"type": "paragraph", "runs": [{"type": "text", "text": "It rose by 12 points."}]}]},
            "body": {"blocks": [{"type": "paragraph", "runs": [{"type": "chip", "id": "c0", "key": "nope", "value": "1.0"}]}]},
            "facts": {}, "fact_sheet_id": None}
    grounding.check_card(None, None, get_settings(), None, card, bad, "planted")
    assert bad.chips == 1 and bad.chips_ok == 0 and bad.text_with_numbers == 1 and len(bad.problems) == 2
