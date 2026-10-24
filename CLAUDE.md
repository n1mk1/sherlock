# Sherlock

Sherlock is an AI data analyst, ML engineer and storyteller in one. You drop in a CSV, and it cleans the data, builds a dashboard, runs honest models and writes grounded story cards. It shows its work at every step and exports everything as a runnable Jupyter notebook. It is the entry for the **Nebius x NVIDIA Global AI Hackathon**, in the **Best Apps and Agents** track. Submissions close **2026-10-30, 10:00 PT / 13:00 ET**.

## Where things are

| Read this | For |
|---|---|
| `docs/01-PRD.md` | What must be true: requirement IDs (LOAD-1, CLEAN-3, NB-4…), P0/P1/P2, metrics, release criteria, §12 submission map |
| `docs/02-APP-FLOW.md` | Every screen, state, transition and edge case |
| `docs/03-UIUX-BRIEF.md` | Tokens, components, copy rules, accessibility |
| `docs/04-TRD.md` | Architecture, API contract, data formats, pipelines, config, deployment |
| `docs/05-BACKEND-SCHEMA.md` | SQLite tables, Parquet and file layout, retention |
| `docs/06-IMPLEMENTATION-PLAN.md` | Build order, cut order (§5), test data (§6), submission artifacts (§7), video script (§9) |
| `docs/official_page.md`, `docs/judges_rubric.md` | Hackathon rules and judging summary; the live rules at https://nebiusglobalaihackathon.devpost.com/rules win on any conflict |
| `REVIEW.md` | The Oct 20 adversarial review (its line numbers refer to the Oct 19 docs) |

When docs disagree, the PRD decides *what*, the TRD and schema decide *how*, and the official rules beat both. If you change one doc, update the others that restate the same fact in the same edit.

## Non-negotiables

- **Only NVIDIA models, all through Nebius Token Factory.** Roles: `large` = Nemotron 3 Ultra, `medium` = Nemotron 3 Super, `small` = Nemotron 3 Nano, `embed` = an NVIDIA embedding model or empty. The app refuses to start otherwise (TRD §3.5). Never add another LLM provider.
- **The model never computes numbers.** Every number comes from executed code (SQL, a recipe run or a step). Generated text puts numbers only in chips bound to fact sheets, and the no-digits rule is enforced.
- **Never mutate data in place.** Every change is a step that creates a new version, with lineage and undo. Auto-cleaning never deletes rows; it quarantines them.
- **Stay generic.** Any CSV must work, or fail with a clear message. No dataset-specific code, tuning or prep for Titanic; it is only the "Try with sample" file.
- **Notebook export is never cut.** Every step stores `notebook_code`, and every run writes `repro.py`.
- **Secrets never reach the repo or a notebook.** `.env` stays local, and `.env.example` lists every variable.

## Hackathon rules to respect

- Public GitHub repo with an MIT `LICENSE` at the root, so it shows in the About section. The README has setup and run instructions and says how Nemotron and Token Factory are used, including where Token Factory accelerated the workflow.
- The hosted demo is free to use with no login, and stays up and funded through the judging period (Dec 1–15, 2026) and the winner announcement.
- The video is public on YouTube and **under** 3:00. No copyrighted music, and no third-party trademarks without permission.
- Feedback on Token Factory, AI Cloud and the NVIDIA models goes in `FEEDBACK.md`. Log surprises there as they happen.
- Name only the Nebius services the deployed app actually uses. For example, claim Serverless Jobs only if production runs `JOB_BACKEND=nebius`. Claim Tavily only if a runtime call to it ships.

## Working rules

- Build in vertical slices. Commit each verified slice to `main` and push right away.
- Definition of done: it runs on the sample locally, its test passes, it is reachable from the UI, and it is committed.
- Mock the LLM while building the UI and pipelines (`LLM_MOCK=1`, fixtures in `api/tests/fixtures/llm/`).
- **Doc edits:** fix gaps by adding requirements and content. Don't add timelines or schedules, and don't trim or re-scope features. The only way a P0 may drop is the cut order in plan §5.
- Doc style: plain, direct sentences; requirements get an ID and acceptance criteria.

## Stack (planned; see TRD §2 for the full layout)

- `api/`: Python 3.12, uv, FastAPI (one uvicorn worker), SQLite (WAL) for app state, Parquet plus in-memory DuckDB for data, a pandas sandbox subprocess, scikit-learn and statsmodels, nbformat.
- `web/`: Vite, React 18, TypeScript, Tailwind, shadcn, Bklit charts, Glide Data Grid, react-grid-layout, React Flow, TanStack Query, Zustand.
- Deployment: one image that serves the API and the built web app from one origin, on a Nebius Serverless Endpoint with `/data` mounted. The fallback is a Nebius AI Cloud VM.

## Commands (planned; plan §4)

```bash
cd api && uv sync                      # install backend
cd web && pnpm install                 # install frontend
docker compose up                      # run locally
uv run pytest                          # backend tests
pnpm test                              # frontend tests
uv run sherlock eval corruption        # also: ml, grounding, ask, notebook
uv run python scripts/smoke_llm.py     # check Token Factory models
./scripts/deploy.sh                    # build, push, update the endpoint
```
