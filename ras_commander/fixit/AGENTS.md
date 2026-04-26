# RasFixit Contract

This file is the canonical local instruction file for `ras_commander/fixit/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles automated geometry repair workflows.

## Core Modules

- `RasFixit.py` - main repair entry points
- `obstructions.py` - blocked-obstruction parsing and envelope logic
- `results.py` - repair result containers
- `visualization.py` - optional visual outputs
- `log_parser.py` - compute-log parsing support

## Critical Rules

- Preserve the blocked-obstruction envelope behavior:
  - 0.02-unit gap insertion
  - max-elevation-wins overlap handling
  - 8-character fixed-width formatting
- Create backups before destructive writes.
- Keep result objects audit-friendly, with enough original and repaired context to support review.
- Make it clear that automated repairs still require engineering review.

## Testing

- Validate repairs against real geometry files and inspect outputs or plots when a repair changes geometry materially.
