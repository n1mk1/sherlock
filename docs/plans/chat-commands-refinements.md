# Plan: make chat commands dependable (no new features)

**Status:** built (2026-10-27). Builds on `docs/plans/chat-commands.md` (built).

**What was built, and where it differs from the plan below**

- **R1 live** (Nemotron, `samples/eval/commands.yaml`, 65 phrasings, 55 with a card expected): before, 35 of 65 routed right, 23 of 55 effects right, median 11.5 s. After, 65 of 65 routed right, 51 of 55 effects right, median 6.9 s, p90 11.4 s. The 4 misses were "make age a whole number" phrasings refused as "changes nothing": the diff compared the values after casting them to the new type, so 22.0 → 22 wasn't a change. Fixed after: a new type is an effect of its own (`impact.columns_retyped`, summary "Make age whole numbers"), and number to number compares the numbers as they are (28.5 → 28 counts).
- **R1 final** (all slices and the review merged, one live run): 61 of 65 passed; 64 of 65 routed right, 52 of 55 effects right, median 11.9 s, p90 28.6 s. Two causes, both fixed after: the reading's no-digits rule refused the user's own numbers ("round to 2 places", "replace double spaces"), so a reading may now repeat a number the request holds, in digits or words ("2" and "two" are one number), and a reading still bad after the repair is dropped from the card rather than blocking the change; and "what would happen if I upper-cased …" made a card, so a what-if is never a command (`loop.WHAT_IF`). Re-run live, 3 of those 4 passed, and the fourth passed twice on its own: model variance.
- **R2:** the reading is also the step's decision line, so the Changes panel and the notebook say "You asked: …" then "**What does it do?** Upper-case every value in sex. You pressed OK in chat".
- **R4:** a warned check is still recorded as "fail" in the step's verifier receipt; only the card turns it into a warning and leaves out its tick.
- **R5:** cleanup of the kept file is lazy, as planned: a card whose version moved keeps its file until OK, Cancel or the startup sweep. A card that OK refreshes keeps its new run, so the next OK saves it without running the code again. Example values go to the prompt for the columns the message names, not the router's `resolved`.
- **Small fixes:** `then` keeps the rest of the message as typed when it splits at "then" into as many parts as the plan has steps; otherwise the planner's questions, with nothing added. A failed OK shows the user's sentence on the card; the model's side stays on the server.

**In one line:** the loop stays as it is: type a command, read the card, press OK, Undo if needed. This plan makes each part of it right more often, faster and easier to trust.

**Scope fence.** No new intents, no new buttons, panels or endpoints, no new kinds of step. Every change below edits code that exists: the router guards, the `STEP` prompt, the dry run, the checks, the card and the eval. If a slice starts needing a new surface, it stops and asks.

---

## 0. Where it is weak today

| # | Weakness | Where | Evidence |
|---|---|---|---|
| R1 | Routing depends on regex guards written for the phrasings tried live; nothing measures the rest | `agent/loop.py` `COMMAND`, `CODE_ASK`, `PLAN_WORDS`, `DELETE_ASK` (lines 88–110) | 6 command cases in `samples/eval/ask_questions.yaml`; 3 of 11 live commands misrouted before the guards |
| R2 | The card can't show a misread request. The summary comes from counts ("Change 1,309 cells: sex"); the model's own reading is dropped | `commands.py::_payload`, `ChatBar.tsx::CommandView` | `StepDraft.reading` is written on every call and never stored |
| R3 | Failures are dead ends, worded for developers | `commands.py::propose` (`"I couldn't write a safe change for that: {why[:300]}"`), `_first_failure` | A failed check reads "nan introduced: 12 values became empty" |
| R4 | The Cleaner's checks refuse changes a user asks for by name | `cleaning/verifiers.py::verify`, used by `commands.dry_run` | "blank out fares over 500" fails `nan_introduced`; "fill missing cabin with Unknown" fails `placeholder_fill`; "make NYC and New York the same" fails `merge_safety`; "show dates as DD/MM/YYYY" fails `dtype` (date → text) |
| R5 | Slow, with one status line for the whole wait, and OK repeats the dry run even when nothing changed | `loop.py` emits only "Writing the code"; `commands.run` always calls `dry_run` again | Router + medium draft + full-file dry run + verify (+ repair: a second draft and dry run), then the same dry run again on OK |
| R6 | Code on the card can be long or loop-heavy, and the before/after preview shows the first 8 changed cells, which often repeat one pattern | `prompts.STEP` ("keep it short"), `steps/diff.py::before_after` (first 20 cells), card slices to 8 | Nothing enforces vectorised code; a title-casing card can show 8 rows of the same `male → Male` |

Order: R1 first (it measures everything else), then R4 and R2 (correctness and trust), then R3, R5 and R6.

---

## R1. Measure routing and success on real phrasings

**Change**

- New eval file `api/samples/eval/commands.yaml`, run by the existing ask eval (`eval/ask.py`) through a `--file` option on `sherlock eval ask`, so there is no second runner.
- 60 phrasings across the two samples already in the eval (`titanic3.csv`, `sales_dated.csv`), written generically ("upper-case <a text column>"), never tuned to Titanic. Each group of five says the same thing in different ways:
  - plain imperatives ("trim the spaces in name"), polite forms ("could you round fare to 2 places"), wishes ("I want sex in capitals"), terse ones ("fare → 2dp"), and ones that start with a noun ("the names have extra spaces, fix them");
  - each command shape: change text, change numbers, fill blanks, set rows aside ("delete …"), add a column, convert a type, limit to a condition ("only for third class");
  - near misses that must **not** become commands: "make a chart of fare by class", "how do I trim spaces?", "which names have extra spaces?", "what would happen if I rounded fare?";
  - plan-open cases with `context: {plan_open: true}`: "also leave age alone" edits the plan; "round fare" is a command.
- Expectations reuse the `proposal` check (kind, `cells_changed`, `columns_added`, `quarantined`), plus `intent` for the near misses. Expected counts are computed from the CSV with DuckDB, as the file header already requires.
- The eval prints a per-phrasing table and three totals: **routed right**, **card produced**, **card's effect right**, plus the median and p90 seconds.

**Then fix what it finds.** Order of preference: the router's intent lines (`prompts.INTENT_LINES`), then the `STEP` prompt, and a regex guard only when a phrasing is common and the model keeps missing it. Every guard added gets a comment naming the live phrasing it fixes, as the existing ones do.

**Tests:** recorded fixtures (`LLM_RECORD`) for a third of the phrasings in `tests/fixtures/llm/chat_commands.json`, so `pytest` keeps the routing honest offline.

**Done when:** live, at least 57 of 60 route right and at least 54 of 60 produce the right effect; no near miss becomes a card. Record the before and after numbers in the commit message.

---

## R2. Show what the model understood

**Change**

- `StepDraft.reading` gets a tighter description: one plain sentence, in the user's terms, of what the code does ("Upper-case every value in sex"; "Set aside the rows where age is empty"). It must pass `wording_problem` (no numbers in words, no causal words, no markup); the `validate` callback rejects it otherwise, which uses the one repair that exists.
- `_payload` stores it as `reading`; `Proposal` gets the field (`api/types.ts`, regenerated OpenAPI).
- The card shows it first, above the code-written summary:

  ```
  Upper-case every value in sex                    ← the model's reading
  Change 1,309 cells in 1,309 rows: sex            ← code-written counts (unchanged)
  [ code ]  [ before / after ]  ✓ checks
  ```

- The sentence never carries a number: counts stay in the code-written summary, so the rule that numbers come from code still holds.

**Tests:** `test_chat_commands.py` checks that the reading is stored, that a reading with a number the request lacks or "because" is repaired, and that the user's own numbers may be said back; `commands.test.tsx` checks it renders above the summary.

**Done when:** every card in the R1 eval shows a reading, and the eval's `text_any` can check it for a few phrasings.

---

## R3. Failures that say what to do next

**Change** (all in `commands.py`, in the user's words, written by code):

| Failure | Today | After |
|---|---|---|
| A column name not in the file | `'Fare' is not a column of this file; use one of …` (to the model only); user sees the repair's last error | "This file has no column called Fare. The closest are fare and fare_usd." (closest by `rapidfuzz`, already a dependency) |
| A check failed after the repair | "I couldn't write a safe change for that: nan introduced: 12 values became empty" | "The code would empty 12 cells in fare that had values, so I didn't make a card. If you meant to blank them, say 'blank out …'." One sentence per check, from a table next to `CHECK_WORDS` |
| The code crashed after the repair | "the code failed: KeyError …" | "The code I wrote didn't run (it looked for a column that isn't there). Try naming the column." The raw error stays in the receipt, not the chat |
| Nothing changes | "it changes nothing in this version of the file" | "Nothing in this version matches that, so there's nothing to change." plus, when the code filtered rows, how many rows the filter matched (0) |
| Not doable | "I can't make that change to this file: <reading>" | unchanged, but the reading now follows R2's wording rule |

**Tests:** one per row of the table, with fixtures that force each failure.

**Done when:** no reply the R1 eval produces contains a Python exception name, a check's internal name, or an unexplained "safe".

---

## R4. Let the user's explicit request outrank the Cleaner's guards

The Cleaner's checks protect against changes nobody asked for. A chat command is asked for, and the user sees the code and the before/after before OK. The `quarantine_scope` check already became a card warning for this reason; R4 does the same for four more.

**Change** (`commands.dry_run`, after `verifiers.verify`):

| Check | Stays a refusal | Becomes a card warning |
|---|---|---|
| `row_ledger`, rows added or removed, columns removed | yes | |
| `dtype`: mixed types in one column | yes (breaks the Parquet file and the grid) | |
| `parse_quarantine`: unparsed values not set aside | yes (silent data loss) | |
| `pandera` | yes | |
| `nan_introduced` | | "This empties 12 cells that had values, in fare." |
| `placeholder_fill` | | "This fills 687 blanks in cabin with the text 'Unknown'. Sherlock can't tell that apart from a real value." |
| `merge_safety` | | "This makes 3 different values in city the same value." |
| `dtype`: number or date turned into text | | "fare becomes text: sorting and sums on it will stop working." |
| `quarantine_scope` | | (already a warning) |

- The warnings are code-written from the report's counts, and shown on the card and in chat, as the quarantine warning is now.
- The checks a card shows as passed (`checks`) list only the ones that passed, so a warned check never shows a ✓.
- `STEP` keeps "never with a placeholder word" as a default, adding "unless the user names the value", so the model doesn't invent "Unknown" on its own.
- The Cleaner is untouched: it still calls `verify` with the refusals as they are.

**Tests:** one per warned check: the command produces a card with the warning and no ✓ for that check, and OK saves it. One per kept refusal: no card, and R3's message.

**Done when:** the four example commands in §0 each produce a card with the right warning, and a mixed-type result is still refused.

---

## R5. Faster, with the wait shown

**Measure first.** `llm_calls.latency_ms` already times each model call. Add a timing log line per stage in `commands.propose` (draft, static check, sandbox, diff and verify) and run the R1 eval to get a baseline per stage. Record it in the commit message.

**Change**, in order of expected gain (keep only what the baseline shows is worth it):

1. **OK reuses the dry run when the version hasn't moved.** Keep the dry-run Parquet as `.chat_<proposal id>.parquet` instead of deleting it in `propose`. On OK, if `current_version == base_version` and the file is there, commit it with no second sandbox run. Remove it on Cancel, failure and after commit. When another step commits, the file is left alone: OK sees the version moved, ignores the file, deletes it and re-runs (lazy, so `steps/commit.py` needs no hook). Command cards never expire, so there's no TTL: on startup, remove any `.chat_*` file whose card isn't pending. A changed version takes today's path (dry run again, refresh if the effect differs).
2. **Status per stage.** `propose` takes the loop's `emit` and says "Writing the code", "Running it on a copy of the file", "Checking the result", and "Fixing the code" during a repair, through the `status` event the chat already renders. No new UI.
3. **Smaller prompt.** `STEP` sends every column's dtype and the full chat context. Send the dtypes plus three example values for the columns the router resolved (`resolved` in the loop), and the dtypes only for the rest. Check on the R1 eval that routing and success don't drop.
4. **Read the Parquet once.** `dry_run` reads `src` twice (in `diff_versions` and `_read`). Pass the frames through.

**Tests:** OK on an unchanged version makes no sandbox call (count `sandbox.execute` calls); OK after another step still refreshes; the leftover file is gone after Cancel and after commit.

**Done when:** the median time from send to card drops by at least a quarter on the R1 eval, OK on an unchanged version answers in under a second, and the chat shows each stage.

---

## R6. Short code, a preview that shows the variety

**Change**

- **Code style, checked.** `static_check` gets a `style` pass used only for commands (not the sandbox's safety check): a Python `for` or `while` loop over the frame, `iterrows`, `itertuples`, or `apply(..., axis=1)` when a column operation exists. These go back to the model through the existing repair ("Use whole-column pandas, no row loops"), not to the user. `STEP` gets the same rule and two short examples (a string method on a column; `result.loc[mask, col] = …`).
- **Line limit.** More than 15 lines goes back once with "Make it shorter". Above the limit after the repair, the card still shows, folded to the first lines with "Show all".
- **Varied preview.** `diff.before_after` picks up to 20 cells covering the distinct `old → new` pairs first (one example per pair, most frequent first), then fills with more rows. The card shows 8 and says "and N more like these" from the counts.
- **Notebook.** Check that an exported command step reads cleanly: the reading as its markdown line, then the code. It's a one-line change in the step's markdown if it doesn't.

**Tests:** a fixture whose first draft uses `iterrows` is repaired to a vectorised version; the before/after of a mixed command lists each distinct pair once; the exported notebook runs (`sherlock eval notebook`).

**Done when:** no card in the R1 eval contains a row loop, and every card's preview shows each distinct change pattern before repeats.

---

## Small fixes found while reading (do with the slice they touch)

- The Undo tooltip says "up to 3 changes in a row" only when it's off. Say it in the enabled tooltip too: "Undo: <summary> (Ctrl+Z) · 2 more after this".
- `commands.then` joins later questions with "and" and adds "?" even when the rest is a command ("round fare then trim names" becomes "trim names?"). Keep the user's words as typed.

---

## Order and checks

1. **R1:** the eval, a live baseline, then routing fixes. Commit the eval and the fixes separately so the baseline is in history.
2. **R4:** the checks, then the matching R3 messages.
3. **R2:** the reading on the card.
4. **R3:** the rest of the messages.
5. **R5:** measure, then reuse the dry run, status lines, prompt size.
6. **R6:** style check and preview.

Each slice: `uv run pytest`, `corepack pnpm typecheck`, `corepack pnpm test`, `corepack pnpm e2e`, the R1 eval live, then commit, push and deploy by hand. Work in a worktree (other sessions commit to `main` here) and fast-forward.

## Risks

- **R4 weakens guards.** It does, on purpose, and only for chat commands, which the user reads before OK. The four checks that protect the file's structure stay as refusals.
- **R1 can turn into regex sprawl.** The rule is: prompt first, guard last, every guard cites a live miss. If the guards grow past a dozen, routing commands should move to the model alone, judged on this eval.
- **R5's kept file uses disk.** At most one Parquet per pending card on the current version, removed on every exit path and by the startup sweep.
- **Live eval cost.** 60 phrasings is about 60–120 medium calls per run. Run it per slice, not per edit.
