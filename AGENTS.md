# ras-commander Agent Contract

This file is the canonical shared instruction contract for repository-local coding agents.

## Harness Loading

- Codex reads this file directly.
- Claude Code must import this file from the matching `CLAUDE.md`.
- The `AGENTS.md` hierarchy is the shared source of truth. Read the nearest file first, then inherit parent `AGENTS.md` files.
- `CLAUDE.md` files are loaders and Claude-specific adapters. They must not become a second documentation system.
- Shared rules belong in the `AGENTS.md` hierarchy or a shared skill corpus. Do not leave a rule that Codex also needs only in `.claude/rules/`.
- `.claude/rules/` is a Claude preload layer. It can restate or accelerate shared guidance, but it is not the canonical shared contract.
- `.claude/MANIFEST.md` is the current Claude component registry. It is useful for discovery, but it is not the source of truth for shared behavior.
- `.claude/agents/` contains Claude-native delegation roles. Keep them thin and point them back to shared instructions.
- `.claude/settings.json` and `.codex/hooks.json` are thin hook adapters that call shared hook logic under `scripts/agent_hooks/`.
- Primary first-class harnesses in this repository are Claude Code and Codex.

## Current Codex Skill Status

- Codex auto-loads `AGENTS.md`.
- Codex skill discovery can be enabled locally by generating `.agents/skills/` links:
  - `python scripts/agent_framework/sync_codex_skill_bridge.py`
- The bridge links explicitly allowlisted shared-domain skills from `.claude/skills/` and Codex-native adapter skills from `.agents/native-skills/`.
- A shared skill must declare `shared_corpus: true`, `harness_scope: shared`, accepted `source_owner`, and accepted `security_review` metadata before the bridge exposes it to Codex.
- A Codex-native adapter skill must declare `shared_corpus: false`, `harness_scope: codex_only`, accepted `source_owner`, and accepted `security_review` metadata.
- Skills marked `shared_corpus: false` or `harness_scope: claude_only` are excluded.
- `.agents/skills/*` entries are generated symlinks or Windows junctions, not source files. Do not edit them directly.
- Shared skill sources remain `.claude/skills/` until a later migration changes that explicitly.
- Codex-only provider handoff skills, such as Claude Code QAQC invocation, live in `.agents/native-skills/`.

## Recommended Harness Tools

- First-class harnesses for this repo are Claude Code and Codex.
- For Codex, use the repo's generated skill bridge before creating any copied skill tree.
- Codex may call Claude Code for independent QAQC through the Codex-native `dev_invoke_claude-code` adapter when the user explicitly requests Claude review.
- Claude may call Codex for independent QAQC through the Claude-native `dev_invoke_codex-cli` adapter when the user explicitly requests Codex review.
- For local browser inspection of docs or future UI work, Codex Browser Use is the only recommended browser plugin when available.
- For issue and PR workflows, GitHub's official CLI or MCP tooling is acceptable.
- Do not add generic agent-tool recommendation lists, Gemini, Context7, or copied parallel framework folders as repo-standard guidance.

## Agent Tool Supply Chain

- Agent-facing external tools, plugins, and skills should be written by `gpt-cmdr` or sourced from official Anthropic or OpenAI repositories.
- Treat third-party external plugins and skills from outside `gpt-cmdr`, Anthropic, or OpenAI as untrusted until audited.
- If a third-party plugin or skill is useful, audit it and re-implement the required behavior in this repository instead of linking to it as an external dependency.
- Do not make opaque third-party agent plugins, MCP servers, skills, or command wrappers part of the standard repo workflow.

## Do This First

- Ignore `ai_tools/` and generated knowledge-base artifacts. They are maintainer infrastructure, not the working codebase.
- Prefer cleaned notebooks when present. If a cleaned copy is not available, treat notebooks as reference and avoid output-heavy reruns unless the task requires it.
- Use local ignored working folders such as `working/`, `scripts/`, or `ras_agent/` at repo root for temporary outputs and extracted scripts.
- If a `TASK.md` contains stale `C:\GH\...` paths, remap them to `G:\GH\...` before failing.

## Environment

- Default host context is Windows.
- Use `pathlib.Path` for path handling. Accept forward slashes and backslashes.
- Use a single repo-local `uv` environment:
  - `uv venv .venv`
  - `uv pip install -e .`
  - `uv run python -c "import ras_commander as ras; print(ras.__version__)"`
- HEC-RAS execution requires an installed `Ras.exe`. Pass an explicit executable path when the active environment does not already resolve one.

## Repository Map

- `ras_commander/` - core library code and subpackages. Read [ras_commander/AGENTS.md](ras_commander/AGENTS.md) for library-local rules.
- `examples/` - notebooks and scenario workflows. Read [examples/AGENTS.md](examples/AGENTS.md) before doing notebook work.
- `docs/` - MkDocs documentation source. Read [docs/AGENTS.md](docs/AGENTS.md) for docs-local rules.
- `tests/` - repo tests and smoke checks. Read [tests/AGENTS.md](tests/AGENTS.md) for test-local rules.
- `agent_tasks/` - long-running task coordination and worktree tracking.
- `.claude/` - Claude-native rules, skills, agents, commands, and manifests.
- `.codex/` - Codex-native hook configuration only. Shared Codex instructions still live in `AGENTS.md`; Codex skills use `.agents/`.
- `scripts/agent_hooks/` - shared cross-harness hook dispatcher used by Claude Code and Codex.

## Working Rules

- Use real HEC-RAS projects, typically through `RasExamples.extract_project()`. Do not default to mocks or synthetic datasets for domain validation.
- Prefer `ras.plan_df`, `ras.geom_df`, `ras.boundaries_df`, and related DataFrames as the source of truth for paths and metadata. Do not replace them with ad hoc globbing when the DataFrame already exists.
- Most `Ras*` and `Hdf*` classes are static namespaces. Do not instantiate them unless the API clearly requires an instance.
- Public API work should follow the repo logging pattern:
  - `from ras_commander import get_logger, log_call`
  - `logger = get_logger(__name__)`
  - decorate public methods with `@log_call`
- Keep original project folders immutable when practical. Prefer `dest_folder=` or separate working directories for execution outputs and experiments.
- Generate reviewable outputs:
  - HEC-RAS project artifacts that open in the GUI
  - plots or figures when results need visual checking
  - log output and explicit audit trails for code paths

## Notebooks

- Notebooks are reference material for humans. Extract repeatable logic into scripts or library changes.
- Replace notebook-only shell snippets such as `!pip install` with terminal commands using `uv`.
- Put notebook-derived scripts and outputs in writable working folders, not alongside committed notebook assets.

## Testing And Validation

- Use `pytest` for targeted tests.
- Prefer tests that touch real library behavior and real example projects.
- Do not commit generated model outputs, extracted example datasets, large temporary rasters, or ad hoc benchmark artifacts.

## Coordination And Handoffs

- For multi-session tasks, use `agent_tasks/` and its `.agent/` state files when the task is large enough to need a durable handoff.
- If a task spans repositories, document the request in markdown and keep the Python API layers independent.

## Update Discipline

- If a rule matters to both Claude and Codex, update the relevant `AGENTS.md` file.
- If a change is Claude-only, keep it in `CLAUDE.md`, `.claude/rules/`, `.claude/agents/`, or `.claude/commands/` as appropriate.
- If you change the instruction architecture, also update:
  - [docs/development/multi-harness-agent-contract.md](docs/development/multi-harness-agent-contract.md)
  - [agent_tasks/2026-04-25_multi_harness_agent_framework_migration_plan.md](agent_tasks/2026-04-25_multi_harness_agent_framework_migration_plan.md)
