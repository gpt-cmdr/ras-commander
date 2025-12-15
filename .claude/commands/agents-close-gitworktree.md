You are closing out a git worktree after completing (or abandoning) work. This command updates the tracking registry and optionally removes the worktree.

## Your Task

### 1. Identify the Worktree to Close

Options:
- **Current worktree**: Detect from `git branch --show-current`
- **User-specified**: Ask if multiple options exist
- **From registry**: Read `agent_tasks/git_worktree_status.md` and let user choose

```bash
# Get current branch
CURRENT_BRANCH=$(git branch --show-current)

# List all worktrees
git worktree list
```

### 2. Determine Closeout Status

Ask the user or infer from context:

- **merged**: Work was completed and merged to main/target branch
- **abandoned**: Work was stopped before completion (document why)

If merged, ask for:
- PR number or link (if applicable)
- Brief summary of what was accomplished

If abandoned, ask for:
- Reason for abandonment
- Whether work should be picked up later

### 3. Update Tracking Registry

Edit `agent_tasks/git_worktree_status.md`:

1. Find the entry for this branch in "Active Worktrees"
2. Add closeout information:
   ```markdown
   - **Closed**: {YYYY-MM-DD HH:MM}
   - **Status**: merged | abandoned
   - **Closeout Notes**: {summary, PR link, or reason for abandonment}
   ```
3. Move the entire entry to "Closed Worktrees" section

### 4. Handle Git Cleanup

Ask user preference:

**Option A: Full Cleanup** (recommended for merged work)
```bash
# Return to main repo
cd {MAIN_REPO_PATH}

# Remove worktree
git worktree remove {WORKTREE_PATH}

# Delete local branch (if merged)
git branch -d {BRANCH_NAME}

# Delete remote branch (if pushed)
git push origin --delete {BRANCH_NAME}

# Prune stale references
git worktree prune
```

**Option B: Keep Worktree** (for reference or future work)
- Only update registry
- Leave worktree and branch intact

**Option C: Partial Cleanup**
- Remove worktree but keep branch
- Useful if work might resume from different location

### 5. Report Completion

```
Worktree Closed Successfully

Branch: {branch-name}
Status: {merged|abandoned}
{Closeout Notes}

Registry updated: agent_tasks/git_worktree_status.md

{If cleanup performed:}
- Worktree removed: {yes/no}
- Local branch deleted: {yes/no}
- Remote branch deleted: {yes/no}
```

## Example Registry Update

### Before (in Active Worktrees):
```markdown
### agent/hdf-refactoring
- **Path**: C:/GH/ras-commander-worktrees/agent/hdf-refactoring
- **Created**: 2024-12-14 10:30
- **Purpose**: Refactor HDF extraction for better performance
- **Status**: active
- **Agent Session**: Session working on HDF improvements
- **Notes**: Targeting 2x speedup on large files
```

### After (moved to Closed Worktrees):
```markdown
### agent/hdf-refactoring [CLOSED]
- **Path**: C:/GH/ras-commander-worktrees/agent/hdf-refactoring
- **Created**: 2024-12-14 10:30
- **Closed**: 2024-12-15 14:45
- **Purpose**: Refactor HDF extraction for better performance
- **Status**: merged
- **Agent Session**: Session working on HDF improvements
- **Closeout Notes**: Achieved 2.3x speedup. Merged via PR #142. Worktree and branch removed.
```

## Safety Checks

Before removing worktree:
1. Verify all changes are committed: `git status`
2. Verify branch is merged (if claiming merged): `git branch --merged main`
3. Warn if uncommitted changes exist
4. Confirm with user before deletion

## Related Commands

- `/agents-start-gitworktree` - Create new worktree
- `/agent-taskupdate` - Update task progress
- `finishing-a-development-branch` skill - PR and merge workflow
