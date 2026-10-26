# Sherlock · Backlog

Everything still open after the Day 1–9 reviews (2026-10-25), in one list. A tag like "D7 F2" is finding F2 of the Day 7 review.

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
- **The README** (D9 F6, F7, C8):
  - one sentence on where Token Factory accelerated the work, which the live rules ask for in so many words (for example, one OpenAI-compatible endpoint for all three sizes, and strict JSON schema with one repair round);
  - a committed source for three numbers: the per-role median latencies (put the `llm_calls` query and its output in `FEEDBACK.md` or TRD §14), "78–116 s" per notebook, and "about 1,500 tokens per chat message";
  - plan D9.3's cost per role (Ultra's says "on the account's console") and the `llm_calls` purposes by name.
- **The new-user cap on the live site** (D9 H1). The Day 9 session was turned away with "Too many new visitors" four times after creating about 20 users, against a cap of 300 an hour. Render's logs have `new user: ip <hash>, N forwarded hop(s)` for each new user. Many hashes means the key is fine. One hash for everyone, or 3 hops (Cloudflare in front of Render), means every visitor shares one bucket, and a judge's first visit can fail.
- **Keep it running through judging** (D9 C5): Render's paid plan and the Token Factory credit until Dec 15, 2026 (PRD §9).

## 2. Decisions only the owner can make

- **Type-aware cell editors** (PRD CSV-5, P0; D5 O1). Every cell edits as text: no category dropdown (`GET /columns/{col}/values` exists for it), boolean toggle, date picker or number check before saving. Cut 5 doesn't cover these. Build them, or record the drop in the PRD (plan §2.0: any further drop needs a PRD change).
- **The P0s cut 5 removed are still P0 in the PRD** (D5): CSV-2 (the hover tooltip), CSV-3 (Ctrl+arrow, jump to row), CSV-4 (selection stats), CSV-6 (TSV copy and paste, fill down), CSV-7 (add above or below, duplicate), CSV-9 (replace), CSV-10 (column filters, quick views), CSV-11 (buffer undo/redo, Review changes) and CSV-14 (right-click menus). PRD §12.1 counts only the P0s the cut order didn't remove, so nothing is missing. A note beside each row would make the PRD say so itself.
- **Imbalanced two-class targets** (D7 F3). The verdict compares accuracy only, so with 3% positives a model with AUC 0.95 reads "weak, 0.0 points better". Use AUC or balanced accuracy for the verdict and the one-column rule, or require both to agree. That's a PRD and TRD change.
- **Where the story suggestion goes** (D6 F14). Plan D6.3 says side by side. App Flow §11 step 5 says "your text vs the AI's revision". UI/UX §4.5's as-built note says under the body, which is what's built. Pick one; the other docs then add a line saying so.
- **"Budget exceeded with zero steps"** (D3 L8). App Flow §5 says it returns to the offer. TRD §7.2 and the code build the dashboard anyway.

## 3. Honesty and Rule 2

The five demo-path bugs (D6 F2, F3; D7 F1, F4; D8 F1) were fixed in `f064fd9`. Still open:

- **The cleaning log shows the model's own numbers** (D3 M2). `expected_effect` is the log's main text, `diagnosis.cause` reaches skip reasons and decisions, and the critic's first concern becomes `flag_reason`. Build the line from the verifier report (cells changed, rows quarantined, issue count before → after) and keep the model's sentence as secondary text with no digits.
- **Noise can "beat the baseline"** (D7 F2). The verdict only checks `lift >= 0.02`, and at 150 rows one row is 3.3 points of a fold: 3 of 30 pure-noise sets passed. Require a clearly positive fold-wise lift (`core.baselines` would return per-fold scores), or scale the threshold with n.
- **A number that settles a text target isn't flagged as a leak** (D7 F5). The correlation check runs only for numeric targets, and the purity check only on non-numeric features, so `refund_amount > 0` exactly when `churned = yes` becomes the top driver.
- **A target computed from the features** (D7 F7). `revenue = units × unit_price` is reported as R² 0.9995 and "beats the best simple rule". Warn on held-out R² > 0.99 or accuracy > 99%.
- **"95% interval"** (D7 F6). Mean ± 1.96·sd/√folds understates the spread (the folds overlap; the t-quantile for 5 folds is 2.78), and the winner of three models is scored on the folds that picked it. Call it "fold spread (approximate)" or use a t-quantile, and add the optimism to `limits`.
- **Rankings the narrator states with no fact behind them** (D6 F8): "Ticket comes third", "decreases for lower classes and for males within each class". Give ranks as chips (`driver_2` is already a fact) and tell the prompt to say only what the listed facts show. Comparisons across cards are checked in code since `f064fd9`.
- **Number words still accepted** (D8 F1): "one", "single" and "pair" ("Only one group", "A pair of groups"). TRD §7.4 lists ordinals and archaic words as gaps by design, but not these.
- **A number word typed in a card edit isn't marked unverified** (D6 F18). `mark_unverified` matches digits only, so "zero" stays plain text.
- **`is_nvidia_embed` admits non-NVIDIA IDs** (D9 F10; latent, since embeddings are off). `llm/models.py` accepts "embed" plus "nvidia", "nv-" or "nemotron" anywhere in the ID, so `someorg/conv-embed-v1` passes. Require the `nvidia/` prefix as `is_nemotron_chat` does, and change TRD §3.5 with it.
- **An outdated synthesis goes into the notebook without a note** (D8 F7). Its chips render from the current sheets beside prose written about the old numbers. An outdated run gets a note; a card doesn't.
- **Partial dependence for 3+ classes says "predicted <target>"** (D7 F9). It's the share predicted as the most common class.

## 4. Accessibility (UI/UX §2.4, §6, §8)

- Click-to-filter needs a mouse, and a click with no `mousemove` before it only focuses the widget (D4 F2, D7 F20). Touch isn't checked on a device.
- Widgets, story cards and canvas nodes can't be focused, so card ↔ widget linking has no keyboard path, and a widget's menu has no keyboard route (D4 F11, D6 F13). Canvas nodes have no accessible name, only `role="group"` (D8 F12).
- Bklit charts have no text alternative: their SVGs are `aria-hidden`, and "Show as table" is the only route. The custom charts have one (D4 F10, D6 F13).
- Reduced motion: the chip pulse is a fixed 400 ms (`StoryCard.tsx`), `scrollIntoView` is smooth, and `animate-spin`, `animate-pulse` and the Bklit bars ignore it (D4 F10, D6 F13). Several custom chart hooks check `useReducedMotion` now, so recheck before fixing.
- Slide-over panels below 1024 px stay in the tab order, don't trap focus, and don't close on Esc (D2 M8).
- Shared hover between two charts isn't built. It's one of the Bklit spike's pass rules (D1 #3, D4 F18, D6 F13).
- The card editor's `/` picker has `role="listbox"` with no options or arrow keys, and `/` is always swallowed, so "and/or" can't be typed (D6 F12).
- The drag handle has no role, and the resize separators have no `aria-valuenow` (D4 F17).

## 5. Bugs and gaps by area

### Identity, limits, operations

- `POST …/use-as-is` and `POST /jobs/{jid}/retry` start model-calling jobs without `llm_rate_limit`, and so does an upload whose profile job queues the build (D1 #5). The token budgets still apply. TRD §15 should say that routes which start such jobs count.
- `/healthz` doesn't report the build's commit (D9 F13). A `GIT_COMMIT` build argument echoed there would make "the deployed commit matches `main`" one request.
- `scripts/live_check.py --files all` says it checks that each notebook "rebuilds the version", but it only executes it (D9 F12). `sherlock eval notebook` does compare values.
- The focused widget's title is read without a dataset check (`agent/loop.py`, `SELECT title FROM widgets WHERE id = ?`), so another user's title could reach the prompt (D4 F7). Low risk: the IDs are random ULIDs.

### Ingest, rows and profile

- The import preview doesn't detect the header row or skip rows, and sends only the options the user changed, so the server's sniffed `skip_rows` can stack on a header row the user set (D2 M6). App Flow §3.2 says the header row is auto-detected.
- Edits (`rows/edits.py`): the same cell twice in one batch keeps the first one's `invalid` mark and history; `2020-01-01 13:45` in a DATE column drops the time; `nan` in a DOUBLE is accepted and marked changed; restoring a row that isn't quarantined commits an empty version (D2).
- A conflict that lands between `save()`'s check and `commit_step`'s comes back without `conflicts`, though TRD §4.3 says "always" (D2).
- `offset=10**20` or `version=10**20` on `GET /rows` is a 500, not a 422 (D2).
- `ingest/sniff.py` `header_names` reads one physical line, so a quoted newline in a header splits it (D2).
- A 3-line cp1252 file was detected as cp775 (D2). Longer files are fine, and the preview can override the encoding.
- SSE: `jobs/events.py` `emit` inserts the row, then publishes, with no lock across both, so IDs can publish out of order (D2, from reading). A library stream that drops before its first event reopens live-only and can miss a `dataset.status` (D2).
- `cleaning/detectors/impossible_values.py` `NON_NEGATIVE` has no word boundaries, so `average_temp`, `account_balance` and `percentage_change` count as non-negative quantities (D2).
- `profile/infer.py` `TARGET_NAMES` includes `survived` (D3 L6, Rule 4).
- Web: CR-only line endings with Skip rows > 0 say "no data rows"; error toasts dismiss after 4 s, though Brief §4.10 says they stay; the status badge's hover text appears only on `failed` (App Flow §14); the empty-state pitch uses `text-foreground-2`, not `--muted-foreground` (Brief §5.1) (D2).
- LLM client: the `strip_reasoning` docstring claims to handle an unterminated `<think>`, and `embed` isn't in the client's `ROLES` (D2).

### The Cleaner

- The corruption benchmark can't see over-quarantining, since harm counts only changed values (D3 M3). Count an undamaged row that gets quarantined as harm, or add a "rows lost to quarantine" column.
- Later versions' `issues` rows keep no `outcome`, while the report reads `from_version` (D3 M4).
- The end-of-run report can be skipped when the build finishes fast; App Flow §5 says it shows for 3 seconds (D3 M5).
- Smaller (D3): `counts.found` can be lower than fixed + flagged + skipped (L1); the budget line lags by the issue in progress (L2); the diagnose context includes decisions from undone steps (L3); the ambiguity vote counts option indexes across samples whose option lists differ (L4); the offer's summary leads with issues that are never fixed (L7).

### Dashboard and chat

- The 20-widget warning shows only from the Add widget drawer. Duplicate, Pin and chat's `create_widget` don't return or show it (D4 F4; PRD DASH-10).
- On a wide file the 60-candidate cap cuts in generation order, so trends and tables can be dropped before they're scored (D4 F5).
- Pinning a table pins the first result's query and drops the answer's `selection_id` (D4 F6; API only, since the UI offers Pin on charts).
- Compose needs a repair on about a third of answers (D4 F8), and one live answer came back with no prose: "Here is the result (3 rows)." (D9 F16).
- Inline rename may submit twice, and Esc may commit through `onBlur` (D4 F16, unverified).
- The empty-widget message says "No rows match the current filter" with no filter set and has no Clear filter link; "Show as table" resets on reload (UI/UX §5.5); chat answers have no copy button (App Flow §10.2) (D4 F17).
- A help question ("how do I re-run an outdated analysis?") can route to `ask_model` (D7 F12). A keyword pre-route for "how do I …" to `app_help` would fix it.
- `ask_meaning` drops the general block without a word when the model returns nothing, though TRD §8.2 says it's shown (D7 F13).
- "The model" means the newest run once another answer comes between (D7 F14, `insight.pick_run`).
- Once, an edit asked right after a question in the same thread got no proposal within 90 s (D9 F5, not reproduced). Worth one scripted repro.

### CSV tab

- No "Export up to step k" after a failed export (D5 O2; App Flow §17.5). The backend supports `up_to_step`.
- The Clean with AI pending-edits note has Discard but no Save (App Flow §8.4); the scope labels have no counts; "1 rows" and "1 cells" (D5 O3).
- "Keep mine" on a row the newer version deleted can't be saved (`422`) and blocks the buffer until the line is removed (D5 O5, from the code).
- For about a second after Save, the grid shows the old version's rows under the new header (D5 O6).
- Select-all offers to delete only the rows whose pages are loaded (D5 O7).
- The undo confirmation doesn't say which replayed steps touch the same columns (D5 O8; App Flow §8.5).
- Find shows at most the rows of the first 10,000 matches (D5 O9).
- An invalid edit reads "age → abc" in the step's list, though it was saved blank and flagged (D5 O10).

### Stories

- The notebook puts edited card text into Markdown raw. Escape `\`, `*`, `_`, `#`, `<`, `>` and `&` in text runs (D6 F9; TRD §7.7).
- "Change view" never offers heatmap or scatter, so a heatmap switched to bars can't go back (D6 F10).
- The cascade progress line clears only on `cascade.done`, so leaving mid-cascade, or a job that dies, leaves it showing (D6 F11).
- Editor chips show the value saved with the card, not `Card.facts`, and unverified chips aren't dashed (D6 F12).
- An analysis card re-told after a cascade gets no "changed" badge, because its job's reason is `widget` (D6 F15).
- Labels repeat the model's noun: "Passenger class pclass 1", "Fare fare values" (D6 F16).
- The story panel: suggestion chips have no handler; the outdated badge can queue repeat jobs; hover isn't cleared on Edit layout or widget delete; the evidence query isn't invalidated on `card.updated`; the drawer shows no run for an analysis fact; the panel says "Stories appear once the dashboard is built" when the request fails (D6 F17).
- An edited card doesn't say that its chips re-render from the latest sheet (D6 F21; by design, TRD §4.6).
- The cascade toast leaves out `outdated` and `errors` (D6 F23).
- Cramér's V uses the Yates-corrected χ² on 2×2 tables, and Cohen's d the unweighted mean of the two variances (D6 F19, D7 F21). Both understate a little. State them in TRD §8.2, or use `correction=False` and the pooled SD.

### ML

- The progress labels misreport the work: "setting baselines" and "testing models" are sent back to back, and "explaining" takes about half the run (D7 F8).
- Constant columns stay in as features with importance 0 (D7 F10).
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

- `THIRD_PARTY.md` lists only the web app's direct dependencies. The bundle also ships the d3 modules (ISC), `d3-ease` (BSD-3-Clause), `robust-predicates` (Unlicense) and `tslib` (0BSD); `corepack pnpm licenses list --prod` gives the whole set (D9 F11).
- The notebook's `%pip` cell needs pip in the kernel's environment: in a `uv venv` without `--seed` it installs nothing, then fails at `import duckdb`. A Markdown line above the cell is enough (D9 F14).
- At phone width, KPI titles are cut to a few letters (D9 F15).

## 6. Evals and tests

- The ask eval passes contradictory answers. Any cell of any table can match; `text_any` passes on one word, so "significant" and "could be chance" both pass; and a source can stand in for an answer (D4 F13, D8 F4). The grounding eval checks each chip against its fact, not what the words claim between chips.
- `test_sandbox.py::test_happy_path_and_log` asserts the machine-wide `%TEMP%/sherlock-sandbox` is empty, so it fails while another process has a worker open. Set `SANDBOX_TMP` to `tmp_path` (D3 L5, D4 F14).
- The job-polling helpers don't check the status code, so a `429` under load becomes a `TypeError` (`test_jobs.py`, `test_notebook.py`, `test_stories.py`; D5 O11, D7 F16).
- No test asserts the `run.updated` event (D7 F17).
- No component tests for Save, conflicts and Undo: `SaveActions`, `ConflictDialog`, `ChangesPanel`, `CsvTab` (D5 O4).
- Day 2's list of untested cases: large integers, a DATE with a time, `nan` and booleans in edits; the same cell twice in one batch; hand-edit protection after an undo; conflicts mid-save; a huge offset or version; `state_rev` after undo; SSE replay and event order; a non-retryable 4xx failing at once; `OpenAITransport`'s error classes; the path with no `LLM_BASE_URL`; `sse.ts` dedup, reopen and backoff; `ImportPreviewDialog`'s options round trip; slide-over keyboard behaviour.

## 7. Docs (Rule 1)

- `FEEDBACK.md`'s Bklit and Glide spike records say "passed", though a pass rule wasn't tried: shared hover, and range paste (not needed after cut 5). Say "pass rule partly met" (D1 #3, D4 F18).
- PRD PROF-1 says the typing step commits "on every path"; with nothing to type there's no step, as TRD §7.1 says (D2).
- TRD §7.1 step 1 says an upload over the limit is aborted "while streaming", but Starlette spools the multipart body before the handler runs (D2, not probed).
