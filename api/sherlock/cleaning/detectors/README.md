# Writing a detector

A detector is code that finds and counts one kind of data problem. Sherlock never asks the model to find or count anything, so a new check is either a detector module, a rule, or a pack of detectors. The spec it exports is all the rest of the app needs to know about it: the plan, the Cleaner, the review, the log, chat and the web app read it from the registry.

## Pick the right tool

- **A constraint on a column** (a range, allowed values, a pattern, an order between two columns): don't write code. Add it as a check in the cleaning plan ("Add a check") or through `POST /datasets/{id}/rules`. A fixed interpreter runs it (`cleaning/rules/`).
- **A new kind of problem every file can have**: a built-in detector, one module in this folder, added to `BUILTINS` in `__init__.py`.
- **Checks for one field or company** (finance codes, lab units): a pack, an installable Python package your operator turns on with `DETECTOR_PLUGINS`.

## The module

```python
from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.fixtures import clean_frame


def detect(frame: Frame) -> list[Finding]:
    """Read `frame.columns` (each a `profile.infer.Column`: raw, text, numeric, dates, type, role) and
    return one Finding per column (or per frame, for whole rows) with its count and at most five examples."""


def damage(df, column, rows, rng) -> dict:
    """Seeded damage of the kind `detect` finds: {(row, column): damaged value} for the chosen rows."""


SPEC = DetectorSpec(
    "my_check", "plain words for a finding", "One sentence on what it finds.",
    group="text", weight=0.5, default_level="splits", scope="column", detect=detect, depth=1,
    injectors={"my_damage": Injector(damage)}, clean_fixture=lambda: (clean_frame(), "category"),
)
```

- **`id`** is stored on every issue row; never rename it. Bump `version` when what the detector finds changes, so stored severity reviews of the old findings are dropped.
- **`label`** reads in "263 <label>" and "<label> in <column>". **`group`** is the plan module: `types`, `missing`, `text`, `records`, `outliers` or `other`.
- **`weight`** (0–1) orders findings by size within a level. **`default_level`** is what the finding does to an analysis before any review: `breaks`, `skews`, `splits`, `check` (probably real, worth a look) or `cosmetic`. Code raises it on the target or a measure and lowers it on free text (§7.2).
- **`depth`** (1–5) is the layer it belongs to, by how wide a part of the data it reads: 1 single values, 2 each column as a whole, 3 rows against rows, 4 columns against columns, 5 the dataset as a whole. The offer's Cleaning depth slider shows and plans the layers up to the one picked. Left out, it is 1.
- **Behaviour fields** say how the Cleaner treats the issues, instead of special cases in its code: `never_change` (with `skip_text`), `type_fix`, `domain_rule`, `vote`, `code_fix`, `runs_before`, `plan_extras`, `marks_column`.
- **Generic only** (Rule 4): word lists and placeholders, never a sample file's column names. `tests/test_prompt_hygiene.py` checks the strings.

## The contract

Every registered detector must clear `cleaning/contract.py`: plain wording; nothing found in the shared clean frame or its own `clean_fixture`; at least the damaged rows found when its first injector damages its fixture; the same findings twice from the same frame, which it leaves unchanged; well-shaped findings; and at most 2 s on 200,000 rows. A detector that never changes data gives a `found_fixture` it must find something in instead of an injector.

```bash
uv run pytest tests/test_detector_contract.py   # the built-ins, in the test suite
uv run sherlock detectors check                  # everything registered, packs included; exits 1 on a failure
```

The corruption benchmark builds its damage from the injectors (`registry.injector("<detector>[:<kind>]")`), so a set can name your detector and measure how well the Cleaner repairs it.

## A pack

A pack is a Python package that exports a sequence of specs through the entry point group `sherlock.detectors`. `api/samples/detector_pack/` is a working example:

```toml
[project.entry-points."sherlock.detectors"]
example = "sherlock_example.detectors:SPECS"
```

Packs run in the API process with its permissions, so only the operator installs them, and none load unless `DETECTOR_PLUGINS` is `all` or names the pack. A pack whose specs the registry refuses (a repeated id, an unknown group or level, a weight outside 0–1, a depth outside 1–5, a `runs_before` cycle) is skipped, logged, and listed as refused in `/healthz`; the API still starts. `DETECTORS_OFF` turns any detector off without a deploy; its old issues still display.
