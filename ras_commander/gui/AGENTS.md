# GUI Automation Contract

This file is the canonical local instruction file for `ras_commander/gui/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles HEC-RAS and RASMapper GUI automation.

## Architecture

- Layer 1: Win32 primitives and constants
- Layer 2: element finders for HEC-RAS and RASMapper surfaces
- Layer 3: orchestrated workflows built from steps and shared context

## Critical Rules

- Keep GUI code in the existing static-class style.
- Guard optional pywin32 behavior cleanly when Windows GUI dependencies are unavailable.
- Use workflow steps and shared context for multi-stage automation instead of hard-coded monolithic scripts.
- Prefer responsive-window checks over fixed sleeps when waiting for load completion.
- Preserve fallback chains for menu navigation or keyboard recovery when the UI is inconsistent.

## RASMapper Notes

- RASMapper is a different UI stack from the main HEC-RAS shell.
- TreeView and context-menu behavior needs RASMapper-specific handling.
- Mesh-generation timing is variable; avoid brittle timing assumptions.
