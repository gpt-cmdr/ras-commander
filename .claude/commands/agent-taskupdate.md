Look at your task list and memory, assess your current progress, and make a detailed plan to continue making progress on your task list.

## Task Update Protocol

### 1. Read Current State (Do This First)

Read the following files to understand the current situation:

```
agent_tasks/.agent/STATE.md      -- Current project state, what's in progress
agent_tasks/.agent/PROGRESS.md   -- Recent session history (last 2-3 entries)
agent_tasks/.agent/BACKLOG.md    -- All tasks and their status
```

If these files don't exist, look for task planning documents in `agent_tasks/` root or `agent_tasks/tasks/`.

### 2. Assess Current Progress

For the currently in-progress task:
- What was accomplished in the last session?
- Are there blockers?
- What is the next concrete action?

For the backlog:
- Are any "Blocked" tasks now unblocked?
- Have new tasks emerged from the current work?

### 3. Update STATE.md

Update `agent_tasks/.agent/STATE.md` with:
- Current timestamp
- What is currently in progress
- Health status (Green / Yellow / Red)
- Any blockers discovered
- Next priorities

STATE.md format:
```markdown
# Project State

**Last Updated**: {YYYY-MM-DD HH:MM}
**Session**: {N}
**Health**: Green | Yellow | Red

## Current Focus
{What task is actively being worked on}

## Next Priorities
1. {Priority 1}
2. {Priority 2}

## Blockers
- {Any blockers, or "None"}

## Recent Accomplishments
- {What was done recently}
```

### 4. Append to PROGRESS.md

Append a new session entry to `agent_tasks/.agent/PROGRESS.md`:

```markdown
## Session {N} — {YYYY-MM-DD}

### Accomplished
- {What was done}

### Decisions Made
- {Any key decisions and rationale}

### Files Modified
- {List of files}

### Handoff Notes
{Context the next session needs to know immediately}

### Next Session Should Start With
1. {First action}
2. {Second action}
```

PROGRESS.md is append-only — never edit previous entries.

### 5. Update BACKLOG.md

Update task status:
- Mark completed tasks with `[x]`
- Add any new tasks discovered
- Move newly-unblocked tasks from Blocked to Ready
- Add notes to tasks based on current findings

BACKLOG.md task format:
```markdown
## Ready
- [ ] task-id: Task description (estimated complexity: S/M/L)

## In Progress
- [ ] task-id: Task description — Started {date}

## Blocked
- [ ] task-id: Task description — Blocked: {reason}

## Completed
- [x] task-id: Task description — Completed {date}
```

### 6. Plan Next Steps

Based on the updated state, propose a concrete plan for continuing:
- Which task to work on next (from Backlog Ready)
- What specific actions to take
- Which agents or skills to engage

## When to Use This Command

- At the start of a new session (update state, plan the session)
- When switching from one task to another
- When a task completes (update BACKLOG before starting next)
- When discovering a blocker (update STATE and BACKLOG)
- After a subagent completes (incorporate findings into state)
- Periodically during long tasks (keep state current)

## Cross-References

**Commands** (related):
- `/agent-taskclose` -- End-of-task variant (more aggressive cleanup and knowledge extraction)
- `/agent-engagesubagents` -- When task requires delegating to multiple agents
- `/agent-cleanfiles` -- Periodic cleanup of completed task artifacts
