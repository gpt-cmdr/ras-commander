# Memory & Knowledge Consolidation Plan

**Date**: 2025-12-11
**Purpose**: Ultra-thinking analysis and consolidation of memory/knowledge systems
**Status**: Planning complete, ready for execution

## Executive Summary

ras-commander has **two complementary systems** that serve different purposes:

1. **Hierarchical Knowledge** (CLAUDE.md ecosystem) - HOW to work
2. **Agent Memory** (agent_tasks/ ecosystem) - WHAT we're doing

These are **orthogonal, not redundant**. The consolidation focuses on:
- Clarifying boundaries between systems
- Deprecating redundant `planning_docs/`
- Expanding curator scope to understand both
- Creating governance for when to use each

## Current State Analysis

### Three Memory/Planning Locations

| Location | Purpose | Git Tracked? | Status |
|----------|---------|--------------|--------|
| **agent_tasks/** | Multi-session task coordination | Partial (structure yes, .old/ no) | ✅ Active, well-designed |
| **planning_docs/** | Ad-hoc brainstorming | ❌ No (ignored) | ⚠️ Deprecated by CLAUDE.md |
| **feature_dev_notes/** | Feature development research | ❌ No (ignored) | ✅ Active, needs CLAUDE.md |

### Two Knowledge Systems

| System | Purpose | Scope | Lifespan |
|--------|---------|-------|----------|
| **Hierarchical Knowledge** | Teach Claude HOW | Timeless patterns, architecture | Permanent |
| **Agent Memory** | Track WHAT work | Current state, tasks in progress | Active until complete |

## The Key Insight: Orthogonal, Not Redundant

### Hierarchical Knowledge (CLAUDE.md Ecosystem)

**Purpose**: Teach Claude HOW to work in repository
```
"Use static classes for RasCmdr"
"Test with real HEC-RAS examples, not mocks"
"Remote execution requires Session ID=2"
```

**Characteristics**:
- Timeless (true regardless of what task you're doing)
- Educational (teaches patterns and conventions)
- Hierarchical (loaded based on directory)
- Permanent (evolves slowly with repository)

**Files**:
- CLAUDE.md (root → subpackage hierarchy)
- .claude/rules/ (topic-specific guidance)
- .claude/skills/ (library workflows)
- .claude/subagents/ (specialist definitions)

### Agent Memory (agent_tasks/ Ecosystem)

**Purpose**: Track WHAT work is being done across sessions
```
"Currently implementing USGS real-time monitoring (Session 6)"
"Blocked on user decision about authentication method"
"Next: Create gauge catalog generation feature"
```

**Characteristics**:
- Temporal (specific to current work)
- Stateful (changes every session)
- Append-only progress log
- Archived when complete

**Files**:
- .agent/STATE.md (current state snapshot)
- .agent/BACKLOG.md (task queue)
- .agent/PROGRESS.md (session log)
- .agent/LEARNINGS.md (accumulated wisdom)
- .agent/CONSTITUTION.md (project principles)

### How They Complement Each Other

```
Agent starts session:
1. Read CLAUDE.md → Learn HOW to code in this repo
2. Read agent_tasks/STATE.md → Learn WHAT to work on
3. Execute task using knowledge, update memory
4. Session ends, memory persists for next agent
```

**When developing feature**:
- Knowledge guides HOW (patterns, conventions, APIs)
- Memory tracks WHAT (decisions, progress, blockers)

**When feature completes**:
- Extract knowledge FROM memory INTO persistent structure
- Archive task memory to .old/
- Update CLAUDE.md or create skill with learnings

## Problems Identified

### Problem 1: planning_docs/ is Redundant ⚠️

**Current State**:
- Contains 2 brainstorming files (88KB total)
- Ignored in git (.gitignore line 102)
- Root CLAUDE.md line 100 says: "All temporary markdown files... should be placed in planning_docs/"
- But agent_tasks/ already has strategic planning (ROADMAP.md, etc.)

**Why Redundant**:
- agent_tasks/ serves same purpose (strategic planning)
- planning_docs/ not tracked, so no session continuity
- Confuses: where to put planning docs?

**Solution**: Deprecate planning_docs/, consolidate into agent_tasks/

### Problem 2: Unclear Boundaries 🤔

**Current Confusion**:
- When to use agent_tasks/ vs feature_dev_notes/?
- Where do strategic planning docs go?
- How does hierarchical knowledge curator fit with agent memory?

**Solution**: Define clear governance rules

### Problem 3: feature_dev_notes/ Missing Context 📂

**Current State**:
- 94 markdown files in 40+ subdirectories
- No CLAUDE.md to guide agents working there
- Unclear relationship to agent_tasks/ and ras_skills/

**Solution**: Create feature_dev_notes/CLAUDE.md with clear guidance

### Problem 4: Curator Scope Too Narrow 🎯

**Current Scope**: Only hierarchical knowledge (CLAUDE.md, .claude/, ras_skills/)

**Missing**: Understanding of agent memory system

**Impact**: Can't help with:
- planning_docs → agent_tasks/ migration
- When to use agent memory vs knowledge
- Extracting learnings from memory into knowledge

**Solution**: Expand curator scope, rename to reflect full responsibility

## Consolidation Plan

### Action 1: Rename Curator

**Old Name**: `hierarchical-knowledge-curator`
**New Name**: `hierarchical-knowledge-agent-skill-memory-curator`

**Expanded Mission**:
- ✅ Hierarchical Knowledge (CLAUDE.md hierarchy, .claude/)
- ✅ Agent Memory (agent_tasks/ coordination)
- ✅ Skills (ras_skills/ production skills)
- ✅ Memory Continuity (knowledge ↔ memory interaction)

**Benefits**:
- Single specialist understands full landscape
- Can guide planning_docs migration
- Helps extract learnings into knowledge
- Maintains governance for both systems

### Action 2: Deprecate planning_docs/

**Steps**:

1. **Review Current Content**:
   ```bash
   ls -lh planning_docs/
   # AGENT_BRAINSTORMING_HYDRAULIC_WORKFLOWS.md (47KB)
   # RESEARCH_ADVANCED_ANALYSIS_BRAINSTORM.md (42KB)
   ```

2. **Assess Relevance**:
   - If superseded by recent work → archive
   - If still valuable → move to agent_tasks/

3. **Execute Migration**:
   ```bash
   # Archive old brainstorms
   mv planning_docs/* agent_tasks/.old/planning/

   # Remove planning_docs/
   rmdir planning_docs/

   # Update .gitignore (remove /planning_docs line)
   ```

4. **Update CLAUDE.md**:
   - Remove line 100 reference to planning_docs/
   - Update guidance to use agent_tasks/ for all planning

**Result**: Single location for all planning (agent_tasks/)

### Action 3: Create feature_dev_notes/CLAUDE.md

**Purpose**: Guide agents working in feature development area

**Content**:
```markdown
# feature_dev_notes/ - Feature Development Research

When working in this directory, you're doing active feature development research.

## Purpose

This directory contains feature-specific development research, analysis, and planning:
- Detailed technical analysis
- Prototypes and experiments
- Large example projects and datasets
- Planning documents for new features

## Organization

One folder per feature area:
```
feature_dev_notes/
├── Hierarchical_Knowledge_Approach/  # Complete research + planning
├── gauge_data_import/                 # USGS integration development
├── hms_ras_linking_agent/            # HMS-RAS boundary linking
└── [feature-name]/                   # Your feature research
```

## Relationship to Other Systems

### vs agent_tasks/ (Task Memory)

**Use feature_dev_notes/ when**:
- Feature-specific research and analysis
- Large example projects (HEC-RAS models, datasets)
- Iterative development with prototypes
- Planning docs specific to ONE feature

**Use agent_tasks/ when**:
- Cross-cutting work affecting multiple features
- Multi-session task coordination
- Strategic planning for entire repository
- Tracking current work state

**Rule of Thumb**: If research is specific to one feature area, use feature_dev_notes/. If it's about project-wide work or current session state, use agent_tasks/.

### vs .claude/ (Persistent Knowledge)

**feature_dev_notes/**: Development phase
- Research, experiments, learning
- Iteration and prototypes
- Large files, temporary documents

**.claude/**: Production phase
- Refined knowledge extracted from research
- Permanent patterns and guidance
- Concise, actionable documentation

**Migration Path**: feature_dev_notes/ → .claude/ (when knowledge crystalizes)

### vs ras_skills/ (Production Skills)

**feature_dev_notes/**: Development
- Prototype skills
- Testing and iteration
- Full context and examples

**ras_skills/**: Production
- Proven, reliable skills
- Clean, minimal documentation
- Ready for end-user deployment

**Migration Path**: feature_dev_notes/ → ras_skills/ (when skill is production-ready)

## Lifecycle

1. **Start**: Create feature_dev_notes/[feature-name]/
2. **Develop**: Research, analyze, prototype, plan
3. **Extract**: Move learnings to .claude/rules/ or create skills
4. **Deploy**: Promote production-ready skills to ras_skills/
5. **Archive**: Keep in feature_dev_notes/ for historical reference

**Do NOT delete**: Feature development notes are valuable historical context.

## Best Practices

- **One feature per folder**: Clear boundaries
- **Include README.md**: Explain feature and status
- **Document decisions**: Why did we choose approach X?
- **Large files OK**: This folder is not git-tracked
- **Link from agent_tasks/**: If feature has active task

## See Also

- agent_tasks/ - Multi-session task coordination
- .claude/ - Persistent knowledge hierarchy
- ras_skills/ - Production-ready skills
```

**Result**: Clear guidance for agents working on feature development

### Action 4: Define Clear Boundaries

**Create Governance Matrix**:

| Scenario | Use agent_tasks/ | Use feature_dev_notes/ | Use .claude/ | Use ras_skills/ |
|----------|------------------|------------------------|--------------|-----------------|
| Starting new feature development | Create task in BACKLOG.md | Create feature folder | - | - |
| Feature-specific research | Document decisions in PROGRESS.md | Store analysis, prototypes | - | - |
| Multi-session task tracking | STATE.md, BACKLOG.md, PROGRESS.md | - | - | - |
| Pattern discovered during dev | Add to LEARNINGS.md | - | Extract to rules/ | - |
| Production-ready skill | Update BACKLOG (complete) | - | Create skill/ | Move from dev |
| Strategic planning | ROADMAP.md, planning docs | - | - | - |
| How to code in repo | - | - | CLAUDE.md, rules/ | - |
| Multi-step workflow | - | - | skills/ | - |
| End-user automation | - | - | - | SKILL.md |

**Decision Tree**:
```
Is this about CURRENT work state?
├─ YES → agent_tasks/ (STATE, BACKLOG, PROGRESS)
└─ NO ↓

Is this feature-specific research?
├─ YES → feature_dev_notes/[feature-name]/
└─ NO ↓

Is this permanent knowledge (HOW to code)?
├─ YES → .claude/ (CLAUDE.md, rules/, skills/, subagents/)
└─ NO ↓

Is this production-ready skill?
└─ YES → ras_skills/
```

### Action 5: Add Agent Memory Reference to Curator

**New File**: `.claude/subagents/hierarchical-knowledge-curator/reference/agent-memory-system.md`

**Content**: Complete documentation of agent_tasks/ memory system:
- How .agent/ files work (STATE, BACKLOG, PROGRESS, LEARNINGS, CONSTITUTION)
- Session lifecycle (start, during, end)
- When to use agent memory vs feature research
- Relationship to hierarchical knowledge
- Best practices for multi-session coordination
- planning_docs/ deprecation complete

## Implementation Steps

### Step 1: Review planning_docs/ Content

```bash
cd planning_docs
cat AGENT_BRAINSTORMING_HYDRAULIC_WORKFLOWS.md | head -50
cat RESEARCH_ADVANCED_ANALYSIS_BRAINSTORM.md | head -50
```

Assess if still relevant or superseded by recent work.

### Step 2: Execute planning_docs/ Migration

```bash
# Create archive location
mkdir -p agent_tasks/.old/planning

# Move brainstorm files
mv planning_docs/* agent_tasks/.old/planning/

# Remove empty planning_docs/
rmdir planning_docs/

# Update .gitignore (remove /planning_docs line 102)
```

### Step 3: Create feature_dev_notes/CLAUDE.md

Use content from Action 3 above.

### Step 4: Rename Curator

```bash
# Rename subagent file
mv .claude/subagents/hierarchical-knowledge-curator.md \
   .claude/subagents/hierarchical-knowledge-agent-skill-memory-curator.md

# Rename reference directory
mv .claude/subagents/hierarchical-knowledge-curator \
   .claude/subagents/hierarchical-knowledge-agent-skill-memory-curator
```

Update YAML frontmatter name field.

### Step 5: Add Agent Memory Reference

Create `agent-memory-system.md` in reference/ directory.

### Step 6: Update Root CLAUDE.md

Remove planning_docs/ references:
- Line 100: Remove planning_docs/ paragraph
- Update guidance to use agent_tasks/ for all planning

### Step 7: Commit Changes

```bash
git add .
git commit -m "Consolidate memory systems: Deprecate planning_docs, expand curator scope"
```

## Success Metrics

### Before

- ❌ Three planning locations (agent_tasks, planning_docs, feature_dev_notes)
- ❌ Unclear boundaries between systems
- ❌ Curator only understands knowledge, not memory
- ❌ feature_dev_notes/ has no CLAUDE.md

### After

- ✅ Two complementary systems (knowledge + memory) with clear boundaries
- ✅ Single planning location (agent_tasks/)
- ✅ Curator understands full landscape
- ✅ feature_dev_notes/ has clear guidance
- ✅ Governance matrix for when to use each system

## Post-Consolidation State

### Hierarchical Knowledge (CLAUDE.md Ecosystem)

**Purpose**: HOW to work
**Locations**: /, ras_commander/, .claude/, ras_skills/
**Managed By**: hierarchical-knowledge-agent-skill-memory-curator

### Agent Memory (agent_tasks/ Ecosystem)

**Purpose**: WHAT we're doing
**Locations**: agent_tasks/.agent/
**Managed By**: hierarchical-knowledge-agent-skill-memory-curator

### Feature Research (feature_dev_notes/)

**Purpose**: Feature-specific development
**Locations**: feature_dev_notes/[feature-name]/
**Guided By**: feature_dev_notes/CLAUDE.md
**Migrates To**: .claude/ (knowledge) or ras_skills/ (production skills)

### Planning (Consolidated)

**All planning in**: agent_tasks/
- Strategic: ROADMAP.md, WORKTREE_WORKFLOW.md
- Tactical: BACKLOG.md, tasks/
- Historical: .old/planning/

## Benefits of Consolidation

1. **Clarity**: Clear boundaries, no confusion
2. **Efficiency**: One curator understands all systems
3. **Simplicity**: Fewer locations to check
4. **Governance**: Decision tree for where things go
5. **Continuity**: Knowledge ↔ memory interaction well-defined

---

**Status**: Plan complete, ready for execution
**Next**: Execute steps 1-7 in sequence
**Est. Time**: 2-3 hours
