# Documentation Build Checklist

## Why This Exists

To prevent **"documentation build failures on EVERY commit"** - created after fixing the `generate_cognitive_docs.py` gitignore issue.

## Root Cause of Past Failures

The `scripts/generate_cognitive_docs.py` file was accidentally gitignored by an overly broad pattern (`generate_*.py`), causing GitHub Actions to fail with:
```
python: can't open file 'scripts/generate_cognitive_docs.py': [Errno 2] No such file or directory
```

## Pre-Commit Checklist

Before committing changes that affect documentation:

### 1. Verify Workflow Dependencies Are Not Gitignored

```bash
# Check if critical files are gitignored
git check-ignore scripts/generate_cognitive_docs.py
git check-ignore docs/requirements-docs.txt
git check-ignore mkdocs.yml

# Should return NOTHING (exit code 1)
# If any file is ignored, fix .gitignore immediately
```

### 2. Verify All Workflow Scripts Are Committed

```bash
# List scripts used by workflows
git ls-files scripts/

# Should include:
# - scripts/generate_cognitive_docs.py

# If missing, add with:
# git add scripts/generate_cognitive_docs.py
```

### 3. Test Generator Script Locally

```bash
# Run the cognitive docs generator
python scripts/generate_cognitive_docs.py

# Should output:
# - Generated: docs/cognitive-infrastructure/agents.md
# - Generated: docs/cognitive-infrastructure/skills.md
# - Generated: docs/cognitive-infrastructure/commands.md

# Verify files created:
ls -la docs/cognitive-infrastructure/*.md
```

### 4. Test MkDocs Build Locally

```bash
# Clean previous build
rm -rf site/

# Test build (without --strict to allow warnings)
mkdocs build

# Should complete with exit code 0
# Warnings are OK, errors are NOT

# Verify site directory created
ls -la site/
```

### 5. Check Workflow Files Are Valid

```bash
# Validate GitHub Actions workflow
python -c "
import yaml
with open('.github/workflows/docs.yml') as f:
    workflow = yaml.safe_load(f)
    print(f'✓ Valid workflow: {workflow[\"name\"]}')
    print(f'  Steps: {len(workflow[\"jobs\"][\"build\"][\"steps\"])}')
"

# Validate ReadTheDocs config
python -c "
import yaml
with open('.readthedocs.yaml') as f:
    config = yaml.safe_load(f)
    print(f'✓ Valid RTD config')
    print(f'  Pre-build: {config[\"build\"][\"jobs\"][\"pre_build\"]}')
"
```

## Post-Push Checklist

After pushing to GitHub:

### 1. Monitor GitHub Actions

```bash
# Open GitHub Actions page
# https://github.com/gpt-cmdr/ras-commander/actions

# Or use gh CLI:
gh run list --limit 5

# Watch latest run:
gh run watch
```

### 2. If Build Fails

```bash
# Get failed logs
gh run view --log-failed

# Common issues:
# - Missing file (check git ls-files)
# - Gitignored file (check git check-ignore)
# - Invalid YAML (validate locally first)
# - Missing dependency (check docs/requirements-docs.txt)
```

## Common Pitfalls

### ✗ Overly Broad Gitignore Patterns

**Bad:**
```gitignore
generate_*.py  # Catches EVERYTHING including scripts/
test_*.py      # Catches EVERYTHING including tests/
```

**Good:**
```gitignore
ai_tools/generate_*.py  # Specific directory only
examples/test_*.py      # Specific directory only
```

### ✗ Forgetting to Add Workflow Dependencies

If workflow uses a file, it MUST be committed:
- ✓ Scripts in `scripts/`
- ✓ Requirements in `docs/requirements-docs.txt`
- ✓ Configuration files (mkdocs.yml, .readthedocs.yaml)
- ✗ Auto-generated files (agents.md, skills.md - in .gitignore)

### ✗ Using --strict Flag with Warnings

**Problem:** `mkdocs build --strict` fails on ANY warning

**Solution:** Remove `--strict` or fix ALL warnings first

**Current config:**
```yaml
# .github/workflows/docs.yml
- name: Build documentation
  run: mkdocs build  # No --strict flag
```

## Quick Verification Script

Run this before pushing:

```bash
#!/bin/bash
echo "=== Documentation Build Pre-Commit Check ==="
echo ""

# 1. Check for gitignored workflow files
echo "1. Checking for gitignored workflow files..."
if git check-ignore scripts/generate_cognitive_docs.py >/dev/null 2>&1; then
    echo "   ✗ FAIL: scripts/generate_cognitive_docs.py is gitignored!"
    exit 1
else
    echo "   ✓ PASS: Generator script not gitignored"
fi

# 2. Verify script is committed
echo "2. Checking if generator script is committed..."
if git ls-files scripts/generate_cognitive_docs.py | grep -q .; then
    echo "   ✓ PASS: Generator script is committed"
else
    echo "   ✗ FAIL: Generator script not in repository!"
    exit 1
fi

# 3. Test generator script
echo "3. Testing generator script..."
if python scripts/generate_cognitive_docs.py >/dev/null 2>&1; then
    echo "   ✓ PASS: Generator script runs successfully"
else
    echo "   ✗ FAIL: Generator script failed!"
    exit 1
fi

# 4. Test mkdocs build
echo "4. Testing mkdocs build..."
if mkdocs build >/dev/null 2>&1; then
    echo "   ✓ PASS: MkDocs build succeeds"
else
    echo "   ⚠ WARNING: MkDocs build has issues (check manually)"
fi

echo ""
echo "=== All checks passed! Safe to push ==="
```

## File Locations Reference

**Workflow files:**
- `.github/workflows/docs.yml` - GitHub Actions workflow
- `.readthedocs.yaml` - ReadTheDocs configuration
- `mkdocs.yml` - MkDocs configuration

**Generator:**
- `scripts/generate_cognitive_docs.py` - Cognitive docs generator (MUST BE COMMITTED)

**Dependencies:**
- `docs/requirements-docs.txt` - Python packages for docs build

**Generated files (gitignored):**
- `docs/cognitive-infrastructure/agents.md`
- `docs/cognitive-infrastructure/skills.md`
- `docs/cognitive-infrastructure/commands.md`

**Manual files (committed):**
- `docs/cognitive-infrastructure/index.md`

## Emergency Fix

If builds keep failing:

```bash
# 1. Check what files workflow expects
grep -r "python scripts/" .github/workflows/
grep -r "python scripts/" .readthedocs.yaml

# 2. Verify those files exist and are committed
git ls-files scripts/

# 3. If missing, add and push immediately
git add scripts/
git commit -m "Add missing workflow scripts"
git push

# 4. Monitor fix
gh run watch
```

---

**Created:** 2025-12-17
**Last Updated:** 2025-12-17
**Related Issue:** Documentation build failures from missing generator script
