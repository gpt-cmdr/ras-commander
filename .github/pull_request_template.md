## Summary

<!-- Brief description of what this PR does and why -->

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Refactoring (no functional changes)
- [ ] Example notebook

---

## LLM Self-Review

> **ras-commander encourages LLM-assisted contributions.** If your agent prepared this code, confirm it reviewed the style guide. See [CONTRIBUTING.md](../CONTRIBUTING.md) for details.

### Style Compliance

- [ ] Static class pattern followed (`.claude/rules/python/static-classes.md`)
- [ ] `@staticmethod` + `@log_call` on public methods (`.claude/rules/python/decorators.md`)
- [ ] Naming conventions followed (`.claude/rules/python/naming-conventions.md`)
- [ ] `pathlib.Path` used, accepts both `str` and `Path` (`.claude/rules/python/path-handling.md`)
- [ ] DataFrames used for project metadata, not glob (`.claude/rules/python/dataframe-first-principle.md`)

### Code Quality

- [ ] Google-style docstrings with Args, Returns, Raises
- [ ] Tested with real HEC-RAS project (`RasExamples.extract_project()`)
- [ ] No hardcoded file paths
- [ ] Uses logging, not `print()`
- [ ] Proper error handling with informative messages

### API Changes (if applicable)

- [ ] `ras_object=None` parameter included for multi-project support
- [ ] Standard parameter names (`plan_number`, `geom_file`)
- [ ] API consistency auditor 5 rules followed (`.claude/agents/api-consistency-auditor.md`)
- [ ] Return types consistent (DataFrames for tabular data)

### Notebooks (if applicable)

- [ ] First cell is markdown with H1 title
- [ ] Uses `RasExamples.extract_project()` for data
- [ ] Development toggle cell included (`USE_LOCAL_SOURCE`)

---

## Test Plan

<!-- How was this tested? Which example project? -->

## LLM Attribution

**Model/Tool used**: <!-- e.g., Claude Code (Opus 4.6), Codex CLI, Aider, Cursor, manual, etc. -->
