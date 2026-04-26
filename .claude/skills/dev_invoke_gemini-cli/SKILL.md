---
name: dev_invoke_gemini-cli
description: |
  Legacy Claude-only provider orchestration for Google Gemini CLI using markdown file handoff.
  Write review request to REVIEW.md, Gemini analyzes, outputs findings to FINDINGS.md.
  Use only when the user explicitly requests Gemini. Do not trigger for generic QAQC,
  quality assurance, security review, architecture review, or second-opinion requests.

  Triggers: gemini, gemini cli, delegate to gemini, gemini subagent,
  gemini-3-pro-preview, gemini-3-flash-preview

  Prerequisites: Gemini CLI authenticated (gemini login or GEMINI_API_KEY)
  Models: gemini-3-pro-preview (default), gemini-3-flash-preview (large context)
shared_corpus: false
harness_scope: claude_only
---

# Invoking Gemini CLI

> Legacy Claude-only orchestration skill. This is not part of the standard production harness policy. It is excluded from the shared multi-harness corpus and should be used only when the user explicitly requests Gemini.

When the user explicitly requests Gemini, delegate the requested review or analysis task to Gemini CLI using markdown files for input and output. Write review criteria to REVIEW.md, invoke Gemini, then read FINDINGS.md for results.

## Pattern: Markdown File Handoff

```
Claude Code                         Gemini CLI
    |                                   |
    +-- Write REVIEW.md ----------------+
    |   (code + review criteria)        |
    |                                   |
    +-- Execute: gemini -y "Read        |
    |   REVIEW.md, analyze, write       |
    |   findings to FINDINGS.md"        |
    |                                   |
    |                                   +-- Reads REVIEW.md
    |                                   +-- Analyzes content
    |                                   +-- Writes FINDINGS.md
    |                                   |
    +-- Read FINDINGS.md <--------------+
    |   (analysis + recommendations)    |
    v                                   v
```

**Benefits**:
- Eliminates shell escaping issues
- Keeps context structured in reviewable files
- Enforces explicit output structure
- Supports session resume

## Model Selection

| Model | Use Case | Status |
|-------|----------|--------|
| `gemini-3-pro-preview` | **Default.** Strong reasoning | CLI default |
| `gemini-3-flash-preview` | Large context, fast analysis | For big codebases |

**Recommendation**: Use default `gemini-3-pro-preview` for most tasks. Switch to `gemini-3-flash-preview` for very large context (>100K tokens) via `-m` flag.

**Note**: If you encounter 429 capacity errors with `gemini-3-pro-preview`, retry or wait briefly.

## Invocation

### Standard Pattern Within This Legacy Skill

```bash
cd /path/to/project && gemini -y "Read REVIEW.md in the current directory. Follow the review criteria. Write all findings to FINDINGS.md."
```

### With Explicit Model

```bash
cd /path/to/project && gemini -y -m gemini-3-flash-preview "Read REVIEW.md, analyze per criteria, write findings to FINDINGS.md"
```

### Resume Session

```bash
gemini -r <session_id> "Read REVIEW.md for updated criteria, append to FINDINGS.md"
```

## Core Flags Reference

| Flag | Purpose |
|------|---------|
| `-y` | YOLO mode - auto-approve all actions |
| `-m <model>` | Model: `gemini-3-pro-preview`, `gemini-3-flash-preview` |
| `-r <id>` | Resume session by ID |
| `--output-format json` | JSON output for parsing |
| `--list-sessions` | List available sessions |

## Review Request Template (REVIEW.md)

```markdown
# Review Request: [Brief Title]

## Objective
[What kind of review/analysis is needed]

## Review Criteria
Rate each finding: CRITICAL | HIGH | MEDIUM | LOW

### Security
- SQL injection vulnerabilities
- XSS risks
- Authentication/authorization issues
- Hardcoded secrets

### Reliability
- Error handling gaps
- Edge cases not covered
- Race conditions
- Resource leaks

### Performance
- N+1 query patterns
- Unnecessary allocations
- Missing caching opportunities

### Maintainability
- Code clarity
- Naming conventions
- Documentation gaps

## Code to Review

### File: src/api/users.ts
```typescript
// Paste code here or reference file
```

### File: src/services/auth.ts
```typescript
// Paste code here
```

## Context
[Any relevant background, constraints, or requirements]

## Output Format
Write to FINDINGS.md with:
- Summary of review
- Findings table with severity, location, description
- Specific recommendations
- Overall assessment
- Session ID for follow-up
```

## Findings Template (FINDINGS.md)

Instruct Gemini to produce:

```markdown
# Review Findings: [Title]

## Summary
[Brief overview of review results]

## Findings

| Severity | Location | Issue | Recommendation |
|----------|----------|-------|----------------|
| CRITICAL | users.ts:45 | SQL injection via unsanitized input | Use parameterized queries |
| HIGH | auth.ts:23 | Missing rate limiting on login | Add rate limiter middleware |
| MEDIUM | users.ts:78 | No input validation | Add schema validation |
| LOW | auth.ts:12 | Magic number | Extract to named constant |

## Detailed Analysis

### CRITICAL: SQL Injection (users.ts:45)
[Detailed explanation with code example]

### HIGH: Missing Rate Limiting (auth.ts:23)
[Detailed explanation with recommendation]

## Recommendations
1. [Priority action items]
2. [Secondary improvements]

## Overall Assessment
[Summary judgment: PASS | NEEDS WORK | FAIL]

## Session
Session ID: `<id>` (for follow-up questions)
```

## Workflow Example (ras-commander)

### 1. Write REVIEW.md

```markdown
# Review Request: Remote Execution Security

## Objective
Security review of the PsExec-based remote execution module.

## Review Criteria
Rate findings: CRITICAL | HIGH | MEDIUM | LOW

Focus on:
- Command injection vulnerabilities
- Credential exposure
- Path traversal risks
- Session hijacking

## Code to Review

### File: ras_commander/remote/PsexecWorker.py
```python
[paste relevant code]
```

### File: ras_commander/remote/Execution.py
```python
[paste relevant code]
```

## Context
- This module executes HEC-RAS remotely via PsExec
- Runs with elevated privileges on remote Windows machines
- Handles user credentials for authentication

## Output Format
Write to FINDINGS.md with severity-rated findings and specific mitigations.
```

### 2. Execute Gemini

```bash
cd "C:/GH/ras-commander" && gemini -y "Read REVIEW.md, perform security review per criteria, write findings to FINDINGS.md"
```

### 3. Read FINDINGS.md

Review the findings, address issues, and continue development.

## Environment Variables

```bash
GEMINI_API_KEY=xxx         # Required (or use OAuth login)
GOOGLE_API_KEY=xxx         # Alternative (takes precedence)
```

## Rate Limits

| Limit | Value |
|-------|-------|
| Requests/minute | 60 |
| Requests/day | 1,000 |

## Session Management

- Session ID appears in Gemini output
- Use `gemini --list-sessions` to see available sessions
- Resume with `gemini -r <id> "follow-up instruction"`

## Tips

1. **Paste actual code** - Don't describe, include the real code in REVIEW.md
2. **Define severity levels** - CRITICAL/HIGH/MEDIUM/LOW helps prioritization
3. **Specify output structure** - Tell Gemini exactly what FINDINGS.md should contain
4. **Provide context** - Domain, compliance requirements, constraints
5. **Ask focused questions** - One review type per request gets better results

## Legacy Capability Notes

Codex is the production-supported second harness for this repository. Use this
legacy Gemini path only when the user explicitly asks for Gemini.

**Use Codex by default for**:
- QAQC and code review
- Security review
- Complex implementation
- Extended thinking tasks
- Multi-file refactoring

**Use this Gemini path only for**:
- explicit Gemini requests
- reproducing historical Gemini-based review workflows

**Use specialized ras-commander agents for**:
- HDF analysis -> `hdf-analyst`
- Geometry parsing -> `geometry-parser`
- USGS integration -> `usgs-integrator`

## Cross-References

**Agents** (delegate when needed):
- `code-oracle-gemini` -- Delegate for large context Gemini analysis

**Skills** (related workflows):
- `dev_invoke_codex-cli` -- Alternative: Codex CLI for deep reasoning
- `dev_invoke_kimi-cli` -- Alternative: Kimi CLI for test generation
- `qa_review_triple-model` -- Uses this skill as one of three reviewers
