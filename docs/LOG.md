# Sherlock · Build log

Three lines per day: done, not done, and the decision for tomorrow (Implementation Plan §8).

## 2026-10-24 (Fri)

- **Done:**
  - Replan with all nine cuts (plan §2.0).
  - D1.1 scaffold: `api/`, `web/`, compose, CI, README, LICENSE, FEEDBACK.
  - D1.2 Nemotron smoke test: Ultra, Super and Nano pass 6/6 with reasoning on; `LLM_TOOLS_MODE=native`; no NVIDIA embedding model, so `embed` is empty.
  - D1.4: migration 001, cookie identity, ownership, rate limits, `/me`.
  - The public repo is `n1mk1/sherlock`; CI is green.
- **Not done:**
  - D1.3 Nebius deploy, moved to Oct 25 by the replan.
  - The Day 1 stretch: theme tokens in `web/src/app/theme.css`.
  - The Day 0 check of the Nebius credit balance (not recorded yet).
  - The owner's `CLAUDE.md` rule 6 edit is still uncommitted.
- **Decision for tomorrow:**
  - Open with the hello-world deploy: the image with the API and web build, a registry, and the Serverless Endpoint with `/data`. It's timeboxed to 3 h, and the AI Cloud VM fallback is taken the same day if `/data` persistence or SQLite locking fails.
  - Then D2.1–D2.8 backend: ingest, profile, steps, sandbox, jobs/SSE, rows API, the `llm/` client, the typing step.
  - Prerequisites from the owner: Docker Desktop running, the Nebius CLI installed and logged in, and a registry Nebius can pull from.

### 2026-10-24 (evening update)

- **Done:**
  - Theme tokens (the Day 1 stretch).
  - The production image (verified locally).
  - The `CLAUDE.md` rule 6 edit, committed.
  - Ubuntu WSL with the Nebius CLI. The Nebius AI Cloud tenant turned out to be new and suspended, so on the owner's decision hosting moved to Render (`render.yaml`, PRD §9).
  - D1.3 on Render: https://sherlock-anw3.onrender.com is live, and the `/data` exit check passed (boots 1 → 2, SQLite lock works, cookie user persists).
- **Not done:**
  - The Nebius AI Cloud credit balance: there's no active AI Cloud tenant. Token Factory, which serves all inference, shows 0.94 of the 1.00 starter credit left plus a $25 top-up (recorded in `FEEDBACK.md`).
  - The Nebius alternative is scripted but has never run.
- **Decision for tomorrow:**
  - Start the D2.1–D2.8 backend directly; the deploy is no longer first.
  - Move the Render plan from Starter to Standard before the sandbox lands (D2.4 needs about 2 GB).
