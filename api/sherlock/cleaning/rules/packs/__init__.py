"""Shipped rule packs (PRD CLEAN-13, TRD §7.1 step 4): rules as data in `packs/*.json`, generic by
construction (Rule 4): a pack names columns by whole words of their name and by type, never by one
file's columns. A pack with `"run_by": "rule"` is run by the rule detector on every dataset;
`plausible_values.json` is read by the impossible_values detector instead.
"""

import json
import re
from functools import cache
from pathlib import Path

from sherlock.cleaning.rules.kinds import KINDS

HERE = Path(__file__).parent
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def name_words(name: str) -> set[str]:
    """The whole words of a column name, split at anything but letters and digits and at camelCase, each
    also without a final "s"."""
    words = {w.lower() for w in re.split(r"[^0-9A-Za-z]+", CAMEL.sub(" ", name)) if w}
    return words | {w[:-1] for w in words if w.endswith("s")}


@cache
def packs() -> tuple[dict, ...]:
    """The shipped packs the rule detector runs, checked once: known kinds and actions, a match by words."""
    out = []
    for f in sorted(HERE.glob("*.json")):
        pack = json.loads(f.read_text(encoding="utf-8"))
        if pack.get("run_by") != "rule":
            continue
        for rule in pack["rules"]:
            assert rule["kind"] in KINDS and rule["action"] in ("quarantine", "flag", "fix") and rule["match"]["words"], rule
        out.append(pack)
    return tuple(out)


def rules_for(frame) -> list[dict]:
    """The packs' rules for a frame: one per rule and matching column, id `<pack>.<rule>` (a finding's
    detector is `rule:<pack>.<rule>`, its key `rule:<pack>.<rule>|<column>`), source `pack`."""
    out = []
    for pack in packs():
        for rule in pack["rules"]:
            words, types = set(rule["match"]["words"]), set(rule["match"].get("types") or [])
            for name, col in frame.columns.items():
                if words & name_words(name) and (not types or col.type in types):
                    out.append({"id": f"{pack['pack']}.{rule['id']}", "kind": rule["kind"], "column": name,
                                "params": dict(rule["params"]), "action": rule["action"], "source": "pack"})
    return out
