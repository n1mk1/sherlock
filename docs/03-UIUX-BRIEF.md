# Sherlock · UI/UX Design Brief

Version 1.1 · 2026-10-24 (warm greys, light and dark modes, five magepunk accents) · The visual and interaction system. Pairs with the [App Flow](02-APP-FLOW.md) (what happens) and the [PRD](01-PRD.md) (what must be true).

---

## 1. Design intent

Sherlock keeps **Bklit's structure** (near-monochrome, hairline borders, generous space, no decoration) and gives it a calm, warm finish in the spirit of Wealthsimple: soft greys instead of black and white, serif headlines, roomy cards, nothing shouting. The palette is a low-contrast take on vintage magepunk tech: the warm greys of a worn field coat, charcoal instead of black, and one jewel-toned accent like a lit rune or an old brass instrument. Everything the user needs to read is text or a chart; color appears only where it carries meaning.

Two modes share one structure, and either mode takes any of five accents (§2.1):

- **Light.** Warm pale grey ground, slightly lighter cards, charcoal text, faint hairlines.
- **Dark.** Warm charcoal ground (not black), cards that barely lift off it, warm off-white text.

The accent is reserved for the thing you're looking at (the hovered widget, the linked card, the chart element that matters), links and the focus ring. Primary buttons are inverted foreground, never accent.

Three rules that decide most calls:
1. **Hierarchy by weight and space, not color.** If something needs to stand out, make it bigger, bolder, or give it room. Reach for the accent last.
2. **Charts are grey by default.** The accent marks the series, bar or value that matters in the story. Multi-series charts use the grey scale (`--chart-1` → `--chart-5`) and labels, not a rainbow.
3. **The data is the interface.** Every number can be clicked or hovered to see where it came from. Chrome stays thin so the data stays loud.

Reference mockups of every screen in both modes, with an accent comparison board: the "Sherlock UI examples" design canvas (https://claude.ai/artifact/UoLRwYCQJG7AEgYutXFr48, private to the owner until shared).

**The canvas is the owner's design** (confirmed 2026-10-24). Where it shows a detail this brief doesn't give, the canvas is the spec, and the detail is written into the section it belongs to (marked "as drawn").
- **Boards, all at 1440 px wide, in light and dark:**
  1. Empty library (§5.1)
  2. Dashboard (§3, §4.3–§4.8, §5.5)
  3. Cleaning in progress (§5.4)
  4. CSV tab (§4.7, §5.6–§5.7)
  5. Flow canvas (§5.10)
  6. Export notebook dialog (§5.13)

  Plus the accent options board (§2.1).
- **PNG exports** of every board are in `docs/Sherlock UI examples-png/`.
- **Theme helper.** Each board computes its colors from one theme helper that matches §2.1 exactly: the base tokens per mode, the five accents with a hover shade each, and `--info` switching to brass under Aether.

---

## 2. Design tokens

All tokens are CSS variables on `:root` (Light) and `.dark` (Dark), in the shadcn naming so shadcn and Bklit components pick them up unchanged. The accent tokens are set by a `data-accent` attribute on `<html>` (§9). Values are hex or `rgba`. Where Bklit defines a token, Sherlock keeps the name and sets its own value.

### 2.1 Color

Base tokens (the same for every accent):

| Token | Light | Dark | Use |
|---|---|---|---|
| `--background` | `#EEECE8` | `#1E1F22` | App ground and side panels |
| `--foreground` | `#2E3035` | `#E6E3DD` | Body text |
| `--foreground-2` | `#4A4D52` | `#C9C6BF` | Secondary text in prose, chart labels |
| `--muted` | `rgba(46,48,53,0.04)` | `rgba(230,227,221,0.04)` | Subtle fills (table header, code) |
| `--muted-foreground` | `#64666B` | `#9A9890` | Labels, captions (≥ 4.5:1 on ground, card and popover) |
| `--card` | `#F7F6F3` | `#25272B` | Widget and card surfaces |
| `--card-foreground` | `#2E3035` | `#E6E3DD` | |
| `--popover` | `#FBFAF8` | `#2B2D31` | Menus, tooltips, drawers, dialogs |
| `--border` | `rgba(46,48,53,0.08)` | `rgba(230,227,221,0.08)` | Hairlines |
| `--border-strong` | `rgba(46,48,53,0.16)` | `rgba(230,227,221,0.16)` | Focused or selected outlines |
| `--input` | `rgba(46,48,53,0.12)` | `rgba(230,227,221,0.12)` | Input borders |
| `--primary` | `#2E3035` | `#E6E3DD` | Primary button fill (inverted foreground, like Bklit) |
| `--primary-foreground` | `#F7F6F3` | `#1E1F22` | |
| `--secondary` | `rgba(46,48,53,0.04)` | `rgba(230,227,221,0.04)` | Secondary button fill |
| `--success` | `#3F6E4D` | `#7FB08E` | Verified, committed |
| `--warning` | `#96552A` | `#D89A5B` | Flagged, outdated |
| `--destructive` | `#A3362B` | `#E2786C` | Errors, delete |
| `--info` | `#456A91` | `#8FAACB` | Number chips (data-bound numbers); brass when the accent is Aether |
| `--info-soft` | `rgba(69,106,145,0.12)` | `rgba(143,170,203,0.12)` | Chip fill |
| `--changed` | `rgba(69,106,145,0.18)` | `rgba(143,170,203,0.18)` | Cells changed by cleaning (with a corner marker, §4.7) |
| `--predicted` | `rgba(63,110,77,0.10)` | `rgba(127,176,142,0.12)` | Predicted cells |

Accent tokens. `--accent` is the text-safe shade for its mode; `--accent-soft`, `--spotlight` and `--unsaved` are that shade at 0.12, 0.25 and 0.26 alpha; `--ring` and `--chart-accent` equal `--accent`; `--accent-foreground` is `--primary-foreground`.

| `data-accent` | Light `--accent` | Dark `--accent` | Mood |
|---|---|---|---|
| `verdigris` (default) | `#2F6B62` | `#6FB3A6` | Patina on old brass instruments. Calm and scientific. |
| `arcane` | `#6A4C93` | `#A88BD6` | Spellbook ink. The most openly magical. |
| `ember` | `#9A4A2E` | `#E08A62` | Forge glow on iron. Warm and urgent. |
| `aether` | `#2F6690` | `#6FB4D9` | Gaslight blue. `--info` switches to brass (`#8A5A33` / `#C9A063`) so chips stay distinct. |
| `brass` | `#8A5A33` | `#C9A063` | Polished fittings. The warmest and most vintage. |

Every accent shade passes 4.5:1 as text on `--background` and `--card` in its mode (5.0 to 7.2:1), and `--primary-foreground` on an accent fill passes too.

Chart tokens (Bklit's names):

| Token | Light | Dark |
|---|---|---|
| `--chart-1` … `--chart-5` | `#3F4247`, `#55575C`, `#6B6D72`, `#7A7C81`, `#87898D` | `#E6E3DD`, `#C9C6BF`, `#A9A69F`, `#8E8C86`, `#7D7F84` |
| `--chart-accent` | `var(--accent)` | `var(--accent)` |
| `--chart-grid` | `rgba(46,48,53,0.06)` | `rgba(230,227,221,0.06)` |
| `--chart-foreground` | `#64666B` | `#9A9890` |
| `--chart-label` | `#4A4D52` | `#C9C6BF` |
| `--chart-crosshair` | `rgba(46,48,53,0.3)` | `rgba(230,227,221,0.3)` |
| `--chart-tooltip-background` | `var(--popover)` | `var(--popover)` |
| `--chart-tooltip-foreground` | `var(--foreground)` | `var(--foreground)` |

Every chart grey is at least 3:1 against `--card` (WCAG 1.4.11).

Rules: never introduce a color outside these tables; only one accent is active at a time; semantic colors always come with an icon or text; the accent is never used for body text.

### 2.2 Typography

| Token | Family | Use |
|---|---|---|
| `--font-sans` | Inter | UI and body |
| `--font-serif` | Source Serif 4 | Screen titles, story card headlines, KPI values, the logo and the pitch line (weight 400, 500 for the logo) |
| `--font-mono` | Geist Mono | Numbers in tables and chips, code, SQL, timestamps |

Scale (px / line-height):

| Name | Size | Weight | Use |
|---|---|---|---|
| display | 32 / 1.1 | 400 serif | Screen titles ("Cleaning titanic3.csv") |
| kpi | 36 / 1.1 | 400 serif, letter-spacing −0.01em | KPI tile values |
| headline | 22 / 1.2 | 400 serif | Story card headline |
| headline-sm | 18 / 1.25 | 400 serif | Canvas card headline |
| title | 15 / 1.3 | 600 | Widget titles, panel titles |
| title-sm | 13 / 1.3 | 600 | Step summaries in the Changes panel |
| body | 14 / 1.55 | 400 | Everything |
| body-sm | 13 / 1.5 | 400 | Card prose, table cells |
| label | 12 / 1.4 | 500 | Chips, footers, axis labels |
| overline | 11 / 1.3 | 600, letter-spacing 0.08em, uppercase | Section labels ("Overview", "Target") |
| mono | 12.5 / 1.4 | 400 mono | Numbers, code |

Numbers in prose are chips (§4.6), never plain text.

### 2.3 Spacing, radius, elevation

- Base unit 4px. Common steps: 4, 8, 12, 16, 20, 24, 32.
- Panel padding 16px; widget padding 12px 16px; card padding 20px 22px. Dashboard gap 20px.
- `--radius: 10px` (Bklit's `.625rem`). Chips and badges 999px, except inline number chips (6px). Inputs and buttons 8px. Widgets, cards, dialogs 16px.
- Elevation is almost never used. Drawers, menus and the chat thread use `0 12px 32px rgba(46,48,53,0.10)` in Light and `0 12px 32px rgba(0,0,0,0.35)` in Dark. Nothing else has a shadow.
- The spotlight is the only glow: `box-shadow: 0 0 0 1px var(--accent), 0 0 14px var(--spotlight)`. "Subtle" halves the blur; "Off" keeps only the 1px ring.

### 2.4 Motion

| Token | Value | Use |
|---|---|---|
| `--duration-fast` | 120ms | Hover states, chip toggles |
| `--duration-base` | 200ms | Panels, drawers, spotlight |
| `--duration-slow` | 320ms | Thread expand, widget enter |
| Easing | `cubic-bezier(0.2, 0, 0, 1)` | All |

Motion (the library) is used for: widget enter (fade + 4px rise), card stream-in, spotlight fade, thread expand, canvas node placement. Charts animate on first render only (Bklit default) and not on re-query. With `prefers-reduced-motion` or the setting on, all durations become 0 and charts don't animate.

### 2.5 Iconography

lucide-react, 16px in controls, 14px in chips, 1.75px stroke. Icon-only buttons always have `aria-label` and a tooltip. No emoji anywhere.

---

## 3. Layout system

### 3.1 The frame

```
┌─────────────┬───────────────────────────────────────┬────────────────┐
│ left 240px  │ centre: flex 1, min 560px             │ right 340px    │
│ (rail 56px) │                                       │ (collapsed 0)  │
└─────────────┴───────────────────────────────────────┴────────────────┘
```

- Panels are shadcn Resizable groups; the user can drag the dividers (left 200–320, right 300–480). Sizes persist per browser.
- Below 1024px, both side panels become Sheets (slide-overs) opened from header icons; the centre takes the full width.
- The centre scrolls; the side panels scroll independently; headers are sticky.
- Every panel has a 1px `--border` divider. Side panels use `--background` in both modes; the dividers do the work.

### 3.2 Centre header

Two rows:
1. The tab switcher, centred: a segmented control (CSV · Dashboard · Flow), 36px tall, active segment `--secondary` fill with `--foreground` text; inactive `--muted-foreground`.
2. Context row: dataset name (title), version pill (mono, `--muted` fill, clickable), filter chips, then right-aligned actions for the tab.
   - **As drawn:**
     - The header has 12px top padding and 24px side padding.
     - The tab row and the context row are 12px apart, and the context row has 12px under it.
     - The version pill reads "v7 · 6 steps": the version, then the number of steps in its effective chain. It's 24px tall, 12px mono.
     - A tab that isn't available yet (Dashboard and Flow during cleaning) is drawn at 40% opacity, with its reason as the tooltip.

### 3.3 Dashboard grid

react-grid-layout, 12 columns, row height 40px, margin 20px. Widget minimum 3 × 5 cells; KPI tiles 3 × 3. Default sizes from the builder: KPI 3 × 3, bar/line 6 × 7, heatmap 6 × 8, driver analysis 8 × 8, table 6 × 8. Breakpoints are measured on the grid container, not the window: lg ≥ 640 (12 cols), md ≥ 480 (8), sm < 480 (4). At 1280px with both side panels open the container is about 700px, which is lg. Layout per breakpoint is stored; only lg is auto-generated, the rest are derived by the library and saved once the user touches them.

---

## 4. Components

Each component lists variants and states. All are shadcn primitives restyled by the tokens unless noted.

### 4.1 Buttons

| Variant | Look | Use |
|---|---|---|
| primary | `--primary` fill, `--primary-foreground` text, 36px, radius 8 | One per view: Import, Save changes, Run, Start |
| secondary | `--secondary` fill, 1px `--border`, 36px | Most actions |
| ghost | no fill, hover `--secondary` | Toolbar icons, menus |
| destructive | ghost until hover, then `--destructive` text | Delete |
| link | `--accent` text, underline on hover | "How do you know?", "Evidence", "Open widget" |

States: hover (fill +4% lightness), active (fill −4%), focus (2px `--ring` offset 2px), disabled (40% opacity, cursor default, tooltip with the reason when one exists), loading (spinner replaces the icon, label stays).

Minimum target 32 × 32 for icon buttons, 36px tall for text buttons; compact text buttons inside panels (the step Undo) may be 28px.

### 4.2 Chips

28px tall, 999px radius, label text, 10px horizontal padding, 1px border.

| Kind | Style |
|---|---|
| filter / scope ("3rd class · 709") | `--secondary` fill; × on hover removes |
| selection ("709 rows selected") | `--accent-soft` fill, `--accent` border |
| related widget | `--secondary`, hover shows spotlight on the target |
| recipe / method | `--secondary`; selected: `--primary` fill |
| status | success / warning / destructive text with icon, no fill |

### 4.3 Widget shell

```
┌ ⠿  Survival by sex          [All rows] [What drives this? ▾] [⋯] ┐  header 40px
│                                                                  │
│                         chart / table                            │  body
│                                                                  │
└ v7 · How do you know?                              updated 2s ago ┘  footer 28px
```

- Surface `--card`, 1px `--border`, radius 16. No shadow.
- Hover (not dragging/brushing): border becomes `--accent`, spotlight applied; its story card gets the same treatment.
- Related (another widget is hovered): border `--accent` at 45% opacity, spotlight at half strength.
- Selected / focused: 1px `--border-strong`.
- Updating: body at 60% opacity with a 2px `--accent` progress line under the header.
- Outdated: footer shows a warning chip "Outdated · Re-run".
- Error: body shows the message in `--muted-foreground`, Retry and Show query buttons.
- Collapsed: header only, 40px.
- Drag handle (⠿) is `--muted-foreground`, visible always, cursor grab; in Edit layout mode the whole header is the handle and a resize corner appears.

### 4.4 Charts (Bklit)

- Series colors from `--chart-1…5`; the story-relevant series or bar in `--chart-accent`. The builder marks which element is "the point" from its fact candidates (top contributor, the outlier, the trend line), which the story job's fact sheet may refine later, and the adapter colors only that.
- Axes: `--chart-label` text at 12px, `--chart-grid` lines, no axis lines, no chart titles inside the plot (the widget title is the title).
- Tooltip: `--popover` surface, mono numbers, the series name in `--muted-foreground`.
- Hovered element: 100% opacity, siblings 60%.
- Clicked (filter active): the clicked element keeps the accent; others 40%.
- Brush: a `--accent-soft` region with 1px `--accent` edges and handles.
- Empty: "No rows match the current filter" in `--muted-foreground`, with a "Clear filter" link.
- Custom visx charts (heatmap, histogram, box plot) follow the same tokens; the heatmap uses a single-hue grey ramp with the accent for the maximum cell.

As built (2026-10-25, D6.5): the custom charts are plain visx SVG. Histogram bars are radius 2, the tallest bin (or the builder's point) in the accent. The heatmap mixes `--chart-1` into `--card` by value (15–85%), the largest cell in the accent, with the value in mono inside cells big enough to hold it. The box plot draws whiskers to min and max, a `--card` box with a 1.5px series outline and a 2px median line; the point's box in the accent. Scatter points are 2.5px at 55% opacity. Each shows a small readout of the hovered element at its top right, and carries a one-sentence summary as its accessible label.

### 4.5 Story card

```
┌ OVERLINE: SURVIVAL BY SEX                    ⟳ changed  ✎ edited ┐
│ Women were nearly four times as likely to survive.      (serif) │
│ Women survived at [72.7%] and men at [19.1%]. The gap holds in   │
│ every class; it is narrowest in 3rd, where …                     │
│ Related: [Class × sex] [What drives survival?]                   │
│ ──────────────────────────────────────────────────────────────── │
│ ⛁ Evidence                                     [Edit] [Ask why]  │
└──────────────────────────────────────────────────────────────────┘
```

- Surface `--card`, 1px `--border`, radius 16, padding 20 22.
- Linked (its widget hovered): `--accent` border and spotlight.
- Badges in the top right: "changed" (warning chip), "edited" (pencil, muted), "outdated" (warning chip, clickable), "unverified" (dashed outline chip on hand-typed numbers), "Cites n cards" (synthesis).
- Overview card: no related chips, bullets instead of prose.
- Synthesis card: overline in `--accent`, "Cites n cards" footer.
- Direction card (building): dashed `--accent` border, a four-item checklist with ✓ / spinner / empty circle.
- Note node (canvas only, not a story card): `--muted` fill, no overline, no chips.

As built (2026-10-25, D6.3): the overline is the widget's title (11px, uppercase, muted); the headline is the serif at 18px; the body 14px in `--foreground-2`; related chips 24px tall. The footer has Evidence (link with a database icon), Edit and Ask why (ghost, small). A card being rewritten is at 70% with a spinning refresh icon. The suggestion sits in a dashed `--warning` box under the body.

### 4.6 Number chip

Inline, mono 12.5px, `--info-soft` fill, 1px `--info` border at 35%, radius 6, padding 0 5px, `--foreground` text. Hover: underline, cursor pointer; click opens the evidence drawer. Unverified: dashed border, `--muted-foreground` text, tooltip "Typed by you, not computed". Updating: a 400ms highlight pulse to `--accent-soft` when the value changes.

As built (2026-10-25): chips render from the card's latest fact-sheet value (`Card.facts`), and pulse to `--accent-soft` for 400 ms when it changes. The title tooltip is the fact's label.

### 4.7 Data grid (CSV tab)

Glide Data Grid themed from tokens:

| Element | Style |
|---|---|
| Header | `--muted` fill, title 13px/600, under it a 11px `--muted-foreground` line (type · missing %), a 14px-tall mini histogram in `--chart-3` |
| Row numbers | mono, `--muted-foreground`, `--muted` fill, sticky |
| Cell | body-sm; numbers mono right-aligned; text left; booleans as "true/false" in mono |
| Selected cell | 2px `--accent` outline |
| Selected range | `--accent-soft` fill, 1px `--accent` outline |
| Changed by cleaning | `--changed` fill plus a 2px `--info` line along the cell's top edge (as drawn on the CSV board, where the legend swatch carries the same top line), so it does not rely on color alone. This replaces the earlier 4px corner triangle |
| Flagged | 1px dashed `--warning` outline (inset) |
| Unsaved edit | `--unsaved` fill, 1px `--accent` outline, and a 4px `--accent` dot in the top-left corner so it differs from a selection by shape |
| Predicted | `--predicted` fill, italic |
| Invalid value | 1px `--destructive` underline |
| Quarantined row | 60% opacity, row number struck through |
| New (pending) row | `--unsaved` fill across the row, row number "new" |

Row height 32px; header 56px. Editors open in place with the same height.

As built (2026-10-25, D5): Glide draws on a canvas, so each style is drawn in code from the resolved tokens. Changed: `--changed` fill and the 2px `--info` top line. Flagged: a dashed `--warning` inset outline. Invalid: a 1px `--destructive` underline. Unsaved: `--unsaved` fill, a 1px `--accent` outline and a 4px `--accent` dot. Find matches: `--accent-soft` fill. Quarantined and to-be-deleted rows: muted text and a struck-through row number. The header draws the name (600, with ↑/↓ when sorted), "type · n% missing" and a 14px mini histogram (numeric bins, or category counts) in `--chart-3`. Number and boolean cells are mono; numbers right-aligned.

### 4.8 Chat bar and thread

- Bar: max 680px wide, centred, `--card` surface, 1px `--border`, radius 14, 52px tall, input 14px, send button 40 × 40 primary. Context chip on the left when present. `/` hint on the right.
  - **As drawn.** On dataset routes the bar sits at the bottom of the centre column (24px side and 20px bottom padding). On the empty library it sits in the centred column, 24px under the pitch.
  - The send button is radius 10 with an arrow icon.
  - Until chat exists (D4.3/D4.8), the input and send button are disabled and the placeholder names the state.
  - **As built (D4.8).** The bar is live on dataset routes once the file is profiled, and stays disabled on the empty library.
    - The context chip always shows: "All rows", or the filter (`col = value`), or the widget last clicked. Its × clears that context.
    - The thread opens 84px above the bar's bottom edge, with a 36px title row ("Ask about <name>", a collapse chevron).
    - While an answer streams, the thread shows the user's bubble, the blocks as they arrive, and the status line.
    - Answers render as follows:
      - numbers at 26px mono with the label under them
      - tables of up to 20 rows in a bordered box, with "Open these rows in CSV" or "Open all n rows in CSV" for row answers
      - charts 220px tall with "Pin to dashboard", or "Open the widget" when chat made one
      - text with number chips (§4.6)
    - "How do you know?" is a `<details>` disclosure listing each source's label and its SQL.
    - Suggested questions are cut (Implementation Plan §2.0, cut 9).
- Thread: expands above the bar to at most 40% of the centre height, `--popover` surface, radius 16, with the drawer shadow. Messages: the user's in a `--secondary` bubble right-aligned (max 80%); Sherlock's as plain text left-aligned with number chips, tables, charts and action buttons inline.
- Suggested questions: three ghost chips under the bar; they disappear once the thread has 3+ messages.
- Status line while working: `--muted-foreground` italic with a 3-dot indicator.
- Plans: a checklist with ✓ ticks as steps complete.
- Clarification: the question, then 2–3 secondary buttons in a row.
- Proposal: a `--card` block with the summary, a "Show code" disclosure, the impact line, Approve (primary) and Reject (ghost).

### 4.9 Drawers and dialogs

- Drawers (How do you know?, model card, Review changes, Changes slide-over): slide from the right over the right panel, 420px wide, `--popover`, drawer shadow, title row with ×.
- Dialogs (Settings, Import preview, confirmations): centred, max 580px (Settings) or 880px (Import preview), dimmed backdrop `rgba(46,48,53,0.28)` (Light) / `rgba(0,0,0,0.5)` (Dark).
- Esc and backdrop click close both. Focus is trapped and returned on close.

### 4.10 Toasts

sonner, bottom-right, `--popover`, 1px `--border`, 10 s for Undo toasts, 4 s otherwise. One line of text plus an optional Undo button (link style). Errors use the destructive icon and stay until dismissed.

### 4.11 Tooltips

`--popover` surface, body-sm, 6px 10px padding, 200ms delay, never longer than two lines except cell provenance (three lines with an Undo link).

### 4.12 Segmented control (settings, tabs)

4px padding container with `--muted` fill and 1px `--border`, radius 11; segments 36px tall, radius 8; active segment `--card` fill (Light) or `--secondary` (Dark) with `--foreground` text and a 1px `--border-strong`.

### 4.13 Empty states

Centred, max 420px wide: a 24px lucide icon in `--muted-foreground`, a title (title size), one sentence (body, muted), one primary action. Never more than one action, except the library empty state, which offers Upload and Try with sample.

---

## 5. Screen specifications

### 5.0 Library panel (left)

As drawn on the Dashboard and Empty library boards:
- 16px padding with 12px gaps.
- The top row has "Sherlock" (serif 20px, weight 500) and, on the right, the Settings gear as a 32px ghost icon button.
- Then the "Your CSVs" overline.
- **Rows.** Each row has 8px × 10px padding and radius 8: the name (weight 500), then a 12px status line:
  - `ready · v7` in `--success` with a check icon
  - `cleaning 42%` with a 2px progress bar (an `--accent` fill on a `--border` track)
  - `offer · 4 issues`, the issue count from the current version's data card
  - `profiling`
  - `failed` in `--destructive` with an alert icon

  The open dataset's row has the `--secondary` fill and a 1px `--border-strong` outline. Other rows are borderless and take the `--secondary` fill on hover.
- With no datasets it reads "No CSVs yet."
- At the bottom: Upload CSV and Try with sample, both secondary and full width.

The right panel (Stories), before there are cards, shows three 120px dashed placeholder cards (radius 16) and "Stories appear once the dashboard is built."

### 5.1 Library empty state (centre)

Drop zone: 2px dashed `--border-strong`, radius 16, 320px tall, icon `upload`, "Drop a CSV anywhere", "or" divider, Upload (secondary) and Try with sample (secondary). Below, the one-sentence pitch in `--muted-foreground`. On drag-over: dashed border becomes `--accent`, fill `--accent-soft`.

### 5.2 Import preview dialog

Header "Import titanic3.csv · 61 KB". A row of four controls (delimiter, encoding, header row, skip rows) as labeled selects/inputs. The preview table (shadcn Table, mono numbers, 20 rows, horizontal scroll). The detection line. Footer: Cancel (ghost), Import (primary).

### 5.3 Cleaning offer (centre)

A single `--card` panel, max 640px, centred vertically in the top third. Display title "Here's what I found". The summary as three lines with icons (missing, missing, flag). "All 7 issues" disclosure (a table: column · issue · count · proposed action). Three buttons in a row: Clean it for me (primary), Use as is (secondary), Go step by step (secondary, P1). Checkbox "Remember my choice".

### 5.4 Cleaning in progress (centre)

As drawn:
- **Layout.**
  - The content is centred at most 1200px wide, with 32px × 24px padding and 20px between blocks.
  - The step label and the elapsed time (mono) sit over a 4px progress bar.
  - The log card (padding 8px × 16px) and the side column (300px or wider) wrap onto one column when the centre is narrow.
  - The app switches columns on the centre panel's width (a container query), not the window's.
- **Log entries.**
  - Each entry is a grid of 56px (time, mono 12px), 24px (icon) and the rest, with 12px vertical padding and a hairline between entries.
  - The text is the column (mono 12.5px), then "· " and the issue in `--foreground-2`.
  - Candidate chips are 24px tall and 12px, and the chosen one is filled `--primary`.
  - The gate line is 12px in the gate's color: `--success` committed, `--warning` flagged, muted skipped, `--accent` running.
- **"So far".** Four tiles: values in mono 24px, labels in muted 12px, with the `--muted` fill and radius 8. The side cards use the 20px × 22px card padding.
- **Side panels.** The board shows the centre alone. The app keeps both side panels on this screen, because App Flow §5 needs the library row (progress, switching datasets) and the story placeholders.


Left 2/3: the live log card (`--card`), entries as a 3-column grid (mono time · icon · text), hairline between entries, auto-scroll. Candidate chips inside entries; the chosen one in `--primary` fill. Right 1/3: "So far" (2 × 2 stat tiles), "Checks" (list with ✓), budget line, and a dashed card "When cleaning finishes, the dashboard builds itself". Top: display title, subtitle, Stop (secondary), progress bar with step label and elapsed time.

### 5.5 Dashboard

As §3.3 and §4.3. The filter bar: chips left, Filter (ghost with icon), then Add widget (secondary), Edit layout (ghost toggle; active state `--secondary` fill). KPI tiles: label (label size, muted), value (kpi), sub-line (label, muted).

As built (2026-10-25, Implementation Plan D4.4–D4.7):
- **Context row.** The filter chip (`col = value`, ×) follows the version pill. On the right: Add widget, Edit layout, the job tray, then the dataset menu. The "Filter" builder button isn't built yet.
- **Layouts.** Only `lg` is stored by the builder. Until the user arranges a breakpoint, `md` and `sm` are packed from `lg` in reading order: KPIs at a quarter width (two to a row on `sm`), charts at full width on `sm`.
- **Widget shell.**
  - The KPI tile shows its value in mono at 28px, with "of n rows" under it. The widget title is the label.
  - Updating is a pulsing 2px `--accent` line under the header, with the body at 60%.
  - The scope chip shows "All rows", or "All rows · col = value" while a filter applies, and hides when the widget is narrower than 360px.
  - The footer shows "first 2,000 rows" when a result was capped.
- **Charts.** Bars are drawn with radius 4.
  - The point's bar or slice is `--chart-accent`, and the rest are `--chart-1`. Pie and ring slices cycle `--chart-1…5`, with a legend list beside the pie.
  - A dated result draws as a line or area. A result with too few dated points falls back to a table.
- **Click-to-filter.** A click on a bar or slice sets the filter on the widget's category column; clicking it again or the chip's × clears it. The clicked chart doesn't filter itself: its clicked element keeps the accent and the others fade to 40%.
- **Widget menu (⋯):**
  - Change view (only the views that can draw the result, with a check on the current one)
  - Duplicate
  - Collapse / Expand
  - Show as table (a check toggle, this browser only)
  - Delete (toast with Undo, 10 s)
- **Add widget drawer.** "Describe it" (a textarea and Add), then Quick templates: a segmented control (Bar of X by Y · KPI of X · Table), column selects, and Add template. A 20-widget warning shows as a warning toast.
- **"How do you know?" drawer.** One sentence naming the widget and version, the SQL in a `--muted` mono block, Copy, and the result row count.

### 5.6 CSV tab

Toolbar (40px): Add row, Add column (P1), Find (opens an inline find bar under the toolbar), Filter (toggles header filter row), Clean with AI (secondary with sparkle icon), Download (ghost, opens a menu: CSV · Notebook (.ipynb)). Right: the legend (three swatches with labels, label size). Header line: dataset name, version pill, unsaved count in `--accent`, Discard (ghost), Review changes (link), Save changes (n) (primary; disabled at 0). Grid fills the rest. Status bar 28px: left "3 cells · sum 452 · avg 150.7 · min 2 · max 300", right "Row 9 · home.dest".

As built (2026-10-25, cut 5): the toolbar holds Add row, Delete row, Restore (when it applies), Find, Clean with AI (secondary, sparkle icon), Download (ghost menu) and the legend on the right; the unsaved count, Discard and Save changes (n) (or "Rebase and save") are in the context row. The find bar is 40px under the toolbar: an input, Find, the match count, ×.

### 5.7 Changes panel (right, CSV tab)

Title "Changes" with the version pill. "Unsaved (yours)" card with accent border when non-empty. "Steps" overline, then step cards: number (mono, muted) · summary (title-sm) · detail line (label, muted) · Undo (secondary, 28px). The latest step has a `--border-strong` outline. Expanding a step reveals a code block (mono, `--muted` fill, Shiki-highlighted) or the edit list, then the impact lines. Footer links: Full cleaning report · Export notebook · Export pipeline (P1).

As built (2026-10-25): the "Unsaved (yours)" card has the `--accent` border and a mono line per pending edit with ×; a running clean shows a card with its label, a 2px `--accent` progress bar and Stop. Code shows in a plain `--muted` mono block (no Shiki). Undo opens a confirmation dialog when the server asks for one.

### 5.8 ML setup (inside a widget)

Stacked sections with overlines: Target (select), Features (chip wrap; excluded chips struck through in muted with a tooltip), Rows (scope chip + "Use selection" link when a brush exists), Method (segmented: Auto · Linear · Logistic; disabled segments with tooltips), More (disclosure with the manifest's params as labeled inputs), Baselines (a 3-row mini table: everyone-majority, best one-column rule, model [pending]). Footer: estimate text ("about 10 s"), Cancel (ghost), Run (primary).

As built (2026-10-25, `web/src/components/ml/MlSetup.tsx`, within cuts 4 and 7):
- **Layout.** The sections stack inside the widget body (scrolling when the widget is short), with 11px uppercase overlines.
- **Target.** A native select of the recipe's `targets`, with a muted line ("Categories: scored by Accuracy.").
- **Features.** 24px pill chips: used in `--border-strong` on `--card`; excluded struck through on `--muted` with "Left out: <reason>" as the tooltip; forced-in with a `--warning` border and a warning icon. Re-including one shows a `--warning` line with the reason.
- **Rows.** The scope chip ("All rows · 1,309 with survived", plus the filter when used) and an "Only the filtered rows" checkbox when a dashboard filter is active.
- **Method.** No segmented control (cut 4): a line, "Auto: tries logistic regression, gradient boosting and a random forest on the same folds and keeps the best."
- **More.** A native disclosure with the manifest's integer params as labeled number inputs.
- **Baselines.** A two-row table plus "Model: pending".
- **Footer.** Estimate, Cancel (ghost) and Run (primary). Run is disabled while the preview has an error, and that error replaces the baselines.

The analysis dropdown is a 28px flask icon button left of the widget menu. Its menu has the group overlines, disabled items with their reason in an 11px line, then "Plain chart (SQL)" as a check item.

### 5.9 Model card drawer

Sections: Verdict (headline-sm serif), Data (rows, version, scope), Excluded columns (list with reasons), Method (name, params), Baselines vs model (table with intervals; the model row bold), Metrics (per method: coefficients table with CI and p; or importance list), Warnings (warning chips with suggestions), Actions: Compare with Auto (secondary), Who did it get wrong? (link), Re-run (secondary when outdated).

As built (2026-10-25, `web/src/components/ml/ModelCardDrawer.tsx`): the 420px drawer titled "Model card".
- **Verdict.** In 20px serif semibold. When outdated, a `--warning` bordered row follows with Re-run.
- **Data.** Target, task, version, scope, rows used of the total, and rows without the target. Plus the sample when there is one.
- **Excluded columns.** Mono and struck through, each with its reason.
- **Method.** "Auto picked <model> by 5-fold stratified cross-validation (seed 42)", the other models with their scores, and the params.
- **Baselines vs model.** Columns: the metric and the 95% interval. The model row is bold, followed by AUC or MAE.
- **Importance.** A list with values.
- **Warnings.** Bordered `--warning` boxes with the suggestion under the text.
- **Limits.** As specified.
- **Show the code.** It reveals `repro.py` in a mono block.
- **Not built.** Compare with Auto (cut 4), Who did it get wrong? (cut 7) and the coefficients table (cut 4).

The analysis widget's body follows App Flow §9 steps 3–5:
- **While running.** The progress line, a 4px `--accent` bar, and the steps with check and spinner icons.
- **The result.** The verdict line (in `--warning` for no signal). Then up to twelve importance rows: the name, a 12px bar in `--chart-1` (the top factor or the open one in `--chart-accent`) and the value in mono.
- **Partial dependence.** A 64px SVG mini chart in a bordered figure under its bar: a line for numbers, bars for categories, with an accessible label listing the points.
- **Footer.** It adds "Model card", and "Outdated" with a small Re-run in `--warning`.

### 5.10 Flow canvas

Canvas background `--background` with a dot grid (`--border` dots, 22px spacing). Nodes: story cards at 240px width using the §4.5 card style at headline-sm; notes 220px with `--muted` fill; synthesis with `--accent` overline; direction with dashed `--accent` border. Edges: 1.5px `--muted-foreground` curves with a small arrowhead; AI-made edges in `--accent`; suggested edges (P1) dashed. Labels: label-size chips at the midpoint, `--card` fill. Selected node: 2px `--accent` outline offset 2px. Zoom control bottom-left (two ghost buttons in a `--card` pill), minimap bottom-right (132 × 84, `--card`, viewport rectangle in `--info`).

Palette (right panel): search input, then rows (drag handle · name · "on canvas" / "not placed" in muted), then a "Try asking" card, then Export: Notebook (.ipynb) (P0) and Obsidian (.canvas) (P1).

### 5.11 Settings dialog

As built (2026-10-24), with cut 1: four settings, each a segmented control with a help line.
- Mode: Light · Dark · System.
- Accent: each with a dot in its color for the active mode.
- Chat bar: Pinned · Auto-hide · Hidden.
  - Auto-hide fades the bar out until it's pointed at or focused.
  - Hidden removes it.
- After upload: Ask me · Always clean · Never clean.

It opens from the library panel's gear, or with `?settings=1` in the URL. The other five settings and the "two per row" layout return when cut 1 is lifted.

Title (display), × button. Nine labeled segmented controls in a single column (two per row for Default tab and Spotlight). The Accent control shows a dot of each accent's color beside its name. Help text under each in body-sm muted. Footer: "Saved to your Sherlock profile" (muted) and Done (primary).

### 5.12 Shortcuts sheet (`?`)

A dialog listing shortcuts in two columns grouped by tab (Global · Dashboard · CSV · Flow · Chat), keys as `<kbd>` in mono.

### 5.13 Export notebook dialog

Centred dialog, max 520px. Title "Export notebook" (display). One body-sm sentence describing what will be rebuilt, with the counts in mono. Four checkboxes (shadcn Checkbox, label on the right, help text in muted under each). The Order segmented control (two segments; the disabled one carries a tooltip). Conditional notes in a `--muted` box with the warning icon (job running, unsaved edits) and, for unsaved edits, a secondary "Save and export" button inside the box. Footer: Cancel (ghost), Export (primary). The `notebook` lucide icon (`book-open`) is used for every Export notebook entry point; "Export notebook" is the label everywhere, never "Download .ipynb" alone.

Progress: a toast "Preparing notebook…" with a 2px `--accent` progress line; on completion the toast reads "Notebook ready" with "Download again" (link). Export is never a blocking modal.

As built (2026-10-25): the title is in the serif display face; the checkboxes are native, tinted with `--accent`; the Flow reading path segment is shown dimmed with its tooltip and can't be chosen. The progress is sonner's loading toast rather than a 2px line.

### 5.14 Dataset menu (⋯)

A ghost icon button at the right end of the context row on all tabs. Menu items: Export notebook (icon `book-open`), Download CSV (`download`), Rename (`pencil`), Delete (destructive, `trash-2`). Keyboard: Ctrl+Shift+E opens Export notebook directly.

### 5.15 Job tray, banners and small disclosures

- Job tray: a ghost icon button in the centre header with a count badge; its popover lists jobs (label, progress bar, Cancel or Retry), and completed ones stay for 1 minute.
  - **As built (D4.4).** The `activity` icon carries an `--accent` count of queued and running jobs.
  - The popover is 320px. Each row shows the job ("Cleaning · titanic3.csv"), its progress label and a 2px bar, then Cancel.
  - Done and cancelled jobs show for a minute. Failed ones stay, with the error in `--destructive`, Retry and a dismiss ×.
  - It polls `GET /jobs` every 3 s.
- Library rail (D4.4): the « button beside the gear collapses the panel to a 56px rail with dataset initials (mono, 36px), Upload, Try with sample, the gear, and » to expand. Its dividers resize the panels (left 200–320, right 300–480; arrow keys move 16px), and sizes persist in this browser.
- Library row menu (D4.5): a ⋯ on hover with Rename (inline), Download original CSV and Delete (confirm, then a toast with Undo for 10 s). The dataset menu (⋯) in the context row has Download CSV, Rename (a dialog) and Delete; Export notebook joins it with D5.6.
- Offline banner: a full-width `--muted` strip under the header with the warning icon and "You're offline. Edits are kept locally."
- Cascade progress line: a 2px `--accent` line under the header with a label-size caption ("Updating 4 widgets and 3 stories").
- Chat sources disclosure: a "How do you know?" link under each answer that expands the SQL, run or step references in a `--muted` mono block.
- "Data changed" badge: a warning chip on user-edited cards with a "See suggestion" link.

---

## 6. Interaction rules

- **Hover linking** fires after 80ms of hover and clears 120ms after leaving, so moving across widgets doesn't flicker. Disabled while dragging, resizing or brushing, and while a drawer is open.
- **Click-to-filter vs brush**: a click without movement filters; movement over 6px starts a brush. Brush only begins inside the plot area, never on axes or the header.
- **Drag**: only from the handle, unless Edit layout is on. While dragging, the dragged widget is 90% opacity with a `--border-strong` outline; the drop placeholder is `--muted`.
- **Keyboard**: every action in a menu has a shortcut listed on `?`. Tab order: left panel → tabs → context row → grid (widgets are focusable; Enter opens the menu) → right panel → chat bar. Arrow keys move between widgets when the grid has focus. Single-key global shortcuts (`/`, `?`) fire only when no cell, input or editor has focus.
- **Focus**: 2px `--ring` with 2px offset, everywhere, including grid cells and canvas nodes.
- **Loading**: skeletons (not spinners) for widgets and cards; spinners only in buttons and the cleaning state.
- **Undo**: every destructive action has a toast with Undo; every step has Undo in the Changes panel; pending edits have Ctrl+Z.
- **Confirmation dialogs** only for: deleting a dataset, discarding pending edits, undoing a non-latest step, and undoing the automatic typing step (step 1). Everything else is undoable instead.

---

## 7. Copy guidelines

- Plain words. "What drives this?" not "Feature importance". "Find groups" not "Clustering". The technical name appears in the model card.
- Numbers are never written in generated prose except as chips.
- Verdicts are one sentence and honest: "No better than the simple rule." is a valid verdict.
- Correlational findings never use "causes", "because", "leads to" in AI text. Edge labels typed by the user can say anything.
- Errors say what happened and what to do, in that order, in one or two sentences. No codes, no stack traces.
- The notebook's Markdown cells use the same voice as story cards; its code cells carry one comment per block saying what the block does in plain words, so the notebook reads as a report even to someone who skips the code.
- Empty states say what will appear here and offer one action.
- Sherlock refers to itself as "I" in chat and as "Sherlock" in UI text.

---

## 8. Accessibility checklist

- Text contrast ≥ 4.5:1 against its surface in both themes (checked for every pair above; `--muted-foreground` is tuned to pass on `--background` and `--card`).
- Chart marks and other non-text graphics ≥ 3:1 against `--card` (WCAG 1.4.11); the chart tokens above are tuned to pass.
- Semantic colors always paired with an icon or text.
- All interactive elements are real buttons, links or inputs; icon-only buttons have `aria-label`.
- Charts have an accessible table alternative: "Show as table" in the widget menu, and `aria-label` summarizing the chart from its fact sheet.
- Grid cells and canvas nodes are keyboard reachable; cell provenance is available via a keyboard shortcut (Ctrl+I) as well as hover.
- Drawers and dialogs trap focus and restore it; Esc closes.
- `prefers-reduced-motion` and the setting disable animation; the spotlight becomes a 1px ring.
- Nothing relies on hover alone: every hover reveal (provenance, card linking) has a click or keyboard path.

---

## 9. Theme switching

- `<html class="dark">` toggles Dark mode and `<html data-accent="verdigris">` (or `arcane`, `ember`, `aether`, `brass`) sets the accent tokens; the shadcn ThemeProvider pattern persists both and follows the system mode when set to.
- Bklit charts, Glide Data Grid (via a theme object built from the CSS variables at runtime and rebuilt on theme change), React Flow (node styles from tokens) and Shiki (two themes: a custom grey dark theme and GitHub Light) all switch with it.
- Fonts are loaded once; both modes use the same families and weights.
- Screenshots and "Copy as image" render with the active theme.
- Implementation (2026-10-24):
  - **Where the tokens live.** Every token in §2 is in `web/src/app/theme.css` and is exposed to Tailwind in `web/src/index.css`, for example `bg-card`, `text-info` and `bg-accent-soft`.
  - **Derived tokens.** `--accent-soft`, `--spotlight`, `--unsaved` and `--info-soft` are computed with `color-mix()` from the active `--accent` or `--info`, so they follow every accent and mode without extra hex values. Under Aether, `--info-soft` follows the brass `--info`.
  - **Two more `<html>` attributes**, set from the settings:
    - `data-spotlight="off"|"subtle"|"full"` picks the spotlight shadow (`--spotlight-shadow`, default subtle).
    - `data-reduce-motion="on"|"off"` overrides the OS preference. With motion reduced, every `--duration-*` is 0 and the spotlight is the 1px ring.
  - **Tokens the brief doesn't name.** `--popover-foreground` and `--secondary-foreground` equal `--foreground` (shadcn needs them). The radii are named `--radius-chip`, `--radius-number-chip`, `--radius-control` and `--radius-surface`, and the overlay shadow is `--shadow-overlay`.
  - **Fonts** are self-hosted from `@fontsource-variable` (Inter, Source Serif 4, Geist Mono), so they're served from the app's own origin.
  - **Test.** `web/src/app/theme.test.ts` checks the base and accent values against §2.1 and the §8 contrast rules: accents and muted text at 4.5:1, chart greys at 3:1.

---

## 10. What's deliberately not in the design

No gradients, no illustration, no hero imagery, no card shadows, no colored chart palettes, no badges on every element, no onboarding tour (the empty state and suggested questions do that job), no dark-mode-only or light-mode-only features.
