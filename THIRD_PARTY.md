# Third-party notices

Sherlock is MIT-licensed ([LICENSE](LICENSE)). This file lists what it is built from and under which
licenses, as they ship in the Docker image. The versions are the locked ones (`api/uv.lock`,
`web/pnpm-lock.yaml`); the licenses were read from each package's own metadata on 2026-10-25.
Development-only tools (pytest, Vitest, Playwright, TypeScript and the like) are not shipped and are
not listed.

## Code copied into this repository

| What | Where | License |
|---|---|---|
| Bklit UI chart components (bar, line, area, pie and their parts), copied through the `@bklit` shadcn registry and edited (TRD §2) | `web/src/components/charts/` | MIT, Copyright (c) 2026 uixmat, https://github.com/bklit/bklit-ui |
| shadcn/ui component patterns (button, dialog, menu, drawer, segmented control) | `web/src/components/ui/` | MIT, https://github.com/shadcn-ui/ui |

**Bklit Studio is not used.** Only the open-source Bklit UI components above are in the repository;
nothing references Bklit Studio (checked by searching the code and dependencies on 2026-10-25).

## Sample data

| File | Source | License |
|---|---|---|
| `api/samples/titanic3.csv` | OpenML dataset 40945, "Titanic" (the `titanic3` passenger list) | Listed by OpenML as **Public** (checked with the OpenML API on 2026-10-25) |
| `api/samples/sales_dated.csv`, `wide_messy.csv`, `reviews_text.csv`, `broken_latin1.txt` | Synthetic, generated once from seeded code | MIT, part of this project |
| `api/samples/seed/titanic3/` | The cached sample (D9.1): the Titanic file after Sherlock's own pipeline | Public (data) and MIT (Sherlock's outputs) |
| `docs/examples/titanic3-raw.csv`, `docs/examples/titanic3-v4.ipynb` | The example notebook exported from the cached sample (D9.2), and a byte-for-byte copy of `api/samples/titanic3.csv` beside it. In the repository, not in the image | Public (data) and MIT (Sherlock's outputs) |

## Models

Sherlock calls NVIDIA Nemotron models (Nemotron 3 Ultra, Super and Nano) through Nebius Token Factory's
API, under Nebius's and NVIDIA's terms of service. No model weights are in this repository or the image.

## Web retrieval

With `TAVILY_API_KEY` set, Sherlock calls Tavily's search, extract and map API (`tavily-python`, above),
under Tavily's terms of service, for outside-world questions, column meanings and a data dictionary the
user links (TRD §3.6). It uses retrieval only: Tavily's own answer and research features, which a
non-NVIDIA model writes, are never called. Search results are shown as quoted excerpts with their URL.

## Fonts

| Font | Package | License |
|---|---|---|
| Inter | `@fontsource-variable/inter` | SIL Open Font License 1.1 |
| Geist Mono | `@fontsource-variable/geist-mono` | SIL Open Font License 1.1 |
| Source Serif 4 | `@fontsource-variable/source-serif-4` | SIL Open Font License 1.1 |

## Web app (`web/package.json` dependencies)

| Package | Version | License |
|---|---|---|
| @fontsource-variable/geist-mono | 5.3.0 | OFL-1.1 |
| @fontsource-variable/inter | 5.3.0 | OFL-1.1 |
| @fontsource-variable/source-serif-4 | 5.3.1 | OFL-1.1 |
| @glideapps/glide-data-grid | 6.0.3 | MIT |
| @radix-ui/react-dialog | 1.3.1 | MIT |
| @radix-ui/react-dropdown-menu | 2.2.1 | MIT |
| @radix-ui/react-popover | 1.1.15 | MIT |
| @radix-ui/react-slot | 1.5.0 | MIT |
| @tanstack/react-query | 5.104.5 | MIT |
| @tiptap/core | 3.32.0 | MIT |
| @tiptap/pm | 3.32.0 | MIT |
| @tiptap/react | 3.32.0 | MIT |
| @tiptap/starter-kit | 3.32.0 | MIT |
| @visx/curve | 4.0.0 | MIT |
| @visx/event | 4.0.0 | MIT |
| @visx/grid | 4.0.0 | MIT |
| @visx/group | 4.0.0 | MIT |
| @visx/responsive | 4.0.0 | MIT |
| @visx/scale | 4.0.0 | MIT |
| @visx/shape | 4.0.0 | MIT |
| @xyflow/react | 12.11.3 | MIT |
| class-variance-authority | 0.7.1 | Apache-2.0 |
| clsx | 2.1.1 | MIT |
| d3-array | 3.2.4 | ISC |
| d3-shape | 3.2.0 | ISC |
| lodash | 4.17.21 | MIT |
| lucide-react | 1.61.0 | ISC |
| marked | 4.3.0 | MIT |
| motion | 14.6.0 | MIT |
| openapi-fetch | 0.17.0 | MIT |
| papaparse | 5.7.0 | MIT |
| react | 18.3.1 | MIT |
| react-dom | 18.3.1 | MIT |
| react-grid-layout | 1.5.2 | MIT |
| react-responsive-carousel | 3.2.23 | MIT |
| react-router-dom | 7.18.4 | MIT |
| sonner | 2.0.8 | MIT |
| tailwind-merge | 3.7.0 | MIT |
| zustand | 5.0.16 | MIT |

### Web app: what those dependencies install

From `corepack pnpm licenses list --prod` (2026-10-26). It's a superset of the bundle: some of these are
build-time helpers of a dependency (Babel and browserslist through Glide's styling library, for example)
and never reach the browser.

| License | Packages |
|---|---|
| MIT | 187 packages, among them the Radix, TipTap, ProseMirror, Floating UI, Linaria and Babel parts, `framer-motion`, `react-router`, `react-draggable`, `react-resizable` and `@visx/point` |
| ISC | `d3-color`, `d3-delaunay`, `d3-dispatch`, `d3-drag`, `d3-format`, `d3-geo`, `d3-interpolate`, `d3-path`, `d3-scale`, `d3-selection`, `d3-time`, `d3-time-format`, `d3-timer`, `d3-transition`, `d3-zoom`, `delaunator`, `internmap`, `electron-to-chromium`, `lru-cache`, `minimatch`, `picocolors`, `semver`, `yallist` |
| MIT and ISC | `@visx/vendor` 4.0.0 |
| BSD-3-Clause | `d3-ease` 3.0.1 |
| Apache-2.0 | `baseline-browser-mapping` 2.11.32 |
| 0BSD | `tslib` 2.8.1 |
| Unlicense | `robust-predicates` 3.0.3 |
| CC-BY-4.0 | `caniuse-lite` 1.0.30001819 (browser support data, build time only) |

## API (`api/pyproject.toml` runtime dependencies, then everything they install)

| Package | Version | License | |
|---|---|---|---|
| charset-normalizer | 3.5.2 | MIT | direct |
| dateparser | 1.2.0 | BSD | direct |
| duckdb | 1.1.3 | MIT | direct |
| fastapi | 0.162.0 | MIT | direct |
| ftfy | 6.3.1 | Apache-2.0 | direct |
| matplotlib | 3.9.2 | Python Software Foundation License | direct |
| nbformat | 5.11.1 | BSD 3-Clause License | direct |
| numpy | 2.1.3 | BSD-3-Clause | direct |
| openai | 3.37.0 | Apache-2.0 | direct |
| pandas | 2.2.3 | BSD 3-Clause License | direct |
| pandera | 0.34.1 | MIT License | direct |
| pydantic-settings | 2.16.1 | MIT | direct |
| python-multipart | 0.0.32 | Apache-2.0 | direct |
| PyYAML | 6.0.3 | MIT | direct |
| RapidFuzz | 3.10.1 | MIT License | direct |
| scikit-learn | 1.5.2 | BSD 3-Clause License | direct |
| sqlglot | 30.24.0 | MIT | direct |
| tavily-python | 0.8.5 | MIT | direct: web search, extract and map (TRD §3.6); off until `TAVILY_API_KEY` is set |
| uvicorn | 0.54.0 | BSD-3-Clause | direct |
| annotated-doc | 0.0.5 | MIT | |
| annotated-types | 0.8.0 | MIT | |
| anyio | 4.15.1 | MIT | |
| attrs | 26.1.0 | MIT | |
| certifi | 2026.10.23 | MPL-2.0 | (through tavily-python's requests and httpx) |
| click | 8.5.0 | BSD-3-Clause | |
| cloudpickle | 3.1.2 | BSD-3-Clause | |
| contourpy | 1.4.0 | BSD-3-Clause | |
| cycler | 0.12.1 | BSD-3-Clause | |
| fastjsonschema | 2.22.2 | BSD-3-Clause | |
| fonttools | 4.67.0 | MIT | |
| h11 | 0.16.0 | MIT | |
| httpcore | 1.0.9 | BSD-3-Clause | (through tavily-python) |
| httpcore2 | 2.16.0 | BSD-3-Clause | |
| httptools | 0.9.0 | MIT | |
| httpx | 0.28.1 | BSD-3-Clause | (through tavily-python) |
| httpx2 | 2.16.0 | BSD-3-Clause | |
| idna | 3.20 | BSD-3-Clause | |
| jiter | 0.18.0 | MIT | |
| joblib | 1.6.0 | BSD-3-Clause | |
| jsonschema | 4.26.0 | MIT | |
| jsonschema-specifications | 2025.9.1 | MIT | |
| jupyter_core | 5.9.1 | BSD-3-Clause | |
| kiwisolver | 1.5.1 | BSD-3-Clause | |
| mypy_extensions | 1.1.0 | MIT | |
| opentelemetry-api | 1.45.1 | Apache-2.0 | |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | |
| pillow | 13.0.0 | MIT-CMU | |
| platformdirs | 4.13.5 | MIT | |
| pydantic | 2.14.1 | MIT | |
| pydantic_core | 2.50.1 | MIT | |
| pyparsing | 3.3.3 | MIT | |
| python-dateutil | 3.0.0 | Apache-2.0 OR BSD-3-Clause (dual) | |
| python-dotenv | 1.2.4 | BSD-3-Clause | |
| pytz | 2026.5 | MIT | |
| referencing | 0.37.0 | MIT | |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python | |
| requests | 2.34.2 | Apache-2.0 | (through tavily-python) |
| rpds-py | 2026.9.1 | MIT | |
| scipy | 1.18.1 | BSD License | |
| six | 1.17.0 | MIT | |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | |
| starlette | 1.10.0 | BSD-3-Clause | |
| threadpoolctl | 3.7.0 | BSD-3-Clause | |
| tiktoken | 0.14.0 | MIT | (through tavily-python) |
| traitlets | 5.16.1 | BSD 3-Clause License | |
| truststore | 0.10.5 | MIT | |
| typeguard | 4.6.0 | MIT | |
| typing-inspect | 0.9.0 | MIT | |
| typing-inspection | 0.4.4 | MIT | |
| typing_extensions | 4.16.0 | PSF-2.0 | |
| tzdata | 2026.5 | Apache-2.0 | |
| tzlocal | 5.4.5 | MIT | |
| urllib3 | 2.8.0 | MIT | (through tavily-python's requests) |
| uvloop | 0.23.0 | MIT OR Apache-2.0 (dual) | (Linux only; through uvicorn[standard]) |
| watchfiles | 1.3.0 | MIT | |
| wcwidth | 0.9.4 | MIT License | |
| websockets | 17.3 | BSD-3-Clause | |

## Container base images

| Image | Use | License |
|---|---|---|
| `python:3.12-slim-bookworm` | the API stage | Python Software Foundation License; Debian packages under their own licenses |
| `node:24-bookworm-slim` | builds the web app only (not in the final image) | MIT (Node.js); Debian packages under their own licenses |
| `ghcr.io/astral-sh/uv` | copies the `uv` binary | MIT OR Apache-2.0 |
