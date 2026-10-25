# Day 2 review: ingest, profile, steps, sandbox, jobs, rows, LLM client, shell

Reviewed 2026-10-25 on branch `claude/review-day2-ce42ad`, cut from `main` at `79f07eb` (Day 5). The scope is Implementation Plan §2 Day 2 (D2.1–D2.10) as rescheduled by §2.0, with the definition of done in §1.

**Verdict.** The Day 2 exit check passes for real, end to end, over `curl`. The backend items are built as the TRD's as-built notes describe, and the frontend items run against the real API. This review fixed seven small bugs, each in its own commit with a test and the matching TRD line. These remain open:

- **High:** a CSV with one ragged row imports silently as a single column.
- **Medium:** the typing step isn't fully lossless (floats past 17 significant digits; timestamps with an offset are moved to UTC and the offset is dropped), and its `verifiers` are hard-coded.
- **Medium:** `openapi.json` is stale, on this branch and on `main`.
- **Medium:** the per-version DuckDB cache can close a connection while a request is still using it.

## How this was checked

- **Tests.**
  - `uv run pytest` in `api/` at `79f07eb`: 280 passed, 3 skipped, 1 failed. The failure was `test_sandbox.py::test_happy_path_and_log`. It's a test-isolation bug, fixed in `15dcccc`.
  - After the fixes: see "Final test run" at the end.
  - `pnpm test` in `web/`: 6 files, 36 tests passed. Plain `pnpm` isn't on PATH on this machine, so it ran as `npx pnpm@10`.
- **Live exit check.**
  - The API ran on `127.0.0.1:8102` with its own scratch `DATA_DIR`.
  - `LLM_BASE_URL` was empty, so every model call failed fast to its fallback and nothing reached Token Factory.
  - **Token Factory spend: 0.**
- **Review.** I read the code against PRD, TRD §3–§7, the Backend Schema and App Flow. Three read-only review passes ran in parallel: ingest/profile/typing, steps/jobs/rows, and llm/web. I re-verified every finding below that carries a file:line, either by reading the code or with a probe. The probe scripts are outside the repo.
- **Not verified here:**
  - The POSIX-only sandbox tests (the memory limit, the `sherlock-sandboxd` protocol, the run-as-`sandbox` isolation) are skipped on Windows. They are covered by the image checks recorded in TRD §3.4.
  - I did not try to get code past the sandbox allowlist. D2.4 is assessed from the protocol tests and from reading the defences.

## Exit check transcript (abridged)

```
POST /api/v1/datasets  file=@api/samples/titanic3.csv
  → 201 {"status":"profiling","current_version":1,"row_count":1309,"column_count":14}
GET /datasets/{id} (3 s later)
  → {"status":"offer","current_version":2,"issue_count":13,"step_count":1}
GET /datasets/{id}/events?last_event_id=0   (replay)
  id 1 job.progress  "Typing 14 columns"
  id 2 version.created  v2 "Typed 7 columns from text: pclass, survived, age, sibsp, parch, fare and 1 more"
  id 3 job.log …  id 4 job.progress "Profiling 14 columns" 50%
  id 5 dataset.status offer v2  id 6 job.done result {version:2, issues:13, typing_step_id}
GET /events (user stream, opened before the upload, live)
  → ids 1, 4, 5 only (job.progress, dataset.status), as TRD §5.2 scopes it
GET /datasets/{id}/datacard → 14 columns typed and with roles; 13 issues (missing, leakage, mixed_types,
  whitespace_case, functional_dependency, id_candidates)
GET /datasets/{id}/rows?limit=2&sort=age:desc → total 1309, row 15 age 80.0 first
POST /datasets/{id}/edits {base_version:2, edits:[{15,age,"81"},{15,cabin,"Z99"}]}
  → 201 step 2 kind edit, to_version 3, notebook_code "df.loc[df._row_id == 15, 'age'] = 81.0 …"
POST …/edits again with base_version 2 → 409 conflict, current_version 3,
  conflicts [{row_id:15, column:age, mine:"82", theirs:"81.0"}]
GET /rows?view=changed → v3, 1 row, marks {age: changed, cabin: changed}; cell history has old 80.0 → new 81.0
POST /steps/{step2}/undo {base_version:2} → 409 (stale)
POST /steps/{step2}/undo {base_version:3} → 200 step 3 kind undo, to_version 4
POST /steps/{step2}/undo {base_version:4} → 409 "This step isn't part of the current data"
rows at v2 / v3 / v4 for row 15: 80.0 A23 / 81.0 Z99 / 80.0 A23 (v4 = previous data, no marks)
versions table: v4 → parquet_path versions/v2.parquet, effective chain [typing step]; v3.parquet untouched
POST /steps/{typing}/undo {confirm:false} → {"confirm_required":true,"replay_needed":[],"warning":"typing"}
SSE replay after id 6 → id 7 version.created (edit), id 8 version.created (undo)
Another user (no cookie): GET /datasets/{id} and /datasets/{id}/events → 404
export.csv → 200, Content-Disposition: attachment; filename="titanic3-v4.csv"
find?q=Barkworth → {"count":1,…}; columns/embarked/values → S 914, C 270, Q 123
```

Non-Titanic files (CLAUDE.md Rule 4):

| File | Result |
|---|---|
| `;`-delimited cp1252 with a quoted newline, decimal commas, leading-zero codes | 201 · 3×6 · `Montréal`, `bon\nmultiligne`, `02134` intact; nothing typed (lossless) |
| tab-delimited UTF-16 (BOM) | 201 · 3×6 · same values |
| `|`-delimited UTF-8 with BOM | 201 · 3×6 · same values |
| header `a,a,,_row_id,b` | 201 · `a, a_2, col_3, _row_id_2, b` |
| header `Name,name,NAME,_ROW_ID` | 201, but DuckDB renamed them `name_1`, `NAME_2`, `_ROW_ID_1` and `columns_json` disagreed. **Fixed** (`f9567d9`) |
| header only / empty file | 422 "This file has no data rows." |
| binary bytes | 422 with App Flow §3.2's copy |
| `samples/broken_latin1.txt` | 201 · 152×4: the preamble is read as data, a known and documented gap (Plan §6). The typing step quarantined the header line and kept "salary" in lineage, as TRD §7.1 3b says |
| 3 columns, one row with an extra field (or 10% of rows short) | **201 as a single column `a,b,c`**: open High finding 1 |
| timestamps with `-05:00` and `-04:00` offsets | the dataset ended `failed` with "Can only use .dt accessor with datetimelike values". **Fixed** (`82af08b`) |

## Status by item

| Item | Status | Evidence |
|---|---|---|
| **D2.1** ingest and the datasets endpoints | partial | All four endpoints behave as TRD §4.2 says (transcript). BOM, UTF-16, `;`/tab/`|`, quoted newlines, blank, duplicate and reserved headers, and the refusals all work (`test_ingest.py`, 24 tests). Open: ragged rows (High 1); a quoted newline inside a header cell (Low). Fixed: case-only duplicate names (`f9567d9`) |
| **D2.2** profile and the 16 detectors | done | Every detector in PRD §7.3.2 is in `cleaning/detectors/`, registered in `DETECTORS`/`WEIGHTS`, and has a synthetic-column test in `test_detectors.py` (mixed types, sentinels, whitespace/case, near-duplicate categories, duplicates, impossible values, numbers as text, ambiguous dates, mojibake, unit mixes, cross-column, functional dependency, ID candidates, missingness, outliers, leakage). The datacard and value index are tested in `test_profile.py`. Fixed: mixed-offset crash (`82af08b`) |
| **D2.3** `commit_step`, undo latest, steps endpoints | done | Lock, `base_version` 409, effective chain, lineage, `state_rev`, required `notebook_code` and re-profile (`steps/commit.py`). Undo of the latest step writes a new version row that points at the older Parquet and rewrites nothing (transcript: v4 → `v2.parquet`), as TRD §7.8 says. Tests: `test_steps.py`, `test_replay.py` |
| **D2.4** sandbox | done (POSIX parts not run here) | `test_sandbox.py`: 42 passed, 3 skipped on Windows (RLIMIT_AS, the daemon, run-as-`sandbox`). The static check works on the syntax tree, and the worker restricts builtins and imports again, blocks sockets and builds its env from scratch (`test_worker_env_has_no_secrets`). Allowlist escape attempts weren't run in this review |
| **D2.5** jobs, SSE with replay, profile job | done | The claim statement matches TRD §3.3. Replay with `?last_event_id=` and live delivery match §5.2 (transcript). Another user gets 404. Tests: `test_jobs.py` |
| **D2.6** rows API | done | Paging, sort, filter, views, marks, history, edits with conflicts, find, values and `export.csv` (transcript, `test_rows.py`). Fixed: integer edits rounded or 500 (`a53efa3`), RE2-only regex 500 (`ab8f34a`), `contains` wildcards (`d54abcb`). Open Lows below |
| **D2.7** `llm/` | done | Strict `json_schema`, one repair, retries only on transient errors, budgets before each call, an `llm_calls` row per attempt, fixtures, `REASONING_OFF_OK = {route}`, the Nemotron-only startup check (`test_llm_client.py`, `test_llm_models.py`). Fixed: the 120 s cap was exceeded (`b254c23`) |
| **D2.8** typing step as step 1 | partial | Committed as step 1 on upload, on the sample and through the CLI, which goes through `POST /datasets`. Lossless for int (`007` stays text), bool and plain dates. A failed cast quarantines the row with the original kept in lineage (verified live). Open: Medium 2 (floats, offsets, hard-coded verifiers) |
| **D2.9** shell, tokens, client, SSE hook, Query and stores | partial | Three panels with slide-overs, tabs, the theme tokens (spot-checked against Brief §2.1), `openapi-fetch` client, `sse.ts` with resume and dedup, TanStack Query, the Zustand store. Built against the real API per Replan §2.0. Open: `openapi.json` stale (Medium 3); error boundaries not built (already listed in Plan §3) |
| **D2.10** Library panel | done | List with status badges from the user-level stream, dropzone overlay, Papa Parse import preview (`web/src/lib/importPreview.ts`), sample button, and the size, binary and no-rows rules. Open: header/skip preview (Medium 6), small UI gaps (Low) |

## Commits on this branch

| Commit | Fix | Test | Doc |
|---|---|---|---|
| `a53efa3` | Integer edits are parsed exactly. `9007199254740993` was saved as `…992` and marked "changed". An integer past `BIGINT`'s range is now `invalid`, where it used to be a 500 | `test_integer_edits_are_exact_or_invalid` | TRD §4.3 |
| `ab8f34a` | `find` regexes that Python's `re` accepts but DuckDB's RE2 refuses (`(?=a)`, `(a)\1`) are 422, where they used to be 500 | `test_find_values_and_csv_download` | TRD §4.3 |
| `d54abcb` | The `contains` filter is a plain substring. `%` used to match every row, and a null value searched for "None" | `test_page_sort_and_filter` | TRD §4.3 |
| `b254c23` | LLM calls stay within 120 s, attempts included. A call that kept timing out ran to 122 s on large and 134 s on small/medium | `test_retries_stop_at_the_two_minute_cap` | TRD §3.5 |
| `82af08b` | A column of timestamps with mixed UTC offsets stays text, where it used to fail the profile job | `test_mixed_utc_offsets_stay_text_and_profile` | TRD §7.1 type rules |
| `15dcccc` | Tests get their own `SANDBOX_TMP`. The shared `<temp>/sherlock-sandbox` made the "temp dirs removed" check fail whenever another Sherlock process ran a worker | (`test_sandbox.py` now passes alongside other runs) | — (test-only) |
| `f9567d9` | Column names that differ only in case get `_2`-style suffixes, so `columns_json` matches the Parquet | `test_names_differing_only_in_case_match_the_parquet` | TRD §7.1 column names |

Every TRD addition is one appended sentence or bullet in a section that `main`'s `52cc5eb` (Day 6) didn't touch. A test merge is reported at the end. No code file on this branch is changed by `52cc5eb`.

## Open findings, most severe first

### High

1. **A CSV with ragged rows imports silently as one column.** `ingest/sniff.py` `sniff()`: DuckDB's `sniff_csv` returns `|` for a 3-column file where 1 row in 101 has an extra field, or where 10% of rows are short. `csv.Sniffer` gives no answer, and "DuckDB wins". The file imports as one column named `a,b,c`, with no error (verified live: `ragged.csv` and `short.csv` came back as 100×1).
   - Adding `null_padding=true` to `sniff_csv`, which is what the read uses, picks `,`. But it broke `test_preamble_semicolon_latin1_is_auto_detected`, and a row with an extra field then fails the read ("Error when sniffing file"). So it isn't a one-line fix, and I reverted it.
   - The fix needs a decision:
     - how a row with too many fields is handled: `strict_mode=false`, quarantine, or a clear 422;
     - when to distrust a delimiter that yields a single column while `,`/`;`/tab occur on every line.

### Medium

2. **The typing step isn't fully lossless, and its verifiers are fixed strings.** This contradicts TRD §7.1 3b ("the cast is lossless") and PRD PROF-1.
   - `profile/typing.py:50` casts floats with `TRY_CAST(… AS DOUBLE)`, so `0.12345678901234567890` becomes `0.12345678901234568` (verified).
   - `typing.py:54` casts to `TIMESTAMP`, so `2024-01-15 10:00:00+05:00` becomes `05:00:00` with the offset gone (verified). Nanoseconds are truncated.
   - None of these rows is quarantined. The lineage diff casts the old text the same way, so the cells don't show as changed either.
   - `typing.py:137` stores `verifiers={"row_ledger": "pass", "lossless": "pass"}` without checking anything.
   - Fix (medium): a round-trip check for floats and timestamps (or a significant-digit limit), leave offset timestamps untyped or type them `TIMESTAMPTZ`, and compute the verifiers.
3. **`web/src/api/openapi.json` and `schema.d.ts` are stale** (Rule 1, TRD §3.1). They lack `NotebookOptions` and the four export routes (`POST …/exports/notebook`, `GET …/exports/notebook/preview`, `GET /exports/{id}`, `GET /exports/{id}/download`). `main`'s file lacks them too, and the story routes added in `52cc5eb` as well. `ExportDialog.tsx` falls back to the untyped `request()`.
   - Fix: on `main`, run `uv run --project api python scripts/dump_openapi.py`, then `pnpm openapi`. A test that compares `app.openapi()` with the committed file would keep them in step.
4. **The DuckDB version cache closes connections that are in use.** `storage.py` `VersionConnections._entry` (the eviction loop and the LRU overflow, lines 147–153) and `drop` (162–165) call `conn.close()` without taking that entry's `lock`.
   - A request still querying version 1 when the profile job opens version 2 gets "Connection already closed!" (reproduced with two threads).
   - Fix (small to medium): close under the entry's lock, or mark the entry and close it when its last user releases it. Watch for lock-order deadlocks with `self._lock`.
5. **Undoing a later edit drops the protection on an earlier hand edit of the same cell.**
   - `steps/commit.py:183` writes `user_edited_cells` with `INSERT OR REPLACE`, so the cell now points at the later step.
   - `steps/undo.py:114` deletes that step's rows.
   - Example: edit `name`→A1, edit `name`→A2, undo the second. The grid shows A1, but the cell is no longer protected from Clean with AI.
   - The code follows Schema §2.7 and TRD §7.8 literally; the gap is in the spec. Fix: after the delete, rebuild the cell rows from the edit steps still in the effective chain, and add that rule to the docs.
6. **The import preview's header and skip aren't detected, which can make the server use the wrong header line.**
   - `ImportPreviewDialog.tsx:40-41` always assumes `headerRow: 1, skipRows: 0`, and only changed options are sent.
   - Example: the user sets Header row = 3 on a file with 2 preamble lines and leaves Skip rows alone. The server adds its own sniffed `skip_rows` to that, and the wrong line becomes the header.
   - App Flow §3.2 says the header row is "auto-detected". Fix: send `header_row` and `skip_rows` together whenever either changes, and detect them on the client or change the doc.
7. **The Cleaner's prompts break TRD §3.5 prompt hygiene.** Column names (user data) sit outside `<data>` blocks. `cleaning/loop.py:99` `_json` wraps values in a raw `<data>` tag without defusing a `</data>` inside them, though `llm.client.data_block()` exists for this. This is Day 3 code, but the rule belongs to D2.7. Fix: small.
8. **Slide-over panels below 1024 px aren't hidden from keyboard users.** `AppShell.tsx` only moves them off screen with a transform: they stay in the tab order, have no focus trap, and Esc doesn't close them (Brief §3.1, §8). `AppShell.tsx` changed on `main` in `52cc5eb`, so fix it there.

### Low

- **SSE ordering.** `jobs/events.py:84-93` `emit` inserts the row, then publishes, with no lock spanning both. A job thread and a request thread can publish ids out of order, and a resuming client may then see an event twice. Found by reading the code; not reproduced.
- **Library stream gap.** A stream opened live-only (the library's) that drops before its first event reopens live-only too (`web/src/api/sse.ts:9,17`), so a `dataset.status` sent in that gap is lost until a refetch. Fix: invalidate the datasets query when a stream reopens.
- **Edit edge cases** (`rows/edits.py`):
  - The same cell twice in one batch stores the last value but keeps the first one's `invalid` mark and history.
  - `2020-01-01 13:45` in a `DATE` column silently drops the time.
  - `nan` in a `DOUBLE` column is accepted and marked "changed".
  - Restoring a row that isn't quarantined commits an empty version.
- **Mid-save conflict.** A conflict that lands between `save()`'s check (`rows/edits.py:216`) and `commit_step`'s check under the lock comes back without `conflicts`. TRD §4.3 says "always". The client copes with `?? []`.
- **Huge numbers.** `offset=10**20` or `version=10**20` on `GET /rows` is a 500 rather than a 422.
- **Header with a quoted newline.** `ingest/sniff.py` `header_names` reads one physical line, so `"first\nname",age` gives `first, col_2`.
- **Short cp1252 files.** A 3-line cp1252 file (`Café,€5`) was detected as cp775. Longer files are fine, and the preview can override the encoding.
- **Impossible values matches inside words.** `cleaning/detectors/impossible_values.py:11-12` `NON_NEGATIVE` has no word boundaries, so `average_temp` ("age"), `account_balance` ("count") and `percentage_change` are treated as non-negative quantities.
- **Web.**
  - Preview with CR-only line endings and Skip rows > 0 says "no data rows" (`importPreview.ts`).
  - Error toasts auto-dismiss after 4 s; Brief §4.10 says they stay until dismissed.
  - The badge's hover text appears only on `failed` (App Flow §14).
  - The empty-state pitch uses `text-foreground-2`; Brief §5.1 says `--muted-foreground`.
- **LLM.**
  - The `strip_reasoning` docstring claims to handle an unterminated `<think>`; it doesn't (the TRD doesn't ask for it).
  - `embed` is a TRD role but not in the client's `ROLES`. This only matters once embeddings exist.
- **Doc/code mismatches (Rule 1).**
  - TRD §7.1 step 3 (line 885) still says inference uses `TRY_CAST`, `dateparser` and `SUMMARIZE`. The as-built note further down describes pandas.
  - PRD PROF-1 says the typing step commits "on every path". With nothing to type there is no step; TRD §7.1 documents that, but the PRD doesn't.
  - TRD §7.1 step 1 says the upload is aborted "while streaming". Starlette spools the multipart body before the handler runs. This comes from how Starlette works; I didn't probe it.
- **CSV export formula injection.** `export.csv` writes cells such as `=HYPERLINK(…)` as they are. No doc requires escaping them, so this isn't a mismatch; worth an owner decision.

### Test gaps (no test today)

- **Rows:** large integers, DATE with a time, `nan` and booleans in edits; duplicate cells in one batch; a hand edit staying protected after a later edit is undone; conflicts that land mid-save; huge offset or version; `state_rev` after undo; the live stream skipping events already replayed, and event order.
- **LLM:** non-retryable 4xx failing at once; `OpenAITransport` error classification; the no-`LLM_BASE_URL` path writing no row.
- **Web:** `sse.ts` (dedup, reopen, backoff); `applyStatus` updating a badge; `ImportPreviewDialog`'s `changedOptions` round trip; slide-over keyboard behaviour.
- **CI:** nothing checks that `openapi.json` matches `app.openapi()`.

## Final test run and merge check

- **API.** `uv run pytest` in `api/` at `f9567d9`, with every fix applied: **285 passed, 3 skipped (POSIX-only sandbox tests), 0 failed**, in 3 min 13 s on Windows.
- **Web.** `pnpm test` in `web/`: 36 passed. The web code is unchanged on this branch.
- **Merge.** `git merge-tree --write-tree main HEAD` merges cleanly with `main` at `52cc5eb` (Day 6), with no conflicts.
