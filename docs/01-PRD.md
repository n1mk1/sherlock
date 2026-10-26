# Sherlock · Product Requirements Document (PRD)

Version 1.2 · Owner: As Wasti · Status: final for the Nebius x NVIDIA Global AI Hackathon

Companion documents: [App Flow](02-APP-FLOW.md) · [UI/UX Design Brief](03-UIUX-BRIEF.md) · [TRD](04-TRD.md) · [Backend Schema](05-BACKEND-SCHEMA.md) · [Implementation Plan](06-IMPLEMENTATION-PLAN.md)

---

## 1. Product summary

**One line.** Sherlock is a data analyst, ML engineer and storyteller in one: drop in a CSV, and it cleans the data, builds a dashboard, runs honest models on any slice, and tells you what it all means, while showing its work at every step.

**The problem.** Getting from a raw CSV to a decision takes a chain of specialists: someone to clean the data, someone to chart it, someone to model it, someone to explain it. Each handoff loses context, and the final numbers can rarely be traced back to how they were produced. AI tools that promise to do this end to end usually hallucinate numbers, hide their reasoning, or require the user to already know pandas and statistics.

**The product.** A web app where every number comes from executed code, every change to the data is a recorded and reversible step, and the AI's job is to translate, orchestrate and narrate rather than to compute. The user interacts through a dashboard, a spreadsheet view of the data, a story canvas, and a chat bar that can answer any question about any of them.

**Hackathon framing.** Built for the Best Apps and Agents track. Runs on Nebius Token Factory for all Nemotron inference and is hosted on Render (one Docker web service with a persistent disk), with a Nebius Serverless Endpoint or AI Cloud VM as the documented alternative (§9). Every model call Sherlock makes goes to an NVIDIA model on Token Factory (§9). Submitted by 2026-10-30 13:00 EDT. How each submission requirement and judging criterion is met is in §12.

---

## 2. Goals and non-goals

### 2.1 Goals (ranked)

1. **Trust.** Every number on screen can be traced to a query, a recipe run or a cleaning step in one click. Zero unsourced numbers in generated text.
2. **Autonomy with control.** Cleaning runs headless by default and produces a result a human can audit, undo and override cell by cell.
3. **Breadth of questions.** The user can ask, in plain language, about the data, the statistics, the drivers, specific rows, the cleaning history, the widgets, the stories, the models, the meaning of columns, and the app itself.
4. **Honest ML.** Every model is scored against baselines on held-out data; leakage is detected and excluded; "no signal" is a valid result.
5. **A story that stays true.** Story cards are written from computed facts, update when the data or widgets change, and never overwrite what the user wrote.
6. **Generic.** Any CSV a judge uploads works, or fails with a clear message. No dataset-specific code.
7. **Portable.** At any moment, the whole investigation (load, every cleaning step and edit, every widget, every model, every story) can leave the app as a runnable Jupyter notebook (`.ipynb`). Nothing Sherlock did is locked inside Sherlock.

### 2.2 Non-goals (for this release)

- Multiple files joined together, or comparisons across CSVs.
- User accounts, teams, sharing links, permissions.
- Real-time or streaming data sources, scheduled refresh, alerts.
- Free-form ML code written by the model.
- An editable notebook inside the app with a live kernel. The notebook export is a faithful, runnable reproduction; editing it happens in Jupyter, VS Code or Kaggle. (An in-app Notebook tab is P2.)
- A full catalog of ML methods (only Auto, linear regression and logistic regression are in scope; cut 4 of the Implementation Plan (§2.0) removed the two named methods, so only Auto ships; others are listed as P1/P2).
- Mobile layouts. The target is a laptop or desktop browser at 1280px or wider; narrower screens get a usable but secondary layout.
- Localisation. English only.

---

## 3. Users

| Persona | Who | What they want from Sherlock | How they'll judge it |
|---|---|---|---|
| **The operator** (primary) | Someone who owns a spreadsheet of business data (ops lead, founder, analyst-adjacent) and needs answers this week | Clean data without learning pandas; a dashboard without picking chart types; answers to "why" without hiring a data scientist | Did it find the problems I know about? Are the answers right? Can I check them? |
| **The analyst** | Knows SQL and some statistics; wants speed and auditability | Headless cleaning they can review; "show me the SQL"; proper regression output; export the pipeline | Would I be embarrassed by anything it did? |
| **The hackathon judge** | Has 5–10 minutes, will try their own CSV and ask hard questions | A demo that works instantly, a chat that answers their question with a source, something they haven't seen before (Flow) | Does it work? Is it new? Did it use Nemotron and Nebius well? |

### 3.1 The specific pain

The operator has a messy export (from a CRM, a store, an HR system, a survey tool) and a question that has to be answered from it. Today they either do it by hand in a spreadsheet, which takes hours and leaves no record of what was changed, or paste it into an AI chat, which answers fast but can't show where a number came from, forgets the cleaning between sessions, and sometimes invents figures. Either way the answer can't be defended when someone asks "how do you know?". Sherlock's main improvement is that the answer arrives as fast as a chat answer and stays as checkable as a careful analyst's work.

### 3.2 Alternatives and how Sherlock differs

| Alternative | What it does well | Where it falls short for this user | What Sherlock does instead |
|---|---|---|---|
| Doing it by hand (spreadsheet, pivot tables) | Full control, familiar | Slow; cleaning edits overwrite the original and aren't recorded; no modelling | Every change is a recorded, undoable step with cell lineage; cleaning and modelling run on their own |
| General AI chat with code execution | Fast answers to one-off questions | Work lives in one conversation; numbers in prose aren't bound to the code that produced them; no persistent dashboard or cleaning history | Numbers in generated text are chips bound to computed facts and verified before display; the dataset, steps, dashboard and stories persist and update together |
| BI tools with an AI assistant | Polished dashboards, sharing | Expect data that is already clean and modelled; cleaning happens in a separate tool | Cleaning, dashboard, models and stories are one pipeline on one dataset, and a data change flows through all of them |
| Notebooks (Jupyter and hosted notebook tools) | Reproducible, flexible | Need pandas, SQL and statistics skills | Sherlock writes the notebook for you: the export is a runnable `.ipynb` of everything it did |

The insight behind the design: the hard part of AI data analysis is not producing an answer but making the answer trustworthy. Sherlock uses the model to translate, plan and narrate, and leaves every number to executed code, every data change to a verified step, and every claim to a fact sheet the user can open.

---

## 4. Success metrics

| Metric | Target | How measured |
|---|---|---|
| Unsourced numbers in generated text | 0 | Grounding test: 100% of cached story numbers pass `verify_claim`; ask-anything eval tracks unsourced numbers |
| Ask-anything accuracy on the eval set (≈50 questions: Titanic plus at least 15 on a second end-to-end file) | ≥ 85% correct; ≥ 95% of unanswerable questions answered with an honest "can't" | Eval harness, run on every prompt or model change. The set (50 questions: 28 on Titanic, 17 on `sales_dated.csv`, 5 on `reviews_text.csv`) has no unanswerable questions yet, so the second target isn't measured (docs/BACKLOG.md) |
| Cleaning benchmark (corruption injected into 3 clean datasets) | Recovery rate reported; harm rate ≤ 2% of clean cells; row loss = 0 | Benchmark harness |
| Planted-truth ML tests | 3/3 pass (finds planted drivers; excludes planted leak; reports no signal on noise) | Test suite |
| Time from "Try with sample" to a complete dashboard with stories | ≤ 5 s (cached) · ≤ 180 s live for a 1,309-row file | Manual timing |
| End-to-end CSV set | 5/5 files reach a dashboard or a clear error | Manual run before submission |
| Notebook export | The exported `.ipynb` for every file in the end-to-end set executes without error (`nbconvert --execute`) and its final DataFrame equals the current version cell for cell | CI test on the sample; manual on the set |
| Demo video | ≤ 3:00, shows every hero moment in the demo script (Implementation Plan §9), and names the NVIDIA model and Nebius service behind each AI moment | Submission |
| Cold-start user test | At least 3 people who have never seen Sherlock reach a sourced answer on a CSV of their choice without help; time to first sourced answer, where they hesitated, and what they said are recorded | `docs/USER-TESTS.md`, summarized in the README |
| Baseline comparison | Time and steps to answer the same 3 questions on the same file by hand (spreadsheet) versus with Sherlock, plus how many of the hand-made answers can be traced to their source | `docs/USER-TESTS.md`, summarized in the README and the video |
| Model cost and latency | Per role (large, medium, small, embed): model ID, median latency, tokens per call and cost per sample run, from `llm_calls` | README model table |

---

## 5. Scope and priorities

Priority definitions: **P0** ships by 2026-10-29, except items removed by the Implementation Plan's cut order (§5), which is the only way a P0 item may be dropped. **P1** ships only if P0 is complete; order within P1 is binding. **P2** is after the hackathon and is listed only so decisions today don't block it.

### 5.1 P0

**Cuts applied:** all nine rows of the Implementation Plan's cut order (§5). The plan's §2.0 lists exactly what each cut removes from the items below: P0-03 settings, P0-05 CSV tab extras, P0-06 method chooser, `predict` and brush scope, P0-04 brushing, P0-07 the material-change check, P0-08 "rewrite" and "take the story toward X", and P0-10 suggested questions and `?`. The release criteria (§10) apply to what remains.

| ID | Area | Requirement |
|---|---|---|
| P0-01 | Load | Drag-and-drop anywhere, Upload button, "Try with sample" (Titanic). Import preview. Clear errors for bad files. |
| P0-02 | Clean | Cleaning offer after profiling. Headless auto-clean with live log, verifiers, gate, report, decision log. "Clean with AI" any time from the CSV tab, on the whole file or a selection. |
| P0-03 | Shell | Three panels; CSV / Dashboard / Flow tabs; chatbot bar; collapsible side panels; settings overlay; light and dark modes, each with five accent colors (Verdigris by default). At 1024 px and wider the left panel collapses to a rail, but the right panel only resizes: its collapse is not built yet (docs/BACKLOG.md). |
| P0-04 | Dashboard | Auto-built 6–10 widgets on Bklit UI; drag and resize; click-to-filter; add/edit widgets by chat; "How do you know?" on every widget. |
| P0-05 | CSV tab | Spreadsheet-grade editing (the P0 set in §7.5), saved as undoable steps; Changes panel. |
| P0-06 | ML | Auto mode; method chooser with linear and logistic regression; `driver_analysis` and `predict` recipes; scope by brush, filter or whole dataset; model cards with baselines. |
| P0-07 | Stories | Story card per widget plus an overview; number chips; verification; two-way linking; updates on change; editable without overwriting user text. |
| P0-08 | Flow | Canvas per CSV; cards, notes, labeled connections; "make sense of this", "take the story toward X", "rewrite this card". |
| P0-09 | Ask anything | Natural-language questions across every area in §7.9; sourced answers; follow-ups; clarification with buttons; "Pin to dashboard" and "Add to Flow". |
| P0-10 | Quality of life | Suggested questions; toasts with Undo; `/` summons chat; `?` shows shortcuts. |
| P0-11 | Ship | Deployed with a public URL on Render (a web service with a persistent disk at `/data`), or on the Nebius alternative in §9 (a Serverless Endpoint or an AI Cloud VM); cached sample run. |
| P0-12 | Notebook export | From any tab, at any time, "Export notebook" downloads a runnable `.ipynb` that reproduces the current state from the raw CSV: load, every step, every widget's query and chart, every ML run, every story card as Markdown. Table outputs are embedded so it reads without running. (§7.12) |

### 5.2 P1 (in order)

None of these is built yet. Four show in the app as disabled choices: "Ask me before each fix" in the cleaning plan's Mode row, and "Find groups", "Find unusual rows" and "Forecast" in the analysis menu.

1. Step-by-step cleaning mode; computed columns by chat.
2. `k-means` ("Find groups") with AI-named clusters.
3. What-if form; predictions for newly added rows; "add predictions as a column".
4. Column operations in the CSV tab (add, delete, rename, retype, reorder, hide).
5. Command palette (Ctrl+K).
6. "What changed" text on story badges; "Argue against this"; "Order this into a story"; Markdown and Obsidian export.
7. Significance tests as a widget; "Find unusual rows"; Simpson's paradox detector.
8. One-page report export (PDF/Markdown, rendered from the notebook with nbconvert).
9. Tavily outside context for anomalies.
10. Forecast recipe; "what changed and why" for dated data.
11. Notebook extras: chart images embedded as outputs; cells ordered by the Flow reading path when one exists; "Open in Colab" link; Kaggle-ready variant (data path parameter at the top).

### 5.3 P2

Editable Notebook tab with a live kernel and `.ipynb` import; accounts and sharing; joins across CSVs; decision flipping with pipeline replay; widget chaining; fit-on-A/score-on-B; free-form ML code; full method catalog; R-style formulas; learned cleaning playbook; alerts and scheduled refresh; DuckDB-WASM local mode; GPU acceleration.

---

## 6. Core concepts (definitions used everywhere)

| Term | Definition |
|---|---|
| **User** | An anonymous identity tied to a browser cookie. Owns a library of datasets and a settings record. |
| **Dataset** | One uploaded CSV and everything that belongs to it: versions, steps, widgets, layout, story cards, canvas, chat thread, ML runs. |
| **Version** | An immutable snapshot of the dataset's table. Version 1 is the raw import. Every committed step produces version n+1. |
| **Step** | One recorded change to the data: a cleaning fix, a batch of user edits, or a derived column. Has a summary, the code or edit list, an impact report, and cell-level lineage. Undoable. |
| **Lineage** | For every changed cell: old value, new value, the step that changed it. |
| **Data card** | The profile of a version: per-column type, role, stats, missing %, distinct values, detected issues. Input to every AI call. |
| **Widget** | A dashboard tile defined by a spec: scope (columns, rows) + op (SQL or ML recipe) + view (chart type). Layout is stored separately. |
| **Scope** | Which columns (by role) and which rows (a SQL predicate) an op runs on. |
| **Recipe** | A tested, parameterized ML or statistics procedure with a manifest. `method` selects Auto or a named technique within it. |
| **Run** | One execution of a recipe on a version with a scope and params. Produces a model card, results, a fact sheet, and optionally a saved model. Cached by its inputs. |
| **Fact sheet** | The computed numbers (in code) that a story card or chat answer is allowed to quote. |
| **Story card** | A short narrative about a widget, the dashboard, or a set of cards, with number chips bound to a fact sheet. Kinds: overview, widget, synthesis, direction, answer (a chat answer added to Flow). Direction cards were removed by cut 3 (Implementation Plan §2.0), so no code writes that kind. Flow notes are canvas nodes, not story cards. |
| **Number chip** | An inline number in a card that is bound to a fact-sheet value and updates when it changes. A hand-typed number is a chip marked "unverified". |
| **Canvas** | The Flow tab's document for a dataset: nodes (cards, notes) and labeled edges, stored as JSON Canvas. |
| **Job** | A background task (cleaning, dashboard build, story generation, ML run) with streamed progress. |
| **Cascade** | The automatic reaction to a new version or widget change: widgets re-query, affected runs are invalidated, affected stories update. |
| **Notebook** | A Jupyter `.ipynb` generated from a dataset's current state: one cell group per step, widget, run and card, in a deterministic order. It is derived, never hand-maintained: regenerating it after a change always reflects the new state. |

---

## 7. Functional requirements

Each requirement has an ID, a statement, and acceptance criteria. "Must" is binding for the stated priority.

### 7.1 Loading data

| ID | Requirement | Acceptance criteria |
|---|---|---|
| LOAD-1 (P0) | The user can load a CSV by dragging it anywhere over the app, by clicking Upload, or by clicking "Try with sample". | Dropping a file over any part of the window shows a full-window drop target and accepts the file. Upload opens the OS file picker filtered to `.csv, .tsv, .txt`. The sample loads without a file picker. |
| LOAD-2 (P0) | Before import, the user sees a preview: the first 20 rows as parsed, the detected delimiter, encoding and header row, and can correct each. | Changing delimiter, encoding or header row re-renders the preview within 500 ms. "Import" is disabled until at least one column and one row parse. The delimiter and encoding are detected; the header row is not detected yet and starts at row 1 (docs/BACKLOG.md). |
| LOAD-3 (P0) | Files are capped at 50 MB, 1,000 columns and 2,000,000 rows. Oversized or unreadable files produce a specific, plain-language error. | Error messages name the cause (too large, not a delimited text file, empty, could not decode) and what to do. The app never shows a stack trace. |
| LOAD-3a (P0, owner's decision) | A file whose rows have different numbers of fields still imports with its real columns. Short rows are padded with empty cells. A row with more fields than the header keeps its extra values in `col_N` columns past the header, and the row is quarantined ("extra fields"), never dropped. | A file with one long row, or with a tenth of its rows short, imports with its real columns, not as a single column. |
| LOAD-4 (P0) | Each loaded CSV becomes a dataset in the user's library with a status: profiling → offer → cleaning → building → ready, or failed. | The CSV panel shows the status within 1 s of each change. Switching datasets does not stop background work. |
| LOAD-5 (P0) | The user can rename and delete a dataset. Deletion asks for confirmation and removes everything belonging to it. | After delete, the dataset's folder and rows are gone; a toast offers Undo for 10 s; the data is soft-deleted and purged 10 minutes later. |
| LOAD-6 (P0) | A stable `_row_id` is assigned to every row at import and never changes. | New rows added later get fresh IDs; IDs are never reused. |
| LOAD-7 (P1) | The user can give the URL of a data dictionary or codebook for the file (an optional "Data dictionary URL" in the import preview). Sherlock reads it with Tavily and keeps what it says about each column as a note, with the page's own words and its address. Only a URL the user typed is fetched, and nothing from the file is sent. | A dictionary page that describes the columns gives a note on each column it describes, shown on hover over the column's header in the CSV tab: Sherlock's sentence (no digits), the page's own words quoted, the address and the date it was read. A site root is searched for its dictionary page. With no Tavily key, or when the page can't be read, the import goes on and one line says the dictionary wasn't read. Notes are metadata: they never change a value. |

### 7.2 Profiling

| ID | Requirement | Acceptance criteria |
|---|---|---|
| PROF-1 (P0) | After import, Sherlock builds a data card for version 1: per column, the inferred type (int, float, bool, date, datetime, category, text, id, or empty for a column with no values), the role (measure, dimension, time, id, target-like, free text), missing count and %, distinct count, min/max/mean/median for numbers, top values for categories, and detected issues. | The data card is complete for a 1,309 × 14 file within 3 s and for a 50 MB file within 60 s. Types are inferred from values, not from the loader (`all_varchar` import). A deterministic typing step (code, not LLM) then casts every column whose values parse losslessly at ≥ 99% to its inferred type (in those columns, missing-value sentinels such as `N/A` become empty first), quarantines rows whose cast fails, and commits as step 1 on every path, including "Clean it myself" and After upload "I'll clean it myself". It is undoable like any step, with a warning. A file with no column to cast gets no typing step and stays at version 1 (TRD §7.1). |
| PROF-2 (P0) | The data card is shown as the cleaning offer's one-line summary and in the CSV tab's column headers. | Summary names the top 3 issues by impact, e.g. "263 missing ages, 1,014 missing cabins, 2 possible leakage columns". As built, the offer shows "1,309 rows · 14 columns · 7 issues", then the three most severe issues as a list, one per column ("263 missing in age", "boat records the outcome"). |
| PROF-3 (P0) | The data card is recomputed for every new version and cached per version. | A cascade never uses a stale data card. |

### 7.3 Cleaning

| ID | Requirement | Acceptance criteria |
|---|---|---|
| CLEAN-1 (P0) | After profiling, the centre panel shows a cleaning offer with the summary and two choices: "Clean with AI", which opens the cleaning plan (CLEAN-8a), and "Clean it myself", which builds the dashboard on the data as it is and opens the CSV tab to edit by hand or ask the chat. | The offer appears automatically unless the "After upload" setting is "Open the cleaning plan" (the plan opens by itself and says why) or "I'll clean it myself" (the build screen says why). Nothing is cleaned without a click on Start cleaning. |
| CLEAN-2 (P0) | Headless cleaning runs as a background job with a live log: one entry per step with a timestamp, the column, what was tried, what was chosen and why, and the gate decision. | Log entries arrive over SSE within 1 s of the event. The user can switch datasets or tabs; the job continues and the CSV panel shows progress. |
| CLEAN-3 (P0) | Every cleaning step is validated by the verifiers in §7.3.1 before commit. A step that fails any verifier is not committed. | Row count never changes due to auto-cleaning. No parse op commits with failures converted to blanks: a failed value's row is quarantined and the original text is kept in lineage (this is how the typing step meets the rule). |
| CLEAN-4 (P0) | Steps are gated: high confidence commits; medium commits with a flag and the original kept in lineage; low is skipped and logged. | The report lists every skipped issue with its reason. |
| CLEAN-4b (P0) | The Cleaner doesn't commit a guess the data can't settle. A step is skipped when two of its candidates pass every check but give different values to more than 1% of the cells they both change; the log shows two of those cells both ways. Values that differ only in their numbers ("Region 1", "Region 2"), or two values that are each common, are never merged. A date column whose every value reads both ways (day-first and month-first) is left as text, with no order guessed, until the user says which. | The corruption benchmark's look-alike and ambiguous-date sets (TRD §14) end with 0 harm and 0 wrong values, and the report lists each such skip with its reason. |
| CLEAN-4a (P0, owner's decision) | Two further rules skip a step whatever its confidence. A step may not quarantine more than twice as many rows as its issue has, plus 10. A step the reviewer says changed values it shouldn't have is skipped too; the reviewer's other concerns still don't block a commit. | The report lists such a step as skipped, with its reason. |
| CLEAN-5 (P0) | Auto-cleaning never deletes rows. Rows that would be removed (duplicates, impossible records) are quarantined and shown. | Quarantined rows appear in the CSV tab under the "only flagged" view, marked, and can be restored (Restore in the row menu creates a step). Quarantined rows are excluded from widgets, ML and stories, and the exclusion is visible in the SQL shown under "How do you know?". The "only flagged" view and the row menu were removed by cut 5 (Implementation Plan §2.0): quarantined rows are marked in the grid, and the toolbar's Restore button adds the selected ones to the unsaved edits, which Save commits as a step. |
| CLEAN-6 (P0) | The run ends with a report: counts of issues found / fixed / flagged / skipped, each step with its summary and impact, and the decision log. | The report is reachable from the CSV tab's Changes panel at any later time. |
| CLEAN-7 (P0) | Every committed step is undoable from the Changes panel. Undoing step k when later steps exist asks for confirmation and replays the later steps on top (or fails clearly if a later step depends on it). | Undo produces a new version; nothing is ever mutated in place. |
| CLEAN-8 (P0) | "Clean with AI" is available in the CSV tab toolbar at any time, with scope: whole dataset, current selection, or rows added since the last clean. | It runs on the current version. Hand-edited cells are skipped and listed in the report, with an option to include them. Unsaved edits must be saved or discarded first (prompted). The option to include hand-edited cells is not built yet: every clean from the app leaves them alone (docs/BACKLOG.md). The button opens the cleaning plan (CLEAN-8a) in the right panel, with the scope. |
| CLEAN-8a (P0, owner's decision) | Before Clean with AI runs, from the offer or the CSV tab, Sherlock shows a cleaning plan: the code detectors' diagnosis of the current version, one fix per issue grouped into modules (types and parsing, missing and placeholder values, spelling and formatting, duplicates and broken records, outliers, other checks), each with its count, up to 5 example values and the planned action, and **every fix ticked**. The user can untick fixes, one at a time or a whole module, then Start cleaning or Discard. Leakage and ID-like columns show as "Marked, not changed", with no checkbox. | No number in the plan comes from the model. A plan made on an older version is diagnosed again and merged (ticks kept) before it's shown or started. An unticked fix is skipped without a model call, logged "not in your plan", and listed in the report as "You left this out of the plan"; issues found mid-run are still attempted. The plan isn't a modal: from the offer it fills the centre, from the CSV tab it replaces Changes in the right panel (with the scope), so the chat bar stays usable. The lazy path stays one click: Start cleaning with everything ticked. "Clean them" on the toast after saving new rows, and Approve on chat's "clean these rows" proposal, also open the plan, with those rows as its scope; they start nothing themselves. |
| CLEAN-8b (P0, owner's decision) | In the cleaning plan the user can also rewrite any fix in plain words (✎, with Reset to Sherlock's wording), add steps of their own (a column, or the rows, and an instruction), remove those steps, and ask the chat to do any of this, which applies to the plan at once. The Cleaner writes and checks code that follows each instruction; editing the code itself is CLEAN-10's. | The user's steps run first and count against the budget. Every hard check still applies to them (placeholder fills, the row ledger, the quarantine cap: at most a fifth of the rows for a step with no detector), and a step that fails one is skipped with the reason. A step the user asked for that would be skipped for low confidence commits with a flag ("kept because you asked for it") and can be undone. The diagnosis can't end it as "leave as is". The step records the instruction ("You asked: …") in Changes, the report ("Your steps", each fixed, flagged, skipped or not reached) and the exported notebook. Chat's reply is written by code ("Unticked 1 fix: missing values in cabin."). An ambiguous-dates fix also asks which order the dates are written in (Day first · Month first), with three of its values read both ways; the order picked is the user's instruction for that fix, replaces the Cleaner's three-way vote with one diagnosis, and is listed under "Your steps". A column whose every date reads both ways is cleaned only once an order is picked (CLEAN-4b). |
| CLEAN-9 (P0) | The budget per headless run is 20 attempted issues (committed or not), 5 minutes wall-clock, and a configurable token cap. Hitting any budget ends the run cleanly with a partial report. | The report says which budget ended the run. |
| CLEAN-10 (P1) | Step-by-step mode: each proposed step appears in the chat thread as an approval card with summary, code (collapsed), impact preview, and Approve / Edit / Reject. | Nothing commits without Approve. Edit opens the code for changes and re-runs the preview. The mode is chosen in the cleaning plan's Mode row (CLEAN-8a): "Run on its own" or "Ask me before each fix", shown disabled with "comes later" until this is built. |
| CLEAN-11 (P1) | The committed pipeline can be exported as a runnable Python script. | The script reproduces the latest version from the raw file. |

#### 7.3.1 Verifiers (all P0)

Row-count ledger (no unexplained row loss) · parse success rate reported, and any parse failure goes to quarantine rather than blank · lossless round-trip for type parses · sum and distribution conservation where the op should preserve them · no silent NaN introduction · dtype sanity · `pandera` constraints derived from the data card · no merge of look-alike categories that are different on purpose (CLEAN-4b).

#### 7.3.2 Detectors (all P0, code not LLM)

Mixed types · sentinels (`-999`, `N/A`, `null`, `?`, empty) · whitespace and case variants · near-duplicate categories · exact and near duplicates · impossible values (negative ages, future dates) · numbers stored as text (currency symbols, thousands separators, locale decimals) · ambiguous date formats · mojibake · unit mixes · cross-column violations (`end < start`) · broken functional dependencies (city → state) · ID candidates · missingness patterns · outliers (robust statistics) · leakage candidates (columns that record the outcome).

### 7.4 Dashboard

| ID | Requirement | Acceptance criteria |
|---|---|---|
| DASH-1 (P0) | After cleaning (or "Clean it myself"), the dashboard is built automatically with 6–10 widgets chosen by interestingness, each validated (schema, SQL dry-run, ≤ 2,000 result rows). | A dashboard exists for every file in the end-to-end set. No widget shows an error state on first render for those files. |
| DASH-2 (P0) | A `driver_analysis` widget is included when a target-like column is detected. | On Titanic, "What drives survival?" is on the first dashboard. As built, the widget is titled from the column's name ("What drives survived?") and is added when the file has at least 100 rows. |
| DASH-3 (P0) | Widgets render on Bklit UI charts (plus custom heatmap, histogram, box plot, scatter, KPI card, table). | Every chart follows the active theme's tokens. |
| DASH-4 (P0) | Widgets can be dragged by their handle (⠿) and resized by their corner; layout persists per dataset. | Reloading restores the layout. Layout changes don't trigger the cascade. |
| DASH-5 (P0) | Clicking a bar, slice or cell sets a global filter that every widget inherits; one chip shows the active filter; clicking again or the chip's × clears it. | Filtered widgets re-query within 1 s for the Titanic file. Widgets with `inherit_global_filters: false` are unaffected. |
| DASH-6 (P0) | Brushing a range on a chart creates a row selection (predicate) that ML setup and chat can use. | The selection chip shows the row count. Esc clears it. Removed by cut 8 (Implementation Plan §2.0): click-to-filter (DASH-5) stays, and ML scope comes from the filter or the whole dataset. |
| DASH-7 (P0) | Every widget has "How do you know?" which shows the SQL (for `sql` ops) or the recipe, scope and model card (for `ml` ops). | SQL shown is exactly what was executed. |
| DASH-8 (P0) | Widgets can be created and edited from chat ("add a chart of fare by port", "make this a line chart", "only show 1st class"). New widgets appear highlighted; edits are undoable. | The chat shows a link to the widget it changed. |
| DASH-9 (P0) | Widgets can be duplicated, collapsed to their header, and deleted (toast with Undo). | Delete removes its story card too; Undo restores both. |
| DASH-10 (P0) | The dashboard soft-caps at 20 widgets with a warning. | Adding the 21st shows the warning but is allowed. |
| DASH-11 (P0) | Any data change keeps the same dashboard: widgets re-query the new version, affected ML runs are marked outdated, affected stories update. | After a CSV-tab save, every widget that references a changed column re-renders with new numbers. |

### 7.5 CSV tab (spreadsheet)

| ID | Requirement | Acceptance criteria |
|---|---|---|
| CSV-1 (P0) | The CSV tab shows the current version in a virtualized grid with sticky headers and row numbers. Headers show type, missing % and a mini distribution. | Scrolling 50 MB files stays smooth (server-side paging). |
| CSV-2 (P0) | Cells changed by cleaning are tinted; hovering shows `old → new (step n)`. Quarantined rows are marked. Hand-edited unsaved cells have a distinct style. | The three styles are distinguishable in both themes without relying on color alone (icon or outline). The `old → new (step n)` hover was removed by cut 5 (Implementation Plan §2.0); the three styles remain. |
| CSV-3 (P0) | Navigation: arrow keys, Tab/Enter, Ctrl+arrow to the data's edge, jump to row number. | Keyboard-only use covers all editing. Ctrl+arrow and jump to row were removed by cut 5 (Implementation Plan §2.0). Jump to row isn't there; the grid library's default Ctrl+arrow still moves to the first or last row or column. |
| CSV-4 (P0) | Selection: click; Shift+click and drag for ranges; header click selects a row or column; Ctrl+A. | The status bar shows count, sum, average, min, max for numeric selections. Range selection and the status-bar stats were removed by cut 5 (Implementation Plan §2.0). The stats aren't there: the status bar shows how many cells are selected. The grid library's default range selection (Shift+click, drag, Ctrl+A) is still on, and Delete, Restore and Clean with AI act on the selected rows. |
| CSV-5 (P0) | Editing: type to replace, Enter or double-click to edit, Esc cancels; type-aware editors (category dropdown with existing values, number validation, boolean toggle, date picker); autocomplete from the column's values. | Invalid values are flagged inline and can be kept. The type-aware editors and autocomplete are not built yet: every cell edits as text (docs/BACKLOG.md). |
| CSV-6 (P0) | Copy a range as TSV; paste a block from Excel/Sheets; fill down (Ctrl+D). | Pasting a 100 × 10 block takes under 1 s and shows as pending edits. Removed by cut 5 (Implementation Plan §2.0). The grid library's defaults still copy a selected range with Ctrl+C and paste the clipboard's text into one cell; block paste and fill down aren't there. |
| CSV-7 (P0) | Rows: add above/below, duplicate, delete. All logged and undoable. | New rows get new `_row_id`s. Add above or below and duplicate were removed by cut 5 (Implementation Plan §2.0): Add row adds a row at the top, and Delete marks the selected rows; both are saved as a step. |
| CSV-8 (P0) | Columns: sort (multi-column), resize, auto-fit. Sorting and filtering change the view only, never the data. | The version is unchanged by sort/filter. Multi-column sort, resize and auto-fit are not built yet: a header click sorts by that one column, and column widths are fixed (docs/BACKLOG.md). |
| CSV-9 (P0) | Find and replace with match count preview, regex option, scoped to selection or column. | Replace creates pending edits, not an immediate version. Replace was removed by cut 5 (Implementation Plan §2.0); Find stays, over the whole file, with a match count. |
| CSV-10 (P0) | Per-column filters (values list, numeric range, contains, is empty) and quick views: only changed, only flagged, only missing. | Filters are view-only and persist while the tab is open. Removed by cut 5 (Implementation Plan §2.0). |
| CSV-11 (P0) | Undo/redo (Ctrl+Z / Ctrl+Y) for pending edits; a pending count on the Save button; "Review changes" shows a diff with per-change discard. | Save creates exactly one new version containing all pending edits as one step. Undo/redo of pending edits and "Review changes" were removed by cut 5 (Implementation Plan §2.0); the pending count on Save, Discard, and one version per Save remain. |
| CSV-12 (P0) | Download the current version as CSV. | The download matches the grid's data (not its view filters). |
| CSV-12a (P0, owner's decision) | In the downloaded CSV, a text cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return gets a leading `'`, so a spreadsheet doesn't run it as a formula. Number, date and boolean columns export exactly. The original upload (`raw.csv`) is offered unchanged. | `=HYPERLINK(…)` in a text column downloads as `'=HYPERLINK(…)`; `-3` in a number column stays `-3`. |
| CSV-13 (P0) | Select cells and ask the chat about them or tell it to fix them; the change arrives as a reviewable step. | The chat context shows "n cells selected". As built, the chip says "n rows selected", and only a request to edit or clean uses the selection (as a proposal to approve); a question about the selected cells is not limited to them yet (docs/BACKLOG.md). |
| CSV-14 (P0) | Right-click menus for row, column and cell actions. | Every menu action has a keyboard equivalent listed on `?`. Removed by cut 5 (Implementation Plan §2.0); the `?` sheet was removed by cut 9. |
| CSV-15 (P0) | The right panel shows Changes: the cleaning report, every step and edit batch with its summary and impact, and Undo per step. | Unsaved edits appear at the top as "Unsaved (yours)". |
| CSV-16 (P1) | Column operations: add (empty with a type, or computed by chat), delete, rename, retype, reorder, hide/show, split, merge. | Each is a step. |
| CSV-17 (P1) | Row detail drawer; freeze columns; multiple ranges; fill handle with series; saved views; version history with restore and compare; Parquet/Excel export. | — |

### 7.6 ML

| ID | Requirement | Acceptance criteria |
|---|---|---|
| ML-1 (P0) | Every widget has an analysis dropdown with plain-language options: "What drives this?", "Predict a column", and (P1) "Find groups", "Find unusual rows", "Forecast". Options that don't fit the data are disabled with the reason. | "Forecast" is disabled with "needs a date column" on Titanic. "Predict a column" was removed by cut 7 (Implementation Plan §2.0) and is listed disabled, "Not in this release". |
| ML-2 (P0) | Setup shows target (pre-filled with the best guess), feature chips (excluded ones crossed out with the reason on hover), the row scope chip, and a Method selector (Auto, Linear regression, Logistic regression). Advanced settings are under "More". | A run can be started with one click after choosing an option. The Method selector was removed by cut 4 (Implementation Plan §2.0): the form says the run uses Auto. |
| ML-3 (P0) | Every supervised run performs: leakage check, fair split (rows that share an ID-like group, such as a ticket or an account, stay in one fold), preprocessing inside CV folds, baselines (majority/mean and best one-column rule), model search (Auto) or the chosen method, explanations, model card. | On the planted-truth tests: drivers found, leak excluded, noise reported as "no signal". |
| ML-4 (P0) | Linear regression reports coefficients with confidence intervals and p-values, R² and adjusted R², and a residuals plot. Logistic regression reports coefficients and odds ratios, accuracy vs baselines, a confusion matrix and ROC. | Computed with statsmodels; numbers match a reference run within floating-point tolerance. Removed by cut 4 (Implementation Plan §2.0). Auto's classification card still has a confusion matrix and, for two classes, a ROC curve from the out-of-fold predictions. |
| ML-5 (P0) | Assumption checks for chosen methods (non-linearity, influential outliers, collinearity, class imbalance, perfect separation) are shown as warnings with a suggestion, never as blockers. | `boat` on Titanic triggers the perfect-separation warning if forced in. Removed by cut 4 (Implementation Plan §2.0): with no method to choose, the method checks aren't built. Auto's model card warns on class imbalance, a small sample, many-valued features and a feature forced in against the checks, so `boat` forced in gets the forced-in warning. |
| ML-6 (P0) | "Compare with Auto" runs Auto on the same setup and shows both. | Shown side by side in the model card. Removed by cut 4 (Implementation Plan §2.0); the model card lists the other models Auto tried. |
| ML-7 (P0) | Prediction fills rows where the target is blank; predicted cells are visually distinct with the probability or range on hover; existing rows get out-of-fold scores; every prediction has a per-row explanation; low-confidence and out-of-distribution rows are marked. | Predictions never overwrite real values. Removed by cut 7 (Implementation Plan §2.0). |
| ML-8 (P0) | Runs execute as background jobs with plain-language progress and are cached by (version, scope, recipe, method, params). | A repeat run returns within 200 ms. |
| ML-9 (P0) | Results that depend on changed columns are marked "outdated" after a new version, with a re-run button (or automatic re-run per the story-update setting). | Never silently shows results from an older version. |
| ML-10 (P0) | Minimum rows per recipe are enforced (100 for supervised); below that, the run refuses with the count needed. | — |
| ML-11 (P1) | `k-means` with elbow chart, profiles and AI-named clusters; what-if form; predictions for new rows on save; "add predictions as a column"; "find unusual rows"; significance test widget; Simpson's paradox detector; forecast. | — |

### 7.7 Story cards

| ID | Requirement | Acceptance criteria |
|---|---|---|
| STORY-1 (P0) | Each widget has a story card: headline, 2–4 sentences, number chips with evidence links, related-widget chips, Edit, Ask why. An overview card summarizes the top 3–5 findings. | Cards stream in as each passes verification. |
| STORY-2 (P0) | Numbers in cards are chips bound to fact-sheet values; the narrator never types numbers. | A card's numbers equal the fact sheet's values at all times. |
| STORY-3 (P0) | Every story is verified before caching; ungrounded stories are regenerated; if regeneration fails, the card shows the fact sheet as bullet points instead of prose. The same chip-only schema and verification apply to every other LLM-written text shown to the user: card rewrites, suggested revisions, synthesis and direction cards, and widget titles. | Grounding test passes 100%. Card rewrites and direction cards were removed by cuts 2 and 3 (Implementation Plan §2.0). A widget title written in chat passes the builder's title check and the wording check, or the templated title is used (TRD §8.1). |
| STORY-4 (P0) | Two-way linking: hovering a widget highlights its card and related widgets; hovering a card highlights its widget; clicking a card scrolls to its widget. | Highlight appears within 100 ms; no layout shift. |
| STORY-5 (P0) | Stories update on: widget added / changed / removed, data saved, cleaning step committed, ML result arrived or invalidated. Only affected cards update. The LLM re-narrates only on a material change; otherwise chips refresh. | After editing one cell in `age`, only cards whose fact sheets depend on `age` update. The material-change check was removed by cut 6 (Implementation Plan §2.0): every affected card is narrated again, and the overview with them. |
| STORY-6 (P0) | Updated cards show a "changed" badge. With "Story updates: Ask first", they show "outdated, click to refresh" instead. | — |
| STORY-7 (P0) | Cards are editable inline. A user-edited card is never overwritten; it gets a "data changed" badge with a suggested revision to accept, edit or dismiss. Hand-typed numbers are marked "unverified". A number chip saved with an edit shows its fact's value, and one with no fact behind it is marked "unverified" too. A number typed in words ("zero", "twice") is marked "unverified" like one typed in digits. Once the data moves past the version the user's words were written on, the card says so ("Written on v5, data is now v7"), also after the suggestion is dismissed, and a card with hand-typed numbers asks for them to be checked ("Has numbers you typed; check them"), since no code keeps them current. | Editing on the canvas and in the panel edits the same object. Both badges show on the panel's card and on its canvas node. |
| STORY-8 (P0) | Wording rules enforced in prompts and checked post-hoc: no causal language for correlational findings; mention small samples (n < 30). The words around a chip may not claim more than its fact: no name said twice, an importance stays next to its column, a level isn't read as a gap, and a synthesis neither works a number out of its cards' chips nor compares two cards' numbers in a way code hasn't checked. Chat answers name only category values the data has. | Reviewed in the eval set. The chat's model-written text (answer prose, the closest question, clarification options, the reading, widget titles) passes the same wording check, and a chat value label shows only a cell of a result's non-number column or a value the DataCard knows; a count or an average is always a chip (TRD §8.1). |
| STORY-9 (P1) | "Changed" badges say what changed. Tavily context on anomaly cards with citations. | — |

### 7.8 Flow canvas

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FLOW-1 (P0) | One infinite canvas per dataset with pan, zoom, minimap, "fit view". | Saved automatically within 1 s of any change. |
| FLOW-2 (P0) | Story cards can be dragged from the palette onto the canvas. A card on the canvas is the same object as in the panel (live). The palette marks cards already placed. | Editing the card in either place updates both. |
| FLOW-3 (P0) | Notes (free text) can be added, edited and deleted. | — |
| FLOW-4 (P0) | Edges can be drawn between any two nodes, labeled with free text, and deleted. | Labels render at the edge midpoint. |
| FLOW-5 (P0) | Chat on the canvas uses the selected nodes as context (or the whole canvas). "Make sense of this" adds a synthesis card connected to its sources. "Take the story toward X" creates the needed widget(s) and places their cards connected to the selection. "Rewrite this card" proposes an edit to accept or reject. | A synthesis card cites its source cards; numbers in it are chips from those cards' fact sheets. "Rewrite this card" and "Take the story toward X" were removed by cuts 2 and 3 (Implementation Plan §2.0); "Make sense of this" stays. |
| FLOW-6 (P0) | The canvas is stored as JSON Canvas. | A valid `.canvas` document is produced. |
| FLOW-7 (P1) | Groups, chart thumbnails on cards, AI-suggested connections, "Argue against this", "Order this into a story", Markdown and `.canvas` export, auto-layout. | — |

### 7.9 Ask anything (chat)

| ID | Requirement | Acceptance criteria |
|---|---|---|
| ASK-1 (P0) | The chat bar is present on all tabs, scoped to the open dataset, with its own thread per dataset. Visibility is a setting (pinned / auto-hide / hidden); `/` summons it. | The thread persists across reloads. |
| ASK-2 (P0) | Questions are routed to the right source: data (SQL), statistics, drivers, rows, cleaning history, widgets, stories/canvas, models, column meaning, app help. | Eval set covers every category. |
| ASK-3 (P0) | Every number in an answer is traceable: "How do you know?" reveals the SQL, recipe run or step. An answer with an untraceable number is never shown as prose. | Unsourced-number count in the eval = 0. |
| ASK-4 (P0) | Answers take the right shape: number, small table, quick chart, or text. Chart answers have "Pin to dashboard"; narrative answers have "Add to Flow"; row answers link to the CSV tab. | — |
| ASK-5 (P0) | Follow-ups keep context ("and for men?", "plot that"). Selections (cells, rows, widgets, cards) are context. Fuzzy names resolve ("NYC" → "New York, NY"). | Eval includes follow-up pairs. |
| ASK-6 (P0) | Ambiguous questions get one clarifying question with 2–3 button options, never an open-ended one. | The router's clarifications, and those built in code: a name that matches nothing in the file but looks like one of its columns or values (when the query can't be written), which column a meaning question is about, which two columns a test compares, and which widget to explain or change. Each has 2–3 buttons, and the choice resumes the question (TRD §8.1). |
| ASK-7 (P0) | Long questions show a short plan (2–5 steps) and stream results. At most 8 answerer and action calls per message. | — |
| ASK-8 (P0) | Honest limits: when the data can't answer, the reply says so and suggests the closest answerable question. | — |
| ASK-9 (P0) | Suggested questions appear under the input, generated from the data card (3 at a time). | They are answerable (checked against the eval harness for the sample). Removed by cut 9 (Implementation Plan §2.0). |
| ASK-10 (P0) | Data changes requested in chat arrive as proposals (approve / reject). Additive actions (new widget, new card) apply immediately and are undoable. | — |
| ASK-11 (P1) | Outside-world questions answered via Tavily with citations. | — |

### 7.10 Settings

| Setting | Options | Default | Effect |
|---|---|---|---|
| Mode | Light · Dark · Follow system | Follow system | Swaps the base token set |
| Accent | Verdigris · Arcane · Ember · Aether · Brass | Verdigris | Swaps the accent tokens (UI/UX brief §2.1) |
| Chatbot bar | Pinned · Auto-hide · Hidden | Pinned | §7.9 ASK-1 |
| After upload | Ask me · Open the cleaning plan · I'll clean it myself (the stored values are `ask`, `always`, `never`) | Ask me | Whether the offer appears. "Open the cleaning plan" opens the plan by itself and never cleans unattended (CLEAN-1, CLEAN-8a) |
| Default cleaning mode | Auto · Step by step (P1) | Auto | Used by the offer and "Clean with AI" |
| Story updates | Automatic · Ask first | Automatic | STORY-6, and whether outdated ML runs re-run automatically (ML-9) |
| Spotlight on hover | Off · Subtle · Full | Subtle | Strength of the hover highlight |
| Reduce motion | Follow system · On · Off | Follow system | Disables non-essential animation |
| Default tab | CSV · Dashboard · Flow | Dashboard | Tab shown when a dataset opens for the first time |

Settings are stored per user (browser cookie identity) on the server, so they survive reloads.

Cut 1 (Implementation Plan §2.0) keeps four of these in the settings dialog: Mode, Accent, Chatbot bar and After upload. The other five are still stored with the defaults above, and only `PUT /me/settings` can change them. Story updates, Spotlight on hover, Reduce motion and Default tab act on their values; Default cleaning mode is read by no code, since only Auto cleaning is built. The dialog labels Follow system "System" and the Chatbot bar "Chat bar".

### 7.11 Quality of life (P0)

Toasts with Undo (10 s) after deleting a widget, rows, a card or a dataset · `/` focuses or summons the chat bar and `?` opens the shortcuts sheet (both only when no cell, input or editor has focus) · suggested questions · "remember where I was" (tab, scroll, selection per dataset, per browser) · empty states that say what goes there and offer one action · unsaved CSV edits survive a page reload (local storage, keyed by dataset and version).

The `?` sheet and suggested questions were removed by cut 9 (Implementation Plan §2.0). "Remember where I was" keeps each dataset's last tab on the server (so in any browser), and the dashboard's scroll and the Flow view in this browser. The CSV grid's scroll and the selection aren't remembered yet (docs/BACKLOG.md).

### 7.12 Notebook export

| ID | Requirement | Acceptance criteria |
|---|---|---|
| NB-1 (P0) | "Export notebook" is reachable from every tab: the dataset header menu (⋯), the CSV toolbar's Download menu, the Flow palette's Export link, and the chat ("export a notebook"). It is available in every dataset status except `profiling` and `failed`. | The action is visible on every enabled tab; during cleaning it exports the latest committed version and says so in the notebook's first cell. |
| NB-2 (P0) | The export is a valid `.ipynb` (nbformat 4.5) named `<dataset>-v<version>.ipynb`, plus a sidecar download of the raw file named `<dataset>-raw.csv` when the user ticks "Include data" (default on). Without the data, the first cell documents where to put the raw file. | `nbformat.validate` passes. The notebook opens in Jupyter, VS Code, Colab and Kaggle without warnings. |
| NB-3 (P0) | The notebook reproduces the current version from the raw file: a load cell that decodes the raw file with the recorded encoding and reads it with DuckDB's `read_csv` (the same transcoding, reader, options and `all_varchar` setting as the import, and the same `_row_id` and `_quarantine_reason` columns), then one code cell per step in the current version's effective chain, in order. Cleaning steps use their stored pandas code (the automatic typing step uses its stored DuckDB statement) against the same helper functions (vendored into the notebook as one cell); edit batches are rendered as explicit pandas assignments by `_row_id`; undone steps are left out and an undo appears only as a Markdown note; quarantine is a `_quarantine_reason` column, never a drop. | Executing the notebook top to bottom yields a DataFrame equal to the current version (same rows by `_row_id`, same columns, same values, same dtypes) for every file in the end-to-end set. |
| NB-4 (P0) | Every widget becomes a Markdown cell (title) plus a code cell that runs its exact SQL with DuckDB on the DataFrame and shows the result table, plus a code cell that draws the chart with matplotlib (bar, line, area, pie/ring as bar, scatter, histogram, box, heatmap; KPI and table as a printed value or DataFrame). Global filters are not applied; the widget's own row predicate is. Widgets with an ML op get their run's reproduction cell (NB-5) and its importance or coefficients table instead of SQL and chart cells. | The result table in the notebook equals the widget's data in the app for the same version. Chart cells execute without error. |
| NB-5 (P0) | Every ML run becomes a code cell that reproduces it: scope query, the exact feature list and exclusions (as comments with reasons), the same split and seed, the same preprocessing, the chosen method via scikit-learn/statsmodels, baselines, metrics, and the importance or coefficients table. Auto runs reproduce the winning model only, with a comment naming the alternatives tried. | Re-executed metrics match the model card within 0.5 percentage points (same seed, same library versions pinned in the requirements cell). |
| NB-6 (P0) | Every story card becomes a Markdown cell placed after its widget (or after its sources for synthesis cards): the headline as a heading, the body with number chips rendered as plain numbers, a line listing related widgets, and the "evidence" SQL in a collapsed details block. The overview card is the notebook's introduction. Notes from the Flow canvas are included when "Include canvas notes" is ticked. | No number in a Markdown cell differs from the fact sheet it came from. |
| NB-7 (P0) | Outputs for table and text cells are embedded at export time (computed server-side from the data the app already has), so the notebook reads correctly on GitHub and Kaggle without execution. Chart cells have no embedded output in P0 (P1 embeds PNGs). | Opening the file in a viewer shows every table. |
| NB-8 (P0) | The first cells are: a title and provenance cell (dataset name, version, export time, Sherlock version, a link to the models used), a parameters cell (`DATA_PATH`, `RANDOM_SEED`), a requirements cell (`pip install` line with pinned versions of pandas, duckdb, numpy, scikit-learn, statsmodels, matplotlib, rapidfuzz, dateparser, ftfy) and the vendored helpers cell. | Running the requirements cell in a fresh environment is enough to execute the rest. |
| NB-9 (P0) | Export runs as a job with progress; for the sample it completes in ≤ 5 s, for a 50 MB file in ≤ 60 s. The result is cached per (version, dataset state revision, options) and invalidated by a new version or by any widget, card, run, layout or canvas change. | A repeat export of the same version downloads immediately. |
| NB-10 (P0) | The export dialog has options: Include data (raw CSV) · Include story cards · Include canvas notes · Include ML runs · Order: by step then dashboard order (default) or by Flow reading path (P1). | Options are remembered per user. |
| NB-11 (P0) | The notebook never contains secrets, user identifiers, or the model's prompts. Generated analysis code contains no network calls; the only network use is the requirements cell's pinned `pip install` line. | Static check in the exporter's tests. |
| NB-12 (P1) | Chart PNGs embedded; Flow reading-path order; "Open in Colab"; Kaggle variant; PDF and Markdown renderings via nbconvert for the one-page report. | — |

---

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| **Performance** | Titanic-sized file: profile ≤ 3 s; widget query ≤ 300 ms; dashboard first paint ≤ 2 s after build; cascade after a save ≤ 5 s to all widgets re-rendered. 50 MB file: profile ≤ 60 s; grid scroll stays at 60 fps with paging; headless clean ≤ 5 min (budget). |
| **Reliability** | Jobs are checkpointed per step and resumable after a server restart. The UI never shows a raw exception. |
| **Security** | Generated code runs in a sandbox with no network, CPU/memory/time limits, per-dataset isolation, only the dataframe in scope. Cell values enter prompts only as delimited data blocks. Per-user caps: 50 MB per file, 500 MB per user, 7-day expiry, rate limits, token budget. |
| **Security (owner's decision)** | A visitor is a cookie, so the per-user caps reset if the cookie is dropped. Two more caps don't. All users' model calls together are capped per UTC day (`APP_TOKEN_BUDGET`, default 10M tokens); past it, model features answer "Sherlock has used today's model budget for everyone" and everything else keeps working. New users are capped at 300 an hour per client IP (`NEW_USERS_PER_IP_HOUR`), which is high enough for judges sharing a network. Chat roles must be NVIDIA's own Nemotron models (`nvidia/` publisher). |
| **Privacy** | Data is stored only on Sherlock's own backend (the Render service's persistent disk; on the Nebius alternative, its mounted volume), and cell values leave it only inside prompts to Nebius Token Factory. No third-party analytics. Retention claims are made only after checking the terms of the host and of Token Factory. |
| **Accessibility** | Keyboard operable throughout; visible focus; text contrast ≥ 4.5:1; color never the only signal; `prefers-reduced-motion` respected. |
| **Browser support** | Latest Chrome, Edge, Firefox, Safari on desktop. |
| **Observability** | Every LLM call logged with model, tokens, latency, purpose and outcome; every job with timings; errors with request IDs. |

---

## 9. Constraints and assumptions

- Inference: NVIDIA models via Nebius Token Factory for every role, following the track's guidance (Ultra for demanding reasoning, Super or Nano for fast everyday calls): large = Nemotron 3 Ultra (cleaning diagnosis and proposals), medium = Nemotron 3 Super (critic, curation, SQL, plans, overview, synthesis, narration, answer composition), small = Nemotron 3 Nano (routing and the chat thread's summary), embed = an NVIDIA embedding model from the Token Factory catalog. Narration and answer composition run on Super because Nano failed at them in live runs (TRD §7.4, §8.1). The hackathon rule needs at least one NVIDIA open-source model; Sherlock uses no other provider, and the app refuses to start if a configured chat model is not Nemotron (TRD §3.5). If the catalog has no NVIDIA embedding model, embeddings are switched off and value resolution uses exact and fuzzy matching only. As built, the catalog has none, so `embed` is empty (TRD §3.5). Model IDs, context lengths and feature support (tool calling, JSON-schema output) are confirmed and recorded in `FEEDBACK.md`; the architecture does not depend on any single capability. As built, `FEEDBACK.md` records the IDs and the tool-calling and JSON-schema checks, but no context lengths: the catalog's `/v1/models` returns only IDs.
- Hosting: the backend runs on **Render** as one Docker web service built from `api/Dockerfile`, with a persistent disk mounted at `/data`. A service with a disk is single-instance, which matches the one-process design (TRD §3.1). Jobs run in-process (`JOB_BACKEND=local`). Why: the Nebius AI Cloud tenant for this account was new and suspended (it has no credits or billing, separate from the Token Factory credits), and the rules don't require Nebius hosting. The Nebius route below stays documented and scripted (`scripts/deploy.sh`) as the alternative, and moving to it is one deploy plus a URL change.
- Hosting, Nebius alternative: backend on a Nebius Serverless Endpoint; heavy jobs on Serverless Jobs with a local worker-pool fallback. Persistent storage on the endpoint is verified on Day 1; if it fails, the same image runs on one Nebius AI Cloud VM with a disk. The rules require running on Token Factory or AI Cloud, which inference on Token Factory already satisfies; Nebius hosting is a choice, not a rule. The submission names only the Nebius services the deployed app actually uses (Serverless Jobs only if `JOB_BACKEND=nebius` runs in production).
- Availability: the public URL (and its paid Render plan), the Token Factory key and enough Token Factory credit to serve judges stay live through the hackathon's judging period and winner announcement, not only until the submission deadline.
- Charts: Bklit UI (MIT). Its Studio is proprietary and excluded.
- Sample data: titanic3 (1,309 rows) if its license allows bundling; otherwise fetched at setup, or Kaggle's `train.csv` after a license check.
- Team: one or two people. The implementation plan has a cut order if it stays one.

---

## 10. Release criteria (go / no-go for submission)

Go when all are true:
1. Every P0 requirement not removed by the Implementation Plan's cut order passes its acceptance criteria on the five-file end-to-end set (named in Implementation Plan §6).
2. The public URL works from a fresh browser with no console errors on the sample flow.
3. Grounding test 100%; ask-anything eval ≥ 85% and 0 unsourced numbers.
4. The cleaning benchmark has been run and its numbers are in the README.
5. README, LICENSE, `FEEDBACK.md`, video and description are complete and cover everything in §12.
6. The exported notebook for the sample executes cleanly in a fresh environment and reproduces the current version.
7. The repo is public, opens without a login, and shows the MIT license at the top of its page; no secret is in its history.
8. Every configured model role is an NVIDIA model, confirmed on the public deployment through `/healthz` and the `llm_calls` log.
9. The cold-start user test and the baseline comparison (§4) have been run and their results are in the README.

---

## 11. Open questions (owner: As Wasti, resolve by Oct 20)

| Question | Blocks | Default if unresolved |
|---|---|---|
| Must the app be hosted on Nebius? | Hosting plan | Resolved from the official rules: no. Running on Token Factory or AI Cloud is the requirement, and Token Factory inference meets it. Sherlock hosts on Render, with Nebius hosting as the documented alternative (§9). |
| Which Nemotron models does Token Factory serve, with which features? | Model assignments (TRD §3.5) | Use the largest available Nemotron model for reasoning roles |
| Does Glide Data Grid cover range select, range paste and fill handle? | CSV tab library | Keep Glide; if it lacks them, cut fill handle and range paste to P1 (AG Grid Community has no range selection, clipboard or fill handle) |
| Does Bklit expose custom tooltips and shared hover state? | Hover linking | Edit the copied source |
| Sample file license | Bundling | Resolved: OpenML 40945 lists the Titanic data's licence as "Public" (Harrell and Cason, Vanderbilt Biostatistics), so `api/samples/titanic3.csv` is bundled; `scripts/fetch_sample.py` rebuilds it from OpenML |
| Solo or two people? | Timeline | Solo; apply the cut order early |

---

## 12. Submission requirements and judging

Sources: [official_page.md](official_page.md) (the Devpost rules, which control) and [judges_rubric.md](judges_rubric.md) (the judges' panel). This section maps each requirement to what satisfies it.

### 12.1 Mandatory requirements (judging stage one: pass or fail)

| Requirement | How Sherlock meets it | Artifact |
|---|---|---|
| Runs on Nebius Token Factory or Nebius AI Cloud | All inference on Token Factory (the Nebius service the app uses); hosted on Render (§9) | Deployed app; README "NVIDIA models and Nebius" section |
| Uses at least one NVIDIA open-source model | Every role is an NVIDIA model; startup check (TRD §3.5) | `llm_calls` log; README model table |
| Fits the chosen track (Best Apps and Agents: a practical app or agent people would actually use, with Nemotron on Token Factory) | A working analyst agent on the user's own CSV, end to end | Hosted URL; video |
| A working project, not a concept | Every P0 not removed by the cut order passes its acceptance criteria (§10) | Hosted URL; end-to-end set |

### 12.2 Submission form

| Item | Required content | Where it comes from |
|---|---|---|
| Category | Best Apps and Agents | — |
| Project description | Problem, audience, solution, technical architecture, demonstrated result, differentiation, limitations, future work | §3.1, §3.2, TRD §1, README benchmark and user-test tables, Implementation Plan §7 |
| Working demo URL | Public, no login, "Try with sample" works from a fresh browser; live through judging (§9) | P0-11 |
| Demo video | Public YouTube, ≤ 3:00, shows the working product and how the NVIDIA models and Nebius are used. The live rules say "less than three (3) minutes", so under 3:00 | Implementation Plan §9 |
| Public repository | GitHub, readable without a login | `github.com/n1mk1/sherlock` |
| Open-source license | MIT, `LICENSE` at the repo root so it shows at the top of the repo page | `LICENSE` |
| README | Setup and run commands, the NVIDIA models and what each does, Nebius Token Factory and the other Nebius services used | `README.md` (Implementation Plan §7) |
| Technology feedback | Feedback on Token Factory, the Nemotron models, and Nebius AI Cloud as far as it was tried (the suspended new tenant and the separate billing) | `FEEDBACK.md` (Implementation Plan §7) |
| Pre-existing project disclosure | Not applicable: the project was started inside the submission period | — |
| Builders & Brews city | Only if an IRL event was attended (Toronto is a listed city) | — |

### 12.3 Judging criteria (stage two, 25% each)

| Criterion | What judges look for | What demonstrates it in Sherlock |
|---|---|---|
| Technological Implementation | Platform features used for a real reason; justified model choices; working core; trade-offs understood | Model roles chosen by task weight (Ultra for planning fixes, Super for SQL, narration and answers, Nano for high-volume routing; §9), with measured latency and cost per role (§4); grounding and verification that the model can't bypass; sandboxed execution; benchmark and eval tables; architecture diagram |
| Design | A complete product, not a proof of concept; value within 30 s; the "aha" within 2 minutes; clear first action; visible progress and errors | "Try with sample" gives a dashboard and stories in seconds; the overview card puts conclusions before evidence; live cleaning log, job tray and cascade progress; empty states with one action; accessibility (UI/UX brief §8) |
| Potential Impact | A specific audience and pain; evidence the product improves on today's workflow | §3.1; cold-start user test and baseline comparison (§4); "rows deleted: 0" and the cleaning benchmark |
| Quality of the Idea | Non-obvious, differentiated, understands the hard parts | §3.2; the trust design (chip-only narration, verifiers, quarantine instead of delete, honest ML against baselines); notebook export as an exit, not a lock-in |

Ties are broken by the first criterion in the table, then the next.

### 12.4 Prizes Sherlock can enter

- One overall award or the Best Apps and Agents track award.
- Best Use of Tavily (bonus) only if a Tavily API call runs in the deployed app (ASK-11, STORY-9). It is not claimed otherwise.
- Most Valuable Feedback (bonus), judged on completeness, viability and potential impact: `FEEDBACK.md` is written to those three criteria (Implementation Plan §7).
- A City Winner award only if an IRL Builders & Brews event was attended.

### 12.5 Panel guidance applied

- **Conclusion before evidence.** Overview card first, verdict line first in model cards, recommended next questions under the chat. The recommended questions (ASK-9) were removed by cut 9 (Implementation Plan §2.0).
- **Quantify against a baseline.** ML against majority and one-column rules; the user test against doing it by hand.
- **Document limitations.** The README has a "Known limitations" section: failed eval questions, cleaning cases the benchmark misses, file types that fail, anonymous identity with no recovery, and the 7-day expiry.
- **Every integration has a job.** No service or model is named in the submission unless the deployed app uses it.
