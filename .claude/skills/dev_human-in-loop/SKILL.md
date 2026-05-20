---
name: dev_human-in-loop
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
description: |
  Pause agent work and request explicit human input at hard gates where
  professional judgment, public API compatibility, HEC-RAS execution,
  agent infrastructure, or git/release operations create material risk.

  Triggers: human-in-the-loop, HITL, human approval, human decision,
  approval gate, hard gate, public API change, engineering assumption,
  HEC-RAS execution approval, agent infrastructure change, release gate.
---

# Human-in-the-Loop Decision Gates

## Purpose

Use this skill when agent work reaches a decision point that should not be
resolved by inference alone. Stop before irreversible work, professional
engineering judgment, or shared workflow changes happen without a clear human
decision.

## Core Rule

When a hard gate is reached:

1. Stop before taking the gated action.
2. Summarize the decision needed and known facts.
3. Provide the smallest useful option set.
4. Wait for an explicit answer, or use the configured issue-control process.
5. Record the decision and continue only within the approved scope.

Do not work around the gate by choosing a lower-level command, alternate tool,
or indirect path that has the same effect as the gated action.

## Hard Gates

### Public API And Compatibility

Pause before changing interfaces or behavior that downstream users may depend
on, including:

- Function signatures, return types, column names, or DataFrame schemas.
- Module paths, imports, public class names, or exported constants.
- Defaults, deprecations, removals, compatibility shims, or documented public
  contracts.

Ask for the intended compatibility posture: preserve, deprecate with a shim,
or intentionally break with migration notes.

### HEC-RAS Execution And Model Mutation

Pause before actions that run, preprocess, mutate, or overwrite HEC-RAS models
when the request did not already authorize that exact operation, including:

- Computing plans or preprocessing geometry.
- Writing to original project folders instead of a destination folder.
- Reusing, deleting, or overwriting DSS, HDF, terrain, plan, geometry, or result files.
- Launching GUI automation that may trigger prompts, licensing, or long runs.
- Treating a failed or partially complete HEC-RAS run as acceptable evidence.

The decision packet must name the project, plan, executable path if relevant,
destination folder, expected outputs, and how results will be verified.

### Engineering Assumptions

Pause when the next step depends on a domain assumption that materially affects a
hydraulic or hydrologic conclusion, including:

- Boundary condition selection or interpretation.
- Manning's n, terrain, bridge, culvert, obstruction, or structure assumptions.
- Rainfall distribution, recurrence interval, calibration target, or gauge selection.
- Spatial reference, vertical datum, units, conversions, warnings, instability,
  missing results, or geometry issues.

State the assumption plainly, why it matters, and what evidence is available.

### Agent Infrastructure

Pause before changing shared agent behavior, including:

- `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.agents/`, `.claude/rules/`, skills,
  hooks, or shared agent scripts.
- Skill metadata that changes discoverability, security posture, or harness
  scope.
- Hooks, provider handoff tools, MCP/app/plugin configuration, or automation
  that forwards repository context to another system.

For shared rules, prefer updating the `AGENTS.md` hierarchy. Keep harness
adapter files thin unless the change is truly harness-specific.

### Git And Release Operations

Pause before operations that affect shared history, published artifacts, or
review state, including:

- Pushing to protected branches, force-pushing, rebasing shared branches, or
  deleting remote branches.
- Creating releases, tags, package publishes, or deployment artifacts.
- Closing worktrees or deleting branches when unmerged work may still exist.
- Marking a task complete without required diffs, tests, artifacts, or evidence.

Follow the repository's feature-branch and PR workflow unless a human explicitly
approves an exception.

### Secrets And External Systems

Pause before using or requesting credentials, accepting license prompts, making
network calls that mutate shared services, or changing production-like data.
Never place secrets in tracked files, prompts, logs, issue comments, or review
artifacts.

## Allowed Without A Human Gate

These actions usually do not require this skill when they stay within the
current request and workspace:

- Reading files, inspecting git status, and running non-mutating discovery.
- Creating a feature branch for requested work.
- Adding focused tests or docs for already approved behavior.
- Running local tests that do not execute HEC-RAS or mutate external systems.
- Writing temporary outputs to approved ignored or artifact directories.

If an allowed action reveals a hard gate, stop at that point.

## Decision Packet Template

Use this structure when asking for input:

```markdown
### Needs Human Decision

Decision needed: <one sentence>

Context:
- <fact 1>
- <fact 2>

Options:
- Recommended: <option and consequence>
- Alternative: <option and consequence>

Question: <single direct question>
```

For unattended issue runners, post the packet to the control plane, move the
issue to the correct waiting state, and stop work until a human/operator answer
is available.

## Anti-Patterns

Do not:

- Bury a gated decision inside a long status update.
- Ask for approval after the risky action is already complete.
- Convert a professional engineering assumption into a code default without
  review.
- Treat "tests passed" as approval for a public contract or engineering
  assumption change.
- Delete a worktree, branch, or artifact before verifying that the requested
  salvage or review evidence exists elsewhere.
