# Test Contract

This file is the canonical local instruction file for `tests/`.

## Scope

- Parent guidance from the repository root `AGENTS.md` still applies.
- Tests in this repository often exercise real HEC-RAS-adjacent behavior. Treat them as domain validation, not isolated toy examples.

## Working Rules

- Use `pytest` for targeted runs.
- Prefer tests that exercise real example projects or actual file formats over mocks when the behavior depends on HEC-RAS semantics.
- Keep generated outputs in temporary folders or ignored working folders, not in `tests/`.
- If a test requires external software or data that is unavailable, skip or scope the test cleanly rather than silently weakening assertions.

## Hygiene

- Do not commit ad hoc outputs such as text dumps, screenshots, or local validation images.
- Remove or ignore temporary debug files created during test development.
