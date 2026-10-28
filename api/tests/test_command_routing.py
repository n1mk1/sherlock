"""Which messages become cleaning commands (docs/plans/chat-commands-refinements.md R1). A command phrasing the model
routes to something else (`ask_data`, `ask_code`, `find_rows`) is sent to `clean_step` by the router guards in
`agent/loop.py`; one the model routes right stays there; a question, a chart or a how-to never reaches the step
writer. Recorded model replies: `command_routing.json`, the same phrasings as `samples/eval/commands.yaml`."""

import json
import shutil
from pathlib import Path

import pytest

from sherlock.agent import loop
from sherlock.config import get_settings
from tests.test_chat import send
from tests.test_jobs import db_rows, wait_status

API = "/api/v1"
LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")

def text(entry: dict) -> str:
    """The message a recorded route answers: `<data>\n<message>\n</data>`."""
    return entry["match"][0].removeprefix("<data>\n").removesuffix("\n</data>")


# Near misses: none of these may be sent to the step writer, whatever the model says.
NEAR_MISSES = ["make a chart of fare by class", "how do I trim spaces?", "which names have extra spaces?",
               "what would happen if I rounded fare?", "show me the passengers with no age",
               "how many passengers have a missing age?", "plot the age distribution", "make a chart of revenue by region",
               "how do I delete rows?", "which orders were returned?", "what would happen if I upper-cased the region column?",
               "can you explain how to fill blanks with the median?"]
# (message, what the recorded router says; the guards must make it clean_step): every recorded route that isn't a near miss
COMMANDS = [(text(e), e["content"]["intents"][0])
            for e in json.loads((LLM / "command_routing.json").read_text(encoding="utf-8")) if e["purpose"] == "route"
            and text(e) not in NEAR_MISSES]


@pytest.fixture(autouse=True)
def mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    shutil.copy(LLM / "command_routing.json", folder / "command_routing.json")
    monkeypatch.setenv("LLM_MOCK", str(folder))
    get_settings.cache_clear()


@pytest.fixture
def ready(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    wait_status(client, ds["id"], "ready")
    return ds


def purposes(ds_id: str) -> list[str]:
    return [c["purpose"] for c in db_rows("SELECT purpose FROM llm_calls WHERE dataset_id = ? AND message_id IS NOT NULL "
                                          "ORDER BY rowid", ds_id)]


def test_the_recorded_phrasings_cover_every_kind_of_wording():
    said = {s for _, s in COMMANDS}
    assert len(COMMANDS) >= 18 and {"ask_data", "ask_code", "find_rows", "clean_step"} <= said


@pytest.mark.parametrize("message,routed", COMMANDS, ids=[m for m, _ in COMMANDS])
def test_a_command_in_any_wording_becomes_a_card(client, ready, message, routed):
    events, msg = send(client, ready["id"], message)
    assert purposes(ready["id"]) == ["route", "step"], (routed, [c for c in purposes(ready["id"])])
    p = msg["proposal"]
    assert p["status"] == "pending" and p["kind"] in ("clean_step", "computed_column")
    assert any(e == "proposal" for e, _ in events) and "press OK" in msg["text"]


@pytest.mark.parametrize("message", NEAR_MISSES)
def test_a_near_miss_is_not_a_command_to_the_router_guards(message):
    assert not loop.COMMAND.search(message) and not loop.DELETE_ASK.search(message)


@pytest.mark.parametrize("message", ["what would happen if I rounded fare?", "What if I upper-cased the region column?",
                                     "what will change if I trim the names?"])
def test_a_what_if_is_never_a_command(message):
    assert loop.WHAT_IF.search(message)


@pytest.mark.parametrize("message,routed", [("make a chart of fare by class", "ask_data"), ("how do I trim spaces?", "ask_history"),
                                            ("how do I delete rows?", "ask_model")])
def test_a_chart_or_a_how_to_gets_no_card_and_no_step_call(client, ready, message, routed):
    _, msg = send(client, ready["id"], message)
    assert "proposal" not in msg and "step" not in purposes(ready["id"])
    assert msg["text"]
