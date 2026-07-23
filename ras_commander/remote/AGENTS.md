# Remote Execution Contract

This file is the canonical local instruction file for `ras_commander/remote/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles distributed HEC-RAS execution across local, PsExec, Docker, and future worker backends.

## Worker Structure

- Base worker and factory: `RasWorker.py`
- Implemented workers: `PsexecWorker.py`, `LocalWorker.py`, `DockerWorker.py`
- Stub or optional backends: `SshWorker.py`, `WinrmWorker.py`, `SlurmWorker.py`, `AwsEc2Worker.py`, `AzureFrWorker.py`
- Dispatch and orchestration: `Execution.py`, `Utils.py`

## Critical Rules

- HEC-RAS requires a desktop session on Windows remote hosts.
- For PsExec execution, always target a verified interactive desktop session with
  `session_id`. When `system_account=True` is required, preserve both PsExec
  flags (`-s -i <session_id>`) and validate HEC-RAS in that exact session.
- Keep optional backend dependencies lazy-loaded and guarded with explicit dependency-check functions.
- Use relative imports inside the subpackage.
- Keep the worker factory routing centralized in `init_ras_worker()`.

## Adding Or Editing Workers

1. Add or update the worker dataclass.
2. Add or update the backend-specific `init_*_worker()` helper.
3. Update dispatch in `RasWorker.py` and execution routing in `Execution.py`.
4. Export the public surface through `__init__.py`.
5. Keep dependency errors explicit and actionable.

## Testing

- Validate remote behavior against the real backend that the code targets.
- Do not claim a stub backend works unless its execution path is actually implemented.
