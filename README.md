# Sherlock

Sherlock is an AI data analyst for people who own a messy CSV and need answers they can defend. It cleans the data, builds a dashboard, runs honest models and writes story cards; every number comes from executed code, and the whole analysis exports as a runnable Jupyter notebook.

**Hosted URL:** https://sherlock-anw3.onrender.com (Render, Frankfurt; currently the scaffold, with `/healthz` live)

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
uv run --project api python scripts/smoke_llm.py   # tests the Nemotron models, prints the MODEL_* lines
```

The API refuses to start until `MODEL_LARGE`, `MODEL_MEDIUM` and `MODEL_SMALL` are Nemotron IDs. Copy the lines the smoke test prints into `.env`.

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

Sherlock is hosted on **Render**: one Docker web service built from `api/Dockerfile` with a persistent disk at `/data`, defined in [`render.yaml`](render.yaml). Every model call still goes to Nemotron on Nebius Token Factory.

1. In the Render dashboard, choose **New → Blueprint** and pick this repository.
2. When asked, enter `LLM_API_KEY`. It's `sync: false`, so it never lives in the repo.
3. Apply. Render builds the image, attaches the disk and deploys.

Later pushes to `main` that touch `api/`, `web/` or `render.yaml` redeploy once CI passes.

### Nebius alternative

The same image runs as one container on a CPU-only Nebius Serverless Endpoint (`cpu-d3`, `4vcpu-16gb`) with a Nebius shared filesystem mounted at `/data`. There, the Token Factory key is stored in a Nebius secret (SecretStash) instead of plain endpoint settings. This needs an active Nebius AI Cloud tenant with billing or credits.

Requirements: bash, Docker, `jq`, `curl` and the [Nebius CLI](https://docs.nebius.com/cli/install) with a profile for the project. On Windows, use WSL (Ubuntu) with Docker Desktop's WSL integration.

```bash
./scripts/deploy.sh setup   # once: registry, /data filesystem, secret, image, endpoint
./scripts/deploy.sh         # redeploy: build, push the same tag, restart (the URL stays the same)
./scripts/deploy.sh check   # restart and confirm /data and the cookie user survive it
```

Build and run the image locally:

```bash
docker build -f api/Dockerfile -t sherlock .
docker run -p 8080:8080 --env-file .env -e DATA_DIR=/data -e DATABASE_URL=sqlite:////data/sherlock.db -v sherlock-data:/data sherlock
```

## Tests and evals

```bash
cd api && uv run pytest
cd web && pnpm test
```

The sandbox's OS-isolation test (workers run as the `sandbox` user and can't read protected files) needs root, so CI skips it. Run the whole API suite as root on Linux with:

```bash
docker run --rm -v "$PWD:/src:ro" -e UV_PROJECT_ENVIRONMENT=/venv ghcr.io/astral-sh/uv:python3.12-bookworm-slim sh -c 'useradd --system sandbox && cp -r /src /work && cd /work/api && rm -rf .venv && uv sync --frozen -q && chmod -R a+rX /venv /work && uv run pytest -q'
```

## License and third-party notices

MIT, see [LICENSE](LICENSE). Third-party licenses go in `THIRD_PARTY.md`.
