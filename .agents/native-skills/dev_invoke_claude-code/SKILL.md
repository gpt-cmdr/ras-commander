---
name: dev_invoke_claude-code
description: |
  Codex-native adapter for invoking Anthropic Claude Code CLI as an independent
  read-only QAQC reviewer using markdown file handoff.
  Use when the user explicitly asks Codex to ask Claude, Claude Code, Opus, or
  Anthropic for a QAQC/code review, second-model review, or independent review.
  Do not trigger for generic QAQC unless the user asks for Claude specifically.

  Triggers: claude review, claude code review, ask claude, invoke claude,
  claude qaqc, opus review, anthropic review, second model with claude

  Prerequisites: Claude Code CLI authenticated and available as `claude`.
  Default model: opus with xhigh effort for deep reviews; use sonnet/high for
  faster or lower-cost review passes.
shared_corpus: false
harness_scope: codex_only
source_owner: gpt-cmdr
security_review: internal
---

# Invoking Claude Code For QAQC

> Codex-native provider handoff skill. This is not a shared domain workflow and
> should not be mirrored into `.claude/skills/`. It lets Codex request an
> independent Claude Code review while keeping shared repo policy in `AGENTS.md`.

Use this skill when the user explicitly asks Codex to have Claude Code review
code, documentation, notebooks, or agent-framework changes.

## Safety Rules

- Use Claude as a read-only reviewer by default.
- Do not let Claude edit files, commit, push, install tools, or mutate the worktree.
- Do not overwrite root-level `TASK.md` or `OUTPUT.md`; those may belong to another handoff.
- Put each review in an ignored workspace such as
  `working/agent-reviews/claude-code/{timestamp}-{slug}/`.
- Give Claude the same shared repo contract Codex used: nearest `AGENTS.md`,
  relevant local `AGENTS.md` files, and task-specific files.
- Do not use `--dangerously-skip-permissions` unless the user explicitly requests
  it and the workspace is externally sandboxed.

## Handoff Pattern

Create a review workspace:

```powershell
$reviewDir = "working/agent-reviews/claude-code/20260426-claude-qaqc"
New-Item -ItemType Directory -Force $reviewDir | Out-Null
```

Write `TASK.md` in that folder. Include:

- the review target files or directories
- the exact concern or review objective
- the shared instruction files Claude should read first
- a strict read-only constraint
- the expected finding format

Minimum `TASK.md` shape:

```markdown
# Claude Code QAQC Review

You are performing an independent read-only QAQC review for ras-commander.

## Read First

1. AGENTS.md
2. The nearest local AGENTS.md files for the target paths
3. docs/development/multi-harness-agent-contract.md when reviewing agent infrastructure

## Target

- path/to/file_or_directory

## Review Focus

- correctness bugs
- behavioral regressions
- missing tests or validation gaps
- security or supply-chain risks, if relevant

## Constraints

- Do not edit files.
- Do not run destructive commands.
- Do not commit or push.
- Write findings first, ordered by severity.
- Include file and line references when possible.
```

Invoke Claude Code non-interactively and capture its report:

```powershell
claude --print `
  --model opus `
  --effort xhigh `
  --permission-mode auto `
  --disallowedTools "Edit,Write,MultiEdit,NotebookEdit" `
  --output-format text `
  --append-system-prompt "Read-only QAQC review. Do not edit files. Return only the review report." `
  "Read $reviewDir/TASK.md, perform the review, and write the final report to stdout." `
  > "$reviewDir/OUTPUT.md"
```

Use `sonnet` with `--effort high` when the user wants a faster review:

```powershell
claude --print `
  --model sonnet `
  --effort high `
  --permission-mode auto `
  --disallowedTools "Edit,Write,MultiEdit,NotebookEdit" `
  --output-format text `
  --append-system-prompt "Read-only QAQC review. Do not edit files. Return only the review report." `
  "Read $reviewDir/TASK.md, perform the review, and write the final report to stdout." `
  > "$reviewDir/OUTPUT.md"
```

## Output Handling

After Claude returns:

1. Read `OUTPUT.md`.
2. Validate whether each finding is actionable and grounded in the repo.
3. Do not blindly apply Claude's recommendations.
4. Summarize Claude's findings to the user and distinguish:
   - confirmed issues
   - plausible issues needing local verification
   - items you reject after inspection

## Optional Session Capture

If session metadata is needed, run with JSON output and save the raw result:

```powershell
claude --print `
  --model opus `
  --effort xhigh `
  --permission-mode auto `
  --disallowedTools "Edit,Write,MultiEdit,NotebookEdit" `
  --output-format json `
  "Read $reviewDir/TASK.md and perform the read-only QAQC review." `
  > "$reviewDir/RUN.json"
```

If using JSON output, extract the review text into `OUTPUT.md` before presenting
the result.

## Explicit Opt-In: Claude Ultrareview

Claude Code also exposes `claude ultrareview`. Treat that as a separate,
explicit opt-in path because it is cloud-hosted and branch/PR oriented.

Use it only when the user asks for Claude Ultrareview or a cloud-hosted Claude
review of the current branch/PR. Do not substitute it for the default local
markdown handoff above.

## Failure Handling

- If `claude` is not found, report that Claude Code CLI is not installed or not
  on `PATH`.
- If authentication fails, ask the user to authenticate Claude Code.
- If Claude requests edit permissions, stop and rerun with a stricter read-only
  prompt rather than granting broad permissions.
- If Claude's review is empty or generic, tighten `TASK.md` with explicit files,
  line ranges, and review questions.
