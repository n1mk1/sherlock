# Sherlock

Sherlock is an AI data analyst for people who own a messy CSV and need answers they can defend. It cleans the data, builds a dashboard, runs honest models and writes story cards; every number comes from executed code, and the whole analysis exports as a runnable Jupyter notebook.

**Hosted URL:** _not deployed yet (first deploy: Oct 25)._

> This README is a skeleton. Its sections follow Implementation Plan §7 and are filled in on Oct 28.

## Screenshot

_To come._

## Try it

_Try with the sample, then upload your own CSV._

## NVIDIA models and Nebius

_A table per role (model ID, what it does, median latency, tokens and cost per sample run), the Nebius services the deployed app uses, and the request and data-flow diagram._

## How trust works

_Sources, chips, verifiers, quarantine._

## Results

_Cleaning benchmark, ML planted-truth tests, grounding test, ask-anything eval, user test and baseline comparison._

## Known limitations

_To come._

## Accessibility

_To come._

## Local setup and run

Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.12 is pinned in `api/.python-version`), Node 24 with pnpm through Corepack (`corepack enable`), a Nebius Token Factory API key, and optionally Docker.

```bash
cp .env.example .env        # then set LLM_BASE_URL and LLM_API_KEY
```

With Docker:

```bash
docker compose up           # API on :8000, web on :5173
```

Without Docker:

```bash
cd api && uv sync && uv run uvicorn sherlock.main:app --reload --port 8000
cd web && pnpm install && pnpm dev
```

## Deploy

_The Nebius Serverless Endpoint commands, recorded in `scripts/deploy.sh` after the first deploy._

## Tests and evals

```bash
cd api && uv run pytest
cd web && pnpm test
```

## License and third-party notices

MIT, see [LICENSE](LICENSE). Third-party licenses go in `THIRD_PARTY.md`.
