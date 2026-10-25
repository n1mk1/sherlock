# Day 6 review: stories and the cascade

Reviewed 2026-10-25 on branch `claude/review-day6-e3de9c`, cut from `main` at 8c96ca3. The scope is Implementation Plan §2 "Day 6", narrowed by cut 6 (no material hash: every affected card is narrated again). "Done" means plan §1: it runs on the Titanic sample, its test passes, the UI reaches it, and it's committed.

**Verdict.** Day 6 meets its exit check in a real browser, and every number on a card traced back to code: 60 of 60 chips in the live grounding eval (Titanic and `sales_dated.csv`), 62 of 62 on the browser datasets, and 130 fact-sheet values recomputed independently with pandas and scipy, all equal. But Rule 2 had holes. A model could put a number on a card through a value label, which was accepted for any value and shown as written. It could also spell numbers in forms the validator missed: teens, "half", "a third of", Roman numerals, "²", "½" and HTML entities. This review closed those holes for story cards, the overview and synthesis cards (commits 10e5a33 and 62341c7). The same label hole is still open in chat answers (F2). The other fixes:

1. The card editor lost the text of a numbered list on Save.
2. `n` counted rows with a blank in the widget's column, so a card read "Average fare across 1,309 passengers" next to a tile saying "of 1,308 rows".
3. Cards read "38.2% %" and "sex.female".
4. `uv run sherlock eval grounding`, the PRD's P0 grounding test, didn't exist. It's built now.

Each fix is its own commit with a test and its doc change.

## Evidence

| Check | Result |
|---|---|
| `uv run pytest` (api, after the fixes) | **350 passed, 3 skipped**, 1 deselected (the `live` marker), on the final commit 62341c7. |
| `uv run pytest` before the fixes | 1 failed, 205 passed, then stopped (`-x`). The failure was `test_notebook.py::test_export_runs_and_rebuilds_the_version_after_an_undo`: `wait_for` polled `/jobs` every 50 ms, so on a busy machine (three reviews' test runs at once) a wait outlasted 600 reads a minute and got a 429 body. Fixed in 6174618 (poll every 0.2 s), after which 345 passed and 3 skipped. |
| `pnpm test` (web, after the fixes) | 8 files, 55 tests passed (53 before, plus 2 new). `tsc -b` is clean. |
| `uv run sherlock eval grounding`, live, run once | **60 of 60 chips grounded, 0 problems.** titanic3.csv: 10 cards, all by the model, 32 chips, 14 calls, 29,335 tokens. sales_dated.csv: 9 cards, all by the model, 28 chips, 11 calls, 21,667 tokens. The command didn't exist before this review (F5). |
| The same checks on the browser datasets | 29 of 29 chips on the exit-check dataset after the cascade and 33 of 33 on the first build. The one "problem" was the reviewer's own typed text on the edited card, so the eval now skips the text runs of edited cards (TRD §14). |
| Independent fact-sheet check (pandas and scipy, not the app's SQL) | **130 values, all equal.** Titanic, all 9 SQL widgets: 36 of 36 (KPIs, histogram, two box plots, heatmap, rate bar with χ² and Cramér's V). sales_dated (built offline with the model off, 0 tokens): 36 of 36, including the scatter correlation and Kruskal-Wallis. The time series on sales_dated (month sum, week average, month count): 33 of 33, including the Kendall trend and its p-value. wide_messy: 25 of 25. The 2 other "differences" are the checker printing an int category as `1.0`. |
| Rule 2 probes against the narrator (`stories/narrate.py`) | 33 tries. **Before:** 25 got a model-made number onto the card. They were value labels (`value:fare:512.33` shown as "fare 512.33", `value:sex:three quarters`), Unicode numbers (² ½ ① Ⅻ), Roman numerals ("XLV"), teens, zero, half, "a third of", "one in", quadrupled, hundredfold, trillion and ordinals. **After:** only ordinals, "fourscore", non-English words and spaced letters get through (TRD §7.4 lists them). Digits, fullwidth and Arabic-Indic digits were already refused. |
| Notebook export of the browser dataset (v3, after the cascade and an edited card) | The overview follows the load cell as "## What stands out". Each card follows its widget as `###`, with a "Related:" line and a closed `<details>` Evidence block. The hand-typed 12 shows as `12*` with the footnote. Seen: "38.2%%" (since fixed) and "2.7 points.." (fixed by the same commit). |
| Browser exit check, live, run once | **Passed.** API on :8106, Vite on :5196 at `review6.localhost`. Screenshots are in `reviews/day-6/`. Spend: 21 calls, 45,107 tokens, plus 12 calls and 24,708 tokens for a first build that had to be repeated after a port clash (F22). |

### Exit check, step by step

| Step | Result | Screenshot |
|---|---|---|
| The sample dashboard has grounded cards | Try with sample, then Use as is. Ten widgets: three KPIs, histogram, two box plots, two heatmaps, a count bar and "What drives survived?". Eleven cards (the overview plus 10), all written by Nemotron Super, one after a repair. Every chip is grounded (29 of 29 after the cascade). | `01-dashboard-and-cards.jpg` |
| Hovering links both ways | Hovering "Fare by passenger class" scrolls to its card and highlights it. Hovering the "Fare distribution" card spotlights its widget. | `02-hover-widget-highlights-card.jpg`, `03-hover-card-spotlights-widget.jpg` |
| A chip opens its evidence | "512.33 is the highest fare, computed on version 2", with the `SELECT MAX("fare") …` that made it and Copy. | `04-evidence-drawer.jpg` |
| Editing a column's values updates only the cards that depend on it | The exit check names `age`, but here only the analysis reads `age`, so the check used `fare`, as the plan's own check did. Row 1's fare went to 60000 in the CSV tab and was saved as v3. The progress line read "Updating 5 widgets and 5 stories" and the five widgets dimmed. The cascade took 25 s: `{widgets: 5, cards: 4, runs: 1}`. Changed: Average fare (now 79.01, "changed"), Fare distribution, Fare by passenger class, Fare by gender, and the analysis, which re-ran with its card re-told. Untouched, still v2 with the same `updated_at`: Survival rate, Number of passengers, Survival by class and gender, Survival by gender and siblings/spouses, Passenger counts by parents/children. The overview was re-told with the badge. | `06-cascade-progress-line.jpg`, `07-cascade-changed-badge.jpg` |
| An edited card keeps its text and shows a suggestion | Before the edit, the "Fare by gender" card was edited: a sentence with a typed "12" (saved as a dashed unverified chip) and a chip from the `/` picker. After the cascade it kept that text with "edited" and "changed", and showed "The data changed. Suggested revision:" with Accept, Edit and Dismiss. | `05-edited-card-unverified-chip.jpg`, `08-edited-card-keeps-text-with-suggestion.jpg` |
| Ask why → chat | Fills "Why Median fare was highest for pclass 1 passengers, at 60.00…" with the widget as the context chip. It wasn't sent, to save tokens. | `09-ask-why-to-chat.jpg` |
| Not Titanic (Rule 4) | `sales_dated.csv` in the live grounding eval: 9 cards, 28 of 28 chips grounded. Its fact sheets, time series included, were recomputed independently (above). | n/a |

## Status by item

| Item | Status | Evidence |
|---|---|---|
| **D6.1** `stories/`: fact sheets per view, significance helpers, relations, narrator with the chip-only schema and no-digits validator, `verify`, overview, `stories` job streaming `card.updated` | **done** (Rule 2 holes and two fact bugs fixed here) | `stories/facts.py`, `narrate.py`, `service.py`, `jobs/stories.py`. Every fact type matched an independent recomputation (130 values). χ² uses scipy's default Yates correction on 2×2 tables, so Cramér's V reads 0.527 where the uncorrected value is 0.529 (F19). `verify` re-runs SQL and recomputes `a / b` and the change; tests and labels are taken as recomputed with the sheet (`facts.py:318`). **Fixed:** value labels unchecked, number forms missed (10e5a33); `n` counted blanks, `depends_on` read a CTE's `lo`/`w` (2101a3a); "38.2% %" and "sex.female" (ac83dc9). `card.updated` streams per card (`service.py:285`), seen live. |
| **D6.2** cascade within cut 6: column dependencies, suggestions for edited cards, Ask first marks outdated, debounce, every affected card re-narrated | **done** | `jobs/cascade.py`. Live: only the five `fare` widgets were affected, and the edited card got a suggestion (above). Debounce: `test_jobs.py:372`. Ask first had no card test; one is added in 62341c7: the affected cards and the analysis whose run read the column go `outdated` with their text kept, and no narrate call is made. An analysis card re-told after its re-run gets no "changed" badge (F15). |
| **D6.3** story panel, cards, chips with the evidence drawer, related chips, two-way hover with the spotlight, badges, TipTap editor with chip and label nodes and `/` picker, suggestion side by side, Ask why → chat | **partial** | All built and seen live (`StoriesPanel.tsx`, `StoryCard.tsx`, `CardEditor.tsx`). **Fixed:** the editor saved a numbered list as empty text and joined words across a line break (efbe3bc). **Open:** a card edit stores whatever chips the client sends (F3). The suggestion sits under the body, not side by side (F14). Editor chips show write-time values, and `/` can't be typed (F12). Cards and widgets can't be focused (F13). |
| **D6.4** cascade progress line, updating widgets and cards, summary toast | **done** | "Updating 5 widgets and 5 stories" with the widgets dimmed (`06-…jpg`). Cards show a spinner from `status: updating`. Toast at `DatasetPage.tsx:97-102` (locked; seen in code, gone before a screenshot). The line can stick if the page is left mid-cascade (F11, from code). The toast leaves out `outdated` and `errors` (F23). |
| **D6.5** custom visx histogram, heatmap, box plot, scatter; builder candidates; gauge as a KPI tile | **done** (F10 open) | `charts/custom.tsx`, `dashboard/candidates.py:210-255`. Live on Titanic: histogram, two box plots and two heatmaps. The scatter was built on sales_dated ("revenue against unit_price"). Gauge → KPI at `adapter.tsx:90`. "Change view" never offers heatmap or scatter, so a heatmap switched to a bar can't go back (F10). |
| **D6.6** story cards in the notebook: overview as the introduction, each card after its widget, evidence details, unverified footnotes, Include story cards | **done** (F9 open) | `notebook/exporter.py:119-176`, `cells.py:228-270` (both locked). Checked on the live export (above) and by `test_cards_go_into_the_notebook`. Text runs go into Markdown raw (F9). |
| Day 4 carry-over: chart text alternatives, reduced motion, keyboard click-to-filter (F2, F10), shared hover (F18) | **partial** | The custom charts have `role="img"` and an `aria-label`, but it's built from the result rows, not the fact sheet (UI/UX §8); Bklit charts still have none. Reduced motion is partial: tokens are zeroed (`theme.css:163`), but the chip pulse, smooth scrolls, `animate-spin`/`animate-pulse` and Bklit bars still move. Click-to-filter still needs a mouse (`adapter.tsx:102-121`). Card ↔ widget hover works. Hovering a point in one chart doesn't highlight it in another, so the spike's "shared hover across two charts" is still unbuilt (F13). |

## Findings, ranked

"Locked" marks a file with the owner's uncommitted Day 8 work, so this review reports the finding but doesn't fix it.

### High

- **F1. A value label could carry any number onto a card (Rule 2). Fixed.**
  - Where: `narrate.py::label_text`. It accepted `value:<column>:<value>` for any column of the file and any value, and the card shows the value as written.
  - What happened: `{"label": "value:fare:512.33"}` put "fare 512.33" on the card, and `value:sex:three quarters` put "three quarters". It didn't match TRD §7.4, which says labels name "the category values its facts name".
  - Synthesis cards and `ask_story` had the same hole (`synthesis.py::_check`).
  - Fixed in 10e5a33 (stories and the overview, whose prompt now lists the allowed value labels) and 62341c7 (synthesis).
  - The same commits closed the missed number forms: teens, zero, half, "a third of", "one in", -fold, quadrupled, trillion, capital Roman numerals, any Unicode number (category N) and HTML entities.
- **F2. Chat answers have the same label hole (Rule 2, open).**
  - Where: `agent/compose.py:75-83`, Day 4 code. `label_text` takes any value of an existing column, so a composed answer could say "fare 512.33" as a label.
  - Fix: allow only values that occur in the answer's result cells (or the DataCard's top values), as stories now do. Add to TRD §8.1.
- **F3. A card edit stores whatever chips the client sends, so a chip can look verified with nothing behind it (Rule 2).**
  - Where: `routers/cards.py:57-67` (locked) stores chip runs as sent. `CardEditor.tsx:18` lets pasted `span[data-chip]` create chips with any `key`, `value` and `unverified`.
  - What happens: a chip with `key: null, unverified: false`, or with a key not on the sheet, renders as a solid "verified" chip.
  - Fix: in PATCH, resolve each chip against the card's fact sheet: take the value from the sheet, and mark a chip with an unknown key unverified. TRD §4.6.
- **F4. The editor lost the user's words. Fixed (efbe3bc).** "1. " made a numbered list, which `fromDoc` saved as empty text. A line break joined the words either side, and marks were dropped.
- **F5. The PRD's P0 grounding test had no command. Fixed (5edd5e2).** `uv run sherlock eval grounding` answered "comes with D6" after D6 was marked done. PRD §3 and STORY-3 make "100% of cached story numbers pass verify" a P0 metric.

### Medium

- **F6. `n` counted rows with a blank in the widget's column. Fixed (2101a3a).** Live: "Average fare across 1,309 passengers" beside the tile's "of 1,308 rows". The small-sample rule also reads `n`.
- **F7. Units said twice, missing spaces. Fixed (ac83dc9).** Live: "Survival rate was 38.2% %.", "501.0× times larger", "2.7 points..", "for each sex.female".
- **F8. The narrator states rankings and comparisons that no fact backs.**
  - Live: "Age follows as the second most important factor. Ticket comes third", "Survival decreases for lower classes and for males within each class" (the heatmap's sheet holds only its highest cell), and "Passengers in the group with the highest median paid considerably more…".
  - None of these is a number, but none can be verified either. Ordinals are the known Rule 2 gap.
  - Fix: give ranks as chips (`driver_2` is already a fact), add a prompt rule to say only what the listed facts show, and consider rejecting comparative claims about groups the facts don't name.
- **F9. The notebook puts text runs into Markdown raw.**
  - Where: `notebook/cells.py:229-243` (locked).
  - Model text can no longer hold entities or brackets, but a user's edited card can: `&half;`, `<img …>`, `#` or `*` render as Markdown or HTML.
  - Fix: escape `\`, `*`, `_`, `#`, `<`, `>` and `&` in text runs. TRD §7.7 rules.
- **F10. "Change view" never offers heatmap or scatter.**
  - Where: `WidgetShell.tsx:30-40`.
  - A heatmap's result reads as bar, pie or ring, so after switching it to a bar there's no way back, and the current view isn't checked in the menu.
  - Fix: offer heatmap for two categories plus a value, and scatter for two numeric columns.
- **F11. The cascade progress line can stick (from code, not reproduced).**
  - Where: `DatasetPage.tsx` (locked), `sse.ts:7-9`.
  - The line clears only on `cascade.done`. A user who leaves the dataset mid-cascade, or a job that dies before `cascade.done`, leaves it and the dimmed widgets until the next cascade.
  - Fix: clear it when the cascade job reaches a final state, or on mount.
- **F12. Editor gaps.**
  - Editor chips show the value stored when the card was saved, not `Card.facts` (TRD §4.6), and unverified chips aren't dashed (`CardEditor.tsx:21-25`).
  - `/` is always swallowed, so "and/or" can't be typed (`:107-111`).
  - The picker's `role="listbox"` has no options and no arrow keys (`:144`).
- **F13. Accessibility carried from Day 4 (F2, F10, F11, F18), still open.**
  - Click-to-filter needs a mouse.
  - Bklit charts have no text alternative. The custom charts' labels come from rows, not fact sheets (UI/UX §8).
  - Reduced motion leaks: the chip pulse is a hard-coded 400 ms (`StoryCard.tsx:40`), plus smooth `scrollIntoView`, `animate-spin`/`animate-pulse`, and Bklit bars without `useReducedMotion`.
  - Cards and widgets can't be focused, so card ↔ widget linking has no keyboard path.
  - Shared hover across two charts isn't built.
- **F14. The suggestion isn't side by side, and the docs disagree.** Plan D6.3 says "side by side". App Flow §11 step 5 says "your text vs the AI's revision, Accept / Keep mine". UI/UX §4.5 as-built says under the body, which is what's built (`StoryCard.tsx:132-153`). The owner should pick one; add, don't cut.

### Low

- **F15. An analysis card re-told after a cascade gets no "changed" badge.** Live: "What drives survived?" was re-told on v3 with `changed_badge = 0`. Its re-run queues a `stories` job with reason `widget`, not `cascade`.
- **F16. Labels repeat the model's words.** "Passenger class pclass 1", "Fare fare values spanned…". A numeric category reads "pclass 1" by design (TRD §7.4), and the model adds its own noun. A prompt line could say a label already names its column.
- **F17. Small story-panel bugs (from code).**
  - Suggestion chips are buttons with no handler (`StoryCard.tsx:143-144`).
  - The outdated badge has no pending state, so repeat clicks queue repeat jobs (`:112`).
  - Hover isn't cleared on Edit layout or widget delete.
  - `StoryCard` reads `useUi()` without a selector.
  - Hovering a related chip can scroll the panel back and forth.
  - The evidence query isn't invalidated on `card.updated`, so for up to 30 s the drawer can show the old version (`queries.ts`, locked).
  - The drawer shows no run for an analysis fact.
  - The panel says "Stories appear once the dashboard is built" when the cards request fails (`StoriesPanel.tsx`, locked).
- **F18. A number word the user types isn't marked unverified.** `mark_unverified` matches digits only, so "zero" in an edit stays plain text.
- **F19. Cramér's V uses the Yates-corrected χ² on 2×2 tables** (`facts.py:164`). It reads 0.527 against 0.529 uncorrected for sex × survived. That's negligible, but the usual definition is uncorrected.
- **F20. Remaining Rule 2 gaps, by design.** Ordinals ("first", "third"), archaic and non-English number words, and letters spaced apart. TRD §7.4 now lists them.
- **F21. The suggestion's Accept uses the sheet's version, but an edited card's chips already show the new values.** The user's kept text with "Rows: 1,309" re-renders from the latest sheet, so a number in the user's sentence can change under them. That's by design (TRD §4.6), but the "edited" card doesn't say so.
- **F22. Environment notes for the next browser check.**
  - Port clash: another session's Vite held `[::1]:5187` while this review's Vite took `127.0.0.1:5187` (autoPort moved it off a busy 5186). The other session's browser then reached this API: a sample dataset and a widget were created on :8106 (14 calls, 28,188 tokens, not counted below). Use `--strictPort --host 127.0.0.1` and a port no sibling uses. A note is in the shared notes folder.
  - The first page load still made 3 or 4 anonymous users (the Day 1 identity finding).
  - The browser tool's `type` action doesn't fire TipTap's key handler. Press `/` with a key action instead.
- **F23. The cascade toast leaves out `outdated` and `errors`** (`DatasetPage.tsx`, locked), so it understates an Ask-first cascade.

## Commits on this branch

| Commit | What | Test | Docs |
|---|---|---|---|
| 6174618 | `wait_for` polls every 0.2 s, so a slow machine's waits don't hit the 600-reads limit and get a 429 body | the job tests pass under load (they failed before) | none (test only) |
| 10e5a33 | Rule 2: a story's and the overview's `value:` labels must be allowed labels; more number words and capital Roman numerals; any Unicode number is a digit; HTML entities are markup | `test_no_number_reaches_a_card_by_another_way` fails before, passes after | TRD §7.4 "second pass" |
| efbe3bc | The card editor offers only what a card stores: no numbered lists, line breaks or marks; no lists in the headline | `stories.test.ts` "the card editor's schema" fails before, passes after | App Flow §11 |
| 2101a3a | `n` counts rows with the widget's columns filled; `depends_on` leaves out columns of other tables (a CTE's `b.lo`) | `test_rows_behind_a_widget_have_its_columns_filled…` fails before, passes after | TRD §6.4 |
| ac83dc9 | No unit said twice after a chip (`%`, percent, ×, times, a sentence's full stop); a space after punctuation before a chip or label | `test_a_unit_the_chip_shows_is_not_said_twice…` fails before, passes after | TRD §7.4 "Rendering in code" |
| 5edd5e2 | `uv run sherlock eval grounding` | `test_the_grounding_eval_checks_every_number_on_the_cards` (passes on real cards, flags a tampered chip and a spelled number) | TRD §14, plan §3 and §4 |
| 62341c7 | Synthesis and `ask_story` value labels checked against the labels their cards use; plus a test of "Ask first" for cards | `test_a_synthesis_takes_only_the_value_labels…`, `test_ask_first_marks_the_affected_cards_outdated…`; `test_canvas.py` still passes | TRD §7.4.1 |

## Token Factory spend for this review

| Run | `llm_calls` | Tokens |
|---|---|---|
| `eval grounding` (live, once): titanic3 and sales_dated | 25 | 51,002 |
| Browser exit check (build, stories, cascade) | 21 | 45,107 (14,219 prompt, 30,888 completion) |
| First browser build, repeated after the port clash (F22) | 12 | 24,708 (7,719 prompt, 16,989 completion) |
| **Total** | **58** | **120,817** |

The fact-sheet checks on sales_dated and wide_messy ran with the model switched off (0 calls). Another session's browser reached this API during the port clash and spent 14 calls and 28,188 tokens on its own dataset. That spend isn't counted above.
