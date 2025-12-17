# Pre-Commit Hooks

Custom pre-commit hooks for ras-commander repository invariants.

## Installation

```bash
# Install pre-commit
pip install pre-commit

# Install hooks (run from repo root)
pre-commit install
```

## Hooks in This Directory

### check_docs_notebooks.py

**Purpose**: Block commits to `docs/notebooks/`

**Why**: This directory is generated from `examples/` during documentation builds. Committing files here causes RTD deployment failures and repository bloat.

**Trigger**: Always runs (checks staged files)

### check_rtd_no_symlinks.py

**Purpose**: Ensure `.readthedocs.yaml` uses `cp`, not `ln -s`

**Why**: ReadTheDocs strips symlinks during deployment (`rsync --safe-links`). Using symlinks results in missing content on the live site.

**Trigger**: When `.readthedocs.yaml` is modified

### check_mkdocs_no_execute.py

**Purpose**: Ensure `mkdocs.yml` has `execute: false` for mkdocs-jupyter

**Why**: CI environments don't have HEC-RAS installed. Notebook execution would fail and break documentation builds.

**Trigger**: When `mkdocs.yml` is modified

## Usage

### Run All Hooks

```bash
pre-commit run --all-files
```

### Run Specific Hook

```bash
pre-commit run check-docs-notebooks --all-files
pre-commit run check-rtd-no-symlinks --all-files
pre-commit run check-mkdocs-no-execute --all-files
```

### Bypass Hooks (Emergency Only)

```bash
git commit --no-verify -m "Emergency fix"
```

## Testing Hooks Manually

```bash
# Test docs/notebooks check
python hooks/check_docs_notebooks.py

# Test RTD symlink check
python hooks/check_rtd_no_symlinks.py

# Test mkdocs execute check
python hooks/check_mkdocs_no_execute.py
```

## Exit Codes

- `0`: Check passed
- `1`: Violation found (commit blocked)

## Documentation

- **Architecture**: `feature_dev_notes/Hooks_Infrastructure/HOOK_ARCHITECTURE.md`
- **Implementation Details**: `feature_dev_notes/Hooks_Infrastructure/DETERMINISTIC_HOOKS.md`
- **Status & Roadmap**: `feature_dev_notes/Hooks_Infrastructure/STATUS.md`
