# Governance Rules - Hierarchical Knowledge Architecture

**Purpose**: Decision framework for maintaining healthy knowledge organization
**Version**: 1.0
**Date**: 2025-12-11

## File Size Governance

### When to Split Files

**Proactive Planning** (60KB threshold):
- Start planning split when file reaches 60KB
- Identify logical division points
- Create migration plan
- No immediate action required

**Hard Limit** (75KB threshold):
- MUST split when file reaches 75KB
- Immediate action required
- No exceptions

**Why These Limits?**
- Claude processes files efficiently up to ~60KB
- Performance degradation beyond 75KB
- Progressive disclosure maintains quality under limits

### Target Sizes by File Type

| File Type | Target Size | Max Size | Rationale |
|-----------|-------------|----------|-----------|
| Root CLAUDE.md | <200 lines (~10KB) | 250 lines | Strategic vision only |
| Subpackage CLAUDE.md | <150 lines (~8KB) | 200 lines | Tactical patterns |
| .claude/rules/*.md | 50-200 lines | 300 lines | One focused topic |
| .claude/skills/SKILL.md | <500 lines (~25KB) | 600 lines | Navigation + overview |
| Reference files | Unlimited | - | Loaded on-demand |

## Content Assignment Rules

### When to Create New CLAUDE.md

Create a new subpackage CLAUDE.md when **ALL** of these are true:

✅ **Subpackage has 3+ modules** with distinct responsibilities
✅ **Specialized knowledge exceeds 4KB** and is reusable across modules
✅ **Parent CLAUDE.md would exceed 20KB** if content added there

**Examples**:
- ✅ `ras_commander/usgs/` - 14 modules, complex USGS workflows
- ✅ `ras_commander/remote/` - 6 modules, critical remote execution patterns
- ❌ `ras_commander/utils/` - 2 helper modules, no specialized knowledge

### When to Create New Rules File

Create a new .claude/rules/ file when:

✅ **Topic is distinct and reusable** across multiple locations
✅ **Content is 50-200 lines** of focused guidance
✅ **Multiple agents would benefit** from this knowledge

**Anti-patterns to avoid**:
- ❌ Creating rules file for <50 lines (too granular)
- ❌ Mixing unrelated topics in one file (poor cohesion)
- ❌ Duplicating content from CLAUDE.md (maintain single source)

### When to Consolidate Files

Consolidate when **ANY** of these are true:

✅ **Multiple files <2KB** covering the same topic
✅ **Circular references** between 3+ files
✅ **Content redundancy** across multiple locations
✅ **Navigation confusion** (unclear which file to read)

**Process**:
1. Identify logical grouping
2. Merge content with clear sections
3. Update cross-references
4. Archive old files

## Hierarchy Governance

### Content Distribution Philosophy

**Broad context moves UP** (toward root):
- Strategic vision
- Project-wide patterns
- High-level architecture
- Decision frameworks

**Specific details move DOWN** (toward leaves):
- Implementation specifics
- API details
- Code examples
- Troubleshooting guides

### Progressive Disclosure Pattern

```
Level 1 (Root CLAUDE.md):
  "Use static classes. Test with HEC-RAS examples."
  ↓
Level 2 (ras_commander/CLAUDE.md):
  "Common pattern: init → compute → extract"
  ↓
Level 3 (ras_commander/hdf/CLAUDE.md):
  "HdfResultsPlan API for results. Check steady vs unsteady first."
  ↓
Level 4 (.claude/rules/hec-ras/hdf-files.md):
  [Complete API reference, code examples, edge cases]
  ↓
Level 5 (.claude/skills/extracting-hecras-results/reference/api.md):
  [Exhaustive documentation, all parameters, all methods]
```

### 5-Level Hierarchy Structure

```
1. Root CLAUDE.md
   └─ Strategic vision, model selection, delegation patterns

2. Library CLAUDE.md (ras_commander/)
   └─ Module organization, common workflows

3. Subpackage CLAUDE.md (ras_commander/hdf/)
   └─ Domain-specific patterns, key APIs

4. Rules (.claude/rules/hec-ras/hdf-files.md)
   └─ Detailed procedures, technical guidance

5. Skills Reference (.claude/skills/*/reference/*.md)
   └─ Complete documentation, all details
```

## Skills Governance

### When to Create a Library Skill (.claude/skills/)

Create a library skill when:

✅ **Multi-step workflow** users frequently need
✅ **Crosses multiple modules** in ras-commander
✅ **Discoverable via natural language** improves UX
✅ **Reusable pattern** applies to many projects

**Examples**:
- ✅ "executing-hecras-plans" - RasCmdr workflow with parallel execution
- ✅ "integrating-usgs-gauges" - Complete USGS workflow across 4 modules
- ❌ "reading-one-file" - Too trivial, not a workflow

### When to Create a Domain Skill (ras_skills/)

Create a domain skill when:

✅ **Production-ready capability** for end users
✅ **Standalone functionality** can distribute separately
✅ **Domain-specific automation** (not library usage)
✅ **Shareable across projects** beyond ras-commander

**Examples**:
- ✅ "dss-linker" - Production HMS-to-RAS boundary linking
- ✅ "historical-flood-reconstruction" - Complete flood event modeling
- ❌ "hdf-file-reader" - Library functionality, belongs in .claude/skills/

### Skill Naming Standards

**Pattern**: Gerund form (verb + -ing)

✅ **Good Examples**:
- `executing-hecras-plans`
- `extracting-results`
- `integrating-usgs-gauges`
- `parsing-geometry-files`
- `repairing-geometry-issues`

❌ **Bad Examples**:
- `plan-executor` (noun form)
- `execute-plans` (imperative)
- `USGS-helper` (vague, noun)
- `geometry_parser` (underscore, noun)

### Skill Description Requirements

**Formula**: What + When + Triggers

**Minimum length**: 100 characters
**Maximum length**: 1024 characters
**Required elements**:
- What it does (specific actions)
- When to use it (trigger scenarios)
- Trigger keywords (for discovery)
- Domain-specific terms (HEC-RAS, USGS, etc.)

**Example** (good):
```yaml
description: |
  Executes HEC-RAS plans using RasCmdr.compute_plan(), handles parallel
  execution across multiple plans, and manages destination folders. Use when
  running HEC-RAS simulations, computing plans, executing models, or setting
  up parallel computation workflows. Handles plan numbers (01-99), destination
  folder setup, geometry preprocessing, and core allocation.
```

## Subagent Governance

### When to Define a Specialist Subagent

Create a specialist subagent when:

✅ **Clear domain boundary** exists (HDF, geometry, remote, USGS)
✅ **Significant specialized knowledge** (>10KB)
✅ **Frequent delegation** from main agent expected
✅ **Benefits from context inheritance** (folder-based specialization)

**Anti-patterns**:
- ❌ Creating subagent for single function
- ❌ Overlapping domains between agents
- ❌ Subagent without clear working directory

### Model Selection Standards

**Hard-code model in subagent definition** (cost predictability):

- **Opus**: Main orchestrator ONLY
  - High-level planning
  - Complex multi-domain decisions
  - Cost: ~$15/1M tokens

- **Sonnet**: Specialist agents
  - Domain expertise (HDF, geometry, USGS)
  - Multi-step workflows
  - Cost: ~$1.50/1M tokens

- **Haiku**: Task agents
  - Single file reads
  - Simple transforms
  - Quick operations
  - Cost: ~$0.02/1M tokens

### Tool Permission Standards

Grant **minimal necessary tools**:

**Read-only analysis**:
```yaml
tools: Read, Grep, Glob
```

**Documentation generation**:
```yaml
tools: Read, Grep, Glob, Write
```

**Code modification**:
```yaml
tools: Read, Write, Edit, Grep, Glob, Bash
```

**Never grant without justification**:
- Bash (can execute arbitrary commands)
- Write (can create files)
- Edit (can modify existing code)

## Subagent Output Governance

### Core Requirement: Markdown File Output

**All subagents MUST write markdown files and return file paths to the main agent.**

This is a foundational pattern that enables:
- Knowledge persistence across sessions
- Filterable/selective reading by main agent
- Consolidation by hierarchical knowledge agent
- Non-destructive lifecycle management

### Output Location Standards

| Output Type | Location | Example |
|-------------|----------|---------|
| Task analysis | `.claude/outputs/{subagent}/` | `.claude/outputs/hdf-analyst/2025-12-15-wse-analysis.md` |
| Multi-session state | `agent_tasks/.agent/` | STATE.md, PROGRESS.md |
| Feature research | `feature_dev_notes/{feature}/` | Context-specific |
| Consolidated findings | `.claude/outputs/summaries/` | Topic summaries |

### File Naming Standard

**Pattern**: `{date}-{subagent}-{task-description}.md`

**Examples**:
- `2025-12-15-hdf-analyst-breach-results-investigation.md`
- `2025-12-15-geometry-parser-cross-section-audit.md`
- `2025-12-15-usgs-integrator-gauge-discovery.md`

### Knowledge Lifecycle Management

**Active outputs** → `.claude/outputs/`
- Current, relevant findings
- Read by main agent as needed

**Outdated outputs** → `.old/`
- Superseded by newer analysis
- Preserved for reference
- Moved by hierarchical knowledge agent

**Recommend delete** → `.old/recommend_to_delete/`
- Temporary/scratch files
- Incorrect or failed outputs
- Duplicates
- User reviews before deletion

### Hierarchical Knowledge Agent Duties

The hierarchical-knowledge-agent-skill-memory-curator:

1. **Monitor** output growth in `.claude/outputs/`
2. **Consolidate** related findings into summaries
3. **Prune** outdated content to `.old/`
4. **Recommend deletion** for obviously stale files
5. **Never auto-delete** - user makes final decision

### Agent Tasks Cleanup (via `/agent-cleanfiles`)

The cleanup command actively reviews `agent_tasks/`:

1. **Scan BACKLOG.md** for completed tasks `[x]`
2. **Archive completed task folders**: `agent_tasks/tasks/{id}/ → agent_tasks/.old/tasks/`
3. **Clean orphaned files**: Planning docs, session handoffs for completed work
4. **Cross-reference** with `feature_dev_notes/` for completed feature research
5. **Flag uncertain** files for user decision

**Task Lifecycle**:
```
BACKLOG (Ready/Blocked) → IN PROGRESS → COMPLETED → ARCHIVED (.old/tasks/)
```

### Anti-Patterns to Enforce

❌ **Returning text blobs** - Text doesn't persist across sessions
❌ **Not writing files** - Knowledge lost when session ends
❌ **Unorganized locations** - Hard to find and consolidate
❌ **Overwriting without versioning** - Loses previous work

✅ **Write structured markdown** - Organized, dated, traceable
✅ **Return file paths** - Main agent reads as needed
✅ **Follow naming conventions** - Enables automation

**See**: `.claude/rules/subagent-output-pattern.md` for complete pattern documentation.

## Deprecation Governance

### AGENTS.md Deprecation Timeline

**Decision**: Keep for 1 release cycle with deprecation notice

**Phase 1** (Current release):
- Create CLAUDE.md alongside AGENTS.md
- Add deprecation notice to AGENTS.md
- Document migration path
- Both files present

**Phase 2** (Next release):
- Remove AGENTS.md files
- Keep only CLAUDE.md
- Update all references

**Deprecation Notice Template**:
```markdown
# AGENTS.md (DEPRECATED)

**⚠️ This file is deprecated and will be removed in the next release.**

Please refer to `CLAUDE.md` in this directory for current documentation.

## Migration

ras-commander now uses Claude's official hierarchical memory framework:
- CLAUDE.md files for context
- .claude/rules/ for detailed guidance
- .claude/skills/ for library workflows
- .claude/agents/ for specialist agents

See: `feature_dev_notes/Hierarchical_Knowledge_Approach/` for details.

---

[Original AGENTS.md content preserved below for one release cycle]
```

## Quality Assurance Rules

### Pre-Commit Checklist

Before committing changes:

**File Sizes**:
- [ ] No files exceed 75KB
- [ ] Root CLAUDE.md <200 lines
- [ ] Subpackage CLAUDE.md <150 lines
- [ ] Rules files 50-200 lines

**Content Quality**:
- [ ] No duplicated content
- [ ] No circular references
- [ ] Clear navigation
- [ ] Logical hierarchy

**Skills**:
- [ ] YAML frontmatter valid
- [ ] Description has trigger keywords
- [ ] Main SKILL.md <500 lines
- [ ] Reference files for details

**Subagents**:
- [ ] Model specified
- [ ] Tools minimal
- [ ] Working directory set
- [ ] Description trigger-rich

### Periodic Audits

**Weekly**:
- Check for new files exceeding size targets
- Scan for duplicated content
- Verify skills discoverable

**Monthly**:
- Full hierarchy review
- Consolidation opportunities
- Governance rule updates

**Quarterly**:
- Architecture health assessment
- User feedback integration
- Success metrics review

## Decision Matrix

### Quick Reference Guide

| Situation | Action | Location |
|-----------|--------|----------|
| Multi-step library workflow | Create skill | .claude/skills/ |
| Production domain automation | Create skill | ras_skills/ |
| Specialist domain (>10KB) | Create subagent | .claude/agents/ |
| Topic-specific guidance (50-200 lines) | Create rules file | .claude/rules/ |
| Subpackage with 3+ modules | Create CLAUDE.md | subpackage/ |
| File exceeds 60KB | Plan split | - |
| File exceeds 75KB | MUST split | - |
| Duplicated content | Consolidate | Logical grouping |
| Unclear navigation | Refactor hierarchy | Progressive disclosure |

## Open Decisions Log

Track decisions requiring user input:

### Decision 1: Subagent Location ✅ RESOLVED
**Options**: .claude/agents/ (centralized) vs alongside code
**Decision**: .claude/agents/ (centralized, discoverable)
**Date**: 2025-12-11

### Decision 2: ras_skills/ Merger ✅ RESOLVED
**Options**: Keep separate vs merge with .claude/skills/
**Decision**: Keep separate (library vs domain distinction clear)
**Date**: 2025-12-11

### Decision 3: Model Hard-Coding ✅ RESOLVED
**Options**: Hard-code vs let main agent decide
**Decision**: Hard-code (cost predictability, Sonnet for specialists)
**Date**: 2025-12-11

### Decision 4: AGENTS.md Timeline ✅ RESOLVED
**Options**: Remove immediately vs 1 release cycle vs indefinite
**Decision**: 1 release cycle with deprecation notice
**Date**: 2025-12-11

---

**Status**: Active governance framework
**Review Cycle**: Quarterly
**Last Updated**: 2025-12-11
