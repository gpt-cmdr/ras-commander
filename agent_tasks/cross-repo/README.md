# Cross-Repository Coordination (Immediate Implementation)

This folder contains **immediate implementation requests** that involve coordination between sibling repositories (ras-commander ↔ hms-commander).

## Purpose

When an AI agent needs a feature implemented in a sibling repository as part of **current work**, it documents the request here for **human review and handoff**.

## Key Principles

1. **Agent-Layer Only** - Cross-repo coordination exists only at the AI/documentation level
2. **Human-in-the-Loop Required** - Every handoff requires explicit human engagement
3. **Markdown-Based** - All coordination happens through markdown files
4. **No Direct AI-to-AI Handoff** - Agents prepare documentation; humans trigger next steps
5. **API Independence** - Python APIs remain completely independent

## Workflow

```
1. Agent identifies immediate implementation need in sibling repo
2. Agent writes request in this folder
3. HUMAN reviews and decides to engage sibling repo
4. Human opens sibling repo, provides request context
5. Sibling agent implements feature
6. Sibling agent writes response with implementation details
7. HUMAN reviews implementation
8. Human returns to original repo with response
9. Original agent integrates/tests with human oversight
```

## File Naming Convention

```
{YYYY-MM-DD}_{source-repo}_to_{target-repo}_{topic}.md
```

**Examples:**
- `2024-12-13_ras_to_hms_add-dss-export-function.md`
- `2024-12-13_hms_to_ras_parallel-worker-pattern.md`

## Request Template

See `_TEMPLATE_implementation_request.md` in this folder.

## Sibling Repository Locations

| Repository | Local Path | Purpose |
|------------|------------|---------|
| ras-commander | `C:\GH\ras-commander` | HEC-RAS automation |
| hms-commander | `C:\GH\hms-commander` | HEC-HMS automation |

## What Goes Here vs feature_dev_notes/cross-repo/

| Location | Use Case | Timeline |
|----------|----------|----------|
| `agent_tasks/cross-repo/` | Implementation requests, immediate needs | Current sprint |
| `feature_dev_notes/cross-repo/` | Research, exploration, future ideas | Non-urgent |

## Status Tracking

Requests in this folder should be tracked in `agent_tasks/.agent/BACKLOG.md` with the `[cross-repo]` tag.

## See Also

- `feature_dev_notes/cross-repo/` - Research and future feature exploration
- `agent_tasks/.agent/` - Memory system (STATE, PROGRESS, BACKLOG)
- `docs/development/agent-infrastructure.md` - Full agent documentation
