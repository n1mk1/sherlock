# User tests and the baseline comparison

PRD §4 asks for two pieces of evidence, both summarized in the README and the video:

1. **Cold-start user test.** At least three people who have never seen Sherlock reach a sourced answer on a CSV of their choice, without help. Record the time to the first sourced answer, where they hesitated, and what they said.
2. **Baseline comparison.** The same three questions on the same file, by hand in a spreadsheet and with Sherlock: time, steps, and how many answers can be traced to their source.

**Status (2026-10-25).** The Sherlock half of the baseline is measured below, on the live site. The cold-start sessions and the by-hand timings need real people and haven't been run yet; their tables are empty on purpose. Nothing in this file is estimated or invented: a blank means not measured.

---

## 1. Cold-start user test

### Protocol

- **Who.** Three people who have never seen or heard about Sherlock, ideally people who handle exports at work (sales, operations, HR, a small business owner). Not teammates, not hackathon participants who saw a demo.
- **Setup.** A laptop with a fresh browser profile (or a private window) open on https://sherlock-anw3.onrender.com. Their own CSV if they have one; otherwise they choose one of `api/samples/sales_dated.csv`, `reviews_text.csv` or `wide_messy.csv`.
- **The only instruction.** "This tool answers questions about a spreadsheet. Load your file and find out something you'd want to know about it. Think aloud." No tour, no hints. Answer questions about the task, not the tool.
- **Stop** at the first answer that shows its source (a chat answer whose "How do you know?" holds a query, or a story card whose number opens its evidence), or after 10 minutes.
- **Record:** the time from page load to the first sourced answer; each place they paused for more than about 5 seconds or asked something; what they said, verbatim where possible; whether they opened "How do you know?" on their own; and what we changed because of it (with the commit).

### Results

| # | Who (role, no names) | CSV | Task they chose | Time to first sourced answer | Where they hesitated | What they said | Opened the source unprompted? | What we changed |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |

---

## 2. Baseline comparison

**File:** `titanic3.csv` (1,309 passengers, 14 columns), the bundled sample.

**Questions** (chosen so a spreadsheet user can answer each with a filter or a pivot table):

1. What was the survival rate for women and for men?
2. What was the average fare in each passenger class?
3. How many passengers under 18 survived?

### With Sherlock (measured 2026-10-25, live site, a fresh browser identity)

Steps: open the site, click **Try with sample (Titanic)** (1 click; the cleaned, charted sample opened in 0.28 s), then type each question in the chat bar (1 step each).

| Question | Answer | Time (question sent → answer) | Steps | Traceable to its source? |
|---|---|---|---|---|
| 1. Survival rate by sex | female 72.7%, male 19.1% | 11.2 s | 1 | Yes: the SQL under "How do you know?" |
| 2. Average fare by class | class 1: 87.51, class 2: 21.18, class 3: 13.30 | 8.3 s | 1 | Yes: the SQL |
| 3. Survivors under 18 | 84 | 10.9 s | 1 | Yes: the SQL |
| **Total** | | **about 31 s, plus 0.3 s to open the sample** | **4** | **3 of 3** |

The values were checked against DuckDB on the same data: questions 1 and 2 match the raw file to every digit shown, except class 3's fare (13.30 against 13.3029 raw), because the cleaning filled the one missing fare from its class median. Question 3 is 84 on Sherlock's version and **81 on the raw file**: the cleaning filled 263 missing ages from the median of each passenger's title, class and sex, which gave three more survivors an age under 18. Both numbers are right for their data, and Sherlock's difference is traceable: the step is in the Changes panel with its code and decision, and Undo brings back 81. A spreadsheet count on the raw file silently leaves out every passenger without an age.

### By hand in a spreadsheet (to be measured)

Protocol: one person who uses spreadsheets at work, starting from the raw `titanic3.csv` opened in Excel, Google Sheets or LibreOffice, a stopwatch from the moment the file is open to each answer, counting each filter, formula or pivot table set-up as a step. Afterwards, ask: "If your manager asked how you got this number, what would you show?", and count an answer as traceable only if the formula or pivot that produced it is still there and points at the data.

| Question | Answer | Time | Steps | Traceable to its source? |
|---|---|---|---|---|
| 1. Survival rate by sex | | | | |
| 2. Average fare by class | | | | |
| 3. Survivors under 18 | | | | |
| **Total** | | | | |

### Comparison (fill in once both halves are measured)

| | By hand | With Sherlock |
|---|---|---|
| Total time | | about 31 s (and 0.3 s to open the sample) |
| Total steps | | 4 |
| Answers traceable to their source | | 3 of 3 |
| Cleaning recorded and reversible | | yes (two steps, each with Undo) |
