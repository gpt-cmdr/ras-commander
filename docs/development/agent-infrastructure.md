# Agent Infrastructure & Hierarchical Knowledge

ras-commander implements a sophisticated **hierarchical knowledge system** that enables AI agents to efficiently work with the codebase. This infrastructure includes specialized subagents, reusable skills, and slash commands for common workflows.

## Overview

The agent infrastructure is designed around three core concepts:

1. **Hierarchical Knowledge Organization** - Progressive disclosure of context through CLAUDE.md files
2. **Specialist Subagents** - Domain-specific AI assistants for HDF analysis, geometry parsing, etc.
3. **Reusable Skills** - Common workflow patterns that can be invoked by name

This architecture enables:

- **Cost optimization** - Use expensive models only where needed
- **Automatic specialization** - Folder context provides domain expertise
- **Efficient context loading** - Progressive disclosure prevents token waste
- **Consistent workflows** - Standardized patterns across the codebase

## Hierarchical Knowledge System

### Progressive Disclosure Architecture

The repository uses a **hierarchical CLAUDE.md structure** for progressive disclosure of context:

```
Root CLAUDE.md (Strategic)
├─ High-level philosophy and patterns
├─ Quick reference for common operations
└─ Pointers to detailed rules

.claude/rules/ (Tactical)
├─ python/ - Language patterns (static classes, decorators, paths)
├─ hec-ras/ - Domain knowledge (execution, geometry, HDF)
├─ testing/ - Testing approaches (TDD, environments)
└─ documentation/ - Doc standards (notebooks, mkdocs)

Subpackage CLAUDE.md (Implementation)
├─ ras_commander/CLAUDE.md - Library API patterns
├─ ras_commander/hdf/CLAUDE.md - HDF workflows
├─ ras_commander/remote/CLAUDE.md - Remote execution
└─ ras_commander/usgs/CLAUDE.md - USGS integration

AGENTS.md (Technical Details)
└─ Implementation-specific patterns and edge cases
```

### Context Inheritance

When a subagent works in a specific directory, it automatically inherits the full context chain:

**Example: Geometry Parser in `ras_commander/geom/`**

```
Automatic Context Loading:
1. /CLAUDE.md (root)
   → "Use static classes, test with HEC-RAS examples"

2. /ras_commander/CLAUDE.md (library)
   → "Module organization, common patterns"

3. /ras_commander/geom/AGENTS.md (geometry)
   → "Fixed-width parsing, bank station interpolation, 450-point limit"

Result: Full context WITHOUT manual passing!
```

### Best Practices

The system follows strict **anti-duplication principles** documented in `.claude/rules/documentation/hierarchical-knowledge-best-practices.md`:

✅ **DO:**
- Point to existing primary sources (CLAUDE.md, AGENTS.md)
- Keep navigators lightweight (200-400 lines)
- Include critical warnings that MUST be visible
- Use single source of truth for all information

❌ **DON'T:**
- Duplicate API documentation from code docstrings
- Duplicate workflows from CLAUDE.md files
- Create reference/ folders with duplicated content
- Exceed 400 lines without strong justification

**Exception:** Two subagents (`hierarchical-knowledge-agent-skill-memory-curator` and `claude-code-guide`) are permitted to have reference/ folders containing meta-knowledge and cached external documentation.

## Specialist Subagents

Subagents are AI assistants spawned by the main agent to handle specialized tasks.

### Three-Tier Architecture

```
Main Agent (Claude Opus)
├─ High-level planning and delegation
├─ Loads: Root CLAUDE.md + .claude/rules/**
└─ Spawns specialist subagents when needed

Specialist Subagents (Claude Sonnet)
├─ Domain expertise (HDF, geometry, remote, USGS)
├─ Inherit: Hierarchical CLAUDE.md chain
├─ Use: Library skills + domain skills
└─ Spawn task subagents (Haiku) for quick ops

Task Subagents (Claude Haiku)
├─ Fast, focused operations
├─ Single-file reads, simple transforms
└─ Cost-effective bulk operations
```

### Implemented Subagents

| Subagent | Model | Domain | Skills |
|----------|-------|--------|--------|
| **claude-code-guide** | Haiku | Claude Code best practices | - |
| **hdf-analyst** | Sonnet | HDF file analysis | extracting-hecras-results |
| **geometry-parser** | Sonnet | Geometry file parsing | parsing-hecras-geometry |
| **usgs-integrator** | Sonnet | USGS gauge data | integrating-usgs-gauges |
| **precipitation-specialist** | Sonnet | AORC & Atlas 14 | analyzing-aorc-precipitation |
| **quality-assurance** | Sonnet | RasFixit validation | repairing-geometry-issues |
| **remote-executor** | Sonnet | Distributed execution | executing-remote-plans |
| **documentation-generator** | Sonnet | Notebooks & API docs | - |
| **git-operations** | Haiku | Version control | using-git-worktrees |
| **hierarchical-knowledge-curator** | Haiku | Memory system curation | - |

### Subagent Definition Format

Subagents are defined in `.claude/subagents/{name}.md` with YAML frontmatter:

```yaml
---
name: hdf-analyst
description: |
  Expert in HEC-RAS HDF file analysis. Extracts results, handles both steady
  and unsteady plans, processes breach data, and generates hydraulic tables.
  Use when analyzing HDF files, extracting water surface elevations, or
  processing model results.
model: sonnet
tools: [Read, Grep, Bash, Write]
skills: [extracting-hecras-results]
working_directory: ras_commander/hdf
---

# HDF Analyst Subagent

[Lightweight navigator content pointing to primary sources...]
```

### Delegation Decision Tree

The main agent uses this logic to spawn subagents:

```
User Request
├─ HDF result extraction? → hdf-analyst (Sonnet)
│   └─ Uses: extracting-hecras-results skill
├─ Geometry file parsing? → geometry-parser (Sonnet)
│   └─ Uses: parsing-hecras-geometry skill
├─ USGS data integration? → usgs-integrator (Sonnet)
│   └─ Uses: integrating-usgs-gauges skill
├─ Simple file read/grep? → quick-reader (Haiku)
│   └─ Fast, cost-effective
└─ Complex orchestration? → Handle directly (Opus)
    └─ Multi-domain coordination
```

## Library Skills

Skills are reusable workflow patterns that both agents and subagents can invoke.

### Skill Types

| Type | Location | Purpose | Example |
|------|----------|---------|---------|
| **Library Skills** | `.claude/skills/` | How to use ras-commander | `executing-hecras-plans` |
| **Domain Skills** | `ras_skills/` | Production automation | `historical-flood-reconstruction` |

### Implemented Library Skills

**Core Operations:**
1. **executing-hecras-plans** - RasCmdr.compute_plan(), parallel execution
2. **extracting-hecras-results** - HdfResultsPlan API, steady vs unsteady
3. **parsing-hecras-geometry** - RasGeometry, fixed-width parsing

**Advanced Features:**
4. **integrating-usgs-gauges** - Complete USGS workflow
5. **analyzing-aorc-precipitation** - AORC grid extraction
6. **repairing-geometry-issues** - RasFixit validation loops

**Specialized:**
7. **executing-remote-plans** - PsExec, Docker, SSH workers
8. **reading-dss-boundary-data** - RasDss API, HEC-DSS files
9. **using-git-worktrees** - Isolated development environments

### Skill Structure

Each skill uses progressive disclosure:

```
executing-hecras-plans/
├── SKILL.md              # Main instructions (< 500 lines)
├── reference/            # Detailed docs (loaded on-demand)
│   ├── compute_plan.md
│   ├── parallel.md
│   └── callbacks.md
├── examples/             # Working demonstrations
│   ├── basic.md
│   └── advanced.md
└── scripts/              # Executable utilities
    ├── validate_plan.py
    └── setup_workers.py
```

### Skill Discovery

Skills are discovered through **trigger-rich descriptions** in YAML frontmatter:

```yaml
---
name: executing-hecras-plans
description: |
  Executes HEC-RAS plans using RasCmdr.compute_plan(), handles parallel
  execution across multiple plans, and manages destination folders. Use when
  running HEC-RAS simulations, computing plans, executing models, or setting
  up parallel computation workflows.
---
```

Key terms like "execute", "compute", "parallel", "HEC-RAS", "simulation" help Claude discover when to invoke this skill.

## Slash Commands

Slash commands provide quick access to common agent workflows.

### Available Commands

The repository includes four agent coordination slash commands in `.claude/commands/`:

#### `/agent-cleanfiles`

Clean up task files non-destructively:
- Moves outdated/unneeded outputs to `.old`
- Lists temporary files for user approval
- Consults organizational plan for recommendations

```bash
# Usage in Claude Code
/agent-cleanfiles
```

#### `/agent-taskupdate`

Review and plan task progress:
- Assesses current progress against task list
- Creates detailed continuation plan
- Reviews memory system state

```bash
/agent-taskupdate
```

#### `/agent-taskclose`

End conversation with proper closeout:
- Documents all information for future sessions
- Performs closeout actions
- Cleans up files before ending

```bash
/agent-taskclose
```

#### `/agent-engagesubagents`

Multi-agent coordination workflow:
- Lists relevant subagents for user approval
- Creates detailed execution plan
- Uses `agent_tasks/` for shared memory

```bash
/agent-engagesubagents
```

#### `/agent-crossrepo`

Cross-repository coordination workflow:
- Creates request files for sibling repositories
- Guides proper handoff documentation
- Enforces human-in-the-loop protocol

```bash
/agent-crossrepo
```

See [Cross-Repository Coordination](#cross-repository-coordination) for details.

### Creating Custom Slash Commands

Add new commands in `.claude/commands/{name}.md`:

```markdown
Brief description of what this command does and when to use it.
Can include detailed instructions that expand when invoked.
```

Commands are automatically discovered by Claude Code based on the filename.

## Memory System

For complex tasks spanning multiple sessions, ras-commander uses an **`agent_tasks/` memory system**.

### Memory Structure

```
agent_tasks/
├── .agent/
│   ├── STATE.md       # Current session state
│   ├── PROGRESS.md    # Historical progress log
│   └── BACKLOG.md     # Pending tasks
└── {task-name}.md     # Task-specific coordination file
```

### Session Protocol

**Every session start:**
- Read `agent_tasks/.agent/STATE.md`
- Read `agent_tasks/.agent/PROGRESS.md`
- Read `agent_tasks/.agent/BACKLOG.md`

**Every session end:**
- Update `STATE.md`
- Append to `PROGRESS.md`
- Update `BACKLOG.md`

This enables **passive coordination** between sessions without manual state management.

## Integration with LLM Forward Development

The agent infrastructure supports the **LLM Forward Development** philosophy:

### Core Principles

1. **Professional Responsibility First** - Safety, ethics, licensure paramount
2. **LLMs Forward (Not First)** - Technology accelerates, doesn't replace judgment
3. **Multi-Level Verifiability** - GUI review + visual outputs + code audit trails
4. **Human-in-the-Loop** - Multiple review pathways
5. **Domain Expertise Accelerated** - H&H knowledge → working code efficiently

### Agent-Assisted Workflows

✅ **Agents excel at:**
- Test with real HEC-RAS projects (`RasExamples.extract_project()`)
- Create reviewable projects with descriptive titles
- Generate visual outputs for verification
- Maintain audit trails (`@log_call` decorators)
- Enable multiple review pathways

❌ **Agents should NOT:**
- Use synthetic test data or mocks
- Create black-box implementations
- Skip professional review steps
- Generate code without verification paths

## Cross-Repository Coordination

ras-commander can coordinate with sibling repositories (e.g., hms-commander) through a **human-in-the-loop markdown-based protocol**.

### Architecture Principle: Agent-Layer Only

```
┌─────────────────────────────────────────────────────────────────┐
│                    AGENT COORDINATION LAYER                      │
│  ┌──────────────────┐         ┌──────────────────┐              │
│  │  ras-commander   │◄───────►│  hms-commander   │              │
│  │  AI Agent        │ markdown│  AI Agent        │              │
│  └────────┬─────────┘  files  └────────┬─────────┘              │
│           │                            │                         │
│           ▼                            ▼                         │
│  feature_dev_notes/           feature_dev_notes/                │
│  agent_tasks/                 agent_tasks/                      │
└─────────────────────────────────────────────────────────────────┘
                    │                    │
                    ▼                    ▼
         ┌─────────────────┐  ┌─────────────────┐
         │ HUMAN IN LOOP   │  │ HUMAN IN LOOP   │
         │ Review/Approve  │  │ Review/Approve  │
         └────────┬────────┘  └────────┬────────┘
                  │                    │
                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PYTHON API LAYER                            │
│  ┌──────────────────┐         ┌──────────────────┐              │
│  │  ras_commander/  │         │  hms_commander/  │              │
│  │  (independent)   │         │  (independent)   │              │
│  └──────────────────┘         └──────────────────┘              │
│           NO DIRECT CODE DEPENDENCIES                            │
└─────────────────────────────────────────────────────────────────┘
```

**Critical Principles:**

1. **Agent-Layer Only** - Cross-repo awareness exists only at the AI/documentation level, NOT in Python code
2. **Human-in-the-Loop Required** - Every handoff requires explicit human engagement
3. **Markdown-Based Communication** - All coordination through markdown files
4. **No Direct AI-to-AI Handoff** - Agents prepare documentation; humans trigger next steps
5. **API Independence** - Python APIs remain completely independent

### Coordination Locations

| Location | Use Case | Timeline |
|----------|----------|----------|
| `feature_dev_notes/cross-repo/` | Research, exploration, future ideas | Non-urgent |
| `agent_tasks/cross-repo/` | Implementation requests, immediate needs | Current work |

### Handoff Workflow

```
1. Agent A (ras-commander) identifies need involving sibling repo
                    │
                    ▼
2. Agent A writes markdown request file
   └─ feature_dev_notes/cross-repo/{date}_{topic}.md (research)
   └─ agent_tasks/cross-repo/{date}_{topic}.md (implementation)
                    │
                    ▼
3. HUMAN reviews request, decides to engage
                    │
                    ▼
4. Human opens hms-commander, provides request context
                    │
                    ▼
5. Agent B (hms-commander) reads request, implements/researches
                    │
                    ▼
6. Agent B writes response in markdown file
                    │
                    ▼
7. HUMAN reviews response
                    │
                    ▼
8. Human returns to ras-commander with response
                    │
                    ▼
9. Agent A integrates/tests with human oversight
```

### Slash Command

Use `/agent-crossrepo` to initiate cross-repo coordination:

```bash
/agent-crossrepo
```

This guides the agent through creating properly formatted request files.

### Sibling Repositories

| Repository | Local Path | Purpose |
|------------|------------|---------|
| ras-commander | `C:\GH\ras-commander` | HEC-RAS automation |
| hms-commander | `C:\GH\hms-commander` | HEC-HMS automation |

### Common Integration Points

When coordinating between HEC-RAS and HEC-HMS workflows:

- **DSS File Handoff** - HMS output → RAS boundary conditions
- **Spatial Matching** - HMS subbasin outlets → RAS cross sections
- **Time Series Alignment** - HMS interval → RAS computation interval
- **Validation Workflows** - Cross-model verification

## Best Practices

### For Subagent Creators

1. **One domain per subagent** - Don't mix unrelated expertise
2. **Hard-code model** - Sonnet for specialists, Haiku for tasks
3. **Minimal tool sets** - Only grant necessary permissions
4. **Clear triggers** - Help main agent know when to delegate
5. **Trust context inheritance** - Don't duplicate CLAUDE.md content

### For Skill Creators

1. **Identify workflow** - Multi-step process users frequently need
2. **Use gerund naming** - `executing-plans`, not `plan-executor`
3. **Progressive disclosure** - Main SKILL.md < 500 lines
4. **Trigger-rich descriptions** - Include discovery keywords
5. **Test with real projects** - Validate with actual HEC-RAS models

### For Documentation

1. **Single source of truth** - One authoritative location per concept
2. **Lightweight navigators** - Point to sources, don't duplicate
3. **Critical warnings visible** - Don't bury essential information
4. **No unauthorized duplicates** - Follow 2-exception rule strictly

## Benefits

The hierarchical knowledge system provides:

✅ **Cost Optimization**
- Use expensive models only where needed
- Progressive disclosure minimizes token usage
- Haiku for simple tasks, Sonnet for specialists

✅ **Automatic Specialization**
- Folder context = domain expertise
- No manual context passing required
- Consistent patterns across codebase

✅ **Efficient Maintenance**
- Update once in primary source
- No version drift from duplicates
- Clear authoritative documentation

✅ **Parallel Execution**
- Multiple subagents work concurrently
- Shared memory via `agent_tasks/`
- Clear boundaries prevent conflicts

✅ **Discoverability**
- Trigger-rich descriptions
- Natural language activation
- Progressive complexity

## See Also

- [LLM Forward Development](llm-development.md) - Development philosophy
- [Contributing Guide](contributing.md) - Contribution workflow
- [Architecture Overview](architecture.md) - System design
- `.claude/rules/documentation/hierarchical-knowledge-best-practices.md` - Detailed guidelines
- `.claude/subagents/README.md` - Subagent creation guide
- `.claude/skills/README.md` - Skill creation guide
- `agent_tasks/README.md` - Memory system documentation
- `agent_tasks/cross-repo/README.md` - Cross-repo implementation requests
- `feature_dev_notes/cross-repo/README.md` - Cross-repo research coordination

## References

- [Engineering with LLMs](https://engineeringwithllms.info) - LLM Forward framework
- [CLB Engineering Corporation](https://clbengineering.com/) - Framework origin
- Claude Skills Framework - Native skill system implementation
