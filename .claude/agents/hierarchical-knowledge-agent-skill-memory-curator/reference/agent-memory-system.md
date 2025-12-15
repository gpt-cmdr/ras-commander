# Agent Memory System - Multi-Session Task Coordination

**Purpose**: Persistent memory for multi-session development tasks
**Location**: `agent_tasks/`
**Complements**: Hierarchical knowledge (CLAUDE.md ecosystem)
**Version**: 1.0
**Date**: 2025-12-11

## Executive Summary

The agent memory system (`agent_tasks/`) provides **temporal task coordination** across sessions, complementing the **timeless knowledge** in CLAUDE.md hierarchy.

**Key Distinction**:
- **Hierarchical Knowledge** (CLAUDE.md) → HOW to code
- **Agent Memory** (agent_tasks/) → WHAT we're doing

These systems are **orthogonal, not redundant**. Together they enable effective multi-session development.

## Core Concept: Session Amnesia

**Fundamental Principle**: Every session starts with amnesia - only files persist.

Agents don't remember previous sessions. The memory system ensures context continuity by maintaining structured state in markdown files that agents read at session start.

```
Session N ends → Update memory files → Commit to git
Session N+1 starts → Read memory files → Continue work
```

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
├── ROADMAP.md           # Strategic planning (15 feature areas)
├── WORKTREE_WORKFLOW.md # Git worktree development pattern
├── README.md            # Complete system documentation
└── .gitignore           # Excludes .old/ and tasks/*/
```

## Memory Files (.agent/)

### STATE.md - Read This First Every Session

**Purpose**: Single source of truth for current project state

**Contents**:
```markdown
# Project State

**Last Updated**: 2025-12-11 15:30 UTC (Session 7)
**Health**: 🟢 Green | 🟡 Yellow | 🔴 Red

## Current Focus

Session 7 (current): Implementing Phase 2 of hierarchical knowledge approach
- Extracting Python patterns from root CLAUDE.md → .claude/rules/python/
- Target: Reduce root from 607 lines → <200 lines

## Next Priorities

1. Complete Phase 2 content migration (root → rules)
2. Create missing CLAUDE.md files (6 subpackages)
3. Begin Phase 4 (agents & skills)

## Blockers

None

## Recent Completions

- ✅ Phase 1: Foundation (rename, .claude/ structure, ras_skills/)
- ✅ Hierarchical Knowledge Curator subagent created
- ✅ Memory system consolidation (planning_docs deprecated)
```

**Update Frequency**: End of every session

**Reading Pattern**:
```python
# Session start
1. Read STATE.md - Get current snapshot
2. Identify "Current Focus" - What to work on
3. Check "Blockers" - Any obstacles?
4. Review "Next Priorities" - Queue awareness
```

### BACKLOG.md - Task Queue

**Purpose**: All tasks organized by status

**Contents**:
```markdown
# Task Backlog

## Ready (Can start immediately)

### Task ID: LIB-002 - Create Missing CLAUDE.md Files
**Priority**: High
**Effort**: 2-3 hours
**Dependencies**: None
**Description**: Create CLAUDE.md for usgs/, check/, precip/, mapping/ subpackages

### Task ID: LIB-003 - Define HDF Analyst Subagent
**Priority**: Medium
**Effort**: 1 hour
**Dependencies**: Phase 2 complete
**Description**: Create specialist subagent for HDF file operations

## Blocked

### Task ID: LIB-005 - Implement Automated Calibration
**Blocker**: Waiting for user decision on optimization algorithm
**Description**: ...

## Completed

### Task ID: LIB-001 - Hierarchical Knowledge Foundation ✅
**Completed**: 2025-12-11 (Session 6)
**Outcome**: .claude/ structure created, ras_skills/ established, curator defined
```

**Update Frequency**: When tasks change status

**Format**:
- Ready: No dependencies, clear requirements
- Blocked: Specific blocker noted, clear unblock condition
- Completed: Date, session, outcome summary

### PROGRESS.md - Append-Only Session Log

**Purpose**: Historical record of all sessions with handoff notes

**Contents**:
```markdown
# Session Progress Log

## Session 7 - 2025-12-11

**Focus**: Memory system consolidation

**Completed**:
- ✅ Reviewed planning_docs/ content (2 brainstorm files, 88KB)
- ✅ Migrated planning_docs/ → agent_tasks/.old/planning/ (non-destructive)
- ✅ Created feature_dev_notes/CLAUDE.md with clear boundaries
- ✅ Renamed curator: hierarchical-knowledge-agent-skill-memory-curator
- ✅ Added agent-memory-system.md reference documentation
- ✅ Deprecated planning_docs/, updated root CLAUDE.md

**Decisions**:
- planning_docs/ redundant with agent_tasks/ → deprecate
- Curator scope expanded to understand both knowledge AND memory
- Clear governance: agent_tasks/ vs feature_dev_notes/ vs .claude/ vs ras_skills/

**Handoff Notes**:
Next session should begin Phase 2 content migration:
1. Extract Python patterns from root CLAUDE.md → .claude/rules/python/
2. Start with static-classes.md (most fundamental pattern)
3. Test context loading after extraction

**Blockers**: None

---

## Session 6 - 2025-12-11

**Focus**: Phase 1 implementation

**Completed**:
- ✅ Created .claude/ framework structure
- ✅ Renamed ras_agents → ras_skills
- ✅ Updated .gitignore (exclude large dev folders)
- ✅ Created hierarchical-knowledge-curator subagent

**Handoff Notes**:
Phase 1 complete. Next: Begin Phase 2 (content migration).
See MASTER_IMPLEMENTATION_PLAN.md for details.

---

[Earlier sessions...]
```

**Update Frequency**: End of every session (append only)

**Critical Elements**:
- Focus - What was the session about?
- Completed - What got done?
- Decisions - Why did we choose approach X?
- Handoff Notes - What should next session do?
- Blockers - What stopped progress?

### LEARNINGS.md - Accumulated Wisdom

**Purpose**: Pattern library of what works and what doesn't

**Contents**:
```markdown
# Project Learnings

## Patterns That Work Well

### Always Read Memory Files First
**Context**: Multi-session coordination
**Pattern**: STATE.md → PROGRESS.md (last 2) → BACKLOG.md
**Why**: Prevents redundant work, maintains continuity
**Example**: Session 7 picked up exactly where Session 6 left off

### Non-Destructive Migrations
**Context**: Deprecating planning_docs/
**Pattern**: Copy → Verify → Archive → Document
**Why**: Can always recover if something important was missed
**Example**: planning_docs/ → agent_tasks/.old/planning/ with README.md

## Anti-Patterns to Avoid

### Deleting Historical Research
**Context**: Completed features
**Anti-Pattern**: Removing feature_dev_notes/ after completion
**Why Bad**: Loses valuable context for future maintainers
**Correct Approach**: Keep in feature_dev_notes/, extract knowledge to .claude/

### Mixing Temporal and Timeless
**Context**: Documentation organization
**Anti-Pattern**: Putting current task state in CLAUDE.md
**Why Bad**: CLAUDE.md is timeless (HOW), not temporal (WHAT)
**Correct Approach**: Current state → agent_tasks/STATE.md, patterns → CLAUDE.md

## Project-Specific Discoveries

### Hierarchical Knowledge + Agent Memory = Complete System
**Discovery**: Two complementary systems, not redundant
**Knowledge**: HOW to code (CLAUDE.md hierarchy)
**Memory**: WHAT we're doing (agent_tasks/ coordination)
**Interaction**: Extract learnings FROM memory INTO knowledge when patterns emerge

### Progressive Disclosure Saves Tokens
**Discovery**: Reference files have 0 token cost until read
**Pattern**: Main SKILL.md <500 lines, details in reference/
**Benefit**: 6x reduction in baseline context (60KB available, 10KB typical)
```

**Update Frequency**: When patterns emerge or lessons learned

### CONSTITUTION.md - Project Principles

**Purpose**: Decision guide and quality standards

**Contents**:
```markdown
# Project Constitution

## Core Development Principles

### 1. Test with Real HEC-RAS Projects, Not Mocks

**Why**: HEC-RAS is complex, mocks miss edge cases
**Applies To**: All new features, validation, testing
**Example**: Use RasExamples.extract_project() for validation

### 2. Static Classes Pattern

**Why**: Cleaner API, no instantiation confusion
**Applies To**: Core classes (RasCmdr, HdfBase, etc.)
**Forbidden**: `RasCmdr()` instantiation

### 3. Progressive Disclosure

**Why**: Token efficiency, better organization
**Applies To**: CLAUDE.md hierarchy, skills, reference files
**Target**: Root <200 lines, subpackage <150 lines, rules 50-200 lines

## Required Technologies

- Python 3.10+
- HEC-RAS 6.x+ (5.x legacy support)
- pathlib.Path for all paths
- @log_call decorator for functions

## Forbidden Approaches

- ❌ Unit tests with mocks (use real HEC-RAS projects)
- ❌ Instantiating static classes
- ❌ Deleting historical research
- ❌ planning_docs/ (deprecated, use agent_tasks/)

## Quality Bar for "Done"

- ✅ Tested with real HEC-RAS example projects
- ✅ Example notebook demonstrating usage
- ✅ Patterns extracted to .claude/rules/
- ✅ Documentation updated
- ✅ Commit message explains WHY, not just WHAT
```

**Update Frequency**: Rarely (only when principles change)

## Session Lifecycle

### Every Session Start

```markdown
1. Read `agent_tasks/.agent/STATE.md`
   → Understand current project state

2. Read `agent_tasks/.agent/PROGRESS.md` (last 2 sessions)
   → Get recent context and handoff notes

3. Check `agent_tasks/.agent/BACKLOG.md`
   → Pick next task if nothing in progress

4. Read relevant CLAUDE.md files
   → Learn HOW to code in this area
```

**Time Investment**: 5-10 minutes
**Benefit**: Complete context, no redundant work

### During Session

```markdown
- Work on ONE task at a time
- Make incremental commits (early and often)
- Document decisions in PROGRESS.md as you go
- If blocked, update STATE.md and move to next task
```

**Pattern**: Focus, commit, document, iterate

### Every Session End

```markdown
1. Update `.agent/STATE.md` with current status
   → Health, current focus, next priorities, blockers

2. Append to `.agent/PROGRESS.md` with session summary
   → What completed, decisions, handoff notes

3. Update `.agent/BACKLOG.md`
   → Mark completed, add new tasks discovered

4. Write detailed handoff notes
   → Assume next session knows nothing

5. Extract learnings to LEARNINGS.md (if patterns emerged)
   → What worked, what didn't
```

**Time Investment**: 10-15 minutes
**Benefit**: Next session starts smoothly

## When to Use Agent Memory

**Use agent_tasks/ for**:
- ✅ Multi-session features (can't finish in one context window)
- ✅ Complex tasks requiring exploration and planning
- ✅ Work involving multiple files and components
- ✅ Tasks where decisions and rationale need tracking
- ✅ Strategic planning (ROADMAP.md, etc.)

**Don't use for**:
- ❌ Simple bug fixes (single session)
- ❌ Single-file changes (no coordination needed)
- ❌ Quick documentation updates (straightforward)
- ❌ Obvious implementations (no decisions to track)

## Relationship to Other Systems

### vs Hierarchical Knowledge (.claude/)

| Aspect | Agent Memory (agent_tasks/) | Hierarchical Knowledge (.claude/) |
|--------|----------------------------|-----------------------------------|
| **Purpose** | WHAT we're doing | HOW to code |
| **Nature** | Temporal, stateful | Timeless, patterns |
| **Updates** | Every session | When patterns emerge |
| **Lifespan** | Active until complete, then archive | Permanent, evolves slowly |
| **Examples** | "Currently on task LIB-002" | "Use static classes" |

**Complementary**: Read CLAUDE.md to learn HOW, read agent_tasks/ to learn WHAT

### vs Feature Development Research (feature_dev_notes/)

| Aspect | Agent Memory | Feature Research |
|--------|--------------|------------------|
| **Scope** | Cross-cutting, project-wide | Feature-specific |
| **Content** | State, tasks, decisions | Analysis, prototypes, experiments |
| **Updates** | Every session | During feature development |
| **Location** | agent_tasks/ | feature_dev_notes/[feature-name]/ |

**Rule of Thumb**:
- Project coordination → agent_tasks/
- Feature-specific research → feature_dev_notes/

## Migration: planning_docs/ Deprecated

**Status**: planning_docs/ deprecated 2025-12-11

**Reason**: Redundant with agent_tasks/

**Migration**:
- Old brainstorm files → agent_tasks/.old/planning/
- New planning docs → agent_tasks/ (strategic) or feature_dev_notes/ (feature-specific)
- Root CLAUDE.md updated (no more planning_docs/ references)

**New Pattern**:
```
Need planning document?
├─ Strategic (project-wide) → agent_tasks/
└─ Feature-specific → feature_dev_notes/[feature]/
```

## Best Practices

### DO

✅ **Read memory files every session** - STATE, PROGRESS (last 2), BACKLOG
✅ **Update memory files every session end** - Keep them current
✅ **Work on one task at a time** - Focus until complete or blocked
✅ **Write detailed handoff notes** - Next session knows nothing
✅ **Extract learnings** - Patterns → .claude/, wisdom → LEARNINGS.md
✅ **Use git for memory structure** - Commit STATE, BACKLOG, PROGRESS
✅ **Archive completed work** - tasks/ → .old/tasks/

### DON'T

❌ **Skip reading memory files** - Causes redundant work
❌ **Work on multiple tasks** - Context switching is expensive
❌ **Forget handoff notes** - Next session will struggle
❌ **Put current state in CLAUDE.md** - Keep temporal separate from timeless
❌ **Delete completed tasks** - Archive to .old/, don't remove
❌ **Use planning_docs/** - Deprecated, use agent_tasks/ or feature_dev_notes/

## Git Tracking

**What's tracked**:
- .agent/ structure and memory files (STATE, BACKLOG, PROGRESS, LEARNINGS, CONSTITUTION)
- Strategic planning (ROADMAP.md, WORKTREE_WORKFLOW.md)
- README.md, .gitignore

**What's NOT tracked** (see .gitignore):
- agent_tasks/.old/ (archive folder)
- agent_tasks/tasks/*/ (active task work)

**Rationale**: Structure and memory tracked, temporary work ignored

## Success Patterns

### Pattern 1: Smooth Session Transitions

```
Session N ends:
- Update STATE.md: "Completed LIB-001, starting LIB-002"
- Append PROGRESS.md: "Next: Extract static-classes.md to .claude/rules/python/"
- Update BACKLOG.md: LIB-001 → Completed, LIB-002 → In Progress

Session N+1 starts:
- Read STATE.md: "Working on LIB-002"
- Read PROGRESS.md (last session): "Next: Extract static-classes.md"
- Continue immediately, no time wasted
```

**Benefit**: Zero context loss between sessions

### Pattern 2: Knowledge Extraction

```
During feature development:
- Document decisions in PROGRESS.md
- Note patterns in LEARNINGS.md
- Keep research in feature_dev_notes/

When feature completes:
- Extract patterns → .claude/rules/ (permanent knowledge)
- Update LEARNINGS.md → Confirmed patterns
- Archive task → .old/tasks/
- Keep feature_dev_notes/ for historical context
```

**Benefit**: Learnings become permanent knowledge

## Tools

All coordination files are **plain Markdown**:
- Read with any text editor
- Edit with any text editor
- Version control with git
- Archive with simple file operations
- No special tools required

**Simple, portable, future-proof.**

---

**Status**: Active memory system, complements hierarchical knowledge
**Documentation**: agent_tasks/README.md (complete guide)
**Curator**: hierarchical-knowledge-agent-skill-memory-curator
**Version**: 1.0
