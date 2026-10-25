# Day 7 review: ML (driver analysis with Auto, answerers, ML UI, reproduction)

Reviewed 2026-10-25 on branch `claude/review-day7-2c8959`, cut from `main` at 8c96ca3. The scope is Implementation Plan §2 "Day 7", as the §2.0 replan narrows it: cut 4 (Auto only), cut 7 (`driver_analysis` only, no `predict`), and cut 8 (ML scope comes from a filter, not a brush). "Done" means plan §1: it runs on the Titanic sample, its test passes, the UI reaches it, and it's committed.

**Verdict.** Day 7 meets its exit check in a real browser. On Titanic filtered to 3rd class, "What drives this?" gave importance bars and a model card with both baselines. The exported notebook ran in a fresh venv and reproduced every run's metric exactly, on Titanic and on a non-Titanic regression (`sales_dated.csv`, target `revenue`). The planted-truth eval passes 3 of 3.

The method is mostly sound:
- preprocessing is fitted inside each fold;
- target encoding is cross-fitted;
- the baselines use the same folds;
- importance is computed on held-out folds;
- every number comes from code.

But the honesty of the verdict has real gaps, and four findings are high severity:

1. **F1. Group leakage.** Titanic's `ticket` is target-encoded across random folds, so families sit on both sides of a split. On 3rd class it inflates accuracy by 4 points and AUC by 0.08. It also makes `ticket` both the "best one-column rule" and the second "driver". TRD §7.5 step 4's `GroupKFold` isn't built, and no cut covers it.
2. **F2. Pure noise passes as signal.** On pure-noise two-class targets with 150 rows, 3 of 30 runs said "Beats the best simple rule" and 5 more said "weak". The fixed 2-point threshold is smaller than cross-validation noise at that size.
3. **F3. Imbalanced targets.** With 3% positives and a real driver (AUC 0.95), the verdict was "weak": accuracy can't move when 97% share one outcome.
4. **F4. Wrong story-card claims about runs.** The narrator misattributed importance numbers live. The cards read "influenced by 1.00" with no driver named, "0.373 lower than unit_price" when 0.373 is units' own importance, and "Sex sex is the strongest driver".

This review fixed seven bugs, each in its own commit with a test and the matching TRD line:
- short target names knocked out innocent columns (`y` left out `day` and `salary`; `age` left out its driver `page_views`);
- a rare class crashed the run;
- the verdict called one strong driver "weak";
- that verdict could credit a target-encoded ID;
- a malformed `scope` gave a 500;
- the 50k sample wasn't stratified although the model card said it was;
- `ask_stats` gave the rank-biserial r the wrong sign.

## Evidence

| Check | Result |
|---|---|
| `uv run pytest` (api, at 8c96ca3 before the fixes, machine shared with the Day 5 and Day 6 reviews) | 341 passed, 3 skipped, 3 failed in 18 min. All three failures are the same `TypeError: string indices must be integers` in a `wait_for` that polls `GET /jobs` (`test_notebook.py:164`, `test_stories.py:152,200`): the response was an error object, not a list, under heavy load. Re-run alone, all three pass (126 s), including the Day 7 notebook execution test (F16). |
| `uv run pytest` (api, on this branch after the fixes) | **349 passed, 3 skipped, 0 failed** in 10.5 min (6 new tests, 3 extended). The three load failures above didn't recur. |
| `corepack pnpm test` (web) | 8 files, 53 tests passed. `tsc -b` is clean, also after the `ModelCardDrawer.tsx` change. |
| `uv run sherlock eval ml` | **3 of 3 planted cases pass.** drivers: logistic regression, accuracy 0.904, beats_baseline, strong then moderate, `code` and `leak` left out. noise: accuracy 0.502, no_signal. regression: ridge, R² 0.948, beats_baseline. |
| My planted datasets, through the real profiler and `analyze` | See the table under D7.1. |
| Browser exit check, Titanic (live, once) | **Passed.** API on 127.0.0.1:8107 with its own data folder, Vite on 127.0.0.1:5187, opened at `http://review7.localhost:5187`. Screenshots `01`–`10`, `12`, `13` in `reviews/day-7/`. |
| Exported notebook, fresh venv | **Reproduces exactly.** A new `uv venv` (Python 3.12) with only `nbclient`, `ipykernel` and `pip`; the notebook's own `%pip install` cell installed the pins. Titanic: 3rd class `accuracy: 0.804 (95% interval 0.782 to 0.826) on 709 rows` and the builder's run `0.804 … on 1,309 rows`, exported and executed identical. Sales: `r2: 1.000 … on 5,000 rows` and `accuracy: 0.927 … on 5,000 rows`, identical. |
| Second sample, not Titanic (Rule 4) | `sales_dated.csv` with "Use as is". The builder's "What drives returned?" said no signal: AUC 0.504, with the 93% imbalance warning (an honest answer for a random outcome). "What drives this?" on "Total Revenue by Product" ran a **regression**: "A number: scored by R²". Random forest scored R² 0.9995 against 0.59 for the best one-column rule (`unit_price`), "Beats the best simple rule by 0.41 in R²". The factors were `unit_price` 1.00, `units` 0.37, `product` 0.04 (`11-sales-revenue-regression.jpg`). |
| Token Factory spend | See the end. |

### Exit check, step by step

| Step | Result | Screenshot |
|---|---|---|
| Try with sample → Use as is | The builder made 9 SQL widgets, "What drives survived?" and story cards. The driver widget showed progress, then "Beats the best simple rule by 2.4 points. Gradient boosting: Accuracy 80.4% vs 78.0%", with sex 1.00, age 0.22, ticket 0.20, pclass 0.17. This matches the plan's as-built note. | `01-driver-all-rows.jpg` |
| Filter to 3rd class | No class bar was on the dashboard, so I added "Rows by pclass" from the Add widget drawer's quick template (no model call). Clicking bar 3 set `pclass = 3`. **The click only filters after the mouse has moved over the bar:** a click with no prior hover only focuses the widget (F20). | `02-filter-pclass-3.jpg` |
| Analysis dropdown | Explain: What drives this?. Predict a column: "Not in this release". Find groups and Find unusual rows: "Coming later". Forecast: "needs a date column". Plain chart (SQL) is checked. | `03-analysis-dropdown.png` |
| Setup | Target `survived` (from the chart's `y`). Chips: `name` struck through ("ID-like: unique per row"); `boat` and `body` struck through ("records the outcome (leakage): near-perfect predictor of survived (0.98)" and "(1.00)"). Rows "All rows · pclass = 3 · 709 with survived" with "Only the filtered rows" on. Method: Auto with what it tries. Baselines: majority 74.5%, **best one-column rule `ticket` 79.5%** (F1). "about 9 s". | `04-setup-features.jpg`, `05-setup-baselines.jpg` |
| Run | The widget became "What drives survived?" with "testing models…" and the steps ticked off. | `06-run-progress.jpg` |
| Result | Logistic regression 80.4% against 79.5%. Factors: sex 1.00, **ticket 0.97**, sibsp 0.14. The live server had my third commit but not the guard commit, so the verdict read "ticket alone does nearly as well (79.5%): it carries the signal…". That wording is what led to commit 0fdde18 (F1). | `07-third-class-result.jpg` |
| Model card | Verdict; data ("rows where "pclass" = 3: 709 rows used of 709"); excluded columns with reasons; "Auto picked Logistic regression by 5-fold stratified cross-validation (seed 42). Also tried: Gradient boosting (79.1%), Random forest (78.7%)". Baselines against the model with "95% interval 78.2% to 82.6%" (F6), AUC 0.799, importance, confusion (477/51/88/93), ROC (AUC 0.795), "Who did it get wrong? (139 rows)". Warnings: class imbalance 74%; "ticket, home.dest have many values and were target-encoded inside the folds". Limits. | `08-model-card.jpg` |
| Who did it get wrong? | It opened the CSV tab on `?rows=` with "139 rows selected" and a toast. | `09-wrong-rows-csv.jpg` |
| Export notebook | The dialog counts "1 step, 6 widgets, 2 model runs, 9 story cards". "Notebook ready". Executed as above. | `10-export-dialog.jpg` |
| Outdated / Re-run | With "Story updates: Ask first", an `age` edit (v2 → v3) marked both analyses outdated: "v2 · Outdated · Re-run". Re-run produced a v3 run with identical numbers (0.803926; the edited row isn't in 3rd class). | `12-outdated-rerun.jpg`, `13-rerun-v3.jpg` |
| Chat answerers (live) | See D7.3. | — |

**What went wrong during the check.** My first attempt, between about 15:12 and 15:16, reached the **Day 6 review's API**. The Day 6 Vite briefly held 127.0.0.1:5187 (its note `day-6-ports.md`). That run's dataset, "Rows by pclass" widget and driver run are on the Day 6 API, so its model calls (dashboard curation and story narration) were billed there and aren't counted below. Everything in the table above was redone on my own API, as its database shows. I left `day-7-ports.md` in the shared notes folder.

## Status by item

| Item | Status | Evidence |
|---|---|---|
| **D7.1** `ml/` common path: scope → DataFrame, framing, leakage, split, preprocessing, baselines, explain, (predictions, OOD, calibration), planted-truth tests | **partial** (fixed here; F1, F2, F3, F5 open) | `ml/plan.py`, `ml/core.py`, `ml/analysis.py`. **Sound:** each fold fits its own `Pipeline` (`core.py:108-110`, imputer, scaler, one-hot and `TargetEncoder`, whose `fit_transform` cross-fits); the baselines use the model's folds (`core.py:140`); permutation importance is on each held-out fold (`core.py:157`); the model card's numbers come from executing `repro.py` (`analysis.py:72`). **Not built:** `GroupKFold` and `TimeSeriesSplit` (TRD §7.5 step 4, no cut covers them; F1); predictions, OOD and calibration (a recorded decision, TRD §7.5, tied to cut 7); SHAP (a recorded decision). **Fixed:** short-target-name exclusions (a4032bf), the rare-class crash (8d553f9), the unstratified sample (c8b1331). |
| **D7.2** `driver_analysis` with Auto, registry and manifests, `GET /recipes`, runs API, cache, `run.updated`, builder's driver widget | **done** (fixed here; F11, F17) | `ml/registry.py`, `ml/runner.py`, `routers/runs.py`, `dashboard/builder.py:101-114`. Seen live: recipes with reasons, preview, runs, results, model card, code, wrong-rows, rerun, cascade outdating. `tests/test_ml.py` covers the API end to end, including the cache (< 0.5 s; PRD ML-8 says 200 ms). **Fixed:** `GET /recipes?scope=<bad JSON>` answered 500 (c30349a). No API test asserts `run.updated` (F17). |
| **D7.3** `ask_why`, `ask_stats`, `ask_model`, `ask_meaning`, `app_help` with `docs/help/*.md`, tool exposure by tab | **done** (fixed here; F12, F13, F14) | `agent/insight.py`, `agent/loop.py::TOOLS`, `docs/help/*.md` (6 files), `tests/test_answerers.py`. Live, once each, on Titanic (details below). **Fixed:** the `ask_why` sentence for one strong column (0179fbb, 0fdde18); the rank-biserial sign (c2020d6). |
| **D7.4** Frontend: dropdown with reasons, setup from the manifest, progress, importance with the partial-dependence chart, confusion and ROC, model card drawer, "who did it get wrong?", outdated / re-run | **done** (F6, F18, F19, F20) | `web/src/components/ml/*.tsx`, `WidgetShell.tsx`. All seen live (screenshots above). The method control, coefficients, residuals and Compare with Auto are cut 4; predictions, predicted cells and explain-row are cut 7. **Fixed:** the drawer now says the sample is "stratified by <target>" (c8b1331). |
| **D7.5** `repro.py` for Auto, `GET /runs/{rid}/code`, run cells in the export with embedded metrics and importance, execution test within 0.5 pp | **done** (F15) | `ml/repro.py` copies `core.py`'s functions with `ast` and renders `reproduce(df, seed=42)`. The runner gets the card's numbers by executing that text, so the app and the notebook can't drift. The run cells are rendered in `notebook/cells.py:274-308` and `exporter.py:160-222` (both locked). `test_notebook.py:207-210` asserts ≤ 0.005. Live in a fresh venv: exact on four runs, two datasets, classification and regression. There is no `notebook/repro_render.py`; TRD §2's layout still lists it (F15). |

### D7.1 in detail: my planted datasets

The script is in the session scratchpad, not the repo. Each case is built as a version frame, profiled with the real `build_datacard`, then run through `analyze` on all rows. n = 600 unless stated.

| Case | Model, score | Baselines (majority / best rule) | Verdict as built at 8c96ca3 | Right? |
|---|---|---|---|---|
| A known driver: `churned` ~ 1.8·x2 + noise, string target | logistic 83.0%, AUC 0.91 | 53.2% / x2 82.8% | **weak**: "Only 0.2 points better than the best simple rule: treat these drivers as weak." | **No.** x2 is a strong driver. Fixed (0179fbb): "x2 alone does nearly as well (82.8%): it carries the signal, and the other columns add only 0.2 points" |
| A numeric leak (`refund_amount` > 0 iff churned) with a string target | gradient boosting 100% | 51.8% / refund_amount 100% | no_signal: "No better than refund_amount alone (100.0%)…" | Partly. It wasn't excluded: the \|corr\| check needs a numeric or boolean target (`plan.py:86`). The verdict names it, but importance shows it as the top "driver" (F5). |
| A categorical leak (`status_code` with values per outcome) | — | — | excluded: "each of its values goes with one churned value (leakage)" | Yes |
| A repeating ID (`user_ref`, 400 values over 600 rows), a constant text column and a constant number | logistic 71.8% | 50.8% / x1 72.5% | no_signal naming x1; the ID target-encoded with importance 0 and a high-cardinality warning | Yes. The constants are kept as features with importance 0, not left out with a reason (F10). |
| Imbalanced: 3% positives, n = 2,000, real driver x1 | random forest 98.2%, **AUC 0.95** | 97.0% / x1 98.1% | **weak** ("0.0 points better") | **No** (F3) |
| Imbalanced: 1% positives, n = 300 (3 positives) | — | — | **crash**: `ValueError: Only one class present in y_true` | **No.** Fixed (8d553f9): `422` "Each value of fraud needs at least 5 rows, one per fold…; '1' has 3." |
| Target named `y` (bank-marketing style) with `day`, `salary`, `pdays` | — | — | `day`, `salary` and `pdays` excluded as "derived from y (its name contains it)" | **No** (Rule 4). Fixed (a4032bf). |
| Target `age`, driven by `page_views` | ridge R² −0.04 | — | `page_views` excluded as "derived from age"; **no_signal** | **No.** Fixed (a4032bf). |
| Regression with a 0.99-correlated copy and a `price_x2` | ridge R² 0.93 | −0.002 / x3 0.59 | `price_x2` excluded by name, `cost_total` by \|corr\| > 0.98; beats_baseline with x3 | Yes |
| Regression on pure noise | ridge R² −0.04 | — | no_signal | Yes |
| Four classes with a rare class (12 of 600) | logistic macro-F1 0.60 | 0.13 / x1 0.36 | beats_baseline, x1 first | Yes (the interval is wide: 0.50–0.70) |
| **False-positive rate:** 30 pure-noise two-class datasets, n = 150, 6 noise columns | — | — | **beats_baseline 3, weak 5, no_signal 22**; lifts up to +5.3 points | **No** (F2) |
| False-positive rate: 30 pure-noise regressions, n = 150 | — | — | no_signal 30 | Yes |

**F1 quantified.** This is Titanic 3rd class (709 rows) with `core.evaluate`, comparing the shipped random stratified folds against `StratifiedGroupKFold` by ticket:

| Features | Folds | Logistic acc / AUC | Best one-column rule | Top factors |
|---|---|---|---|---|
| with `ticket` | stratified (as shipped) | 0.803 / 0.794 | ticket 0.795 | sex 1.00, ticket 0.98, sibsp 0.13 |
| with `ticket` | grouped by ticket | 0.762 / 0.710 | sibsp 0.744 | sex 1.00, sibsp 0.18, age 0.12 |
| without `ticket` | stratified | 0.777 / 0.740 | fare 0.745 | sex 1.00, sibsp 0.37, age 0.17 |
| without `ticket` | grouped by ticket | 0.773 / 0.713 | sibsp 0.744 | sex 1.00, sibsp 0.35, age 0.20 |

### D7.3 in detail: live answers on Titanic (one message each)

| Message | Routed to | Result |
|---|---|---|
| "what drives survival?" | `ask_why` | From the cached builder run (no new `ml_run`): "A model can predict survived better than simple rules: its accuracy on rows it never saw is 80.4% against 78.0%… sex (1.00), age (0.22) and ticket (0.20). These are associations, not causes." Chips, the importance table, Model card. |
| "is age different between survivors and non-survivors?" | `ask_stats` (one `stats` call to pick the columns) | Welch's t: p 0.077, Cohen's d 0.11 (negligible) on 1,046 rows, "could well be chance"; Mann-Whitney agrees (p 0.178); a per-group table. **SciPy agrees exactly** (t 1.771, U 138,624). The table had d = 0.112 beside rank-biserial r = −0.049 for the same direction; fixed in c2020d6. |
| "who did the model get wrong?" | `ask_model` | "The model got 139 of 709 rows wrong…", with 20 rows and Open rows. It used the 3rd-class run: the stats answer in between had replaced the `ask_why` focus (F14). |
| "what does parch mean?" | `ask_meaning` | The code-written part is right: "1,309 of 1,309 rows… 8 different values from 0 to 9", with a values table. **No "In general (not from your data)" block:** the `meaning` call returned an empty text, was repaired, and the answer silently left the block out (F13). |
| "how do I re-run an outdated analysis?" | **`ask_model`** (should be `app_help`) | "The results do not contain information on how to re-run an analysis." `docs/help/analysis.md:18-19` has an "Outdated analyses" section that answers it (F12). |

Tool exposure by tab is covered by `test_answerers.py::test_app_help_and_tool_exposure_by_tab`. `TOOLS` in `loop.py` matches TRD §8.2 as built.

## Findings, ranked

"Locked" marks a file with the owner's uncommitted Day 8 work, so this review reports the finding but doesn't fix it.

### High

- **F1. Group leakage: a repeated group ID is target-encoded across random folds.**
  - Where: `ml/core.py:88-91` (folds), `:69` (`TargetEncoder`), `plan.py:121-123` (more than 50 values → target-encoded).
  - What happens: TRD §7.5 step 4 says `GroupKFold` "if an id-like group column repeats". It isn't built, the plan says so, and **no cut covers it**. On Titanic, `ticket` (shared by families, 929 values) is target-encoded. Family members fall on both sides of a fold, so a held-out row's ticket encoding carries its relatives' outcomes.
  - The cost, on 3rd class (table above): about 4 accuracy points, 0.08 AUC, and a false driver (ticket importance 0.97). It also corrupts the baseline: the "best one-column rule" is `ticket` at 79.5%, so the verdict compares against a leaky rule.
  - On all of Titanic, ticket is driver no. 3 (0.20), as the plan's own as-built note records.
  - The model card's `high_cardinality` warning ("importance can be inflated; check them by hand") is the only guard.
  - Fix (needs a decision):
    - group the folds (`StratifiedGroupKFold`) on a repeating ID-like column such as `ticket`;
    - and/or keep target-encoded columns out of the one-column baselines.
  - Commit 0fdde18 only stops the verdict from naming such a column.
- **F2. The verdict ignores cross-validation noise, so pure noise "beats" the baseline 10% of the time at n = 150.**
  - Where: `ml/analysis.py:22` (`LIFT` 2 points), `:115-136`.
  - What happens: the model card has an interval, but the verdict only checks `lift >= 0.02`. With 150 rows, one row in a 30-row fold is 3.3 points.
  - 30 pure-noise datasets gave beats_baseline 3 times (lifts +2.7, +2.0, +5.3 points) and weak 5 times.
  - These verdicts become fact sheets and story cards ("Beats the best simple rule by 5.3 points").
  - Fix:
    - say `beats_baseline` only when the fold-wise lift over the best baseline is clearly positive; `core.baselines` would need to return per-fold scores (the model's are already in `folds`);
    - or scale the threshold with n.
- **F3. Imbalanced two-class targets are judged by accuracy only.**
  - Where: `ml/analysis.py:115-136`, `plan.py:79` (metric).
  - What happens: with 3% positives, a model with AUC 0.95 can only gain 3 accuracy points over "everyone gets the most common outcome". The verdict said "weak, 0.0 points better".
  - The `class_imbalance` warning says "Compare against the baseline, not against 50%", which is the comparison that fails here.
  - The sales file's `returned` (93% "no") is honest only because its AUC is 0.50.
  - Fix: for imbalanced two-class targets, use AUC or balanced accuracy for the verdict (and the one-column rule), or require both to agree. This needs a PRD/TRD decision.
- **F4. Story cards about runs misstate what the numbers mean.**
  - Where: `stories/narrate.py` (not locked) with the run fact sheet from `runner.facts_for` (`runner.py:384-407`).
  - What happens, seen live:
    - Sales: "Revenue is most strongly influenced by `1.00`." The driver isn't named.
    - Sales: "importance is `0.373` lower than that of unit_price." 0.373 is units' own importance; the gap is 0.627.
    - Titanic (first attempt, on the Day 6 API, same code): "Sex sex is the strongest driver… Age age comes next… Ticket ticket follows" (a label run followed by the same word as text).
  - Every number is a chip bound to a fact, so Rule 2's letter holds, but the claim around it is false and the verifier doesn't catch it.
  - Fix:
    - give `driver_N_importance` facts a label that names the column;
    - add a narrate check that a `driver_N_importance` chip sits next to its `driver_N` label;
    - reject a label run followed by the same word.

### Medium

- **F5. A numeric leak is never checked when the target is text.** `plan.py:86,105-108`: the \|correlation\| > 0.98 check runs only when the target is numeric or boolean. The purity check (`_pure`) runs only on non-numeric features. So a number that settles a yes/no text target (`refund_amount` > 0 exactly when `churned = yes`) is used. It shows as the top driver; the verdict's "No better than refund_amount alone" is the only hint. Fix: for categories, apply a purity-style test to numbers too, such as a depth-1 tree's held-out accuracy ≥ 98% while the majority is < 95%.
- **F6. "95% interval" overstates what the interval is.**
  - Where: `core.py:178` (mean ± 1.96·sd/√folds), `ModelCardDrawer.tsx:96`, `notebook/cells.py:294,307` (locked).
  - Fold scores aren't independent (their training sets overlap), so this understates the uncertainty. With 5 folds, a t-quantile is 2.78, not 1.96.
  - Auto also reports the CV mean of the best of three models, so the winner's score is optimistic, and nothing in `limits` says so.
  - TRD §6.6 documents the formula, so the code matches the doc. The label "95% interval" and the verdict's use are the problem.
  - Fix: call it "fold spread (approximate)", or use a t-quantile with a note. Add "the model was picked on these folds; its score is slightly optimistic" to `limits`.
- **F7. A target computed from the features isn't flagged.** On `sales_dated.csv`, `revenue = units × unit_price`. The run reports R² 0.9995 and "Beats the best simple rule by 0.41 in R²" as if units and price "drive" revenue. That's true, but it's an identity, not a finding. Fix: a model-card warning when held-out R² > 0.99 or accuracy > 99%: "near-perfect: check whether the target is computed from these columns".
- **F8. The progress labels misreport the work.** `analysis.py:57-58` emits "setting baselines" and "testing models" back to back. The baselines are computed inside `repro.execute` during "explaining", and that step also re-trains the winner, so "explaining" takes about half the run. Fix: emit the labels where the work happens.
- **F9. Partial dependence for 3+ classes is labelled wrongly.** `analysis.py:108`: for multiclass, the value is the share of rows predicted as the most common class, but `of` says "predicted <target>". Fix: say "share predicted as <class>".

### Low

- **F10. Constant columns stay in as features.** A constant (or, under a filter, `pclass` on 3rd class) is listed in `features_used` and on the chips with importance 0, instead of being left out as "has one value in these rows".
- **F11. `GET /recipes` doesn't give per-method compatibility.** TRD §4.8's table promises "per-method compatibility". With Auto only it matters little, but the as-built note doesn't say it's missing.
- **F12. A help question can route to `ask_model`.** "how do I re-run an outdated analysis?" went to `ask_model` (the small route model, with a run in focus). It answered "The results do not contain information…" although `docs/help/analysis.md:18-19` answers it. Fix: a keyword pre-route for "how do I …" to `app_help`, as `flow.MAKE_SENSE` does for the Flow tab.
- **F13. `ask_meaning` silently drops the general block when the model returns nothing.** `insight.py:378-389`: after the repair, `general` is `None` and the answer has no general block and no note. Correct (nothing invented), but TRD §8.2 says the block is shown. The answer could say "No general description is available for parch."
- **F14. "The model" means the newest run once another answer intervenes.** `insight.py:281` (`pick_run`): the focus is only the previous answer's. After "what drives survival?" (all rows) then a stats question, "who did the model get wrong?" answered about the 3rd-class run.
- **F15. TRD §2's layout still lists `notebook/repro_render.py`, `ml/common.py`, `ml/recipes/` and `ml/methods/`.** §7.5 explains the `ml/` split, but nothing says reproduction rendering lives in `ml/repro.py`, not `notebook/repro_render.py` (also named in plan D7.5). Add an as-built line to §2 (not done here, to keep `docs/04-TRD.md` edits to the fixes).
- **F16. Three tests poll `GET /jobs` without checking the status.** `test_notebook.py:164`, `test_stories.py:152,200` index the JSON as a list. Under load the endpoint returned an error object (most likely the read rate limit), so they fail with a `TypeError` instead of retrying. Fix: retry on a non-200 in `wait_for`'s lambdas, or raise the limit in tests.
- **F17. No test asserts `run.updated`.** `tests/test_ml.py` polls `GET /runs/{rid}`. The web app depends on the event (`web/src/api/queries.ts:326`, locked).
- **F18. The setup form's number fields can't be typed into.** `MlSetup.tsx:183` drops any value outside the range on each keystroke. Typing "120" into Time budget fails at "1" (minimum 10), so only the spinner works. Fix: keep a text draft and check on blur.
- **F19. An analysis widget's scope chip says only "Some rows".** `WidgetShell.tsx:230` (locked): the 3rd-class analysis shows "Some rows", not "pclass = 3". The model card does say it.
- **F20. Click-to-filter needs a mouse move before the click.** The click reads the hovered bar (Day 4's F2 is the keyboard side of this), so a click without a prior `mousemove` only focuses the widget. A touch tap may do the same; that isn't verified on a device.
- **F21. Minor statistics.** Cohen's d uses the unweighted average of the two variances (`insight.py:141`), not the n-weighted pooled SD. Cramér's V uses `chi2_contingency`'s Yates-corrected chi² for 2×2 tables (`:160`). Both are common and both understate a little. State them in TRD §8.2, or use the pooled SD and `correction=False`.

## Commits on this branch

| Commit | What | Test | Doc |
|---|---|---|---|
| a4032bf | `plan.py`: a target name of 4+ letters and digits still matches a column name anywhere; a shorter one matches as whole words (split at punctuation and camelCase). A target `y` no longer leaves out `day` and `salary`; `age` no longer leaves out `page_views`. | `test_ml.py::test_a_short_target_name_leaves_out_only_columns_named_after_it` | TRD §7.5 step 3 |
| 8d553f9 | `plan.py`: a category target needs `cv_folds` rows of each value, else `422` with the value and its count. Before, 3 positives in 300 rows crashed with SciPy's "Only one class present". The preview and the job both check it. | `test_ml.py::test_an_outcome_rarer_than_the_folds_is_refused` | TRD §4.8 |
| 0179fbb | `analysis.verdict` and `insight._verdict_runs`: when the best one-column rule clearly beats the majority, a weak or no_signal verdict names that column instead of calling the drivers weak. | `test_ml.py::test_one_strong_column_is_named_not_called_weak`, `test_answerers.py::test_ask_why_names_the_one_column_that_carries_the_signal` | TRD §6.6, §8.2 |
| c30349a | `routers/runs.py`: `GET /recipes?scope=` that isn't JSON is `422`, not 500. | `test_ml.py::test_recipes_preview_run_results_code_and_cache` (extended) | TRD §4.8 |
| c8b1331 | `core.sample` (carried into `repro.py`): a scope over 50,000 rows is sampled stratified by a category target, as the model card's `stratify_column` already claimed and TRD §6.7 specifies. The drawer names the stratify column. | `test_ml.py::test_a_large_scope_is_sampled_stratified_in_the_app_and_its_reproduction` | TRD §7.5 step 1 |
| 0fdde18 | `analysis.model_card` marks a baseline on a target-encoded column `target_encoded`, and neither verdict nor `ask_why` names it as carrying the signal (F1's live case). | `test_ml.py::test_one_strong_column_is_named_not_called_weak`, `test_answerers.py::test_ask_why_names_the_one_column_that_carries_the_signal` (extended) | TRD §6.6 |
| c2020d6 | `insight.ask_stats`: rank-biserial r = 2U/(n₁n₂) − 1, the same sign as Cohen's d. | `test_answerers.py::test_ask_stats_picks_the_test_by_the_column_types` (extended; fails without the fix) | TRD §8.2 |

None of these touch a locked file. Nothing is pushed or merged.

## Token Factory spend for this review

| Run | `llm_calls` | Prompt tokens | Completion tokens |
|---|---|---|---|
| Browser exit check on my API: two dashboard builds (Titanic, sales), story narration for both and for 5 runs, 5 chat messages | 41 | 32,038 | 46,357 |
| First attempt that reached the Day 6 API (one build and its narration) | billed to the Day 6 API, not counted | — | — |
| `eval ml`, planted data, notebook runs, tests | 0 (code only, fixtures) | — | — |
| **Total on this review's API** | **41** | **32,038** | **46,357** |

By purpose: narrate 22, overview 8, route 5, curate 2, meaning 2, stats 1, compose 1. Four of the 41 needed a repair, and none failed.
