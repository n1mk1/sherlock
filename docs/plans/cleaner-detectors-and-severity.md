# Plan: an extensible, severity-ranked Cleaner

**Status:** proposal for after the hackathon, not built. Nothing here is a spec until the PRD and TRD say it (CLAUDE.md Rule 1). Items marked **Owner** need a decision before the build; they are collected in §15.

**In one line:** the Cleaner's checks become a registry that can grow without limit: code detectors, installable packs, rules you write, and rules Sherlock suggests. Every finding is rated on a five-level severity scale with a one-line reason, and the plan and the queue follow that scale. Two things never change: code finds and counts every issue, and code runs and checks every fix.

---

## 1. Why

The work answers two problems found in the same place, the cleaning plan.

### 1.1 The plan doesn't say what matters

A run often reads like "16 issues found, 4 fixed". The five clean runs in the local `api/data/sherlock.db` (mostly Titanic) break down like this:

| Outcome | Findings | Share |
|---|---|---|
| Fixed (committed) | 17 | 31% |
| Fixed, flagged for review | 3 | 5% |
| Never changed by design: leakage and ID columns, and every other finding on those columns | 21 | 38% |
| "Left as is": Ultra judged the values to be real (missing cabins, an old passenger's age) | 10 | 18% |
| Real failures: no candidate passed the checks | 3 | 5% |
| Not reached | 1 | 2% |
| **Total** | **55** | |

Only about 5% are real failures. The rest of the gap has two causes:

- **The plan treats observations as fixes.** "Missing values" and "outliers" sit next to "fare stored as text" as ticked fixes, although the detectors' own planned actions say "otherwise leave the values missing" and "they stay in unless they're errors". The report then counts all of them as "skipped".
- **The ranking measures size, not impact.** Severity = share of rows affected × detector weight (TRD §7.1 step 4). Three impossible ages in the target column score almost zero, and a typo in the target ranks the same as a typo in a notes column.

### 1.2 The set of checks can't grow

Every detector's facts are hard-coded in nine places. Adding one, or renaming one, means editing all of them, and missing one fails quietly: a raw id shows in the UI, an issue lands in the wrong section, or the queue order breaks.

```mermaid
flowchart LR
    D((one detector)) --> A[detectors package init<br/>WEIGHTS, DETECTORS]
    D --> B[cleaning/plan.py<br/>DETECTOR_MODULE, LABELS,<br/>NEVER_CHANGE, SKIP_TEXT, TYPE_FIXES]
    D --> C[cleaning/loop.py<br/>LABELS again, VOTE_DETECTORS,<br/>DOMAIN_RULES, CODE_FIXES, queue]
    D --> E[cleaning/verifiers.py<br/>issue_count: module by name]
    D --> F[profile/datacard.py<br/>leakage branch]
    D --> G[web CleanPlanPanel.tsx<br/>LABELS a third time]
    D --> H[PRD §7.3.2<br/>the list of 16]
    D --> I[benchmark injectors<br/>eval/corruption.py]
    D --> J[tests]
```

### 1.3 Goals

1. **Severity you can act on.** Before pressing Start, you see which findings would change answers, which are probably fine, and why.
2. **A budget spent where it matters.** The Cleaner's 20 attempts and 300 s (`CLEAN_MAX_STEPS`, `CLEAN_MAX_SECONDS`) go to the most severe issues first.
3. **An honest report:** "fixed · checked and kept · couldn't fix", not one large "skipped".
4. **One file per detector.** A new detector is one module, or one rule, with no edits anywhere else, and it is rated, grouped and queued correctly from its own spec.
5. **Growth without Python.** You can add a check in plain terms, and Sherlock can suggest checks the built-ins miss.
6. **The same safety bar for everything.** Every detector, built in or added, passes one shared test suite and is measured by the corruption benchmark.

### 1.4 Non-goals

- The model never scans rows, counts anything or executes code. Detectors and rules are evaluated by code (Rule 2).
- The Cleaner's loop is unchanged: diagnose, propose, sandbox, nine hard checks, critic, gate, `commit_step`.
- Uploaded code never runs in the API process. Python packs are installed by the operator; users add rules, which are data.
- Leakage and ID columns are not rated: they stay under "Marked, not changed".

---

## 2. The design in one picture

```mermaid
flowchart TB
    subgraph Sources["Where checks come from"]
        S1[Built-in detectors<br/>cleaning/detectors/*.py]
        S2[Installed packs<br/>Python entry points]
        S3[Rule packs<br/>cleaning/rules/*.json]
        S4[Your checks<br/>rules per dataset]
        S5[Suggested checks<br/>Super writes rules]
    end
    S3 --> RD[rule detector<br/>one interpreter]
    S4 --> RD
    S5 --> RD
    S1 --> R[(Detector registry<br/>one DetectorSpec each)]
    S2 --> R
    RD --> R
    R --> P[Profile: run every enabled check<br/>code: find and count]
    P --> RT[Rate severity<br/>Super: level + reason]
    RT -. fails .-> DF[Default level<br/>from each spec]
    RT --> PL[Plan grouped by level<br/>you pick, reword, add checks]
    DF --> PL
    PL --> Q[Queue: your steps,<br/>then highest level]
    Q --> LP[Cleaner loop — unchanged<br/>Ultra writes code · sandbox · 9 checks · critic · gate]
    LP --> V[New version<br/>checks re-run]
    V --> Q

    classDef new fill:#FAEEDA,stroke:#854F0B,color:#412402
    classDef keep fill:#E1F5EE,stroke:#0F6E56,color:#04342C
    class R,RD,RT,DF,S2,S3,S4,S5 new
    class LP keep
```

| Step | Who | Today | After |
|---|---|---|---|
| Know which checks exist | code | 16 names in nine places | **the registry: one spec per check, from code, packs or rules** |
| Find and count issues | code | 16 detectors | **every enabled check, including rules** |
| Decide what never changes | code | leakage and ID names | **`spec.never_change`** |
| Rank issues | code | share × weight | **Super rates each finding on five levels with a reason; the spec's default level is the fallback** |
| Pick what to run | you | everything ticked | **grouped by level; "Worth a look" and suggestions start unticked; "Add a check"** |
| Write fix code | Ultra | same | same |
| Run, verify, commit / flag / skip | code | same | same |

The registry (§3) and the severity scale (§5) are the two halves of the design. The registry tells the rest of the app what each check is: its label, its group, its behaviour and its default severity. The rating then adjusts that severity for this file, by looking at the column's role and the examples.

---

## 3. The detector registry

### 3.1 `DetectorSpec`

Each detector is one module that exports a spec. Every fact that is now scattered across the nine places becomes a field, including its default severity level (§5.2).

```python
@dataclass(frozen=True)
class DetectorSpec:
    id: str                      # stable; stored as issues.detector ("sentinels")
    version: int                 # bump when what it finds changes; stored on the issue
    label: str                   # plain words for the plan and the log ("placeholder values")
    description: str             # one sentence for the catalog and the rating prompt
    group: str                   # fallback plan section when levels are off: types | missing | text | records | outliers | other | kept
    weight: float                # code severity weight, 0–1 (TRD §7.1 step 4); orders issues within a level
    default_level: Level         # breaks | skews | splits | check | cosmetic (§5.2)
    scope: Scope                 # "column" | "rows" | "columns" (a pair or more)
    applies_to: frozenset[str]   # column types it reads; empty = all
    detect: Callable[[Frame], list[Finding]]

    # Behaviour that is a special case in loop.py and plan.py today:
    never_change: str | None = None      # reason shown under "Marked, not changed" (leakage, IDs); not rated
    marks_column: str | None = None      # a flag it puts on the DataCard (leakage_candidates, id_columns)
    type_fix: bool = False               # allowed on an ID column (sentinels, numbers_as_text)
    domain_rule: bool = False            # violations quarantined, never guessed; low confidence flags
    vote: bool = False                   # an ambiguous order settled by a three-sample majority
    code_fix: Callable[[Finding], Candidate] | None = None   # a fix code can write without the model
    runs_before: tuple[str, ...] = ()    # same-column order (sentinels before impossible_values)
    plan_extras: Callable[[Finding], dict] | None = None     # extra plan fields (dates read both ways)

    # Quality gates (§9):
    injector: Callable[[pd.DataFrame, Random], Damage] | None = None   # benchmark damage of this kind
    clean_fixture: Callable[[], pd.DataFrame] | None = None            # data it must find nothing in
    enabled_by_default: bool = True
```

The `Finding` type (`detectors/base.py`) keeps its shape: detector, column, count, proposal, at most five examples, details.

### 3.2 The registry (`cleaning/registry.py`)

- **`register(spec)`** refuses: a duplicate id; an unknown group or level; a weight outside 0–1; a `runs_before` that names an unknown id or creates a cycle.
- **Lookups:** `all()`, `enabled(settings)`, `get(id)`, `label(id)`. `get` returns an "unknown detector" spec for issue rows written by a pack that has since been removed, so old versions still display.
- **`load_plugins()`** runs once at startup. It reads Python entry points in the group `sherlock.detectors`, which a pack declares in its own `pyproject.toml`:

  ```toml
  [project.entry-points."sherlock.detectors"]
  finance = "sherlock_finance.detectors:SPECS"
  ```

- **Config** (TRD §10):
  - `DETECTORS_OFF`: ids to skip.
  - `DETECTOR_PLUGINS`: `off` | `all` | an allowlist of pack names (**Owner**, §15).
  - `RULE_MAX_S` (§4.3).
- **`/healthz`** lists the loaded packs and their versions, as it lists the model ids.

### 3.3 What reads the registry instead of a name

| Today | After |
|---|---|
| `detectors.WEIGHTS[...]`, `DETECTORS` tuple | `spec.weight`, `registry.enabled()` |
| `plan.DETECTOR_MODULE`, `LABELS`, `NEVER_CHANGE`, `SKIP_TEXT`, `TYPE_FIXES` | `spec.group`, `spec.label`, `spec.never_change`, `spec.type_fix` |
| `loop.LABELS`, `VOTE_DETECTORS`, `DOMAIN_RULES`, `CODE_FIXES` | `spec.label`, `spec.vote`, `spec.domain_rule`, `spec.code_fix` |
| `loop.queue`'s `sentinels` special case | a general same-column order from `spec.runs_before` (§7) |
| `plan._item`'s `ambiguous_dates` branch | `spec.plan_extras` |
| `datacard.py`'s `leakage` branch | `spec.marks_column` |
| `verifiers.issue_count`'s module lookup | `registry.get(id).detect` |
| the web's `LABELS` | `GET /detectors` (§10.2) |

---

## 4. Checks without code: rules

Most useful future checks are not new algorithms. They are constraints: a range, allowed values, a pattern, an order between two columns. One built-in detector, `rule`, interprets them. A rule is data, so you, a rule pack or the model can add one safely: a fixed interpreter runs it, never arbitrary code.

### 4.1 Rule kinds

| Kind | Parameters | Finds | Default level |
|---|---|---|---|
| `range` | `min`, `max` (either may be open) | numbers outside the range | skews |
| `date_window` | `earliest`, `latest` | dates outside the window | skews |
| `allowed` | `values` (at most 200) | values not in the list, ignoring case and spacing | splits |
| `pattern` | `regex` (anchored, ≤ 200 characters, no backreferences) | text that doesn't match the pattern | splits |
| `not_missing` | — | missing values in a column that must be filled | check |
| `unique` | — | repeated values in a column that must be unique | skews |
| `order` | `left`, `right`, `op` (`<`, `<=`) | rows where the two columns are in the wrong order (start after end) | skews |
| `depends` | `from`, `to` | rows where the same `from` value has a different `to` value | check |

A rule also has an `action`:
- `quarantine`: the domain-rule handling, as `impossible_values` has today;
- `flag`: kept and marked for review;
- `fix`: the Cleaner's normal diagnose and propose, given the rule as the issue.

Each rule becomes its own plan item and issue key, `rule:<rule_id>|<column>`, so it is counted, rated and queued like any other finding.

### 4.2 Where rules come from

| Source | Stored in | Columns named by | Starts | Generic? (Rule 4) |
|---|---|---|---|---|
| **Rule pack** (shipped) | `cleaning/rules/*.json` | type, role or name words ("a column whose name says age") | ticked | must be; the hygiene test checks it |
| **Your checks** | `detector_rules`, per dataset | the dataset's own columns | ticked | yours, so they may name columns |
| **Suggested checks** (§6.3) | `detector_rules`, status `suggested` | the dataset's own columns | unticked | per dataset |

The existing `impossible_values` word lists (`NON_NEGATIVE`, ages, percentages, dates) move into a rule pack in the last slice (§14). That also fixes the open problem that its name matching has no word boundaries (`account_balance`, `average_temp`).

### 4.3 Interpreter safety

- **Vectorised only:** pandas operations, never `eval`, `query` or per-row Python. A rule that runs past `RULE_MAX_S` (2 s) on the profile's frame is stopped and listed as "This check took too long".
- **Regex limits:** a regex is checked when it's saved (anchored, no backreferences or nested quantifiers, length capped) and runs with a match timeout through the `regex` package (**Owner**, §15).
- **Parameter checks:** parameters must fit the column's type. A `range` on a text column is refused when the rule is saved, not at run time.

---

## 5. Severity

### 5.1 The scale

The five levels are adapted from incident severity levels to what an issue does to an analysis. A level is a category, not a computed number, so it fits Rule 2. In the schema it is an enum of words, not digits.

| Level | Enum | Plan heading | Meaning | Typical findings (placeholders, not one file's columns) |
|---|---|---|---|---|
| SEV-1 | `breaks` | Breaks answers | Answers or models would be wrong | numbers stored as text or mixed types in the target or a key measure; duplicate records that inflate counts |
| SEV-2 | `skews` | Skews answers | Answers would be biased | placeholders such as `-999` pulling an average; impossible values; mixed units |
| SEV-3 | `splits` | Splits groups | Groups would be split or mislabeled | `"<value>"` and `"<Value> "` showing as two bars; near-duplicate categories; garbled characters in a category |
| SEV-4 | `check` | Worth a look | Probably real; worth a look | outliers; rows that break a usual dependency; missing values with no rule to recover them |
| SEV-5 | `cosmetic` | Cosmetic | Doesn't change any answer | spacing or case in a free-text column |

### 5.2 Default levels: code, on every spec

Each spec carries a `default_level`. It is used:
- when the rating call fails, times out, is over budget or returns an invalid reply;
- for an issue that a fix exposes in the middle of a run (§7);
- when rating is turned off.

Code then adjusts it for the column:
- one level more severe when the column is the target or a measure (`profile.infer` roles);
- one level less severe on a free-text column, never below `cosmetic`.

| Built-in detector | `default_level` | On target / measure |
|---|---|---|
| `mixed_types`, `numbers_as_text`, `duplicates` | skews | breaks |
| `sentinels`, `impossible_values`, `unit_mixes`, `ambiguous_dates` | skews | breaks |
| `near_duplicate_categories`, `whitespace_case`, `mojibake`, `cross_column` | splits | skews |
| `missing`, `outliers`, `functional_dependency` | check | check |
| `leakage`, `id_candidates` | not rated (`never_change`) | — |

Rules take theirs from their kind (§4.1), and a pack's detectors from their own specs. A new check is therefore rated sensibly even with the model off.

### 5.3 What the levels drive

| Where | Effect |
|---|---|
| **Plan** | grouped under the five headings, highest first; "Worth a look" starts unticked (**Owner**, §15) |
| **Queue** | your steps first, then by level, then by code severity within a level (§7) |
| **Budget** | when the 20 attempts or 300 s run out, the issues not reached are the least severe |
| **Report** | each item shows its level; "Worth a look" items that end "left as is" count as **checked and kept**, not skipped |

---

## 6. The background review: rating and suggestions

### 6.1 One job, two calls, after profiling

Opening a plan must stay instant: today `plans.create` runs inside the request with no model call. So both model calls run in one background job, `review_issues` (`jobs/review.py`). The profile job queues it after each upload, and `POST …/clean/plan` queues it when the version has no review yet.

```mermaid
sequenceDiagram
    autonumber
    participant J as review_issues job
    participant S as Super
    participant C as Registry + rule interpreter (code)
    participant DB as SQLite
    participant U as You (plan)

    Note over J: queued after the profile job (version v)
    opt suggested checks on (P1)
        J->>S: suggest_rules — DataCard summary, fenced
        S-->>J: up to 8 rules {kind, column, params, action, reason}
        J->>J: validate columns, kinds, params, wording
        J->>C: run each valid rule on v
        C-->>J: count + examples
        J->>DB: detector_rules (suggested) + issues (detector rule)
    end
    J->>S: rate — every finding on v, fenced, with column roles and the scale
    S-->>J: [{ref, level, reason, likely_real}]
    J->>J: validate (each ref once, wording check)
    J->>DB: issues.sev, sev_reason, sev_source = model
    J-->>U: plan.updated
    Note over U: until then the plan shows default levels and "Reviewing…"
```

- **Suggestions come first** so the rating sees them and rates them like any other finding.
- **One review per version.** Stored on `issues`, so reopening a plan or merging a stale one (`plan.merge`) doesn't call the model again.
- **Not on every commit.** `commit_step` re-profiles each new version inline. During a run the queue uses the plan's levels and the specs' defaults (§7), so a run adds no model calls.
- **Serial per dataset,** like `stories`. Both calls count against `JOB_TOKEN_BUDGET`; over budget, the defaults apply and the clean run keeps its own budget.

### 6.2 The rating call

- **Role and purpose:** `medium`, purpose `rate`, temperature 0, reasoning on (only `route` may turn it off, TRD §3.5).
- **Prompt** (`cleaning/prompts/rate.txt`): the scale, then one line per finding inside a `<data>` block:
  - its ref (`f1`, `f2`…, as `edit_plan` does);
  - the spec's label and description;
  - the column's role and type;
  - code's count and share;
  - up to five examples;
  - the planned action, or the rule's text.

  Column names, examples and the file name are fenced (`llm.text.fence`). Prompt examples are placeholders (Rule 4). A new detector or rule needs no prompt change, since its spec supplies the words.
- **Schema** (`llm/schemas.py`, `Ratings`):

  ```json
  { "ratings": [ { "ref": "f1", "level": "breaks|skews|splits|check|cosmetic",
                   "reason": "<one sentence, no digits>", "likely_real": false } ] }
  ```

- **Validation** (code):
  - every ref appears exactly once, with no unknown refs;
  - `reason` passes `stories.wording.wording_problem` and the no-digits rule, so every number in the plan comes from code;
  - `likely_real: true` forces `check`;
  - on a target or measure column the level is never less severe than the spec's default (the floor in §5.2).

  A failing reply gets the client's one repair call, then the defaults. A reason that fails on its own is dropped, and the item keeps the model's level.
- **Cost:** about 2–6 s and a few thousand tokens for a typical file of 10–30 findings. It's an ordinary `llm_calls` row, so receipts and `sherlock llm stats` show it.

### 6.3 Suggested checks (P1)

The model writes a rule; code evaluates it. This is how the set of checks grows on its own without breaking Rule 2. The model already writes SQL that code runs, and here it writes rules that code runs.

- **Input:** the DataCard summary chat already uses (TRD §8.1): column names, types, roles, missing share, range and top values. Never raw rows.
- **Output** (`RuleSuggestions`, purpose `suggest_rules`, `medium`): at most eight rules `{kind, column, params, action, reason}`, validated against the columns and kinds (§4.1).
- **Thresholds are suggestions,** like a literal in SQL the model writes. The plan shows them as an editable rule labelled "suggested by Sherlock", never as a fact. The count beside it is code's (**Owner**, §15).
- **Shown unticked** under "Suggested checks", with their level and reason. Keep makes a rule `active` for this dataset, so it runs on every new version. Dismiss makes it `off`, and it is never suggested again.

---

## 7. Queue order during a run

```mermaid
flowchart LR
    T[Ticked plan items] --> O0[Your steps first]
    O0 --> O1[Then by level<br/>breaks → cosmetic]
    O1 --> O2[Within a level:<br/>code severity, highest first]
    O2 --> O3[Same-column order<br/>from spec.runs_before]
    O3 --> Q[Queue]
    Q --> X[Attempt one issue]
    X --> V[New version → checks re-run]
    V --> N{Issue key seen in the plan?}
    N -- yes --> L1[Keep the plan's level]
    N -- no --> L2[Spec's default level, code]
    L1 --> Q
    L2 --> Q
```

- **Your steps stay first,** as today (`loop.USER_SEVERITY`).
- **`runs_before` replaces the sentinel special case.** `sentinels` declares `runs_before = ("impossible_values",)`, so a column's placeholders run just before its domain rule whatever their levels, and `-999` becomes a missing value instead of quarantining the row. A pack or rule can declare its own order the same way.
- **No model call during the run.** A new issue that a fix exposes takes its spec's default level.

---

## 8. The trust boundary

```mermaid
flowchart LR
    subgraph Model["Model side — words and choices"]
        SG[Super: suggest rules]
        RT[Super: severity + reason]
        G[Ultra: diagnosis + fix code]
        CR[Super: critic]
    end
    subgraph Code["Code side — every number, every change"]
        RG[Registry + rule interpreter:<br/>find and count]
        S[Sandbox: run the code]
        K[9 hard checks + soft score]
        GT[Gate: commit / flag / skip]
        V[commit_step: new version, lineage, undo]
    end
    SG --> RG --> RT --> G --> S --> K --> CR --> GT --> V
```

- **A suggested rule** only proposes a check. Code counts it, and you decide whether to keep it.
- **A rating** only moves an item within the plan and sets whether it starts ticked. It can't stop the checks from running, commit a fix that fails them, change a count, or touch a leakage or ID column.
- **A failed fix is still skipped:** a `breaks` item whose fix fails the checks is skipped with its reason, as today.

---

## 9. The same bar for every check

A check is code that judges data, so a bad one quietly produces bad plans. Instead of relying on reviewers to remember what to look at, one suite runs on every spec in the registry, including installed packs and the rule interpreter. It runs in CI and at pack install time (`uv run sherlock detectors check`).

```mermaid
flowchart LR
    N[New detector, pack or rule kind] --> T1[Contract tests]
    T1 --> T2[Clean fixture:<br/>finds nothing]
    T2 --> T3[Injector: finds its damage]
    T3 --> T4[Time budget]
    T4 --> T5[Wording + hygiene]
    T5 --> T6[Default level valid]
    T6 --> T7[Corruption eval picks up<br/>its injector automatically]
    T7 --> OK[Registered and enabled]
    T1 -. any failure .-> X[Refused, naming the check that failed]
```

| Check | Rule |
|---|---|
| Metadata | id unique and snake_case; group and `default_level` valid; weight 0–1; label and description present |
| Determinism | the same frame twice gives the same findings |
| Purity | the frame and its columns are unchanged after `detect` |
| Finding shape | count > 0, the column exists (or is None for row scope), at most five examples, details JSON-serialisable |
| Clean data | `clean_fixture()` gives no findings (a shared clean fixture of every column type is the default) |
| Finds its damage | `injector` damage of N cells gives a finding with count ≥ N |
| Resolvable | re-running on the injector's clean values finds nothing, so the verifier's "share of the issue gone" works |
| Time | ≤ 2 s on a 200,000-row frame of the types it applies to. The suite also reports the total for every enabled check on 500,000 rows, which must stay inside the Profile budget (≤ 60 s for a 50 MB file, TRD §13) |
| Wording | label, description and proposal pass `wording_problem` and carry no sample column names (`test_prompt_hygiene.py`) |
| Generic | no column name from any sample file in the module's constants or a shipped rule pack (Rule 4) |

`sherlock eval corruption` builds its damage from `registry.all()` injectors, so each new check is measured for recovery, wrong values, harm and row loss with no new eval code. It also checks the ratings (§13).

---

## 10. Data, API and screens

### 10.1 Schema (`docs/05-BACKEND-SCHEMA.md`)

- **Migration `009_issue_review.sql`** adds to `issues` (§2.8):
  - `detector_version INTEGER`, so `plan.merge` can tell a changed finding from a changed detector;
  - `sev TEXT`;
  - `sev_reason TEXT`;
  - `sev_source TEXT` (`model` | `default`);
  - `likely_real INTEGER`.
- **Migration `010_detector_rules.sql`:**

  ```sql
  CREATE TABLE detector_rules (
    id          TEXT PRIMARY KEY,          -- rul_…
    user_id     TEXT NOT NULL,
    dataset_id  TEXT,                       -- NULL = the user's rule for every dataset (P2)
    source      TEXT NOT NULL,              -- user | suggested | pack
    status      TEXT NOT NULL,              -- active | suggested | off
    spec_json   TEXT NOT NULL,              -- {kind, column, params, action, reason}
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
  );
  ```

- **`clean_plans.items_json`** (§2.21) is JSON, so plan items gain `sev`, `sev_reason`, `sev_source`, `likely_real` and `rule_id` without a migration.

### 10.2 API (TRD §4.4)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/detectors` | — | `{ detectors: [{ id, label, description, group, default_level, source }] }` |
| POST | `/datasets/{id}/clean/plan` | as today | `CleanPlan`: items gain the level fields, and the plan gains `review: "ready" \| "running" \| "default"` |
| GET | `/datasets/{id}/rules` | — | `{ rules: Rule[] }` |
| POST | `/datasets/{id}/rules` | `{ kind, column, params, action }` | `Rule` (validated; `422` names the bad field) |
| PATCH | `/rules/{rid}` | `{ status?, params?, action? }` | `Rule` |

New plan ops (`PlanOp`, `plan.apply_ops`):
- `tick_level` and `untick_level`, like `tick_module`;
- `add_rule`;
- `keep_suggestion` and `dismiss_suggestion`.

### 10.3 Screens (App Flow §4.1, §5)

- **Plan panel**, groups in this order:
  1. **Your steps**
  2. **Breaks answers**
  3. **Skews answers**
  4. **Splits groups**
  5. **Worth a look**
  6. **Cosmetic**
  7. **Suggested checks**
  8. **Marked, not changed**
- **Each item shows:**
  - the label from `GET /detectors` (the web's `LABELS` map goes away);
  - code's count and examples;
  - the planned fix or the rule;
  - the model's reason in muted text, and "(default level)" when the fallback set it.
- **No per-item badges.** The group heading carries the level, keeping to the UI brief's "no badges on every element" (UIUX §10).
- **While the review is running,** the plan shows default levels and "Reviewing…", then refreshes on `plan.updated`.
- **"Add a check"** in the plan: pick a column, a kind with its parameters, and an action. The count appears as soon as the rule is saved, because code runs it on the current version.
- **Chat** (`agent/actions.py` `edit_plan`): plan lines include the level and reason. "Skip the cosmetic ones", "do everything that breaks answers" and "flag rows where `<column>` is below zero" become plan edits.
- **Report** (PRD CLEAN-6): **fixed · flagged · checked and kept · couldn't fix · not attempted**.
  - "Checked and kept" = left as is, or `likely_real`.
  - "Couldn't fix" = skipped by the checks, the gate or disagreeing candidates.

  Each count lists its items with their level and the reason already stored in `issues.skip_reason`.

---

## 11. Where the code goes

```mermaid
flowchart TB
    subgraph IN["api/sherlock/cleaning/"]
        c1[registry.py — new]
        c2[detectors/*.py — each exports a DetectorSpec]
        c3[rules/ — interpreter + shipped packs, new]
        c4[review.py — rating + suggestions, validation, defaults, new]
        c5[prompts/rate.txt, suggest_rules.txt — new]
        c6[plan.py, loop.py, verifiers.py, report.py]
    end
    subgraph OUT["Outside cleaning/"]
        o1[llm/schemas.py — Ratings, RuleSuggestions]
        o2[jobs/review.py — new; runner KINDS;<br/>jobs/profile.py queues it]
        o3[profile/datacard.py — marks_column]
        o4[routers/cleaning.py, new routers/rules.py,<br/>GET /detectors]
        o5[db/migrations 009, 010]
        o6[agent/actions.py — edit_plan]
        o7[config.py — DETECTORS_OFF, DETECTOR_PLUGINS, RULE_MAX_S]
        o8[web — CleanPlanPanel, CleaningOffer,<br/>report view, Add a check, regenerated types]
        o9[eval/corruption.py — injectors from the registry]
        o10[tests + fixtures/llm]
    end
    IN --- OUT
```

| Area | Files | Change |
|---|---|---|
| Registry | `cleaning/registry.py` (new); `detectors/*.py`, `detectors/__init__.py` | one spec per detector; registration, plugins, lookups |
| Rules | `cleaning/rules/` (new): `interpreter.py`, `kinds.py`, `*.json` packs | the `rule` detector and its kinds |
| Review | `cleaning/review.py` (new), `prompts/rate.txt`, `prompts/suggest_rules.txt` | rating, suggestions, validation, default levels |
| Cleaner | `plan.py`, `loop.py`, `verifiers.py`, `report.py` | read specs; group and queue by level; `runs_before`; new report counts |
| LLM | `llm/schemas.py` | `Ratings`, `RuleSuggestions` |
| Jobs | `jobs/review.py` (new), `jobs/runner.py` (`KINDS`, `SERIAL_KINDS`), `jobs/profile.py` | the background review |
| Profile | `profile/datacard.py` | `marks_column` instead of the leakage branch |
| API | `routers/cleaning.py`, `routers/rules.py` (new), `/detectors` | §10.2 |
| DB | `db/migrations/009_issue_review.sql`, `010_detector_rules.sql` | §10.1 |
| Chat | `agent/actions.py` | level-aware plan lines; `tick_level`, `add_rule` |
| Config | `config.py`, `.env.example`, `render.yaml` | `DETECTORS_OFF`, `DETECTOR_PLUGINS`, `RULE_MAX_S` |
| Web | `CleanPlanPanel.tsx`, `CleaningOffer.tsx`, the cleaning report view, `api/schema.d.ts`, `api/types.ts` | §10.3 |
| Eval | `eval/corruption.py`, `eval/synthetic.py` | injectors from the registry; rating checks |
| Tests | `tests/test_detector_contract.py`, `test_cleaning_review.py`, `test_rules.py` (new); `test_cleaner.py`, `test_cleaning_units.py`, `test_chat_actions.py`, `test_prompt_hygiene.py`; `fixtures/llm/cleaner_review.json` | §13 |
| Developer guide | `api/sherlock/cleaning/detectors/README.md` (new); example pack in `api/samples/detector_pack/` | how to write a detector, a rule pack or a pack |

---

## 12. Docs to update in the same commits (Rule 1)

| Doc | Section | Change |
|---|---|---|
| PRD | §7.3.2 | "the built-in detectors" plus the registry; the list of 16 stays as the built-in set |
| PRD | new **CLEAN-8c** | severity levels with reasons, the default levels, what starts ticked |
| PRD | CLEAN-6 | the report's new counts |
| PRD | new **CLEAN-12** | the registry and catalog: one spec per check; labels come from the catalog |
| PRD | new **CLEAN-13** | your checks: rule kinds, actions, counts from code |
| PRD | new **CLEAN-14** | suggested checks: model-written rules, evaluated by code, approved by you |
| TRD | §3.3 | job kind `review_issues` |
| TRD | §3.5 | purposes `rate` and `suggest_rules` |
| TRD | §4.4 | `/detectors`, `/rules`, plan fields and ops |
| TRD | §7.1 step 4, §7.2 | the registry, `DetectorSpec`, the rule detector, the queue by level, `runs_before` |
| TRD | §10 | `DETECTORS_OFF`, `DETECTOR_PLUGINS`, `RULE_MAX_S` |
| TRD | §14 | the contract suite, the review tests, the registry-driven corruption eval |
| TRD | §15 | packs are installed by the operator only; rules are data run by a fixed interpreter |
| Schema | §2.8, §2.21, new table, migrations list | §10.1 |
| App Flow | §4.1, §5 | groups, "Reviewing…", Add a check, Suggested checks, report counts |
| UI brief | plan panel and report | group headings, muted reasons, the Add a check form, the suggested group, no per-item badges |
| Implementation plan | build order | the slices in §14 |
| LOG.md | one entry per slice | what was built and verified (history stays out of the specs, Rule 5) |

---

## 13. How we verify it

- **Contract suite** (`test_detector_contract.py`): every rule in §9, parametrised over `registry.all()`. Slice 1's proof is that the 16 built-ins pass it with identical findings before and after.
- **Registry:**
  - duplicate ids, bad groups, levels and weights, and `runs_before` cycles are refused;
  - a removed pack's old issues still display;
  - `DETECTORS_OFF` disables a detector.
- **Rules** (`test_rules.py`):
  - each kind finds what its table says;
  - a bad parameter is refused when saved;
  - a slow rule stops at `RULE_MAX_S`;
  - a hostile regex is refused or times out;
  - a rule's issue is counted, rated and queued like any finding.
- **Review** (`test_cleaning_review.py`, recorded replies, no network):
  - a valid rating sets levels and reasons;
  - a missing, duplicate or unknown ref gets a repair, then the defaults;
  - a reason with digits or causal wording is dropped;
  - `likely_real` forces `check`;
  - the target and measure floor holds;
  - leakage and ID findings are never sent;
  - suggestions are validated, run by code and stored unticked;
  - with `LLM_BASE_URL` unset, every item gets its default level and the plan still opens.
- **Queue:**
  - your steps first, then by level, then by code severity;
  - `runs_before` holds even when the later detector is rated higher;
  - an issue a fix exposes gets its default level;
  - the budget ends on the least severe.
- **Prompt hygiene:** `test_prompt_hygiene.py` sends the malicious file through the `rate` and `suggest_rules` builders, and shipped rule packs carry no sample column names.
- **API and e2e:**
  - opening a plan returns at once with `review: "running"` or `"default"`, and `plan.updated` follows;
  - Playwright covers:
    - the eight groups;
    - unticking "Worth a look";
    - Add a check, with its count shown;
    - Keep and Dismiss on a suggestion;
    - the new report counts.
- **Live eval** (`sherlock eval corruption`, Nemotron):
  - **Rating:** every injected damage in a target or measure is rated `breaks` or `skews`, and damage to free text is rated `splits` or lower.
  - **Report honesty:** "couldn't fix" equals the real failures.
  - **Unchanged:** recovery, Wrong 0, harm 0 and row loss 0 stay at or above the last logged run.
  - **Stable:** the same file reviewed twice gives the same levels.

---

## 14. Build order

Each slice is verified (`uv run pytest`, `corepack pnpm test`, `corepack pnpm typecheck`, `corepack pnpm e2e` where the UI changes, `sherlock eval corruption`) and committed with its docs.

```mermaid
flowchart LR
    S0[0 · Specs] --> S1[1 · Registry,<br/>no behaviour change]
    S1 --> S2[2 · Contract suite<br/>+ injectors]
    S1 --> S3[3 · Default levels<br/>+ queue by level]
    S3 --> S4[4 · Rating call<br/>review job]
    S4 --> S5[5 · Plan + report UI]
    S2 --> S6[6 · Your checks<br/>rule detector]
    S5 --> S6
    S2 --> S7[7 · Installable packs]
    S6 --> S8[8 · Suggested checks]
    S6 --> S9[9 · impossible_values<br/>as a rule pack]
    S5 --> S10[10 · Live evals]
    S8 --> S10
```

0. **Specs.** The doc changes in §12, written first.
1. **Registry, no behaviour change.**
   - Add `DetectorSpec` and `registry.py`, and give the 16 built-ins their specs (with `default_level`, unused yet).
   - Move every hard-coded map in §3.3 to the registry; add `GET /detectors`; switch the web's labels to it.
   - Proof: the full test suite and the offline corruption eval give identical results.
2. **Contract suite and injectors.** `test_detector_contract.py`, an injector and clean fixture per built-in, and the corruption eval reading injectors from the registry. Fix any built-in that fails the contract.
3. **Default levels and queue by level, no model.** Migration 009; plan items with `sev_source: default`; grouping by level; `loop.queue` by level with `runs_before`. Shipped alone, this already gives the target-column boost and the honest grouping.
4. **The rating call.** `Ratings`, `rate.txt`, `review.py` with validation and fallback, the `review_issues` job, and `plan.updated`.
5. **Plan and report UI.** The eight groups, reasons, "Reviewing…", `tick_level` in the panel and in chat, and the new report counts.
6. **Your checks.** The rule interpreter and kinds, migration 010, the `/rules` API, `add_rule`, and "Add a check".
7. **Installable packs.** Entry points, `DETECTOR_PLUGINS`, `DETECTORS_OFF`, `/healthz` listing, `sherlock detectors check`, the developer guide and the example pack.
8. **Suggested checks (P1).** `suggest_rules` inside the review job, validation, the "Suggested checks" group, Keep and Dismiss.
9. **Built-in rule packs.** Move the `impossible_values` word lists into `cleaning/rules/*.json` with word-boundary matching; the contract suite and the corruption eval prove recovery is unchanged.
10. **Live evals.** The rating, report-honesty and stability checks against Nemotron, with results in `docs/LOG.md`.

Slices 2 and 3 only need slice 1, so they can be built in parallel, as can slices 6 and 7.

---

## 15. Risks and open decisions

### 15.1 Owner decisions

| # | Question | Proposal |
|---|---|---|
| 1 | Priority of CLEAN-8c, 12, 13, 14 | After the hackathon: P1 for 8c, 12 and 13; P2 for 14 (suggested checks). Nothing here changes the P0 scope or the cut order (plan §5). |
| 2 | Should "Worth a look" start unticked? | Yes: these are the findings that end "left as is" today. You can tick them, or the whole group from chat. |
| 3 | Should "Cosmetic" start ticked? | Yes: case and spacing fixes are cheap, safe and almost always pass the checks. |
| 4 | Are installed packs allowed in production? | `DETECTOR_PLUGINS=off` by default, an allowlist when on. Packs run in the API process with its permissions, so only the operator installs them. |
| 5 | Are model-suggested thresholds compatible with Rule 2? | Yes, as with SQL literals: a threshold is a rule parameter you see and can edit, and the count is code's. |
| 6 | Add the `regex` package for timed matching? | Yes, so a pattern can't hang the profile job. Otherwise, drop the `pattern` kind. |

### 15.2 Risks

| Risk | Mitigation |
|---|---|
| The model rates a serious issue low | The target and measure floor (§6.2); the item stays ticked unless it lands in `check`. |
| The model rates something real as `breaks` | The checks and the gate are unchanged, so a wrong fix still can't commit. A bad rating changes the order, not the data. |
| Levels change between visits | One review per version, temperature 0, stored on `issues`. |
| Prompt injection through a column name or a cell | Fenced like every prompt; covered by the hygiene test; a reason with markup fails the wording check. |
| A slow or noisy check degrades every upload | The time budget in the contract suite, `RULE_MAX_S`, and `DETECTORS_OFF` without a deploy. |
| A pack removed after its issues were stored | `registry.get` returns an "unknown detector" spec, so old plans and reports still display. |
| A detector change makes old plans misleading | `issues.detector_version`; `plan.merge` re-runs items whose detector version changed. |
| Too many plan items as checks grow | Severity groups keep the important ones on top; suggestions start unticked. |
| Overlapping checks flag the same cells | `spec.scope` and the issue key; the contract suite reports pairs of checks that flag the same cells on the shared fixture. |
| Extra wait before the plan | None: the plan opens with default levels and updates itself. |
