# Subagents - Specialist Agent Definitions

This directory contains definitions for specialist agents that handle specific domains within ras-commander workflows.

## What are Subagents?

**Subagents** are AI assistants spawned by the main agent (Opus orchestrator) to handle specialized tasks. They:
- **Inherit context automatically** via hierarchical CLAUDE.md files
- **Use specific models** optimized for their role (Sonnet for specialists, Haiku for quick tasks)
- **Access skills** just like the main agent
- **Work in focused directories** to get relevant context

## Three-Tier Architecture

```
Main Agent (Opus)
├─ High-level planning and delegation
├─ Loads: Root CLAUDE.md + .claude/rules/**
└─ Spawns specialist agents when needed

Specialist Subagents (Sonnet)
├─ Domain expertise (HDF, geometry, remote, USGS)
├─ Inherit: Hierarchical CLAUDE.md chain
├─ Use: Library skills + domain skills
└─ Spawn task agents (Haiku) for quick ops

Task Subagents (Haiku)
├─ Fast, focused operations
├─ Single-file reads, simple transforms
└─ Cost-effective bulk operations
```

## Implemented Subagents

### Domain Specialists (Sonnet)
- **hdf-analyst** - HDF file analysis, results extraction
- **geometry-parser** - Geometry file parsing, cross-section analysis
- **usgs-integrator** - USGS gauge data integration and validation
- **remote-executor** - Distributed HEC-RAS execution
- **precipitation-specialist** - AORC and Atlas 14 workflows
- **quality-assurance** - RasFixit geometry repair
- **win32com-automation-expert** - COM automation, GUI interaction
- **ras-commander-api-expert** - API integration, dataframe structures, spawns explore subagents

### Knowledge Management (Opus)
- **hierarchical-knowledge-agent-skill-memory-curator** - Knowledge organization, structural reasoning

### Utility Agents (Sonnet)
- **documentation-generator** - Example notebooks and API docs
- **example-notebook-librarian** - Notebook management
- **python-environment-manager** - Environment setup
- **git-operations** - Git workflows
- **notebook-runner** - Notebook execution

### Review Agents (Haiku)
- **notebook-output-auditor** - Review notebook outputs for errors
- **notebook-anomaly-spotter** - Detect anomalies in results
- **conversation-index-scanner** - Pattern matching in conversations
- **slash-command-finder** - File pattern searching
- **claude-code-guide** - Documentation lookup
- **hec-hms-documentation-scout** - Documentation review

### Analysis Agents (Mixed)
- **conversation-deep-researcher** - Deep analysis (Opus)
- **best-practice-extractor** - Pattern extraction (Sonnet)
- **blocker-detector** - Problem identification (Sonnet)

## Subagent Definition Format

```yaml
---
name: hdf-analyst
description: |
  Expert in HEC-RAS HDF file analysis. Extracts results, handles both steady
  and unsteady plans, processes breach data, and generates hydraulic tables.
  Use when analyzing HDF files, extracting water surface elevations, or
  processing model results.
model: sonnet
tools: Read, Grep, Bash, Write
skills: extracting-hecras-results
working_directory: ras_commander/hdf
---

# HDF Analyst Subagent

You are an expert in HEC-RAS HDF file operations.

## Automatic Context Inheritance

When working in `ras_commander/hdf/`, you automatically inherit:
1. Root CLAUDE.md (strategic vision)
2. ras_commander/CLAUDE.md (library patterns)
3. ras_commander/hdf/CLAUDE.md (HDF implementation details)
4. .claude/rules/hec-ras/hdf-files.md (detailed HDF guidance)

## Your Expertise

- HdfResultsPlan API for steady and unsteady results
- Conditional workflows (detect steady vs unsteady)
- Breach results extraction
- Hydraulic table generation from preprocessed geometry

## Available Skills

You have access to the `extracting-hecras-results` skill which provides:
- Complete API reference
- Steady vs unsteady detection patterns
- Example workflows
- Common pitfalls and solutions

## Delegation

For quick file reads or simple operations, you can spawn Haiku task agents.
```

## Context Inheritance Example

When `geometry-parser` subagent works in `ras_commander/geom/`:

```
Automatic Context Loading:
1. /CLAUDE.md (root)
   → "Use static classes, test with HEC-RAS examples"

2. /ras_commander/CLAUDE.md (library)
   → "Module organization, common patterns"

3. /ras_commander/geom/CLAUDE.md (geometry)
   → "Fixed-width parsing, bank station interpolation, 450-point limit"

Result: Subagent has full context WITHOUT manual passing!
```

## Creating Subagent Definitions

1. **Choose domain**: Identify specialized area (HDF, geometry, remote, etc.)
2. **Select model**: Sonnet for specialists, Haiku for simple tasks
3. **Specify tools**: Limit to necessary tools for security
4. **Assign skills**: Which skills should auto-load?
5. **Set working directory**: Where should the subagent operate?
6. **Write description**: Include trigger keywords for delegation

## Guidelines

- **One domain per subagent**: Don't mix unrelated expertise
- **Specify default model**: See Model Selection Framework below
- **Minimal tool sets**: Only grant necessary permissions
- **Clear triggers**: Help main agent know when to delegate
- **Trust context inheritance**: Don't duplicate CLAUDE.md content

## Model Selection Framework

### Model Capabilities

| Model | Intelligence | Speed | Cost | Best For |
|-------|-------------|-------|------|----------|
| **Opus 4.5** | Highest | Slower | $$$ | Complex reasoning, architecture, multi-domain analysis |
| **Sonnet 4.5** | High | Medium | $$ | Domain specialists, code generation, structured analysis |
| **Haiku 4.5** | Moderate | Fast | $ | Long context review, pattern matching, log analysis |

### Model Assignment by Task Type

**Use Haiku** for:
- Reviewing notebook outputs for errors/anomalies
- Scanning logs and compute messages
- Pattern matching in large files
- Documentation lookup
- Simple file scanning and indexing

**Use Sonnet** for:
- Domain specialists (HDF, geometry, USGS, remote execution)
- Code generation and modification
- Multi-step workflows with clear instructions
- Analysis requiring domain knowledge
- Documentation generation

**Use Opus** for:
- Complex multi-domain reasoning
- Architecture decisions
- Tasks where Sonnet struggled (escalation)
- Orchestration requiring full context
- Novel problem-solving

### Subagent Model Assignments

| Subagent | Default | Rationale |
|----------|---------|-----------|
| **hdf-analyst** | Sonnet | Domain specialist, structured HDF analysis |
| **geometry-parser** | Sonnet | Domain specialist, fixed-width parsing expertise |
| **usgs-integrator** | Sonnet | Domain specialist, multi-step workflows |
| **remote-executor** | Sonnet | Domain specialist, complex configuration |
| **quality-assurance** | Sonnet | Domain specialist, RasFixit patterns |
| **precipitation-specialist** | Sonnet | Domain specialist, AORC/Atlas 14 workflows |
| **documentation-generator** | Sonnet | Content generation, code examples |
| **example-notebook-librarian** | Sonnet | Notebook management, modifications |
| **python-environment-manager** | Sonnet | Environment setup, troubleshooting |
| **git-operations** | Sonnet | Git workflows, conflict resolution |
| **win32com-automation-expert** | Sonnet | COM automation, GUI interaction |
| **ras-commander-api-expert** | Sonnet | API integration, dataframe structures, spawns Haiku subagents |
| **hierarchical-knowledge-agent-skill-memory-curator** | Opus | Knowledge organization, complex reasoning about structure |
| **notebook-output-auditor** | Haiku | Long context review, output validation |
| **notebook-anomaly-spotter** | Haiku | Pattern detection in outputs |
| **notebook-runner** | Sonnet | Execution management, error handling |
| **conversation-index-scanner** | Haiku | Pattern matching in conversations |
| **slash-command-finder** | Haiku | File pattern searching |
| **claude-code-guide** | Haiku | Documentation lookup |
| **hec-hms-documentation-scout** | Haiku | Documentation review |
| **best-practice-extractor** | Sonnet | Analysis, pattern extraction |
| **blocker-detector** | Sonnet | Analysis, problem identification |
| **conversation-deep-researcher** | Opus | Deep analysis, complex reasoning |

### Escalation Pattern

**Orchestrator should escalate models when**:

1. **Subagent doesn't understand task** → Re-invoke with clearer instructions + higher model
2. **Output is incomplete or wrong** → Escalate Haiku → Sonnet → Opus
3. **Task is more complex than expected** → Use `model="opus"` override
4. **Multiple domains involved** → Consider handling directly as orchestrator

**Example escalation**:
```python
# First attempt with default (Haiku)
result = Task(subagent_type="notebook-output-auditor", prompt="Review outputs...")

# If result is insufficient, escalate to Sonnet
result = Task(subagent_type="notebook-output-auditor", model="sonnet",
              prompt="[More detailed instructions]...")

# For complex analysis, use Opus
result = Task(subagent_type="notebook-output-auditor", model="opus",
              prompt="[Comprehensive analysis with reasoning required]...")
```

### Cost Optimization

**Optimize by defaulting to cheaper models**:
- Long context tasks → Haiku (75x cheaper than Opus)
- Routine domain work → Sonnet (10x cheaper than Opus)
- Complex reasoning → Opus (use sparingly)

**Batch similar tasks**:
- Multiple file reviews → Single Haiku agent with file list
- Multiple domain analyses → Parallel Sonnet agents

## Critical: Markdown Output Pattern

**All subagents MUST write markdown files and return file paths to the main agent.**

```
Subagent receives task
    ↓
Subagent performs work
    ↓
Subagent writes markdown to .claude/outputs/{subagent}/{date}-{task}.md
    ↓
Subagent returns file path to main agent
    ↓
Main agent reads file as needed
```

**Why This Pattern**:
- **Persistence**: Text returns vanish when session ends; files survive
- **Filterable**: Main agent reads only what's needed
- **Consolidation**: Hierarchical knowledge agent organizes and prunes
- **Audit Trail**: All work products traceable and reviewable
- **Non-Destructive**: Outdated files move to `.old/`, never auto-deleted

**Output Location**: `.claude/outputs/{subagent-name}/`

**File Naming**: `{date}-{subagent}-{task-description}.md`

**Example**:
```
.claude/outputs/hdf-analyst/2025-12-15-breach-results-analysis.md
```

**See**: `.claude/rules/subagent-output-pattern.md` for complete documentation

## Delegation Decision Tree

Main agent uses this logic to decide when to spawn agents:

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

## Benefits

1. **Cost optimization**: Use expensive models only where needed
2. **Automatic specialization**: Folder context = domain expertise
3. **Parallel execution**: Multiple agents work concurrently
4. **Clear boundaries**: Each subagent has defined scope

## See Also

- [Architecture Clarity](../../feature_dev_notes/Hierarchical_Knowledge_Approach/ARCHITECTURE_CLARITY.md)
- [Claude Skills Framework](../../feature_dev_notes/Hierarchical_Knowledge_Approach/research/claude_skills_framework.md)
- Root CLAUDE.md for delegation patterns
