# Sherlock · UI/UX Design Brief

Version 1.1 · 2026-10-24 · The visual and interaction system: tokens, components, copy and accessibility. Pairs with the [App Flow](02-APP-FLOW.md) (screens, states, transitions) and the [PRD](01-PRD.md) (what must be true).

A "Not built yet" line marks a spec the code doesn't meet yet. "Removed by cut N" means the cut order dropped it (plan §5, applied in plan §2.0).

---

## 1. Design intent

Sherlock keeps **Bklit's structure** (near-monochrome, hairline borders, generous space, no decoration) with a calm, warm finish in the spirit of Wealthsimple: soft greys instead of black and white, serif headlines, roomy cards. The palette is a low-contrast take on vintage magepunk tech: warm greys, charcoal instead of black, and one jewel-toned accent. Everything the user reads is text or a chart; color appears only where it carries meaning.

Two modes share one structure, and either takes any of five accents (§2.1):

- **Light.** Warm pale grey ground, slightly lighter cards, charcoal text, faint hairlines.
- **Dark.** Warm charcoal ground (not black), cards that barely lift off it, warm off-white text.

The accent marks the thing you're looking at (the hovered widget, the linked card, the chart element that matters), links and the focus ring. Primary buttons are inverted foreground, never accent.

Three rules decide most calls:
1. **Hierarchy by weight and space, not color.** Make it bigger, bolder or give it room. Reach for the accent last.
2. **Charts are grey by default.** The accent marks the series, bar or value that matters. Multi-series charts use the grey scale (`--chart-1` → `--chart-5`) and labels, not a rainbow.
3. **The data is the interface.** Every number can be clicked or hovered to see where it came from. Chrome stays thin.

**Reference mockups.** The "Sherlock UI examples" design canvas (https://claude.ai/artifact/UoLRwYCQJG7AEgYutXFr48, private to the owner until shared) is the owner's design. Where it shows a detail this brief doesn't give, the canvas is the spec, and the detail is written into its section here, marked "as drawn".
- **Boards** (1440 px wide, light and dark): 1. Empty library (§5.1) · 2. Dashboard (§3, §4.3–§4.8, §5.5) · 3. Cleaning in progress (§5.4) · 4. CSV tab (§4.7, §5.6–§5.7) · 5. Flow canvas (§5.10) · 6. Export notebook dialog (§5.13) · plus the accent options board (§2.1).
- **PNG exports** aren't in the tree; git history has them (`git show 4dfc8ef:"docs/Sherlock UI examples-png/2 · Dashboard.png"`).
- **Theme helper.** Each board computes its colors from one helper that matches §2.1: the base tokens per mode, the five accents with a hover shade each, and `--info` switching to brass under Aether.

---

## 2. Design tokens

All tokens are CSS variables on `:root` (Light) and `.dark` (Dark) in `web/src/app/theme.css`, in shadcn naming so shadcn and Bklit components pick them up unchanged. `data-accent` on `<html>` sets the accent (§9). Values are hex or `rgba`. Where Bklit defines a token, Sherlock keeps the name and sets its own value. Tailwind 4 has no config file: `web/src/index.css` exposes the tokens as utilities in an `@theme inline` block (§9).

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
| `--info` | `#456A91` | `#8FAACB` | Number chips (data-bound numbers); brass under Aether |
| `--info-soft` | `--info` at 0.12 | `--info` at 0.12 | Chip fill |
| `--changed` | `rgba(69,106,145,0.18)` | `rgba(143,170,203,0.18)` | Cells changed by cleaning (with a 2px `--info` top line, §4.7) |
| `--predicted` | `rgba(63,110,77,0.10)` | `rgba(127,176,142,0.12)` | Predicted cells |

Accent tokens. `--accent` is the text-safe shade for its mode. `--accent-soft`, `--spotlight` and `--unsaved` are that shade at 0.12, 0.25 and 0.26 alpha. `--ring` and `--chart-accent` equal `--accent`; `--accent-foreground` is `--primary-foreground`.

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

Rules: never introduce a color outside these tables; one accent is active at a time; semantic colors always come with an icon or text; the accent is never body text.

### 2.2 Typography

| Token | Family | Use |
|---|---|---|
| `--font-sans` | Inter | UI and body |
| `--font-serif` | Source Serif 4 | Screen titles, story card headlines, the logo and the pitch line |
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
| body | 14 / 1.55 | 400 | Everything (the `body` default) |
| body-sm | 13 / 1.5 | 400 | Card prose, table cells |
| label | 12 / 1.4 | 500 | Chips, footers, axis labels |
| overline | 11 / 1.3 | 600, letter-spacing 0.08em, uppercase | Section labels ("Overview", "Target") |
| mono | 12.5 / 1.4 | 400 mono | Numbers, code |

Numbers in prose are chips (§4.6), never plain text.

Where the screens step off the scale:
- Serif at weight 600: story card headline 18px (§4.5), canvas card headline 15px (§5.10), model card verdict 20px (§5.9), Export notebook title 22px (§5.13). The logo is serif 20px at 500.
- Widget titles are 13px/600 (§5.5). KPI values are mono 28px at 500, not the serif `kpi` style (§5.5).
- Changes panel step summaries are 13.5px at 500 (§5.7).
- The cleaning-in-progress title is serif 26px until the centre is 768px wide, then 32px (§5.4).

### 2.3 Spacing, radius, elevation

- Base unit 4px. Common steps: 4, 8, 12, 16, 20, 24, 32.
- Panel padding 16px; widget padding 12px 16px; card padding 20px 22px. Dashboard gap 20px.
- `--radius: 10px` (Bklit's `.625rem`). Chips and badges 999px (`--radius-chip`), except inline number chips at 6px (`--radius-number-chip`). Inputs and buttons 8px (`--radius-control`). Widgets, cards and dialogs 16px (`--radius-surface`).
- Elevation is almost never used. Drawers, menus and the chat thread use `--shadow-overlay`: `0 12px 32px rgba(46,48,53,0.10)` in Light, `0 12px 32px rgba(0,0,0,0.35)` in Dark. Nothing else has a shadow.
  - Not built yet: dialogs, popovers (job tray, the card editor's number picker), the custom charts' readout and the narrow-screen slide-overs also use `--shadow-overlay`; the column-note tooltip has Tailwind's `shadow-md`, and Bklit's chart tooltip its own soft shadow.
- The spotlight is the only glow, `--spotlight-shadow`: `0 0 0 1px var(--accent), 0 0 14px var(--spotlight)` at Full, a 7px blur at Subtle (the default), the 1px ring alone at Off. The Spotlight setting is removed by cut 1, so the app shows Subtle unless a saved setting says otherwise (§9).

### 2.4 Motion

| Token | Value | Use |
|---|---|---|
| `--duration-fast` | 120ms | Hover states, chip toggles |
| `--duration-base` | 200ms | Panels, drawers, spotlight |
| `--duration-slow` | 320ms | Thread expand, widget enter |
| `--ease` | `cubic-bezier(0.2, 0, 0, 1)` | All |

Motion (the library) is for: widget enter (fade + 4px rise), card stream-in, spotlight fade, thread expand, canvas node placement. Charts animate on first render only (Bklit default), not on re-query. With `prefers-reduced-motion` or the setting on, every `--duration-*` is 0 and charts don't animate.

- Not built yet: only the Bklit charts use Motion. Widgets, cards, the thread and canvas nodes appear with no enter animation, drawers don't slide in, and the spotlight fades over `--duration-fast`.
- The Reduce motion setting is removed by cut 1, so the OS preference decides unless a saved setting says otherwise (§9).
- Not built yet: reduced motion in full. Bklit's line and area animations follow the OS preference but not a saved setting; its bar and pie entry animations, Tailwind's pulse and spin, smooth scrolling to a widget or card, the number chip's 400ms pulse and the analysis progress bar's 500ms transition ignore both.

### 2.5 Iconography

lucide-react, 16px in controls, 14px in chips, 1.75px stroke. Icon-only buttons always have `aria-label` and a tooltip. No emoji anywhere. (Not built yet: see §4.1 for the stroke and tooltip gaps.)

---

## 3. Layout system

### 3.1 The frame

```
┌─────────────┬───────────────────────────────────────┬────────────────┐
│ left 240px  │ centre: flex 1, min 560px             │ right 340px    │
│ (rail 56px) │                                       │ (collapsed 0)  │
└─────────────┴───────────────────────────────────────┴────────────────┘
```

- **Dividers** (`AppShell.tsx`, Sherlock's own, not shadcn Resizable): a 1px `--border` line with a 6px grip. Drag to resize: left 200–320, right 300–480. Sizes persist per browser.
  - Each is a focusable `role="separator"` (WAI-ARIA window splitter): `aria-valuenow` is the panel's width in pixels, `aria-valuemin`/`aria-valuemax` are the bounds, the text is "240 pixels wide", and ← / → move it 16px.
- **Below 1024px** both side panels become slide-overs opened from header icons ("Show your CSVs", "Show stories"), each up to 320px wide (85% of a narrow screen), sliding in over `--duration-base` above a dimmed backdrop that closes them on click; the centre takes the full width.
  - Not built yet: the slide-overs don't trap focus or close on Esc, and the backdrop has no dark-mode variant.
- The centre scrolls; the side panels scroll independently; headers are sticky.
- Side panels use `--background` in both modes; the dividers do the work.
- Not built yet: the centre has no 560px minimum, and the right panel can't be collapsed at 1024px and up.

### 3.2 Centre header

`CenterHeader.tsx`. As drawn: 12px top padding, 24px side padding, 12px between the rows and 12px under the context row.

1. **Tab switcher**, centred: a segmented control (CSV · Dashboard · Flow) styled as §4.12, segments 36px tall; active `--foreground`, inactive `--muted-foreground`. A tab that isn't available yet (Dashboard and Flow during cleaning) is at 40% opacity with its reason as the tooltip.
2. **Context row**: dataset name (title), version pill, filter chips, then the tab's right-aligned actions.
   - The version pill reads "v7 · 6 steps" (the version, then the steps in its effective chain): 24px tall, 12px mono, `--muted` fill. Not built yet: it isn't clickable (App Flow has a click open the Changes panel).

### 3.3 Dashboard grid

react-grid-layout (`Dashboard.tsx`), 12 columns, row height 40px, margin 20px.
- **Sizes.** Widget minimum 3 × 5 cells; KPI tiles 3 × 3. Builder defaults (`DEFAULT_SIZE` in `api/sherlock/widgets/layout.py`): KPI and gauge 3 × 3; bar, line, area, pie, ring, scatter, histogram, box, ROC and residuals 6 × 7; heatmap, table and confusion 6 × 8; importance (driver analysis) and coefficients 8 × 8.
- **Breakpoints** are measured on the grid container, not the window: lg ≥ 640 (12 cols), md ≥ 480 (8), sm < 480 (4). At 1280px with both side panels open the container is about 700px, which is lg.
- **Layouts per breakpoint.** The builder stores only lg. Until the user arranges md or sm, Sherlock derives them from lg (§5.5) and saves them once touched.

---

## 4. Components

Each lists variants and states. All are shadcn primitives restyled by the tokens unless noted.

### 4.1 Buttons

`ui/button.tsx`. Sizes: default 36px, `sm` 28px (13px text), `icon` 32 × 32.

| Variant | Look | Use |
|---|---|---|
| primary | `--primary` fill, `--primary-foreground` text, 36px, radius 8 | One per view: Import, Save changes, Run, Start |
| secondary | `--secondary` fill, 1px `--border`, 36px | Most actions |
| ghost | no fill, hover `--secondary` | Toolbar icons, menus |
| destructive | ghost until hover, then `--destructive` text | Delete |
| link | `--accent` text, underline on hover | "How do you know?", "Evidence", "Open widget" |

States:
- Hover: fill +4% lightness; active: fill −4%. A primary button does this with a brightness filter (110% and 95%).
- Focus: 2px `--ring` outline, offset 2px.
- Disabled: 40% opacity, cursor default, tooltip with the reason when one exists.
- Loading: a spinner replaces the icon, the label stays.
- Not built yet: secondary buttons show no hover change (`hover:bg-muted` equals `--secondary`); the loading spinner sits beside the icon; most icons use lucide's 2px stroke, not 1.75 (§2.5); many icon-only buttons have no tooltip (job tray, dataset menu, widget shell, chat bar, the cleaning plan's ✎, × and chevrons).

Targets: icon buttons at least 32 × 32, text buttons 36px tall; compact text buttons inside panels (the step Undo) may be 28px.
- Not built yet: the inline icon buttons in the cleaning plan and the Changes panel (✎, ×, chevrons) are about 18px; the widget header's analysis and menu buttons are 28px; and the text buttons in the CSV toolbar and the Dashboard and Flow context rows are 28px.

### 4.2 Chips

28px tall, 999px radius, label text, 10px horizontal padding, 1px border.

| Kind | Style |
|---|---|
| filter / scope ("3rd class · 709") | `--secondary` fill; × removes |
| selection ("709 rows selected") | `--accent-soft` fill, `--accent` border |
| related widget | `--secondary`; hover spotlights the target |
| recipe / method | `--secondary`; selected: `--primary` fill |
| status | success / warning / destructive text with icon, no fill |

### 4.3 Widget shell

`dashboard/WidgetShell.tsx`.

```
┌ ⠿  Survival by sex                            [All rows] [⚗] [⋯] ┐  header 40px
│                                                                  │
│                         chart / table                            │  body
│                                                                  │
└ v7 · How do you know?                              updated 2s ago ┘  footer 28px
```

- Surface `--card`, 1px `--border`, radius 16. No shadow.
- Hover: border `--accent`, plus `--spotlight-shadow` outside Edit layout; its story card gets the same and the Stories panel scrolls it into view.
- Related (another widget's card is hovered): border `--accent` at 45%, spotlight at half strength. Not built yet: the border only, no spotlight.
- Selected / focused: 1px `--border-strong`.
- Updating: body at 60% opacity, with a pulsing 2px `--accent` line under the header.
- Outdated (an analysis widget whose run is older than the data): the footer shows "Outdated" in `--warning` with a small secondary Re-run.
- Error: the message in `--muted-foreground`, then Retry and Show query.
- Collapsed: header only, 40px.
- Drag handle (⠿): `--muted-foreground`, always visible, cursor grab. In Edit layout the whole header is the handle and a resize corner appears. It's a mouse grip, so it is `role="img"` named "Drag to move" (the layout has no keyboard move; not built yet).
- Footer details are in §5.5.

### 4.4 Charts (Bklit)

- Series colors from `--chart-1…5`; the story-relevant series or bar in `--chart-accent`. The builder marks "the point" from its fact candidates (top contributor, the outlier, the trend line), which the story job's fact sheet may refine; the adapter colors only that.
- Axes: `--chart-label` text at 12px, `--chart-grid` lines, no axis lines, no titles inside the plot (the widget title is the title).
- Tooltip: `--popover` surface, mono numbers, the series name in `--muted-foreground`.
- Hovered element: 100% opacity, siblings 60%.
- Clicked (filter active): the clicked element keeps the accent; others 40%.
- Not built yet: Bklit siblings fade to 40% on hover, not 60%, and tooltip numbers aren't mono.
- Brush: a `--accent-soft` region with 1px `--accent` edges and handles. Removed by cut 8.
- Empty: "No rows match the current filter" in `--muted-foreground`, with a "Clear filter" link. Not built yet: the message shows whether or not a filter is set, and there's no link.

Custom charts (`charts/custom.tsx`, plain visx SVG) follow the same tokens:
- **Histogram.** Bars radius 2; the tallest bin (or the builder's point) in the accent.
- **Heatmap.** Cells mix `--chart-1` into `--card` by value (15–85%); the largest cell in the accent; the value in mono inside cells big enough to hold it.
- **Box plot.** Whiskers to min and max, a `--card` box with a 1.5px series outline, a 2px median line; the point's box in the accent.
- **Scatter.** Points 2.5px at 55% opacity; the hovered point grows to 4px in the accent.
- **All.** Axis labels 11px in `--chart-label`. Histogram and box plot: hovered element at 100%, siblings 60%; the heatmap outlines the hovered cell in `--foreground`. A small readout of the hovered element at the top right. A one-sentence summary as the accessible label (`role="img"`).

### 4.5 Story card

`stories/StoryCard.tsx`.

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
- Overline: the widget's title, or "Overview", "Synthesis" or "Answer" for a card without one (11px, uppercase, muted). Headline: serif 18px, weight 600. Body: 14px in `--foreground-2`. Related chips: 24px tall.
- Footer: Evidence (link with a database icon; it opens the first chip's evidence and is disabled on a card with no chips), then Edit, a trash icon button (§5.15) and Ask why (ghost, small).
- Linked (its widget hovered): `--accent` border and `--spotlight-shadow`.
- Updating (being rewritten): the card at 70%.
- Badges, top right:
  - "changed": a `--warning` outlined chip; it clears when clicked.
  - "edited": pencil icon, muted.
  - "outdated, click to refresh": a `--warning` outlined chip.
  - Hand-typed numbers are dashed chips in the text, not a badge (§4.6).
  - "Cites n cards" on a synthesis (on its canvas node only, below).
- **User-written text on a newer version** (PRD STORY-7). Once the data is past the version a card's words were written on:
  - an edited card shows "Written on v5, data is now v7", a muted chip with a `--border-strong` outline;
  - a card with hand-typed numbers shows "Has numbers you typed; check them", a dashed `--warning` chip.
  - Both stay until the user edits the card on the new version or accepts a suggestion. On the canvas node they're 10px, like its other chips.
- **Suggestion.** When the data changes under an edited card, the new narration sits under the body in a dashed `--warning` box headed "The data changed. Suggested revision:" (12px, 600, `--warning`), with Accept (primary), Edit (secondary) and Dismiss (ghost), all small. There's no separate badge or link.
- Overview card: no related chips, bullets instead of prose.
- Synthesis card: overline in `--accent`, "Cites n cards" footer. Not built yet: in the Stories panel it has the muted overline and no "Cites n cards"; only its canvas node has both (§5.10).
- Direction card (building): dashed `--accent` border, a four-item checklist with ✓ / spinner / empty circle. Removed by cut 3.
- Note node (canvas only, not a story card): `--muted` fill, no overline, no chips.

### 4.6 Number chip

Inline button, mono 12.5px, `--info-soft` fill, 1px `--info` border at 35%, radius 6, padding 1.5px 5px (25px tall, over WCAG 2.5.8's 24px), `--foreground` text.
- Value: the card's latest fact-sheet value (`Card.facts`). Tooltip: the fact's label.
- Hover: underline, cursor pointer. Click: opens the evidence drawer. Not built yet: the cursor stays the default arrow (Tailwind 4 gives buttons `cursor: default`).
- In chat answers the chip is a plain span, not a button: its tooltip reads "Computed from the query below", and the source is under "How do you know?" (§4.8).
- Updating: a 400ms pulse to `--accent-soft` when the value changes.
- Unverified: dashed `--border-strong` border, `--muted-foreground` text, tooltip "Typed by you, not computed".
- **Evidence drawer** ("How do you know?"): "<value> is the <label>, computed on version n", then the SQL in a `--muted` mono block with Copy, or the formula and the test. A hand-typed number says it has no evidence.

### 4.7 Data grid (CSV tab)

Glide Data Grid (`csv/Grid.tsx`). Glide draws on a canvas, so each style is drawn in code from the resolved tokens.

| Element | Style |
|---|---|
| Header | `--background` fill; the name at 13px/600 (with ↑/↓ when sorted); under it an 11px `--muted-foreground` line ("type · n% missing"); a 14px-tall mini histogram (numeric bins or category counts) in `--chart-3` |
| Row numbers | mono, `--muted-foreground`, `--background` fill, sticky |
| Cell | body-sm; numbers mono right-aligned; text left; booleans "true/false" in mono |
| Selected cell | 2px `--accent` outline |
| Selected range | `--accent-soft` fill, 1px `--accent` outline |
| Find match | `--accent-soft` fill |
| Changed by cleaning | `--changed` fill plus a 2px `--info` line along the top edge (as drawn; the legend swatch carries the same line), so it doesn't rely on color alone |
| Flagged | 1px dashed `--warning` inset outline |
| Unsaved edit | `--unsaved` fill, 1px `--accent` outline, and a 4px `--accent` dot top-left, so it differs from a selection by shape |
| Predicted | `--predicted` fill, italic. Removed by cut 7 |
| Invalid value | 1px `--destructive` underline |
| Quarantined or to-be-deleted row | muted text, row number struck through |
| New (pending) row | `--unsaved` fill across the row, row number "new" |

Row height 32px; header 56px. Editors open in place at the same height.

**Column notes** (PRD LOAD-7). A column with a note starts its type line with ⓘ ("ⓘ category · 0% missing"). Hovering the header shows a tooltip under it:
- `--card` fill, `--border`, radius 10px (`--radius`), shadow-md, at most 340px wide, 12.5px text.
- Sherlock's sentence in `--foreground`; the source's words in italic `--foreground-2`, with a 2px `--border` rule on the left and curly quotes.
- An 11.5px `--muted-foreground` line: "From the data dictionary" or "From the web", the site, "retrieved <date>", ending "Not computed from your data."
- It's hover-only (no keyboard or click path: not built yet); chat's "what does <column> mean?" gives the same note.

### 4.8 Chat bar and thread

`shell/ChatBar.tsx`, `chat/Blocks.tsx`, `chat/Receipts.tsx`.

**Bar.**
- Max 680px wide, centred, `--card`, 1px `--border` (`--border-strong` on focus), radius 14, 52px tall, input 14px. A mono `/` hint on the right, then the send button: 40 × 40 primary, radius 10, arrow icon.
- As drawn: on dataset routes the bar sits at the bottom of the centre column (24px side and 20px bottom padding). On the empty library it sits in the centred column, 24px under the pitch. Not built yet: it's 48px under the pitch.
- **Context chip** on the left, always shown, 28px:
  - Dashboard: "All rows", the filter (`col = value`) or the widget last clicked, with × to clear.
  - CSV tab: "n rows selected". Flow tab: "n cards selected" or "Whole canvas".
  - The CSV and Flow chips are in `--accent` (text and border) while something is selected. Not built yet: no `--accent-soft` fill. The Dashboard's filter or widget chip is a `--secondary` chip in `--muted-foreground` with ×.
- **Disabled** where chat can't answer, with the placeholder naming the state: "Load a CSV to start asking" on the empty library, "Ask about this CSV (profiling in progress)" while a file profiles; a failed file's bar is disabled too. Otherwise the placeholder reads "Ask Sherlock, or tell it what to build…".
- While a cleaning plan is open the placeholder reads "Ask Sherlock to change the plan…" (§5.3a).
- **Sending while an answer is written.** Enter or send still takes the message: the bar empties and the message waits in the thread under the answer, in a dashed `--border-strong` bubble with "Queued: sends when this answer finishes · Cancel" under it (12px `--muted-foreground`). Queued messages go one at a time once the stream ends, so two answers never run at once. Cancel removes it and puts its text back in an empty bar. Meanwhile the send button's tooltip reads "Sends when this answer finishes".
- Suggested questions (three ghost chips under the bar, gone at 3+ messages): removed by cut 9.

**Thread.**
- Opens 84px above the bar's bottom edge, at most 40vh tall, `--popover`, radius 16, `--shadow-overlay`. A 36px title row: "Ask about <name>" and a collapse chevron.
- The user's messages: a `--secondary` bubble, right-aligned, max 80%. Sherlock's: plain text, left-aligned, with blocks inline.
- An empty thread shows one muted line with placeholders, not column names, so it fits any file: "Ask about the data (“the average of one column for each value of another”), find rows (“the rows where …”), or ask for a widget (“add a chart of … by … to the dashboard”)."
- While working: the user's bubble, the blocks as they arrive, and a status line in `--muted-foreground` italic with a 3-dot indicator.
- Plans: a checklist with ✓ ticks as steps complete.
- Clarification: the question, then 2–3 secondary buttons in a row.

**Answer blocks.**
- Number: 26px mono with the label under it.
- Table: up to 20 rows in a bordered box, with "Open these rows in CSV" or "Open all n rows in CSV" for row answers, or a muted "Showing 20 of n rows".
- Chart: 220px tall, with "Pin to dashboard", or "Open the widget" when chat made one.
- Text: with number chips (§4.6; in chat they're plain spans).
- General knowledge (`labeled: "general"`): a 1px dashed `--border` box, 13px `--foreground-2`, tooltip "From the model's general knowledge, not computed from your data".
- Web (TRD §8.2): a 1px dashed `--info` border at 50%, 13px `--foreground-2`, tooltip "From the web pages cited below, not computed from your data". A citation is a superscript 10.5px `--accent` link "[n]" that opens the page in a new tab. Under it, 12.5px: "Searched the web for: “…”" in `--muted-foreground` (with "(from earlier today)" when the cache answered), then a `<details>` "n sources"; each is "[n] <title>" (an `--accent` link) "· <site> · retrieved <date>" and its excerpt as an italic `<q>` with a 2px `--border` rule on the left.
- Actions after the blocks: small secondary Model card (an `open_model_card` action), Export notebook and Undo (for a widget chat changed), and a ghost "Add to Flow".

**Disclosures.** Every Sherlock message shows "How do you know?", a `<details>` listing each source's label and its SQL, run or step reference in a `--muted` mono block.
- Nested under it, **How I worked it out** (`Receipts.tsx`), in `--accent` like its parent. Opened, it shows a 12px table, Step · Model · Time · Tokens:
  - the step in plain words with its number ("2. Wrote the query");
  - "(repair)" in `--accent` on a repair call; "(in place of the medium model)" in `--accent` on a fallback call;
  - "(failed)" or "(cut off, asked again)" in `--warning` on a failed attempt, its row muted;
  - the full model ID in mono; time in seconds ("cached" for a web request the cache answered); tokens, right-aligned mono.
  - A medium-weight total line follows ("Total: 4 calls · 5.3 s waiting on them · 2,500 tokens · 1 repair").
  - States: "Reading the calls…"; "No model was called for this."; "The calls couldn't be read. Try again in a minute."
  - The same disclosure ends the cleaning report's full report dialog (App Flow §5).

**Proposal** (a change chat wants to make): a dashed `--accent` box with the summary, a table of the cells it changes (Row · Column · Now · After, up to 20), Approve (primary) and Reject (ghost). Once decided it reads "Approved", "Rejected" or "Expired: the data changed since". Not built yet: the "Show code" disclosure and the impact line (`Proposal.impact` exists).

### 4.9 Drawers and dialogs

- **Drawers** (`ui/drawer.tsx`): slide from the right over the right panel, 420px wide, `--popover`, `--shadow-overlay`, a 56px title row (15px/600) with ×. Used for How do you know?, the model card, Add widget and the cleaning report summary. The Review changes drawer is removed by cut 5.
- **Dialogs** (`ui/dialog.tsx`): centred, `--popover`, 1px `--border`, radius 16, a × at the top right. Max widths: Settings 580px, Import preview 880px, cleaning full report 720px, the save-conflict dialog ("The data changed while you edited") 560px, Export notebook 520px, the step Undo confirmation 460px, other confirmations and Rename 420px.
- Both have a dimmed backdrop, `rgba(46,48,53,0.28)` (Light) / `rgba(0,0,0,0.5)` (Dark). Esc and backdrop click close both; focus is trapped and returned on close (Radix Dialog).

### 4.10 Toasts

sonner, bottom-right, `--popover`, 1px `--border`. 10 s for Undo toasts, 4 s otherwise (the new-rows "Clean them" toast stays 15 s, "Notebook ready" 60 s). One line of text plus an optional Undo button (link style). Errors use the destructive icon and stay until dismissed. Not built yet: error toasts close after 4 s, and the Undo is sonner's default filled action button, not link style.

### 4.11 Tooltips

`--popover` surface, body-sm, 6px 10px padding, 200ms delay, at most two lines.
- `ui/tooltip.tsx` (`Tip`, Radix Tooltip) draws it, with an optional keyboard shortcut on the right in mono 11px muted, and a `--shadow-overlay`. The Flow canvas's controls use it.
- Not built yet: everywhere else (outside the charts' own tooltips, §4.4, and the column-note tooltip, §4.7) the tooltip is still the browser's native `title`.
- Cell provenance tooltip (three lines with an Undo link): removed by cut 5.

### 4.12 Segmented control (settings, tabs)

`ui/segmented.tsx` (`role="radiogroup"`). Container: 4px padding, `--muted` fill, 1px `--border`, radius 11. Segments: 36px tall, radius 8, 14px text. Active: `--card` fill (Light) or `--secondary` (Dark), `--foreground` text, 1px `--border-strong`. Inactive: `--muted-foreground`, `--foreground` on hover. The tab switcher (§3.2, `CenterHeader.tsx`) copies the look as a `role="tablist"` of links, the active tab at weight 500.

### 4.13 Empty states

Centred, max 420px wide: a 24px lucide icon in `--muted-foreground`, a title (title size), one sentence (body, muted), one primary action. Never more than one action, except the library empty state (Upload and Try with sample).
- Not built yet: the dashboard's ("No widgets yet") has no icon and its Add widget button is secondary.

---

## 5. Screen specifications

Behaviour, states and transitions for each screen are in the App Flow; this section is the visual spec.

### 5.0 Library panel (left)

`library/LibraryPanel.tsx`. As drawn on the Dashboard and Empty library boards:
- 16px padding with 12px gaps.
- Top row: "Sherlock" (serif 20px, weight 500); on the right the Settings gear and the « collapse button (ghost icon buttons; « hides below 1024px).
- The "Your CSVs" overline.
- **Rows**: 8px × 10px padding, radius 8, the name (weight 500), then a 12px status line:
  - `ready · v7` in `--success` with a check icon
  - `cleaning 42%` with a 2px progress bar (`--accent` fill on a `--border` track)
  - `building` with the same bar, no percentage
  - `offer · 4 issues`, the count from the current version's data card
  - `profiling`
  - `failed` in `--destructive` with an alert icon

  The open dataset's row has the `--secondary` fill and a 1px `--border-strong` outline. Other rows are borderless and take `--secondary` on hover. The row menu is in §5.15.
- With no datasets: "No CSVs yet."
- At the bottom: Upload CSV and Try with sample, both secondary and full width.

**Right panel (Stories) before cards** (`StoriesPanel.tsx`): three 120px dashed `--border-strong` placeholder cards (radius 16) and "Stories appear once the dashboard is built." Once the dashboard has widgets but no cards yet: "Writing the stories…".

### 5.1 Library empty state (centre)

`library/EmptyLibrary.tsx`, `DropOverlay.tsx`.
- **Drop zone**: at most 640px wide, 320px tall, 2px dashed `--border-strong`, radius 16. Inside: the `upload` icon (24px, muted), "Drop a CSV anywhere" (display serif 32px), an "or" divider, Upload and "Try with sample (Titanic)" (both secondary), then two 12px muted lines: ".csv, .tsv or .txt · up to 50 MB" and "No sign-up: your CSVs stay with this browser. Clearing its cookies, or another browser, starts an empty library."
- **Pitch** under the zone: serif 18px in `--foreground-2`, max 520px. Then the chat bar (§4.8).
- **Drag-over**: a file dragged over any screen raises a full-window overlay: 2px dashed `--accent` border, `--accent-soft` fill, the icon in `--accent` and "Drop to import" (serif 32px).

### 5.2 Import preview dialog

`library/ImportPreviewDialog.tsx`, 880px.
- Title: "Import titanic3.csv · 61 KB" (serif 22px; the size in 14px sans, muted).
- A row of four controls (Delimiter, Encoding, Header row, Skip rows) as labeled selects and inputs; under them a full-width "Data dictionary URL (optional)" input (type url, placeholder "https://… a page that describes the columns", PRD LOAD-7).
- The preview table: 20 rows, a `--muted` header row at 600, cells in 12.5px mono, horizontal scroll.
- Footer: the detection line ("Detected n columns · about n rows", 13px muted; a blocking problem in `--destructive`), Cancel (ghost), Import (primary).

### 5.3 Cleaning offer (centre)

`dataset/CleaningOffer.tsx`, `OfferActions.tsx`.
- A single `--card` panel, max 640px, 8vh from the top, radius 16.
- Display title "Here's what I found in titanic3.csv", then a muted line of rows · columns · issues.
- The three most severe issues as lines with icons (missing: dashed circle; leakage: `--warning` flag; others: alert triangle). No issue table: the cleaning plan (§5.3a) lists every issue (owner's decision, App Flow §4).
- Two buttons in a row: Clean with AI (primary), which opens the cleaning plan, and Clean it myself (secondary), which opens the CSV tab. After a failed run they read Try cleaning again and Build dashboard without cleaning, under a 13px `--destructive` line with the error ("… Your data is safe; you can build the dashboard without cleaning or try again.").
- A "Remember my choice" checkbox with the muted hint "· You can change this in Settings" (label size).
- Go step by step (P1) is the plan's Mode row (§5.3a).

### 5.3a Cleaning plan (centre, or the right panel on the CSV tab)

`dataset/CleanPlanPanel.tsx`. Behaviour: PRD CLEAN-8a and App Flow §4.1. Two layouts:
- **Centre** (from the offer): a `--card` panel, max 720px, 6vh from the top. Display title "Cleaning plan · v2", a muted line "Sherlock checked v2. Untick, edit or add steps, or ask in chat." (when a newer version has arrived: "Sherlock checked v2; the data is v3. Checking the plan again…"), ending in "Reviewing…" (12.5px, a `status` region) while the severity review runs. Optional body-sm (13px) muted lines:
  - opened by the After upload setting: "Opened because After upload is “Open the cleaning plan” · Change" (Change opens Settings at that field);
  - opened for some rows: "Only the n rows you asked to clean." or "Only the n rows you just added."
- **Side** (from the CSV tab's Clean with AI): fills the right panel in place of Changes, 16px padding, title "Cleaning plan · v2" (15px/600), sm footer buttons.
  - A **Scope** fieldset above the modules (overline legend, radios): Whole dataset · Current selection (n rows) · Rows added since the last clean. When the plan was opened for some rows, a first, picked radio names them: "The n rows you just added" or "The n rows you asked to clean". Under a narrowed scope: "Counts are for the whole file; changes stay inside the rows in scope."
  - The footer sticks to the panel's bottom on `--background` with a top border.
- **While it's made**: a spinner and "Diagnosing v2 of titanic3.csv…" in the same box.
- **Groups by level** (PRD CLEAN-8c): an overline title per group, Your steps · Breaks answers · Skews answers · Splits groups · Worth a look · Cosmetic · Marked, not changed, over a 1px border, a tri-state checkbox on the left ("<group>: tick all", indeterminate when some are ticked) and "n of m" in mono muted on the right. Marked, not changed has neither. Empty groups aren't shown. No per-item badge: the heading carries the level (§10).
- **Item row** (separated by 1px `--border`): checkbox (`--accent`) · the column in mono · the issue in body (muted when unticked) · the count in mono muted · on the next line the planned action in body-sm muted · under it the review's reason (12px muted), or "(default level)" when code's default stands · on the right a ▸ chevron when there are examples, opening up to 5 values as mono chips (`--muted` fill, 1px border, radius 8, truncated at 240px). Checkbox names read "age: missing values".
- **Marked, not changed** rows: the `flag` icon in `--warning` instead of a checkbox, and the reason ("ticket looks like an ID column, so it is left as is") in place of the action.
- **Editing** (PRD CLEAN-8b): a ghost ✎ (`pencil`, 14px) on the right of every changeable row opens an inline editor under it: a 3-row textarea (13px, `--card`, `--input` border, `--accent` on focus, at most 500 characters with a mono counter), Save (primary, sm), Cancel (ghost), and Reset (ghost) on a rewritten fix. A rewritten fix shows the instruction in body-sm with an "edited" tag (`--accent-soft` fill, `--accent` text, 11px, radius 4), and Sherlock's wording beneath, muted and struck through.
- **Date order** (`DateOrder`): under an ambiguous-dates row, indented with the action:
  - a body-sm medium "Which order are these dates in?";
  - a 12px mono table (Value · Day first · Month first; header muted; the picked column in `--accent`) of up to three values;
  - a `radiogroup` of two 28px buttons, "Day first" and "Month first" (picked: `--primary` fill; the other outlined `--border-strong`); a second click clears the order.
  - With no order, one muted line says why it matters.
- **Your steps** rows: the issue reads "your step", no count, the instruction in `--foreground`, "· from chat" (11px muted) when chat added it, and an × (ghost, 14px) removes it.
- **"+ Add a step"**: a link button with the `plus` icon under the modules. It opens a bordered box (radius 14, 12px padding): a Column select (mono; Rows first, then the file's columns), a "What to do" textarea, then Cancel and Add (primary).
- **Suggested checks** (PRD CLEAN-14): an overline group above Marked, not changed; each row a disabled checkbox, the check in words, "suggested by Sherlock" (11px muted), the count and the model's reason on the next line in body-sm muted, then **Keep** (secondary, sm) and **Dismiss** (ghost, sm).
- **"+ Add a check"** beside it (PRD CLEAN-13): the same bordered box with selects (32px, `--card`, `--input` border) for Column (mono), Check and "Rows that break it", and 32px inputs for the check's values, labelled in 12px muted; Cancel and Add check (primary). A check's row has an × (ghost, 14px) that turns it off.
- **Chat** while it's open: the bar's placeholder reads "Ask Sherlock to change the plan…".
- **Mode**: an overline, then two radios: "Run on its own" (selected) and "Ask me before each fix" (P1), muted at 60% with "comes later" and the tooltip "Step-by-step cleaning comes in a later release".
- **Footer**:
  - "n of m ticked" (body-sm muted); past 20, "· Sherlock tries up to 20 per run; your steps first, then the most severe".
  - On the CSV tab, the unsaved-edits note on `--muted` with Discard edits.
  - "Cells you edited by hand are left alone and listed in the report." (label size).
  - Right-aligned Discard (ghost) and **Start cleaning (n)** (primary). It's disabled with nothing ticked, with unsaved CSV edits, or while an editor holds unsaved text, with the reason as its title.
- **The report's "Your steps"** (`CleaningReport.tsx`): the first overline section of the full report, one line per step the user added or fix they rewrote: an icon (check, flag or skip), the column in mono, the instruction in quotes, the outcome ("done", "done with a flag", "skipped", "not reached") and the step number, with the skip reason muted beneath. Decisions and the Changes panel's step detail show "You asked: “…”" muted above the question.

### 5.4 Cleaning in progress (centre)

`dataset/CleaningProgress.tsx`. As drawn, with both side panels kept (App Flow §5 needs the library row's progress and dataset switching, and the story placeholders; the board shows the centre alone).
- **Layout.**
  - Content centred at most 1200px wide, 32px × 24px padding, 20px between blocks.
  - Top: display title (§2.2), subtitle, Stop (secondary), then the step label and elapsed time (mono) over a 4px progress bar.
  - Left 2/3: the live log card (`--card`, padding 8px × 16px, at most 60vh tall), auto-scrolling while it's scrolled to the end. Right 1/3: "So far", "Checks on the latest step", the budget line, and a dashed card "When cleaning finishes, the dashboard builds itself." Side cards use the 20px × 22px card padding.
  - The two columns wrap into one when the centre panel is under 768px (a container query on the centre, not the window).
- **Log entries.**
  - A grid of 56px (time, mono 12.5px), 24px (icon) and the rest, 12px vertical padding, a hairline between entries.
  - Text: the column (mono 12.5px), then "· " and the issue in `--foreground-2`.
  - Candidate chips: 24px tall, 12px; the chosen one filled `--primary`.
  - The outcome line (13px, `--foreground-2`) is written by code from the step's verifier report. The model's own sentence, when it has no number, sits under it at 12.5px muted.
  - The gate line: 12px in the gate's color: `--success` committed, `--warning` flagged, muted skipped, `--accent` running.
  - The issue's model calls end the entry in 11.5px mono muted ("3 model calls · <models> · 12.3 s").
- **"So far"**: four tiles (2 × 2), values in mono 24px, labels 12px muted, `--muted` fill, radius 8.
- **Checks**: a list with a `--success` ✓ (or a `--destructive` × on a failed check), then the budget line in mono 12.5px muted ("n of 20 issues tried · 01:12 of 05:00"). The merge check reads "No look-alike categories merged" and the fill check "Missing values stay missing".

### 5.5 Dashboard

Grid as §3.3, widgets as §4.3. `dashboard/Dashboard.tsx`, `DashboardActions.tsx`.
- **Context row.** The filter chip (`col = value`, ×) follows the version pill. On the right: Add widget (secondary, sm), Edit layout (ghost sm toggle; active `--secondary` fill), the job tray, then the dataset menu. Not built yet: the Filter button (ghost with icon) and its filter builder; a filter comes only from clicking a chart.
- **Layouts.** Until the user arranges a breakpoint, md and sm are packed from lg in reading order: KPIs at a quarter width (two to a row on sm), charts at full width on sm.
- **KPI tile.** The widget title is the label; the value in mono 28px (weight 500); "of n rows" under it (label, muted) when the result carries a row count. A gauge draws as a KPI tile.
- **Widget shell.**
  - Title: 13px, weight 600, 16px line. A long title wraps to a second line and is cut with an ellipsis only after that, with the whole title as its tooltip, so a KPI label ("Average customer age") reads in full at desktop widths.
  - Scope chip (24px): "All rows", or "All rows · col = value" while a filter applies; "Some rows" or "Selection" for a widget with its own narrower scope. It hides when the widget is narrower than 360px.
  - Footer (28px, 12px muted): the version in mono · "How do you know?" (link) · "Model card" on an analysis · "Outdated" with Re-run · "first 2,000 rows" when a result was capped. Not built yet: "updated 2s ago" (§4.3).
  - A card click, or `?widget=` in the URL, scrolls to the widget and flashes it: `--accent` border and a 3px `--spotlight` ring for 1.2 s.
- **Charts.** Bars have radius 4. The point's bar or slice is `--chart-accent`; the rest `--chart-1`. Pie and ring slices cycle `--chart-1…5`, with a legend list beside the pie. A dated result draws as a line or area; one with too few dated points falls back to a table.
- **Click-to-filter.** A click on a bar or slice sets the filter on the widget's category column; clicking it again or the chip's × clears it. The clicked chart doesn't filter itself: its clicked element keeps the accent and the others fade to 40%. Not built yet: pie and ring slices don't fade; only their legend rows do.
- **Widget menu (⋯):** Change view (only views that can draw the result, a check on the current one) · Duplicate · Collapse / Expand · Show as table (a check toggle, this browser only; not built yet: it resets on reload) · Delete (toast with Undo, 10 s).
- **Add widget drawer.** "Describe it" (a textarea and Add), then Quick templates: a segmented control (Bar of X by Y · KPI of X · Table), column selects, and Add template. Past 20 widgets, a warning toast.
- **"How do you know?" drawer** (`ExplainDrawer.tsx`). One sentence naming the widget and version, the SQL in a `--muted` mono block, Copy, and the result row count. An analysis widget shows its run's reproduction code instead.

### 5.6 CSV tab

`csv/CsvTab.tsx`, `SaveActions.tsx`.
- **Toolbar** (40px, `role="toolbar"`, sm buttons): Add row, Delete row (or "Delete n rows"), Restore (when quarantined rows are selected), Find (toggles a find bar), Clean with AI (secondary, sparkle icon), Download (ghost menu: CSV · Notebook (.ipynb)). The legend on the right: three swatches with labels (changed · flagged · unsaved, label size), hidden below a 768px window.
  - Not built: Add column (P1), and the Filter toggle for a header filter row.
- **Context row**: the unsaved count in `--accent`, Discard (ghost) and Save changes (n) (primary), or "Rebase and save" on a conflict. They hide when nothing is pending. Review changes is removed by cut 5.
- **Find bar** (40px, under the toolbar): an input ("Find in every cell…"), Find, the match count ("n matches in n rows; only those rows are shown"), ×; Esc closes it.
- **Grid** fills the rest (§4.7).
- **Status bar** (28px): the selected cell count, the row count (with the sort, marked "view only"), the unsaved count in `--accent`, and on the right "Row 9 · home.dest". The selection stats (sum · avg · min · max) are removed by cut 5.
- **Opened on a selection** (`?rows=`, from a chat answer or "Who did it get wrong?"): a strip under the toolbar with an "n rows selected" chip (`--accent-soft`, `--accent` border) and Show all rows (ghost).
- **Read-only while a job owns the data** (App Flow §5): while the status is `cleaning` or `building`, a 13px strip on `--muted` (`role="status"`) reads "Cleaning in progress · editing resumes when it finishes" or "Building your dashboard · editing opens when it finishes". Cells don't open an editor; Add row, Delete row and Restore are disabled with the reason as their title.
- **Clean with AI** opens the cleaning plan (§5.3a) in the right panel.

### 5.7 Changes panel (right, CSV tab)

`csv/ChangesPanel.tsx`.
- Title "Changes" with the version pill.
- **Unsaved (yours) · n**: a card with the `--accent` border when non-empty, a mono line per pending edit with ×.
- **Running clean**: an `--accent`-bordered card, "Cleaning…" with the progress label, a 2px `--accent` progress bar and Stop (ghost). It sits above Unsaved.
- **Steps** overline, then step cards newest first (radius 14): a chevron to expand · number (mono, muted) · summary (13.5px, 500) · detail line (12px, muted: columns, cells changed, rows added, deleted or quarantined, "flagged · 0.62", who made it) · Undo (secondary, 28px). The latest step has a `--border-strong` outline. With no steps: "No steps yet. Edits you save and cleaning fixes appear here."
- **Expanding a step**: its code in a plain `--muted` mono block (no syntax highlighting) or its edit list, then the impact lines and decisions.
- **Undo** opens a confirmation dialog when the server asks for one (§6).
- **Undone step**: a dashed border on `--background` instead of `--card`, the summary in `--muted-foreground` and struck through, "· undone" on the detail line. No opacity, which would take its text under 4.5:1 (§8).
- **Footer links**: Full cleaning report (a drawer with the report summary; its View full report opens the full report, Your steps first, in a 720px dialog) · Export notebook. Not built: Export pipeline (P1).
- While a cleaning plan is open, the right panel shows the plan (§5.3a, side layout); Start or Discard gives it back to Changes.

### 5.8 ML setup (inside a widget)

`ml/MlSetup.tsx`, `AnalysisMenu.tsx`. Sections stack inside the widget body (scrolling when the widget is short), each under an 11px uppercase overline:
- **Target.** A native select of the recipe's `targets`, then a muted line ("Categories: scored by Accuracy.").
- **Features.** 24px pill chips: used in `--border-strong` on `--card`; excluded struck through on `--muted` with "Left out: <reason>" as the tooltip; forced-in with a `--warning` border and a warning icon. Re-including one shows a `--warning` line with the reason.
- **Rows.** The scope chip ("All rows · 1,309 with survived", plus the filter when used), and an "Only the filtered rows" checkbox when a dashboard filter is active. The "Use selection" link (with a brush) is removed by cut 8.
- **Method.** One line, since the segmented control (Auto · Linear · Logistic) is removed by cut 4: "Auto: tries logistic regression (ridge regression for a number), gradient boosting and a random forest on the same folds and keeps the best."
- **More.** A native disclosure with the manifest's integer params as labeled number inputs.
- **Baselines.** A table of the two baselines (everyone-majority, best one-column rule) plus "Model: pending" ("already run" when the same settings ran before).
- **Footer.** The estimate ("about 10 s"), Cancel (ghost) and Run (primary). Run is disabled while the preview has an error, and that error replaces the baselines.

**Analysis menu**: a 28px flask icon button left of the widget menu. Its menu has the group overlines (Explain · Predict · Group · Unusual · Time, each shown only when it has recipes), disabled items with their reason in an 11px line, then "Plain chart (SQL)" as a check item.

### 5.9 Model card drawer

`ml/ModelCardDrawer.tsx`: the 420px drawer titled "Model card". Sections in order:
- **Verdict.** 20px serif, weight 600. When outdated, a `--warning` bordered row with Re-run follows (none when opened from a chat answer).
- **Data.** Target, task, version, scope, rows used of the total, rows without the target, and the sample when there is one.
- **Excluded columns.** Mono, struck through, each with its reason.
- **Method.** "Auto picked <model> by 5-fold stratified cross-validation (seed 42)." When the folds are grouped (TRD §7.5 step 4) it ends "…(seed 42), keeping rows that share a <column> in one fold." Then "Also tried:" with the other models' scores, and the params.
- **Baselines vs model.** A 12px table: the rows, the metric and the 95% interval. The model row is bold, followed by AUC or MAE.
- **Importance.** "Permutation importance on held-out folds (10 repeats)", then a list with values.
- **Who it got wrong** (classification): the confusion matrix, the ROC curve and a secondary "Who did it get wrong? (n rows)" button, which opens the CSV tab on those rows and closes the drawer.
- **Warnings.** `--warning` bordered boxes with the suggestion under the text.
- **Limits.** The card's limits in one muted line.
- **Show the code.** A secondary button (Show the code · Hide the code) that reveals `repro.py` in a mono block.
- Removed by cut 4: Compare with Auto and the coefficients table (with CI and p).

**The analysis widget's body** (`MlResult.tsx`, App Flow §9 steps 3–5):
- **While running.** The progress line ("What drives survived: testing models…"), a 4px `--accent` bar, the steps with check and spinner icons, and Cancel (ghost).
- **Failed or cancelled.** The reason in muted text and a Re-run button.
- **View switcher** (classification): 24px text tabs over the body: Importance · Confusion · ROC.
- **Importance.** The verdict line (in `--warning` for no signal), then up to twelve rows: the name, a 12px bar in `--chart-1` (the top factor or the open one in `--chart-accent`) and the value in mono.
- **Partial dependence.** A 64px SVG mini chart in a bordered figure under its bar: a line for numbers, bars for categories, with an accessible label listing the points.
- **Confusion matrix.** A table of mono counts, actual by predicted. Each cell is tinted with `color-mix` of `--chart-accent` (the diagonal, right) or `--chart-1` (wrong), 12–62% by count, with a tooltip. A line under it gives the count predicted wrong.
- **ROC curve.** A 170px SVG: the curve in `--chart-accent`, the chance diagonal dashed in `--chart-grid`, small axis labels, the AUC in the caption.
- **Footer.** Adds "Model card", and "Outdated" in `--warning` with a small secondary Re-run.

### 5.10 Flow canvas

`flow/FlowTab.tsx`, `FlowPalette.tsx`. React Flow (`@xyflow/react` 12.11.3) with its structural `base.css` only; every colour comes from the tokens (`.flow-canvas` rules in `index.css`).
- **Canvas**: `--background` with a dot grid (`--border-strong` dots, 1.2px, 22px spacing).
- **Card nodes**: 240px wide (widened up to 480px) in the §4.5 style with no shadow; the headline serif 15px at 600, the body 13px clamped to six lines (except on a synthesis). "Open widget" when it has one; small `--warning` chips for "changed", "outdated" and "sources changed"; the user-text badges at 10px (§4.5).
- **Synthesis node**: `--accent` overline, `--border-strong` border, "Cites n cards" in its footer.
- **Notes**: 220px (160–480px), radius 14, a fill of 5% foreground over the background.
- **Node menu**: a 28px ghost ⋯ (`ui/menu.tsx`, as the widget menu) at the top right of a card's overline row or a note's corner, hidden until the node is hovered, focused or selected (as library rows). Right-click opens the same items at the pointer. Remove from canvas uses ×, because the card stays in the palette; Delete note, Delete card and Delete connection use `trash-2` and the destructive item style. Shortcuts show on the right of each item (`MenuShortcut`, mono 11px muted).
- **Resize grip**: the right edge of a selected node, 8px wide, showing a 2px `--accent` line while hovered or dragged.
- Direction node (dashed `--accent` border): removed by cut 3.
- **Handles**: 9px side handles with an `--accent` ring, shown on hover and selection.
- **Selected node**: 2px `--accent` outline offset 2px; dashed for the first node picked in connect mode.
- **Edges**: 1.5px bezier curves with a closed arrowhead; `--muted-foreground` for the user's, `--accent` for the AI's; 2.25px and `--accent` when selected. Suggested edges (P1, dashed) aren't built.
- **Labels**: pill chips at the midpoint, `--card` fill, edited in place. A selected connection's pill (an empty one when it has no label) carries its ⋯.
- **View control**: bottom-left, a `--card` pill of 32px ghost icon buttons (`ui/button.tsx`): Undo and Redo (dimmed when there's nothing to undo or redo), a hairline, then zoom out, the zoom level in mono 12px (a ghost button that resets to 100%) and zoom in. Each has a tooltip with its key. Zoom, fit and centring animate over `--duration-base`, so reduced motion makes them instant.
- **Minimap**: bottom-right, 132 × 84, `--card`, the viewport mask stroked in `--info`.
- **Status row**: the node count at the canvas's top left ("Story canvas · 6 nodes · 3 selected", 13px muted), then the selection's `sm` buttons: **Make sense of this** (primary, two or more cards), **Connect** (ghost, `spline`, exactly two nodes) and **Remove** (ghost, ×, anything selected; its name says what: "Remove 2 nodes from the canvas").
- **Context row**: `Button size="sm"`: Add note (secondary, `plus`), Connect (ghost, `spline`, `aria-pressed` with a `--secondary` fill while on, as Edit layout) and Fit view (ghost, `maximize`), each with a tooltip. While connecting, an `--accent`-bordered pill at the top centre says what to click next.
- Deleting nodes or edges gives a toast with Undo for 10 s.
- **Empty canvas**: as §4.13: a 24px muted `workflow` icon, "The canvas is empty", one muted sentence on how to fill it, and **Add note** (primary).

**Palette** (right panel): a "Story cards" overline; a "Search cards" input; rows (drag handle · name · "on canvas" / "not placed" in muted; Enter or a double-click places one in the middle); a "Try asking" card; then Export: Notebook (.ipynb) (P0, a link) and "Obsidian (.canvas) · P1" (muted, not built).

### 5.11 Settings dialog

`shell/SettingsDialog.tsx`, 580px.
- Title "Settings" (display serif 32px) and ×.
- With cut 1, four settings in one column, each a label (13px/600), a segmented control (§4.12) and a help line (13px muted):
  - **Mode**: Light · Dark · System.
  - **Accent**: each with a dot in its color for the active mode.
  - **Chat bar**: Pinned · Auto-hide · Hidden. Auto-hide fades the bar out until it's pointed at or focused; Hidden removes it.
  - **After upload**: Ask me · Open the cleaning plan · I'll clean it myself (owner's decision; stored as `ask|always|never`), help "What happens once a new CSV is profiled. Nothing is cleaned until you start a plan."
- Footer: "Saved to your Sherlock profile" (muted) and Done (primary).
- Opens from the library panel's gear, or `?settings=1` in the URL. `&field=after_upload` scrolls to that field and outlines it in `--accent` (radius 14); the "Change" links on the plan and building screens use it.
- When cut 1 is lifted, the other five settings return (`cleaning_mode`, `story_updates`, `spotlight`, `reduce_motion`, `default_tab`; `GET /me` already stores all nine), with Default tab and Spotlight two per row.

### 5.12 Shortcuts sheet (`?`)

A dialog listing shortcuts in two columns grouped by tab (Global · Dashboard · CSV · Flow · Chat), keys as `<kbd>` in mono. Removed by cut 9.

### 5.13 Export notebook dialog

`shell/ExportDialog.tsx`, centred, max 520px.
- Title "Export notebook" (serif 22px, weight 600).
- One 14px sentence on what will be rebuilt, the counts in mono (steps, widgets, model runs, story cards, canvas notes).
- Four native checkboxes tinted `--accent`, label on the right, muted help under each: Include data · Include story cards · Include canvas notes · Include ML runs.
- **Order** segmented control: "Steps, then dashboard order"; "Flow reading path" is dimmed with its tooltip and can't be chosen.
- Conditional notes in a `--muted` box with the warning icon (job running, unsaved edits). Not built yet: a secondary "Save and export" button in that box; the note says "save first to include them".
- Footer: Cancel (ghost), Export (primary).
- **Progress**: sonner's loading toast "Preparing notebook…", then "Notebook ready" with "Download again" (shown for 60 s). Export is never a blocking modal.
- The `book-open` icon marks every Export notebook entry point, and "Export notebook" is the label everywhere, never "Download .ipynb" alone. Not built yet: the Flow palette and chat export entries lack the icon, and the CSV tab's Download menu and the Flow palette label it "Notebook (.ipynb)".

### 5.14 Dataset menu (⋯)

`shell/DatasetMenu.tsx`. A ghost icon button at the right end of the context row on all tabs. Items: Export notebook (`book-open`, with "Ctrl+Shift+E" or the reason it's blocked on the right), Download CSV (`download`), Rename (`pencil`, a dialog), Delete (destructive, `trash-2`; confirm, then a toast with Undo for 10 s). Ctrl+Shift+E opens Export notebook directly from any tab.

### 5.15 Job tray, banners and small disclosures

- **Job tray** (`JobTray.tsx`): a ghost icon button (`activity`) in the centre header with an `--accent` count of queued and running jobs. Its 320px popover lists jobs: the job ("Cleaning · titanic3.csv"), its progress label, a 2px bar, and Cancel. Done and cancelled jobs show for a minute; failed ones stay, with the error in `--destructive`, Retry and a dismiss ×. Empty, it reads "No background jobs right now." It polls `GET /api/v1/jobs` every 3 s.
- **Library rail**: the « button beside the gear collapses the panel to a 56px rail with dataset initials (mono, 36px), Upload, Try with sample, the gear, and » to expand. Dividers in §3.1.
- **Library row menu**: a ⋯ on hover with Rename (inline), Download original CSV and Delete (confirm, then a toast with Undo for 10 s). The context row's dataset menu is §5.14.
- **Offline banner** (`OfflineBanner.tsx`): a strip at the top of the centre with a `--warning` tint and border and the `wifi-off` icon: "Can't reach Sherlock. Your data is safe, and unsaved CSV edits stay in this browser; this clears when the connection is back." It shows when the browser goes offline or an API request can't reach the server (the `sherlock:offline` event), and clears on `online` or when `/healthz` answers (checked every 5 s while it shows).
- **Error boundary** (`ErrorBoundary.tsx`): a view that crashes shows a `--card` panel in its place: "Something went wrong showing the dashboard" (or the page, CSV tab, canvas, library, side panel), "Your data is safe on the server…", the error's first 300 characters in mono, **Try again** (primary) and **Reload** (ghost). The rest of the app keeps working; moving to another dataset or tab resets it.
- **Story card delete**: a ghost trash icon button after Edit; the toast "Card deleted" offers Undo for 10 s.
- **"Why the offer was skipped" lines** (App Flow §4): a body-sm (13px) muted line with a Change link, under the plan's title ("Opened because After upload is “Open the cleaning plan” · Change") or under "Building your dashboard…" ("Building without cleaning because After upload is “I'll clean it myself” · Change"). They stay on screen rather than as a toast.
- **Cascade progress line**: a 2px `--accent` line under the header with a label-size caption ("Updating 4 widgets and 3 stories").
- **Chat sources disclosure**: §4.8.
- **"Data changed" on edited cards**: the inline suggestion under the body (§4.5).

---

## 6. Interaction rules

- **Hover linking** fires after 80ms of hover and clears 120ms after leaving, so moving across widgets doesn't flicker. Off while dragging, resizing or brushing, and while a drawer is open.
  - Not built yet: it fires and clears at once, with no delay. It's off while Edit layout is on, not only during a drag or resize.
- **Click-to-filter vs brush**: a click without movement filters; movement over 6px starts a brush, only inside the plot area. Brushing is removed by cut 8.
- **Drag**: only from the handle, unless Edit layout is on. The dragged widget is at 90% opacity with a `--border-strong` outline; the drop placeholder is `--muted` (`index.css`, `.dashboard-grid`).
- **Keyboard**:
  - Tab order: left panel → tabs → context row → grid (widgets are focusable; Enter opens the menu) → right panel → chat bar. Arrow keys move between widgets when the grid has focus.
  - Global shortcuts: `/` focuses the chat bar; Ctrl+Shift+E opens Export notebook. Single-key shortcuts fire only when no cell, input or editor has focus.
  - Canvas keys (Ctrl+Z, Ctrl+A, Ctrl+D, Shift+1, …) are listed in App Flow §12.2. They follow canvas tools (Figma, Miro, tldraw), act only on the Flow tab while no input, note, editor, menu or dialog has focus, and show in the tooltip or menu item of the control that does the same thing.
  - Every menu action having a shortcut listed on `?`: removed with the `?` sheet by cut 9.
  - Not built yet: widgets aren't focusable, so the widget tab stop, Enter and arrow keys don't work.
- **Focus**: 2px `--ring` with 2px offset everywhere, including grid cells and canvas nodes.
  - Not built yet: only `ui/button.tsx` sets the offset; icon buttons and segments draw the 2px ring flush, menu items mark focus with a `--secondary` fill, and the tab switcher's links fall back to the base `outline-ring/50`.
- **Loading**: skeletons (not spinners) for widgets and cards; spinners only in buttons and the cleaning state.
  - Not built yet: spinners also show on the profiling and building screens, on an updating story card and on the running analysis step.
- **Undo**: every destructive action has a toast with Undo; every step has Undo in the Changes panel. A pending edit is removed with its × in the Changes panel (Ctrl+Z buffer undo is removed by cut 5).
- **Confirmation dialogs** only for: deleting a dataset, discarding pending edits, undoing a non-latest step, and undoing the automatic typing step (step 1). Everything else is undoable instead.
  - Not built yet: the cleaning plan's Discard edits discards at once, with no confirmation.

---

## 7. Copy guidelines

- Plain words. "What drives this?" not "Feature importance". "Find groups" not "Clustering". The technical name appears in the model card.
- Numbers are never written in generated prose except as chips.
- Verdicts are one honest sentence: "No better than the simple rule." is a valid verdict.
- Correlational findings never use "causes", "because" or "leads to" in AI text. Edge labels typed by the user can say anything.
- Errors say what happened and what to do, in that order, in one or two sentences. No codes, no stack traces.
- The notebook's Markdown cells use the story cards' voice. Each code block carries one plain-words comment saying what it does, so the notebook reads as a report even to someone who skips the code.
- Empty states say what will appear here and offer one action.
- Sherlock is "I" in chat and "Sherlock" in UI text.

---

## 8. Accessibility checklist

- Text contrast ≥ 4.5:1 against its surface in both themes (checked for every pair above; `--muted-foreground` is tuned to pass on `--background` and `--card`).
- Chart marks and other non-text graphics ≥ 3:1 against `--card` (WCAG 1.4.11); the chart tokens are tuned to pass.
- Semantic colors always paired with an icon or text.
- All interactive elements are real buttons, links or inputs; icon-only buttons have `aria-label`. The widget drag handle is a named `role="img"`, not a control, since it works with a mouse only (§4.3).
- Targets are at least 24 × 24 px (WCAG 2.5.8), inline number chips included (§4.6).
- Nothing is dimmed with opacity when its text must stay readable: a faded state uses a muted color or a dashed border instead (§5.7).
- The end-to-end flow (`web/e2e/axe.ts`, called from `flow.spec.ts`) runs axe-core 4.10 with the `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa` and `wcag22aa` tags on five screens: the empty library, the dashboard with stories, the CSV tab with the thread open, the Flow canvas, and the Changes panel with an undone step. Any violation fails it.
- Charts have an accessible alternative: "Show as table" in the widget menu, and an `aria-label` summarizing the chart from its fact sheet. Not built yet: the Bklit charts' SVGs are `aria-hidden` with no summary; only the custom charts carry one.
- Grid cells and canvas nodes are keyboard reachable. Canvas nodes and connections are named ("Story card: Survival rate. Overall survival rate was 38.2%.", "Note: …", "Connection from Survival rate to Synthesis, labelled summarized in"), and React Flow's own descriptions and movement announcements are in Sherlock's words (`ariaLabelConfig`). Cell provenance by keyboard (Ctrl+I) is removed with cell provenance by cut 5.
- Drawers and dialogs trap focus and restore it; Esc closes.
- `prefers-reduced-motion` and the setting disable animation, and the spotlight becomes a 1px ring (the setting is removed by cut 1). Not built yet in full (§2.4).
- Nothing relies on hover alone: every hover reveal (card linking, column notes) has a click or keyboard path. Not built yet: card linking has a click path but no keyboard path, and column notes are hover-only.

---

## 9. Theme switching

- `<html class="dark">` sets Dark mode; `<html data-accent="verdigris">` (or `arcane`, `ember`, `aether`, `brass`) sets the accent tokens. With no `data-accent`, Verdigris applies.
- **ThemeSync** (`web/src/app/ThemeSync.tsx`) applies the settings from the user's server profile (`GET /me`), not browser storage, to `<html>`, and follows the OS's `prefers-color-scheme` while the mode is System.
- Bklit charts, Glide Data Grid (a theme object built from the resolved CSS variables and rebuilt on theme change) and React Flow (node styles from tokens) all switch with it. Code blocks are plain `--muted` mono (no Shiki).
- Fonts load once; both modes use the same families and weights.
- Screenshots and "Copy as image" (P1, not built) render with the active theme.
- Implementation:
  - **Where the tokens live.** Every §2 token is in `web/src/app/theme.css`; `web/src/index.css` imports it and maps the tokens to Tailwind 4 utilities in `@theme inline`, for example `bg-card`, `text-info` and `bg-accent-soft`. There's no `tailwind.config.*`.
  - **Derived tokens.** `--accent-soft`, `--spotlight`, `--unsaved` and `--info-soft` are `color-mix()` of the active `--accent` or `--info`, so they follow every accent and mode without extra hex values. Under Aether, `--info-soft` follows the brass `--info`.
  - **Two more `<html>` attributes**, from the settings. Under cut 1 the dialog doesn't offer them, so they keep their defaults (subtle, and the OS preference) unless a saved value says otherwise:
    - `data-spotlight="off"|"subtle"|"full"` picks `--spotlight-shadow` (default subtle).
    - `data-reduce-motion="on"|"off"` overrides the OS preference; the stored `system` removes the attribute. With motion reduced, every `--duration-*` is 0 and the spotlight is the 1px ring.
  - **Tokens the brief doesn't name.** `--popover-foreground` and `--secondary-foreground` equal `--foreground` (shadcn needs them). The radii are `--radius-chip`, `--radius-number-chip`, `--radius-control` and `--radius-surface`; the overlay shadow is `--shadow-overlay`; the easing is `--ease`. The other variables Bklit's components read (`--chart-positive`, `--chart-scale-01` … `05`, `--chart-marker-*` and so on) map onto the tokens above, with no new colors.
  - **Fonts** are self-hosted from `@fontsource-variable` (Inter, Source Serif 4, Geist Mono), served from the app's own origin.
  - **Test.** `web/src/app/theme.test.ts` checks the §2.1 values and the §8 contrast rules: `--background` and `--card` in each mode, every accent in both modes, Aether's brass `--info`, each accent at 4.5:1 on ground and card, muted text at 4.5:1 and chart greys at 3:1 on `--card`.

---

## 10. What's deliberately not in the design

No gradients, no illustration, no hero imagery, no card shadows (§2.3), no colored chart palettes, no badges on every element, no onboarding tour (the empty state and the empty thread's hint do that job, §4.8; suggested questions are removed by cut 9), no dark-mode-only or light-mode-only features.
