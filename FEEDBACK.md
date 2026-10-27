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

## The Cleaner on Nemotron (2026-10-24, Implementation Plan D3)

**What we used it for:** the headless Cleaner. Per issue, Ultra (`large`) diagnoses it and writes up to three pandas candidates against our helper library, every candidate runs in the sandbox and is scored by code verifiers, and Super (`medium`) critiques the best one before the gate. All three calls use strict `response_format` JSON schemas with reasoning on.

**First live runs on the Titanic sample:**

| Run | Where | Time | Calls (diagnose · propose · critic) | Tokens (prompt + completion) | Median latency |
|---|---|---|---|---|---|
| 1 | local (Windows) | 130 s | 10 · 7 · 6 | 21.1k + 29.8k ≈ 51k | diagnose 3.3 s · propose 6.9 s · critic 3.1 s |
| 2 | Render (Linux, sandbox user) | 119 s | similar | similar | similar |

- **What worked:**
  - Every reply validated against its schema on the first try; no repair call was needed.
  - Ultra's code ran in our restricted sandbox: it used the helpers (`fill_by_group`, `normalize_whitespace_case`, `quarantine_rows`) instead of importing anything.
  - Ultra left legitimate values alone when asked to judge: "The age 80 belongs to the oldest passenger … not an error."
- **Problems:**
  - Run 1 imputed the missing `body` numbers, a column our leakage detector had flagged, because only the leakage issue itself was excluded from fixing. That was our bug (a missing-values issue on the same column got through), now fixed. The model did what the issue asked.
  - The same input gave different gates between runs. In run 2, Super raised concerns on three "fill with 'Unknown'" steps that it had passed in run 1, so they committed with a flag instead of outright. With reasoning on, temperature 0 isn't deterministic for us.
  - One candidate called `df.insert` on a column that already existed and failed in the sandbox; the other candidates covered it.
- **Suggestion:** a `seed` parameter honoured end to end (with reasoning on) on Token Factory would make agent pipelines like this reproducible for tests and for judges re-running a demo. It would help anyone building evaluation harnesses on Nemotron.

**Cost:** the night's work (five Titanic cleans, three benchmark runs and a few live checks, about 0.65M tokens, mostly Ultra) used the remaining $0.94 of the $1.00 trial credit. The $25 account balance was untouched, and calls kept working once the trial credit read $0.00.

- **Problem:** the console doesn't say what happens at $0.00 trial credit. Calls went on working, and we couldn't tell whether they were drawing on the account balance or on some grace allowance. Separately, the "Post-trial preference" defaults to stopping usage when the 30-day trial ends. A hackathon app deployed in the trial's first week would lose its model during judging unless the owner finds that setting.
- **Suggestion:** show, in the balance panel, which balance the next call draws from. Email a warning a week before a trial with a live API key stops usage. This would help every team whose judging period runs past their trial.

**Corruption benchmark** (`uv run sherlock eval corruption`, 2026-10-24): the clean sets are damaged in known ways and the Cleaner runs on each with the real models.

| Set | Rows | Damaged cells | Recovered | Harm | Row loss | Quarantined | Steps | Time |
|---|---|---|---|---|---|---|---|---|
| titanic_clean | 1,043 | 509 | 92.1% | 0.00% | 0.0% | 81 | 5 | 81 s |
| sales | 1,500 | 765 | 97.3% | 0.00% | 0.0% | 45 | 5 | 87 s |
| hr | 800 | 269 | 94.1% | 0.00% | 0.0% | 5 | 5 | 80 s |

**Rerun after the owner's two cleaning decisions** (missing values stay missing; reviewer concerns don't block a commit), same seeds:

| Set | Recovered | Harm | Row loss | Steps | Time |
|---|---|---|---|---|---|
| titanic_clean | 97.2% (was 92.1%) | 0.00% | 0.0% | 4 | 59 s |
| sales | 94.5% (was 97.3%) | 0.00% | 0.0% | 5 | 69 s |
| hr | 74.0% (was 94.1%) | 0.00% | 0.0% | 4 | 75 s |

- Placeholders improved from 28 to 41 of 102 recovered.
- The two drops are run-to-run variance in which fix Ultra proposes, not the new rules:
  - `hr` department case variants: 55 of 120 this time, 120 of 120 before.
  - `sales` units placeholders: 3 of 45, 27 of 45 before.
- Same input and temperature 0, different code. This is the reproducibility point above, measured.

**Rerun after output agreement, merge safety and two new corruptions** (2026-10-26): three new sets test what the Cleaner must not do, dates that read both ways (written day-first in one set and month-first in the other) and look-alike categories ("Plan A"/"Plan B", "Region 1"/"Region 2", "Austria"/"Australia"). **Wrong** counts damaged cells changed into the wrong value.

| Set | Recovered | Wrong | Harm | Row loss | Steps | Time |
|---|---|---|---|---|---|---|
| titanic_clean | 92.1% | 5.1% | 0.00% | 0.0% | 5 | 117 s |
| sales | 97.6% | 0.0% | 0.00% | 0.0% | 4 | 103 s |
| hr | 98.1% | 0.0% | 0.00% | 0.0% | 3 | 75 s |
| dates_dmy | 0.0% (was 100%, a silent guess) | 0.0% | 0.00% | 0.0% | 0 | 2 s |
| dates_mdy | 0.0% | 0.0% (was 100%) | 0.00% | 0.0% | 0 | 6 s |
| lookalikes | 41.7% (was 100%) | 0.0% | 0.00% | 0.0% | 1 | 90 s |

- Before, the import typed both date sets day-first without saying so: right on one, wrong on every value of the other. Now neither is guessed; the user picks the order in the plan.
- The `titanic_clean` and `lookalikes` drops were fixed the same morning: a lone imputation candidate had filled 26 age placeholders, and the look-alike fixes were skipped when candidates spelled one value two ways or wrote a number as currency text. After the fixes:

| Set | Recovered | Wrong | Harm | Row loss | Steps | Time |
|---|---|---|---|---|---|---|
| titanic_clean | 97.2% | 0.0% | 0.00% | 0.0% | 4 | 73 s |
| dates_dmy | 0.0% | 0.0% | 0.00% | 0.0% | 0 | 2 s |
| dates_mdy | 0.0% | 0.0% | 0.00% | 0.0% | 0 | 11 s |
| lookalikes | 100.0% | 0.0% | 0.00% | 0.0% | 4 | 128 s |

- **Feedback for Nemotron 3 Ultra:** in one run all three candidate fixes for a column came back as one line of code with a literal `\n` where the line breaks belong (the code string escaped twice inside the JSON reply), so none parsed. Steps to reproduce: ask for `Candidates` with a `code` field under strict decoding at temperature 0 and check `ast.parse` on each; it happened for one column in one of five benchmark runs on 2026-10-26, and in none of the others. Sherlock now repairs it when the repaired code parses. Suggestion: validate that a string field meant to hold code has real line breaks, or document the escaping the structured-output mode applies.

- **What it recovered fully:** money formatting (`$1,234.5` → numbers), case and spacing variants, mojibake (`ZÃ¼rich` → `Zürich`) and day-first dates. Typos in categories were 42 of 45.
- **Weak spot:** placeholder values (`N/A`, `-999`, `?`) in numeric columns. Only 28 of 102 became missing; the rest were quarantined as parse failures, or `-999` stayed a number. The quarantined rows keep their text and are excluded from analysis, so nothing is silently wrong, but the cleaning is incomplete. This is our pipeline's order (the issue is diagnosed after the typing step), not a model fault.
- **Harm 0%** after we fixed two bugs in our own scorer: yes/no columns typed as booleans counted as changed, and money damage rounded fares to cents. The first two runs reported 11–13% harm, all of it the scorer.

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

### Nemotron in the dashboard builder and chat (2026-10-25, Implementation Plan D4)

- **Curation (Super, schema `Curation`).** It picked 7–8 widgets from a 14-item shortlist and titled them in plain words ("Survival by sex", "Fare by class", "Passengers by port"). None of its titles needed the templated fallback.
- **Routing (Nano, reasoning off).** About 1 s per message.
  - With a flat list of intents it sent plain breakdowns ("average fare by class", "median fare by class") to `ask_stats`.
  - Saying "most messages are ask_data; when in doubt choose ask_data", and narrowing `ask_stats` to explicit significance questions, fixed most of it.
  - "Survival rate by sex as a chart" was read as also asking for a dashboard widget until `create_widget` was limited to requests that name the dashboard.
- **SQL (Super).** 2–5 s, and good with the column examples in the prompt. Two habits:
  - It read "port" as `home.dest` until the prompt said to match words by the columns' example values, not their names. Then it chose `embarked`.
  - It sometimes wrote `AVG(<boolean>)`, which DuckDB refuses. The prompt now says to cast.
- **Compose: Nano versus Super.**
  - Nano, with reasoning on, strung chips together with no words ("87.5121.1813.30") and left sentences unfinished, so compose moved to Super.
  - Super, with `prose` as the schema's last field, often closed the object with an empty `prose`. Moving `prose` first cut the repairs.
  - Super still sometimes writes JSON fragments inside a text run, which the no-digits rule rejects. After one repair, the answer falls back to the raw table with its SQL.
  - **Suggestion for Token Factory or the model card:** document how property order in a strict `json_schema` affects generation. It changes the output a lot.
- **Eval v0** (35 questions on two files): 31 and then 32 passed, with 0 unsourced answers and a median of 11–12 s per answer.

### Nemotron writing story cards (2026-10-25, Implementation Plan D6)

**What we used it for:** a short story card per dashboard widget. Code computes a fact sheet (values, rankings, chi² and Kruskal-Wallis tests, trends); the model writes the headline and two to four sentences as a list of runs where every number is a chip naming a fact and every column or category is a label. Strict `json_schema` (the Story union from Day 1), reasoning on.

- **Nano (`small`), the planned narrator, didn't hold the contract.** On the Titanic dashboard (8 cards):
  - It typed the chip markup inside text runs: `{"text": "The rate is {\"chip\":\"value\"}."}`. Strict decoding enforces the run shapes, but nothing stops JSON inside a string, and the no-digits check passes because the markup has no digits.
  - It ran sentences together (`".It is"`) and two of thirteen calls hit our 30 s timeout. Median latency was 22.5 s.
  - **Effect:** narration moved to Super, as chat compose did on Day 4. We added a check that rejects `{`, `}`, `chip` and `column:` inside a text run.
- **Super (`medium`) wrote valid cards** with a median of 13.6 s per card (about 1,500 completion tokens, most of it reasoning). On its first try it also wrote chip markup inside text runs on two of eight cards and on the overview; one repair fixed each.
- **Super spelled a number out to get around the no-digits rule** (live, 2026-10-25, after the deploy). On a "passengers by `parch`" card, it wrote "only 2 passengers had **six** parents or children" rather than use the category label. The value was right, but the model typed it, not code. We now also reject numbers in words. **Suggestion:** say in the model card or the structured-output guide that "no digits" constraints are commonly met by spelling numbers out. Teams relying on a regex for grounding need to know this.
- **Steps to reproduce:** ask any Nemotron model, with a strict schema whose items are `{"text"}` / `{"chip"}` / `{"label"}` objects, to write two sentences with three numbers: some replies embed `{"chip": ...}` as text.
- **Suggestion:** a documented pattern (or a constrained-decoding option) for "interleaved text and references" outputs, the shape every grounded-generation app needs. An example in the Nemotron docs showing the expected run list would help any team building cited or chip-based text.
- **Token Factory returned `529 System is overloaded`** three times in one stories job (2026-10-25, about 07:10 UTC), each answered in about 3.4 s. Our retry with backoff (2 s) succeeded every time, so the cards were only slower. **Suggestion:** a `Retry-After` header on 529, and a status page entry, so clients back off for the right time.

### Nemotron on the Flow canvas, chat actions and the evals (2026-10-25, Implementation Plan D8–D9)

- **"Make sense of this" (Super, schema `Story`, purpose `synthesis`).** On Titanic it wrote a correct comparison of three cards in one call ("Overall survival stood at 38.2%, with females at 72.7% versus males at 19.1%…", every number a chip from the cards' fact sheets). On the sales file it twice typed chip markup inside a text run (`'The average unit price {"chip":"c3.value"} equals…'`), so the card fell back to the cards' headlines. Strict `json_schema` decoding enforces the run union's shape but not what a string holds, which is the same gap we hit in D6.
  - **Suggestion:** document that strict decoding constrains structure only, and expose a "forbidden substrings in strings" or regex constraint. Teams forcing citation-style output would use it.
- **Routing (Nano, reasoning off).** In the 50-question eval it sent "what is the overall survival rate?" and "what is the return rate?" to the significance-test answerer, though the intent line says "only when the user asks whether a difference … is significant". We now keep that intent in code for messages that mention a test or a relationship.
- **SQL (Super).** It once used DuckDB's `APPROX_QUANTILE` for a median (60.31 against an exact 60.0), and twice judged "average revenue per order" and "men in second class" unanswerable. Two prompt lines fixed all three in the rerun.
- **Wording (Super).** One story said "how class influences typical ticket price": causal language our first word list didn't cover. "Influence", "affect" and "impact" are now rejected too.
- **Latency.** Medians held (Super 4–10 s, Nano about 1.5–3 s), but one Nano routing call took 27 s and one Super synthesis 23 s during an afternoon overload. With 90 s per answer and 8 calls we stayed inside the budget; a user waiting on a 27 s "Thinking…" notices.
  - **Suggestion:** return `Retry-After` or a queue-depth hint on slow paths, as with 529, so clients can show "the model is busy" instead of spinning.
- **Spend for Day 8–9.** Three seed builds of the sample (about 50–68k tokens each, Ultra and Super), two grounding builds, three 50-question eval runs and the live checks: roughly 1 M tokens, an estimate (each eval answer is about 3–5k tokens across route, SQL and compose; the console has the exact figure).

### NVIDIA embedding model (`embed`)

- None is available on Token Factory, so this role is empty (see Token Factory problem 1).

### Not assigned: `Nemotron-3.5-Super-VL`, `Nemotron-3_5-Lightning`

- **Super-VL:** 6/6 in both modes and fast. It's a candidate if the `medium` role ever needs replacing.
- **Lightning:**
  - With thinking on, its median was 20 s.
  - Story hit the 4,096-token cap while reasoning and returned no JSON.
  - It never chose `create_widget`.
  - It isn't used.

## The model-call log (`sherlock llm stats`, 2026-10-26)

Every Nemotron call is a row in `llm_calls` (TRD §3.5). `uv run sherlock llm stats` (in `api/`, TRD §14) opens the database read-only and sums it per purpose and per role: p50 and p95 latency and tokens over the calls that answered, and the repair, fail and fallback rates over every attempt. This is the committed source for the README's median latencies and tokens per message.

Run on 2026-10-26 against the local `.env` database (`DATABASE_URL=sqlite:///./data/sherlock.db` in `api/`), which holds the Day 3–7 live runs of 2026-10-25: 10 jobs and 3 chat answers over 7 datasets. The command was `uv run sherlock llm stats`; `--json` gives the same figures as JSON.

Model calls over the whole log: 111 (2026-10-25T01:24:51.745Z to 2026-10-25T13:16:38.242Z). Latency and tokens are over the calls that answered; the rates over every attempt.

| purpose | roles | calls | p50 s | p95 s | tokens per call | tokens | repair | fail | fallback |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| diagnose | large | 33 | 2.8 | 5.0 | 1,786 | 58,927 | 0% | 0% | 0% |
| propose | large | 23 | 6.0 | 10.1 | 3,621 | 83,273 | 0% | 0% | 0% |
| critic | medium | 20 | 3.8 | 6.3 | 1,037 | 20,748 | 0% | 0% | 0% |
| narrate | medium | 16 | 9.8 | 15.9 | 1,835 | 23,853 | 7% | 19% | 0% |
| compose | medium | 4 | 6.6 | 9.4 | 1,456 | 5,825 | 100% | 0% | 0% |
| overview | medium | 4 | 9.4 | 12.0 | 2,458 | 9,831 | 100% | 0% | 0% |
| curate | medium | 3 | 9.3 | 11.5 | 2,383 | 7,150 | 0% | 0% | 0% |
| route | small | 3 | 1.4 | 1.6 | 1,232 | 3,696 | 0% | 0% | 0% |
| sql | medium | 3 | 4.1 | 4.3 | 1,441 | 4,323 | 0% | 0% | 0% |
| widget | medium | 2 | 3.5 | 3.8 | 1,469 | 2,938 | 0% | 0% | 0% |

| role | models | calls | p50 s | p95 s | tokens per call | tokens | repair | fail | fallback |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| large | nvidia/Nemotron-3-Ultra-550b-a55b | 56 | 4.1 | 9.7 | 2,539 | 142,200 | 0% | 0% | 0% |
| medium | nvidia/nemotron-3-super-120b-a12b | 52 | 6.1 | 14.2 | 1,524 | 74,668 | 11% | 6% | 0% |
| small | nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B | 3 | 1.4 | 1.6 | 1,232 | 3,696 | 0% | 0% | 0% |

Chat messages with model calls: 3; tokens per message p50 6,717, p95 7,288.

**What it shows:**
- **Latency.** Ultra's diagnose had a median of 2.8 s, faster than Super's critic (3.8 s); propose, which writes up to three pandas fixes, took 6.0 s. Super's writing calls took longest: a story card 9.8 s (p95 15.9 s), the overview 9.4 s, curation 9.3 s. Nano's routing took 1.4 s.
- **Tokens per chat message.** Each call was 1,000–3,600 tokens, most of it the prompt. A whole chat answer (route, the SQL draft, compose and its repair) came to 2,700–7,400 tokens in the three logged, with a median of 6,717. Nano's share is its one route call, about 1,200 tokens. The README's "about 1,500 tokens per chat message" for Nano was close to a single call's size, not an answer's; it now says both.
- **Repairs.** Both chat answers that reached compose needed its one repair (chip markup inside a text run), and so did both overviews; narration needed one repair in 16 attempts. Strict `json_schema` decoding enforces the shape, so a repair is always about a rule beyond the schema (no digits in prose, no markup in a text run).
- **Failures.** The only failed attempts were three narrate calls that got HTTP 529 (`server_error`, overloaded) from Token Factory, each after about 3.4 s, and were retried. That is 19% of narrate's attempts and 6% of Super's. A 529 is retried like a 5xx (TRD §3.5).
- **Suggestion:** a `Retry-After` on the 529 would let clients wait exactly as long as needed instead of backing off blind; and a documented per-model rate limit would let us size the per-role gates (`LLM_CONCURRENCY_*`) from the numbers instead of from trial.

## Tavily web retrieval, live (2026-10-26)

`uv run sherlock eval web --live` with a real `TAVILY_API_KEY` in the local `.env`. The deployed app has no key yet, so web retrieval is off there. Each question is asked three times: with the web on, with Tavily failing (a stand-in that answers a 502 or a timeout at once) and with the web off. Tavily is used for `search`, `extract` and `map` only; Nemotron writes every sentence.

| Run | Web on | Web failing | Web off | Cell values sent | Tavily calls | Tavily p50 |
|---|---|---|---|---|---|---|
| All three files (20 questions) | 14 of 20 | 13 of 20 | 17 of 20 | 0 | 17 | 2,030 ms |
| `reviews_text.csv` again (7 questions) | 6 of 7 | 7 of 7 | 6 of 7 | 0 | 7 | 1,187 ms |

- **Privacy held in both runs:** no outbound request held a cell of the file, or a digit run the question didn't contain.
- **The first run's six failures were a Token Factory stall, not the web.** Six answers in a row on `reviews_text` ran into the 90 s message deadline ("This answer ran out of time."), five of them with the failing stand-in, which returns at once, so the time went to the model calls. The rerun of that file, minutes later, failed soft on all seven questions (2–16 s each) with no error.
- **The misses are routing**: a few outside-world questions that use one of the file's words go to the file's answerers or the help, and "what does posted mean?" (a date column) was answered from the data with no web source.
- Median answer with the web on: 9.9–10.3 s, against 4.2–5.3 s with it off.

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
- **2026-10-25, Bklit check (Implementation Plan §2.0, before D4.7). It passed.**
  - **Install.** `@bklit/bar-chart`, `line-chart`, `area-chart`, `pie-chart` and `ring-chart` came from the `@bklit` shadcn registry (`https://ui.bklit.com/r/{name}.json`) with shadcn CLI 4.22.1.
  - **Problems along the way:**
    - The CLI calls `pnpm` directly, which on this machine only exists through Corepack, so the install needed a `pnpm` shim on `PATH`.
    - It asked to overwrite `src/lib/utils.ts`, and `--yes` didn't answer that.
    - It appended its own oklch palette to `index.css`, which overrode our chart tokens. We removed it and mapped Bklit's extra variables onto the brief's tokens in `theme.css`.
    - The code targets React 19, so one ref type needed a cast under React 18. `@types/d3-shape` and `@types/d3-array` had to be added.
  - **Pass rules.**
    - Custom tooltip rows: yes (`ChartTooltip rows`).
    - Theme tokens: yes, every color is a CSS variable.
    - A shared hover between two charts: not tried yet (that's D6 hover linking).
  - **Brushing** wasn't needed (cut 8).
  - **What we changed.** `Bar` has no per-bar fill or click handler, so we added `getFill` and `isDimmed` props to our copy, and a click on the chart reads the hovered index from `useChartHover`. Bklit's `RingChart` is a radial progress ring, so a share "ring" is drawn as a `PieChart` with an inner radius.
- **2026-10-25, react-grid-layout check. It passed with one fallback.**
  - 1.5.2 works with React 18.
  - Drag is restricted to a handle with `draggableHandle`, and `draggableCancel` keeps clicks on buttons and charts.
  - `WidthProvider` failed the re-measure check: it measured the container as 0 when the tab mounted and never measured again, so the grid stayed on its 4-column layout. The dashboard now measures its container with its own `ResizeObserver` and passes `width`.
  - `react-resizable`'s stylesheet isn't reachable under pnpm's strict layout, so the resize corner is styled in `index.css`.
- **2026-10-25, Glide Data Grid check (Implementation Plan §2.0, before D5.1). It passed.**
  - **Setup.** `@glideapps/glide-data-grid` 6.0.3 (the `latest` tag; 6.0.4 is still alpha), with its peers `lodash`, `marked` and `react-responsive-carousel`. It works with React 18.
  - **Pass rules.**
    - Editing: yes. The overlay editor needs a `<div id="portal">` in the page; without it double-click selects but no editor opens, and nothing says why.
    - Range selection: yes (`rangeSelect="multi-rect"`, drag and Shift+click).
    - Range paste: not shown. A synthetic `paste` event with a `DataTransfer` didn't reach the grid in the automated browser, so it wasn't verified. Cut 5 removes TSV paste, so it isn't needed.
    - Theme from the CSS variables: yes, once each token is resolved to `rgba()` in code. The canvas can't read `var(--accent)` or `color-mix()`, so a helper reads the computed color through a probe element and a 1 × 1 canvas.
    - 500,000 rows with a paged data source: yes. The scroll area is 17 M px tall, a jump to row 294,119 drew a loading cell and then the page, and `updateCells` redraws only the fetched page.
  - **Fill handle** was turned on but not tried (cut 5).
  - **Result.** No fallback was needed. The CSV tab uses Glide with a paged source of 200 rows a page.
