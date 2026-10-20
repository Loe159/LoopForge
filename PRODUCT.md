# Product

<!-- impeccable:product-schema 1 -->

## Platform

terminal (Textual TUI and local CLI)

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
- The detailed existing landing-screen design remains valid. A [separate run UX plan](docs/plans/2026-10-20-001-run-live-context-ux-plan.md) now scopes Live, Context, Changes and Evidences (planned, not implemented).

## Brand Commitments

The product name is LoopForge. The repository-tracked [DESIGN.md](DESIGN.md) is the primary design-system reference for the terminal landing screen. The proposed run extension preserves its visual language.

## Design references

- [DESIGN.md](DESIGN.md): existing terminal foundation.
- [Native agent observation](docs/decisions/agent-run-observation.md): implemented capabilities and limitations.
- [Run four-view plan](docs/plans/2026-10-20-001-run-live-context-ux-plan.md): proposed, not implemented.

The previous evidence section listed local Windows download paths not tracked in the repository. Such paths are not portable documentation.

## Product Principles

- Keep important project and run state visible without requiring a command.
- Preserve one behavior path across the TUI and existing command surfaces.
- Make keyboard focus and the next available navigation action unambiguous.
- Show only factual local state and supported actions.
