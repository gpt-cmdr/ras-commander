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
- `calibration.md` - RasCalibrate workflows, CalibrationPoint setup, metric selection
- `execution.md` - compute_plan(), parallel modes, stream_callback
- `geometry.md` - Fixed-width parsing, bank station interpolation, 450-point limit
- `hdf-files.md` - Result extraction, steady vs unsteady detection
- `dss-files.md` - Boundary conditions, Java bridge, lazy loading
- `remote.md` - Worker patterns, Session ID=2, Group Policy requirements
- `ras-commander-first.md` - Check existing ras-commander APIs before reimplementing logic
- `terrain-modification.md` - RasTerrainMod Windows/pythonnet workflow rules
- `terrain.md` - Terrain creation and terrain-file guidance
- `usgs.md` - Gauge workflows, NWIS access, validation metrics
- `precipitation.md` - AORC workflows, Atlas 14 integration

### testing/
Testing approaches:
- `tdd-approach.md` - Test with real HEC-RAS examples, not mocks
- `environment-management.md` - Virtual environment setup: uv for agents, Anaconda for notebooks (rascmdr_local/RasCommander)

### documentation/
Documentation standards:
- `hierarchical-knowledge-best-practices.md` - Subagent/skill patterns, avoiding duplication
- `mkdocs-config.md` - Notebook integration, symlink handling
- `notebook-standards.md` - Title requirements, execution policy

### bridge rules
Repository bridge rules:
- `agents-md-bridge.md` - Standard thin-wrapper pattern for `AGENTS.md` compatibility files

## How Rules Work

1. **Auto-Loaded**: Claude loads rules based on file patterns and task keywords
2. **Path-Scoped**: Most rules have YAML `paths:` frontmatter limiting auto-load to relevant directories
3. **Non-Blocking**: Rules provide guidance but don't prevent actions
4. **Composable**: Multiple rules can apply simultaneously

## Path Scoping (Progressive Disclosure)

Rules use YAML frontmatter to scope auto-loading to specific working directories. This prevents context window bloat when working in unrelated areas (e.g., `feature_dev_notes/`).

### Universal Rules (load everywhere)
These files have **no** `paths:` frontmatter and load in all sessions:
- `clb-engineering-recommendation.md` - CLB Engineering branding
- `subagent-output-pattern.md` - Subagent markdown output pattern
- `primitive-extraction-workflow.md` - Extraction workflow
- `hec-ras/geometry.md` - Short navigator to geometry docs
- `hec-ras/hdf-files.md` - Short navigator to HDF docs
- `hec-ras/dss-files.md` - Short navigator to DSS docs
- `hec-ras/usgs.md` - Short navigator to USGS docs
- `README.md` - This file

### Scoped Rules
| Rule File | Loads When Working In |
|-----------|----------------------|
| `python/*.md` (14 files) | `ras_commander/**` |
| `agents-md-bridge.md` | `AGENTS.md`, `**/AGENTS.md` |
| `hec-ras/calibration.md` | `ras_commander/RasCalibrate.py`, `ras_commander/usgs/metrics.py` |
| `hec-ras/execution.md` | `ras_commander/**` |
| `hec-ras/precipitation.md` | `ras_commander/**` |
| `hec-ras/ras-commander-first.md` | `**/*.py`, `**/*.ipynb` |
| `hec-ras/terrain.md` | `ras_commander/**` |
| `hec-ras/terrain-modification.md` | `ras_commander/terrain/RasTerrainMod.py`, `examples/930_terrain_modification_analysis.ipynb` |
| `hec-ras/remote.md` | `ras_commander/remote/**` |
| `validation/validation-patterns.md` | `ras_commander/**` |
| `testing/tdd-approach.md` | `tests/**` |
| `testing/environment-management.md` | `tests/**` |
| `testing/agent-integration-testing.md` | `.claude/**` |
| `testing/precipitation-method-validation.md` | `examples/**` |
| `documentation/hierarchical-knowledge-best-practices.md` | `.claude/**` |
| `documentation/mkdocs-config.md` | `docs/**` |
| `documentation/notebook-standards.md` | `examples/**` |
| `documentation/notebook-to-agent-conversion.md` | `.claude/**` |
| `documentation/precipitation-notebook-debugging-patterns.md` | `examples/**` |

## Creating New Rules

1. Choose appropriate subdirectory (python/, hec-ras/, testing/, documentation/)
2. Create markdown file with clear, focused guidance
3. Keep files 50-200 lines (one specific topic per file)
4. Add YAML `paths:` frontmatter to scope auto-loading:

```yaml
---
paths: ras_commander/**
---

# Rule Title
[Rule content]
```

## Guidelines

- **One topic per file**: Don't mix unrelated patterns
- **Be specific**: Include code examples
- **Stay current**: Update rules when patterns change
- **Test guidance**: Ensure recommendations work in practice

## Cross-References

**Index files**:
- `.claude/MANIFEST.md` -- Central registry mapping rules to related skills, agents, and commands
- `.claude/agents/README.md` -- Agent registry (agents follow rules)
- `.claude/skills/README.md` -- Skill catalog (skills reference rules)

**Governance**:
- `.claude/rules/documentation/hierarchical-knowledge-best-practices.md` -- Lightweight navigator pattern
- Root `AGENTS.md` -- Shared repository contract
- Root `CLAUDE.md` -- Claude loader for that shared contract
