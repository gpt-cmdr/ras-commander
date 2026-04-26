---
paths: ras_commander/**, examples/**
---

# Commit Policy: Library Code Requires Notebook Coverage

**Context**: Ensures every new library function ships with test coverage and documentation
**Priority**: Critical - applies to all commits adding new public API
**Auto-loads**: Yes (library and examples code)

## Core Rule

Every commit that adds **new public library functions** to `ras_commander/` MUST include:

1. **Example notebook coverage** in `examples/` exercising the new function with real-world data (RasExamples, eBFE, USGS, or other production sources — never mocks)
2. **Documentation update** in the relevant subpackage `AGENTS.md` listing the new method or changed shared behavior
3. **Evidence the function was tested** (notebook executed successfully or verified)

All three elements ship in the **same commit** so every commit is self-contained.

## Exemptions

| Category | Notebook Required? | AGENTS.md Required? |
|----------|--------------------|---------------------|
| New public library function | Yes | Yes |
| Bug fix to existing function with existing coverage | No | No |
| Framework/governance files (`.claude/` rules, skills, commands) | No | No |
| Documentation-only changes (docs/, mkdocs.yml) | No | No |
| Refactoring with no public API change | No | No |

## .py Test Files

Files in `tests/` are **temporary development scaffolding**:

- Useful during implementation for quick iteration
- May inform later notebook creation
- Must NOT be included in library commits
- Clean up when the corresponding notebook exists

## Blocking Commits

If notebook coverage or AGENTS.md docs are missing, the commit is **BLOCKED** until prerequisites are met. Track blocked commits explicitly in the plan with unblocking steps.

## Rationale

- Notebooks serve as both documentation and functional tests
- Real-world data catches integration issues mocks would miss
- AGENTS.md updates keep subpackage API docs current
- Self-contained commits enable clean git bisect and cherry-pick
