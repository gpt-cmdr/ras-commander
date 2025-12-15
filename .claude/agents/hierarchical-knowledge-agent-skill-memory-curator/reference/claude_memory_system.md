# Claude Code Memory System - Research Summary

**Source**: claude-code-guide agent research
**Date**: 2025-12-11
**Agent**: aba6c33
**Reference**: https://code.claude.com/docs/en/memory

## Executive Summary

Claude Code uses a **4-level hierarchical context loading system** with automatic discovery of nested CLAUDE.md files. The key insight: **nested files load on-demand when working in subdirectories**, enabling progressive disclosure and token budget optimization.

## Hierarchical Context Loading

### 4-Level Precedence (Highest to Lowest)

| Priority | Memory Type | Location | Scope | ras-commander Status |
|----------|------------|----------|-------|---------------------|
| 1 (Highest) | Enterprise policy | `/Library/Application Support/ClaudeCode/CLAUDE.md` (macOS) | Organization-wide | N/A |
| 2 | Project memory | `./CLAUDE.md` or `./.claude/CLAUDE.md` | Project-wide | ✓ EXISTS (33KB) |
| 3 | Project rules | `./.claude/rules/*.md` | Modular team guidance | ❌ NOT IMPLEMENTED |
| 4 | User memory | `~/.claude/CLAUDE.md` | Personal preferences | User-specific |
| 4b | Project local | `./CLAUDE.local.md` | Personal project settings | Auto-gitignored |

### Discovery Mechanism

**Recursive Upward Traversal**:
```
Working directory: ras-commander/ras_commander/remote/

Loads (in order):
1. /ras-commander/CLAUDE.md (root)
2. /ras-commander/ras_commander/CLAUDE.md (if exists)
3. /ras-commander/ras_commander/remote/CLAUDE.md (if exists)
```

**Key Feature**: Nested files load **on-demand** when Claude reads files in those subtrees, not at startup!

## Modular Rules Directory

**Recommended Structure**:
```
.claude/
├── CLAUDE.md              # Main instructions
└── rules/
    ├── code-style.md
    ├── testing.md
    ├── security.md
    ├── hec-ras/
    │   ├── geometry.md
    │   ├── hdf-files.md
    │   └── execution.md
    └── examples/
        └── notebook-style.md
```

**All `.md` files in `.claude/rules/` automatically loaded** with same priority as project CLAUDE.md.

### Path-Specific Rules (YAML Frontmatter)

```yaml
---
paths: ras_commander/**/*.py
---

# Core Library Development Guidelines
- All classes use static methods with @log_call
- Use pathlib.Path for all path operations
```

**Glob patterns supported**:
- `**/*.py` - All Python files
- `src/**/*` - All files under src/
- `{src,lib}/**/*.py` - Multiple directories
- `ras_commander/**/*.{py,pyi}` - Multiple extensions

## File Imports (@syntax)

**Include external documentation**:
```markdown
# Project Overview
@README.md

# API Reference
@ras_commander/README.md

# Git Workflow
@docs/git-instructions.md

# User Preferences
@~/.claude/my-project-instructions.md
```

**Constraints**:
- Relative and absolute paths supported
- Not evaluated inside code blocks
- Recursive imports allowed (max depth: 5 hops)
- View loaded memory with `/memory` command

## Token Limits & Best Practices

### No Hard Token Limits Documented

**Focus on organization instead**:
1. **Be specific**: "Use 2-space indentation" > "Format code properly"
2. **Use structure**: Bullet points under descriptive markdown headings
3. **Review periodically**: Update as project evolves

**Recommended file sizes**:
- Individual rules: 50-200 lines each
- Total loaded context: Stay under 25,000 tokens (safe zone)
- Use nested files for on-demand loading of detailed content

## Subagent Context Inheritance

**Key Characteristics**:
- Each subagent has **its own context window** (separate from main conversation)
- Subagents **start with clean slate** each invocation
- They inherit all memory files (CLAUDE.md) in scope
- They do NOT inherit main conversation history

**Subagent Configuration with Skills**:
```yaml
---
name: hdf-expert
description: Expert in HEC-RAS HDF file analysis
tools: Read, Grep, Bash
skills: hdf-analysis  # Auto-load skill files!
---
```

## Practical Recommendations for ras-commander

### Strategy 1: Refactor Current CLAUDE.md

**Current Problem**: 33KB monolithic file
**Solution**: Extract to hierarchical structure

```
Before:
/CLAUDE.md (33KB) - Everything mixed together

After:
/CLAUDE.md (12KB) - Strategic overview only
/ras_commander/.claude/CLAUDE.md (18KB) - Core library patterns
/ras_commander/remote/.claude/CLAUDE.md (6KB) - Remote execution
/examples/.claude/CLAUDE.md (8KB) - Notebook conventions
```

### Strategy 2: Implement Modular Rules Directory

**Create `.claude/rules/` structure**:
```
.claude/
├── CLAUDE.md (main, import-based)
└── rules/
    ├── architecture/
    │   ├── class-patterns.md (static classes, decorators)
    │   ├── error-handling.md (logging, exceptions)
    │   └── path-handling.md (pathlib patterns)
    ├── development/
    │   ├── testing.md (TDD with HEC-RAS examples)
    │   ├── naming.md (snake_case, abbreviations)
    │   └── documentation.md (docstring standards)
    ├── hec-ras/
    │   ├── project-management.md
    │   ├── execution.md
    │   ├── file-operations.md
    │   ├── hdf-processing.md
    │   ├── geometry-parsing.md
    │   └── remote-execution.md
    └── notebooks/
        └── style-guide.md
```

**Each file**: 50-150 lines, path-specific YAML frontmatter

**Root CLAUDE.md becomes**:
```markdown
# ras-commander Project Memory

## Quick Links
@AGENTS.md (quick-start guide)
@ras_commander/AGENTS.md (library API)

## Architecture
@.claude/rules/architecture/class-patterns.md

## Development
@.claude/rules/development/testing.md
@.claude/rules/development/naming.md

## HEC-RAS Specifics
@.claude/rules/hec-ras/execution.md
```

### Strategy 3: Nested Context for Subpackages

**Create on-demand context files**:
```
ras_commander/remote/.claude/CLAUDE.md
ras_commander/hdf/.claude/CLAUDE.md
ras_commander/geom/.claude/CLAUDE.md
```

**These load automatically** when Claude reads files in those directories!

### Strategy 4: Path-Specific Rules

**Example - Remote Execution**:
```yaml
---
paths: ras_commander/remote/**/*.py
---

# Remote Execution Guidelines
- All workers must inherit from RasWorker base class
- Use lazy loading for optional dependencies (paramiko, docker)
- Document network requirements in docstrings
- Session ID configuration critical (never use system account)
```

**Example - Notebooks**:
```yaml
---
paths: examples/**/*.ipynb
---

# Notebook Development Guidelines
- All notebooks must have H1 title in first cell
- Include data source references
- Test notebooks before committing with clean kernel
- Prefer cleaned notebooks over raw execution outputs
```

## Migration Plan for ras-commander

### Phase 1: Modular Rules (Week 1-2)

1. Create `.claude/rules/` directory structure
2. Extract content from root CLAUDE.md into topic-specific files
3. Update root CLAUDE.md to use `@imports`
4. Test with `/memory` command to verify loading

### Phase 2: Nested Context (Week 3-4)

1. Create `ras_commander/.claude/CLAUDE.md` with core patterns
2. Create subpackage-specific files (remote/, hdf/, geom/)
3. Test on-demand loading by working in subdirectories
4. Verify no duplication between levels

### Phase 3: Path-Specific Rules (Week 5-6)

1. Add YAML frontmatter to rules files
2. Define glob patterns for different file types
3. Test that correct rules apply in correct locations
4. Measure token savings with `/memory`

## Key Takeaways

1. **Hierarchical loading is automatic** - Just place CLAUDE.md in subdirectories
2. **On-demand context** - Nested files load when working in those areas (token savings!)
3. **Modular rules** - `.claude/rules/` is the recommended organization pattern
4. **Path-specific context** - YAML frontmatter targets specific file patterns
5. **No hard token limits** - Focus on organization and relevance
6. **Subagents get clean slate** - They inherit memory files, not conversation history
7. **Import syntax** - Use `@path` to include documentation without duplication

## Testing Recommendations

**Validate hierarchical loading**:
```bash
# Work in root
claude code  # Should load only root CLAUDE.md

# Work in subpackage
cd ras_commander/remote
claude code  # Should load root + ras_commander + remote CLAUDE.md

# Verify loaded context
/memory
```

**Monitor token usage**:
- Use `/memory` to see what's loaded
- Prune unnecessary content
- Split large files if context feels cluttered

---

**Bottom Line**: Claude Code's memory system is **designed for hierarchical knowledge**. We just need to organize ras-commander's documentation to match the system's capabilities.
