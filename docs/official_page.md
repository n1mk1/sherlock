# Nebius × NVIDIA Global AI Hackathon
## Official Rules, Judging Rubric & Submission Strategy Report

**Report date:** October 24, 2026  
**Submission deadline:** **October 30, 2026, 1:00 PM EDT** (10:00 AM PDT)  
**Format:** Online, public hackathon  
**Official page:** https://nebiusglobalaihackathon.devpost.com/  
**Official rules:** https://nebiusglobalaihackathon.devpost.com/rules  
**Schedule:** https://nebiusglobalaihackathon.devpost.com/details/dates  
**Judges' discussion:** https://www.youtube.com/watch?v=LjCh-ZIyjx4

> **Source distinction:** Sections labeled **Official** summarize Devpost's published materials. Sections labeled **Panel guidance** come from the user-provided judges' session transcript. Sections labeled **Recommended** are independent preparation advice, not additional competition rules.

---

## 1. Executive Summary

The challenge is to **build a working AI system on open, independent infrastructure**. Eligible projects must operate on **Nebius Token Factory or Nebius AI Cloud** and use **at least one NVIDIA open-source model**. Participants select one of four tracks.

The competition has **two judging stages**:

1. **Stage One — pass/fail:** assess baseline viability, real fit with the selected track, and genuine application of required APIs/SDKs. Superficially rebranding an unrelated idea does not qualify.
2. **Stage Two — scored:** evaluate the four **equally weighted** judging criteria: Technological Implementation, Design, Potential Impact, and Quality of the Idea. Each accounts for **25%** of the judging framework.

**Panel guidance:** Judges repeatedly favored focused products that solve real user problems, work reliably, explain their technical architecture, and make their main benefit obvious immediately. They warned against unnecessary model/tool integrations, generic AI wrappers, weak onboarding, and unsupported claims.

**Critical implication:** A polished submission cannot compensate for failing a mandatory requirement. Verify compliance first; then optimize the four equally weighted categories.

---

## 2. Official Dates and Eligibility

### 2.1 Official schedule

| Event | Date and time |
|---|---|
| Submission period begins | August 26, 2026, 9:00 AM PDT |
| **Submission deadline** | **October 30, 2026, 10:00 AM PDT / 1:00 PM EDT** |
| Judging period | December 1–15, 2026 |
| Winners announced | On or around January 11, 2027 |

**As of October 24, 2026:** approximately six calendar days remain before the submission deadline. Do not assume the deadline is at midnight.

### 2.2 Official eligibility summary

- Individuals must be at or above the age of majority in their country of residence.
- Eligible individuals may participate individually or as part of teams; eligible organizations may also enter.
- Teams/organizations must appoint an authorized representative.
- The official rules list geographical restrictions and other exceptions. They specifically list **Quebec** among excluded jurisdictions, along with Brazil and several sanctioned locations.
- Sponsor/administrator conflicts of interest, judges and certain related parties are excluded.
- The complete Official Rules control where this summary is incomplete.

**Recommended action:** Confirm the eligibility of every team member and the entrant organization, if applicable, before finalizing the submission.

---

## 3. Mandatory Technical Challenge — Official

All submissions **must**:

- Run on **Nebius Token Factory** **or** **Nebius AI Cloud**.
- Use **at least one NVIDIA open-source model**.
- Meet the requirements of the selected track.
- Demonstrate a working project, not merely a concept description.

**Not universally mandatory:** Using several NVIDIA models; using every Nebius tool; adopting Tavily; deploying on Serverless Endpoints or Serverless Jobs. Those can be useful or track-relevant but are not blanket requirements for all projects.

### Technical evidence to prepare — Recommended

- Model names, endpoints, and workloads handled.
- A diagram of the request/data flow.
- The specific role of Nebius infrastructure.
- A reproducible example showing actual inference.
- Why model choice, latency, cost, and reliability suit the problem.
- Clear treatment of API keys and secrets in public code.

---

## 4. The Four Official Tracks

### 4.1 Coding and Agentic Engineering Track

**Official scope:** Coding agents and developer tools, including agents that write, run, and test code in Token Factory.

**Suggested demonstration — Recommended:** Show a realistic developer task, code creation/modification, tests, execution result, and appropriate model use. Report accuracy, completion, latency, or cost where measurable.

### 4.2 Best Apps and Agents Track

**Official scope:** Practical applications, productivity tools, copilots, and agents that users would actually use. Use Nemotron through Nebius Token Factory.

**Official model guidance:** Nemotron 3 Ultra for demanding reasoning; Nano or Super for faster everyday calls. Nebius Serverless Endpoints and Serverless Jobs are encouraged but **not required**.

**Suggested demonstration — Recommended:** Show a real user workflow and measurable improvement, not just a chatbot conversation.

### 4.3 Personal AI Track

**Official scope:** Always-on, private assistants where the user controls their data. The track encourages persistent memory, reusable skills, selected data/tool access, and execution across daily workflows.

**Officially mentioned tools:** NVIDIA NemoClaw, OpenShell, Hermes Agent, and Nebius Serverless, with at least one NVIDIA open-source model required.

**Suggested demonstration — Recommended:** Show memory persistence, tool use, permissions or privacy controls, task completion, and error handling. Do not claim persistent autonomy if your demo only runs one isolated request.

### 4.4 Physical AI Track

**Official scope:** Embodied/edge agents, robotics, IoT, or on-device intelligence. Models mentioned include Nemotron, GROOT, Cosmos, and Sonic. Serverless Jobs/Endpoints can support simulation, synthetic data, evaluation, processing, and inference.

**Special official demo requirement:** The video must contain **at least one minute** of physical hardware/robot actually operating; **if no physical hardware component exists**, show the key application modules operating for at least one minute.

**Special official submission rule:** A hosted demo URL is **not required** for Physical AI projects.

**Suggested demonstration — Recommended:** Show evidence of the physical or simulation workflow, inputs, decisions, and observable results.

---

## 5. Complete Submission Requirements — Official

| Item | Required content | Notes |
|---|---|---|
| **Working project** | Functional solution using required Nebius infrastructure and NVIDIA open-source model(s) | Must satisfy chosen track |
| **Category** | Choose the best-fitting track | Four tracks available |
| **Project description** | What was built, why it exists, and how it works | Connect problem, solution and architecture |
| **Working demo URL** | Hosted application or test build | **Not required for Physical AI** |
| **Public demo video** | Public YouTube video, **3 minutes or shorter** | Show actual functionality and use of required technology |
| **Public source repository** | GitHub, GitLab or Bitbucket URL | Must be accessible for judging/testing |
| **Open-source license** | MIT, Apache 2.0, MPL 2.0 or comparable license | Must be visible at the top of repository page |
| **README** | Setup and execution instructions | Highlight NVIDIA models, Nebius Token Factory, and relevant services |
| **Technology feedback** | Feedback on Nebius Token Factory/AI Cloud and NVIDIA tools/models used | Part of submission |
| **Pre-existing project disclosure** | Describe significant changes made during the submission period | Conditional: only if project existed beforehand |
| **Builders & Brews city** | Select event city attended | Conditional: for City Winner Award consideration |

### 5.1 Demo-video requirements

- Publicly accessible **YouTube** video.
- Maximum length: **3 minutes**.
- Demonstrate a working project.
- Explain/show how NVIDIA open-source models and Nebius infrastructure are used.
- **Physical AI:** include at least one minute of relevant hardware operation or key application modules in action.

### 5.2 Repository requirements

- Public repository URL.
- Visible open-source license at the root/top-level repository page.
- README containing setup and run instructions.
- Explain NVIDIA model usage and Nebius infrastructure integration.
- Include enough detail for judging and testing.

### 5.3 Submission readiness checklist

- [ ] Entrant/team eligible under the official rules.
- [ ] Correct track selected.
- [ ] Project genuinely uses Nebius Token Factory or Nebius AI Cloud.
- [ ] At least one NVIDIA open-source model is genuinely used.
- [ ] Working primary feature is demonstrated.
- [ ] Working demo URL added, except if Physical AI.
- [ ] Public YouTube demo is **≤3:00**.
- [ ] Physical AI video includes ≥1:00 of required operation, if applicable.
- [ ] Public repo URL works without login.
- [ ] Open-source license is prominent.
- [ ] README has reproducible setup and run commands.
- [ ] Technology feedback submitted.
- [ ] Pre-existing work and new changes explained, if applicable.
- [ ] Builders & Brews city selected, if eligible.
- [ ] Submission finalized before October 30, 1:00 PM EDT.

---

## 6. Official Judging Process and Rubric

### Stage One: Pass / Fail

The judges first evaluate whether the submission:

- Is a genuine attempt to meet the chosen track's stated goal.
- Meets a baseline level of viability.
- Reasonably applies required APIs/SDKs.

Projects that fail Stage One do **not** progress to Stage Two.

### Stage Two: Four equally weighted criteria

| Official criterion | Official weight | Core judging question |
|---|---:|---|
| **Technological Implementation** | **25%** | How well built is it, and how effectively does it use Nebius Token Factory/AI Cloud and NVIDIA open-source models? |
| **Design** | **25%** | Is it a coherent, complete product experience rather than only a technical proof of concept? |
| **Potential Impact** | **25%** | Does it credibly solve a specific problem for real users, and does the demonstration show it actually does so? |
| **Quality of the Idea** | **25%** | Is the application creative and non-obvious, with genuine understanding of the problem domain? |

**Tie-break rule — Official:** In a tie, the score in the **first listed criterion** is compared, followed by the next criterion in order as needed; a panel vote resolves a tie persisting across all applicable criteria.

### 6.1 Technological Implementation — 25%

**Official focus:** Engineering quality and effective integration of required Nebius and NVIDIA technology.

**Panel guidance:**
- Use model/platform features for a real reason, not just for attribution.
- Creative implementations can stand out.
- More services do not automatically earn more points.

**Recommended proof:** Functional architecture diagram, real inference trace, appropriate model choices, latency/cost measurements, and successful task execution.

**Typical weaknesses:** Unnecessary stacks, shallow integration, broken demos, unexplained model choices.

### 6.2 Design — 25%

**Official focus:** A complete, coherent product experience.

**Panel guidance:**
- Aim for the core "wow" within **30 seconds**.
- Aim for an understandable experience and "aha moment" in **under 2 minutes**.
- Prioritize intuitive onboarding, feedback, navigation and visible results.
- Design for the actual user: CLI tools can qualify as excellent design.

**Recommended proof:** Cold-start user test, sensible default inputs, progress/error indicators, clear primary action and outcome.

**Typical weaknesses:** Generic AI-generated style, information overload, hidden actions, unclear onboarding.

### 6.3 Potential Impact — 25%

**Official focus:** A credible, specific case for solving a real problem for a real audience, supported by what the demo actually shows.

**Panel guidance:**
- Define the exact audience and pain point.
- Ask people who might actually use the product.
- Show what improvement your product creates.

**Recommended proof:** User statements, baseline vs outcome, time/cost saved, quality improvement, or a clear reduction in workflow friction.

**Typical weaknesses:** Vague audience, invented benefits, no evidence, cool technology without a real use case.

### 6.4 Quality of the Idea — 25%

**Official focus:** Originality, creativity and genuine understanding of the problem space.

**Panel guidance:**
- Generic wrappers are less compelling.
- Explain where the problem is genuinely difficult.
- Show thoughtful trade-offs, such as model size and cost.
- Small problems solved well can be excellent submissions.

**Recommended proof:** Differentiation from existing alternatives, concrete domain insight, thoughtful scope, justifiable technical design.

**Typical weaknesses:** Derivative idea, vague novelty, lots of unrelated features, little domain understanding.

---

## 7. Judges' Live Review Lessons — Panel Guidance

| Reviewed project | Positive signals | Suggested improvement |
|---|---|---|
| **Telltale (scam detection)** | Clear workflow, evidence, sample inputs, practical need | Put recommended actions first; reduce density; consider workflow integrations and cases with thin evidence |
| **Slash-agent (cost-aware coding)** | Concrete cost-optimization goal and receipts | Display routing/progress; compare costs to a baseline; improve onboarding |
| **Mnemos (AI memory)** | Distinctive design, inspectable memory, MCP integration potential | Explain use case sooner; show real integrations and session boundaries |
| **Assay (robotics data QA)** | Technical depth and practical quality checks | Improve onboarding, chart/report interpretation, and corrective guidance |

### Cross-project lessons

1. **Show the conclusion before the evidence dump.**
2. **Quantify improvements against a baseline.**
3. **Explain why your product matters within seconds.**
4. **Test your UI on someone unfamiliar with it.**
5. **Document and explain real limitations rather than hiding them.**
6. **Constrain scope; don't add technologies without a distinct contribution.**

---

## 8. Official Prize Structure

**Advertised:** $50,000+ in prizes, including cash awards and hardware.

### 8.1 Overall awards

| Award | Prize | Winners |
|---|---:|---:|
| Grand Prize | **$20,000 USD** | 1 |
| 2nd Place | **$10,000 USD** | 1 |
| 3rd Place | **$6,000 USD** | 1 |

### 8.2 Track awards

| Track winner | Prize | Winners |
|---|---|---:|
| Coding and Agentic Engineering | NVIDIA Jetson Orin Nano | 1 |
| Best Apps and Agents | NVIDIA Jetson Orin Nano | 1 |
| Personal AI | NVIDIA Jetson Orin Nano | 1 |
| Physical AI | NVIDIA Jetson Orin Nano | 1 |

### 8.3 Bonus and special awards

| Award | Prize | Winners | Eligibility detail |
|---|---|---:|---|
| Best Use of Tavily | **$3,000 USD** | 1 | Functional **runtime call to Tavily API** in the solution |
| City Winner Awards | **$500 USD each** | 20 | Eligible participating Builders & Brews IRL city event attendees |
| Most Valuable Feedback | **$100 USD + NVIDIA swag pack each** | 10 | Eligible feedback submissions |

**Official prize-combination limit:** Each project is eligible for **one Overall Award OR one Track Award**, plus **one Bonus Award**, subject to the rules. Do not assume multiple overall or track awards can stack.

**Special feedback judging:** Feedback submissions are judged on **completeness, viability, and potential impact**.

**City events:** Participating locations listed in the rules include Tokyo, Da Nang, Seoul, Kuala Lumpur, Singapore, Taipei, Tel Aviv, London, Copenhagen, Stockholm, Warsaw, Amsterdam, Berlin, Paris, Mexico City, New York City, **Toronto**, Boston, San Francisco and Los Angeles.

---

## 9. Internal Self-Scoring System — Recommended, Not Official

The official rules confirm **equal weights**, but do not specify a public 1–5 rating scale. Use the following only for internal assessment.

| Score | Interpretation |
|---:|---|
| 1 | Poorly evidenced or major gaps |
| 2 | Some capability, material issues |
| 3 | Functional, credible and understandable |
| 4 | Strong execution and supporting proof |
| 5 | Exceptional demonstration of the criterion |

| Criterion | Proposed rating | Weighted contribution |
|---|---:|---:|
| Technological Implementation | __ / 5 | 25% |
| Design | __ / 5 | 25% |
| Potential Impact | __ / 5 | 25% |
| Quality of the Idea | __ / 5 | 25% |
| **Total (internal)** | **__ / 20** | **100%** |

**Self-review procedure:** First complete the Stage One compliance checklist. Then enter a 1–5 rating for each of the four criteria and identify the weakest section. Prioritize a fix that simultaneously improves user experience and demonstrable value.

---

## 10. Final Six-Day Plan — Recommended

| Date | Focus | Output |
|---|---|---|
| Oct 24 | Eligibility, track choice, mandatory tech | Compliance matrix and frozen scope |
| Oct 25 | Reliability and end-to-end workflow | Working principal use case |
| Oct 26 | Design, onboarding and error states | Clear cold-start experience |
| Oct 27 | User tests, proof and comparisons | Feedback log and supporting metrics |
| Oct 28 | README, public repo, architecture and license | Reproducible repository |
| Oct 29 | Record, edit and publish ≤3-minute demo; complete Devpost draft | Submission-ready materials |
| **Oct 30** | Final checks and submit **before 1:00 PM EDT** | Final Devpost submission |

**Recommended buffer:** Submit ahead of the hard deadline. Uploading videos, fixing repository permissions, and completing form fields can take longer than expected.

### Suggested ≤3-minute demo outline — Recommended

| Time | Show |
|---|---|
| 0:00–0:20 | Specific user problem and why it matters |
| 0:20–0:45 | Immediate result / core value proposition |
| 0:45–1:50 | Main workflow operating on realistic input |
| 1:50–2:25 | Nebius + NVIDIA model integration and architectural choices |
| 2:25–2:50 | Evidence, outcome comparison, limitations |
| 2:50–3:00 | Distinctive takeaway |

For Physical AI, ensure the required **at least one minute of hardware or key module operation** appears within the maximum three-minute video.

---

## 11. Final Project Evaluation Worksheet

**Project name:** __________________________  
**Selected track:** __________________________  
**Audience:** __________________________  
**Core problem:** __________________________  
**Core benefit:** __________________________

### Stage One — Mandatory gate

- [ ] Meets selected track's goal.
- [ ] Uses Nebius Token Factory or Nebius AI Cloud.
- [ ] Uses at least one NVIDIA open-source model.
- [ ] Has a working principal capability.
- [ ] Required submission artifacts are ready.

**Gate status:** PASS / NOT READY

### Stage Two — Equal-weight rubric

#### A. Technological Implementation — 25%
**Internal score:** __ / 5  
**Best evidence:** __________________________  
**Biggest gap:** __________________________  
**Next fix:** __________________________

#### B. Design — 25%
**Internal score:** __ / 5  
**Best evidence:** __________________________  
**Biggest gap:** __________________________  
**Next fix:** __________________________

#### C. Potential Impact — 25%
**Internal score:** __ / 5  
**Best evidence:** __________________________  
**Biggest gap:** __________________________  
**Next fix:** __________________________

#### D. Quality of the Idea — 25%
**Internal score:** __ / 5  
**Best evidence:** __________________________  
**Biggest gap:** __________________________  
**Next fix:** __________________________

**Total internal score:** __ / 20

### Prize eligibility

- [ ] Relevant overall or track award.
- [ ] Tavily runtime API use, if seeking Best Use of Tavily.
- [ ] Eligible city participation, if seeking City Winner Award.
- [ ] Complete and useful technology feedback, if seeking Most Valuable Feedback.

### Top three changes before submission

1. __________________________
2. __________________________
3. __________________________

---

## 12. Source Notes and Verification

**Official Devpost:** https://nebiusglobalaihackathon.devpost.com/  
**Official rules — controlling source:** https://nebiusglobalaihackathon.devpost.com/rules  
**Official schedule:** https://nebiusglobalaihackathon.devpost.com/details/dates  
**Judges' discussion:** https://www.youtube.com/watch?v=LjCh-ZIyjx4

- Official rules were checked on **October 24, 2026**.
- Dynamic participant totals are intentionally omitted because they change.
- Panel comments are observational advice, **not** extra formal rules.
- The internal 1–5 scorecard, six-day plan, and three-minute storyboard are **recommendations**, not published official scoring methods.
- For discrepancies, the full Devpost **Official Rules** take precedence.
