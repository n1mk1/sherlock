"""The rule detector (PRD CLEAN-13, TRD §7.1 step 4): one built-in detector, `rule`, that runs a
dataset's active rules (`Frame.rules`) through a fixed interpreter, so a rule is data, never code.

Each rule is its own finding, detector `rule:<rule id>`, so it is counted, rated, queued and keyed
(`rule:<id>|<column>`) like any other. A finding carries its kind's default level and its action:
`quarantine` is a domain rule (quarantined by its own fix, never guessed), `flag` is listed and never
changed, `fix` goes through the Cleaner's diagnose and propose with the rule as the issue. A rule that
runs past `RULE_MAX_S` is stopped and finds nothing ("This check took too long").
"""

import time

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector, examples
from sherlock.cleaning.detectors.fixtures import clean_frame
from sherlock.cleaning.rules.kinds import ACTIONS, KINDS, RuleError
from sherlock.llm.schemas import Candidate

TOO_LONG = "This check took too long"


def validate(spec: dict, columns: dict[str, str]) -> dict:
    """A rule as saved: `{kind, column, params, action}` checked against the file's columns
    ({name: type}); RuleError names the bad field. Parameters must fit the column's type."""
    kind = KINDS.get(spec.get("kind"))
    if kind is None:
        raise RuleError("kind", f"Unknown kind {spec.get('kind')!r}; use one of {', '.join(KINDS)}.")
    column = spec.get("column")
    if column not in columns:
        raise RuleError("column", f"{column!r} isn't a column of this file.")
    if kind.types and columns[column] not in kind.types:
        raise RuleError("column", f"{column} is {columns[column]}; a {spec['kind']} check needs {' or '.join(kind.types)}.")
    action = spec.get("action", "flag")
    if action not in ACTIONS:
        raise RuleError("action", f"The action is one of {', '.join(ACTIONS)}.")
    params = kind.check(spec.get("params") or {}, columns)
    if spec["kind"] == "order" and (columns[column] in ("int", "float")) != (params["as"] == "number"):
        raise RuleError("params.left", "Both columns of an order must be numbers, or both dates.")
    return {"kind": spec["kind"], "column": column, "params": params, "action": action}


EVIDENCE_KEYS = ("url", "title", "excerpt", "retrieved_at")


def source_of(spec: dict) -> dict:
    """What a rule carries beside its check, kept through validation, Keep and an edit: the model's
    `reason` and the web `evidence` (url, title, excerpt, retrieved_at) docs/plans/tavily.md §3.3 gave it.
    Anything of another shape is dropped."""
    out = {}
    if isinstance(spec.get("reason"), str) and spec["reason"].strip():
        out["reason"] = spec["reason"].strip()[:300]
    ev = spec.get("evidence")
    if isinstance(ev, dict) and all(isinstance(ev.get(k), str) for k in EVIDENCE_KEYS) and ev["excerpt"].strip():
        out["evidence"] = {k: ev[k] for k in EVIDENCE_KEYS}
    return out


def words(rule: dict) -> str:
    return KINDS[rule["kind"]].words(rule["column"], rule["params"])


def proposal(rule: dict) -> str:
    said = words(rule)
    return {"quarantine": f"Quarantine the rows where it isn't true that {said}; don't guess a replacement.",
            "flag": f"Listed for your review, not changed: rows where it isn't true that {said}.",
            "fix": f"Fix the values so that {said}."}[rule["action"]]


def run(rule: dict, frame: Frame, max_s: float) -> tuple[Finding | None, str | None]:
    """The rule's finding on the frame (None when nothing breaks it), or the error that stopped it."""
    kind = KINDS[rule["kind"]]
    column = rule["column"]
    if column not in frame.columns or any(c not in frame.columns for c in (rule["params"].get("left"),
                                                                           rule["params"].get("from")) if c):
        return None, "A column this check reads is no longer in the file"
    if kind.types and frame.columns[column].type not in kind.types:  # a check for every dataset, on another file
        return None, f"{column} is {frame.columns[column].type} in this file, which a {rule['kind']} check doesn't read"
    started = time.monotonic()
    try:
        if rule["kind"] == "pattern":
            mask = kind.mask(frame, column, rule["params"], deadline=started + max_s)
        else:
            mask = kind.mask(frame, column, rule["params"])
    except TimeoutError:
        return None, TOO_LONG
    if time.monotonic() - started > max_s:
        return None, TOO_LONG
    count = int(mask.sum())
    if not count:
        return None, None
    details = {"rule_id": rule["id"], "rule": {k: rule[k] for k in ("kind", "column", "params", "action")},
               "words": words(rule), "default_level": kind.default_level, "source": rule.get("source", "user")}
    if rule.get("evidence"):  # a sourced check: its plan item shows the page (docs/plans/tavily.md §3.3)
        details["evidence"] = rule["evidence"]  # web text: the Cleaner's prompts leave it out (`loop._details`)
    if rule["action"] == "quarantine":
        details["domain_rule"] = True
    elif rule["action"] == "flag":
        details["never_change"] = proposal(rule)  # listed under "Marked, not changed" with the rule's words
    return Finding(f"rule:{rule['id']}", column, count, proposal(rule),
                   examples(frame.columns[column].raw[mask].tolist()), details), None


def detect(frame: Frame) -> list[Finding]:
    from sherlock.config import get_settings

    from sherlock.cleaning.rules.packs import rules_for

    max_s = get_settings().rule_max_s
    rules = list(frame.rules) + rules_for(frame)  # the dataset's checks, then the shipped packs' (PRD CLEAN-13)
    return [f for f in (run(r, frame, max_s)[0] for r in rules) if f is not None]


def quarantine(issue: dict) -> Candidate | None:
    """A quarantine rule's own fix: the rows its mask names set aside, built by code."""
    rule = (issue.get("details") or {}).get("rule")
    if not rule or rule.get("action") != "quarantine":
        return None
    column = rule["column"]
    code = f"{KINDS[rule['kind']].code(column, rule['params'])}\nresult = quarantine_rows(df, bad, {'check: ' + column!r})"
    return Candidate(label="Quarantine rows that break your check", code=code,
                     expected_effect="Sets aside the rows that break the check.")


def _damage(df, column, rows, rng) -> dict:
    """A negative number in place of each chosen value: it breaks the fixture's "at least 0" range."""
    return {(i, column): f"-{abs(float(df.at[i, column])) + 1:g}" for i in rows}


SPEC = DetectorSpec(
    "rule", "your check", "Checks you wrote, or a rule pack set: a range, allowed values, a pattern, an order and more.",
    group="other", weight=0.6, default_level="skews", scope="column", detect=detect, depth=1,
    code_fix=quarantine,
    injectors={"range": Injector(_damage)}, clean_fixture=lambda: (clean_frame(), "amount"),
    fixture_rules=({"id": "fixture", "kind": "range", "column": "amount", "params": {"min": 0.0, "max": None},
                    "action": "quarantine"},),
)
