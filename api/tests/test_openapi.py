"""The committed OpenAPI schema matches the app (TRD §3.1, Day 2 review). The web client's types are
generated from `web/src/api/openapi.json`, so a route added without regenerating it would be untyped.
To fix a failure: `uv run --project api python scripts/dump_openapi.py`, then `pnpm openapi` in `web/`."""

import json
from pathlib import Path

from sherlock.main import create_app

COMMITTED = Path(__file__).resolve().parents[2] / "web" / "src" / "api" / "openapi.json"


def test_committed_openapi_matches_the_app():
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    live = json.loads(json.dumps(create_app().openapi()))
    missing = sorted(set(live["paths"]) - set(committed["paths"]))
    stale = sorted(set(committed["paths"]) - set(live["paths"]))
    assert not missing and not stale, f"regenerate openapi.json: missing {missing}, stale {stale}"
    assert live == committed, "openapi.json differs from the app's schema: regenerate it"
