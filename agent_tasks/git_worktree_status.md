# Git Worktree Status Registry

This file tracks all git worktrees created by agents for isolated development work. It serves as a persistent registry that allows agents to identify their workspace even after context resets.

## Purpose

- **Track active worktrees** across all agent sessions
- **Enable recovery** when agents lose context and need to find their branch
- **Document intent** so the purpose of each branch is clear
- **Coordinate** when multiple agents work on different features

## How to Use

### Finding Your Worktree After Reset

1. Read this file to find entries matching your current task
2. Verify with `git worktree list` that the path exists
3. Navigate to the worktree and continue work

### Creating New Entries

Use the `/agents-start-gitworktree` command, which automatically:
1. Creates the worktree and branch
2. Adds an entry to this file
3. Sets up sideloaded folders

### Closing Out Worktrees

When work is complete:
1. Update the entry's **Status** to `merged` or `abandoned`
2. Add **Closed** timestamp and **Closeout Notes**
3. Run `git worktree remove {path}` if no longer needed

---

## Active Worktrees

<!-- Add new worktree entries below this line -->

*No active worktrees registered yet.*

<!-- Template for new entries:

### agent/{feature-name}
- **Path**: C:/GH/ras-commander-worktrees/agent/{feature-name}
- **Created**: YYYY-MM-DD HH:MM
- **Purpose**: Brief description of the work being done in this worktree
- **Status**: active
- **Agent Session**: Description of agent/session creating this
- **Notes**: Any relevant context or dependencies

-->

---

## Closed Worktrees

<!-- Move completed/abandoned worktrees here for historical reference -->

*No closed worktrees yet.*

<!-- Template for closed entries:

### agent/{feature-name} [CLOSED]
- **Path**: C:/GH/ras-commander-worktrees/agent/{feature-name}
- **Created**: YYYY-MM-DD HH:MM
- **Closed**: YYYY-MM-DD HH:MM
- **Purpose**: Brief description of the work
- **Status**: merged | abandoned
- **Closeout Notes**: Summary of outcome, PR link if merged, reason if abandoned

-->

---

## Quick Reference

### List All Worktrees
```bash
git worktree list
```

### Create Worktree (via command)
```
/agents-start-gitworktree
```

### Remove Worktree
```bash
# From main repo
git worktree remove ../ras-commander-worktrees/agent/{feature-name}

# Force remove if needed
git worktree remove --force ../ras-commander-worktrees/agent/{feature-name}

# Clean up stale references
git worktree prune
```

### Delete Branch After Merge
```bash
# Local
git branch -d agent/{feature-name}

# Remote (if pushed)
git push origin --delete agent/{feature-name}
```

---

## Recovery Scenarios

### Scenario 1: Agent forgets which branch to use

1. Read this file
2. Match purpose description to current task
3. Verify path exists with `git worktree list`
4. `cd` to worktree path

### Scenario 2: Worktree exists but not in registry

1. Run `git worktree list` to find all worktrees
2. Add missing entry to this file
3. Include purpose if known, or mark as "unknown - needs investigation"

### Scenario 3: Registry entry but worktree deleted

1. Update status to `abandoned`
2. Add closeout note: "Worktree removed without proper closeout"
3. Move to Closed Worktrees section
