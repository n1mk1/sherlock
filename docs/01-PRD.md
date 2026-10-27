# Sherlock · Product Requirements Document (PRD)

Version 1.2 · Owner: As Wasti · Status: final for the Nebius x NVIDIA Global AI Hackathon

Companion documents: [App Flow](02-APP-FLOW.md) · [UI/UX Design Brief](03-UIUX-BRIEF.md) · [TRD](04-TRD.md) · [Backend Schema](05-BACKEND-SCHEMA.md) · [Implementation Plan](06-IMPLEMENTATION-PLAN.md)

---

## 1. Product summary

**One line.** Sherlock is a data analyst, ML engineer and storyteller in one: drop in a CSV, and it cleans the data, builds a dashboard, runs honest models on any slice, and tells you what it all means, while showing its work at every step.

**The problem.** Getting from a raw CSV to a decision takes a chain of specialists: someone to clean the data, chart it, model it and explain it. Each handoff loses context, and the final numbers can rarely be traced back to how they were produced. AI tools that promise to do it end to end often hallucinate numbers, hide their reasoning, or need the user to know pandas and statistics.

**The product.** A web app where every number comes from executed code, every change to the data is a recorded, reversible step, and the AI translates, orchestrates and narrates rather than computes. The user works through a dashboard, a spreadsheet view of the data, a story canvas, and a chat bar that answers questions about any of them.

**Hackathon framing.** Built for the Best Apps and Agents track. All inference is NVIDIA Nemotron on Nebius Token Factory; the app is hosted on Render, with Nebius as the documented alternative (§9). Submitted by 2026-10-30 13:00 EDT. §12 maps the submission rules and judging criteria.

---

## 2. Goals and non-goals

### 2.1 Goals (ranked)

1. **Trust.** Every number on screen can be traced to a query, a recipe run or a cleaning step in one click. Zero unsourced numbers in generated text.
2. **Autonomy with control.** Cleaning runs headless by default and produces a result a human can audit, undo and override cell by cell.
3. **Breadth of questions.** The user can ask, in plain language, about the data, the statistics, the drivers, specific rows, the cleaning history, the widgets, the stories, the models, the meaning of columns, and the app itself.
4. **Honest ML.** Every model is scored against baselines on held-out data; leakage is detected and excluded; "no signal" is a valid result.
5. **A story that stays true.** Story cards are written from computed facts, update when the data or widgets change, and never overwrite what the user wrote.
6. **Generic.** Any CSV a judge uploads works, or fails with a clear message. No dataset-specific code.
7. **Portable.** At any moment the whole investigation (load, every cleaning step and edit, every widget, model and story) can leave the app as a runnable Jupyter notebook (`.ipynb`). Nothing Sherlock did is locked inside Sherlock.

### 2.2 Non-goals (for this release)

- Multiple files joined together, or comparisons across CSVs.
- User accounts, teams, sharing links, permissions.
- Real-time or streaming data sources, scheduled refresh, alerts.
- Free-form ML code written by the model.
- An editable notebook inside the app with a live kernel. The export is a faithful, runnable reproduction; editing happens in Jupyter, VS Code or Kaggle. (An in-app Notebook tab is P2.)
- A full catalog of ML methods. In scope: Auto, linear regression and logistic regression. Cut 4 (Implementation Plan §2.0) removed the two named methods, so only Auto ships; others are P1/P2.
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

The operator has a messy export (from a CRM, a store, an HR system, a survey tool) and a question to answer from it. Today they either work by hand in a spreadsheet, which takes hours and leaves no record of what changed, or paste it into an AI chat. The chat answers fast but can't show where a number came from, forgets the cleaning between sessions, and sometimes invents figures. Either way the answer can't be defended when someone asks "how do you know?". Sherlock's answer arrives as fast as a chat answer and stays as checkable as a careful analyst's work.

### 3.2 Alternatives and how Sherlock differs

| Alternative | What it does well | Where it falls short for this user | What Sherlock does instead |
|---|---|---|---|
| Doing it by hand (spreadsheet, pivot tables) | Full control, familiar | Slow; cleaning edits overwrite the original and aren't recorded; no modelling | Every change is a recorded, undoable step with cell lineage; cleaning and modelling run on their own |
| General AI chat with code execution | Fast answers to one-off questions | Work lives in one conversation; numbers in prose aren't bound to the code that produced them; no persistent dashboard or cleaning history | Numbers in generated text are chips bound to computed facts and verified before display; the dataset, steps, dashboard and stories persist and update together |
| BI tools with an AI assistant | Polished dashboards, sharing | Expect data that is already clean and modelled; cleaning happens in a separate tool | Cleaning, dashboard, models and stories are one pipeline on one dataset, and a data change flows through all of them |
| Notebooks (Jupyter and hosted notebook tools) | Reproducible, flexible | Need pandas, SQL and statistics skills | Sherlock writes the notebook for you: the export is a runnable `.ipynb` of everything it did |

The insight behind the design: the hard part of AI data analysis is not producing an answer but making it trustworthy. So every number is left to executed code, every data change to a verified step, and every claim to a fact sheet the user can open.

---

## 4. Success metrics

| Metric | Target | How measured |
|---|---|---|
| Unsourced numbers in generated text | 0 | `sherlock eval grounding`: 100% of story chips bound to their fact and still holding when re-checked by `verify` (`sherlock/stories/facts.py`, TRD §7.4); `sherlock eval ask` counts unsourced answers |
| Ask-anything accuracy on the eval set (≈50 questions: Titanic plus at least 15 on a second end-to-end file) | ≥ 85% correct; ≥ 95% of unanswerable questions answered with an honest "can't" | `sherlock eval ask`, run on every prompt or model change. The set (`api/samples/eval/ask_questions.yaml`) has 61 questions: 39 on Titanic, 17 on `sales_dated.csv`, 5 on `reviews_text.csv`. Only 3 are unanswerable, too few to measure the second target |
| Cleaning benchmark (corruption injected into 3 clean datasets, plus the look-alike and ambiguous-date sets of CLEAN-4b) | Recovery rate reported; harm rate ≤ 2% of clean cells; row loss = 0 | `sherlock eval corruption` |
| Planted-truth ML tests | 3/3 pass (finds planted drivers; excludes planted leak; reports no signal on noise) | `sherlock eval ml` and the test suite |
| Time from "Try with sample" to a complete dashboard with stories | ≤ 5 s (cached) · ≤ 180 s live for a 1,309-row file | Manual timing |
| End-to-end CSV set | 5/5 files reach a dashboard or a clear error | Manual run before submission |
| Notebook export | The exported `.ipynb` for every file in the end-to-end set executes without error in a fresh environment (nbclient, in a new virtualenv built from its requirements cell) and its final DataFrame equals the current version cell for cell | `sherlock eval notebook` and a test on the sample; manual on the set |
| Demo video | Under 3:00, shows every hero moment in the demo script (Implementation Plan §9), and names the NVIDIA model and Nebius service behind each AI moment | Submission |
| Cold-start user test | At least 3 people who have never seen Sherlock reach a sourced answer on a CSV of their choice without help; time to first sourced answer, where they hesitated, what they said and what was changed after are recorded | Run by hand with the protocol in the target; results go in the README's Results |
| Baseline comparison | Time and steps to answer the same 3 questions on the same file by hand (spreadsheet) versus with Sherlock, plus how many answers each way can be traced to their source | Run by hand; results go in the README's Results and the video |
| Model cost and latency | Per role (large, medium, small, embed): model ID, median latency, tokens per call and cost per sample run, from `llm_calls` | README model table (`sherlock llm stats`: p50/p95 latency and tokens per role and purpose; it doesn't compute cost) |

---

## 5. Scope and priorities

Priority definitions: **P0** ships by 2026-10-29, except items removed by the Implementation Plan's cut order (§5), which is the only way a P0 item may be dropped. **P1** ships only if P0 is complete; order within P1 is binding. **P2** is after the hackathon and is listed only so decisions today don't block it.

### 5.1 P0

**Cuts applied:** all nine rows of the Implementation Plan's cut order (§5). They narrow P0-03 (settings), P0-04 (brushing), P0-05 (CSV tab extras), P0-06 (method chooser, `predict`, brush scope), P0-07 (material-change check), P0-08 ("rewrite", "take the story toward X") and P0-10 (suggested questions, `?`). Plan §2.0 has the detail, and each affected requirement in §7 says "Removed by cut N". The release criteria (§10) apply to what remains.

| ID | Area | Requirement |
|---|---|---|
| P0-01 | Load | Drag-and-drop anywhere, Upload button, "Try with sample" (Titanic). Import preview. Clear errors for bad files. |
| P0-02 | Clean | Cleaning offer after profiling. Headless auto-clean with live log, verifiers, gate, report, decision log. "Clean with AI" any time from the CSV tab, on the whole file or a selection. |
| P0-03 | Shell | Three panels; CSV / Dashboard / Flow tabs; chatbot bar; collapsible side panels; settings overlay; light and dark modes, each with five accent colors (Verdigris by default). Not built yet: at 1024px and wider the right panel resizes but can't collapse; the left one collapses to a rail. |
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

None of these is built yet. (Four P1 requirements outside this list are built: LOAD-7, CLEAN-4f, CLEAN-12 and ASK-11.) Four show in the app as disabled choices: "Ask me before each fix" in the cleaning plan's Mode row, and "Find groups", "Find unusual rows" and "Forecast" in the analysis menu.

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
| **Story card** | A short narrative about a widget, the dashboard, or a set of cards, with number chips bound to a fact sheet. Kinds: overview, widget, synthesis, direction, answer (a chat answer added to Flow). No code writes direction cards (cut 3, Implementation Plan §2.0). Flow notes are canvas nodes, not story cards. |
| **Number chip** | An inline number in a card that is bound to a fact-sheet value and updates when it changes. A hand-typed number is a chip marked "unverified". |
| **Canvas** | The Flow tab's document for a dataset: nodes (cards, notes) and labeled edges, stored as JSON Canvas. |
| **Job** | A background task (cleaning, dashboard build, story generation, ML run, export) with streamed progress. |
| **Cascade** | The automatic reaction to a new version or widget change: widgets re-query, affected runs are invalidated, affected stories update. |
| **Notebook** | A Jupyter `.ipynb` generated from a dataset's current state: one cell group per step, widget, run and card, in a deterministic order. It is derived, never hand-maintained: regenerating it after a change always reflects the new state. |

---

## 7. Functional requirements

Each requirement has an ID, a statement, and acceptance criteria. "Must" is binding for the stated priority. "Not built yet" marks a criterion the code doesn't meet; "Removed by cut N" marks one the cut order dropped (Implementation Plan §2.0), then says what remains.

### 7.1 Loading data

| ID | Requirement | Acceptance criteria |
|---|---|---|
| LOAD-1 (P0) | The user can load a CSV by dragging it anywhere over the app, by clicking Upload, or by clicking "Try with sample". | Dropping a file over any part of the window shows a full-window drop target and accepts the file. Upload opens the OS file picker filtered to `.csv, .tsv, .txt`. The sample loads without a file picker. |
| LOAD-2 (P0) | Before import, the user sees a preview: the first 20 rows as parsed, the detected delimiter, encoding and header row, and can correct each. | Changing delimiter, encoding or header row re-renders the preview within 500 ms. "Import" is disabled until at least one column and one row parse. Not built yet: the delimiter and encoding are detected, but the header row starts at row 1 for the user to change. |
| LOAD-3 (P0) | Files are capped at 50 MB, 1,000 columns and 2,000,000 rows. Oversized or unreadable files produce a specific, plain-language error. | Error messages name the cause (too large, not a delimited text file, empty, could not decode) and what to do. The app never shows a stack trace. |
| LOAD-3a (P0, owner's decision) | A file whose rows have different numbers of fields still imports with its real columns. Short rows are padded with empty cells. A row with more fields than the header keeps its extra values in `col_N` columns past the header and is quarantined ("extra fields"), never dropped. | A file with one long row, or with a tenth of its rows short, imports with its real columns, not as a single column. |
| LOAD-4 (P0) | Each loaded CSV becomes a dataset in the user's library with a status: profiling → offer → cleaning → building → ready, or failed. | The CSV panel shows the status within 1 s of each change. Switching datasets does not stop background work. |
| LOAD-5 (P0) | The user can rename and delete a dataset. Deletion asks for confirmation and removes everything belonging to it. | After delete, the dataset's folder and rows are gone; a toast offers Undo for 10 s; the data is soft-deleted and purged 10 minutes later. |
| LOAD-6 (P0) | A stable `_row_id` is assigned to every row at import and never changes. | New rows added later get fresh IDs; IDs are never reused. |
| LOAD-7 (P1) | The user can give the URL of a data dictionary or codebook for the file (the optional "Data dictionary URL" in the import preview). Sherlock reads it with Tavily and keeps what it says about each column as a note, with the page's own words and its address. Only a URL the user typed is fetched, and nothing from the file is sent (TRD §7.1.1). | A dictionary page that describes the columns gives a note on each column it describes, shown on hover over the column's header in the CSV tab: Sherlock's sentence (no digits), the page's words quoted, the address and the date read. A site root is searched for its dictionary page. With no Tavily key, or when the page can't be read, the import goes on and one line says the dictionary wasn't read. Notes are metadata: they never change a value. |

### 7.2 Profiling

| ID | Requirement | Acceptance criteria |
|---|---|---|
| PROF-1 (P0) | After import, Sherlock builds a data card for version 1: per column, the inferred type (int, float, bool, date, datetime, category, text, id, or empty for a column with no values), the role (measure, dimension, time, id, target-like, free text, or empty), missing count and %, distinct count, min/max/mean/median for numbers, top values for categories, and detected issues. | The data card is complete for a 1,309 × 14 file within 3 s and for a 50 MB file within 60 s. Types are inferred from values, not from the loader (`all_varchar` import). A deterministic typing step (code, not LLM) then commits as step 1 on every path, including "Clean it myself" and "I'll clean it myself": it casts every column whose values parse losslessly at ≥ 99% (missing-value sentinels such as `N/A` become empty first) and quarantines rows whose cast fails. It is undoable like any step, with a warning. A file with no column to cast gets no typing step and stays at version 1 (TRD §7.1). |
| PROF-2 (P0) | The data card is shown as the cleaning offer's one-line summary and in the CSV tab's column headers. | Summary names the top 3 issues by impact, e.g. "263 missing ages, 1,014 missing cabins, 2 possible leakage columns". The offer shows the counts ("1,309 rows · 14 columns · 7 issues"), then the three most severe issues as a list, one per column ("263 missing in age", "boat records the outcome"). |
| PROF-3 (P0) | The data card is recomputed for every new version and cached per version. | A cascade never uses a stale data card. |

### 7.3 Cleaning

| ID | Requirement | Acceptance criteria |
|---|---|---|
| CLEAN-1 (P0) | After profiling, the centre panel shows a cleaning offer with the summary and two choices: "Clean with AI", which opens the cleaning plan (CLEAN-8a), and "Clean it myself", which builds the dashboard on the data as it is and opens the CSV tab to edit by hand or ask the chat. | The offer appears automatically unless the "After upload" setting is "Open the cleaning plan" (the plan opens by itself and says why) or "I'll clean it myself" (the build screen says why). Nothing is cleaned without a click on Start cleaning. |
| CLEAN-2 (P0) | Headless cleaning runs as a background job with a live log: one entry per step with a timestamp, the column, what was tried, what was chosen and why, and the gate decision. | Log entries arrive over SSE within 1 s of the event. The user can switch datasets or tabs; the job continues and the CSV panel shows progress. The progress total ("step 3 of 12") is the number of issues the run expects to attempt; it grows only when a fix exposes a new issue, and the run may end before it when a fix settles a later issue. |
| CLEAN-3 (P0) | Every cleaning step is validated by the verifiers in §7.3.1 before commit. A step that fails any verifier is not committed. | Row count never changes due to auto-cleaning. No parse op commits with failures converted to blanks: a failed value's row is quarantined and the original text is kept in lineage (the typing step meets the rule the same way). |
| CLEAN-4 (P0) | Steps are gated: high confidence commits; medium commits with a flag and the original kept in lineage; low is skipped and logged. | The report lists every skipped issue with its reason. |
| CLEAN-4b (P0) | The Cleaner doesn't commit a guess the data can't settle. A step is skipped when two of its candidates pass every check but give different values to more than 1% of the cells they both change; the log shows two of those cells both ways. A case or spacing variant of one value is the same value, not a disagreement. A lone candidate counts as neutral, not full, agreement. Values that differ only in their numbers ("Region 1", "Region 2"), or two values that are each common, are never merged, unless one is the other with an inner letter left out ("Wst", "West": a typo). A merge of two common spellings always commits with a flag, for review. A date column whose every value reads both ways (day-first and month-first) stays text, with no order guessed, until the user says which. | The corruption benchmark's look-alike and ambiguous-date sets (TRD §14) end with 0 harm and 0 wrong values, and the report lists each such skip with its reason. |
| CLEAN-4a (P0, owner's decision) | Two further rules skip a step whatever its confidence. A step may not quarantine more than twice as many rows as its issue has, plus 10. A step the reviewer says changed values it shouldn't have is skipped too (except a domain rule's quarantine, CLEAN-4c); the reviewer's other concerns don't block a commit. | The report lists such a step as skipped, with its reason. |
| CLEAN-4c (P0) | A value outside its column's plausible domain, as the impossible-values detector's rules name it (a negative quantity, an age over 120, a percentage outside 0–100, a date in the future or before 1800), is quarantined, not kept and not replaced by a guess. The diagnosis can't leave it as is. Low confidence commits it with a flag instead of skipping it. When the reviewer objects to a fix that only quarantines the rows the rule names, the step commits with a flag instead of being skipped. | On a file with customer ages −5 and 999, the run quarantines those rows (with a flag at worst), and no widget, story or answer averages them. With no passing candidate it is still skipped. |
| CLEAN-4d (P0) | A column taken for an ID is never cleaned, so the ID rule must not take measures. A mostly-unique column whose values mostly read as amounts (a decimal part, money, a percentage or thousands separators: "36.74", "$4.20") is a measure stored as text, not an ID, unless its name says ID. A float column is never an ID candidate. An ID flag doesn't block a column's placeholder or formatted-number fixes. | A `unit_price` column of "36.74", "$4.20" and "n/a" values gets its placeholder and numbers-as-text fixes and becomes a number. Codes and whole numbers ("O0001", "1001") can still be IDs. |
| CLEAN-4e (P0) | Numbers stored as text in a measure ("36.74", "$4.20", "1,250") always get a parse step. When the model's proposal fails (for example a reply cut off at its token cap) or none of its fixes passes the checks, the Cleaner tries its own parse: the helper that reads currency, separators, percentages and negatives, with the values it can't read quarantined. On a measure the diagnosis can't leave such a column as text. | On a file whose `unit_price` mixes "36.74" and "$4.20", the run leaves `unit_price` a number column even when every propose reply is cut off, and "average unit price by region" needs no text-to-number cast. A minus sign survives the parse. |
| CLEAN-4f (P1) | A cleaning step's title names its column once: "<what the step did> (<column>)", or the step's label alone when the label already names the column as a word (in brackets or not, with underscores or spaces). | "Parse numbers (units)", "Parse numbers (handles commas, currency, %) on units"; never "… on units (units)" or "… (units) (units)". |
| CLEAN-5 (P0) | Auto-cleaning never deletes rows. Rows that would be removed (duplicates, impossible records) are quarantined and shown. | Quarantined rows appear in the CSV tab under the "only flagged" view, marked, and can be restored (Restore in the row menu creates a step). Quarantined rows are excluded from widgets, ML and stories, and the exclusion is visible in the SQL under "How do you know?". The "only flagged" view and the row menu: removed by cut 5. Quarantined rows are marked in the grid, and the toolbar's Restore adds the selected ones to the unsaved edits, which Save commits as a step. |
| CLEAN-6 (P0) | The run ends with a report: counts of issues found / fixed / flagged / skipped, each step with its summary and impact, and the decision log. The report also says what became of each issue: fixed, flagged, checked and kept (the Cleaner looked and judged the values real), couldn't fix, not attempted (unticked, waiting on the user's choice, or not reached before the budget ran out), and, apart, marked and not changed. | The report is reachable from the CSV tab's Changes panel at any later time. Each count comes from why the issue was skipped, recorded when it was, never from parsing the reason. Not built yet: the report screen shows the first four counts only. |
| CLEAN-7 (P0) | Every committed step is undoable from the Changes panel. Undoing step k when later steps exist asks for confirmation and replays the later steps on top (or fails clearly if a later step depends on it). | Undo produces a new version; nothing is ever mutated in place. |
| CLEAN-8 (P0) | "Clean with AI" is available in the CSV tab toolbar at any time, with scope: whole dataset, current selection, or rows added since the last clean. It opens the cleaning plan (CLEAN-8a) with that scope. | It runs on the current version. Hand-edited cells are skipped and listed in the report, with an option to include them. Unsaved edits must be saved or discarded first (prompted). Not built yet: the option to include hand-edited cells; the API takes `include_user_edited`, but the app always sends false, so every clean leaves them alone. |
| CLEAN-8a (P0, owner's decision) | Before Clean with AI runs, from the offer or the CSV tab, Sherlock shows a cleaning plan: the code detectors' diagnosis of the current version, one fix per issue grouped into modules (types and parsing, missing and placeholder values, spelling and formatting, duplicates and broken records, outliers, other checks), each with its count, up to 5 example values and the planned action, and **every fix ticked**. The user can untick fixes, one at a time or a whole module, then Start cleaning or Discard. Leakage and ID-like columns show as "Marked, not changed", with no checkbox. | No number in the plan comes from the model. A plan made on an older version is diagnosed again and merged (ticks kept) before it's shown or started. An unticked fix is skipped without a model call, logged "not in your plan", and listed in the report as "You left this out of the plan"; issues found mid-run are still attempted. The plan isn't a modal, so the chat bar stays usable (placement: App Flow §4.1). The lazy path stays one click: Start cleaning with everything ticked. "Clean them" on the toast after saving new rows, and Approve on chat's "clean these rows" proposal, open the plan with those rows as its scope; they start nothing themselves. |
| CLEAN-8b (P0, owner's decision) | In the cleaning plan the user can also rewrite any fix in plain words (✎, with Reset to Sherlock's wording), add steps of their own (a column or the rows, and an instruction), remove those steps, and ask the chat to do any of this, which applies to the plan at once. The Cleaner writes and checks code that follows each instruction; editing the code itself is CLEAN-10's. | The user's steps run first and count against the budget. Every hard check still applies (placeholder fills, the row ledger, the quarantine cap: at most a fifth of the rows for a step with no detector), and a step that fails one is skipped with the reason. A user step that would be skipped for low confidence commits with a flag ("kept because you asked for it") and can be undone; the diagnosis can't end it as "leave as is". The step records the instruction ("You asked: …") in Changes, the report ("Your steps": fixed, flagged, skipped or not reached) and the notebook. Chat's reply is written by code ("Unticked 1 fix: missing values in cabin."). An ambiguous-dates fix asks which order the dates are written in (Day first · Month first), showing three values read both ways. The order picked is the user's instruction for that fix, replaces the Cleaner's three-way vote with one diagnosis, and is listed under "Your steps". A column whose every date reads both ways is cleaned only once an order is picked (CLEAN-4b). |
| CLEAN-8c (P1) | Every finding has a severity level: breaks answers, skews answers, splits groups, worth a look (probably real), or cosmetic. Code gives each a default level from its detector and its column: one level more severe on the target or a measure, one less on free text; an outlier, a missing value or a broken dependency stays "worth a look" whatever its column, and duplicate rows take no adjustment. Leakage and ID columns have no level. The Cleaner attempts the issues by level, breaks first, then by size, so when the budget runs out what's left is the least severe; a column's placeholders still go before its impossible values. | No level comes from a number the model wrote (Rule 2). The same damage in a measure is attempted before the same damage in a category column. Not built yet: a review by the model with a one-line reason, and the plan grouped by level with "Worth a look" unticked. |
| CLEAN-9 (P0) | The budget per headless run is 20 attempted issues (committed or not), 5 minutes wall-clock, and a configurable token cap (`CLEAN_MAX_STEPS`, `CLEAN_MAX_SECONDS`, `JOB_TOKEN_BUDGET`; TRD §10). Hitting any budget ends the run cleanly with a partial report. | The report says which budget ended the run. |
| CLEAN-10 (P1) | Step-by-step mode: each proposed step appears in the chat thread as an approval card with summary, code (collapsed), impact preview, and Approve / Edit / Reject. | Nothing commits without Approve. Edit opens the code for changes and re-runs the preview. The mode is chosen in the cleaning plan's Mode row (CLEAN-8a): "Run on its own" or "Ask me before each fix", shown disabled with "comes later" until this is built. |
| CLEAN-11 (P1) | The committed pipeline can be exported as a runnable Python script. | The script reproduces the latest version from the raw file. |
| CLEAN-12 (P1) | The checks are a registry. Each detector's module exports one spec: its id, its label in plain words, a one-sentence description, its plan module, its severity weight, its default severity level, and how the Cleaner treats it (never changed, still fixed on an ID column, a domain rule, settled by a vote, a fix code writes itself, a check that goes first on its column). The plan, the Cleaner, the log, chat and the web app read a detector's facts from its spec, never from their own list of names. A catalog lists every check. | One label per detector, the same in the plan, the offer, the log and chat; the web app takes it from the catalog. The registry refuses a duplicate id, an unknown module or level, a weight outside 0–1, and a check that must go before an unknown check or before itself through others, so a bad built-in stops the API from starting. An issue whose detector is no longer registered still shows, its id in words. The 16 built-ins find exactly what they found before the registry. Every detector passes one contract suite (finds nothing in clean data, finds its own seeded damage, deterministic, leaves the data alone, within 2 s on 200,000 rows; TRD §14), and the corruption benchmark builds its damage from the detectors' own injectors. |

#### 7.3.1 Verifiers (all P0)

Row-count ledger (no unexplained row loss) · parse success rate reported, and any parse failure goes to quarantine rather than blank · lossless round-trip for type parses · sum and distribution conservation where the op should preserve them · no silent NaN introduction · dtype sanity · `pandera` constraints derived from the data card · no merge of look-alike categories that are different on purpose (CLEAN-4b) · no missing value filled with a placeholder word ("Unknown", "N/A") · no missing value filled unless a related column recovers it (owner's decision: missing values stay missing; a step the user asked for may fill) · the quarantine cap (CLEAN-4a, CLEAN-8b). Implementation: `sherlock/cleaning/verifiers.py` (TRD §7.2). The parse rate and distribution conservation (how little a numeric column's median and spread moved) are soft scores, not hard checks. Not built yet: a round-trip check on the Cleaner's own parses (the typing step's casts have one, `sherlock/profile/typing.py`) and sum conservation.

#### 7.3.2 Detectors (all P0, code not LLM)

Mixed types · sentinels (`-999`, `N/A`, `null`, `?`, empty) · whitespace and case variants · near-duplicate categories · exact and near duplicates · impossible values (negative ages, future dates) · numbers stored as text (currency symbols, thousands separators, locale decimals) · ambiguous date formats · mojibake · unit mixes · cross-column violations (`end < start`) · broken functional dependencies (city → state) · ID candidates · missingness patterns · outliers (robust statistics) · leakage candidates (columns that record the outcome). These are the 16 built-in detectors, one module each in `sherlock/cleaning/detectors/`, each registered with its spec (CLEAN-12).

### 7.4 Dashboard

| ID | Requirement | Acceptance criteria |
|---|---|---|
| DASH-1 (P0) | After cleaning (or "Clean it myself"), the dashboard is built automatically with 6–10 widgets chosen by interestingness, each validated (schema, SQL dry-run, ≤ 2,000 result rows). | A dashboard exists for every file in the end-to-end set. No widget shows an error state on first render for those files. |
| DASH-2 (P0) | A `driver_analysis` widget is included when a target-like column is detected. | On Titanic, "What drives survival?" is on the first dashboard. The widget is titled from the column's name ("What drives survived?") and is added when the file has at least 100 rows (ML-10). |
| DASH-3 (P0) | Widgets render on Bklit UI charts (plus custom heatmap, histogram, box plot, scatter, KPI card, table). | Every chart follows the active theme's tokens. |
| DASH-4 (P0) | Widgets can be dragged by their handle (⠿) and resized by their corner; layout persists per dataset. | Reloading restores the layout. Layout changes don't trigger the cascade. |
| DASH-5 (P0) | Clicking a bar, slice or cell sets a global filter that every widget inherits; one chip shows the active filter; clicking again or the chip's × clears it. | Filtered widgets re-query within 1 s for the Titanic file. Widgets with `inherit_global_filters: false` are unaffected. |
| DASH-6 (P0) | Brushing a range on a chart creates a row selection (predicate) that ML setup and chat can use. | The selection chip shows the row count. Esc clears it. Removed by cut 8: click-to-filter (DASH-5) stays, and ML scope comes from the filter or the whole dataset. |
| DASH-7 (P0) | Every widget has "How do you know?" which shows the SQL (for `sql` ops) or the recipe, scope and model card (for `ml` ops). | SQL shown is exactly what was executed. |
| DASH-8 (P0) | Widgets can be created and edited from chat ("add a chart of fare by port", "make this a line chart", "only show 1st class"). New widgets appear highlighted; edits are undoable. | The chat shows a link to the widget it changed. |
| DASH-9 (P0) | Widgets can be duplicated, collapsed to their header, and deleted (toast with Undo). | Delete removes its story card too; Undo restores both. |
| DASH-10 (P0) | The dashboard soft-caps at 20 widgets with a warning. | Adding the 21st shows the warning but is allowed. |
| DASH-11 (P0) | Any data change keeps the same dashboard: widgets re-query the new version, affected ML runs are marked outdated, affected stories update. | After a CSV-tab save, every widget that references a changed column re-renders with new numbers. |

### 7.5 CSV tab (spreadsheet)

| ID | Requirement | Acceptance criteria |
|---|---|---|
| CSV-1 (P0) | The CSV tab shows the current version in a virtualized grid with sticky headers and row numbers. Headers show type, missing % and a mini distribution. | Scrolling 50 MB files stays smooth (server-side paging). |
| CSV-2 (P0) | Cells changed by cleaning are tinted; hovering shows `old → new (step n)`. Quarantined rows are marked. Hand-edited unsaved cells have a distinct style. | The three styles are distinguishable in both themes without relying on color alone (icon or outline). The `old → new (step n)` hover: removed by cut 5; the three styles remain. |
| CSV-3 (P0) | Navigation: arrow keys, Tab/Enter, Ctrl+arrow to the data's edge, jump to row number. | Keyboard-only use covers all editing. Ctrl+arrow and jump to row: removed by cut 5. There is no jump to row; the grid's default Ctrl+arrow still moves to the first or last row or column. |
| CSV-4 (P0) | Selection: click; Shift+click and drag for ranges; header click selects a row or column; Ctrl+A. | The status bar shows count, sum, average, min, max for numeric selections. Range selection and the status-bar stats: removed by cut 5. The status bar shows how many cells are selected. The grid's default range selection (Shift+click, drag, Ctrl+A) still works, and Delete, Restore and Clean with AI act on the selected rows. |
| CSV-5 (P0) | Editing: type to replace, Enter or double-click to edit, Esc cancels; type-aware editors (category dropdown with existing values, number validation, boolean toggle, date picker); autocomplete from the column's values. | Invalid values are flagged inline and can be kept. Not built yet: the type-aware editors and autocomplete; every cell edits as text. |
| CSV-6 (P0) | Copy a range as TSV; paste a block from Excel/Sheets; fill down (Ctrl+D). | Pasting a 100 × 10 block takes under 1 s and shows as pending edits. Removed by cut 5. The grid's defaults still copy a selected range with Ctrl+C and paste the clipboard's text into one cell; there is no block paste or fill down. |
| CSV-7 (P0) | Rows: add above/below, duplicate, delete. All logged and undoable. | New rows get new `_row_id`s. Add above or below and duplicate: removed by cut 5. Add row adds a row at the top, and Delete marks the selected rows; both are saved as a step. |
| CSV-8 (P0) | Columns: sort (multi-column), resize, auto-fit. Sorting and filtering change the view only, never the data. | The version is unchanged by sort/filter. Not built yet: multi-column sort, resize and auto-fit; a header click sorts by that one column, and column widths are fixed. |
| CSV-9 (P0) | Find and replace with match count preview, regex option, scoped to selection or column. | Replace creates pending edits, not an immediate version. Replace: removed by cut 5. Find stays, over the whole file, with a match count, and shows only the matching rows. |
| CSV-10 (P0) | Per-column filters (values list, numeric range, contains, is empty) and quick views: only changed, only flagged, only missing. | Filters are view-only and persist while the tab is open. Removed by cut 5. |
| CSV-11 (P0) | Undo/redo (Ctrl+Z / Ctrl+Y) for pending edits; a pending count on the Save button; "Review changes" shows a diff with per-change discard. | Save creates exactly one new version containing all pending edits as one step. Undo/redo of pending edits and "Review changes": removed by cut 5. The pending count on Save, Discard, and one version per Save remain. |
| CSV-12 (P0) | Download the current version as CSV. | The download matches the grid's data (not its view filters). |
| CSV-12a (P0, owner's decision) | In the downloaded CSV, a text cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return gets a leading `'`, so a spreadsheet doesn't run it as a formula. Number, date and boolean columns export exactly. The original upload (`raw.csv`) is offered unchanged. | `=HYPERLINK(…)` in a text column downloads as `'=HYPERLINK(…)`; `-3` in a number column stays `-3`. |
| CSV-13 (P0) | Select cells and ask the chat about them or tell it to fix them; the change arrives as a reviewable step. | The chat context shows "n cells selected". The chip says "n rows selected", and only a request to edit or clean uses the selection (as a proposal to approve). Not built yet: a question about the selected cells isn't limited to them. |
| CSV-14 (P0) | Right-click menus for row, column and cell actions. | Every menu action has a keyboard equivalent listed on `?`. Removed by cut 5; the `?` sheet by cut 9. |
| CSV-15 (P0) | The right panel shows Changes: the cleaning report, every step and edit batch with its summary and impact, and Undo per step. | Unsaved edits appear at the top as "Unsaved (yours)". |
| CSV-16 (P1) | Column operations: add (empty with a type, or computed by chat), delete, rename, retype, reorder, hide/show, split, merge. | Each is a step. |
| CSV-17 (P1) | Row detail drawer; freeze columns; multiple ranges; fill handle with series; saved views; version history with restore and compare; Parquet/Excel export. | — |

### 7.6 ML

| ID | Requirement | Acceptance criteria |
|---|---|---|
| ML-1 (P0) | Every widget has an analysis dropdown with plain-language options: "What drives this?", "Predict a column", and (P1) "Find groups", "Find unusual rows", "Forecast". Options that don't fit the data are disabled with the reason. | "Forecast" is disabled with "needs a date column" on Titanic. "Predict a column": removed by cut 7; it is listed disabled, "Not in this release" (`sherlock/ml/registry.py`). |
| ML-2 (P0) | Setup shows target (pre-filled with the best guess), feature chips (excluded ones crossed out with the reason on hover), the row scope chip, and a Method selector (Auto, Linear regression, Logistic regression). Advanced settings are under "More". | A run can be started with one click after choosing an option. The best guess, and the builder's "What drives …?" widget, is never an ID, free text (values averaging over 40 characters, even when a few repeat) or a category with more than 20 values. The Method selector: removed by cut 4; the form says the run uses Auto. |
| ML-3 (P0) | Every supervised run performs: leakage check, fair split (rows that share an ID-like group, such as a ticket or an account, stay in one fold), preprocessing inside CV folds, baselines (majority/mean and best one-column rule), model search (Auto) or the chosen method, explanations, model card. | On the planted-truth tests: drivers found, leak excluded, noise reported as "no signal". |
| ML-4 (P0) | Linear regression reports coefficients with confidence intervals and p-values, R² and adjusted R², and a residuals plot. Logistic regression reports coefficients and odds ratios, accuracy vs baselines, a confusion matrix and ROC. | Computed with statsmodels; numbers match a reference run within floating-point tolerance. Removed by cut 4. Auto's classification card still has a confusion matrix and, for two classes, a ROC curve from the out-of-fold predictions. |
| ML-5 (P0) | Assumption checks for chosen methods (non-linearity, influential outliers, collinearity, class imbalance, perfect separation) are shown as warnings with a suggestion, never as blockers. | `boat` on Titanic triggers the perfect-separation warning if forced in. Removed by cut 4: with no method to choose, the method checks aren't built. Auto's model card warns on class imbalance, a small sample, many-valued features and a feature forced in against the checks, so `boat` forced in gets the forced-in warning. |
| ML-6 (P0) | "Compare with Auto" runs Auto on the same setup and shows both. | Shown side by side in the model card. Removed by cut 4; the model card lists the other models Auto tried. |
| ML-7 (P0) | Prediction fills rows where the target is blank; predicted cells are visually distinct with the probability or range on hover; existing rows get out-of-fold scores; every prediction has a per-row explanation; low-confidence and out-of-distribution rows are marked. | Predictions never overwrite real values. Removed by cut 7. |
| ML-8 (P0) | Runs execute as background jobs with plain-language progress and are cached by (version, scope, recipe, method, params). | A repeat run returns within 200 ms. |
| ML-9 (P0) | Results that depend on changed columns are marked "outdated" after a new version, with a re-run button (or automatic re-run per the story-update setting). | Never silently shows results from an older version. |
| ML-10 (P0) | Minimum rows per recipe are enforced (100 for supervised); below that, the run refuses with the count needed. | — |
| ML-11 (P1) | `k-means` with elbow chart, profiles and AI-named clusters; what-if form; predictions for new rows on save; "add predictions as a column"; "find unusual rows"; significance test widget; Simpson's paradox detector; forecast. | — |

### 7.7 Story cards

| ID | Requirement | Acceptance criteria |
|---|---|---|
| STORY-1 (P0) | Each widget has a story card: headline, 2–4 sentences, number chips with evidence links, related-widget chips, Edit, Ask why. An overview card summarizes the top 3–5 findings. | Cards stream in as each passes verification. |
| STORY-2 (P0) | Numbers in cards are chips bound to fact-sheet values; the narrator never types numbers. | A card's numbers equal the fact sheet's values at all times. |
| STORY-3 (P0) | Every story is verified before caching; ungrounded stories are regenerated; if regeneration fails, the card shows the fact sheet as bullet points instead of prose. The same chip-only schema and verification apply to every other LLM-written text shown to the user: card rewrites, suggested revisions, synthesis and direction cards, and widget titles. | Grounding test passes 100%. Card rewrites and direction cards: removed by cuts 2 and 3. A widget title written in chat passes the builder's title check and the wording check, or the templated title is used (TRD §8.1). |
| STORY-4 (P0) | Two-way linking: hovering a widget highlights its card and related widgets; hovering a card highlights its widget; clicking a card scrolls to its widget. | Highlight appears within 100 ms; no layout shift. |
| STORY-5 (P0) | Stories update on: widget added / changed / removed, data saved, cleaning step committed, ML result arrived or invalidated. Only affected cards update. The LLM re-narrates only on a material change; otherwise chips refresh. | After editing one cell in `age`, only cards whose fact sheets depend on `age` update. The material-change check: removed by cut 6; every affected card is narrated again, and the overview with them. No source that isn't `ready` and current feeds another card: the overview, a synthesis, an `ask_story` answer and the notebook read only usable cards and say which they left out (TRD §7.4.2). |
| STORY-6 (P0) | Updated cards show a "changed" badge. With "Story updates: Ask first", they show "outdated, click to refresh" instead. | With "Ask first", the overview and the syntheses citing an outdated card show "outdated" too. A card that isn't current carries an "Out of date" note in the notebook. |
| STORY-7 (P0) | Cards are editable inline. A user-edited card is never overwritten; it gets a "data changed" badge with a suggested revision to accept, edit or dismiss. Hand-typed numbers are marked "unverified". | Editing on the canvas and in the panel edits the same object. Both badges show on the panel's card and on its canvas node. A number chip saved with an edit shows its fact's value; one with no fact behind it is "unverified", and so is a number typed in words ("zero", "twice"). Once the data moves past the version the user's words were written on, the card says so ("Written on v5, data is now v7"), also after the suggestion is dismissed. A card with hand-typed numbers asks for them to be checked ("Has numbers you typed; check them"), since no code keeps them current. |
| STORY-8 (P0) | Wording rules enforced in prompts and checked post-hoc: no causal language for correlational findings; mention small samples (n < 30). The words around a chip may not claim more than its fact (`sherlock/stories/wording.py`, TRD §7.4). | Reviewed in the eval set. The grounding eval counts the claims checked and failed (target: 0 failed). The rules include:<br>• no name said twice; an importance stays next to its column; a level isn't read as a gap;<br>• a synthesis neither works a number out of its cards' chips nor compares two cards' numbers in a way code hasn't checked;<br>• a ranking ("highest", "comes third") names the group or factor the facts rank there, and a trend word ("rising") goes with a trend, change or correlation that does;<br>• a group behind fewer than 10 rows is never named the highest or the lowest (it stays in the chart), and the group of empty values is called "missing", not "None";<br>• the overview never says one measure is highest (or lowest) for two groups from widgets that group it by different columns, unless each bullet names its column;<br>• chat answers name only category values the data has.<br>The chat's model-written text (answer prose, the closest question, clarification options, the reading, widget titles) passes the same wording check. A chat value label shows only a cell of a result's non-number column or a value the DataCard knows; a count or an average is always a chip (TRD §8.1). |
| STORY-9 (P1) | "Changed" badges say what changed. Tavily context on anomaly cards with citations. | — Not built yet. The Tavily part waits on an owner's decision: its query would carry a period taken from the data. |

### 7.8 Flow canvas

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FLOW-1 (P0) | One infinite canvas per dataset with pan, zoom, minimap, "fit view". | Saved automatically within 1 s of any change. |
| FLOW-2 (P0) | Story cards can be dragged from the palette onto the canvas. A card on the canvas is the same object as in the panel (live). The palette marks cards already placed. | Editing the card in either place updates both. |
| FLOW-3 (P0) | Notes (free text) can be added, edited and deleted. | A note can be added from the header, by double-clicking empty canvas, or by dragging a connection into empty space. |
| FLOW-4 (P0) | Edges can be drawn between any two nodes, labeled with free text, and deleted. | Labels render at the edge midpoint. A click on a label selects its edge. An edge can be reversed and its ends dragged to other nodes. |
| FLOW-5 (P0) | Chat on the canvas uses the selected nodes as context (or the whole canvas). "Make sense of this" adds a synthesis card connected to its sources. "Take the story toward X" creates the needed widget(s) and places their cards connected to the selection. "Rewrite this card" proposes an edit to accept or reject. | A synthesis card cites its source cards; numbers in it are chips from those cards' fact sheets. "Rewrite this card" and "Take the story toward X": removed by cuts 2 and 3; "Make sense of this" stays. |
| FLOW-6 (P0) | The canvas is stored as JSON Canvas. | A valid `.canvas` document is produced. |
| FLOW-7 (P1) | Groups, align and distribute, Markdown in notes, chart thumbnails on cards, AI-suggested connections, "Argue against this", "Order this into a story", Markdown and `.canvas` export, auto-layout. | — |
| FLOW-8 (P0) | Every canvas action has a control on screen, not only a key. The selection's actions sit in the status row; every node and a selected edge have a ⋯ menu; right-click opens the same menu. | Removing works with a mouse alone. A card node offers what its story card offers (Edit, Ask why, Open widget, Delete card) plus Remove from canvas. |
| FLOW-9 (P0) | Box selection (Shift-drag), Select all and Escape. | A plain drag still pans. |
| FLOW-10 (P0) | Undo and redo of this tab's canvas changes, by key and by button. | Undoing never takes back what the AI or another tab did since. The removal toast's Undo and Ctrl+Z agree. |
| FLOW-11 (P0) | Duplicate notes; copy and paste nodes; pasting text makes a note. | A card is never placed twice. |
| FLOW-12 (P0) | Nodes snap to the dot grid; a selected note or card can be widened. | The width is saved. |
| FLOW-13 (P0) | A zoom readout that resets to 100%, and keys to fit all, zoom to the selection and zoom in and out. | Zoom and fit animations follow reduced motion. |

### 7.9 Ask anything (chat)

| ID | Requirement | Acceptance criteria |
|---|---|---|
| ASK-1 (P0) | The chat bar is present on all tabs, scoped to the open dataset, with its own thread per dataset. Visibility is a setting (pinned / auto-hide / hidden); `/` summons it. | The thread persists across reloads. With the bar set to Hidden, `/` does nothing; whether it should summon the bar is an open owner's decision. |
| ASK-2 (P0) | Questions are routed to the right source: data (SQL), statistics, drivers, rows, cleaning history, widgets, stories/canvas, models, column meaning, app help. | Eval set covers every category. |
| ASK-3 (P0) | Every number in an answer is traceable: "How do you know?" reveals the SQL, recipe run or step. An answer with an untraceable number is never shown as prose. | Unsourced-number count in the eval = 0. |
| ASK-4 (P0) | Answers take the right shape: number, small table, quick chart, or text. Chart answers have "Pin to dashboard"; narrative answers have "Add to Flow"; row answers link to the CSV tab. | — |
| ASK-5 (P0) | Follow-ups keep context ("and for men?", "plot that"). Selections (cells, rows, widgets, cards) are context. Fuzzy names resolve ("NYC" → "New York, NY"). | Eval includes follow-up pairs. |
| ASK-6 (P0) | Ambiguous questions get one clarifying question with 2–3 button options, never an open-ended one. | Clarifications come from the router and from code: a name that matches nothing in the file but looks like one of its columns or values (when the query can't be written), which column a meaning question is about, which two columns a test compares, and which widget to explain or change. Each has 2–3 buttons, and the choice resumes the question (TRD §8.1). |
| ASK-7 (P0) | Long questions show a short plan (2–5 steps) and stream results. At most 8 answerer and action calls per message. | — |
| ASK-8 (P0) | Honest limits: when the data can't answer, the reply says so and suggests the closest answerable question. | A question about something no column records is answered with the limit, never with another column's number in its place ("the average income" on a file with no income column). A question about the future says there's no forecast, and whether the file has a time column, instead of asking which column (TRD §8.1). |
| ASK-9 (P0) | Suggested questions appear under the input, generated from the data card (3 at a time). | They are answerable (checked against the eval harness for the sample). Removed by cut 9. |
| ASK-10 (P0) | Data changes requested in chat arrive as proposals (approve / reject). Additive actions (new widget, new card) apply immediately and are undoable. | A cell edit asked for on any tab is a proposal, and a new number outside its column's range carries a warning written by code. A request to delete rows is refused in words, since chat never deletes (Rule 3), with the matching rows listed and a link to the CSV tab (TRD §8.1, §4.4). |
| ASK-11 (P1) | Outside-world questions answered via Tavily with citations. | A question about the outside world (what a term means in general, typical values elsewhere, rules, history, recent events) is answered from a web search (TRD §3.6, §8.1):<br>• one to three sentences, each with a numbered citation, labelled "From the web (not from your data)", then "Searched the web for: …" and the sources with their address, retrieval date and their own words quoted;<br>• the sentences have no digits: a number from the web appears only in the quoted page text, and none becomes a chip or is compared with the data;<br>• only the user's words and column names are sent, never a value from the file (`sherlock eval web` checks every outbound request against every cell);<br>• with no Tavily key, or when the search fails, the answer is one line saying so, never an error.<br>Column meanings use the same search (ASK-2). |

### 7.10 Settings

| Setting | Options | Default | Effect |
|---|---|---|---|
| Mode | Light · Dark · Follow system | Follow system | Swaps the base token set |
| Accent | Verdigris · Arcane · Ember · Aether · Brass | Verdigris | Swaps the accent tokens (UI/UX brief §2.1) |
| Chatbot bar | Pinned · Auto-hide · Hidden | Pinned | §7.9 ASK-1 |
| After upload | Ask me · Open the cleaning plan · I'll clean it myself (stored as `ask`, `always`, `never`) | Ask me | Whether the offer appears. "Open the cleaning plan" opens the plan by itself and never cleans unattended (CLEAN-1, CLEAN-8a) |
| Default cleaning mode | Auto · Step by step (P1) | Auto | Used by the offer and "Clean with AI" |
| Story updates | Automatic · Ask first | Automatic | STORY-6, and whether outdated ML runs re-run automatically (ML-9) |
| Spotlight on hover | Off · Subtle · Full | Subtle | Strength of the hover highlight |
| Reduce motion | Follow system · On · Off | Follow system | Disables non-essential animation |
| Default tab | CSV · Dashboard · Flow | Dashboard | Tab shown when a dataset opens for the first time |

Settings are stored per user (browser cookie identity) on the server, so they survive reloads (`GET /me`, `PUT /me/settings`; TRD §4.1).

Cut 1 (plan §2.0) keeps four settings in the dialog: Mode, Accent, Chatbot bar and After upload, labelled there "System" (for Follow system) and "Chat bar". The other five keep the defaults above and change only through `PUT /me/settings`. Story updates, Spotlight on hover, Reduce motion and Default tab act on their values. No code reads Default cleaning mode, since only Auto cleaning is built.

### 7.11 Quality of life (P0)

Toasts with Undo (10 s) after deleting a widget, rows, a card or a dataset · `/` focuses or summons the chat bar and `?` opens the shortcuts sheet (both only when no cell, input or editor has focus) · suggested questions · "remember where I was" (tab, scroll, selection per dataset, per browser) · empty states that say what goes there and offer one action · unsaved CSV edits survive a page reload (local storage, keyed by dataset and version).

The `?` sheet and suggested questions: removed by cut 9. "Remember where I was" keeps each dataset's last tab on the server (so in any browser), and the dashboard's scroll and the Flow view in this browser. Not built yet: remembering the CSV grid's scroll and the selection.

### 7.12 Notebook export

| ID | Requirement | Acceptance criteria |
|---|---|---|
| NB-1 (P0) | "Export notebook" is reachable from every tab: the dataset header menu (⋯), the CSV toolbar's Download menu, the Changes panel's footer, the Flow palette's Export link, and the chat ("export a notebook"). It is available in every dataset status except `profiling` and `failed`. | The action is visible on every enabled tab; during cleaning it exports the latest committed version and says so in the notebook's first cell. |
| NB-2 (P0) | The export is a valid `.ipynb` (nbformat 4.5) named `<dataset>-v<version>.ipynb`, plus a sidecar download of the raw file named `<dataset>-raw.csv` when the user ticks "Include data" (default on). Without the data, the first cell documents where to put the raw file. | `nbformat.validate` passes. The notebook opens in Jupyter, VS Code, Colab and Kaggle without warnings. |
| NB-3 (P0) | The notebook reproduces the current version from the raw file. A load cell decodes the raw file with the recorded encoding and reads it with DuckDB's `read_csv`, exactly as the import does (same transcoding, options, `all_varchar` setting, `_row_id` and `_quarantine_reason` columns). Then one code cell per step in the current version's effective chain, in order (TRD §7.7). | Executing the notebook top to bottom yields a DataFrame equal to the current version (same rows by `_row_id`, same columns, values and dtypes) for every file in the end-to-end set. Cleaning steps use their stored pandas code (the typing step its stored DuckDB statement) against the same helper functions, vendored into one cell. Edit batches are explicit pandas assignments by `_row_id`. Undone steps are left out; an undo appears only as a Markdown note. Quarantine is a `_quarantine_reason` column, never a drop. |
| NB-4 (P0) | Every widget becomes a Markdown cell (title) plus a code cell that runs its exact SQL with DuckDB on the DataFrame and shows the result table, plus a code cell that draws the chart with matplotlib (bar, line, area, pie/ring as bar, scatter, histogram, box, heatmap; KPI and table as a printed value or DataFrame). Global filters are not applied; the widget's own row predicate is. Widgets with an ML op get their run's reproduction cell (NB-5) and its importance or coefficients table instead of SQL and chart cells. | The result table in the notebook equals the widget's data in the app for the same version. Chart cells execute without error. A KPI prints the value its tile shows (its `value` column, else the first), never the row count beside it (`sherlock eval notebook` checks each KPI line). |
| NB-5 (P0) | Every ML run becomes a code cell that reproduces it: scope query, the exact feature list and exclusions (as comments with reasons), the same split and seed, the same preprocessing, the chosen method via scikit-learn/statsmodels, baselines, metrics, and the importance or coefficients table. Auto runs reproduce the winning model only, with a comment naming the alternatives tried. | Re-executed metrics match the model card within 0.5 percentage points (same seed, same library versions pinned in the requirements cell). |
| NB-6 (P0) | Every story card becomes a Markdown cell placed after its widget (or after its sources for synthesis cards): the headline as a heading, the body with number chips rendered as plain numbers, a line listing related widgets, and the "evidence" SQL in a collapsed details block. The overview card is the notebook's introduction. Notes from the Flow canvas are included when "Include canvas notes" is ticked. | No number in a Markdown cell differs from the fact sheet it came from. |
| NB-7 (P0) | Outputs for table and text cells are embedded at export time (computed server-side from the data the app already has), so the notebook reads correctly on GitHub and Kaggle without execution. Chart cells have no embedded output in P0 (P1 embeds PNGs). | Opening the file in a viewer shows every table. |
| NB-8 (P0) | The first cells are: a title and provenance cell (dataset name, version, export time, Sherlock version, a link to the models used), a parameters cell (`DATA_PATH`, `RANDOM_SEED`), a requirements cell (`pip install` line with pinned versions of pandas, duckdb, numpy, scikit-learn, matplotlib, rapidfuzz, dateparser, ftfy; `NOTEBOOK_PINS`, TRD §10) and the vendored helpers cell. | Running the requirements cell in a fresh environment is enough to execute the rest. |
| NB-9 (P0) | Export runs as a job with progress; for the sample it completes in ≤ 5 s, for a 50 MB file in ≤ 60 s. The result is cached per (version, dataset state revision, options) and invalidated by a new version or by any widget, card, run, layout or canvas change. | A repeat export of the same version downloads immediately. An export never mixes cards from two versions silently: it waits up to 20 s for an update in progress, or says in its first cell that cards were being updated. A widget that fails on the version becomes a cell saying why, and the export still succeeds. Deleting a card, or a cascade starting or ending, makes the next export a new one. |
| NB-10 (P0) | The export dialog has options: Include data (raw CSV) · Include story cards · Include canvas notes · Include ML runs · Order: by step then dashboard order (default) or by Flow reading path (P1). | Options are remembered per user. |
| NB-11 (P0) | The notebook never contains secrets, user identifiers, or the model's prompts. Generated analysis code contains no network calls; the only network use is the requirements cell's pinned `pip install` line. | Static check in the exporter's tests. |
| NB-12 (P1) | Chart PNGs embedded; Flow reading-path order; "Open in Colab"; Kaggle variant; PDF and Markdown renderings via nbconvert for the one-page report. | — |

---

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| **Performance** | Titanic-sized file: profile ≤ 3 s; widget query ≤ 300 ms; dashboard first paint ≤ 2 s after build; cascade after a save ≤ 5 s to all widgets re-rendered. 50 MB file: profile ≤ 60 s; grid scroll stays at 60 fps with paging; headless clean ≤ 5 min (budget). |
| **Reliability** | Jobs are checkpointed per step and resumable after a server restart. The UI never shows a raw exception. After a restart every running job is re-queued: story jobs resume from their checkpoint, and the other kinds start over, which is safe because they are idempotent (TRD §3.3). |
| **Security** | Generated code runs in a sandbox with no network, CPU/memory/time limits, per-dataset isolation, only the dataframe in scope. Cell values enter prompts only as delimited data blocks. Per-user caps: 50 MB per file, 500 MB per user, 7-day expiry, rate limits, token budget (TRD §10, §15). |
| **Security (owner's decision)** | A visitor is a cookie, so the per-user caps reset if the cookie is dropped. Two caps don't. All users' model calls together are capped per UTC day (`APP_TOKEN_BUDGET`, default 10M tokens); past it, model features answer "Sherlock has used today's model budget for everyone" and everything else keeps working. New users are capped at 300 an hour per client IP (`NEW_USERS_PER_IP_HOUR`), high enough for judges sharing a network. Chat roles must be NVIDIA's own Nemotron models (`nvidia/` publisher). |
| **Privacy** | Data is stored only on Sherlock's own backend (the Render service's persistent disk; on the Nebius alternative, its mounted volume). Cell values leave it only inside prompts to Nebius Token Factory; Tavily receives only the user's words, column names and a URL the user typed (ASK-11, LOAD-7). No third-party analytics. Retention claims are made only after checking the terms of the host and of Token Factory. |
| **Accessibility** | Keyboard operable throughout; visible focus; text contrast ≥ 4.5:1; color never the only signal; `prefers-reduced-motion` respected. |
| **Browser support** | Latest Chrome, Edge, Firefox, Safari on desktop. |
| **Observability** | Every LLM call logged with model, tokens, latency, purpose and outcome (`llm_calls`); every job with timings; errors with request IDs (every error body and response carries one). |

---

## 9. Constraints and assumptions

- **Inference.** NVIDIA models on Nebius Token Factory for every role, following the track's guidance (Ultra for demanding reasoning, Super or Nano for fast everyday calls). Model IDs are set in `render.yaml` and `.env.example` (TRD §3.5):

  | Role | Model | Used for |
  |---|---|---|
  | `large` | Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`) | Cleaning diagnosis and proposals |
  | `medium` | Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`) | Cleaning critic, dashboard curation, chat (SQL, plans, edits, answers, web queries, column meanings, data-dictionary notes), narration, overview, synthesis |
  | `small` | Nemotron 3 Nano (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`) | Routing and the chat thread's summary |
  | `embed` | An NVIDIA embedding model from the catalog, or empty | Empty: the catalog has none, so value resolution uses exact and fuzzy matching only |

  Narration and answer composition run on Super because Nano wasn't reliable enough for them (TRD §7.4, §8.1). The rules need at least one NVIDIA open-source model; Sherlock uses no other provider, and the app refuses to start if a chat role isn't Nemotron or the embed role isn't an allowlisted NVIDIA model (`NVIDIA_EMBED_MODELS`). `FEEDBACK.md` records the model IDs and the tool-calling and JSON-schema checks; context lengths aren't recorded, since the catalog's `/v1/models` returns only IDs. The architecture does not depend on any single capability.
- **Hosting.** The app runs on **Render** as one Docker web service built from `api/Dockerfile` (Standard plan, Frankfurt), with a persistent disk mounted at `/data` (`render.yaml`, TRD §11). A service with a disk is single-instance, which matches the one-process design (TRD §3.1). Jobs run in-process. Nebius hosting isn't used because the account's AI Cloud tenant is suspended and the rules don't require it. Moving to the Nebius route below is one deploy plus a URL change.
- **Hosting, Nebius alternative.** Backend on a Nebius Serverless Endpoint (`scripts/deploy.sh`); its `check` command verifies that `/data` survives a restart. If it fails, the same image runs on one Nebius AI Cloud VM with a disk. Heavy jobs on Serverless Jobs with a local worker-pool fallback; not built yet. The rules require running on Token Factory or AI Cloud, which inference on Token Factory satisfies. The submission names only the Nebius services the deployed app uses (Serverless Jobs only if `JOB_BACKEND=nebius` runs in production).
- **Availability.** The public URL (on its paid Render plan), the Token Factory key and enough Token Factory credit to serve judges stay live through the judging period (Dec 1–15, 2026) and the winner announcement (around Jan 11, 2027), not only until the deadline.
- **Charts.** Bklit UI (MIT). Its Studio is proprietary and excluded.
- **Sample data.** titanic3 (1,309 rows), bundled as `api/samples/titanic3.csv` (§11).
- **Team.** Solo; the cut order is applied (Implementation Plan §2.0).

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

All six are decided. The owner's decisions still open are noted at their requirements (ASK-1, STORY-9).

| Question | Blocks | Default if unresolved |
|---|---|---|
| Must the app be hosted on Nebius? | Hosting plan | Decided: no. The rules require running on Token Factory or AI Cloud, which Token Factory inference meets. Hosted on Render, with Nebius as the documented alternative (§9). |
| Which Nemotron models does Token Factory serve, with which features? | Model assignments (TRD §3.5) | Decided: Nemotron 3 Ultra, Super and Nano, IDs in `render.yaml`; tool calling and JSON-schema output checked (`FEEDBACK.md`). No NVIDIA embedding model, so `embed` is empty (§9). |
| Does Glide Data Grid cover range select, range paste and fill handle? | CSV tab library | Decided: Glide kept. Its check passed on editing, range selection, theming and 500,000 paged rows (`FEEDBACK.md`); range paste and the fill handle weren't needed after cut 5. |
| Does Bklit expose custom tooltips and shared hover state? | Hover linking | Decided: Bklit kept. Custom tooltips and theme tokens passed (`FEEDBACK.md`); hover linking (STORY-4) is done in the widget shell, not in the charts. |
| Sample file license | Bundling | Decided: OpenML 40945 lists the Titanic data's licence as "Public" (Harrell and Cason, Vanderbilt Biostatistics), so `api/samples/titanic3.csv` is bundled. |
| Solo or two people? | Timeline | Decided: solo; all nine cuts applied (Implementation Plan §2.0). |

---

## 12. Submission requirements and judging

Sources: [official_page.md](official_page.md) (a summary of the Devpost rules; the live rules at https://nebiusglobalaihackathon.devpost.com/rules control) and [judges_rubric.md](judges_rubric.md) (the judges' panel). This section maps each requirement to what satisfies it.

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
| Working demo URL | Public, no login, "Try with sample" works from a fresh browser; live through judging (§9) | P0-11: https://sherlock-anw3.onrender.com |
| Demo video | Public YouTube, under 3:00 (the live rules say "less than three (3) minutes"), shows the working product and how the NVIDIA models and Nebius are used | Implementation Plan §9 |
| Public repository | GitHub, GitLab or Bitbucket, readable without a login | `github.com/n1mk1/sherlock`. Not public yet |
| Open-source license | MIT, Apache 2.0, MPL 2.0 or comparable, visible at the top of the repo page | MIT, `LICENSE` at the repo root |
| README | Setup and run commands, the NVIDIA models and what each does, Nebius Token Factory and the other Nebius services used | `README.md` (Implementation Plan §7) |
| Technology feedback | Feedback on Token Factory, the Nemotron models, and Nebius AI Cloud as far as it was tried (the suspended tenant and the separate billing) | `FEEDBACK.md` (Implementation Plan §7) |
| Pre-existing project disclosure | Not applicable: the project was started inside the submission period (from 2026-08-26) | — |
| Builders & Brews city | Only if an IRL event was attended (Toronto is a listed city) | — |

### 12.3 Judging criteria (stage two, 25% each)

| Criterion | What judges look for | What demonstrates it in Sherlock |
|---|---|---|
| Technological Implementation | Platform features used for a real reason; justified model choices; working core; trade-offs understood | Model roles chosen by task weight (Ultra for planning fixes, Super for SQL, narration and answers, Nano for high-volume routing; §9), with measured latency and cost per role (§4); grounding and verification that the model can't bypass; sandboxed execution; benchmark and eval tables; the architecture diagram, rendered by `scripts/architecture.py` |
| Design | A complete product, not a proof of concept; value within 30 s; the "aha" within 2 minutes; clear first action; visible progress and errors | "Try with sample" gives a dashboard and stories in seconds; the overview card puts conclusions before evidence; live cleaning log, job tray and cascade progress; empty states with one action; accessibility (UI/UX brief §8) |
| Potential Impact | A specific audience and pain; evidence the product improves on today's workflow | §3.1; cold-start user test and baseline comparison (§4); "rows deleted: 0" and the cleaning benchmark |
| Quality of the Idea | Non-obvious, differentiated, understands the hard parts | §3.2; the trust design (chip-only narration, verifiers, quarantine instead of delete, honest ML against baselines); notebook export as an exit, not a lock-in |

Ties are broken by the first criterion in the table, then the next; a tie across all four goes to a panel vote.

### 12.4 Prizes Sherlock can enter

A project can win one overall award or one track award, plus one bonus award.

- One overall award or the Best Apps and Agents track award.
- Best Use of Tavily (bonus), which needs a runtime Tavily API call in the deployed app. Tavily answers outside-world questions (ASK-11), column meanings (ASK-2) and a linked data dictionary (LOAD-7), retrieval only. The calls run once `TAVILY_API_KEY` is set in Render's environment; it isn't set yet, and the bonus isn't claimed until it is. STORY-9's anomaly context is not built.
- Most Valuable Feedback (bonus), judged on completeness, viability and potential impact: `FEEDBACK.md` is written to those three criteria (Implementation Plan §7).
- A City Winner award only if an IRL Builders & Brews event was attended.

### 12.5 Panel guidance applied

- **Conclusion before evidence.** Overview card first, verdict line first in model cards. Recommended next questions under the chat (ASK-9): removed by cut 9.
- **Quantify against a baseline.** ML against majority and one-column rules; the user test against doing it by hand.
- **Document limitations.** The README has a "Known limitations" section: failed eval questions, cleaning cases the benchmark misses, file types that fail, anonymous identity with no recovery, and the 7-day expiry.
- **Every integration has a job.** No service or model is named in the submission unless the deployed app uses it.
