You are starting a new git worktree for isolated agent work. This command creates a worktree, registers it in the tracking system, and ensures you can identify your workspace even after context resets.

## Your Task

### 1. Gather Information

First, determine the worktree purpose by asking the user OR inferring from context:

- **If user provided a purpose**: Use it directly
- **If no purpose given**: Ask "What is the purpose/feature for this worktree?"

Generate a branch name from the purpose:
- Format: `agent/{purpose-slug}` (e.g., `agent/hdf-refactoring`, `agent/usgs-validation`)
- Use lowercase, hyphens instead of spaces

### 2. Create the Worktree

```bash
# Get current repo root
REPO_ROOT=$(git rev-parse --show-toplevel)
PROJECT_NAME=$(basename "$REPO_ROOT")

# Create worktrees directory if needed (use sibling directory pattern)
WORKTREE_BASE="${REPO_ROOT}/../${PROJECT_NAME}-worktrees"
mkdir -p "$WORKTREE_BASE"

# Create worktree with new branch
BRANCH_NAME="agent/{purpose-slug}"
WORKTREE_PATH="$WORKTREE_BASE/$BRANCH_NAME"
git worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH"
```

### 3. Register in Tracking System

Update `agent_tasks/git_worktree_status.md` by adding an entry:

```markdown
### {Branch Name}
- **Path**: {full worktree path}
- **Created**: {YYYY-MM-DD HH:MM}
- **Purpose**: {description of work being done}
- **Status**: active
- **Agent Session**: {brief identifier if available, or "new session"}
- **Notes**: {any relevant context}
```

### 4. Sideload Shared Folders (Windows)

Create junctions so the worktree can access shared development materials:

```cmd
cd {WORKTREE_PATH}
mklink /J agent_tasks {REPO_ROOT}\agent_tasks
mklink /J feature_dev_notes {REPO_ROOT}\feature_dev_notes 2>nul
mklink /J planning_docs {REPO_ROOT}\planning_docs 2>nul
```

Or on Git Bash/WSL:

```bash
cd {WORKTREE_PATH}
ln -s {REPO_ROOT}/agent_tasks agent_tasks
ln -s {REPO_ROOT}/feature_dev_notes feature_dev_notes 2>/dev/null
ln -s {REPO_ROOT}/planning_docs planning_docs 2>/dev/null
```

### 5. Report Success

Output to user:
```
Git Worktree Created Successfully

Branch: {branch-name}
Path: {worktree-path}
Purpose: {purpose}

Registered in: agent_tasks/git_worktree_status.md

To work in this worktree:
  cd {worktree-path}

To identify this worktree later (even after context reset):
  Check agent_tasks/git_worktree_status.md for your branch purpose
  Or run: git worktree list
```

## Tracking File Location

**File**: `agent_tasks/git_worktree_status.md`

This file tracks ALL agent worktrees with:
- Branch names and paths
- Creation timestamps
- Purpose descriptions (so agents can find their branch after reset)
- Status (active/merged/abandoned)
- Closeout information when work is complete

## Recovery After Context Reset

If an agent loses context and needs to find their worktree:

1. Read `agent_tasks/git_worktree_status.md`
2. Look for entries matching the current task/purpose
3. Check `git worktree list` to verify paths
4. Continue work in the correct worktree

## Related Commands

- `/agent-close-gitworktree` - Close out a worktree when work is complete
- `/agent-taskupdate` - Update task progress
- `using-git-worktrees` skill - Detailed worktree creation patterns

## Important Notes

- Always register worktrees in the tracking file
- Include clear purpose descriptions for recovery
- Sideload `agent_tasks/` so tracking persists across worktrees
- Update status to "merged" or "abandoned" when closing out
