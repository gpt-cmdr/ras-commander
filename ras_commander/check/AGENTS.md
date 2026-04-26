# RasCheck Contract

This file is the canonical local instruction file for `ras_commander/check/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles model QA checks for steady and unsteady HEC-RAS workflows.

## Core Surface

- `RasCheck` - main entry point for validation checks
- `messages.py` - standardized check message content
- `report.py` - report generation and exports
- `thresholds.py` - default and custom validation thresholds

## Critical Rules

- Preserve the flow-type auto-detection behavior. `run_all()` must choose the correct steady or unsteady check set from actual model inputs.
- Keep result severity and threshold handling explicit.
- Reports should stay reviewable and suitable for engineering QA workflows.
- When a check depends on HDF output or results summaries, make that dependency obvious in naming and documentation.

## Relationship To Fixit

- `check/` detects issues.
- `fixit/` repairs some issue classes.
- Do not blur those responsibilities by putting repair logic into `check/` unless the design explicitly changes.

## Testing

- Validate checks against real models and real results where possible.
- Use custom thresholds only when the task or local standard actually requires them.
