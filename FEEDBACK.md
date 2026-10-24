# Feedback: Nebius Token Factory, NVIDIA Nemotron, Nebius hosting

Running notes, written the moment something happens (Implementation Plan §1) and finalized on Oct 29 for the feedback field (§7).

Each entry covers: what we used it for · what worked · the problem, with steps to reproduce and its effect on the build · a concrete, buildable suggestion and who it would help.

## Day 1 smoke test (2026-10-24)

`scripts/smoke_llm.py` ran against the live catalog from a Windows desktop: one run per setting, at temperature 0 with `max_tokens` 4096. It covered every Nemotron chat model in the catalog. Each model got six checks:
- a plain completion
- three JSON-schema completions with `response_format: json_schema, strict: true`: Diagnosis, Route, and Story (a list of text/chip/label runs, with no digits allowed in prose)
- a native tool call
- a pandas task whose code was executed and compared with the right answer

"Thinking off" means we sent `chat_template_kwargs: {"enable_thinking": false}`. Median latency is per call; completion tokens are summed over the six checks.

| Model | Role | Thinking on: pass · median · completion tokens | Thinking off: pass · median · completion tokens |
|---|---|---|---|
| `nvidia/Nemotron-3-Ultra-550b-a55b` | large | 6/6 · 1.43 s · 3,380 | 6/6 · 0.79 s · 466 |
| `nvidia/nemotron-3-super-120b-a12b` | medium | 6/6 · 2.72 s · 1,981 | 4/6 · 1.51 s · 629 |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | small | 6/6 · 4.64 s · 4,222 | 5/6 · 0.90 s · 426 |
| `nvidia/Nemotron-3.5-Super-VL` | not assigned | 6/6 · 2.49 s · 4,549 | 6/6 · 0.72 s · 499 |
| `nvidia/Nemotron-3_5-Lightning` | not assigned | 4/6 · 20.21 s · 8,997 | 4/6 · 1.34 s · 368 |

**Decisions this produced:**
- **Roles:** large = Ultra, medium = Super 120B, small = Nano 30B, as the PRD specifies.
- **`LLM_TOOLS_MODE=native`:** the three role models made valid native tool calls with the right tool.
- **Thinking:** left on by default. With thinking off, the role models broke the Story contract, as described under each model below.
- **`MODEL_EMBED` is empty:** the catalog has no NVIDIA embedding model.
- **Story schema:** it moves to a union of one-key run objects so strict decoding itself enforces one kind per run (TRD §3.5). That fixed Super's thinking-off failure. A rerun with the union, thinking on, passed Story on all three roles (Ultra 4.0 s, Super 7.3 s, Nano 10.5 s).

## Token Factory

**What we used it for:**
- OpenAI-compatible chat completions through the official `openai` Python SDK, with only `base_url` changed
- `GET /v1/models` for the startup catalog and `/healthz`
- `response_format` with strict JSON schema
- native `tools`

**What worked:**
- The SDK worked unchanged.
- Every Nemotron model accepted strict `json_schema` and `tools`.
- `chat_template_kwargs.enable_thinking=false` was accepted by all five and cut completion tokens by roughly 7–10×.
- The models list answered fast enough to back a cached health probe.

**Credit:**
- On 2026-10-24 the console showed **0.94 of the 1.00 starter credit** left, plus a **$25 top-up** (as reported by the owner).
- That works out to about 0.06 for everything so far: three smoke-test runs across five Nemotron models, and one Story rerun on the three role models.
- Per-call costs will come from the `llm_calls` log once the client exists (Implementation Plan D2.7).

**Problem 1: no NVIDIA embedding model in the catalog.**
- **Steps:** call `GET /v1/models` and filter for `embed`. The only result is `Qwen/Qwen3-Embedding-8B`.
- **Effect:** our rules allow only NVIDIA models, so embeddings are off. Name and value resolution in chat falls back to exact and fuzzy matching, so semantic matches like "ticket price" → `fare` are lost.
- **Suggestion:** host one NVIDIA embedding model (a NeMo Retriever / Llama-Nemotron embedding NIM) next to the Nemotron chat models. That would help every team building NVIDIA-only RAG or agents, including everyone in this hackathon.

**Problem 2: model IDs have no consistent scheme and the catalog has no metadata.**
- **Steps:** the five Nemotron IDs are `NVIDIA-Nemotron-3-Nano-30B-A3B`, `Nemotron-3-Ultra-550b-a55b`, `nemotron-3-super-120b-a12b`, `Nemotron-3.5-Super-VL` and `Nemotron-3_5-Lightning`. They mix cases, prefixes, and `3.5` against `3_5`. `/v1/models` returns only `id`.
- **Effect:** choosing Ultra, Super and Nano needed a heuristic (`pick_roles`) plus a test, and we couldn't tell which models support tools, JSON schema or reasoning without calling each one.
- **Suggestion:** use one ID format, and add `family`, `parameters`, `context_length`, `supports_tools`, `supports_json_schema` and `reasoning` fields to `/v1/models`. This helps anyone selecting models automatically.

**Problem 3: reasoning is reported inconsistently.**
- **Steps:**
  - Ultra, Super, Super-VL and Lightning return a visible reasoning trace.
  - Nano returns none, yet uses reasoning-scale tokens: 4,222 completion tokens with thinking on against 426 off.
  - `usage` has no separate reasoning-token count.
- **Effect:** we can't audit or budget reasoning separately, and token budgets (TRD §3.5) count it as output.
- **Suggestion:**
  - Always return reasoning in one field, such as `reasoning_content`, or never return it, per a documented flag.
  - Report `usage.completion_tokens_details.reasoning_tokens`.

  This would help any app with per-user token budgets.

## Nemotron models

### Nemotron 3 Ultra (`large`): `nvidia/Nemotron-3-Ultra-550b-a55b`

- **Results:**
  - 6/6 with thinking on and 6/6 with it off.
  - Despite its size it had the lowest median latency of the three role models (1.43 s on, 0.79 s off).
  - Story used 2,169 completion tokens with thinking on for a two-sentence card, so most of that is reasoning.
- **Tool choice:** in the first run the tool prompt didn't list the columns. Ultra called `ask_data` to ask which columns exist, instead of guessing in `create_widget`. That's sensible, and the test was fixed to give the columns.

### Nemotron 3 Super (`medium`): `nvidia/nemotron-3-super-120b-a12b`

- **Thinking on:** 6/6, with the fewest completion tokens of the three roles (1,981).
- **Thinking off: 4/6.**
  - Story broke the run structure ("each run has exactly one of text, chip, label"). The schema allowed that because all three fields were optional, which was our mistake. After we changed runs to a union of one-key objects with `additionalProperties: false`, Super passed Story with thinking off (0.76 s). Strict decoding enforces structure only as far as the schema expresses it.
  - The tool call put a SQL query into `ask_data`'s `question` instead of calling `create_widget`. In a second thinking-off run, at temperature 0, it chose correctly, so the choice isn't stable without reasoning.
- **Effect:** medium-role calls (the critic and the curation) keep thinking on.

### Nemotron 3 Nano (`small`): `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`

- **Thinking on:** 6/6, but the slowest of the three roles (median 4.64 s; Story took 17 s).
- **Thinking off:** 0.90 s, but Story typed the numbers as digits ("paid on average 84.15 units…") instead of using fact chips. That breaks Sherlock's rule that the model never writes a number.
- **Effect:** narration keeps thinking on. Routing (the Route schema) passed with thinking off on all three role models, so the chat router may turn it off for speed. That's decided when the LLM client is built (Implementation Plan D2.7).

### NVIDIA embedding model (`embed`)

- None is available on Token Factory, so this role is empty (see Token Factory problem 1).

### Not assigned: `Nemotron-3.5-Super-VL`, `Nemotron-3_5-Lightning`

- **Super-VL:** 6/6 in both modes and fast. It's a candidate if the `medium` role ever needs replacing.
- **Lightning:**
  - With thinking on, its median was 20 s.
  - Story hit the 4,096-token cap while reasoning and returned no JSON.
  - It never chose `create_widget`.
  - It isn't used.

## Nebius hosting (Serverless Endpoint / AI Cloud VM)

**What we used it for:** the planned host was one CPU-only Serverless Endpoint with a shared filesystem at `/data` (`scripts/deploy.sh`). We moved hosting to Render on 2026-10-24 because of the problems below. Inference stays on Token Factory.

**Problem 1: Token Factory access doesn't carry over to AI Cloud, and a new AI Cloud tenant starts suspended.**
- **Steps:**
  1. Have a working Token Factory account and API key, signed in with GitHub.
  2. Install the Nebius CLI and run `nebius profile create` with the same GitHub login.
  3. Run `nebius iam tenant list` and `nebius iam project list`. A tenant created at that moment, with `suspension_state: SUSPENDED`, has three default projects (eu-west2, us-north1 and one more), all suspended.
- **Effect:**
  - Nothing can be created: no registry, filesystem or endpoint. The hello-world deploy (Implementation Plan D1.3) was blocked on deadline week.
  - Nothing in the CLI said why the tenant was suspended or what would lift it.
  - The hackathon materials we found mention Builder Program credits for Token Factory, not for AI Cloud.
- **Suggestion:**
  - Make `nebius iam tenant list` (and the console) say why a tenant is suspended and link to the fix (billing, a promo code, verification).
  - Let hackathon credits, or a Token Factory account in good standing, activate a small AI Cloud allowance.

  This helps every hackathon team that wants to host on Nebius, since the rules encourage Serverless but most entrants start on Token Factory.

**Problem 2: the CLI has no Windows build.**
- **Steps:** the install docs cover Ubuntu and macOS only.
- **Effect:** on a Windows dev machine we had to install Ubuntu under WSL, enable Docker Desktop's WSL integration, and run the CLI there. The browser login callback to `127.0.0.1` worked through WSL's localhost forwarding.
- **Suggestion:** ship a Windows binary, or document the WSL route (including `--no-browser`) on the install page.

## Tooling notes from the build

- **2026-10-24, scaffold:** Starlette's `TestClient` now warns that using it with `httpx` is deprecated and asks for `httpx2`, so the API's dev dependencies use `httpx2`. This isn't a Nebius issue; it's kept so the build log is complete.
- **2026-10-24, CI:** `astral-sh/setup-uv` no longer publishes a moving major tag such as `v10`, so CI pins `v10.3.2`.
