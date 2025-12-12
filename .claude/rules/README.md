# Rules - Topic-Specific Guidance

This directory contains modular rules that Claude Code automatically loads when relevant to the current task.

## Organization

### python/
Language-specific patterns for ras-commander development:
- `static-classes.md` - RasCmdr, HdfBase patterns, why no instantiation
- `decorators.md` - @log_call, @standardize_input, custom decorators
- `path-handling.md` - pathlib.Path patterns, Windows compatibility
- `error-handling.md` - Logging, exceptions, LoggingConfig
- `naming-conventions.md` - snake_case, PascalCase, approved abbreviations
- `import-patterns.md` - Flexibility pattern for dev vs installed package

### hec-ras/
Domain-specific knowledge:
- `execution.md` - compute_plan(), parallel modes, stream_callback
- `geometry.md` - Fixed-width parsing, bank station interpolation, 450-point limit
- `hdf-files.md` - Result extraction, steady vs unsteady detection
- `dss-files.md` - Boundary conditions, Java bridge, lazy loading
- `remote.md` - Worker patterns, Session ID=2, Group Policy requirements
- `usgs.md` - Gauge workflows, NWIS access, validation metrics
- `precipitation.md` - AORC workflows, Atlas 14 integration

### testing/
Testing approaches:
- `tdd-approach.md` - Test with real HEC-RAS examples, not mocks
- `example-projects.md` - RasExamples.extract_project() workflows
- `environment-management.md` - Virtual environment setup: uv for agents, Anaconda for notebooks (rascmdr_local/rascmdr_pip)

### documentation/
Documentation standards:
- `hierarchical-knowledge-best-practices.md` - Subagent/skill patterns, avoiding duplication
- `mkdocs-config.md` - Notebook integration, symlink handling
- `notebook-standards.md` - Title requirements, execution policy

## How Rules Work

1. **Auto-Loaded**: Claude loads rules based on file patterns and task keywords
2. **Scoped**: Rules apply when working in relevant code areas
3. **Non-Blocking**: Rules provide guidance but don't prevent actions
4. **Composable**: Multiple rules can apply simultaneously

## Creating New Rules

1. Choose appropriate subdirectory (python/, hec-ras/, testing/, documentation/)
2. Create markdown file with clear, focused guidance
3. Keep files 50-200 lines (one specific topic per file)
4. Use YAML frontmatter for path-specific targeting (optional):

```yaml
---
paths: ras_commander/remote/**/*.py
---

# Remote Execution Patterns
[Rule content specific to remote execution code]
```

## Example: Path-Specific Rule

```yaml
---
paths: ras_commander/hdf/**/*.py
---

# HDF File Operations

When working with HDF files:
- Always use h5py context managers (with statements)
- Check dataset existence before reading
- Handle both steady and unsteady result types
- Use is_steady_plan() to detect plan type
```

## Guidelines

- **One topic per file**: Don't mix unrelated patterns
- **Be specific**: Include code examples
- **Stay current**: Update rules when patterns change
- **Test guidance**: Ensure recommendations work in practice

## See Also

- [Hierarchical Knowledge Approach](../../feature_dev_notes/Hierarchical_Knowledge_Approach/)
- Root CLAUDE.md for strategic vision
- Subpackage CLAUDE.md files for tactical context
