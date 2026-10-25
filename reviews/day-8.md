# Day 8 review: Flow, polish, chat completion, evals, jobs, freeze

Reviewed 2026-10-25 on branch `claude/review-day8-d4d469`, cut from `main` at e84ccc0. The scope is Implementation Plan §2 "Day 8", narrowed by cuts 2, 3 and 9 in the §2.0 table. "Done" means plan §1: it runs on the Titanic sample, its test passes, the UI reaches it, and it's committed. Day 8's commits are 8c96ca3 (D8.1), bdc66d4 (D8.2), 001a5e5 (D8.5), 83cc73a (D8.3), 0b5c966 (D8.6) and f94e802 (D8.4). The findings of the unmerged Day 5–7 reviews aren't repeated here; where one touches Day 8, this report names it.

**Verdict.** Day 8 meets its exit check in a real browser on the sample and on `sales_dated.csv`. Both "make sense of this" cards came from the model, every chip matched its source fact, and the evidence opened the source fact's query. A job killed mid-run resumed from its checkpoint, and chat proposals commit a new, undoable version only when approved. This review fixed two bugs, each in its own commit with a test and the doc change:

1. The canvas's three-way merge compared JSON with different key orders. It could put this tab's stale copy of a node over another tab's or the AI's change, and every load ended in a save that changed nothing (6b21849).
2. Three malformed canvas documents answered `500` instead of `422` (5ec8705).

The top open finding is Rule 2 in synthesis cards. On `main`, synthesis prose accepts numbers spelled out ("zero", "fifteen", "half", "a quarter of", "½", "III") and any `value:` label. Day 6's branch closes those for synthesis too, because synthesis shares the narrator's checks, but merging it as is would drop this branch's newer causal words (influences, affects, impacts). After both merge, "one", "single", "pair", ordinals, and comparisons and conclusions that no fact backs still get through. The prompt asks the model to compare cards, so these are built into the feature (F1).

## Evidence

| Check | Result |
|---|---|
| `uv run pytest` (api, before the fixes) | **359 passed**, 3 skipped, 1 deselected in 12 min 24 s (the machine was busy). After the fixes, `tests/test_canvas.py` passed 5 of 5. |
| `corepack pnpm test` (web, vitest) | **58 passed** in 10 files before the fixes; 59 after (the merge test). `tsc -b` is clean. The error-boundary test prints a stack trace by design. |
| `corepack pnpm e2e` (Playwright flow test) | **1 passed** (12.5 s test, 22 s with the server). The run used a scratchpad `TEMP`, because the server empties `<tmpdir>/sherlock-e2e`. It now selects its second card with Shift+Enter (abe0de9), which passes on the app as it was. A keyboard fix drafted for this review was dropped when that showed it wasn't needed (see D8.2). |
| `uv run sherlock eval ask`, live, run once | **48 of 50**, **0 unsourced**, median 12.8 s per answer. The plan's last recorded run was 49 of 50. Misses:<br>• "Which reviews mention damaged packaging?" (the known gap; this time a 0-row result, not a count).<br>• "What did cleaning change?": routed to `ask_data`, which answered "This file has no column that answers that". That is routing variance; the D8.4 runs passed it.<br>Spent 218 `llm_calls`, 195,545 prompt and 124,077 completion tokens (319,622 in all): route 50, sql 50, compose 74, summary 8, and the three builds' narration. |
| `uv run sherlock eval grounding`, live, run once | **Passed.** titanic3: 10 cards, all by the model, 34 of 34 chips matching their fact, 32 of 32 facts holding when re-run. sales_dated: 12 cards, all by the model, 46 of 46 chips, 46 of 46 facts. 0 text runs with numbers and 0 causal phrases in either. Both syntheses were written by the model. Spent 26 `llm_calls`, 16,081 prompt and 35,993 completion tokens (52,074 in all). A rescan of the kept database found what the eval can't see (F1). |
| Browser exit check, live, run once | **Passed** on both files. API on 127.0.0.1:8108, Vite on 127.0.0.1:5188 (`--strictPort`), opened at `http://review8.localhost:5188`. Spent 20 `llm_calls`, 14,824 prompt and 26,475 completion tokens (41,299 in all): two syntheses, the sales build and its stories, one chat proposal, and the cascades of its approval and undo. Screenshots are in `reviews/day-8/`. |
| Kill the API mid-job | **Resumed.** On the sales build, the API was killed (`taskkill /F`) once the `stories` job had checkpointed 4 of 9 cards. At restart the log said "re-queued 2 running job(s)", and the job finished with `result {cards: 5}`: it told only the 5 it hadn't stored. |
| Two tabs editing the canvas | The live race didn't lose a change, but only by luck. Each tab's comparison bug made it save right after every load, which happened to re-base its copy. A unit test with the server's key order reproduces the loss, and 6b21849 fixes it (F2). |

### Exit check, step by step

| Step | Result | Screenshot |
|---|---|---|
| Try with sample (Titanic) | The cached seed, ready at v4, with a canvas that already holds a synthesis of three cards | `01-sample-canvas.jpg` |
| Place three cards | From the keyboard: search, Tab, Enter placed "Survival by sex", "Fare distribution by class" and "Average age" below the others; each row turned "on canvas" | `02-selecting-cards.jpg` |
| Select them, "Make sense of this" | Shift-click selected three (chip "3 cards selected"); the button sent it. Super wrote it in one call (848 prompt, 2,141 completion tokens), no repair | `03-make-sense-answer.jpg` |
| The synthesis card | Placed right of the three with three "summarized in" edges (`made_by: ai`). Its 6 chips (72.7%, 19.1%, 3.8×, 60.00, 8.05, 29.27) each equal their source fact's `formatted` value (checked in SQLite against the cited card's fact sheet). Labels `value:sex:female`, `value:pclass:1`… came from the cards | `04-synthesis-placed.jpg` |
| Evidence on a synthesis chip | "72.7% is the rate for the top sex, computed on version 4", with the source widget's SQL | `05-synthesis-chip-evidence.jpg` |
| Rule 4: `sales_dated.csv` | Uploaded, "Use as is": 9 widgets and the overview (killed and resumed as above). Three cards placed, then selected **from the keyboard** (Enter, then Shift+Enter twice) and sent with `/` and "Make sense of this". Super wrote "Return rate, revenue disparity, and price disparity all point to Gizmo outperforming Sprocket." with 4 chips (7.3%, 5,000, 17.5×, 16.2×), each equal to its fact | `06-sales-make-sense-answer.jpg`, `07-sales-synthesis-keyboard-selected.jpg` |
| Chat proposal (CSV tab) | "set the region of row 1 to Central": a pending `edit_cells` proposal "Change 1 cell in 1 row: region" (before South, after Central) at v2, with nothing changed. Approve made step `edit` v2→v3. v2's Parquet still says South (Rule 3). A second Approve is `409` "already approved". Undo made step `undo` v3→v4 | (API, see D8.5) |

The keyboard check of the chat proposal was cut short: the browser pane was hidden by then, so key presses stopped reaching the page. Approve and Reject are real `<button>`s (`ChatBar.tsx` `ProposalView`), so they are in the Tab order. The approval itself was driven from the page's own `fetch`.

## Status by item

| Item | Status | Evidence |
|---|---|---|
| **D8.1** `canvas/`: JSON Canvas with etag, validation, pruning, AI writes in one transaction; `add_canvas_node`, `add_canvas_edge`; `ask_story`; "make sense" as a synthesis card with chips through its sources, `sources_changed` and Refresh; Add to Flow makes an `answer` card | **done** (fixed here; F1 open) | `canvas/service.py` (`validate` :60, `write` :162 with `BEGIN IMMEDIATE` and `409` + etag, `mutate` :181), `routers/canvas.py`, `stories/synthesis.py`, `agent/flow.py`; `tests/test_canvas.py`. Live on two files above. **Fixed:** a `fromNode` list, an edge `sherlock` string or a `card_id` list was a `500` (5ec8705). `sources_changed`: `synthesis.check_sources` runs after every stories run (`stories/service.py:299`) and is tested (`test_canvas.py:140-152`); Refresh queues a `stories` job (`routers/cards.py:78-83`). Rule 2: see F1. |
| **D8.2** Flow tab: card, note and synthesis nodes, labelled edges, connect mode and handles, palette (drag or Enter), minimap, zoom, Fit view, selection as chat context, "Open widget", in-place editing, delete with Undo, three-way merge | **done** (fixed here) | `FlowTab.tsx`, `FlowPalette.tsx`, `api/canvas.ts`, `state/flow.ts`. Seen live: palette rows placed with Enter, "on canvas" marks, Shift-click and keyboard selection, the context chip, minimap, Fit view, "summarized in" edges in the accent colour, and the evidence drawer from a node's chip. The keyboard path works: Tab reaches each node, Enter selects it, and Shift+Enter adds it. (The browser tool's own "shift+Enter" sent no separate Shift keydown, which first looked like a bug; Playwright's real key sequence passes.) **Fixed:** the merge (F2). Not run live: connect mode, edge labels, note editing and delete with Undo (code read at `FlowTab.tsx:441-506`). |
| **D8.3** Error boundaries, offline banner, Undo on destructive actions, remembered scroll and viewport, empty states, Export from the palette and from chat, canvas notes and Flow cards in the notebook | **done** (F7, F9) | `ErrorBoundary.tsx`, `OfflineBanner.tsx` (`shell.test.tsx`), `StoryCard.tsx` delete with Undo, `DatasetPage.tsx` scroll memory, `FlowTab.tsx:263-271,507` viewport memory, the empty canvas (`FlowTab.tsx:532-541`), palette Export (`FlowPalette.tsx:102-107`), `actions.export_options` and `loop._export`, `notebook/exporter.py::_flow_cards`, `_canvas_notes`, `cells.note`; tested in `test_chat_actions.py:120` and `test_canvas.py:120-138`. The `?` sheet is cut 9. |
| **D8.4** `eval ask` at 50 questions over three files; `eval grounding`; gaps listed in TRD §8.1 and the README | **done** (F4) | Live here: ask 48 of 50 with 0 unsourced (the plan says 49 of 50 after fixes); grounding 80 of 80 chips and 78 of 78 facts, with no numbers or causal words in text. The gaps are listed in TRD §8.1 ("Eval at fifty questions") and README "Known limitations". The scoring is still lenient (F4). |
| **D8.5** Value-index resolve, clarification buttons, plans with live step statuses, follow-up focus, `update_widget` with Undo, `edit_cells` and `clean_selection` proposals with Approve and Reject, thread summary, Add to Flow | **done** | `agent/actions.py`, `agent/loop.py:241-385` (plan and `plan.step` events), `:470-492` (summary), `:338-358` (`update_widget`, `undo_widget`), `routers/proposals.py`; `tests/test_chat_actions.py` covers approve, a second approve, expiry, reject, an unknown row, tab exposure, `update_widget` with Undo, a two-step plan and export. Live: a proposal applied only when approved, as a new version (above). The proposal summary is written by code, so the model's words can't carry numbers (`actions.py:106`). |
| **D8.6** Checkpoints with resume and heartbeats, the purge job, the Playwright flow test | **done** (F10) | `jobs/runner.py` (`JobContext.checkpoint`, `state` at :149), `jobs/stories.py` (resume from `told`), `jobs/purge.py`; `tests/test_purge.py` (4 tests). Killed and resumed live (above). `pnpm e2e` passes. Only the `stories` job checkpoints, as TRD §3.3's as-built says; clean and build start over. |
| **D8.7** Feature freeze | **held** | See "Freeze" below. |

### Freeze (D8.7)

After the Day 8 work (0b5c966, then f94e802 for D8.4), three commits changed the app:

- **f94e802.** D8.4 itself, plus bug fixes the evals found: the `ask_stats` routing guard (`loop.STATS_WORDS`), exact medians and per-row averages in the SQL prompt, prefixed `from` keys in the overview's merged sheet, and the analysis widget left without a story. It also adds D9.1 (the cached sample clone) and D9.4 (`THIRD_PARTY.md`), which are Day 9 Musts, not new features.
- **0a62263.** Day 9: the seed, the README, `scripts/live_check.py` and `scripts/example_notebook.py`, the eval's `429` retry, and a stricter causal-wording rule (influence, affect, impact). The plan allows "wording rules found by the evals".
- **e84ccc0.** Docs and `scripts/architecture.py`.

None of them adds a user-facing feature beyond the Day 9 plan, so the freeze held.

## Findings, ranked

### High

- **F1. Synthesis prose can still state numbers in words, and claims no fact backs (Rule 2).**
  - **How it was checked.** Offline: model output was handed straight to `synthesis._check` (the validator `make sense` and `ask_story` use), on `main` and with Day 6's narrate, synthesis and text modules overlaid.
  - **Accepted on `main`, refused with Day 6:**
    - spelled-out numbers: "Zero", "Fifteen", "Half of them", "A quarter of them", "Class III"
    - "About ½" (main refuses this one too: `has_digits`)
    - a `value:fare:512.33` label, shown as "512.33"
    - So synthesis shares the narrator's checks, and Day 6's F1 and number-word fixes cover it. Don't re-fix this here.
  - **Merge hazard.** Day 6's branch was cut at 8c96ca3, before 0a62263 added `influenc…|affect…|impact…` to `narrate.CAUSAL` and to the synthesis prompts. With Day 6's files, "Class influences survival" is accepted again. Whoever merges Day 6 must keep both rule sets.
  - **Still accepted with Day 6 applied:** "Only one group", "A single group", "A pair of groups", "Third class trailed first class", "Fourscore". Ordinals and archaic words are Day 6 F20 "by design". "One", "single" and "pair" aren't listed there.
  - **Comparisons and conclusions.** A chip, then "was far higher than", then an unrelated chip, is accepted. The synthesis prompt tells the model to "connect or compare the cards" (`synthesis.py:29`), so such claims are part of the feature, not a slip. Day 6 F8 reported the same for the narrator.
    - Seen live: "Return rate, revenue disparity, and price disparity all point to Gizmo outperforming Sprocket." The return-rate card has no product breakdown, so it points to nothing about Gizmo.
    - Seen live, Titanic: "Survival differed across groups while the typical ticket price remained 33.28" (the seeded synthesis).
    - **In the grounding eval's own sales synthesis**, which the eval passed with every chip matching: "Total revenue amounts to 1,025,982 while total units sold equal 47,715. This shows an average unit price of 21.41 based on 5,000 transactions." Revenue ÷ units is 21.50. 21.41 is the mean of the rows' `unit_price`. The model joined three true chips with a relation that is false, which is computing a number in words.
    - The same rescan found a narrator card saying the overall survival rate "is lower than the rates shown in the breakdown by class and sex", which isn't true for male passengers in third class (Day 6 F8's territory).
  - **Fix options for the owner:**
    - Drop "compare" from the prompt.
    - Or keep it and give the model comparison facts computed in code (for example `<card>.<fact> > <card>.<fact>` as a derived fact) that it must cite.

### Medium

- **F2. The canvas merge undid other tabs' and the AI's changes. Fixed (6b21849).**
  - **Cause.** `api/canvas.ts::mergeCanvas` decided "edited here" with `JSON.stringify(base) !== JSON.stringify(local)`. The base comes from the server, which stores the canvas with sorted keys. The local copy comes from `FlowTab.toDoc`, in its own key order. So every node looked edited here, and the merge put this tab's stale copy over the server's newer one.
  - **Reproduced** in vitest with the server's key order: another tab's move of node `a` was reverted.
  - **Why the live race didn't show it.** `FlowTab.save` used the same comparison, so every load and every `canvas.updated` was followed by a `PUT` that changed nothing. The API log showed a GET/PUT pair each time. That save re-based the tab's copy into its own key order, which hid the merge bug except in the 500 ms after a load or a refetch.
  - **Fix.** Both comparisons sort keys first (`canvas.ts::same`). After the fix, opening the Flow tab made one `GET` and no `PUT`.
  - TRD §2 (web, Flow) now says why.
- **F3. Malformed canvas documents were `500`. Fixed (5ec8705).**
  - These were `500`:
    - an edge whose `fromNode` is a list
    - an edge whose `sherlock` is a string
    - a node whose `card_id` is a list
  - They're `422` now, with the reason. TRD §4.7 lists them.
- **F4. The ask eval's scoring is still lenient (Day 4 F13, unchanged), and the new D8.4 checks add more.**
  - **Day 4 F13 is unchanged.** `check` still takes the expected value from *any* cell of any table (`eval/ask.py:53-59,94-97`). For `rows`, every column is tried as the key, and *any* other cell in the row may match (`:99-101`).
  - **Contradictory answers pass.** `text_any` passes on any one word, and these passes don't depend on the answer being right:
    - "Is fare significantly different between men and women?" passes with "could be chance" **or** "significant". So it passes whichever way the answer goes, and also on "not significant".
    - "How accurate is the model?" passes on any "%".
    - "What did cleaning change?" passes on "typed".
  - **A source can stand in for an answer.** An answer with `source` but no value check passes on the source's kind alone. `unsourced` counts a `card` source as backing a table (`:115`).
  - - **Seen in this run.** "How accurate is the model?" passed on its "%", although the answer reads "The model accuracy model accuracyis 80.4%." (a repeated label and a missing space; the `ask_model` compose path, Day 7's territory). The "significant" question passed with the right verdict this time, but the check would also have passed the wrong one.
  - **The grounding eval can't see wrong relations.** It checks each chip against its fact, not what the words claim between chips. F1's sales synthesis passed it.
  - **Fix.** For "significant" questions, expect the verdict ("unlikely to be chance") and refuse its negation. Prefer number blocks and single-cell tables before any cell.
- **F5. Fit view and new syntheses ignore the open chat thread.**
  - "Make sense of this" opens the thread, which covers the lower half of the canvas.
  - The synthesis is placed level with its sources' centroid. On the sample it landed under the thread, and Fit view fitted nodes behind it (`03-make-sense-answer.jpg`).
  - The e2e test closes the thread first for this reason (`flow.spec.ts:38`).

### Low

- **F6. "I added a synthesis of 3 cards" counts the selection, not the cards cited** (`agent/flow.py:67`). A selected synthesis expands to its sources, deleted cards drop out, and more than eight are cut. The number is code-written, so this isn't Rule 2, but it can be wrong.
- **F7. A `sources_changed` synthesis goes into the notebook without saying so.**
  - `cells.card` renders every chip from the current fact sheet. The prose that was written about the old numbers is exported beside the new ones, with no note.
  - An outdated *run* gets a note (`cells.py:298`); a card doesn't.
- **F8. The synthesis often lists instead of synthesising.**
  - The Titanic synthesis repeats each card in turn: "Survival was highest… Median fare was highest… The overall average age was…". The prompt says "don't repeat each one in turn".
  - No check enforces it. It's quality, not grounding.
- **F9. Approving a cell edit says "Undo it from the Changes panel".** The toast has no Undo button, unlike the other destructive actions D8.3 lists (`ChatBar.tsx` `ProposalView`).
- **F10. The analysis widget is narrated twice in a build.**
  - The build's `stories` job tells every live widget, the analysis among them. The run's own `stories` job then tells it again.
  - Live on sales: 10 narrate calls for 9 widgets, and 2 overviews (about 2k extra tokens).
  - This follows from f94e802's fix for an analysis widget left without a story.
- **F11. Stale TRD lines beside the as-built ones.**
  - TRD §8.1 still says "Not built yet: `ask_story` and `update_widget` get one honest sentence each" and "Not yet: the multi-step planner…, the thread summary, and `update_widget`, `edit_cells` and `clean_selection` proposals (D8.5)". The D8.1 and D8.5 as-built notes below them are right.
  - TRD §7.4's "Checks on every story" lists the causal words without influence, affect and impact. Only §14 adds them.
  - These are left for the owner, because the Day 6 and Day 7 branches edit the same TRD sections.
- **F12. Canvas nodes have no accessible name.**
  - React Flow gives each node `role="group"` and no `aria-label`, so a screen reader hears "group", then the card's text.
  - A label of the overline and the headline would help.
- **F13. `file`, `link` and `group` nodes are accepted by the API, but the Flow tab turns them into notes.**
  - `toFlow` treats them as notes, and the next save writes them back as `type: "text"`, losing `url` and `file`.
  - Nothing creates them today, but `PUT /canvas` accepts them (TRD §4.7).
- **F14. The plan's task inventory said the Day 8 work was still to come. Fixed (eabeafa).** Five §3 lines now say it was built. The `eval/` line is left alone, because Day 6's branch edits it.

## Environment notes for the next reviewer

- The browser tool's "shift+Return" is not a real Shift+Enter for React Flow. It sends Enter with a Shift flag but no Shift keydown, so the selection is replaced. Playwright's `press("Shift+Enter")` works.
- With the browser pane hidden, key presses report success but don't reach the page. Check `document.activeElement` after each one.
- `pnpm e2e` fixes the port at 8010 and empties `<os.tmpdir()>/sherlock-e2e`. Set `TEMP` and `TMP` to your own folder if another session might run it.
- The live evals delete their temp database, so `llm_calls` is lost. This review ran them through a wrapper that keeps the folder.

## Token Factory spend for this review

| What | `llm_calls` | Prompt tokens | Completion tokens | Total |
|---|---|---|---|---|
| Browser exit checks (two syntheses, the sales build and stories, one proposal, its approval's and undo's cascades) | 20 | 14,824 | 26,475 | 41,299 |
| `eval grounding` | 26 | 16,081 | 35,993 | 52,074 |
| `eval ask` | 218 | 195,545 | 124,077 | 319,622 |
| **All** | **264** | **226,450** | **186,545** | **412,995** |

The Rule 2 probes, `pytest`, vitest and `pnpm e2e` used no live model (offline checks or recorded replies).
