# Agent Tasks - Coordination System

This directory contains the agent coordination and memory system for long-running, multi-session development tasks on ras-commander.

## First-Time Setup

If this is your first time using the agent coordination system, create your local state files from templates:

```bash
cd agent_tasks/.agent

# Copy templates to create your state files
cp STATE.template.md STATE.md
cp BACKLOG.template.md BACKLOG.md
cp PROGRESS.template.md PROGRESS.md
cp LEARNINGS.template.md LEARNINGS.md
```

Your local state files are gitignored - they won't be committed to the repository.

## Quick Start

### Starting a New Session
1. **Read `.agent/STATE.md`** - Understand current project state
2. **Read `.agent/PROGRESS.md`** (last 2 sessions) - Get recent context
3. **Check `.agent/BACKLOG.md`** - Pick next task if nothing in progress

### During Session
- Work on **ONE task at a time**
- Make incremental commits
- Document decisions in PROGRESS.md
- If blocked, update STATE.md and move to next task

### Ending a Session
1. Update `.agent/STATE.md` with current status
2. Append to `.agent/PROGRESS.md` with session summary
3. Update `.agent/BACKLOG.md` (mark completed, add new tasks)
4. Write detailed handoff notes (assume next session knows nothing)

## Directory Structure

```
agent_tasks/
├── .agent/              # Memory system (ALWAYS READ FIRST)
│   ├── STATE.md         # Current project state (single source of truth)
│   ├── CONSTITUTION.md  # Project principles and constraints
│   ├── BACKLOG.md       # All tasks not yet started
│   ├── PROGRESS.md      # Session-by-session log (append only)
│   └── LEARNINGS.md     # What worked, what didn't
│
├── tasks/               # Active task folders
│   └── {task-id}-{name}/
│       ├── TASK.md      # Task description and acceptance criteria
│       ├── files...     # Task-specific work files
│       └── RESULT.md    # Completion summary
│
├── .old/                # Archive (not version controlled)
│   ├── planning/        # Archived planning documents
│   ├── tasks/           # Completed task folders
│   └── sessions/        # Old session artifacts
│
└── README.md            # This file
```

## Memory System Files

### STATE.md - Read This First Every Session
Current project state including:
- Last updated timestamp and session number
- Health status (🟢 Green | 🟡 Yellow | 🔴 Red)
- Current focus (what task is in progress)
- Next priorities
- Any blockers

### CONSTITUTION.md - Decision Guide
Project principles, constraints, and quality standards:
- Core development principles (why they matter)
- Required technologies and patterns
- Forbidden approaches
- Quality bar for "done"

### BACKLOG.md - Task Queue
All tasks in priority order:
- **Ready**: No dependencies, can start immediately
- **Blocked**: Waiting on other tasks or user input
- **Completed**: Finished and verified

### PROGRESS.md - Append-Only Log
Session-by-session history:
- What was accomplished
- Decisions made and rationale
- Handoff notes for next session

### LEARNINGS.md - Pattern Library
Accumulated wisdom:
- Patterns that work well
- Anti-patterns to avoid
- Project-specific discoveries

## When to Use This System

**Use agent coordination for:**
- Multi-session features (can't finish in one context window)
- Complex tasks requiring exploration and planning
- Work that involves multiple files and components
- Tasks where you need to track decisions and rationale

**Don't use for:**
- Simple bug fixes
- Single-file changes
- Quick documentation updates
- Obvious, straightforward implementations

## Principles

1. **Every session starts with amnesia** - Only files persist
2. **One task at a time** - Focus until complete or blocked
3. **Detailed handoffs** - Next session should know what to do immediately
4. **Progress over perfection** - Working code > perfect plans
5. **Clean as you go** - Archive old work to .old/

## Task Lifecycle & Cleanup

### Task States
```
BACKLOG (Ready/Blocked) → IN PROGRESS → COMPLETED → ARCHIVED
```

### Cleanup Process

**At Task Close (`/agent-taskclose`)**:
- Agent has maximum context about task files
- Consolidates findings, extracts knowledge
- Moves task-specific artifacts to `.old/`

**Periodic Cleanup (`/agent-cleanfiles`)**:
- Reviews BACKLOG.md for completed tasks `[x]`
- Archives completed task folders: `tasks/{id}/ → .old/tasks/`
- Cleans orphaned planning documents
- Flags uncertain files for user decision

### Archive Structure
```
.old/
├── tasks/           # Completed task folders (TASK.md, RESULT.md, files)
├── planning/        # Archived planning documents
└── sessions/        # Old session artifacts
```

### Non-Destructive Guarantee
- Files are NEVER deleted automatically
- Always moved to `.old/` hierarchy
- User reviews `.old/recommend_to_delete/` before permanent deletion

## Strategic Planning Documents

### ROADMAP.md - Development Roadmap
Comprehensive analysis of all feature development work:
- 15 major feature areas analyzed
- Priority-based organization (Phase 1-4)
- Timeline and complexity estimates
- Resource allocation guidance

Generated from `feature_dev_notes/` and `planning_docs/` analysis.

### WORKTREE_WORKFLOW.md - Git Worktree Development Pattern
Complete guide for using git worktrees with sideloaded development folders:
- Branch isolation without switching branches
- Access to shared `feature_dev_notes/` and `planning_docs/`
- Unified memory system across all worktrees
- Example workflows and troubleshooting

**Recommended Pattern**: Create worktree per feature, sideload research folders, develop in isolation, merge when complete.

## Tools

All coordination files are **plain Markdown** - no special tools required. Just:
- Read with any text editor
- Edit with any text editor
- Version control with git (structure committed, .old/ ignored)
- Archive to .old/ when complete

Simple, portable, future-proof.

## Git Worktree Integration

For feature development using worktrees:

```bash
# Create feature worktree
git worktree add -b feature/check-ras ../ras-commander-worktrees/feature-check-ras

# Sideload development folders (Windows)
cd ../ras-commander-worktrees/feature-check-ras
mklink /J agent_tasks C:\GH\ras-commander\agent_tasks
mklink /J feature_dev_notes C:\GH\ras-commander\feature_dev_notes
mklink /J planning_docs C:\GH\ras-commander\planning_docs

# Now work in isolated branch with access to all coordination and research materials
```

See `WORKTREE_WORKFLOW.md` for complete details.
