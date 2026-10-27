# Sherlock · Backlog

What's still open, in one list. Each line: the area, the gap, where it is, and what done looks like. An item tagged with a doc section, like "(App Flow §3.3)", has a "Not built yet (docs/BACKLOG.md)" marker in that section. When you fix an item, remove its line in the same commit. Paths are a starting point; check the code before relying on them.

---

## 1. Before submitting (Day 10; plan §2 Day 10, PRD §12)

The owner's, unless a line says otherwise.

- **Make the repo public** (stage-one blocker). `n1mk1/sherlock` is private and its About box has no website. Done: secret scan run, repo public, live URL in the About box.
- **The video**: public on YouTube, under 3:00 (the live rules say "less than three (3) minutes"; plan §9 ends by 2:55).
- **The Devpost text** in plan §7's order, track set to Best Apps and Agents.
- **Finalize `FEEDBACK.md`** for the feedback prize.
- **The user tests**: the three cold-start sessions and the by-hand half of the baseline. Their tables in `docs/USER-TESTS.md` are empty, and Potential Impact leans on them.
- **The README's cost and latency figures**:
  - Ultra's cost per sample run, from the account's console (the README says "on the account's console"), so plan D9.3's cost per role is complete;
  - the medians come from the local database's 111 calls of 2026-10-25. Run `uv run sherlock llm stats` against the deployed app's database (a Render shell in `/app/api`) and refresh the README's medians and tokens per message;
  - read the "Where Token Factory sped up the build" sentence against the Devpost text.
- **The Tavily key, for Best Use of Tavily** (plan open decision 1). The live web eval is recorded in `FEEDBACK.md` (local key), but the deployed app has no `TAVILY_API_KEY`, so no Tavily call runs there and the bonus can't be claimed (PRD §12.4). Done: the key set in Render's environment (`sync: false` in `render.yaml`) and a web answer seen on the live site.
- **Keep it running through judging**: Render's paid plan and the Token Factory credit until Dec 15, 2026 (PRD §9).

## 2. Decisions only the owner can make

- **Type-aware cell editors and autocomplete** (PRD CSV-5, P0). Every cell edits as text (`Grid.tsx`): no category dropdown (`GET /columns/{col}/values` exists for it), boolean toggle, date picker, number check or autocomplete. No cut covers it. Build them, or record the drop in the PRD (plan §2.0).
- **Multi-column sort, column resize and auto-fit** (PRD CSV-8, P0). The grid sorts by one column, with fixed widths (`Grid.tsx`). Say whether plan §5's cut 5 ("beyond … sort") covers these; plan §2.0's list doesn't name them.
- **`/` with the chat bar set to Hidden.** PRD ASK-1 says `/` summons the bar; UI/UX §5.11 says Hidden removes it, which is built (`ChatBar.tsx` renders nothing). Pick one.
- **Cut P0s keep their label.** CSV-2, 3, 4, 6, 7, 9, 10, 11, 14 and every other P0 a cut removed carry a "Removed by cut N" marker in the PRD, with the priority unchanged. Say whether that stays.
- **Imbalanced two-class targets.** The verdict compares accuracy only (`ml/analysis.py`, `LIFT`), so at 3% positives a model with AUC 0.95 reads "weak, 0.0 points better". Use AUC or balanced accuracy for the verdict and the one-column rule, or require both; a PRD and TRD change.
- **Where the story suggestion goes.** Plan D6.3 says side by side; App Flow §11 step 5 says "your text vs the AI's revision"; UI/UX §4.5 says under the body, which is built. Pick one and align the other docs.
- **"Budget exceeded with zero steps."** App Flow §5 returns to the offer; TRD §7.2 and the code build the dashboard anyway. Pick one.
- **Specified pieces no cut covers and nobody built.** Build each, or record the drop (a P2 label, or a PRD change for a P0):
  - TRD §7.4 steps 1–2: Welch's t, Mann-Whitney, Cohen's d and a trend slope on fact sheets (chat's `ask_stats` computes them, `stories/facts.py` doesn't), and the correlation (0.4) and dependency (0.6) relations between widgets;
  - TRD §12: JSON logs with the request ID on every line, and `GET /metrics`;
  - TRD §10–§11: `JOB_BACKEND=nebius` and `python -m sherlock.jobs.run` (TRD §1 calls it optional);
  - TRD §14: the mocked clean → build → stories run on all five end-to-end files (it runs on Titanic and small made-up files).
- **Tavily context on anomaly cards** (PRD STORY-9, plan T-4, Tier 3). Not built: its query would hold a period (a month or a year) from the data, which plan open decision 3 leaves to the owner. Say whether a period may go out (shown before sending) or T-4 stays names-only.
- **Narration temperature** (TRD §8.3). The spec says 0.4; narrate and synthesis calls run at the client's default 0 (`llm/client.py`). Keep 0 and change the spec, or pass 0.4.

## 3. Honesty and Rule 2

- **Model-written dashboard titles skip the wording check.** `dashboard/builder.py` refuses only digits and length over 80; chat titles also go through `stories/wording.py` `title_problem` (numbers in words, causal wording). Done: the builder uses `title_problem` and falls back to the templated title.

- **Noise can "beat the baseline".** The verdict checks only `lift >= 0.02` (`ml/analysis.py` `LIFT`); at 150 rows one row is 3.3 points of a fold, and 3 of 30 pure-noise sets passed. Done: a clearly positive fold-wise lift (`core.baselines` returning per-fold scores), or a threshold scaled with n.
- **A number that settles a text target isn't flagged as a leak.** `ml/plan.py` runs the correlation check only for numeric targets and `_pure` only on non-numeric features, so `refund_amount > 0` exactly when `churned = yes` becomes the top driver. Done: a purity or threshold check for numeric features against a category target.
- **A target computed from the features.** `revenue = units × unit_price` reports R² 0.9995 and "beats the best simple rule". Done: a warning on held-out R² > 0.99 or accuracy > 99%.
- **"95% interval".** `ml/core.py` uses mean ± 1.96·sd/√folds, which understates the spread (folds overlap; the t-quantile for 5 folds is 2.78), and the winner of three models is scored on the folds that picked it. Done: call it "fold spread (approximate)" or use a t-quantile, and add the optimism to `limits`.
- **Number words "one", "single" and "pair" pass** ("Only one group", "A pair of groups"): `stories/wording.py` `NUMBER_WORDS` doesn't list them, and TRD §7.4's gaps-by-design list doesn't either. Add them, or list them as gaps.
- **"Sixfold" to "ninefold" pass** (TRD §7.4 refuses twofold to tenfold). `NUMBER_WORDS` in `stories/wording.py` lists only two-, three-, four-, five-, ten-, hundred- and thousandfold. Add six- to ninefold.
- **`is_nvidia_embed` admits non-NVIDIA IDs** (latent: embeddings are off). `llm/models.py` accepts "embed" plus "nvidia", "nv-" or "nemotron" anywhere, so `someorg/conv-embed-v1` passes. Done: require the `nvidia/` prefix as `is_nemotron_chat` does, and update TRD §3.5.
- **Partial dependence for 3+ classes says "predicted <target>"** (`ml/analysis.py`); it's the share predicted as the most common class. Label it so.
- **An outdated synthesis doesn't come back by itself** (TRD §7.4.2, plan 1.3). Under "Ask first", refreshing the cited cards leaves the synthesis `outdated` until its own Refresh. Done: a cue on the synthesis once its sources are current (plan 2b.6 already rewrites under "Automatic").
- **Replay doesn't re-run the Cleaner's verifiers** (TRD §7.8). `steps/replay.py` checks only the file, `_row_id` and the row count, though the spec aborts a replay when "its verifiers fail". Done: `verifiers.verify` for each replayed cleaner step.

## 4. Accessibility (UI/UX §2.4, §6, §8)

- **Updating states dim with opacity**, against §8's "nothing dimmed with opacity": a story card drops to `opacity-70` (`StoryCard.tsx`), a widget body to `opacity-60`. axe never sees those states. Done: a non-opacity cue, or §8 allows it for transient states.
- **Column notes are hover-only** (PRD LOAD-7). Glide draws the header on a canvas with no keyboard focus; chat's "what does <column> mean?" is the only keyboard route.
- **Click-to-filter needs a mouse**, and a click with no `mousemove` before it only focuses the widget. Touch isn't checked on a device.
- **Widgets and story cards can't be focused** (`WidgetShell.tsx`, `StoryCard.tsx`), so card ↔ widget linking and a widget's menu have no keyboard path. Canvas nodes can be focused but have no accessible name, only `role="group"` (`FlowTab.tsx`).
- **Bklit charts have no text alternative**: their SVGs are `aria-hidden` and "Show as table" is the only route. The custom charts have one.
- **Reduced motion is partial**: the chip pulse is a fixed 400 ms and `scrollIntoView` is smooth (`StoryCard.tsx`); `animate-spin`, `animate-pulse` and the Bklit bars ignore it. Several chart hooks check `useReducedMotion`, so recheck before fixing.
- **Slide-over panels below 1024 px** stay in the tab order, don't trap focus and don't close on Esc (`AppShell.tsx`).
- **Shared hover between two charts** isn't built (one of the Bklit spike's pass rules).
- **The card editor's `/` picker** (`CardEditor.tsx`) has `role="listbox"` with no options or arrow keys, and `/` is always swallowed, so "and/or" can't be typed.
- **The widget drag handle is mouse-only**: a named `role="img"`, but react-grid-layout gives the layout no keyboard move.

## 5. Bugs and gaps by area

### Identity, limits, operations

- **Model-calling routes without `llm_rate_limit`**: `POST …/use-as-is`, `POST /jobs/{jid}/retry`, `POST /cards/{cid}/refresh`, and an upload whose profile job queues the build. Token budgets still apply. Done: the dependency on each, listed in TRD §15.
- **Only story jobs resume after a restart** (`jobs/runner.py`); profile, clean, build and ML jobs start over, though PRD §8 says jobs are checkpointed per step and resumable. Done: checkpoints for the Cleaner and the build, or PRD §8 narrowed by the owner.
- **`undo` is in `jobs/runner.py` `KINDS` with no handler.** Nothing queues it today. Done: removed from `KINDS`, or a handler.
- **`scripts/deploy.sh` doesn't pass `TAVILY_API_KEY`, `SANDBOX_MEM_MB` or `DUCKDB_MEMORY_MB`** to the Nebius endpoint (TRD §11). Done: passed like the model IDs.
- **`JOB_BACKEND=nebius` is accepted and ignored** (`config.py`), so jobs run locally (TRD §10). Done: refused at startup until built.
- **`PATCH /widgets/{wid}` with `{ prompt }`** answers `422` "needs chat, which isn't built yet" (`routers/widgets.py`), though `update_widget` exists (TRD §4.5). Done: routed to `update_widget` under `llm_rate_limit`, or the message fixed.
- **Widget and card restore have no 10-minute check**, unlike dataset restore (`widgets/service.py` `restore`, `routers/cards.py`); they work until the purge (TRD §4.5–§4.6). Low priority.
- **`folder_bytes` isn't recomputed when a run or an export finishes** (only `jobs/purge.py` does it), so run artifacts and notebooks count against storage only after the next purge (Schema §4).
- **The Nemotron fallback doesn't cover a full Super gate** (plan 2b.8, TRD §3.5). A Super call waiting for a free slot (all `LLM_CONCURRENCY_MEDIUM` busy) waits to its deadline and fails "This answer ran out of time." Sending it to Ultra needs a wait rule, and would put chat's overflow on Ultra's two slots, which the Cleaner uses.
- **`llm_calls` is never purged** (`jobs/purge.py` keeps it). The budget sums read today's rows through the `created_at` index (migration 004), but the table and the receipts' and spend reads grow with use. Done: a retention rule the budgets and spend figures can live with, e.g. older than the 7-day dataset retention (`DATASET_TTL_DAYS`).
- **`uv run sherlock clean sample` times out after 900 s**: the cached seed is cloned already `ready`, and `cli.py` `clean()` waits for `offer` or `failed`. Done: `SAMPLE_SEED_DIR=off` inside `clean()`, or import `samples/titanic3.csv` directly. Also `eval --sets` help names only corruption and ask, though notebook, grounding and web take it.
- **`scripts/live_check.py --files all` says each notebook "rebuilds the version"** but only executes it. Done: compare values as `sherlock eval notebook` does, or change the wording.
- **The focused widget's title is read without a dataset check** (`agent/loop.py`, `SELECT title FROM widgets WHERE id = ?`), so another user's title could reach the prompt. Low risk: IDs are random ULIDs.

### Ingest, rows and profile

- **Import preview** (`ImportPreviewDialog.tsx`, `lib/importPreview.ts`): doesn't detect the header row or skip rows, and sends only changed options, so the server's sniffed `skip_rows` can stack on a header row the user set (App Flow §3.2, PRD LOAD-2 say the header is auto-detected).
- **Edit batches** (`rows/edits.py`): the same cell twice in one batch keeps the first one's `invalid` mark and history; `2020-01-01 13:45` in a DATE column drops the time; `nan` in a DOUBLE is accepted and marked changed; restoring a row that isn't quarantined commits an empty version.
- **A conflict between `save()`'s check and `commit_step`'s** comes back without `conflicts`, though TRD §4.3 says "always".
- **`offset=10**20` or `version=10**20` on `GET /rows`** is a 500, not a 422.
- **`ingest/sniff.py` `header_names` reads one physical line**, so a quoted newline in a header splits it.
- **A 3-line cp1252 file was detected as cp775.** Longer files are fine, and the preview can override the encoding.
- **`NON_NEGATIVE` has no word boundaries** (`cleaning/detectors/impossible_values.py`), so `average_temp`, `account_balance` and `percentage_change` count as non-negative quantities.
- **`profile/infer.py` `TARGET_NAMES` includes `survived`** (Rule 4: dataset-specific).
- **Web ingest details**: CR-only line endings with Skip rows > 0 say "no data rows"; error toasts close after sonner's default 4 s (`main.tsx`), though Brief §4.10 says they stay; the status badge's hover text shows only on `failed` (`LibraryPanel.tsx`, App Flow §14); the empty-state pitch uses `text-foreground-2`, not `--muted-foreground` (`EmptyLibrary.tsx`, Brief §5.1).
- **`embed` isn't in the LLM client's `ROLES`** (`llm/client.py`).
- **Value embeddings are never computed**, even with `MODEL_EMBED` set: `profile/service.py` writes `value_index.embedding` as NULL, so value matching uses only exact and fuzzy text (TRD §7.1 step 5).
- **`dateparser` is a dependency but type inference doesn't use it** (CLAUDE.md stack, TRD §7.1). Done: used for date inference, or removed from the stack and `pyproject.toml`.
- **No upload progress bar for files over 2 MB** (App Flow §3.1).
- **Paste a CSV** (P1, App Flow §3.1) isn't built.
- **The delimiter list has no free-text "Other"** (`ImportPreviewDialog.tsx`); "Other (…)" shows only when the detected delimiter isn't one of the four (App Flow §3.2).
- **While profiling, the chat bar is disabled** (`ChatBar.tsx`), so questions don't queue as App Flow §3.3 says.
- **Raw `duckdb.connect(":memory:")` connections** have no memory cap and spill to `./.tmp`, which the `app` user can't write in the image (TRD §3.2): `ingest/sniff.py`, `steps/diff.py`, `rows/edits.py`, `cleaning/loop.py` (`_read`, the selection scope), `steps/replay.py` `_row_ids`, and `DESCRIBE`-only helpers (`steps/commit.py`, `steps/replay.py` `_types`). Done: pass `settings` and use `storage.new_duckdb`. The sandbox worker's own connections stay as they are.
- **The jobs tray prints a failed job's raw error** (`JobTray.tsx`), the DuckDB text the failed-profile screen keeps behind "Technical details" (App Flow §3.3, §15).
- **"Profiling failed" has no Delete button** (`StatusScreens.tsx`); Delete is only in the dataset and library menus (App Flow §3.3). Done: reuse `ConfirmDelete`.
- **`Dataset.cleaning_progress` is never filled** (`routers/datasets.py`), so after a reload the library shows "cleaning 0%" until the next `job.progress` (TRD §4.2, `LibraryPanel.tsx`). Done: filled from the running clean job's progress.

### The Cleaner

- **The corruption benchmark can't see over-quarantining**: harm counts only changed values (`eval/corruption.py`). Done: an undamaged row quarantined counts as harm, or a "rows lost to quarantine" column.
- **Later versions' `issues` rows keep no `outcome`**, while the report reads `from_version`.
- **The end-of-run report can be skipped** when the build finishes fast; App Flow §5 says it shows for 3 seconds.
- **Smaller**: `counts.found` can be lower than fixed + flagged + skipped; the budget line lags by the issue in progress; the diagnose context includes decisions from undone steps; the ambiguity vote counts option indexes across samples whose option lists differ; the offer's summary leads with issues that are never fixed.
- **`flag_rows` has no effect** (`cleaning/helpers/__init__.py`): the sandbox returns its `flags`, but nothing flags the step (TRD §7.2). Done: force the gate to `flag` when flags are present, or drop the helper.
- **The critic prompt says "Effect on a sample"** (`cleaning/prompts/critic.txt`), but the effect comes from the full data.
- **Exact and near duplicate rows share one issue key**, `duplicates|None` (`detectors/duplicates.py`, `plan.key`), so the plan shows, and the Cleaner attempts, only the more severe (App Flow §4.1, TRD §4.4; `loop.py` `handled`). Done: near duplicates get their own key.
- **Chat answers during cleaning don't say which version they read** ("as of step 5", App Flow §5). Every message carries `version` (TRD §4.9), but `ChatBar.tsx` shows no "v3" mark on an answer from an older version.
- **A `propose` reply cut off at its 6,000-token cap** still skips its issue as "model output invalid" unless a code fix exists (`loop.CODE_FIXES`: numbers stored as text, PRD CLEAN-4e; domain rules quarantine). Done: shorter code asked for in the propose prompt, or code fixes for more detectors.
- **A merge flagged for review names its pairs case-folded** ("wst → west", from `details.pairs`), not as the file spells them ("Wst → West").
- **`canonicalize_categories` without a mapping uses a ratio of 90** (`cleaning/helpers/__init__.py`), so "Wst"/"West" (85.7) merges only when the model passes the detector's pairs as `mapping`. Not yet seen in a live Cleaner run.
- **Clean with AI in the CSV toolbar has no dot before the first clean** (`CleanButton` in `CsvTab.tsx`), and neither the plan nor the report offers "Include these next time" for hand-edited cells: `api/queries.ts` always sends `include_user_edited: false` (App Flow §4, §8.4; PRD CLEAN-8).

### Dashboard and chat

- **A `web_context` plan step shows its raw intent name**: it has no entry in `agent/loop.py` `STEP_LABELS`. Done: a label such as "Search the web".
- **`agent/compose.py`'s docstring says compose uses `small`**; the code uses `medium` (TRD §8.3).
- **`MAX_CALLS = 8` in `agent/loop.py` likely can't trigger**: at most five plan steps run and the counter rises once per step. Done: a cap that counts model calls, or the constant removed.
- **Some outside-world questions still go to the file** (plan T-6): with reasoning off, Nano doesn't always route the same question the same way ("latest trends in retail pricing this year?" once to `ask_data`, "what return rates do online retailers usually report?" once to `ask_why`). TRD §8.1's guards don't catch these. The answer is about the file, never an error, and no data is sent.
- **The 20-widget warning** (`widgets.service.CAP_WARNING`) is returned only by `POST /datasets/{id}/widgets`; Duplicate, Pin and chat's `create_widget` don't return or show it (PRD DASH-10).
- **On a wide file the 60-candidate cap cuts in generation order** (`dashboard/candidates.py` `MAX_CANDIDATES`), so trends and tables can be dropped before they're scored.
- **Pinning a table pins the first result's query and drops the answer's `selection_id`** (API only; the UI offers Pin on charts).
- **Compose needs a repair on about a third of answers**, and some fall back to the table ("Here is the result (3 rows)."). One cause: the model labels the result's alias (`value:class:1` for `pclass`), which `compose.label_text` refuses. Done: accept a value label on a result column that maps to a file column, or tell the compose prompt that labels name the file's columns.
- **Inline rename may submit twice, and Esc may commit through `onBlur`** (unverified).
- **Widget and answer details**: the empty-widget message says "No rows match the current filter" with no filter set and has no Clear filter link; "Show as table" resets on reload (UI/UX §5.5); chat answers have no copy button (App Flow §10.2).
- **`ask_meaning` drops the general block silently** when the model returns nothing, though TRD §8.2 says it's shown.
- **"The model" means the newest run** once another answer comes between (`insight.pick_run`); an outdated run is labelled "(version N, outdated)", but a done run of the same target isn't preferred over it.
- **An edit asked right after a question in the same thread once got no proposal within 90 s** (not reproduced). Done: one scripted repro.
- **The build shows no skeleton widgets, streaming cards or "6 of 8 widgets" banner**: the grid appears all at once (App Flow §6).
- **The version pill isn't clickable** (App Flow opens the Changes panel from it), and there's no Filter button or builder; a filter comes only from clicking a chart (App Flow §7.1, UI/UX §3.2, §5.5).
- **Add widget has no histogram template**; the templates are Bar, KPI and Table (`AddWidgetDrawer.tsx`, App Flow §7.3).
- **"The closest I can answer: …" is plain text**, not a button that asks it (App Flow §10.2).
- **Hitting the 40k-token message budget** (`MESSAGE_TOKEN_BUDGET`) raises `budget_exceeded` and drops the earlier steps' results (`agent/loop.py`); TRD §8.1 says compose what exists with a note.
- **Proposals expire lazily** (`agent/actions.py` `approve`): a stale one keeps its Approve button until clicked and answers `409`, instead of reading "Expired: the data changed since" (App Flow §10). Done: expire pending proposals in `commit_step`, or compare with `current_version` when listing.
- **A wide file gets no note that the dashboard used only its 30 most informative columns** (App Flow §18); `columns_used` is only in the build job's result (`dashboard/builder.py`).
- **Save doesn't retry by itself once the connection is back**; pressing it again works (App Flow §18).
- **Questions ignore the cells selected in the CSV tab** (PRD CSV-13): the chip says "n rows selected", `ChatBar.tsx` sends `selected_cells`, but only cell-edit proposals read it (`agent/actions.py`). Done: a selection from their `row_ids` passed as `selection_id`.
- **A refusal never offers a closer question** (PRD ASK-8): `NOT_YET` in `agent/loop.py` is empty, so `_suggestion` never runs. Done: the suggestion appended to every can't-answer.
- **A name that matches two columns about equally** ("price" with `unit_price` and `total_price`) isn't asked about before the query (plan 2.8, TRD §8.1); the SQL step picks one. Asking first risks answers the SQL step reads right ("survival" for `survived` scores 75); it needs its own ask-eval run before it ships.
- **Chat's route guards are English keyword rules** (TRD §8.1, `agent/loop.py`): rankings, quarantine, "why …", records over an amount, "how do I …", web search, delete requests, row edits and forecasts are caught only in English. A delete with no leading verb ("I want the male rows gone") isn't caught either.
- **A question for every row with no condition** gets `find_rows` with predicate `TRUE` and "<n> rows match". Done: `find_rows` says a predicate that keeps every row selects nothing in particular.
- **"Why did <a group> …?" adds per-group shares only for a number or yes/no target** (`insight._group_part`); a category target gets the column's rank without them.
- **The column-swap checks are lexical** (`agent/answerers.py`):
  - `Toolkit.substituted` sees only words the router listed as column entities; when Nano lists none, a swapped column depends on the SQL prompt alone. A legitimate reading named unlike its column ("port → embarked") costs one more Super call.
  - `stem_linked` misses synonyms with no shared stem ("paid on average" → `fare` goes to the repair) and lets a different quantity that shares a stem through ("class size" → `pclass`).
  - `money_swapped` knows five kinds (`MONEY_KINDS`): an amount outside them ("tips", "bonus", "budget") depends on `substituted`, and "income" on a file with only `revenue` is refused where a reader might accept it.
- **"And for women only?" after "average fare by class" misses** in about half the live ask-eval runs: Super's SQL step returns an empty query, the repair matches no rows, and the answer is an empty table. No result check fires. Done: the follow-up's context or the SQL prompt's follow-up rule fixed, and the eval passing on repeat runs.
- **The result check's repair costs one more Super call on an honest empty answer** (plan 2.7), about 3–5 s. Telling an expected empty result from a wrong filter needs more than the result.
- **A widget made in chat isn't highlighted when it lands**, and KPI and table answers have no link to their widget (PRD DASH-8, `ChatBar.tsx`).
- **A deleted widget's card stays in the Stories panel** until the overview updates (PRD DASH-9, `api/queries.ts`).
- **The "changed" badge is set only when a stories job's reason is `cascade`** (`stories/service.py`), so a card re-told for another reason, including an analysis card after a cascade (reason `widget`), gets none (PRD STORY-6).
- **Canvas notes and edge labels never reach the model** (PRD FLOW-5, `FlowTab.tsx`, `agent/flow.py`). A note's text is saved only on blur (FLOW-1).
- **The overview accepts 2 bullets** (`stories/narrate.py`, `min_length=2`); PRD asks for 3–5.
- **The CSV tab doesn't remember its scroll position or selection** (PRD §7.11, `DatasetPage.tsx`).

### CSV tab

- **The Filter toggle** (header filter row, P1, UI/UX §5.6) isn't built.
- **No "Export up to step k" after a failed export** (App Flow §17.5); the backend supports `up_to_step`.
- **Cleaning plan and Changes panel copy** (`CleanPlanPanel.tsx`, `ChangesPanel.tsx`): the pending-edits note has Discard edits but no Save (App Flow §8.4); the scopes "Whole dataset" and "Rows added since the last clean" have no counts; "Current selection (1 rows)" and "1 cells" aren't pluralized.
- **"Keep mine" on a row the newer version deleted** can't be saved (`422`) and blocks the buffer until the line is removed.
- **For about a second after Save**, the grid shows the old version's rows under the new header.
- **Select-all offers to delete only the rows whose pages are loaded.**
- **The undo confirmation doesn't say which replayed steps touch the same columns** (App Flow §8.5).
- **Find shows at most the rows of the first 10,000 matches.**
- **An invalid edit reads "age → abc" in the step's list**, though it was saved blank and flagged.

### Stories

- **A renamed dataset can get a stale cached notebook**: rename doesn't bump `state_rev` (`routers/datasets.py`) and the name isn't in `notebook/exporter.py` `cache_key`, so `DATA_PATH` names the old `-raw.csv`. The status isn't in the key either, so PRD NB-1's "exported during cleaning" note can be missing. Done: `state_rev` bumped on rename and status changes.
- **PRD NB-2's "no data" note is in the notebook's second cell**, not its first (`notebook/cells.py`), and `RANDOM_SEED` is set there but never used.
- **The notebook puts edited card text into Markdown raw** (`notebook/cells.py` `_runs_md`). Done: `\`, `*`, `_`, `#`, `<`, `>` and `&` escaped in text runs (TRD §7.7).
- **"Change view" never offers heatmap or scatter** (`WidgetShell.tsx` `compatibleViews`), so a heatmap switched to bars can't go back.
- **The cascade progress line clears only on `cascade.done`** (`api/queries.ts`), so leaving mid-cascade, or a job that dies, leaves it showing.
- **Editor chips show the value saved with the card**, not `Card.facts`, and unverified chips aren't dashed (`CardEditor.tsx`).
- **Labels repeat the model's noun**: "Passenger class pclass 1", "Fare fare values".
- **Story panel details** (`StoriesPanel.tsx`, `StoryCard.tsx`): suggestion chips have no handler; the outdated badge can queue repeat jobs; hover isn't cleared on Edit layout or widget delete; the evidence query isn't invalidated on `card.updated`; the drawer shows no run for an analysis fact; a failed request says "Stories appear once the dashboard is built".
- **An edited card doesn't say its chips re-render from the latest sheet** (by design, TRD §4.6).
- **The cascade toast leaves out `outdated` and `errors`.**
- **The tiny-group rule has gaps** (TRD §6.4, `stories/facts.py` `MIN_GROUP`): a group's size is unknown when the widget's group keys aren't its query's leading columns, or for a UNION, so such a group can be named highest. Chat (`agent/`) doesn't apply the rule: "Which port had the best survival?" can answer with a 2-row group.
- **Old overview and widget cards keep "None" and tiny-group facts** until told again (a refresh, a cascade or a rebuild); nothing re-tells them on deploy.
- **Cramér's V uses the Yates-corrected χ² on 2×2 tables, and Cohen's d the unweighted mean of the two variances**; both understate a little. Done: stated in TRD §8.2, or `correction=False` and the pooled SD.

### ML

- **`TimeSeriesSplit` for a dated target isn't built** (TRD §7.5 step 4); every run uses (grouped) k-fold.
- **The progress labels misreport the work** (`ml/analysis.py`): "setting baselines" and "testing models" are sent back to back, and "explaining" takes about half the run.
- **Constant columns stay in as features** with importance 0 (`ml/plan.py`).
- **A repeating free-text column can get the role `target_like`** (`profile/infer.py` checks the last column's distinct count before its text length), and chat reads that role directly (`agent/loop.py` takes the first `target_like` column; `insight.ROLE_WORDS` calls it an outcome). The DataCard's `target_candidates`, the builder and the stories leave it out (`ml.registry.target_ok`).
- **`GET /recipes` gives no per-method compatibility** (`ml/registry.py` `manifests`), which TRD §4.8 promises.
- **The setup form's number fields drop an out-of-range value on each keystroke** (`MlSetup.tsx`), so "120" can't be typed into Time budget.
- **An analysis widget's scope chip says "Some rows"**, not the filter (`WidgetShell.tsx`, `MlSetup.tsx`).

### Flow

- **Fit view and new syntheses ignore the open chat thread**, which covers the lower half of the canvas.
- **"I added a synthesis of 3 cards" counts the selection**, not the cards cited.
- **The synthesis often lists the cards in turn** instead of synthesising.
- **Approving a cell edit says "Undo it from the Changes panel"**, but its toast has no Undo button.
- **The analysis widget is narrated twice in a build**, about 2k extra tokens.
- **`PUT /canvas` accepts `file`, `link` and `group` nodes**, but the Flow tab saves them back as text notes and loses `url` and `file`.

### Ship

- **The notebook's 5 MB size target isn't checked** (TRD §13): neither the exporter nor `eval notebook` measures it.
- **At phone width, KPI titles are cut to a few letters.**

### Look and feel (UI/UX brief)

Each of these carries a "Not built yet" marker in the brief's section.

- **Motion** (§2.4): only the Bklit charts animate. Widgets, cards, the thread and canvas nodes have no enter animation, and drawers don't slide in.
- **Layout** (§3.1): the centre has no 560px minimum, and the right panel can't collapse at 1024px and up (also PRD P0-03). The slide-over backdrop has no dark-mode variant (`AppShell.tsx`).
- **Shadows** (§2.3, §10): dialogs, popovers, the chart readout and slide-overs use `--shadow-overlay`, and canvas card nodes have a hard-coded `rgba(0,0,0,0.04)` shadow (`FlowTab.tsx`), against "no card shadows". Drop the node shadow; decide on the rest.
- **Buttons** (§4.1): secondary buttons show no hover change (`hover:bg-muted` equals `--secondary`); the loading spinner sits beside the icon instead of replacing it (`ui/button.tsx`). Most icons use lucide's 2px stroke, not 1.75, and many icon-only buttons have no tooltip (`JobTray.tsx`, `DatasetMenu.tsx`, `WidgetShell.tsx`, `ChatBar.tsx`, and the ✎, × and chevrons in `CleanPlanPanel.tsx`).
- **Target sizes** (§4.1): the inline icon buttons in the cleaning plan and the Changes panel are about 18px (`p-0.5` plus a 14–16px icon), under 32 × 32, and the CSV toolbar's text buttons are `size="sm"`, 28px (`CsvTab.tsx`), under 36.
- **Discard edits in the cleaning plan** (§6) throws away the CSV tab's pending edits with no confirmation; the context row's Discard confirms (`SaveActions.tsx`). Reuse that dialog.
- **Tooltips** (§4.11): outside the charts every tooltip is the browser's native `title`, so none of the styling applies. Add a Tooltip primitive. Error toasts close after 4 s (§4.10).
- **Widgets** (§4.3, §5.5): a related widget gets the border but no half-strength spotlight; the footer has no "updated 2s ago"; Bklit siblings fade to 40% on hover, not 60%; pie and ring slices don't fade when filtered; tooltip numbers aren't mono.
- **Hover linking** (§6) fires and clears at once, with no 80 ms / 120 ms delay (`WidgetShell.tsx`, `StoryCard.tsx`).
- **Story panel** (§4.5): a synthesis card has the muted overline and no "Cites n cards"; only its canvas node has both (`StoryCard.tsx`).
- **Chat** (§4.8): proposals have no "Show code" disclosure or impact line, though `Proposal.impact` exists (`ChatBar.tsx`); the selection chip has no `--accent-soft` fill; on the empty library the bar sits 48px under the pitch, not 24px (`EmptyLibrary.tsx`).
- **Empty states** (§4.13): the dashboard's and the canvas's have no icon or primary action.
- **Export** (§5.13): no "Save and export" button (the note says to save first), and the Flow palette and chat export entries lack the `book-open` icon.

## 6. Evals and tests

- **The ask eval passes contradictory answers** (`eval/ask.py`): any cell of any table can match; `text_any` passes on one word, so "significant" and "could be chance" both pass; a source can stand in for an answer. The grounding eval checks each chip against its fact, not what the words claim between chips.
- **The job-polling helpers don't check the status code** (`test_jobs.py`, `test_notebook.py`, `test_stories.py`), so a `429` under load becomes a `TypeError`.
- **No test asserts the `run.updated` event.**
- **The ask eval has few unanswerable questions**: three of 61 in `samples/eval/ask_questions.yaml` (an income the file doesn't record, a forecast, a delete request), so PRD §4's "≥ 95% of unanswerable questions answered with an honest can't" isn't really measured. Done: more of them, on all three files.
- **No component tests for conflicts and Undo**: `SaveActions`' conflict dialog, `ChangesPanel`'s Undo and the CSV tab's save path. `cleaning.test.tsx` covers only the new-rows toast after a save, and `csvtab.test.tsx` the read-only lock and Find.
- **Untested edge cases**: large integers, a DATE with a time, `nan` and booleans in edits; the same cell twice in one batch; hand-edit protection after an undo; conflicts mid-save; a huge offset or version; `state_rev` after undo; the path with no `LLM_BASE_URL`; `ImportPreviewDialog`'s options round trip; slide-over keyboard behaviour.

## 7. Docs (Rule 1)

- **`FEEDBACK.md`'s Bklit and Glide spike records say "It passed"**, though a pass rule wasn't tried: shared hover (Bklit), and range paste (Glide; not needed after cut 5). Done: "pass rule partly met".
- **TRD §7.1 step 1 and §10 (`MAX_UPLOAD_MB`) say an upload over the limit is aborted while streaming**, but Starlette spools the multipart body before the handler runs (not probed).
