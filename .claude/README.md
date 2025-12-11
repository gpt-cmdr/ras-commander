# .claude/ - Claude Framework Configuration

This directory contains Claude Code's memory and skills configuration using the official Claude framework.

## Structure

- **`rules/`** - Topic-specific guidance (auto-loaded by Claude)
- **`skills/`** - Library workflow skills (dynamic discovery)
- **`subagents/`** - Specialist agent definitions

## How It Works

### Hierarchical Memory Loading

Claude Code automatically loads context based on your working directory:

```
When working in: ras_commander/remote/

Automatic context loading:
1. /CLAUDE.md (root - strategic vision)
2. /ras_commander/CLAUDE.md (library - tactical patterns)
3. /ras_commander/remote/CLAUDE.md (subpackage - implementation details)
4. /.claude/rules/** (all relevant rules files)
```

### Rules (Auto-Loaded)

Files in `.claude/rules/` are automatically loaded when relevant to the task. Organize by topic:

- **`python/`** - Language-specific patterns (static classes, decorators, error handling)
- **`hec-ras/`** - Domain knowledge (execution, geometry, HDF files, remote)
- **`testing/`** - Testing approaches (TDD with HEC-RAS examples)
- **`documentation/`** - Documentation standards (MkDocs, notebooks)

### Skills (Dynamic Discovery)

Skills in `.claude/skills/` are discovered dynamically based on task descriptions. Each skill is a folder with:
- `SKILL.md` - Main instructions with YAML frontmatter
- `reference/` - Detailed docs (loaded on-demand)
- `examples/` - Usage demonstrations
- `scripts/` - Executable utilities

### Subagents (Explicit Delegation)

Subagent definitions in `.claude/subagents/` specify specialist agents for specific domains:
- HDF file analysis
- Geometry parsing
- Remote execution
- USGS data integration

## Content Guidelines

| Level | Purpose | Size Target | Auto-Loaded? |
|-------|---------|-------------|--------------|
| Root CLAUDE.md | Strategic vision | < 200 lines | Always |
| Subpackage CLAUDE.md | Tactical patterns | < 150 lines | When in directory |
| .claude/rules/*.md | Detailed procedures | 50-200 lines | By relevance |
| .claude/skills/*/SKILL.md | Workflow navigation | < 500 lines | When discovered |

## See Also

- [Hierarchical Knowledge Approach](../feature_dev_notes/Hierarchical_Knowledge_Approach/)
- [Claude Skills Documentation](https://claude.com/skills)
- Root CLAUDE.md for repository overview
