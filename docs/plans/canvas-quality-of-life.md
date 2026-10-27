# Plan: quality of life on the Flow canvas

**Status:** proposal, not built. Nothing here is a spec until the PRD, App Flow and UI/UX brief say it (CLAUDE.md Rule 1). Items marked **Owner** need a decision first; §9 collects them.

**In one line:** keep the canvas as it works today and add what people expect from a canvas: buttons on screen for every action, a menu on every node, box selection, undo and redo, quicker ways to add and arrange notes, and names for screen readers. Every addition uses the controls, wording and rules the rest of Sherlock already uses.

---

## 1. Why

The Flow tab (App Flow §12, UI/UX §5.10, `web/src/components/flow/`) does what PRD FLOW-1–FLOW-6 ask. You can pan, zoom and fit, use the minimap, and save automatically with a merge. Cards come in from the palette. Notes and labelled edges work, as do Connect mode, Shift-click selection, double-click editing and Delete with an Undo toast.

It still feels bare next to other canvases, for three reasons:

- **Some actions have no button.** Removing anything works only from the keyboard. On the Dashboard and in the Stories panel, the same objects have a ⋯ menu or a trash button. A mouse-only or touch user can't remove anything from the canvas.
- **Familiar canvas habits don't work.** There's no box selection, no Ctrl+Z, no duplicate, no zoom readout and no right-click. Double-clicking empty space zooms in instead of adding a note.
- **The canvas has drifted from the rest of the site.** Its buttons are hand-written copies of `ui/button.tsx`, its zoom animations ignore reduced motion, and its nodes have no accessible names (§3).

The owner likes how the canvas works today and wants **buttons on screen**. So this plan adds controls and changes very little that already exists.

---

## 2. Design principles

There are two kinds of consistency (Nielsen's heuristic 4, *consistency and standards*). **Internal** means the canvas behaves like the rest of Sherlock. **External** means it behaves like the canvases people already know: Figma, FigJam, Miro, tldraw, Obsidian Canvas. When the two disagree, Sherlock's own rules win for how a control looks and what words it uses. Canvas conventions win for gestures and keys, because people bring those from other tools.

| # | Principle | Where it comes from | What it means on the canvas |
|---|---|---|---|
| P1 | **Every action has a visible control; shortcuts are only faster.** | UI/UX §8 ("nothing relies on hover alone"); the owner's request | Remove, connect, duplicate and undo each get a button or menu item. Keys stay as shortcuts. |
| P2 | **The same object offers the same actions everywhere.** | PRD FLOW-2 (a card on the canvas is the same object as in the panel) | A card node offers what its story card offers: Edit, Ask why, Open widget, Delete. |
| P3 | **One component per job.** | UI/UX §4; the audit in §3 | `ui/button.tsx` for every button, `ui/menu.tsx` for every menu, sonner for every toast. No hand-written copies. |
| P4 | **Undo instead of confirm.** | UI/UX §6 | Removals don't ask first. They show a 10 s toast with Undo, and Ctrl+Z works afterwards. A confirmation only for a loss Undo can't reverse (none on the canvas). |
| P5 | **× removes something from a place; the trash can deletes it.** | Today's code: × on filter chips, pending edits and plan steps; `Trash2` on widget, card and dataset Delete | "Remove from canvas" on a card node uses ×, because the card stays in the palette. "Delete note" and "Delete card" use `Trash2`. |
| P6 | **Chrome stays thin; the selection carries the actions.** | UI/UX §1 ("chrome stays thin"); the CSV toolbar, whose buttons change with the selection | Nothing new shows on an idle canvas. Selection actions go in the existing status row at the top left, which is already where Make sense of this appears. Node menus appear on hover, focus or selection. |
| P7 | **Color only where it carries meaning.** | UI/UX §1, §2.1 ("never introduce a color outside these tables") | No colour picker for notes or edges (§9, O-3). The accent marks only the selection, AI edges and the connect hint, as today. |
| P8 | **Canvas keys follow canvas tools.** | Figma, tldraw and Miro conventions | Ctrl+A, Ctrl+Z / Ctrl+Shift+Z, Ctrl+D, Ctrl+C / Ctrl+V, Esc, the arrow keys, Shift+1 (fit), Shift+2 (zoom to selection), Ctrl+0 (100%). They work only while the canvas has focus and no input, note or editor does (UI/UX §6). |
| P9 | **Shortcuts show where the action is.** | `DatasetMenu.tsx:111`, the only shortcut hint in the app | Each menu item shows its key on the right, in that same mono 11px muted style. The `?` shortcuts sheet stays cut (cut 9). |
| P10 | **Motion follows the tokens.** | UI/UX §2.4 | Zoom, fit and centring use `--duration-base`, and take 0 ms when motion is reduced. |
| P11 | **Same words for the same act.** | UI/UX §7; today's toasts | "Removed 2 items from the canvas" (a card isn't deleted), "Note deleted", "Card deleted", always with Undo for 10 s. Sherlock is "Sherlock" in UI text. |
| P12 | **Keep what's built; add, don't rearrange.** | The owner | The header context row, palette, minimap, zoom pill, connect flow and double-click editing stay where they are and work as they do. |

---

## 3. Where the canvas departs from the site today

From an audit of `web/src` (file and line numbers as of `e8141a1`):

| Area | Rest of the site | Canvas today | Fix |
|---|---|---|---|
| Buttons | `Button size="sm"` (Dashboard actions, Save, CSV toolbar) | Hand-written classes in `FlowActions`, `FlowStatus` and `Zoom` (`FlowPalette.tsx:101-120`, `FlowTab.tsx:552-558`) | C-12 |
| Pressed toggle | `aria-pressed` and `bg-secondary` (Edit layout, `DashboardActions.tsx:35-41`) | Connect also adds `text-accent` | C-12 |
| Removing | A ⋯ menu with a destructive Delete (widgets, datasets), or a ghost `Trash2` (story card) | Delete key only | C-1, C-2 |
| Zoom buttons | Focus ring with offset (`ui/button.tsx`); `title` on icon buttons | No visible focus, no `title`, hard-coded 200 ms | C-6, C-12 |
| Shortcut hints | Mono 11px on the right of a menu item | None | C-2 |
| Accessible names | Named controls everywhere | Nodes focusable but unnamed (UI/UX §8, not built yet) | C-11 |
| Empty state | Icon, title, sentence, one primary action (UI/UX §4.13) | No icon, no action | C-13 |
| Motion | `duration-[var(--duration-*)]` | `{ duration: 200 }` and `300` hard-coded | C-6 |

**Gaps the whole site shares**, so they aren't canvas-only:

- **Tooltips:** the site has no tooltip component; every tooltip is a native `title` (UI/UX §4.11, not built yet).
- **Keyboard undo:** no Ctrl+Z anywhere. CSV buffer undo was removed by cut 5.
- **Context menus:** no right-click menu anywhere.

§5 says which of these this plan builds once, for the whole site.

---

## 4. The improvements

Each item gives what it does, the principles behind it, where the code goes and a rough size: S is up to half a day, M is about a day.

### 4.1 On-screen actions

**C-1. Selection actions in the status row (S).** The row at the top left reads "Story canvas · 6 nodes · 2 selected" and shows Make sense of this. It grows into the selection bar (P1, P6):

- **Count:** "· 2 selected" counts nodes and connections: "1 note and 1 connection selected".
- **Make sense of this:** primary, two or more cards selected, as today.
- **Connect:** ghost; shown when exactly two nodes are selected. It draws an edge from the first one picked to the second and opens its label input, like the second click in Connect mode.
- **Remove:** ghost with ×; shown while anything is selected. It calls `deleteElements` on the selection, so it shows the same toast and Undo as the Delete key (`FlowTab.tsx:494`).
- **Accessibility:** the buttons have `aria-label`s that say what they act on: "Remove 2 items from the canvas".

**C-2. A ⋯ menu on every node (M).** A `size-7` ghost trigger at the top right of the node's header, copied from the widget menu (`WidgetShell.tsx:116-124`). It is hidden until the node is hovered, focused or selected, as on library rows (`opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100`, `LibraryPanel.tsx:177`). It uses `ui/menu.tsx`. The items, each with its shortcut on the right (P9):

| Card node | Note | Connection (on its label pill, C-9) |
|---|---|---|
| Edit (double-click) | Edit (double-click) | Edit label (double-click) |
| Ask why | Duplicate (Ctrl+D) | Reverse direction |
| Open widget | Connect from here | Remove label |
| Connect from here | — | — |
| *separator* | *separator* | *separator* |
| × Remove from canvas (Del) | 🗑 Delete note (Del) | 🗑 Delete connection (Del) |
| 🗑 Delete card | | |

- **Delete card** soft-deletes the story card, exactly like the story card's own trash button, with the same "Card deleted" toast and Undo (P2; `StoryCard.tsx:210-216`). Its node hides, as it does today when the card is deleted elsewhere.
- **Ask why** uses the story card's `askWhy` path, with this card as the chat's context.
- **Connect from here** turns Connect mode on with this node already picked, so the next click finishes the edge.

**C-3. Right-click opens the same menu (S).** `onNodeContextMenu`, `onEdgeContextMenu` and `onPaneContextMenu` (React Flow 12.11) open the node's ⋯ menu at the pointer (P8). The pane menu has Add note here, Paste (Ctrl+V), Select all (Ctrl+A) and Fit view (Shift+1). **Owner O-1** decides how: add `@radix-ui/react-context-menu` with `ui/menu.tsx`'s styles, or open the existing dropdown at a virtual anchor. Either way it's one menu look for the whole site.

### 4.2 Selection

**C-4. Box selection, Select all and Esc (S).**
- **Box selection:** Shift-drag on empty canvas draws a box (React Flow's `selectionKeyCode`, today `null`). A plain drag still pans, so nothing that works today changes (P12). The box keeps its current style (`index.css:159-162`).
- **Select all:** Ctrl+A selects every visible node.
- **Esc:** clears the selection (React Flow does this already; the docs will say so).
- **App Flow §12.2:** "There is no box selection" is replaced.

### 4.3 History

**C-5. Undo and redo (M).**
- **The stack:** every finished change this tab makes goes on it, up to 50 entries per dataset. That covers adding, removing, the end of a move, resizing, label and note edits, and connecting.
- **Undo and Redo:** Ctrl+Z undoes, Ctrl+Shift+Z or Ctrl+Y redoes. There are also two ghost icon buttons, `Undo2` and `Redo2`, in the zoom pill. They are dimmed when there's nothing to undo, and their tooltip names the step: "Undo move".
- **Undoing only this tab's changes:** each entry keeps the document before and after its change. Undoing applies after → before on top of the current document with `mergeCanvas(after, before, current)` (`api/canvas.ts`). That reverses only this tab's change and keeps a synthesis the AI placed meanwhile. Redo is the same call the other way round.
- **The removal toast's Undo goes through the same stack**, so the toast and Ctrl+Z always agree.
- **Scope:** canvas only, in this browser tab, gone on reload. Cards edited through the card editor keep their own history (the card's versions). Undo on the canvas covers where things are, not what a card says.
- **Owner O-2:** this is the first Ctrl+Z in the app.

### 4.4 View

**C-6. Zoom readout and view shortcuts (S).**
- **The readout:** the zoom pill becomes − · 100% · +. Clicking the percentage resets to 100%.
- **Shortcuts:** Shift+1 fits all (the same as Fit view), Shift+2 zooms to the selection, Ctrl+0 goes to 100%, Ctrl+= and Ctrl+− zoom in and out. Each shows in its button's tooltip.
- **Motion:** every animated move (zoom, fit, centring on a placed card) reads its duration from `--duration-base`, and takes 0 ms when motion is reduced (P10). A small `motionMs("base")` helper in `lib/` does the reading, and the rest of the site can use it too.

**C-7. Scrolling (S, Owner O-4).** Today the wheel zooms. In Figma and Miro, a two-finger scroll pans and pinching or Ctrl+wheel zooms. React Flow does that with `panOnScroll` and `zoomActivationKeyCode`. This changes a documented behaviour (App Flow §12.2, Scroll / pinch), so it's the owner's call.

### 4.5 Adding and arranging

**C-8. Faster ways to add (S each).**
- **Double-click empty canvas** adds a note there, in edit mode (`zoomOnDoubleClick={false}`). Double-clicking a node still edits it.
- **Drag from a node's handle into empty space** adds a note there, connected and in edit mode (`onConnectEnd`).
- **Duplicate:** Ctrl+D, or Duplicate in the menu, copies the selected notes, and the edges between them, 22px down and right.
- **Copy and paste:** Ctrl+C and Ctrl+V copy and paste notes and the edges between them. Pasting plain text from elsewhere makes a note. Pasting a card that's already on the canvas selects it instead of adding it twice (a card is on the canvas once, TRD §4.7).

**C-9. Arranging (S each).**
- **Snap to the dot grid:** nodes snap to the 22px grid (`snapToGrid`, `snapGrid={[22, 22]}`). The arrow keys already move a focused, selected node (React Flow's default); the docs will say so.
- **Resize:** notes and cards can be widened with React Flow's `NodeResizer` on their right edge. Notes go from 160 to 480px, cards from 240 to 480px; height follows the content. The width is saved in the JSON Canvas `width` the server already stores. `toFlow` reads it instead of forcing `CARD_W` and `NOTE_W`.
- **Edges:**
  - clicking a label pill selects its edge, so Remove and the menu reach it;
  - dragging an edge's end onto another node reconnects it (`onReconnect`).

**C-10. Arrange menu (M, after the rest).** With two or more nodes selected, the status row gets an Arrange ▾ menu:
- align left, centre or right, and top, middle or bottom;
- distribute horizontally or vertically;
- **Tidy**, PRD FLOW-7's auto-layout.

Alignment guides while dragging, like React Flow's helper-lines example, can come later.

### 4.6 Accessibility and finish

**C-11. Names and announcements (S).**
- **Card nodes** are named "Story card: <overline>. <headline in plain text>".
- **Notes** are named "Note: <first 80 characters>".
- **Edges** are named "Connection from <A> to <B>[, labelled <label>]" (`domAttributes` / `ariaLabel`).
- **Built-in descriptions:** `ariaLabelConfig` puts React Flow's own descriptions and movement announcements into Sherlock's words. Closes the UI/UX §8 "not built yet" line.

**C-12. Use the shared components (S).**
- **Header and status row:** `FlowActions`, `FlowStatus` and `Zoom` use `Button`. Add note is secondary. Connect is ghost with `aria-pressed` and `bg-secondary`; the accent hint pill at the top centre stays. Fit view is ghost, and Make sense of this is primary.
- **Zoom buttons:** they become `size="icon"` ghost buttons inside the existing `--card` pill, so they get the focus ring and a tooltip.
- **Card shadow:** the hard-coded card-node shadow (UI/UX §2.3) is dropped: "no card shadows".

**C-13. Empty state (S).** As UI/UX §4.13 asks:
- a 24px muted icon;
- "The canvas is empty" and its sentence;
- one primary action, **Add note**.

The overlay stays click-through, except the button.

**Not in this plan:**
- **Groups** (FLOW-7, P1) need containment rules and notebook-export decisions of their own. They're next after C-10.
- **Markdown in notes**: the app has no Markdown renderer. TipTap is already loaded for the card editor if the owner wants it (O-5).
- **Node colours**: see O-3.
- **The `?` sheet**: it stays cut (cut 9).

---

## 5. Shared pieces built once, for the whole site

| Piece | Where | Who else uses it |
|---|---|---|
| `ui/tooltip.tsx`: Radix Tooltip in the §4.11 style (`--popover`, 200 ms delay, two lines at most), with an optional shortcut | new; adds `@radix-ui/react-tooltip` | Every icon-only button UI/UX §4.1 lists as missing a tooltip. The canvas uses it first; moving the others over is a follow-up slice. |
| `MenuShortcut` in `ui/menu.tsx`, made from `DatasetMenu.tsx:111` | `ui/menu.tsx` | The dataset menu switches to it |
| `ContextMenu` with `ui/menu.tsx`'s item styles (if O-1 picks Radix) | `ui/menu.tsx` | Any future right-click menu |
| `motionMs(token)` | `lib/motion.ts` | Smooth scrolling to a widget or card, which ignores reduced motion today (UI/UX §2.4) |
| `useCanvasHistory`, the undo stack (C-5) | `components/flow/history.ts` | Canvas only |

---

## 6. Docs to update in the same commits (Rule 1)

- **PRD §7.8:**
  - new requirements FLOW-8 (on-screen actions, node menus, right-click), FLOW-9 (box selection and select all), FLOW-10 (undo and redo), FLOW-11 (faster adding, duplicate, copy and paste), FLOW-12 (snap, resize, reconnect), FLOW-13 (view shortcuts and zoom readout);
  - FLOW-3 and FLOW-4 gain removal acceptance criteria;
  - C-10's Tidy stays under FLOW-7.
- **App Flow §12.1:** the status row as the selection bar and the zoom pill's readout and undo buttons. **§12.2:**
  - rows for the ⋯ menu, right-click, box selection, select all, undo, duplicate, copy and paste, double-click on the background, dragging into empty space, resize, reconnect and the view shortcuts;
  - "There is no box selection" replaced;
  - the arrow-key move and Esc written down;
  - the Scroll row changed only if O-4 says so.
- **UI/UX brief:**
  - **§5.10:** the node menu trigger and its reveal; the status row's buttons; the readout; the resize edge; no card-node shadow.
  - **§4.11:** tooltips built.
  - **§2.4 and §8:** the "not built yet" lines this closes, removed.
  - **§6:** the canvas shortcuts listed under Keyboard.
- **TRD §2** (the frontend's Flow bullet): the undo stack and how it merges; `ui/tooltip.tsx`; the new dependency or dependencies.
- **TRD §4.7:** no change. Width, sides and `group` are already accepted.

---

## 7. How we verify it

- **Unit (Vitest, `flow.test.ts`):**
  - the undo stack: undo, then redo, gives back the same document;
  - undo after an AI synthesis landed keeps the synthesis;
  - the removal toast's Undo and Ctrl+Z agree;
  - paste of a card that's already placed selects it;
  - duplicate copies only the edges inside the selection;
  - `toFlow` keeps a saved width.
- **Component (`@testing-library`):**
  - the status row shows Remove and Connect at the right counts;
  - the ⋯ menu lists the right items per node kind;
  - Delete card shows the "Card deleted" toast with Undo;
  - shortcuts don't fire while a note or label input has focus.
- **End to end (`web/e2e/flow.spec.ts`):**
  - after Make sense of this, remove a card with the status-row Remove button, then Ctrl+Z;
  - open a node's menu by keyboard;
  - box-select two nodes.
  - axe still runs on the Flow canvas, now with named nodes and an open menu.
- **By hand, in both themes and with reduced motion:**
  - zoom and fit animate, or don't when motion is reduced;
  - the menu trigger shows on hover and on focus;
  - the canvas works with a mouse alone and with a keyboard alone.
- **Checks:** `corepack pnpm typecheck` (`tsc -b`) and `corepack pnpm test`, then `corepack pnpm e2e`.

---

## 8. Build order

Each slice is one verified commit to `main` with its doc changes.

1. **Shared components and the user's ask:**
   - C-12 (shared buttons);
   - `ui/tooltip.tsx` with `MenuShortcut`;
   - C-1 (status-row Remove and Connect);
   - the fix to connect mode below;
   - C-13 (empty state).
2. **Menus:**
   - C-2 (node ⋯ menu, with Delete card and Ask why);
   - C-3 (right-click);
   - C-9's label-click selection.
3. **History:** C-5 (undo and redo), with the toast's Undo moved onto the stack.
4. **Selection and adding:** C-4 (box selection, select all), C-8 (double-click, drag into empty space, duplicate, copy and paste).
5. **View and finish:**
   - C-6 (readout, shortcuts, motion tokens);
   - C-11 (names);
   - C-9's snapping, resizing and reconnecting.
6. **Later:** C-10 (Arrange and Tidy), then groups (FLOW-7).

**A fix that rides in slice 1:** removing the node picked first in Connect mode now clears that pick. Today `onDelete` doesn't reset `pendingSource` (`FlowTab.tsx:494`), so the next click makes an edge to a node that's gone, and the save drops it without a word.

---

## 9. Owner decisions and risks

### 9.1 Owner decisions

| ID | Question | Recommendation |
|---|---|---|
| O-1 | Right-click: add `@radix-ui/react-context-menu`, or reuse the dropdown at a virtual anchor? | Radix context menu. It's the same family and gives the same keyboard behaviour, with no new look. |
| O-2 | Ctrl+Z on the canvas only, while the rest of the app has none? | Yes. Every canvas tool has it, and its scope is clear (the canvas, this tab). The buttons make it findable. |
| O-3 | Node and edge colours (JSON Canvas presets `"1"`–`"6"`)? | No. The brief keeps colour for meaning and allows no colour outside its tables. Groups with labels are the way to organise. |
| O-4 | Scroll to pan and Ctrl or pinch to zoom, instead of wheel-to-zoom? | Yes, it's what trackpad users expect. But it changes what works today, so only on your word. |
| O-5 | Markdown in notes? | Later, with TipTap, which is already loaded. Not in this plan. |
| O-6 | Card width resizable, or notes only? | Both. Wider cards show more than six lines of body. |

### 9.2 Risks

- **Shift does two jobs.** Shift-drag draws the box and Shift-click adds to the selection. FlowTab's `adding` workaround (`FlowTab.tsx:295`, `:474`) has to keep working with both. Test it first.
- **Undo across tabs.** An undo merged onto a newer server copy can bring back a node another tab deleted, if this tab's change was the one that made it. That's acceptable: it's what the user asked to undo, and the next save merges.
- **Shortcut collisions.** Ctrl+D (the browser's bookmark), Ctrl+0 and Ctrl+= (the browser's own zoom) are taken over only while the canvas has focus, with `preventDefault`. Ctrl+Shift+E (export) and `/` (chat) stay global.
- **Menus inside nodes.** A Radix menu opened from inside a React Flow node must not start a drag or a pan. Mark its trigger `nodrag nopan`, as the existing in-node buttons are.

---

**Sources:**
- [NN/g, Consistency and standards](https://www.nngroup.com/articles/consistency-and-standards/)
- [React Flow accessibility](https://reactflow.dev/learn/advanced-use/accessibility)
- [React Flow undo and redo example](https://reactflow.dev/examples/interaction/undo-redo)
- [React Flow NodeResizer](https://reactflow.dev/docs/examples/nodes/node-resizer/)
- [JSON Canvas 1.0](https://jsoncanvas.org/spec/1.0/)
- [Figma keyboard use](https://help.figma.com/hc/en-us/articles/360040328653-Use-Figma-products-with-a-keyboard)
- [Miro shortcuts](https://miro.com/shortcuts/)
- [tldraw keyboard shortcuts](https://tldraw.dev/examples/ui/keyboard-shortcuts)
