# Git Worktree + Sideload Workflow

This document describes the recommended workflow for developing ras-commander features using git worktrees and sideloaded development folders.

## Overview

**Problem**: Feature development requires:
- Isolated git branches for clean commits
- Access to untracked research/planning materials
- Coordination memory that persists across sessions

**Solution**: Use git worktrees for branch isolation + sideload untracked folders into the worktree.

## Directory Structure

### Main Repository
```
C:\GH\ras-commander\               # Main worktree (main branch)
├── ras_commander/                 # Library code (tracked)
├── examples/                      # Example notebooks (tracked)
├── agent_tasks/                   # Coordination system (partial tracking)
│   ├── .agent/                    # Memory system (TRACKED)
│   ├── tasks/                     # Active tasks (NOT tracked)
│   └── .old/                      # Archive (NOT tracked)
├── feature_dev_notes/             # Research materials (NOT tracked, gitignored)
└── planning_docs/                 # Planning docs (NOT tracked, gitignored)
```

### Feature Worktree
```
C:\GH\ras-commander-worktrees\
└── feature-check-ras\             # Git worktree (feature/check-ras branch)
    ├── ras_commander/             # Library code (tracked in this branch)
    ├── examples/                  # Examples (tracked)
    ├── agent_tasks/               # Coordination (SIDELOADED from main)
    ├── feature_dev_notes/         # Research (SIDELOADED from main)
    └── planning_docs/             # Planning (SIDELOADED from main)
```

## Workflow Steps

### 1. Create Feature Worktree

```bash
# From main repository
cd C:\GH\ras-commander

# Create and checkout feature branch in a new worktree
git worktree add -b feature/check-ras ../ras-commander-worktrees/feature-check-ras

# Verify worktree created
git worktree list
```

**Result**: New worktree at `C:\GH\ras-commander-worktrees\feature-check-ras\` with:
- Fresh clone of ras-commander on new branch
- Independent git index (can commit without affecting main)
- Same git history (shares .git objects)

### 2. Sideload Development Folders

Use symbolic links (Windows) or directory junctions to access untracked folders:

#### Option A: Directory Junctions (Recommended for Windows)

```cmd
cd C:\GH\ras-commander-worktrees\feature-check-ras

# Sideload agent_tasks coordination
mklink /J agent_tasks C:\GH\ras-commander\agent_tasks

# Sideload feature development notes
mklink /J feature_dev_notes C:\GH\ras-commander\feature_dev_notes

# Sideload planning docs
mklink /J planning_docs C:\GH\ras-commander\planning_docs
```

#### Option B: Symbolic Links (Requires Admin on Windows)

```bash
cd C:/GH/ras-commander-worktrees/feature-check-ras

# Sideload folders
ln -s C:/GH/ras-commander/agent_tasks agent_tasks
ln -s C:/GH/ras-commander/feature_dev_notes feature_dev_notes
ln -s C:/GH/ras-commander/planning_docs planning_docs
```

**Result**: Worktree can access all development materials from main repo.

### 3. Update Agent Coordination State

```bash
cd C:\GH\ras-commander-worktrees\feature-check-ras

# Read current state
cat agent_tasks/.agent/STATE.md

# Update for feature work
# Edit agent_tasks/.agent/STATE.md to indicate:
# - Current Focus: Implementing cHECk-RAS feature
# - Files Modified: [list of files in this worktree]
# - Working Branch: feature/check-ras
```

**Important**: Since `agent_tasks/` is sideloaded, changes to memory files affect the main repo. This is **intentional** - memory persists across all worktrees.

### 4. Develop Feature

Work normally in the worktree:

```bash
cd C:\GH\ras-commander-worktrees\feature-check-ras

# Make changes to tracked files
vim ras_commander/RasCheck.py

# Reference feature_dev_notes for research
cat feature_dev_notes/cHECk-RAS/development_plan/00_OVERVIEW.md

# Commit to feature branch
git add ras_commander/RasCheck.py
git commit -m "feat: add RasCheck class skeleton"

# Update coordination memory
echo "Session summary..." >> agent_tasks/.agent/PROGRESS.md
```

### 5. Sync and Merge

When feature is complete:

```bash
# Push feature branch
git push -u origin feature/check-ras

# Switch to main repo
cd C:\GH\ras-commander

# Merge feature (via PR or directly)
git checkout main
git merge feature/check-ras

# Remove worktree if done
git worktree remove ../ras-commander-worktrees/feature-check-ras
```

## Key Benefits

### 1. Branch Isolation
- Each feature gets its own worktree
- No need to stash/commit to switch branches
- Multiple features can be worked on simultaneously

### 2. Shared Development Materials
- `feature_dev_notes/` accessible in all worktrees
- `planning_docs/` research available everywhere
- No duplication of large untracked folders

### 3. Unified Memory System
- `agent_tasks/.agent/` state is shared
- All worktrees read/write same STATE.md, BACKLOG.md, PROGRESS.md
- Enables cross-feature coordination

### 4. Clean Git History
- Only track library code and docs
- Research and planning stay local
- Feature branches contain only relevant changes

## Best Practices

### Worktree Naming
```
feature-{feature-name}       # Feature development
bugfix-{issue-number}        # Bug fixes
experiment-{name}            # Experimental work
```

### Memory Management

**Per-Worktree State**:
Create task folders for each feature:
```
agent_tasks/tasks/check-ras-implementation/
    TASK.md           # Feature-specific task
    notes.md          # Development notes
```

**Shared State**:
Update global memory files:
```
agent_tasks/.agent/STATE.md      # Current worktree and focus
agent_tasks/.agent/BACKLOG.md    # All features across worktrees
agent_tasks/.agent/PROGRESS.md   # Session log (all worktrees)
```

### Commit Strategy

**In Worktree** (tracked):
- Commit library code changes
- Commit new examples/notebooks
- Commit test updates

**Not Committed** (sideloaded):
- Research notes in `feature_dev_notes/`
- Planning docs in `planning_docs/`
- Task work in `agent_tasks/tasks/`

## Troubleshooting

### Junction/Symlink Not Working

**Symptom**: Files not accessible in worktree

**Fix**: Verify junction created correctly:
```cmd
dir /AL C:\GH\ras-commander-worktrees\feature-check-ras
```

Should show `<JUNCTION>` or `<SYMLINKD>` for sideloaded folders.

### Memory State Conflicts

**Symptom**: Two worktrees trying to work on same task

**Fix**: Use STATE.md to coordinate:
```markdown
# agent_tasks/.agent/STATE.md

## Current Focus
**Worktree**: feature-check-ras
**Task**: check-ras-001
**Status**: in_progress

## Other Active Worktrees
- feature-dss-writing: Paused (blocked on user input)
- experiment-permutations: Background research only
```

### Worktree Cleanup

**Problem**: Worktree removed but git still tracks it

**Fix**:
```bash
# Prune stale worktree references
git worktree prune

# Force remove if needed
git worktree remove --force ../path/to/worktree
```

## Advanced Patterns

### Multi-Feature Development

Work on multiple features simultaneously:

```bash
# Terminal 1: Check-RAS feature
cd C:\GH\ras-commander-worktrees\feature-check-ras
code .

# Terminal 2: DSS writing feature
cd C:\GH\ras-commander-worktrees\feature-dss-writing
code .

# Terminal 3: Main repo (reviews, merges)
cd C:\GH\ras-commander
```

All terminals share `agent_tasks/`, `feature_dev_notes/`, `planning_docs/`.

### Temporary Experimental Worktrees

For quick experiments that won't be merged:

```bash
# Create experiment worktree
git worktree add -b experiment/test-idea ../ras-commander-worktrees/experiment-test-idea

# Work, test, discard
cd ../ras-commander-worktrees/experiment-test-idea
# ... experiment ...

# Remove when done (no merge needed)
cd C:\GH\ras-commander
git worktree remove ../ras-commander-worktrees/experiment-test-idea
git branch -D experiment/test-idea
```

## Example: Complete Feature Development Flow

```bash
# ============================================================================
# 1. CREATE WORKTREE
# ============================================================================
cd C:\GH\ras-commander
git worktree add -b feature/check-ras ../ras-commander-worktrees/feature-check-ras
cd ../ras-commander-worktrees/feature-check-ras

# ============================================================================
# 2. SIDELOAD DEVELOPMENT FOLDERS
# ============================================================================
mklink /J agent_tasks C:\GH\ras-commander\agent_tasks
mklink /J feature_dev_notes C:\GH\ras-commander\feature_dev_notes
mklink /J planning_docs C:\GH\ras-commander\planning_docs

# ============================================================================
# 3. ORIENT WITH MEMORY SYSTEM
# ============================================================================
cat agent_tasks/.agent/STATE.md
cat agent_tasks/.agent/BACKLOG.md
cat feature_dev_notes/cHECk-RAS/development_plan/00_OVERVIEW.md

# ============================================================================
# 4. UPDATE STATE FOR THIS WORK
# ============================================================================
# Edit agent_tasks/.agent/STATE.md:
# Current Focus: Implementing cHECk-RAS (feature/check-ras worktree)
# Files Modified: ras_commander/RasCheck.py

# ============================================================================
# 5. DEVELOP FEATURE
# ============================================================================
# Create RasCheck.py
vim ras_commander/RasCheck.py

# Create example notebook
vim examples/28_quality_assurance_rascheck.ipynb

# Commit incrementally
git add ras_commander/RasCheck.py
git commit -m "feat(RasCheck): add RasCheck class skeleton"

git add examples/28_quality_assurance_rascheck.ipynb
git commit -m "docs: add RasCheck example notebook"

# ============================================================================
# 6. UPDATE MEMORY SYSTEM
# ============================================================================
# Append to agent_tasks/.agent/PROGRESS.md
echo "Session summary: Implemented RasCheck class skeleton..." >> agent_tasks/.agent/PROGRESS.md

# Update task status
# Edit agent_tasks/.agent/BACKLOG.md: mark check-ras-001 as completed

# ============================================================================
# 7. PUSH AND CREATE PR
# ============================================================================
git push -u origin feature/check-ras

# Create PR on GitHub (or merge directly if small)
gh pr create --title "Add RasCheck quality assurance feature" --body "Implements cHECk-RAS..."

# ============================================================================
# 8. CLEANUP AFTER MERGE
# ============================================================================
cd C:\GH\ras-commander
git checkout main
git pull origin main
git worktree remove ../ras-commander-worktrees/feature-check-ras
git branch -d feature/check-ras  # Local cleanup
```

## Summary

**Git Worktrees** provide branch isolation without switching branches.

**Sideloaded Folders** provide access to untracked development materials.

**Agent Memory System** coordinates work across all worktrees.

This workflow enables:
- ✅ Multiple features in parallel
- ✅ Clean git history
- ✅ Shared research and planning materials
- ✅ Persistent memory across sessions
- ✅ No duplication of large untracked folders
