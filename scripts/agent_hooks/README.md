# Cross-Harness Hooks

This directory contains shared hook logic used by Claude Code and Codex.

Harness-specific files are intentionally thin:

- `.claude/settings.json` registers Claude Code project hooks.
- `.codex/hooks.json` registers Codex project hooks.
- `.codex/config.toml` enables Codex hooks for this project.

Both adapters call `hook_dispatch.py`, which reads hook JSON from stdin and
returns the JSON output shape expected by the active harness.

The dispatcher is Python-only and avoids Bash/PowerShell-specific behavior, so
the same policy runs on Windows, macOS, and Linux as long as `python` and `git`
are available on `PATH`.

The current hooks are conservative:

- add a short session-start reminder that `AGENTS.md` is the shared contract
- block obviously destructive recursive deletion and hard reset commands
- block direct edits to generated `.agents/skills/` bridge entries

Hooks are guardrails, not a security boundary. Keep critical policy in
`AGENTS.md`, code review, and explicit validation.
