# Sherlock · Backlog

Everything still open after the Day 1–9 reviews and the docs audit against the code (both 2026-10-25), in one list. A tag like "D7 F2" is finding F2 of the Day 7 review. An item the audit found is tagged with the doc section that specifies it, like "(App Flow §3.3)": that section carries a "Not built yet (docs/BACKLOG.md)" marker pointing here.

The nine review reports (`reviews/day-1.md` … `day-9.md`, with their screenshots) were removed from the tree on 2026-10-25, after their open findings were copied here. Each report keeps its evidence, live transcripts and token spend in git history: `git show 9051876:reviews/day-7.md`.

Fixed findings aren't listed. Each fix is in its commit, in its doc note (in the TRD usually "Day N review Fx, fixed …") and in `docs/LOG.md`. When you fix an item here, remove its line in the same commit. File and line references are as of the review, so check the code before relying on them.

---

## 1. Before submitting (Day 10; plan §2 Day 10, PRD §12)

The owner's, unless a line says otherwise.

- **Make the repo public** (D9 C1, a stage-one blocker). `n1mk1/sherlock` was still private on 2026-10-25. Run the secret scan first, and put the live URL in the About box's website field.
- **The video**: public on YouTube and under 3:00, since the live rules say "less than three (3) minutes". Plan §9 is written to finish by 2:55 (D9 C4).
- **The Devpost text** in plan §7's order, with the track set to Best Apps and Agents (D9 C6, C10).
- **Finalize `FEEDBACK.md`** for the feedback prize (D9 C11).
- **The user tests**: the three cold-start sessions and the by-hand half of the baseline. The tables in `docs/USER-TESTS.md` are still empty, and Potential Impact leans on them (D9 C6).
- **The README** (D9 F6, F7, C8). Slice 9 (2026-10-26) wrote the Token Factory sentence ("Where Token Factory sped up the build"), named the `llm_calls` purposes, and gave the per-role medians, the tokens per chat message and the time per notebook a committed source (`sherlock llm stats` in `FEEDBACK.md`, the notebook eval in TRD §14). What's left:
  - Ultra's cost per sample run, from the account's console (the README still says "on the account's console"), so plan D9.3's cost per role is complete;
  - the medians come from the local database's 111 calls of 2026-10-25, before the overnight changes. Before submitting, run `uv run sherlock llm stats` against the deployed app's database (a Render shell in `/app/api`) and refresh the README's medians and tokens per message from it;
  - read the Token Factory sentence over for the Devpost text, which says the same in its own words.
- **The Tavily key, for Best Use of Tavily** (plan open decision 1). Get a key (the Nebius Builder Program includes Tavily credits) and set `TAVILY_API_KEY` in Render's environment (it's declared `sync: false` in `render.yaml`) and in `.env`. Until then no Tavily call runs in the deployed app, so the bonus can't be claimed (PRD §12.4). Then run `uv run sherlock eval web --live` through `eval-locked.sh` and record the result in `FEEDBACK.md`: the offline run uses hand-made Tavily stand-ins, not real replies (TRD §14).
- **Keep it running through judging** (D9 C5): Render's paid plan and the Token Factory credit until Dec 15, 2026 (PRD §9).

## 2. Decisions only the owner can make

- **Type-aware cell editors and autocomplete** (PRD CSV-5, P0; D5 O1). Every cell edits as text: no category dropdown (`GET /columns/{col}/values` exists for it), boolean toggle, date picker, number check before saving, or autocomplete from the column's values. Cut 5 doesn't cover these. Build them, or record the drop in the PRD (plan §2.0: any further drop needs a PRD change).
- **Multi-column sort, column resize and auto-fit** (PRD CSV-8, P0). The grid sorts by one column, with fixed widths (`Grid.tsx`). Plan §5's cut 5 ("beyond … sort") may cover these, but plan §2.0's exact list doesn't name them. Say which.
- **`/` with the chat bar set to Hidden.** PRD ASK-1 says `/` summons the bar; UI/UX §5.11 says Hidden removes it, which is what's built (`/` does nothing). Pick one.
- The cut-5 P0s (CSV-2, 3, 4, 6, 7, 9, 10, 11, 14) and every other P0 a cut removed now carry a "Removed by cut N" marker in the PRD (the audit); their priorities are unchanged.
- **Imbalanced two-class targets** (D7 F3). The verdict compares accuracy only, so with 3% positives a model with AUC 0.95 reads "weak, 0.0 points better". Use AUC or balanced accuracy for the verdict and the one-column rule, or require both to agree. That's a PRD and TRD change.
- **Where the story suggestion goes** (D6 F14). Plan D6.3 says side by side. App Flow §11 step 5 says "your text vs the AI's revision". UI/UX §4.5's as-built note says under the body, which is what's built. Pick one; the other docs then add a line saying so.
- **"Budget exceeded with zero steps"** (D3 L8). App Flow §5 says it returns to the offer. TRD §7.2 and the code build the dashboard anyway.
- **Specified pieces no cut covers and nobody built** (the audit). Build each, or record the drop (a P2 label, or a PRD change for a P0):
  - TRD §7.4 steps 1–2: Welch's t, Mann-Whitney, Cohen's d and a trend slope on fact sheets (chat's `ask_stats` computes them, the sheets don't), and the correlation (0.4) and dependency (0.6) relations between widgets;
  - TRD §12: JSON logs with the request ID on every line, and `GET /metrics`;
  - TRD §10–§11: `JOB_BACKEND=nebius` and `python -m sherlock.jobs.run` (TRD §1 calls it optional);
  - TRD §14: the mocked clean → build → stories run on all five files of the end-to-end set (it runs on Titanic and small made-up files).
- **Tavily context on anomaly cards** (PRD STORY-9, plan T-4, Tier 3). Not built: its query would hold a period (a month or a year) taken from the data, which plan open decision 3 leaves to the owner. Say whether a period may go out, shown before it's sent, or whether T-4 stays names-only.
- **Narration temperature** (TRD §8.3). The spec says 0.4; every narrate and synthesis call runs at 0 (`stories/narrate.py`, `stories/synthesis.py`), and §8.3's as-built line says so. Keep 0 and change the spec, or pass 0.4.

## 3. Honesty and Rule 2

The five demo-path bugs (D6 F2, F3; D7 F1, F4; D8 F1) were fixed in `f064fd9`. Still open:

- **Noise can "beat the baseline"** (D7 F2). The verdict only checks `lift >= 0.02`, and at 150 rows one row is 3.3 points of a fold: 3 of 30 pure-noise sets passed. Require a clearly positive fold-wise lift (`core.baselines` would return per-fold scores), or scale the threshold with n.
- **A number that settles a text target isn't flagged as a leak** (D7 F5). The correlation check runs only for numeric targets, and the purity check only on non-numeric features, so `refund_amount > 0` exactly when `churned = yes` becomes the top driver.
- **A target computed from the features** (D7 F7). `revenue = units × unit_price` is reported as R² 0.9995 and "beats the best simple rule". Warn on held-out R² > 0.99 or accuracy > 99%.
- **"95% interval"** (D7 F6). Mean ± 1.96·sd/√folds understates the spread (the folds overlap; the t-quantile for 5 folds is 2.78), and the winner of three models is scored on the folds that picked it. Call it "fold spread (approximate)" or use a t-quantile, and add the optimism to `limits`.
- **Number words still accepted** (D8 F1): "one", "single" and "pair" ("Only one group", "A pair of groups"). TRD §7.4 lists ordinals and archaic words as gaps by design, but not these.
- **`is_nvidia_embed` admits non-NVIDIA IDs** (D9 F10; latent, since embeddings are off). `llm/models.py` accepts "embed" plus "nvidia", "nv-" or "nemotron" anywhere in the ID, so `someorg/conv-embed-v1` passes. Require the `nvidia/` prefix as `is_nemotron_chat` does, and change TRD §3.5 with it.
- **Partial dependence for 3+ classes says "predicted <target>"** (D7 F9). It's the share predicted as the most common class.
- **"Sixfold" to "ninefold" pass the number-word check** (TRD §7.4). The spec refuses twofold to tenfold, but the pattern in `stories/narrate.py` lists only two-, three-, four-, five- and tenfold.
- **An outdated synthesis doesn't come back by itself** (TRD §7.4.2, plan 1.3). Under "Ask first" a synthesis citing an outdated card is marked `outdated` with it; refreshing the cards leaves the synthesis `outdated` until its own Refresh. Plan 2b.6 rewrites syntheses under "Automatic"; under "Ask first" a cue on the synthesis once its sources are current would help.
- **Replay doesn't re-run the Cleaner's verifiers** (TRD §7.8). `steps/replay.py` checks only the file, `_row_id` and the row count, though the spec aborts a replay when "its verifiers fail". Run `verifiers.verify` for each replayed cleaner step.

## 4. Accessibility (UI/UX §2.4, §6, §8)

- **Column notes are hover-only** (PRD LOAD-7). Glide draws the CSV header on a canvas with no keyboard focus, so a keyboard user can't open a column's note there; chat's "what does <column> mean?" answers with the same note.

- Click-to-filter needs a mouse, and a click with no `mousemove` before it only focuses the widget (D4 F2, D7 F20). Touch isn't checked on a device.
- Widgets and story cards can't be focused, so card ↔ widget linking has no keyboard path, and a widget's menu has no keyboard route (D4 F11, D6 F13). Canvas nodes can be focused (React Flow's default), but they have no accessible name, only `role="group"` (D8 F12).
- Bklit charts have no text alternative: their SVGs are `aria-hidden`, and "Show as table" is the only route. The custom charts have one (D4 F10, D6 F13).
- Reduced motion: the chip pulse is a fixed 400 ms (`StoryCard.tsx`), `scrollIntoView` is smooth, and `animate-spin`, `animate-pulse` and the Bklit bars ignore it (D4 F10, D6 F13). Several custom chart hooks check `useReducedMotion` now, so recheck before fixing.
- Slide-over panels below 1024 px stay in the tab order, don't trap focus, and don't close on Esc (D2 M8).
- Shared hover between two charts isn't built. It's one of the Bklit spike's pass rules (D1 #3, D4 F18, D6 F13).
- The card editor's `/` picker has `role="listbox"` with no options or arrow keys, and `/` is always swallowed, so "and/or" can't be typed (D6 F12).
- The widget drag handle works with a mouse only: it's a named `role="img"` now (live test 2026-10-26, F17), but react-grid-layout gives the layout no keyboard move (D4 F17).

## 5. Bugs and gaps by area

### Identity, limits, operations

- `POST …/use-as-is` (the Clean it myself button) and `POST /jobs/{jid}/retry` start model-calling jobs without `llm_rate_limit`, and so does an upload whose profile job queues the build (D1 #5). So does `POST /cards/{cid}/refresh` (the audit). The token budgets still apply. TRD §15 lists the routes that do count.
- `JOB_BACKEND=nebius` is accepted and silently ignored, so jobs run locally (TRD §10). Refuse it at startup until it's built.
- `PATCH /widgets/{wid}` with `{ prompt }` answers `422` with the stale message "needs chat, which isn't built yet", though `update_widget` exists (TRD §4.5). Route it to `update_widget` under `llm_rate_limit`, or fix the message.
- Widget and card restore have no 10-minute check, unlike dataset restore; they work until the purge runs (TRD §4.5–§4.6). Low priority.
- `folder_bytes` isn't recomputed when a run or an export finishes, so run artifacts and notebooks count against the storage limit only after the next purge pass (Schema §4).
- **The Nemotron fallback doesn't cover a full Super gate** (plan 2b.8, TRD §3.5). Super → Ultra happens when Super's breaker is open or its next retry would come too near the deadline, but a Super call waiting for a free slot (all `LLM_CONCURRENCY_MEDIUM` busy) still waits up to its deadline and fails with "This answer ran out of time." Sending it to Ultra after part of the wait would need a rule for how long to wait first, and would put chat's overflow on Ultra's two slots, which the Cleaner uses.
- `llm_calls` is never purged. The app-wide budget's sum before every model call reads only today's rows through the `created_at` index (migration 004), but the table, and the receipts' and spend figures' reads of it, still grow with use. A purge would need a retention rule the budgets and the spend figures can live with (say, rows older than the 30-day dataset retention). A cost that grows with use, not a mismatch.
- `uv run sherlock clean sample` times out after 900 s. With the cached seed, the sample is cloned already `ready`, and the CLI waits for `offer` or `failed` (`cli.py`, `routers/datasets.py`). Set `SAMPLE_SEED_DIR=off` inside `clean()`, or import `samples/titanic3.csv` directly. Also, the `--sets` help names only `corruption` and `ask`, though `notebook` and `grounding` take it too.
- `scripts/live_check.py --files all` says it checks that each notebook "rebuilds the version", but it only executes it (D9 F12). `sherlock eval notebook` does compare values.
- The focused widget's title is read without a dataset check (`agent/loop.py`, `SELECT title FROM widgets WHERE id = ?`), so another user's title could reach the prompt (D4 F7). Low risk: the IDs are random ULIDs.

### Ingest, rows and profile

- The import preview doesn't detect the header row or skip rows, and sends only the options the user changed, so the server's sniffed `skip_rows` can stack on a header row the user set (D2 M6). App Flow §3.2 and PRD LOAD-2 say the header row is auto-detected.
- Edits (`rows/edits.py`): the same cell twice in one batch keeps the first one's `invalid` mark and history; `2020-01-01 13:45` in a DATE column drops the time; `nan` in a DOUBLE is accepted and marked changed; restoring a row that isn't quarantined commits an empty version (D2).
- A conflict that lands between `save()`'s check and `commit_step`'s comes back without `conflicts`, though TRD §4.3 says "always" (D2).
- `offset=10**20` or `version=10**20` on `GET /rows` is a 500, not a 422 (D2).
- `ingest/sniff.py` `header_names` reads one physical line, so a quoted newline in a header splits it (D2).
- A 3-line cp1252 file was detected as cp775 (D2). Longer files are fine, and the preview can override the encoding.
- `cleaning/detectors/impossible_values.py` `NON_NEGATIVE` has no word boundaries, so `average_temp`, `account_balance` and `percentage_change` count as non-negative quantities (D2).
- `profile/infer.py` `TARGET_NAMES` includes `survived` (D3 L6, Rule 4).
- Web: CR-only line endings with Skip rows > 0 say "no data rows"; error toasts dismiss after 4 s, though Brief §4.10 says they stay; the status badge's hover text appears only on `failed` (App Flow §14); the empty-state pitch uses `text-foreground-2`, not `--muted-foreground` (Brief §5.1) (D2).
- LLM client: `embed` isn't in the client's `ROLES` (D2).
- The import preview's delimiter list has no free-text "Other"; it shows "Other (…)" only when the detected delimiter isn't one of the four (App Flow §3.2).
- While profiling, the chat bar is disabled, so questions don't queue as App Flow §3.3 says (`ChatBar.tsx`).
- DuckDB connections opened with `duckdb.connect(":memory:")` rather than `storage.new_duckdb` have no memory cap and spill to `./.tmp`, which the `app` user can't write in the image (TRD §3.2): `steps/diff.py` (`diff_versions`, run on every commit), `rows/edits.py` (`conflicts`, the edit batch's `_row_id` table), `cleaning/loop.py` (`_read`, the selection scope) and the `DESCRIBE`-only helpers. Pass `settings` and use `new_duckdb`. The sandbox worker's own connections run outside `/data` and stay as they are.
- The jobs tray prints a failed job's raw error (`JobTray.tsx`), the DuckDB text the failed-profile screen now keeps behind "Technical details" (App Flow §3.3, §15).
- The "Profiling failed" screen has no Delete button of its own; Delete is only in the dataset and library menus (App Flow §3.3; `StatusScreens.tsx`). Reuse `ConfirmDelete`.
- `Dataset.cleaning_progress` is never filled, so after a reload the library shows "cleaning 0%" until the next `job.progress` (TRD §4.2; `routers/datasets.py`, `LibraryPanel.tsx`). Fill it from the running clean job's progress.

### The Cleaner

- The corruption benchmark can't see over-quarantining, since harm counts only changed values (D3 M3). Count an undamaged row that gets quarantined as harm, or add a "rows lost to quarantine" column.
- Later versions' `issues` rows keep no `outcome`, while the report reads `from_version` (D3 M4).
- The end-of-run report can be skipped when the build finishes fast; App Flow §5 says it shows for 3 seconds (D3 M5).
- Smaller (D3): `counts.found` can be lower than fixed + flagged + skipped (L1); the budget line lags by the issue in progress (L2); the diagnose context includes decisions from undone steps (L3); the ambiguity vote counts option indexes across samples whose option lists differ (L4); the offer's summary leads with issues that are never fixed (L7).
- The `flag_rows` helper has no effect: its docstring says the step gets flagged, but nothing reads the flags it records (TRD §7.2). Force the gate to `flag`, or drop the helper.
- The critic prompt says "Effect on a sample", but the effect it's given comes from the full data (`cleaning/prompts/critic.txt`).
- Exact and near duplicate rows share one issue key, `duplicates|None` (`detectors/duplicates.py`), so the cleaning plan shows, and the Cleaner attempts, only the more severe of the two; the other is never tried or listed (App Flow §4.1, TRD §4.4; `cleaning/plan.py`, `loop.py` `handled`). Give near duplicates a key of their own.
- Chat answers given during cleaning don't say which version or step they read ("as of step 5", App Flow §5).
  - Since plan 2b.4 every message carries `version` (TRD §4.9) and older answers lose Add to Flow, but the thread shows no "v3" mark on an answer from an older version; `ChatBar.tsx` would need the dataset's current version beside each message.
- The CSV tab's Clean with AI (`CleanButton` in `CsvTab.tsx`) has no dot before the first clean, and neither the cleaning plan nor the cleaning report offers to include hand-edited cells ("Include these next time"): `api/queries.ts` always sends `include_user_edited: false` (App Flow §4, §8.4; PRD CLEAN-8).

### Dashboard and chat

- **Some outside-world questions can still go to the file** (the web eval's live recording, plan T-6): with reasoning off Nano doesn't always route the same question the same way. In the last recording, "what are the latest trends in retail pricing this year?" went to `ask_data` once (a monthly average of the file's unit price) and "outside this file, what return rates do online retailers usually report?" to `ask_why` once; both went to the web in the other passes. TRD §8.1's guards catch a meaning question with no meaning word and a history with no change word, not these. The answer is about the file instead, never an error and never data sent.
- The 20-widget warning shows only from the Add widget drawer. Duplicate, Pin and chat's `create_widget` don't return or show it (D4 F4; PRD DASH-10).
- On a wide file the 60-candidate cap cuts in generation order, so trends and tables can be dropped before they're scored (D4 F5).
- Pinning a table pins the first result's query and drops the answer's `selection_id` (D4 F6; API only, since the UI offers Pin on charts).
- Compose needs a repair on about a third of answers (D4 F8), and one live answer came back with no prose: "Here is the result (3 rows)." (D9 F16).
  - A cause, seen again live on 2026-10-26 (`live_check`, "average fare by class", 33 s): the model labelled the result's alias instead of the file's column, `value:class:1` for `pclass`, which `compose.label_text` refuses ("names no column or value of this file"); the repair failed too, so the answer fell back to the table. Accepting a value label on a result column that maps to a file column, or saying in the compose prompt that labels name the file's columns, not the query's aliases, would fix this case.
- Inline rename may submit twice, and Esc may commit through `onBlur` (D4 F16, unverified).
- The empty-widget message says "No rows match the current filter" with no filter set and has no Clear filter link; "Show as table" resets on reload (UI/UX §5.5); chat answers have no copy button (App Flow §10.2) (D4 F17).
- `ask_meaning` drops the general block without a word when the model returns nothing, though TRD §8.2 says it's shown (D7 F13).
- "The model" means the newest run once another answer comes between (D7 F14, `insight.pick_run`). Since plan 1.3 an outdated run it picks is labelled "(version N, outdated)" with a Re-run sentence, but a done run of the same target isn't preferred over it.
- Once, an edit asked right after a question in the same thread got no proposal within 90 s (D9 F5, not reproduced). Worth one scripted repro.
- The build shows no skeleton widgets, no cards streaming in and no "6 of 8 widgets" banner: the grid appears all at once (App Flow §6).
- The version pill isn't clickable (App Flow opens the Changes panel from it), and there's no Filter button or filter builder; a filter comes only from clicking a chart (App Flow §7.1, UI/UX §3.2, §5.5).
- Add widget has no histogram template; the templates are Bar, KPI and Table (App Flow §7.3).
- "The closest I can answer: …" is plain text, not a button that asks it (App Flow §10.2).
- Hitting the 40k-token message budget mid-answer throws away the earlier steps' results and returns only the budget sentence; TRD §8.1 says to compose what exists with a note (`agent/loop.py`).
- Proposals expire lazily: a stale one keeps its Approve button until it's clicked and answers `409`, instead of reading "Expired: the data changed since" (App Flow §10; `agent/actions.py`). Expire pending proposals in `commit_step`, or compare against `current_version` when listing them.
- A wide file gets no note that the dashboard used only its 30 most informative columns (App Flow §18; the builder keeps `columns_used` in the job result only).
- Save doesn't retry by itself once the connection is back; pressing it again works (App Flow §18).
- Questions ignore the cells selected in the CSV tab: the chip says "n rows selected" and the loop never reads `selected_cells` (PRD CSV-13; `ChatBar.tsx`, `agent/loop.py`). Create a selection from their `row_ids` and pass it as `selection_id`.
- A refusal never offers a closer question: `NOT_YET` is empty, so `_suggestion` never runs (PRD ASK-8; `agent/loop.py`, e.g. `insight.py`'s refusals). Append the suggestion to every can't-answer.
- A name that matches two columns about equally ("price" with `unit_price` and `total_price`) isn't asked about: the SQL step picks one, and a clarification comes only when it can't write the query (plan 2.8, TRD §8.1). Asking before the query would interrupt answers the SQL step reads correctly ("survival" for `survived` scores 75), a risk to the 49/50 ask eval; it needs its own eval run, with the ask eval's questions, before it ships.
- **Chat's route guards are English keyword rules** (TRD §8.1, the live test of 2026-10-26): rankings, quarantine questions, "how do I …", an explicit web search, delete requests, row edits and forecasts are caught by regular expressions on English wording. The same questions in another language (chat answers in Spanish) go wherever Nano routes them. A delete request worded without a leading verb ("I want the male rows gone") isn't caught either.
- A question that asks for every row with no condition ("select everything from <a table>…", live 2026-10-26) gets `find_rows` with the predicate `TRUE` and "<n> rows match", every row listed. Nothing is read outside `t`, but the answer reads as if it had done what was asked; `find_rows` could say a predicate that keeps every row selects nothing in particular.
- "Why did <a group> …?" adds the group's breakdown only for a number or yes/no target; a category target gets the column's rank among the factors without its per-group shares (`insight._group_part`).
- The substituted-column check (`Toolkit.substituted`) only sees a word the router listed as a column entity; when Nano lists none, a swapped column ("income" read as `fare`) still depends on the SQL prompt's rule alone. A legitimate reading named unlike its column ("port → embarked") costs one more Super call.
- The result check's repair (plan 2.7) costs one more Super call on an honest empty answer (a question that really matches no rows), about 3–5 s. Telling an expected empty result from a wrong filter needs more than the result: the literal check covers the common case.
- A widget made in chat isn't highlighted when it lands, and KPI and table answers have no link to their widget (PRD DASH-8; `ChatBar.tsx`).
- A deleted widget's card stays in the Stories panel until the overview updates (PRD DASH-9; `api/queries.ts`).
- The "changed" badge is set only when a stories job's reason is `cascade`, so any card re-told for another reason gets none (PRD STORY-6; `stories/service.py`). D6 F15 is the analysis-card case of this.
- On the canvas, notes and edge labels never reach the model (PRD FLOW-5; `FlowTab.tsx`, `agent/flow.py`). A note's text is saved only on blur (FLOW-1).
- The overview accepts 2 bullets, though PRD asks for 3–5 (`stories/narrate.py`).
- The CSV tab doesn't remember its scroll position or selection (PRD §7.11; `DatasetPage.tsx`).

### CSV tab

- No "Export up to step k" after a failed export (D5 O2; App Flow §17.5). The backend supports `up_to_step`.
- The cleaning plan's pending-edits note has Discard edits but no Save (App Flow §8.4; `CleanPlanPanel.tsx`); its scope labels "Whole dataset" and "Rows added since the last clean" have no counts, and the selection reads "Current selection (1 rows)"; the Changes panel reads "1 cells" (`ChangesPanel.tsx`) (D5 O3).
- "Keep mine" on a row the newer version deleted can't be saved (`422`) and blocks the buffer until the line is removed (D5 O5, from the code).
- For about a second after Save, the grid shows the old version's rows under the new header (D5 O6).
- Select-all offers to delete only the rows whose pages are loaded (D5 O7).
- The undo confirmation doesn't say which replayed steps touch the same columns (D5 O8; App Flow §8.5).
- Find shows at most the rows of the first 10,000 matches (D5 O9).
- An invalid edit reads "age → abc" in the step's list, though it was saved blank and flagged (D5 O10).

### Stories

- A renamed dataset can get a stale cached notebook: rename doesn't bump `state_rev`, and the name isn't in the export's cache key (`routers/datasets.py`, `notebook/exporter.py`), so `DATA_PATH` still names the old `-raw.csv`. The status isn't in the key either, so PRD NB-1's "exported during cleaning" note can be missing. Bump `state_rev` on rename and on status changes.
- PRD NB-2's "no data" note is in the notebook's second cell, not its first (`notebook/cells.py`). `RANDOM_SEED` is set there but never used.
- The notebook puts edited card text into Markdown raw. Escape `\`, `*`, `_`, `#`, `<`, `>` and `&` in text runs (D6 F9; TRD §7.7).
- "Change view" never offers heatmap or scatter, so a heatmap switched to bars can't go back (D6 F10).
- The cascade progress line clears only on `cascade.done`, so leaving mid-cascade, or a job that dies, leaves it showing (D6 F11).
- Editor chips show the value saved with the card, not `Card.facts`, and unverified chips aren't dashed (D6 F12).
- An analysis card re-told after a cascade gets no "changed" badge, because its job's reason is `widget` (D6 F15).
- Labels repeat the model's noun: "Passenger class pclass 1", "Fare fare values" (D6 F16).
- The story panel: suggestion chips have no handler; the outdated badge can queue repeat jobs; hover isn't cleared on Edit layout or widget delete; the evidence query isn't invalidated on `card.updated`; the drawer shows no run for an analysis fact; the panel says "Stories appear once the dashboard is built" when the request fails (D6 F17).
- An edited card doesn't say that its chips re-render from the latest sheet (D6 F21; by design, TRD §4.6).
- The cascade toast leaves out `outdated` and `errors` (D6 F23).
- A group's size for the tiny-group rule (TRD §6.4, `facts.MIN_GROUP`) is unknown when the widget's group keys aren't its query's leading columns, or for a UNION; such a group can still be named highest. Chat answers (`agent/`) don't apply the rule at all: "Which port had the best survival?" can still answer with a 2-row group (live test 2026-10-26, finding 9).
- Old overview and widget cards keep "None" and tiny-group facts until they are told again (a refresh, a cascade or a rebuild); nothing re-tells them on deploy.
- Cramér's V uses the Yates-corrected χ² on 2×2 tables, and Cohen's d the unweighted mean of the two variances (D6 F19, D7 F21). Both understate a little. State them in TRD §8.2, or use `correction=False` and the pooled SD.

### ML

- The progress labels misreport the work: "setting baselines" and "testing models" are sent back to back, and "explaining" takes about half the run (D7 F8).
- Constant columns stay in as features with importance 0 (D7 F10).
- The profile still gives a repeating free-text column the role `target_like` (`profile/infer.py` checks the last column's distinct count before its text length), and chat reads that role directly: `agent/loop.py` takes the first `target_like` column, and `insight.ROLE_WORDS` calls it "it looks like an outcome". The DataCard's `target_candidates`, the builder and the stories leave it out (`ml.registry.target_ok`; live test 2026-10-26, finding 10).
- `GET /recipes` doesn't give the per-method compatibility TRD §4.8 promises (D7 F11).
- The setup form's number fields drop an out-of-range value on each keystroke, so "120" can't be typed into Time budget (D7 F18).
- An analysis widget's scope chip says "Some rows", not the filter (D7 F19).

### Flow

- Fit view and new syntheses ignore the open chat thread, which covers the lower half of the canvas (D8 F5, D9 F15).
- "I added a synthesis of 3 cards" counts the selection, not the cards cited (D8 F6).
- The synthesis often lists the cards in turn instead of synthesising (D8 F8).
- Approving a cell edit says "Undo it from the Changes panel", but its toast has no Undo button (D8 F9).
- The analysis widget is narrated twice in a build, about 2k extra tokens (D8 F10).
- `PUT /canvas` accepts `file`, `link` and `group` nodes, but the Flow tab saves them back as text notes and loses `url` and `file` (D8 F13).

### Ship

- At phone width, KPI titles are cut to a few letters (D9 F15).

### Look and feel (UI/UX brief)

Each of these carries a "Not built yet" marker in the brief's section.

- **Motion** (§2.4): only the Bklit charts animate. Widgets, cards, the thread and canvas nodes appear with no enter animation, and drawers don't slide in.
- **Layout** (§3.1): the centre has no 560px minimum, and the right panel can't collapse at 1024px and up (also PRD P0-03). The slide-over backdrop has no dark-mode variant (`AppShell.tsx`).
- **Shadows** (§2.3, §10): dialogs, popovers, the chart readout and slide-overs use `--shadow-overlay`, and canvas card nodes have a hard-coded `rgba(0,0,0,0.04)` shadow (`FlowTab.tsx`), against "no card shadows". Drop the node shadow; decide on the rest.
- **Buttons** (§4.1): secondary buttons show no hover change, since `hover:bg-muted` equals `--secondary`; the loading spinner is added beside the icon instead of replacing it (`ui/button.tsx`). Most icons use lucide's 2px stroke, not 1.75, and many icon-only buttons have no tooltip (`JobTray.tsx`, `DatasetMenu.tsx`, `WidgetShell.tsx`, `ChatBar.tsx`, and the ✎, × and chevrons in `CleanPlanPanel.tsx`).
- **Target sizes** (§4.1): the inline icon buttons in the cleaning plan and the Changes panel are about 18px (`p-0.5` plus a 14–16px icon; `CleanPlanPanel.tsx`, `ChangesPanel.tsx`), under the 32 × 32 minimum, and the CSV toolbar's text buttons are `size="sm"`, 28px (`CsvTab.tsx`), under 36.
- **Discard edits in the cleaning plan** (§6): it throws away the CSV tab's pending edits at once, with no confirmation; the context row's Discard confirms (`SaveActions.tsx`). Reuse that dialog.
- **Tooltips** (§4.11): outside the charts, every tooltip is the browser's native `title`, so none of the styling applies. Add a Tooltip primitive. Error toasts close after 4 s (§4.10; also D2).
- **Widgets** (§4.3, §5.5): a related widget gets the border but no half-strength spotlight; the footer has no "updated 2s ago"; the empty message shows with no filter and has no Clear link (D4 F17); Bklit siblings fade to 40% on hover, not 60%, pie and ring slices don't fade when filtered, and tooltip numbers aren't mono.
- **Hover linking** (§6): it fires and clears at once, with no 80 ms / 120 ms delay (`WidgetShell.tsx`, `StoryCard.tsx`).
- **Story panel** (§4.5): a synthesis card has the muted overline and no "Cites n cards"; only its canvas node has both (`StoryCard.tsx`).
- **Chat** (§4.8): proposals have no "Show code" disclosure or impact line, though `Proposal.impact` exists (`ChatBar.tsx`); the selection chip has no `--accent-soft` fill; on the empty library the bar sits 48px under the pitch, not 24px (`EmptyLibrary.tsx`).
- **Empty states** (§4.13): the dashboard's and the canvas's have no icon or primary action.
- **Export** (§5.13): no "Save and export" button (the note says to save first), and the Flow palette and chat export entries lack the `book-open` icon.

## 6. Evals and tests

- The ask eval passes contradictory answers. Any cell of any table can match; `text_any` passes on one word, so "significant" and "could be chance" both pass; and a source can stand in for an answer (D4 F13, D8 F4). The grounding eval checks each chip against its fact, not what the words claim between chips.
- The job-polling helpers don't check the status code, so a `429` under load becomes a `TypeError` (`test_jobs.py`, `test_notebook.py`, `test_stories.py`; D5 O11, D7 F16).
- No test asserts the `run.updated` event (D7 F17).
- The ask eval has few unanswerable questions: since 2026-10-26 it has three (an income the file doesn't record, a forecast, a delete request) among 61, so PRD §4's "≥ 95% of unanswerable questions answered with an honest can't" isn't really measured. Add more to `ask_questions.yaml`, on all three files.
- The 11 questions added on 2026-10-26 (TRD §8.1) have been checked offline on recorded replies only (`tests/test_chat_routing.py`); `uv run sherlock eval ask` hasn't been run live since, so whether Nano and Super now answer them right, and the other 50 still pass, isn't measured.
- No component tests for Save, conflicts and Undo: `SaveActions` (with its conflict dialog), `ChangesPanel`, and the CSV tab's save path. `csvtab.test.tsx` covers only the read-only lock (D5 O4).
- Day 2's list of untested cases: large integers, a DATE with a time, `nan` and booleans in edits; the same cell twice in one batch; hand-edit protection after an undo; conflicts mid-save; a huge offset or version; `state_rev` after undo; the path with no `LLM_BASE_URL`; `ImportPreviewDialog`'s options round trip; slide-over keyboard behaviour.

## 7. Docs (Rule 1)

- `FEEDBACK.md`'s Bklit and Glide spike records say "passed", though a pass rule wasn't tried: shared hover, and range paste (not needed after cut 5). Say "pass rule partly met" (D1 #3, D4 F18).
- TRD §7.1 step 1 says an upload over the limit is aborted "while streaming", but Starlette spools the multipart body before the handler runs (D2, not probed).
