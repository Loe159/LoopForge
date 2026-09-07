# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

LoopForge serves developers operating local, keyboard-driven software workflows across one or more projects.

## Product Purpose

LoopForge provides a supervised workflow console for seeing which projects and runs need attention, selecting the relevant work, and executing existing local commands without leaving the terminal interface.

## Positioning

LoopForge keeps workflow execution local and bounded. Verification is evidence; it never grants review or publication authority.

## Operating Context

The primary surface is a full-screen terminal application. Operators move between project and run lists with the keyboard, open runs, and issue supported slash commands through a persistent command input.

## Capabilities and Constraints

- The main screen starts with All projects selected.
- Project selection filters metrics and active runs without opening another screen.
- Enter moves focus from the selected project to its runs; Enter on a run opens that run.
- Left and Right move focus between the project and run panels.
- The command input executes only input beginning with `/`; other text has no effect.
- New Run is available only when an individual project is selected and is hidden for All projects.
- The New Project shortcut is not part of the current surface.
- Existing engine APIs, project registries, run state, action descriptors, and slash-command dispatch remain authoritative.
- Only the main landing screen is in scope for the current redesign.

## Brand Commitments

The product name is LoopForge. The four user-supplied SVG files are the visual source of truth for the main screen, including palette, typography, spacing, component treatments, content hierarchy, and interaction states.

## Evidence on Hand

- `C:/Users/loedu/Downloads/LoopForge TUI - Design System & Screens.svg` defines foundations.
- `C:/Users/loedu/Downloads/Components.svg` defines component examples.
- `C:/Users/loedu/Downloads/Screen all projects.svg` depicts the selected-project state despite its inverted filename.
- `C:/Users/loedu/Downloads/Screen project active.svg` depicts the All-projects state despite its inverted filename.

No external claims, customer evidence, or network-backed content may be invented for this surface.

## Product Principles

- Keep important project and run state visible without requiring a command.
- Preserve one behavior path across the TUI and existing command surfaces.
- Make keyboard focus and the next available navigation action unambiguous.
- Show only factual local state and supported actions.
