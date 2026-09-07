---
name: LoopForge
description: A dense, keyboard-first terminal control room for supervised local workflows.
colors:
  inverse-black: "#0A0A0A"
  metrics-recess: "#0F0D15"
  panel-ink: "#15121B"
  command-slate: "#1D1A23"
  quiet-selection: "#2C2832"
  divider-violet: "#494454"
  idle-border: "#808080"
  focus-violet: "#8B5CF6"
  muted-lilac-gray: "#958EA0"
  quiet-text: "#C7C6C6"
  secondary-text: "#CBC3D7"
  focus-lavender: "#D0BCFF"
  primary-text: "#E7E0ED"
  attention-amber: "#FFB869"
  blocked-coral: "#FFB4AB"
  complete-mint: "#A8E6B0"
typography:
  product:
    fontFamily: "inherit"
    fontWeight: 700
  body:
    fontFamily: "inherit"
    fontWeight: 400
  label:
    fontFamily: "inherit"
    fontWeight: 400
rounded:
  square: "0"
spacing:
  cell: "1 cell"
  gutter: "2 cells"
components:
  panel:
    backgroundColor: "{colors.panel-ink}"
    textColor: "{colors.primary-text}"
    rounded: "{rounded.square}"
    padding: "0"
  selection-row-quiet:
    backgroundColor: "{colors.quiet-selection}"
    textColor: "{colors.primary-text}"
    rounded: "{rounded.square}"
    padding: "0 1 cell"
  selection-row-focused:
    backgroundColor: "{colors.focus-lavender}"
    textColor: "{colors.inverse-black}"
    rounded: "{rounded.square}"
    padding: "0 1 cell"
  command-input:
    backgroundColor: "{colors.command-slate}"
    textColor: "{colors.primary-text}"
    rounded: "{rounded.square}"
    padding: "0 1 cell"
---

# Design System: LoopForge

## Overview

**Creative North Star: "The Quiet Control Room"**

LoopForge is a nocturnal, terminal-native operations surface: dense enough to keep the state of several projects in view, calm enough that a developer can scan it for long sessions. It feels like a purpose-built instrument rather than a decorated application. A restrained violet cast ties its black and graphite surfaces together, while lavender appears only where the current focus or next action must be unmistakable.

The interface stays flat, rectangular, and grid-bound. Hierarchy comes from tonal layers, borders, alignment, and a single inverted selection row rather than large type, illustration, or dimensional effects. Color is evidence: warm amber signals attention, coral signals a blocker, mint signals completion, and quiet gray carries neutral state.

**Key Characteristics:**

- Dense two-panel scanning in a full-screen terminal frame.
- Flat graphite layers with a subtle violet undertone.
- Lavender focus treatments that are rare and unambiguous.
- Monospaced alignment as both typography and layout infrastructure.
- Contextual hotkey guidance that changes with the selected project and panel.

## Colors

The palette is a near-black violet-neutral system with one lavender focus family and a small set of factual status colors.

### Primary

- **Focus Lavender** (`#D0BCFF`): the strongest interaction color, used for focused-row inversion, the command frame, metric values, and key command guidance.
- **Focus Violet** (`#8B5CF6`): the active-panel border that identifies which list owns keyboard navigation.

### Secondary

- **Attention Amber** (`#FFB869`): counts and markers that need human attention.
- **Blocked Coral** (`#FFB4AB`): blocked and failed state markers.
- **Complete Mint** (`#A8E6B0`): completed state markers.

### Neutral

- **Inverse Black** (`#0A0A0A`): the high-contrast text color inside a focused selection; it is not a home-screen surface.
- **Metrics Recess** (`#0F0D15`): the metrics surface, its title cutout, and the hotkey footer.
- **Panel Ink** (`#15121B`): the full home canvas, header, list panels, resting list rows, and the title cutouts for list and command panels.
- **Command Slate** (`#1D1A23`): command-entry surface.
- **Quiet Selection** (`#2C2832`): the highlighted row when its panel is not active.
- **Divider Violet** (`#494454`): structural dividers and low-emphasis borders.
- **Idle Border** (`#808080`): resting panel outlines and titles for panels that do not own keyboard focus.
- **Muted Lilac Gray** (`#958EA0`): metric labels, placeholders, and low-priority hotkeys.
- **Quiet Text** (`#C7C6C6`): version text and neutral status markers.
- **Secondary Text** (`#CBC3D7`): panel titles, summaries, and secondary guidance.
- **Primary Text** (`#E7E0ED`): ordinary readable content.

**The Focus Is Lavender Rule.** Lavender identifies current keyboard ownership or command affordance; it is not a decorative wash.

**The Status Is Sparse Rule.** Semantic colors belong on markers and short attention phrases, not across entire panels or rows.

## Typography

**Display Font:** the user's terminal monospace, inherited from the terminal.

**Body Font:** the user's terminal monospace, inherited from the terminal.

**Label/Mono Font:** the same terminal monospace.

**Character:** The typography is technical, compact, and native to its environment. It relies on column alignment and restrained weight changes instead of a multi-family or multi-size hierarchy.

### Hierarchy

- **Product** (bold, one terminal row): persistent product identity in the header.
- **Panel title** (regular, one terminal row): border-integrated labels such as `METRICS`, `Projects`, `Active runs`, and `Command Input`.
- **Body** (regular, one terminal row): project names, run tasks, metadata, metric values, and commands.
- **Muted label** (regular, one terminal row): metric labels, placeholders, version text, and secondary hints.

**The One Grid Rule.** Keep every label, value, marker, and timestamp on the terminal's monospaced character grid so columns remain scannable without extra rules.

## Layout

The home screen is a fixed vertical stack inside the terminal: a three-row identity header, a six-row metrics panel, a flexible two-column workspace, a four-row command area, and a two-row hotkey footer. Main content uses two-cell side margins and a two-cell gap between equal-width project and run panels. Each list row reserves a marker column, a flexible text field, and right-aligned counts or age metadata.

Selection changes content in place. Startup highlights `All projects`; choosing a project refreshes metrics and filters active runs without navigating to another screen. The left panel is the initial keyboard owner. Up and Down move the visible row selection immediately. Project details - active runs, metrics, adapter, and status - render once, 150 milliseconds after the last arrow key, so rapid navigation does not repaint the detail region for every intermediate row. Enter and Right cancel any pending delay and synchronize those details immediately before focus moves to runs. Left and Right switch panel ownership, and Enter on a run opens it.

At 60 columns or narrower, side margins contract to one cell, the project summary and center hotkey hint disappear, and the two list panels stack vertically. The layout must preserve a visible command area and at least one usable list region before retaining secondary summary text.

**The Persistent Console Rule.** Identity, current metrics, project/run context, command entry, and the relevant hotkeys remain visible together whenever terminal space permits.

**The Cursor First Rule.** Cursor movement is immediate; dependent project details are coalesced behind a 150 millisecond trailing delay, while Enter and Right commit them synchronously before changing focus.

## Elevation & Depth

The system has no shadows. Depth is conveyed through nested tonal surfaces and border contrast: a panel-ink home canvas, the darker metrics and footer recess, and a slightly lighter command surface. Active focus increases border chroma and inverts the current row; it never lifts a surface.

**The Flat By Default Rule.** Do not add shadows, gradients, glow, translucency, or simulated physical elevation to the terminal workspace.

## Shapes

The shipped terminal surface uses square, cell-aligned geometry with no corner radius (`0`). One-cell solid borders define panels, while title text interrupts the top border in the native Textual style. Selection is a full-width rectangular band. Status marks are compact glyphs rather than enclosed pills.

**The Cell Edge Rule.** Containers, focus states, and dividers align to terminal cells; no floating or partially inset geometry is used.

## Components

### Header

- **Shape:** a three-row, full-width rectangular strip with a divider on its bottom edge.
- **Content:** product name and version on the left; total projects and attention count on the right.
- **State:** the attention phrase alone receives semantic amber; the header itself does not change on project selection.

### Metrics Panel

- **Shape:** square panel with a border-integrated `METRICS` title whose cutout matches the metrics recess.
- **Layout:** four facts in a two-by-two grid; labels are muted and values use focus lavender.
- **Behavior:** aggregate facts are shown for `All projects`; selecting a project swaps in project, Git, pack, and adapter facts.

### Project and Run Panels

- **Shape:** equal-width, square bordered containers at normal widths.
- **Resting state:** panel ink with an idle gray border and idle gray title; the title cutout matches the panel-ink home canvas.
- **Focused state:** the owning panel uses the focus-violet border and focus-lavender title.
- **Behavior:** the project cursor moves immediately. Project runs and metrics refresh once after the 150 millisecond trailing delay; Enter or Right synchronizes them immediately before focusing runs. Empty runs return keyboard ownership to projects.

### Selection Rows

- **Shape:** a full-width rectangular band with one cell of horizontal padding.
- **Quiet highlight:** graphite-violet with primary text when the cursor is visible in a panel that does not own focus.
- **Focused highlight:** focus lavender with inverse-black text when the panel owns keyboard input.
- **Content:** status marker first, flexible label or task in the middle, count or relative age aligned at the right edge.

### Command Input

- **Shape:** square, bordered command panel with a one-row input, one-row command hint, and a title cutout matching the panel-ink home canvas.
- **Resting state:** command-slate surface, primary text, muted placeholder.
- **Focus state:** entered text turns focus lavender while the surface remains stable.
- **Behavior:** `/` activates command entry. Enter dispatches only values beginning with `/`; plain text remains visible and inert.

### Status Markers

- **Style:** one glyph before the row; no background container and no extra label when the row already carries status text.
- **Assignment:** needs-human uses attention amber, blocked uses blocked coral, running uses focus lavender, complete uses complete mint, ready and waiting use quiet text, and archived uses muted lilac gray.

### Hotkey Bar

- **Layout:** contextual action at left, navigation instruction centered, quit at right, all on the same recessed surface as metrics.
- **Behavior:** `New Run` appears only for an individual project. It is absent for `All projects`; there is no `New Project` hint. The center copy changes from focusing runs to opening a run as panel ownership moves.

## Do's and Don'ts

### Do:

- **Do** keep the initial selection on `All projects` with the project panel focused.
- **Do** use focus lavender for the active row and focus violet for the active panel border.
- **Do** keep project counts, run ages, and metric pairs aligned to the terminal grid.
- **Do** update metrics, filtered runs, and hotkey guidance together when project selection changes.
- **Do** move the project cursor immediately, then render runs, metrics, adapter, and status once 150 milliseconds after the last Up or Down input.
- **Do** cancel the pending detail delay and synchronize project details immediately before Enter or Right transfers focus to runs.
- **Do** keep plain text inert in the command field and dispatch slash-prefixed commands only.

### Don't:

- **Don't** show `New Run` or `Ctrl+N` while `All projects` is selected.
- **Don't** add a `New Project` action or shortcut to this surface.
- **Don't** use whole-panel warning, error, or success fills; status color stays local to its marker or phrase.
- **Don't** add rounded cards, shadows, gradients, decorative imagery, or proportional typography to the terminal workspace.
- **Don't** introduce a second navigation or command path that diverges from the shared LoopForge behavior.
