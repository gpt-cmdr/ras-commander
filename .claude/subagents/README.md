# Subagents - Specialist Agent Definitions

This directory contains definitions for specialist subagents that handle specific domains within ras-commander workflows.

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
└─ Spawns specialist subagents when needed

Specialist Subagents (Sonnet)
├─ Domain expertise (HDF, geometry, remote, USGS)
├─ Inherit: Hierarchical CLAUDE.md chain
├─ Use: Library skills + domain skills
└─ Spawn task subagents (Haiku) for quick ops

Task Subagents (Haiku)
├─ Fast, focused operations
├─ Single-file reads, simple transforms
└─ Cost-effective bulk operations
```

## Implemented Subagents

1. **claude-code-guide** - Claude Code best practices and configuration (Haiku)
2. **hierarchical-knowledge-agent-skill-memory-curator** - Memory system curation (Haiku)
3. **remote-executor** - Distributed HEC-RAS execution across workers (Sonnet)

## Recommended Future Subagents

1. **hdf-analyst** - HEC-RAS HDF file analysis and result extraction
2. **geometry-parser** - Geometry file parsing and modification
3. **usgs-integrator** - USGS gauge data integration and validation
4. **precipitation-specialist** - AORC and Atlas 14 workflows
5. **quality-assurance** - RasFixit geometry repair and validation
6. **documentation-generator** - Example notebooks and API docs

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

For quick file reads or simple operations, you can spawn Haiku task subagents.
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
- **Hard-code model**: Sonnet for specialists, Haiku for tasks (cost predictability)
- **Minimal tool sets**: Only grant necessary permissions
- **Clear triggers**: Help main agent know when to delegate
- **Trust context inheritance**: Don't duplicate CLAUDE.md content

## Delegation Decision Tree

Main agent uses this logic to decide when to spawn subagents:

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
3. **Parallel execution**: Multiple subagents work concurrently
4. **Clear boundaries**: Each subagent has defined scope

## See Also

- [Architecture Clarity](../../feature_dev_notes/Hierarchical_Knowledge_Approach/ARCHITECTURE_CLARITY.md)
- [Claude Skills Framework](../../feature_dev_notes/Hierarchical_Knowledge_Approach/research/claude_skills_framework.md)
- Root CLAUDE.md for delegation patterns
