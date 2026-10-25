# Day 3 review: the Cleaner

Reviewed 2026-10-25 on branch `claude/review-day3-11bb30`, cut from `main` at `79f07eb` (Day 5). The scope is Implementation Plan §2, Day 3 (D3.1–D3.6), as rescheduled by §2.0, with the definition of done from §1. Specs read: TRD §4.4, §4.10, §5.1, §6.8, §7.2 and §14; App Flow §4–5; UI brief §5.3–5.4; PRD CLEAN-3 to CLEAN-5 and §7.3.1; CLAUDE.md Rules 1–4.

## How it was checked

- **API tests:** `uv run pytest` gave **281 passed, 3 skipped, 1 deselected** (live marker) in 3 min 45 s.
  - The 3 skips are POSIX-only sandbox tests: the memory rlimit, `sandboxd` and the sandbox user. They can't run on this Windows machine.
  - A first run with `-x` failed `test_sandbox.py::test_happy_path_and_log`. That test asserts the machine-wide `%TEMP%/sherlock-sandbox` folder is empty, while the live run and sibling sessions were using it. It passed on the rerun (finding L5).
- **Web tests:** `corepack pnpm test` gave **36 passed** before the fixes and 38 after (two tests added). `tsc -b` is clean.
- **Corruption benchmark:** `uv run sherlock eval corruption` was run offline with the recorded fixtures (`LLM_MOCK=tests/fixtures/llm/cleaner_messy.json`), so nothing was spent. See D3.3.
- **Live exit check:** **one** run of `uv run sherlock clean samples/titanic3.csv` with the real models (Nemotron 3 Ultra and Super on Token Factory), in a throwaway `DATA_DIR`. There was no re-run.
  - **Tokens spent:** 29,490 on the clean (13 calls: 7 diagnose, 3 propose, 3 critic) plus 2,380 on the dashboard build's `curate` call that followed. That's 31,870 in total (13,087 prompt and 18,783 completion), from `llm_calls`.
- **Seeded samples:** `scripts/make_samples.py` was run twice. All four files have the same MD5 both times, and both runs match the committed files (`git status` was clean).
- **Browser:** the cleaning screens were driven against the real API on port 8103 with Vite on 5183, using the recorded `cleaner_slow.json` fixture (no model spend). Checked: the offer, the live log, "So far", the checks card, the budget line, Stop and the ready dashboard.
- **Notebook:** `uv run sherlock export notebook <id>` on the live-run dataset wrote 41 cells (version 5, 4 steps, 8 widgets).

## Status by item

| Item | Status | Evidence |
|---|---|---|
| **D3.1** `verifiers.py`, `gate.py`, `helpers/`, with tests; helpers run in the sandbox | **done** (one bug fixed) | All 10 helpers from TRD §7.2, plus `parse_failures` and `keep_outside_scope` (`api/sherlock/cleaning/helpers/__init__.py:27`). None changes its input in place or drops rows. The hard checks match TRD §7.2 (`verifiers.py:105-178`), including `placeholder_fill`. `test_cleaning_units.py` has 15 test functions (20 cases, two of them added in this review), among them `test_helpers_run_in_the_sandbox_and_types_survive`. **Fixed:** the gate's blast counted a quarantined row as one cell (H1, commit `ddb6ff6`). |
| **D3.2** `loop.py` as TRD §7.2; prompts; fixtures; `POST /clean`, `GET /report`, `job.log` | **done**, with deviations below and two high findings | `loop.py` follows the as-built order in TRD §7.2 (deviations in the comparison table). Prompts are in `cleaning/prompts/*.txt`, and the fixtures are `cleaner_messy.json` and `cleaner_slow.json`. `test_cleaner.py` has 8 end-to-end tests (9 cases): commit and flag, report, log entries, use-as-is, refusals, hand-edited cells, model unavailable, `new_rows` scope, Stop, and `after_upload`. The live run committed steps and wrote a report. **Fixed:** the Titanic example in the propose prompt (M1, `4e4ddae`), and two pseudocode lines documented as built (`a1c1bb1`). |
| **D3.3** `eval/corruption.py`, three sets, recovery / harm / row loss, the table, `FEEDBACK.md` | **done** | The three sets are seeded generators. Damage: money, placeholders, case, typos, mojibake and day-first dates. Scoring and the table are in `corruption.py:177-271`, and `test_benchmark_scoring` passes. `FEEDBACK.md:58-80` has two live tables from 2026-10-24: 92–97% recovered, 0% harm, 0% row loss, then 74–97% on the rerun. The offline run's table is below. **Gap:** quarantine isn't scored as harm (M3). |
| **D3.4** "Use as is" | **done** | `routers/cleaning.py:62-74`. Only from `offer`; it queues `build_dashboard`, and a second call is `409`. Covered by `test_use_as_is_builds_on_the_typed_version`. The Day 1 review notes it skips the LLM rate bucket while its build calls `curate` (Day 1 hand-over). |
| **D3.5** CLI `clean`/`eval`/`export`; seeded `make_samples.py`; `POST /jobs/{jid}/cancel` kills the worker | **done** | All three commands ran. `make_samples` is byte-reproducible. Cancel: `test_stop_kills_the_running_worker_and_builds` (cancelled in under 10 s, `ended_by: stopped`, the build follows). In the browser, Stop during a busy-loop candidate gave `cancelled` plus a built dashboard within 5 s. The kill path is `sandboxd.run_worker` / `runner._direct` with `should_stop` (`sandbox/sandboxd.py:64-99`). |
| **D3.6** offer and in-progress screens over SSE, so-far counts, checks, Stop, the end-of-run report | **partial** | The offer, live log, chips, gate colors, "So far", checks, budget line and Stop all match App Flow §5 and UI brief §5.4. **Fixed:** a running line wasn't replaced when a model wait came between it and its outcome (`a33d903`), and "20-issue budget" was hardcoded (`7e4d8d0`). **Open:** the end-of-run report isn't held for 3 s, so a fast build skips it (M5). The budget line lags one issue (L2). |
| **Exit check** | **done** | Headless on Titanic with the real model: 3 steps committed, a report, 0 rows deleted. The benchmark prints its table. The Titanic expectations are below. |

## The live exit check (Titanic, real model, 2026-10-25)

`uv run sherlock clean samples/titanic3.csv`: ended `done` in 96 s. 13 issues found, 1 fixed, 2 flagged, 11 skipped, 0 rows deleted, v2 → v5. Every version has 1,309 rows.

| Step | Gate | Confidence | What it did |
|---|---|---|---|
| 1 (automatic) | commit | 1.0 | Typed 7 columns |
| 2 | commit | 0.83 | `fill_by_group(result, 'age', by=['pclass', 'sex'], stat='median')`: 263 ages filled, e.g. 1st-class men 42, 3rd-class women 22 |
| 3 | flag | 0.67 | `home.dest` title case: **573 cells**, including state codes ("Brooklyn, NY" → "Brooklyn, Ny", "Dowagiac, MI" → "Dowagiac, Mi") |
| 4 | flag | 0.62 | `functional_dependency` on embarked: **quarantined 1,020 of 1,309 rows (78%)**. 1,014 of them are rows with no cabin, because `embarked != cabin.map(majority)` is true wherever cabin is missing |

**Titanic expectations, checked by hand:**
- **Boat and body leakage: met.**
  - `leakage|boat` and `leakage|body` are marked and never changed.
  - Every other issue on those columns (`missing|body`, `missing|boat`, `mixed_types|boat`) is skipped with "… records the outcome, so it is not changed", with no model call.
- **Age by title: not this run.**
  - The model offered "Median by title in name" as its third candidate. That is the propose prompt's own example label, word for word (M1, fixed).
  - It chose "Median by pclass and sex", which committed. That's a sound, generic fix, and the varying choice matches `docs/LOG.md`.
- **Deck from cabin: not offered.**
  - Cabin was diagnosed "Left as is" (1,014 missing), which follows the owner's "missing values stay missing" rule.
  - A deck column would be a derived column, which no detector proposes. If the expectation still stands, it needs a PRD decision; it isn't a cleaning bug.
- **Side effects of step 4:**
  - Its quarantine hid the 2 missing `embarked` and 1 missing `fare` issues from the re-profiled card, so the run ended `done` without attempting them.
  - The dashboard built on v5 counts only 289 usable rows.

## Corruption benchmark, offline (fixtures, no model spend)

```
| Set | Rows | Damaged cells | Recovered | Harm | Row loss | Quarantined | Steps | Time | Ended by |
| titanic_clean | 1,043 | 509 | 12.0% | 0.00% | 0.0% | 0 | 0 | 2 s | done |
| sales | 1,500 | 765 | 42.7% | 0.00% | 0.0% | 0 | 1 | 4 s | done |
| hr | 800 | 269 | 40.1% | 0.00% | 0.0% | 0 | 0 | 2 s | done |
```

The fixtures answer "leave as is" for every column except `region`, so these numbers measure only the typing step and the one recorded fix. Live recovery is in `FEEDBACK.md` (92–97%, then 74–97%). The harness, the scorer, the throwaway data directory and the table all work offline.

## The loop against TRD §7.2, step by step

| Pseudocode | As built | Verdict |
|---|---|---|
| `queue = issues sorted by severity desc` | `_next_issue` re-reads the current card each time, most severe first, skipping attempted `detector\|column` keys (`loop.py:246`) | match |
| `for issue in queue (while budget remains)` | Steps (`CLEAN_MAX_STEPS`), time (`CLEAN_MAX_SECONDS`) and tokens (`BudgetExceeded`) are all checked; time and steps only between issues | match (documented) |
| context = column entry + 20 samples + 10 examples + earlier decisions | `_column_context`: the column entry, 20 distinct samples, 10 examples, and decisions from the last 10 cleaner steps | match. Decisions from **undone** steps are included too (L3) |
| `diagnosis = LLM(large, Diagnosis)` | large; adds `preferred_option` and `leave_as_is`, which skips with no code | documented deviation |
| `candidates = LLM(large, Candidates)` | large, `max_tokens=6000`, 1–3 candidates, preferred approach first | match |
| sandbox on a 2,000-row sample stratified by issue presence | `_sample_ids`: whole if ≤ 2,000 rows, else up to 1,000 with the issue plus random fill (seed 42) | match |
| `c.score = verifiers.score(r, issue)` | `verifiers.verify`, 0 if any hard check fails | match |
| `best = max …; if best.score == 0: skip` | `loop.py:319-322` | match |
| critique (medium) **before** the gate and full run | the full run and verify come first, then the critic (medium), then the gate | documented deviation (blast is measured, not estimated) |
| `confidence = 0.6·best + 0.2·agreement + 0.2·(no concerns)` | the review term is `not changed_something_it_shouldnt`; concerns don't count | documented owner decision. See H2 |
| `blast = cells_affected / total_cells` | changed cells + **quarantined rows ×1** | **bug, fixed** (H1): a quarantined row now counts as all its cells |
| gate commit / flag / skip | `gate.decide` | match |
| `if not verifiers.passed(full): skip` | `loop.py:341-343` | match |
| `commit_step(…, base_version=v)`; on 409 reload, re-run once, else skip | a 409 skips at once ("The data changed while this step ran") | deviation, **now documented** (`a1c1bb1`) |
| `datacard = profile(new_version); queue = re-detect` | `commit_step` re-profiles; `_next_issue` reads the new card | match |
| row-removing ops are rewritten to quarantine | not rewritten: `row_ledger` fails them and they score 0 | deviation, **now documented** (`a1c1bb1`) |
| parse failures go to quarantine, not NaN | `parse_quarantine` hard check | match |
| ambiguous choices: 3 samples at 0.7, majority, else conservative | `ambiguous_dates` only. The vote counts the *index* across three samples that each have their own option list. Without a majority it takes option 0, but the prompt says only "most conservative first is fine", not "must" | partial (L4) |
| leakage is marked, not fixed | `NEVER_CHANGE`, plus any issue on a leakage or ID column | match (confirmed live) |
| `report()` | `report.build_report` from `state_json`, the job's steps and `issues` | match. `counts.found` counts only the `from_version` card, so found < fixed + flagged + skipped can happen (14 vs 13 live) (L1) |

## Hard rules

- **Rule 3, quarantine and never delete: holds in form, not in spirit.**
  - No step can drop a row: `row_ledger` is a hard check, and every live version has 1,309 rows.
  - But nothing limits *how many* rows a step quarantines. Quarantined rows leave every widget, model and story, so step 4 removed 78% of Titanic from analysis while "0 rows deleted" was reported (H1, M3).
- **Every change is an undoable step with `notebook_code`: holds.**
  - Each cleaner step stores `code`, `notebook_code` (ending `df = result`), `helpers_used` and the verifier report, and `validate_notebook_code` runs at commit.
  - The exported notebook includes all four steps with the helpers vendored.
- **Rule 4, nothing tuned to Titanic: one violation, now fixed.**
  - The propose prompt's example label was "Median by title in name", and the live run proposed it word for word (M1, `4e4ddae`). A test now checks the prompts against `titanic3.csv`'s columns.
  - Outside Day 3: `profile/infer.py:23` `TARGET_NAMES` lists `survived` next to generic names (L6, for the Day 2 review).
  - The detectors, gate thresholds and verifiers are generic.
- **Rule 2, the model never computes a number: exposure.**
  - The model writes code, and every number in steps, counts and verifiers comes from that code.
  - But model-written prose reaches the UI with numbers in it: the log's main line for a committed step is the candidate's `expected_effect`, and skip reasons are "Left as is: <diagnosis.cause>".
  - Live example, shown in the log and the report: "Home destination was not recorded for **over 40%** of passengers…". 564 / 1,309 = 43%, so it happens to be right, but the model computed it (M2).

## Findings, most severe first

**High**

- **H1. A flagged step can quarantine most of the data.**
  - *Live evidence:* step 4 quarantined 1,020 of 1,309 rows (78%) because of a NaN comparison in the model's mask. The critic named the problem ("Over-quarantining: 1020 rows were quarantined while only 4 rows actually violated the functional dependency"). The step still committed with a flag, and the dashboard built on 289 rows.
  - *Our bug, fixed in `ddb6ff6`:* the gate counted a quarantined row as one cell, so the blast read 5.6%. With the fix the step's blast is 78%, and its flag reason becomes "changes more than a fifth of the data".
  - *Not fixed (owner decision):* under the TRD formula a step at confidence ≥ 0.55 still commits with a flag whatever its blast.
  - *Suggested:* a hard verifier that fails a step quarantining far more rows than the issue counts (for example more than 2× the issue's count plus a small margin). Or skip any step whose blast is above a ceiling such as 50%. Either is a PRD CLEAN-4 / TRD §7.2 change.
- **H2. The critic's "changed something it shouldn't" can't stop a commit.**
  - In both live flagged steps the review term was 0. Step 3: 0.6 × 1.0 + 0.2 × ⅓ + 0 = 0.67. Step 4: 0.6 × 0.917 + 0.2 × ⅓ + 0 = 0.62.
  - 0.6 × score + 0.2 × agreement alone clears the 0.55 flag bar, so a step the critic rejects still commits with a flag.
  - Step 3 re-cased 573 `home.dest` values including state codes ("NY" → "Ny"); the critic said exactly that.
  - It's undoable and marked, but it's applied, and the dashboard and stories use it.
  - *Suggested owner decision:* skip when `changed_something_it_shouldnt` is true. This revisits the 2026-10-24 decision, which was about *concerns*, not the verdict.

**Medium**

- **M1. Titanic example in the propose prompt** (Rule 4). **Fixed** in `4e4ddae`, with a test and TRD §7.2.
- **M2. Model prose with model-stated numbers reaches the UI** (Rule 2): `expected_effect` as the log's main text, `diagnosis.cause` in skip reasons and decisions, and the critic's first concern in `flag_reason`.
  - *Suggested:* build the log line from the verifier report (cells changed, rows quarantined, issue count before → after) and keep the model's sentence as secondary text without digits. Or strip digits from model prose the way the story prose check does.
- **M3. The benchmark can't see over-quarantining.**
  - Harm counts only changed values, and quarantined rows keep theirs, so a step like live step 4 scores 0% harm. "Quarantined" is printed but not scored.
  - *Suggested:* count an undamaged row that gets quarantined as harm, or add a "rows lost to quarantine" column next to row loss.
- **M4. The issue rows of later versions keep no outcome.**
  - The loop writes `outcome` on the current version's `issues` row. The report's `found` reads `from_version`, while fixes on later versions have new issue IDs.
  - Live, v2 shows `leakage|body`, `mixed_types|boat`, `whitespace_case|home.dest` and `functional_dependency|embarked` with no outcome, although they were handled.
  - It's not visible in the UI today (the report reads `state_json` and steps), but anything reading `issues.outcome` for the original card will be wrong.
- **M5. The end-of-run report can be skipped entirely.**
  - App Flow §5 says the centre shows the report for 3 seconds, then the build. As built, `ReportSummary` shows only while the status is `building`, and the build finished in under 5 s in the browser check, so the page went from the log straight to the dashboard.
  - The report is still reachable from the CSV tab's Changes panel and from the Flow tab.

**Low**

- **L1.** `counts.found` (issues on `from_version`) can be lower than fixed + flagged + skipped, because skipped includes issues found on later versions (13 vs 14 live).
- **L2.** The budget line ("0 of 20 issues tried") lags by the issue in progress, because `attempted` is checkpointed after the issue ends (`loop.py:214-215`).
- **L3.** Diagnose context includes decisions from undone cleaner steps (`loop.py:411-413` doesn't filter by the effective chain).
- **L4.** The ambiguity vote counts option *indexes* across three samples whose option lists differ. The fallback to option 0 relies on a prompt that only says conservative-first "is fine".
- **L5.** `test_sandbox.py::test_happy_path_and_log` asserts the global `%TEMP%/sherlock-sandbox` is empty, so it fails whenever another process (a sibling session, a live run) has a worker open. This is Day 2's test.
- **L6.** `profile/infer.py:23` `TARGET_NAMES` includes `survived` (Day 2).
- **L7.** The offer's three-line summary leads with issues that are never fixed ("1,188 missing in body", "boat records the outcome") because it sorts only by severity. App Flow's example leads with the fixable ones.
- **L8.** App Flow §5 lists "budget exceeded with zero steps" as a failure that returns to the offer, but TRD §7.2 and the code build the dashboard on `tokens` whatever the step count. The docs disagree; the code follows the TRD.
- **L9.** Cosmetic: odd indentation at `loop.py:329-331` and a run of spaces inside the condition at `loop.py:512`.

**Seen while testing, outside Day 3** (left for the Day 1 review in the shared notes):

- On a first visit the web app fires `/me`, `/events` and `/datasets` in parallel without a cookie. The server creates a user for each (two users 11 ms apart in the check).
- The user-level stream ended up bound to a user other than the dataset's owner, so the library row stayed "profiling" and the page stayed on the cleaning screen after Stop, until a reload.
- Separately, sibling apps on `localhost` (other ports) share the `sherlock_uid` cookie, since cookies ignore ports. Using `http://[::1]:5183` avoided that.

## Commits on this branch

| Commit | What |
|---|---|
| `a33d903` | Web: merge a cleaning log's running line with its outcome across "Waiting for the model…" lines, with a test |
| `ddb6ff6` | Gate: a quarantined row counts as all its cells in the blast (`gate.cells_affected`), with a test and TRD §7.2 |
| `4e4ddae` | Prompt: drop the Titanic example label, with a test against `titanic3.csv`'s columns and TRD §7.2 |
| `a1c1bb1` | TRD §7.2: document the 409 skip and the row-drop rejection as built |
| `bbb426f` | Plan §6: where the corruption sets and damage plan live, and the make_samples reproducibility check |
| `7e4d8d0` | Web: the report names the configured issue budget, with a test |

Nothing is pushed or merged. `.env` was copied in for the live run and isn't committed (it's in `.gitignore`).
