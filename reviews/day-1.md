# Day 1 review (Implementation Plan §2 Day 1, rescheduled by §2.0)

Reviewed on 2026-10-25 against `main` at 79f07eb (Day 5), in worktree `claude/review-day1-fab93c`. Specs read: Plan §1, §2.0, Day 1, §3, §4; PRD §7.10, §9; TRD §2, §3.1, §3.2, §3.5, §4.1, §10, §11, §14, §15; Schema §1–§2; UI/UX brief §2.1.

**Token Factory spend for this review: 0 tokens.** No smoke test or live model call was run. The live `/healthz` check only does a `GET /models` probe.

## Verification run

| Check | Result |
|---|---|
| `uv run pytest` in `api/` (before fixes) | **281 passed, 3 skipped, 1 deselected** in 250 s. The 3 skips are the sandbox OS-isolation tests, which need root on Linux. The deselected test is the `live` marker. |
| `uv run pytest` in `api/` (after fixes) | **285 passed, 3 skipped, 1 deselected** in 231 s (the 4 new tests included) |
| `pnpm test` in `web/` | **6 files, 36 tests passed** |
| `pnpm build` in `web/` | passes (`tsc -b` and `vite build`) |
| GitHub Actions | every run fails in about 3 s (billing). The last three were on `main` (runs 40197314574, 40169231759, 40165076787). |
| Live `GET https://sherlock-anw3.onrender.com/healthz` | `200`: `ok: true`, `db.schema_version: 1`, `storage.boots: 27`, `first_boot_at: 2026-10-24T22:21:47.990Z` (unchanged since the D1.3 exit check), `sqlite_lock: true`, `llm.reachable: true`, the three Nemotron roles, empty `embed` |
| Live `GET /`, `GET /datasets/x`, `GET /api/v1/nope` | the web shell (`<title>Sherlock</title>`, hashed assets), the SPA fallback `200`, and the JSON `404 not_found` envelope. No request to `/api/` was made, so no user was created on prod. |
| Local API on `:8101` (temp data dir) | identity, settings, ownership and rate-limit behaviour, below |
| Schema diff (scratch script: doc SQL vs `migrate()`) | **0 differences** across all 26 tables and their indexes (columns, types, `NOT NULL`, defaults, PKs, FKs, CHECK/UNIQUE) |
| Route audit (walk of every `/api/v1` route) | every route with a path ID has `owned_dataset` or `owned(kind)`, except `restore`, which checks inline (correctly) |
| Theme tokens (scratch script: brief §2.1 tables vs `theme.css`) | 0 differences. `--info-soft` is `color-mix(… 12%)`, the same value. |
| Secret scan | the real `LLM_API_KEY` (read from `.env`, not printed) is in **0** commits and **0** tracked files. No key-like strings are tracked, and `.env` is ignored by both `.gitignore` and `.dockerignore`. |
| `NOTEBOOK_PINS` vs `uv.lock` | all 9 pins equal the locked versions |

## Items

| Item | Status | Evidence |
|---|---|---|
| **D1.1** `api/` scaffold (uv, FastAPI, pydantic-settings, `/healthz`) | done | `api/pyproject.toml`, `api/sherlock/config.py` (every TRD §10 variable, defaults checked by `test_settings_defaults_match_trd`), `api/sherlock/main.py:76` `/healthz` with the TRD §11 shape (`tests/test_healthz.py`) |
| D1.1 `web/` (Vite, React 18, TS, Tailwind, shadcn) | done | `web/package.json` (react 18.3.1, vite 8.3.5, tailwindcss 4.3.3, `@tailwindcss/vite`), `web/components.json` (shadcn new-york, plus the `@bklit` registry) |
| D1.1 `docker-compose.yml`, `.env.example`, `README.md`, `FEEDBACK.md`, `LICENSE` | done | All present. Compose mounts `./data:/data` and proxies Vite to `api:8000` (`web/vite.config.ts:8`). `LICENSE` is MIT, © 2026 As Wasti. The README was stale on deploys (finding 6, fixed). |
| D1.1 CI (`pytest`, `pnpm test`) | partial (blocked) | `.github/workflows/ci.yml` runs `uv sync --frozen`, `pytest`, `pnpm install --frozen-lockfile`, `pnpm test` and `pnpm build`. The action tags exist (`checkout@v7`, `setup-uv@v10.3.2`, `setup-node@v7`). It has never gone green because Actions won't start (finding 4). The same commands pass locally. |
| **D1.2** smoke test | done | `scripts/smoke_llm.py`: catalog listing, Nemotron chat models only (`is_nemotron_chat`), a plain completion, three strict JSON-schema cases (Diagnosis, Route, Story), a native tool call, a pandas task run in a subprocess, latency and tokens, and an embedding call per NVIDIA embed model. `FEEDBACK.md:7-31` records both thinking modes for 5 models and the decisions. |
| D1.2 `.env.example` roles | done | `.env.example:15-20`: `MODEL_LARGE/MEDIUM/SMALL` are the Ultra, Super and Nano IDs from TRD §3.5; `MODEL_EMBED=` and `NVIDIA_EMBED_MODELS=` are empty (the catalog has no NVIDIA embedder); `LLM_TOOLS_MODE=native`. `render.yaml` sets the same values. |
| D1.2 no non-NVIDIA model can be configured (Rule 2) | done after fix | `validate_model_roles` runs in the lifespan, so the app, the CLI and the evals all go through it (`cli.py` and `eval/*` use `TestClient(create_app())`). Before the fix, an allowlisted non-NVIDIA embedder passed (finding 2, fixed). The chat roles use a substring rule (finding 8). The client only ever sends `settings.models[role]` (`llm/client.py:226`). |
| **D1.3** Dockerfile, `render.yaml`, `scripts/deploy.sh` | done | `api/Dockerfile` (two stages, uv 0.11.28, users `app`/`sandbox`, `--workers 1`), `api/docker/entrypoint.sh` (chown/chmod `700`, sandboxd, `setpriv`), `render.yaml` (docker, standard plan, 5 GB disk at `/data`, `LLM_API_KEY` `sync: false`), `scripts/deploy.sh` (setup/deploy/check/url, Nebius; never run, because the tenant is suspended, as TRD §11 records) |
| D1.3 `/data` exit check | done | `sherlock/storage_check.py` (`.boots` and a `BEGIN IMMEDIATE` lock test on `.lockcheck.db`), `tests/test_deploy_bits.py`. Live: 27 boots on the same disk, `first_boot_at` unchanged, `sqlite_lock: true`. |
| D1.3 public `/healthz` and web shell | done | see Verification run |
| **D1.4** migration 001 vs every Schema table | done | `api/sherlock/db/migrations/001_initial.sql` is the doc's SQL exactly (0 differences). It hasn't changed since 183fb42, so the deployed DB at `schema_version: 1` is current. Pragmas are WAL, `foreign_keys`, `busy_timeout=5000` (`db/connection.py:11`). |
| D1.4 `sherlock_uid` identity middleware | done | `sherlock/identity.py`. Live: the first `/api` request sets `sherlock_uid` with `HttpOnly; Max-Age=31536000; Path=/; SameSite=Lax`, the same cookie gets no new `Set-Cookie`, `/healthz` sets none, and only the sha256 is stored (`tests/test_identity.py`). Behind HTTPS it adds `Secure` (live in the D1.3 log). |
| D1.4 ownership on every route | done | The route audit covered 48 `/api/v1` routes. Every route with a path ID depends on `owned_dataset` or `owned(kind)`, except `POST /datasets/{id}/restore`, which calls `check_dataset(include_deleted=True)` inline. Live with two cookies: Bob got `404` on Alice's dataset, datacard, rows, `raw.csv`, steps, widgets, delete, restore and job; Alice got `200`. Bob's lists were empty. A guard test now covers real routes (finding 7, fixed). |
| D1.4 rate limiter | done, with a gap | `sherlock/ratelimit.py` (600/60/10 per minute, sliding window, `Retry-After`). Live: 60 mutations went through, then `429` with `retry-after: 46`. The gap is finding 1, and the LLM bucket misses some routes (finding 5). |
| D1.4 `GET /me`, `PUT /me/settings` | done | `sherlock/routers/me.py`. The defaults equal PRD §7.10. Live: a partial PUT merges, and a bad value or unknown key gets `422 invalid` with the request ID. Stored values that are no longer valid fall back to the default (`tests/test_me.py`). |
| **D1.5** spikes as 1-hour checks (§2.0) | partial | `FEEDBACK.md:207-234` records Bklit, react-grid-layout and Glide. Bklit and Glide are marked "passed" with a pass-rule criterion untried (finding 3). |
| **Stretch** light/dark and five accents in `web/src/app/theme.css` | done | Every base, chart and accent value equals brief §2.1, and Aether switches `--info` to brass. `web/src/app/theme.test.ts` checks the values and the 4.5:1 and 3:1 contrast rules. |

**Day 1 exit criteria:** the public `/healthz` works ✓; the model assignments are known ✓; the spike answers are written down (with gaps, finding 3) ✓; CI green ✗ (blocked by billing; the local equivalent passes).

## Findings, most severe first

1. **High. Dropping the cookie resets every per-user limit and budget.** `IdentityMiddleware` makes a new user for every `/api/` request that has no cookie or an unknown one (`identity.py:25-35`). The rate limiter and the token budgets are per user, so a client that never stores the cookie gets fresh buckets and a fresh 2M-token day on every request.
   - Verified locally: 70 `PUT /me/settings` calls without a cookie gave 70 × `200` and 70 new `users` rows. With a cookie, the 61st call got `429`.
   - On the public URL, a script can therefore drive chat (each message up to the 40k message budget) and cleaning on paid Token Factory credit with no ceiling, and grow `users` without bound.
   - Not fixed here, because the fix is a product decision. Hackathon judges may share an office IP, so a per-IP cap could lock them out. Options for TRD §15 and PRD §9:
     - a cap on *new users* per client IP per hour, keyed on the first `X-Forwarded-For` hop (Render sets it), with existing cookies unaffected
     - an app-wide daily token ceiling (`APP_TOKEN_BUDGET`) checked next to the user budget
     - purging users that have no datasets after a day
2. **Medium, fixed in 2c90254. Rule 2: an allowlisted non-NVIDIA embedding model could start.** `validate_model_roles` accepted any `MODEL_EMBED` listed in `NVIDIA_EMBED_MODELS`, and that list is ordinary configuration. `MODEL_EMBED=BAAI/bge-m3` plus `NVIDIA_EMBED_MODELS=BAAI/bge-m3` started the app. The ID must now also pass `is_nvidia_embed`. Covered by `test_validate_embed_allowlist_cannot_admit_a_non_nvidia_model`, and TRD §3.5 records it.
3. **Medium (doc). Two spike records say "passed" while a criterion in their own pass rule was never tried.**
   - **Bklit.** The plan's pass rule is "tooltip, shared hover and theme tokens work". FEEDBACK says the shared hover was "not tried yet (that's D6 hover linking)". The plan also asks for a 5k-point check, which isn't recorded.
   - **Glide.** The pass rule is "editing, range select and range paste work". Range paste is recorded as "not shown". It's fair that cut 5 removes TSV paste, but the record should say "passed except range paste (not needed after cut 5)".

   Left for the owner, because FEEDBACK is the owner's running log and the Day 6 hover linking is the natural place to run the shared-hover check. Suggested: add "(pass rule partly met: …)" to both entries, and record the shared-hover and 5k-point results when D6 hover linking lands.
4. **Medium (process). CI has never gone green.** The workflow is correct, but Actions won't start jobs (billing), so the exit criterion "CI green" is unmet and `autoDeployTrigger: checksPass` never fires. The "deploy by hand" steps are in TRD §11. The local runs above stand in for CI. The sandbox OS-isolation tests (3 skips) only run as root on Linux, so they also didn't run in this review. The README gives the Docker command for them.
5. **Low. Some routes start a model-calling job without counting against the 10/min LLM bucket.**
   - `POST /datasets/{id}/use-as-is` queues a build, whose curation is a `medium` call (`dashboard/builder.py:84`).
   - `POST /jobs/{jid}/retry` can re-run a clean or build job.
   - An upload whose profile job queues the build directly (`jobs/profile.py:53`) does the same.

   TRD §15 says routes that "call the model" add `llm_rate_limit`, and these only do so through a job. The job and user token budgets still apply. Suggested: add `Depends(llm_rate_limit)` to `use-as-is` and `retry`, and say in TRD §15 that job-starting routes count.
6. **Low (doc), fixed in 201be22. The README said pushes redeploy once CI passes,** and called the hosted app "the scaffold". It now has the hand-deploy steps from TRD §11. TRD §10 said secrets come from "the Serverless Endpoint's environment variables" only; it now also says how they're set on Render.
7. **Low (tests), fixed in 7da9f8b. Ownership was only tested on probe routes.** A new route that forgot `owned_dataset`/`owned(kind)` would have passed the suite. `tests/test_ownership_routes.py` walks every real route and fails on one with a path parameter but no ownership dependency. I checked that it catches an injected `/widgets/{wid}/leak`. It lists `restore` as the one inline check, with its reason, and adds a cross-user restore test. TRD §3.1 records it.
8. **Low (Rule 2 hardening). The chat-role check is a substring test.** Any ID containing `nemotron` passes (`llm/models.py:26`), for example `someorg/nemotron-distill`. That's what TRD §3.5 specifies, and every Nemotron ID in the Token Factory catalog starts with `nvidia/`. Requiring that prefix (or `is_nemotron_chat` plus `nvidia/`) would make the rule exact. It changes TRD §3.5's wording, so it's left for the owner.
9. **Info.** Plan §4 and TRD §9 name `scripts/seed_sample.py`, which doesn't exist yet. It's a D9.1 deliverable, so this isn't a Day 1 gap, but the §4 command table lists it as if it runs today.
10. **Info.** `scripts/smoke_llm.py`'s pandas check `exec`s model-written code in a plain subprocess behind a regex check. That's fine for a script the owner runs by hand on a known prompt; it's not the app's sandbox and shouldn't become one.

## Commits on this branch

- `2c90254` Refuse a non-NVIDIA embedding model even when it is allowlisted (code, test, TRD §3.5)
- `7da9f8b` Test that every real route with an ID checks ownership (test, TRD §3.1)
- `201be22` Say in the README how deploys work while CI can't run (README, TRD §10)
- this report

Nothing was pushed or merged. The fixes touch TRD §3.1, §3.5 and §10, which 52cc5eb (Day 6, now on `main`) didn't change. `git merge-tree origin/main HEAD` reports no conflicts, and the new guard test also passes on a checkout of `origin/main` with Day 6's routes (3 passed).
