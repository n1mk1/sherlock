# Day 9 review: ship

Reviewed 2026-10-25 on branch `claude/review-day9-169efc`, cut from `main` at e84ccc0. The scope is Implementation Plan §2 "Day 9" (D9.1–D9.5 and the exit check), the submission artifacts in plan §7, and hackathon compliance against the live Devpost rules. "Done" means plan §1: it runs on the Titanic sample, its test passes, the UI reaches it, and it's committed. Findings already reported for Days 5–7 on their unmerged branches aren't repeated. Day 8's features (Flow, chat, evals, jobs) belong to the sibling review, so they appear here only where the judge path uses them.

**Verdict.** The Day 9 claims hold up in a fresh browser on the public URL:

- "Try with sample" opens a cloned, fully built dashboard in about a second.
- A question gets a sourced answer in 15 s.
- An edit asked for in chat is approved and saved as v5, and the cascade re-tells only the affected cards (28 s).
- Two cards placed on Flow get a synthesis in 18 s.
- A non-Titanic CSV uploads and builds its dashboard in 21 s, with every story written 30 s later.
- At phone width there's no horizontal scroll.
- `scripts/live_check.py` passes 11 of 11.
- The example notebook rebuilds v4 exactly in a fresh venv.
- The served web bundle is byte-identical to a fresh build of `main`.

**The biggest gap is not in the code.** The GitHub repository is still **private** (C1). The rules need it public, with the license showing, before Oct 30, 10:00 PT.

The second gap is the new-user cap. From this machine's network, `/me` answered `429 Too many new visitors` four times in 25 minutes, but this session made only about 20 users (H1). The cause isn't known yet.

This review fixed five things, each in its own commit:

1. The sample's canvas IDs were shared between clones, and the public seed named the machine that built it.
2. Every page load requested `/datasets//widgets`.
3. The empty chat thread suggested Titanic's columns on every file.
4. Two README claims didn't match the app, and plan §7 named the example notebook `v7` (it's `v4`).
5. The video length: the docs said ≤ 3:00, but the live rules say *less than* three minutes.

## Commits on this branch

| Commit | What |
|---|---|
| d3d8c27 | Remap the sample's canvas node and edge IDs and drop the seed's hostname (F1, F2): `sample_seed.py`, the shipped `rows.json`, a test, TRD §4.2 |
| bf314bd | README: Reduce motion follows the OS (the in-app switch is cut 1); the notebook's assertion checks rows, columns and types. Plan §7 names `titanic3-v4.ipynb` (F8, F9) |
| 53c7743 | Plan Day 10, plan §9 and PRD §12.2: the live rules want the video under 3:00, so aim for 2:55 (C4) |
| a2b9931 | `useWidgets` waits for a dataset ID, so landing pages stop sending `GET /api/v1/datasets//widgets` (F3), with a test |
| a0c648f | The empty chat thread's hint names no sample column (F4, Rule 4), with a test; UI/UX brief §4.8 |

## Evidence

| Check | Result |
|---|---|
| `uv run pytest` (api, after the fixes) | **359 passed, 3 skipped**, 1 deselected, in 12 min 21 s |
| `pnpm test` (web) | 10 files, 58 tests passed before the fixes. The two new tests pass, and `tsc -b` is clean. The widgets test fails without its fix. |
| `tests/test_sample_seed.py` | 2 passed. The new assertion (no seed ID survives into the clone, in any table) fails on `main`: 4 IDs survive (`nd_…`, 3 × `ed_…`). |
| `/healthz` (live, 21:40 UTC) | `ok`, `schema_version` 1 (`main` has one migration, `001_initial.sql`), `/data` writable, SQLite lock ok, LLM reachable, boots 39. The models are `large` `nvidia/Nemotron-3-Ultra-550b-a55b`, `medium` `nvidia/nemotron-3-super-120b-a12b`, `small` `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` and `embed` empty, all equal to `render.yaml` and `.env.example`. |
| Deployed commit vs `main` | The served `assets/index-BzGkqNTD.js` and `index-bJAGl8Ni.css` are the files a fresh `pnpm build` of `main` (e84ccc0) produces, so the web app is current. e84ccc0 changed only docs, `docs/architecture.png` and `scripts/architecture.py`, so a deploy of 0a62263 or later serves `main`'s code. The API's commit can't be read without Render access, because `/healthz` doesn't report one (F13). Render wasn't touched. |
| `scripts/live_check.py` (once, 21:48 UTC) | **11 of 11.** Sample ready in 0.2 s at v4 (10 widgets, 12 cards, 4 canvas nodes). A second client gets 404 for the dataset, widgets, canvas and a card, and an empty library. The 11th model request in a minute gets 429, and another user isn't limited. A sourced answer in 15.6 s. The fare edit saved as v5, and the cascade changed 4 of 12 cards. Two earlier attempts stopped at the second client's `/me` with 429 (H1), before any model call. |
| Example notebook `docs/examples/titanic3-v4.ipynb` | Ran top to bottom in a fresh `uv venv --seed` with only `nbclient` and `ipykernel`; its own `%pip` cell installed the pins. 29 code cells, 117 s, no errors. The final `df` equals the seed's `v4.parquet` (`assert_frame_equal` with dtypes, 1,309 × 16). In a venv without pip the `%pip` cell installs nothing and the notebook fails at `import duckdb` (F14). |
| Secrets (Rule 6) | Clean in all 117 commits of history (key patterns: `eyJ…`, `sk-…`, `tvly-…`, `ghp_…`, assigned `*_API_KEY` values). The seed and the example notebook have no keys, paths or names. The seed did hold the builder's hostname (F2, fixed). |
| Rule 2 grep | No non-NVIDIA model ID or provider outside tests, which use them to check rejection. `api/uv.lock` has no other LLM SDK besides `openai`, which is pointed at Token Factory. One latent hole: F10. |
| `scripts/architecture.py` | Re-rendered to a scratch file, it's byte-identical to `docs/architecture.png`. |
| `THIRD_PARTY.md` vs the lockfiles | Every web `dependencies` entry and every API runtime package (69, plus `uvicorn[standard]`'s four extras) is listed at its locked version and with its license. `httpx2-jsfetch` is left out correctly, since it's Emscripten-only. Bundled transitive web packages aren't listed (F11). No Bklit Studio anywhere in `web/src`, `package.json` or `api/sherlock`. |

### Exit check, live, from fresh browser profiles

Headless Chromium (Playwright from `web/`) ran in new contexts against https://sherlock-anw3.onrender.com, timing each step. It took three passes, all on 2026-10-25:

- **Pass 1, 21:49.** Run with a script bug of mine: it waited on a widget's "How do you know?" instead of the answer's, and the explain drawer it opened blocked the next three steps. Its timings for the landing page, the upload and phone width are valid.
- **Pass 2, 21:56.** Fixed the waits. The ask passed, but no Approve appeared for the edit (F5).
- **Pass 3, 22:02.** Edit → cascade → Flow, with screenshots on failure. Everything passed.

Screenshots are in `reviews/day-9/`, and the timings are in `timings*.json` there.

| Step | Time | Result | Screenshot |
|---|---|---|---|
| Open the URL | 2.3 s (4.1 s cold) | Library with Try with sample | `01-landing.jpg`, `p2-01-landing.jpg` |
| Try with sample → dashboard with stories | **1.2 s** to the first story card (API 0.2 s) | v4, 3 steps, 10 widgets, the stories panel filled | `02-dashboard.jpg`, `p2-02-dashboard.jpg` |
| Ask "average fare by class" | **14.9 s** | "First class averages 87.51, second class averages 21.18, and third class averages 13.30", as chips, plus a table and "How do you know?" with the query and the reading `class → pclass, fare → fare` | `03-answer.jpg`, `04-answer-sql.jpg` |
| Edit a cell (CSV tab, "set the fare of row 1 to 100") | proposal **6.2 s**, Approve → saved **1.9 s** | The proposal (211.3375 → 100) is approved, and a v5 step "Edited 1 cell by hand" shows with Undo in Changes | `05-proposal.jpg`, `06-saved.jpg` |
| A card updates | **28.0 s** | Toast "v5: 3 widgets re-queried, 2 stories updated". The API shows 5 of 12 cards changed (the two fare cards, the overview, the synthesis and the analysis). The Average fare card is marked "changed", and the synthesis says "sources changed". | `07-stories-updated.jpg` |
| Build a Flow story | place two cards, then synthesis in **18.2 s** | 4 → 7 nodes; a synthesis card with chips and "summarized in" edges | `08-flow-before.jpg`, `08-flow-placed.jpg`, `09-flow-synthesis.jpg` |
| Upload a non-Titanic CSV (`sales_dated.csv`) | **21.1 s** to the dashboard, all jobs done **29.8 s** later | Import preview (8 columns, about 5,000 rows), offer, Use as is, then v2 with revenue, units, average price, return rate, a scatter and more | `10-import-preview.jpg` to `13-sales-dashboard-final.jpg` |
| Phone width (390 × 844) | open 4.7 s, CSV and Flow 5.2 s | No horizontal overflow on Dashboard, CSV or Flow. The chat bar is at the bottom, the canvas and minimap work, and KPI titles are cut to "Avera…" (F15). | `20-` to `24-phone-*.jpg` |

## Status by item

| Item | Status | Evidence |
|---|---|---|
| **D9.1** `scripts/seed_sample.py` and the seed; `POST /datasets/sample` clones it with ID remapping; two users independent | **done** (two fixes here) | `scripts/seed_sample.py`, `api/sherlock/sample_seed.py`, `routers/datasets.py:129-160`, `tests/test_sample_seed.py`. Datasets, versions, steps, lineage, issues, runs (with `artifact_dir`, `repro_path` and the run folder's paths and text files), widgets, layouts, fact sheets, relations, cards (chip keys, `source_card_ids`), the canvas's card IDs, jobs and job events were all remapped. **Not remapped:** the canvas's synthesis node `nd_…` and its three edges `ed_…`, which live only in the canvas JSON, so every clone shared them (F1, fixed). Isolation: Alice's edit leaves Bob's copy at v4, and each gets 404 for the other's (test, and live in `live_check`). Seed contents: no secrets or paths, but `jobs.owner_pid` held the builder's hostname (F2, fixed). |
| **D9.2** Final image deployed; the five-file set on the public URL; notebooks executed; the example notebook committed | **done** (the API commit is unverifiable, F13) | `/healthz` and the bundle match `main` (above). The five-file `--files all` run wasn't repeated, to keep live traffic to one pass; plan D9.2 records 31 of 31, and the judge path uploaded `sales_dated.csv` live. The example notebook rebuilds v4 exactly. The plan says v4 where it once said v7: D9.2's as-built note explains why, and §7 now says so too (F9, fixed). |
| **D9.3** README in the §7 order; numbers traceable; `docs/USER-TESTS.md`; architecture image | **partial** | Order: URL → screenshot → try it → NVIDIA and Nebius (table per role, Nebius services, diagram) → trust → results → limitations → accessibility → setup → deploy → tests → license. That matches §7. Numbers: see "README numbers" below. Ultra's cost isn't stated ("on the account's console"), and `llm_calls` purposes aren't named (F6). `USER-TESTS.md` has both protocols and the measured Sherlock half of the baseline; the three cold-start sessions and the by-hand half are empty, which is honest but still missing (C6). |
| **D9.4** `THIRD_PARTY.md`; Bklit Studio absent; sample license | **done** (F11 open) | Versions and licenses match the lockfiles. Bklit UI is MIT, Studio is absent, and OpenML lists the sample as Public. |
| **D9.5** Rate limits, budgets, isolation on the public URL | **done** (H1 open) | `live_check.py`: 429 on the 11th model request, another user unaffected, isolation 404s. Budgets are config (`APP_TOKEN_BUDGET` 10M a day, per-user and per-job) and weren't exhausted, as the plan says. The new-user cap misfired for this network (H1). |
| **Exit**: Try with sample → dashboard in seconds → ask → edit a cell → card updates → Flow story → upload own CSV | **done** | Every step passed live (table above). One unexplained miss: F5. |

### README numbers, traced

| Claim | Source |
|---|---|
| Cleaning 97.2% / 94.5% / 74.0%, harm 0.00%, row loss 0.0% | `FEEDBACK.md` lines 67-72 (rerun of 2026-10-24) |
| ML planted truth 3 of 3 | `docs/LOG.md`, TRD |
| Grounding 36 of 36 + 33 of 33 chips | TRD §8.1 (69 of 69 in plan D8.4) |
| Ask 49 of 50 (44 first), 0 unsourced, median 8.7 s | TRD §8.1, plan D8.4 |
| Live checks 31 of 31; `wide_messy` 685 s | plan D9.2 as built |
| Seed build 151 s, 68k tokens, per-role calls and tokens | TRD §4.2 as built |
| Super cost ≈ $0.02 | 11,899 × $0.30/M + 20,919 × $0.90/M = $0.0224 ✓ (the rate is in `docs/LOG.md`) |
| Median latencies (diagnose 2.8 s, propose 6.0 s, critic 3.8 s, curate 9 s, route 1.4 s, chat SQL 4–7 s, compose 6–7 s) | **Not in any committed log.** They match the owner's local `api/data/sherlock.db` `llm_calls` (diagnose 2.8 s over 33 calls, propose 6.0 s over 23, critic 3.8 s over 20, curate 9.3 s, route 1.4 s, sql 4.1 s, compose 6.6 s), so they're real, but a judge can't trace them (F6) |
| Notebooks "78–116 s each"; "about 1,500 tokens per chat message" | **Not found** in `FEEDBACK.md`, `LOG.md`, TRD or the plan (F6) |
| Baseline "about 31 s, 4 steps, 3 of 3" | `docs/USER-TESTS.md` |
| "Playwright … 11 s" | plan D8.6 |
| Re-run here (no model calls) | `scripts/architecture.py` (identical image), the example notebook (v4 exact), `live_check.py` (11/11), pytest and vitest |

## Hackathon compliance checklist

The live rules (https://nebiusglobalaihackathon.devpost.com/rules, read 2026-10-25) agree with `docs/official_page.md` on the dates, tracks, stages and criteria. They differ on one point: the video "should be less than three (3) minutes" (C4).

| # | Requirement (live rules) | Status | Evidence / gap |
|---|---|---|---|
| C1 | Public repo on GitHub/GitLab/Bitbucket; open-source license file detectable at the top of the repo page (About) | **GAP (blocker)** | `gh repo view`: `n1mk1/sherlock` has **visibility PRIVATE**. Its license is detected as MIT (`LICENSE` at the root, "Copyright (c) 2026 As Wasti"). Make it public before submitting; history is clean by pattern scan, but run the planned secret scan first. The About section's website field is empty, so add the hosted URL. |
| C2 | Runs on Token Factory or AI Cloud: a runtime call to the Token Factory inference API | ✓ | Every role calls `https://api.tokenfactory.nebius.com/v1/` (`render.yaml`), and live answers and syntheses were produced during this review. |
| C3 | Uses at least one NVIDIA open-source model; track = Best Apps and Agents (Ultra for reasoning, Nano/Super for fast calls) | ✓ | `/healthz` lists three Nemotron models with no embedding model. Startup refuses non-Nemotron IDs (`llm/models.py:22-36`). The role split matches the track text (Ultra cleans, Super writes, Nano routes). |
| C4 | Video: public YouTube, **less than three minutes**, shows the project working, no third-party copyrighted music | **open (Day 10)** + docs fixed | The plan's script ended at 3:00 exactly, so it now says finish by 2:55 (53c7743). Not recorded yet. |
| C5 | URL to a working demo, free and unrestricted for testing until the Judging Period ends (Dec 15, 2026, 12:00 PT) | ✓ now / risk | Live and working. PRD §9 keeps Render's paid plan and Token Factory credit through judging. **Risks:** the $25 balance must last to Dec 15, and H1. Datasets expire after 7 days, but judges make their own. |
| C6 | Text description of features and functionality | open (Day 10) | Plan §7 has the section order. Its "demonstrated result" needs the user-test numbers, and the cold-start sessions and by-hand baseline aren't run (`USER-TESTS.md` tables are empty). That evidence is what Potential Impact asks for. |
| C7 | README with setup instructions and clear guidance for running | ✓ | `README.md` "Local setup and run" (`.env.example`, smoke test, `docker compose up`, without Docker), Deploy, Tests. |
| C8 | README highlights how Nemotron / NVIDIA models are used, **where Token Factory accelerated your workflow**, and other Nebius tools | ✓ / small gap | The model table per role, "Why these sizes", cost, and "Nebius services used: Token Factory only". Nothing says in so many words where Token Factory *accelerated the workflow* (one OpenAI-compatible endpoint for all three sizes, strict JSON schema). Worth one sentence (F7). |
| C9 | Repo contains all source, assets and instructions to be functional | ✓ | Source, samples, the seed, the Dockerfile, `render.yaml` and `.env.example`. Checked by this review's fresh install (`uv sync`, `pnpm install --frozen-lockfile`, build and tests). |
| C10 | Identify the track | open (Day 10) | Best Apps and Agents (PRD §12.2). |
| C11 | Feedback on Token Factory, AI Cloud and NVIDIA models (Most Valuable Feedback: completeness, viability, impact) | ✓ draft | `FEEDBACK.md` has sections for Token Factory, each Nemotron model, embeddings, Nebius hosting (the suspended tenant) and tooling, each with problems and suggestions. Finalized on Day 10. |
| C12 | New project, or significant updates explained | ✓ | Started 2026-10-24, inside the period (Aug 26 – Oct 30). |
| C13 | Third-party integrations authorized; open source used per its licenses | ✓ | `THIRD_PARTY.md`. The Titanic data is listed as Public by OpenML. F11 is the notices gap. |
| C14 | English | ✓ | |
| C15 | Deadline | — | **Fri Oct 30, 2026, 10:00 am PT (1:00 pm EDT)**, which the PRD and plan state correctly. Judging Dec 1–15; winners around Jan 11, 2027. |
| C16 | Bonus prizes | ✓ by design | Tavily: `TAVILY_API_KEY` exists in config but nothing calls Tavily, so don't claim it (PRD §12.4). City award only with an IRL event. Feedback prize: C11. A project can win only one overall or track award plus one bonus. |
| C17 | Stage one (pass/fail): fits the track, uses the required APIs | ✓ | A working analyst agent on Token Factory, end to end (exit check above). |
| C18 | Stage two: Technological Implementation, Design, Potential Impact, Quality of the Idea (25% each; ties broken in that order) | ✓ evidence exists | Tech: model roles with measured latency and tokens, verifiers, sandbox, evals, the architecture image. Design: sample in about 1 s, a complete product, phone width works. Impact: the benchmark and the baseline half; the cold-start test is missing (C6). Idea: chip-only narration, quarantine, honest ML, notebook export. |

## Findings, ranked

### Critical

- **C1. The repository is private.** See the checklist above. It's a stage-one blocker if left private: judges must reach a public repo with the license visible. Owner action. Not done here, since this review doesn't change GitHub settings.

### High

- **H1. The new-user cap rejected this network repeatedly, for a reason not yet known.**
  - What happened: between 21:40 and 22:02 UTC, `GET /api/v1/me` from this machine answered `429` "Too many new visitors from your network" four times (21:40 and 21:41 in `live_check`, 21:56 and 22:02 in the browser passes). That's `NEW_USERS_PER_IP_HOUR` = 300, a sliding hour (`identity.py:44-68`). Two `live_check.py` runs died on it, and the browser passes recovered after a 429 on `/me`.
  - Why it's suspect: this session created about 20 users in that time (three `live_check` attempts, three browser passes, five `curl`s). The Day 8 sibling was asked whether it was creating users on the live site and hadn't answered by the end of this review.
  - Two possible causes:
    - Something else on this network is creating about 300 users an hour.
    - `client_ip` (the X-Forwarded-For entry before the last trusted hop, `TRUSTED_PROXY_HOPS` = 1) now picks a shared address. The responses carry `Server: cloudflare` and `CF-RAY`, so another proxy hop would make every visitor behind one edge share a bucket.
  - Why it matters: if it's the second, a judge's first visit can fail.
  - Check: Render's logs have `new user: ip <hash>, N forwarded hop(s)` for each new user. Many different hashes means the key is fine; one hash for everyone, or a hop count of 3, means it isn't. Not checked here, because the Render workspace wasn't selected and choosing one needs the owner.
  - Related: F3 removed one stray request per page load. A request sent before the identity cookie is set could create a user of its own, which would inflate the count; not verified.

### Medium

- **F1. Clones shared the canvas's node and edge IDs. Fixed (d3d8c27).** `_remapper` only collected IDs from `id` and `*_id` columns. The seed's synthesis node and its three edges exist only inside `canvases.canvas_json`, so every user's canvas had the same four IDs. That was harmless today, since canvases are per dataset, but it contradicted TRD §4.2 and §6 ("remaps every ID … the canvas JSON"). Every ID-shaped string is now remapped, and the shipped-seed test checks that none survive.
- **F5. In pass 2, an edit asked right after a question got no proposal within 90 s. Not reproduced.**
  - Pass 2 asked "average fare by class", switched to CSV and asked "set the fare of row 1 to 100" in the same thread. No Approve button appeared within 90 s, and Flow then failed to place cards within 30 s.
  - Pass 3 asked the same edit in a fresh thread. The proposal arrived in 6.2 s, and Flow worked.
  - The difference is the earlier answer in focus. A plausible cause is that "row 1" was read against the previous answer's table (class 1). The failure screenshot wasn't kept, so this is unconfirmed.
  - It's chat routing, so it's Day 8's area. Worth one scripted repro: a question, then an edit, in one thread.
- **F6. Some README numbers can't be traced, and two D9.3 items are thin.**
  - The per-role median latencies are real (they match `llm_calls` in the owner's local database), but no committed file has them. Put the query and its output in `FEEDBACK.md` or TRD §14.
  - "78–116 s each" for the notebooks and "about 1,500 tokens per chat message" have no source.
  - Plan D9.3 asks for cost per role, but Ultra's says "on the account's console". Plan D9.3 also asks for the `llm_calls` purposes (diagnose, propose, critic, curate, narrate, overview, synthesis, route, sql, compose, edits, widget, summary), which aren't named.

### Low

- **F2. The public seed named the builder's machine. Fixed (d3d8c27).** `jobs.owner_pid` is `<hostname>:<pid>:<ulid>`; the six seed jobs held `DESKTOP-F22GLLG:41376:…`. `snapshot` now blanks it, and the shipped `rows.json` is scrubbed (only that field changed).
- **F3. Every page off a dataset route requested `GET /api/v1/datasets//widgets` (404). Fixed (a2b9931).** `StoriesPanel` calls `useWidgets(datasetId ?? "")`. Seen in every live pass. `useWidgets` now waits for an ID, as `useCards` does.
- **F4. The empty chat thread suggested Titanic's columns on every file (Rule 4). Fixed (a0c648f).** On `sales_dated.csv` it said "average fare by class" and "add a chart of fare by port" (`12-sales-dashboard.jpg`). It now uses placeholders. No doc described the hint, so UI/UX §4.8 does now.
- **F7. The README doesn't say where Token Factory accelerated the work.** The live rules ask for it in so many words (C8). One sentence in "NVIDIA models and Nebius" would cover it, for example: one OpenAI-compatible endpoint for three sizes, and strict JSON schema with one repair round.
- **F8. Two README claims went beyond the app. Fixed (bf314bd).**
  - "A Reduce motion setting": the settings dialog has four settings (cut 1), and motion follows the OS.
  - "Asserts it matches": the assertion cell checks row count, columns and types, while the tests compare values.
- **F9. Plan §7 still named `titanic3-v7.ipynb`. Fixed (bf314bd)** with an added note naming v4.
- **F10. `is_nvidia_embed` admits non-NVIDIA IDs (Rule 2, latent).**
  - Where: `llm/models.py:47-49`. It needs only "embed" plus any of "nvidia", "nv-" or "nemotron" anywhere in the ID, so `someorg/conv-embed-v1` ("nv-" inside "conv-") or `someorg/nvidia-embed-distill` pass.
  - Both startup and `pick_roles` rely on it. The allowlist is config, which TRD §3.5 says can't vouch on its own.
  - Embeddings are off in production, so nothing is affected today.
  - Fix: require the `nvidia/` publisher prefix, as `is_nemotron_chat` does since the Day 1 review. Not changed here: TRD §3.5 documents the current rule, and the catalog has no NVIDIA embedding model to check the prefix against.
- **F11. `THIRD_PARTY.md` lists only the web app's direct dependencies.** The built bundle also ships transitive packages with notice-keeping licenses: the d3 modules (ISC), `d3-ease` (BSD-3-Clause), `robust-predicates` (Unlicense), `lucide-react` (ISC, listed) and `tslib` (0BSD). `corepack pnpm licenses list --prod` gives the full set; all of them are permissive.
- **F12. `live_check.py --files all` says it checks that each notebook "rebuilds the version", but it only executes it.** The check therefore rests on the notebook's own assertion cell (rows, columns, types). `sherlock eval notebook` does compare values.
- **F13. `/healthz` doesn't report the build's commit**, so "the deployed commit matches `main`" can only be checked through the web bundle's hash or the Render dashboard. A `GIT_COMMIT` build argument echoed by `/healthz` would make it one request.
- **F14. The notebook's `%pip` cell needs pip in the kernel's environment.** In a `uv venv` without `--seed` it installs nothing silently, then fails at `import duckdb`. A judge with a normal venv or Jupyter has pip, so a markdown line above the cell is enough.
- **F15. Phone width: KPI titles are cut to a few letters** ("Total …", "Surviv…", "Avera…"), and the chat thread covers most of the Flow canvas after "Make sense of this" (also on desktop, `09-flow-synthesis.jpg`).
- **F16. One live chat answer had no prose.** `live_check`'s "average fare by class" came back as just the table, with the message text "Here is the result (3 rows)." (`agent/loop.py:426`). The same question in the browser 8 minutes later had chips and prose. This is run-to-run variance in compose (Day 4 F8 covers repairs). It's still sourced.

## Environment notes for whoever runs this next

- **Spend.** Token Factory use from this review on the live site:
  - one `live_check` (an answer and one cascade);
  - pass 1: an answer, an unapproved edit proposal, and `sales_dated.csv` built with "Use as is" (curation, about ten stories, the overview);
  - pass 2: an answer and one edit request;
  - pass 3: an edit, a cascade and one synthesis.
  - Estimated at about 40 calls; not measured, since the live `llm_calls` table isn't reachable from here.
  - The five-file `--files all` run was **not** repeated.
- **Users created on the live site:** about 20 anonymous users, each with a cloned sample, plus one `sales_dated.csv`. They expire in 7 days.
- **Notebook check:** use `uv venv --seed` so the `%pip` cell can install the pins.
- **Driving the live UI:** `waitForLoadState("networkidle")` never settles, because the SSE stream stays open. Scope "How do you know?" to `getByRole("log", { name: "Chat with Sherlock" })`, because every widget has one too.
