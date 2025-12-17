# GitHub Actions Notebook Validation Hook - Design Plan

**Created**: 2025-12-15
**Purpose**: Prevent Jupyter notebook validation errors from breaking documentation builds
**Trigger**: Recent GitHub Actions failure (run #20233891564)

## Problem Statement

### What Happened
Documentation build failed in GitHub Actions due to malformed Jupyter notebook (`21_dss_boundary_extraction.ipynb`) missing required `outputs` field in code cells.

### Why It Wasn't Caught Earlier
1. **Jupyter Auto-Repair**: Jupyter Lab/Notebook automatically fixes notebooks when opening
2. **No Pre-Commit Validation**: No automated checks before git commit
3. **Late Detection**: Only caught during strict validation in CI/CD pipeline

### Impact
- ❌ Documentation build failures
- ❌ Delayed deployments
- ❌ Wasted CI/CD resources
- ❌ Developer time spent debugging

## Design Goals

### Primary Goals
1. **Catch errors before commit** - Validate notebooks locally before pushing
2. **Fast feedback** - Validation should be quick (<5 seconds for 54 notebooks)
3. **Non-blocking for legitimate changes** - Allow valid notebooks through
4. **Clear error messages** - Tell developers exactly what's wrong and how to fix it

### Secondary Goals
- Integrate with existing development workflow
- Support both VS Code and command-line workflows
- Provide auto-fix capabilities where safe
- Document validation requirements

## Hook Architecture

### Three-Layer Defense Strategy

```
Layer 1: Pre-Commit Hook (Local)
    ↓ (if fails, block commit)
Layer 2: GitHub Actions Pre-Build Check
    ↓ (if fails, fast fail before expensive build)
Layer 3: MkDocs Build (Current)
    ↓ (final validation)
```

### Layer 1: Pre-Commit Hook (Recommended)

**Tool**: `pre-commit` framework with custom hook

**Location**: `.pre-commit-config.yaml` (root)

**Implementation**:
```yaml
repos:
  - repo: local
    hooks:
      - id: validate-notebooks
        name: Validate Jupyter Notebooks
        entry: python .github/hooks/validate_notebooks.py
        language: system
        files: \.ipynb$
        pass_filenames: true
```

**Hook Script**: `.github/hooks/validate_notebooks.py`
```python
#!/usr/bin/env python3
"""
Validate Jupyter notebooks before commit.

Checks:
1. Valid JSON structure
2. Required fields present (outputs, execution_count)
3. nbformat version compatibility
4. No corrupted cells

Exit codes:
0 - All notebooks valid
1 - Validation errors found (blocks commit)
"""

import sys
import json
from pathlib import Path
import nbformat
from nbformat.validator import validate, ValidationError

def validate_notebook(notebook_path):
    """Validate a single notebook."""
    errors = []

    try:
        # Read notebook
        with open(notebook_path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)

        # Validate structure
        validate(nb)

        # Check code cells have required fields
        for i, cell in enumerate(nb.cells):
            if cell.cell_type == 'code':
                if 'outputs' not in cell:
                    errors.append(f"Cell {i}: missing 'outputs' field")
                if 'execution_count' not in cell:
                    errors.append(f"Cell {i}: missing 'execution_count' field")

        return errors

    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]
    except ValidationError as e:
        return [f"nbformat validation error: {e}"]
    except Exception as e:
        return [f"Unexpected error: {e}"]

def main():
    """Validate all notebooks passed as arguments."""
    notebooks = [Path(arg) for arg in sys.argv[1:] if arg.endswith('.ipynb')]

    if not notebooks:
        print("No notebooks to validate")
        return 0

    all_errors = {}
    for notebook in notebooks:
        errors = validate_notebook(notebook)
        if errors:
            all_errors[notebook] = errors

    if all_errors:
        print("❌ Notebook Validation Errors Found:")
        print()
        for notebook, errors in all_errors.items():
            print(f"  {notebook}:")
            for error in errors:
                print(f"    - {error}")
        print()
        print("To fix: Run notebooks in Jupyter, save, and commit again")
        print("Or run: python .github/hooks/fix_notebooks.py <notebook>")
        return 1

    print(f"✅ {len(notebooks)} notebook(s) validated successfully")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

**Auto-Fix Companion**: `.github/hooks/fix_notebooks.py`
```python
#!/usr/bin/env python3
"""Auto-fix common notebook validation issues."""

import sys
import json
from pathlib import Path

def fix_notebook(notebook_path):
    """Fix common validation issues."""
    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)

    fixed = False
    for cell in nb['cells']:
        if cell.get('cell_type') == 'code':
            if 'outputs' not in cell:
                cell['outputs'] = []
                fixed = True
            if 'execution_count' not in cell:
                cell['execution_count'] = None
                fixed = True

    if fixed:
        with open(notebook_path, 'w', encoding='utf-8') as f:
            json.dump(nb, f, indent=1, ensure_ascii=False)
        print(f"✅ Fixed: {notebook_path}")
    else:
        print(f"ℹ️  No fixes needed: {notebook_path}")

def main():
    if len(sys.argv) < 2:
        print("Usage: fix_notebooks.py <notebook1.ipynb> [notebook2.ipynb ...]")
        return 1

    for notebook_path in sys.argv[1:]:
        fix_notebook(Path(notebook_path))

    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### Layer 2: GitHub Actions Pre-Build Check

**Purpose**: Fast-fail before expensive documentation build

**Location**: `.github/workflows/docs.yml` (add step before "Build documentation")

**Implementation**:
```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      # ... existing checkout and setup steps ...

      - name: Validate Jupyter notebooks
        run: |
          python -m pip install nbformat
          python .github/hooks/validate_notebooks.py examples/*.ipynb

      # ... rest of workflow ...
```

**Benefits**:
- Fails in ~10 seconds vs ~2 minutes for full build
- Clear error messages pointing to problematic notebooks
- Saves CI/CD compute time
- Provides same validation as local pre-commit hook

### Layer 3: Existing MkDocs Build

**No Changes Needed**: Current strict validation in `mkdocs build --strict` remains as final safeguard.

## Validation Rules

### Critical Rules (Block Commit)
1. **Valid JSON**: Notebook must be valid JSON
2. **nbformat Valid**: Must pass `nbformat.validate()`
3. **Code Cells Structure**: All code cells must have:
   - `outputs` field (array, can be empty)
   - `execution_count` field (int or null)
4. **No Corrupted Cells**: Cells must have `source` and `metadata`

### Warning Rules (Allow but Warn)
1. **Large Outputs**: Notebooks with >10MB outputs (may slow builds)
2. **Execution Count Gaps**: Non-sequential execution counts (suggest re-run)
3. **Trailing Whitespace**: Extra whitespace in cells (cosmetic)

### Auto-Fix Rules (Safe to Automatically Fix)
1. **Missing outputs**: Add empty `outputs = []`
2. **Missing execution_count**: Add `execution_count = null`
3. **Trailing Whitespace**: Strip trailing whitespace from source

## Integration Points

### 1. Developer Workflow

**Initial Setup** (one-time per developer):
```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Test hooks
pre-commit run --all-files
```

**Daily Workflow**:
```bash
# Edit notebooks in Jupyter
jupyter lab examples/

# Stage changes
git add examples/*.ipynb

# Commit (hooks run automatically)
git commit -m "Update notebooks"

# If validation fails:
python .github/hooks/fix_notebooks.py examples/problematic_notebook.ipynb
git add examples/problematic_notebook.ipynb
git commit -m "Fix notebook validation"
```

### 2. CI/CD Workflow

**GitHub Actions Sequence**:
```
1. Checkout code
2. Setup Python
3. Cache dependencies
4. Install dependencies
5. → Validate notebooks (NEW) ← Fast fail here
6. Copy notebooks to docs
7. Build documentation (expensive)
8. Deploy to GitHub Pages
```

**Benefits**:
- Validation runs in step 5 (~10 sec)
- Build runs in step 7 (~2 min)
- If validation fails, save 2+ minutes per run

### 3. Documentation

**Update Files**:

**`CONTRIBUTING.md`** - Add section:
```markdown
### Jupyter Notebook Standards

All notebooks must pass validation before commit:

```bash
# Validate notebooks
pre-commit run validate-notebooks --all-files

# Auto-fix common issues
python .github/hooks/fix_notebooks.py examples/*.ipynb
```

**Requirements**:
- All code cells must have `outputs` field (even if empty)
- All code cells must have `execution_count` field (can be null)
- Notebooks must be valid JSON and pass nbformat validation

**Troubleshooting**:
- If validation fails: Open notebook in Jupyter, save, and commit again
- For auto-fix: Run `fix_notebooks.py` on problematic notebook
```

**`.claude/rules/documentation/notebook-standards.md`** - Add validation section:
```markdown
## Validation Requirements

### Pre-Commit Validation

All notebooks are validated before commit. Common errors:

1. **Missing outputs field**: Cell has no `outputs` array
   - Fix: Open in Jupyter, save (Jupyter adds it automatically)
   - Or: `python .github/hooks/fix_notebooks.py <notebook>`

2. **Invalid JSON**: Notebook file is corrupted
   - Fix: Revert file, re-edit in Jupyter

3. **nbformat errors**: Incompatible notebook format version
   - Fix: Open in Jupyter, save (upgrades format)
```

## Implementation Plan

### Phase 1: Core Validation (Week 1)

**Tasks**:
1. ✅ Fix existing broken notebook (completed)
2. Create `.github/hooks/validate_notebooks.py`
3. Create `.github/hooks/fix_notebooks.py`
4. Test validation script on all 54 notebooks
5. Add to `.pre-commit-config.yaml`

**Deliverables**:
- Validation script that catches missing outputs errors
- Auto-fix script for common issues
- Pre-commit configuration

**Acceptance Criteria**:
- All current notebooks pass validation
- Script catches missing outputs/execution_count
- Pre-commit hook blocks invalid notebooks

### Phase 2: CI Integration (Week 1)

**Tasks**:
1. Add validation step to `.github/workflows/docs.yml`
2. Test GitHub Actions with intentionally broken notebook
3. Verify fast-fail behavior
4. Update workflow documentation

**Deliverables**:
- GitHub Actions validation step
- Workflow documentation

**Acceptance Criteria**:
- GitHub Actions fails fast on invalid notebooks
- Error messages clearly indicate which notebook/cell failed
- Valid notebooks pass through quickly

### Phase 3: Documentation & Onboarding (Week 2)

**Tasks**:
1. Update `CONTRIBUTING.md` with notebook standards
2. Update `.claude/rules/documentation/notebook-standards.md`
3. Create troubleshooting guide
4. Add validation to PR template checklist

**Deliverables**:
- Updated documentation
- Developer onboarding guide
- PR checklist item

**Acceptance Criteria**:
- Developers know how to validate notebooks
- Clear troubleshooting steps documented
- PR checklist includes notebook validation

### Phase 4: Enhanced Validation (Future)

**Potential Enhancements**:
1. **Output Size Validation**: Warn on notebooks >10MB
2. **Execution Order Validation**: Check execution_count is sequential
3. **Metadata Validation**: Check kernel name, language version
4. **Content Linting**: Check for sensitive data (API keys, passwords)
5. **Cell Count Limits**: Warn on notebooks >100 cells
6. **Image Validation**: Check embedded images are reasonable size

**Priority**: Low (implement if needed)

## Testing Strategy

### Unit Tests

**Test File**: `tests/test_notebook_validation.py`

```python
import pytest
from pathlib import Path
import json
from validate_notebooks import validate_notebook

def test_valid_notebook():
    """Test validation passes for valid notebook."""
    # Create valid test notebook
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "source": "print('hello')",
                "metadata": {},
                "outputs": [],
                "execution_count": None
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5
    }

    test_path = Path("/tmp/test_valid.ipynb")
    with open(test_path, 'w') as f:
        json.dump(nb, f)

    errors = validate_notebook(test_path)
    assert errors == []

def test_missing_outputs():
    """Test validation catches missing outputs."""
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "source": "print('hello')",
                "metadata": {},
                # Missing outputs field!
                "execution_count": None
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5
    }

    test_path = Path("/tmp/test_invalid.ipynb")
    with open(test_path, 'w') as f:
        json.dump(nb, f)

    errors = validate_notebook(test_path)
    assert any("outputs" in e for e in errors)
```

### Integration Tests

**Test GitHub Actions Workflow**:

1. Create test branch
2. Commit intentionally broken notebook
3. Push and verify GitHub Actions fails
4. Fix notebook
5. Push and verify GitHub Actions succeeds

### Manual Testing Checklist

- [ ] Pre-commit hook catches missing outputs
- [ ] Pre-commit hook catches missing execution_count
- [ ] Fix script adds missing fields correctly
- [ ] GitHub Actions fails on invalid notebooks
- [ ] GitHub Actions succeeds on valid notebooks
- [ ] Error messages are clear and actionable
- [ ] All 54 current notebooks pass validation

## Monitoring & Maintenance

### Metrics to Track

1. **Validation Failure Rate**: How often pre-commit hook catches errors
2. **CI Failure Rate**: How often GitHub Actions validation fails
3. **Auto-Fix Usage**: How often developers use fix_notebooks.py
4. **Time Saved**: CI time saved by fast-failing

### Maintenance Tasks

**Monthly**:
- Review validation error logs
- Update validation rules if needed
- Check for new nbformat versions

**Quarterly**:
- Review and update documentation
- Evaluate additional validation rules
- Gather developer feedback

## Risk Assessment

### Low Risk
- ✅ Validation is non-destructive (read-only)
- ✅ Auto-fix only adds missing required fields
- ✅ Can be bypassed with `--no-verify` if needed
- ✅ Existing notebooks already validated

### Medium Risk
- ⚠️ Pre-commit hooks can slow down commits (mitigated: fast validation)
- ⚠️ False positives could block valid notebooks (mitigated: clear error messages)
- ⚠️ Developer learning curve (mitigated: good documentation)

### Mitigation Strategies

1. **Performance**: Keep validation fast (<5 seconds for 54 notebooks)
2. **Bypass Option**: Document `git commit --no-verify` for emergencies
3. **Clear Errors**: Provide actionable error messages with fix instructions
4. **Auto-Fix**: Provide automatic fixes for common issues

## Success Criteria

### Short-Term (1 month)
- ✅ Zero documentation build failures due to notebook validation
- ✅ All developers using pre-commit hooks
- ✅ Fast-fail in GitHub Actions catching errors before expensive builds

### Long-Term (6 months)
- ✅ Notebook validation is routine part of workflow
- ✅ Reduced CI/CD time and costs
- ✅ Improved notebook quality across repository

## Alternatives Considered

### Alternative 1: nbQA

**Tool**: https://github.com/nbQA-dev/nbQA

**Pros**:
- Well-maintained third-party tool
- Integrates with existing Python linters
- Pre-built pre-commit hooks

**Cons**:
- Additional dependency
- Less customizable for our specific needs
- Focuses more on code quality than structure validation

**Decision**: Use custom validation for structure, consider nbQA for code quality later

### Alternative 2: Jupyter nbconvert

**Tool**: Built-in Jupyter notebook conversion tool

**Pros**:
- Official Jupyter tool
- Comprehensive validation
- No additional dependencies

**Cons**:
- Slower than custom validation
- More strict than needed
- May have false positives

**Decision**: Use nbconvert for final validation in CI, custom for pre-commit speed

### Alternative 3: GitHub Actions Only

**Approach**: Skip pre-commit, only validate in CI

**Pros**:
- No developer setup required
- Centralized validation

**Cons**:
- Late error detection (after push)
- Wastes CI/CD resources
- Slower developer feedback

**Decision**: Use both (pre-commit for early catch, CI for safety net)

## References

- **nbformat Specification**: https://nbformat.readthedocs.io/
- **pre-commit Framework**: https://pre-commit.com/
- **Jupyter Notebook Validation**: https://nbformat.readthedocs.io/en/latest/api.html#validation
- **GitHub Actions Best Practices**: https://docs.github.com/en/actions/guides

## Appendix: Common Validation Errors

### Error 1: Missing outputs field

**Error**:
```
Cell 1: missing 'outputs' field
```

**Cause**: Code cell created without outputs array

**Fix**:
```bash
python .github/hooks/fix_notebooks.py examples/notebook.ipynb
```

Or manually:
```json
{
  "cell_type": "code",
  "source": "...",
  "outputs": [],  // ← Add this
  "execution_count": null
}
```

### Error 2: Invalid JSON

**Error**:
```
Invalid JSON: Expecting ',' delimiter: line 42 column 5 (char 1234)
```

**Cause**: Corrupted notebook file (manual edit went wrong)

**Fix**:
1. Revert file: `git checkout HEAD -- examples/notebook.ipynb`
2. Re-edit in Jupyter Lab (don't manually edit JSON)

### Error 3: nbformat version mismatch

**Error**:
```
nbformat validation error: Notebook format 3 not supported
```

**Cause**: Old notebook format version

**Fix**:
1. Open in Jupyter Lab
2. Save (auto-upgrades to format 4)
3. Commit

---

**Plan Created By**: Claude Code (Sonnet 4.5)
**Date**: 2025-12-15
**Status**: Ready for Implementation
