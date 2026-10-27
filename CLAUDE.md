# Sherlock

## Why

Sherlock is an AI data analyst for people who own a messy CSV and need answers they can defend. It cleans the data, builds a dashboard, runs honest models and writes story cards. Every number comes from executed code and can be traced to its source, and the whole analysis exports as a runnable Jupyter notebook. It is our entry for the Nebius x NVIDIA Global AI Hackathon (Best Apps and Agents track), so the hackathon rules are hard constraints.

## What

The tech stack is planned in `docs/04-TRD.md` §2. Pinned versions are in TRD §10 `NOTEBOOK_PINS`.

- **LLM:** NVIDIA Nemotron only, through Nebius Token Factory's OpenAI-compatible API. The four roles are `large` (Nemotron 3 Ultra), `medium` (Nemotron 3 Super), `small` (Nemotron 3 Nano) and `embed` (an NVIDIA embedding model, or empty).
- **`api/`:** Python 3.12 managed with uv.
  - App: FastAPI with one uvicorn worker and pydantic-settings.
  - State and data: SQLite in WAL mode for app state; Parquet files queried through in-memory DuckDB; sqlglot to validate SQL.
  - Cleaning: pandas in a sandboxed subprocess, with rapidfuzz, dateparser, ftfy and pandera.
  - ML: scikit-learn (permutation importance and partial dependence; no SHAP, TRD §7.5). statsmodels is pinned for the linear and logistic methods, which cut 4 removed.
  - Notebooks: nbformat and matplotlib.
- **`web/`:** Vite, React 18, TypeScript and pnpm.
  - UI: Tailwind and shadcn/ui, Bklit charts (visx, plus custom visx charts), react-grid-layout, Glide Data Grid, React Flow, TipTap, Motion, sonner, lucide-react.
  - Data and state: TanStack Query, Zustand, Papa Parse, and an API client generated from OpenAPI.
- **Deploy:** one Docker image serves the API and the built web app from one origin. It runs on Render as a web service with a persistent disk at `/data` (`render.yaml`). A Nebius Serverless Endpoint or AI Cloud VM is the documented alternative (`scripts/deploy.sh`).
- **CI:** GitHub Actions.

## How

Read the doc for the area you're touching before you change it:

| Doc | Read it for |
|---|---|
| `docs/01-PRD.md` | Requirements, with IDs, acceptance criteria and P0/P1/P2; §12 maps the submission rules and judging criteria |
| `docs/02-APP-FLOW.md` | Screens, states, transitions, edge cases |
| `docs/03-UIUX-BRIEF.md` | Design tokens, components, copy, accessibility |
| `docs/04-TRD.md` | Architecture, API contract, data formats, pipelines, config, deployment, testing |
| `docs/05-BACKEND-SCHEMA.md` | SQLite tables, file layout, retention |
| `docs/06-IMPLEMENTATION-PLAN.md` | Build order, cut order (§5), test data (§6), submission artifacts (§7), video script (§9) |
| `docs/BACKLOG.md` | What's still open: the Day 10 submission steps, the owner's pending decisions, and every unfixed finding from the Day 1–9 reviews. Check it before fixing or building in an area, and remove a line when you fix it |
| `docs/LOG.md`, `docs/USER-TESTS.md` | The build log (done, not done, decisions, day by day); the user-test and baseline protocols and results |
| `docs/official_page.md`, `docs/judges_rubric.md` | Hackathon rules and judging; the live rules at https://nebiusglobalaihackathon.devpost.com/rules win any conflict |

When docs disagree, the PRD decides *what* and the TRD and schema decide *how*.

Verify your work (plan §4):

```bash
uv run pytest            # in api/
pnpm test                # in web/
pnpm e2e                 # in web/: builds the app, then the Playwright end-to-end flow
uv run sherlock eval ask # also: corruption, ml, grounding, notebook, web (offline; --live with TAVILY_API_KEY)
```

## Rules

1. **Documentation and implementation match at all times.**
   - Any change to behaviour, the API, the schema, config, UI or dependencies updates the doc that specifies it, in the same commit.
   - If code has to differ from a doc, change the doc first or ask.
   - Never leave a doc describing something the code doesn't do, or code doing something no doc describes.
2. **No model outside NVIDIA on Token Factory.** The model never computes a number. Numbers come from code, and generated text shows them only as chips bound to fact sheets.
3. **Data is never changed in place.** Every change is a step that creates a new version and can be undone. Cleaning quarantines rows; it never deletes them.
4. **Keep it generic.** No code, tuning or prep that is specific to one dataset. Titanic is only the sample file.
5. **Keep docs lean; never cut scope.**
   - Fix gaps by adding requirements. Don't add timelines or trim scope; a P0 drops only through the cut order in plan §5.
   - Specs describe what the code does now, stated once, in the doc that owns it; other docs cite the section (`TRD §7.2`).
   - History (commit hashes, "as built" stories, which day fixed what) goes in `docs/LOG.md` and the commit message, never in a spec.
   - Keep section numbers and requirement IDs stable, because code comments cite them.
6. **Commit each verified slice to `main` and push as much as possible** Secrets stay in `.env`, never in the repo or an exported notebook.
