# Pyright LSP Usage for Agents

**Context**: Type checking and API discovery via pyright-lsp plugin
**Priority**: Medium - improves code quality and API discovery
**Auto-loads**: Yes (all Python code)

## Overview

The `pyright-lsp@claude-plugins-official` plugin is enabled at project scope. It provides real-time type checking, hover information, and go-to-definition for Python code in the repository.

## When to Use Pyright

### Type Error Detection

After writing or editing Python code, check pyright diagnostics to catch type errors before execution. Fix type errors surfaced by pyright in the same turn rather than ignoring them.

Common issues pyright catches:
- Wrong argument types passed to functions
- Missing required parameters
- Incorrect return type usage
- Attribute access on wrong types
- Import errors

### API Discovery

When you know the exact module or class, use pyright hover/go-to-definition to find:
- Method signatures and parameter types
- Return types
- Docstrings
- Class hierarchies

This is faster than Grep or Explore when the location is already known.

### Prefer Pyright Over Grep When

- You know the exact file and class (e.g., `RasCmdr.compute_plan` signature)
- You need return type information
- You want parameter type annotations
- You need to verify an import path exists

### Prefer Grep/Explore Over Pyright When

- Searching across many files for a pattern
- Looking for all usages of a function
- Exploring unfamiliar parts of the codebase
- The exact module location is unknown

## Limitations

- Pyright analyzes static types; some ras-commander patterns use dynamic features (DataFrame column access, HDF paths) that pyright cannot fully validate
- The `ras` global object and `ras_object` parameter pattern may produce false positives since pyright doesn't track runtime initialization
- Third-party libraries without type stubs (h5py, geopandas) may show incomplete type information

## Guidelines

- **Fix real errors**: If pyright flags a genuine type mismatch, fix it
- **Ignore false positives**: DataFrame column access (`df['col']`) and HDF path strings are expected to lack full type coverage
- **Don't add excessive type annotations**: Only add annotations when they improve clarity or fix actual pyright errors. The codebase uses type hints selectively
- **Use for validation**: After editing library code in `ras_commander/`, check that pyright doesn't report new errors in the modified files

## See Also

- **Static Classes**: `.claude/rules/python/static-classes.md` - Class patterns pyright validates
- **Decorators**: `.claude/rules/python/decorators.md` - Decorator stacking pyright checks
- **Path Handling**: `.claude/rules/python/path-handling.md` - Path type patterns
