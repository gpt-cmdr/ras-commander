# MkDocs Deployment Reference

**Quick reference for ras-commander documentation deployment across GitHub Pages and ReadTheDocs.**

## CRITICAL: ReadTheDocs Strips Symlinks

**THE PROBLEM**:

ReadTheDocs uses `rsync --safe-links` during deployment which **removes symbolic links for security**. Symlinks work during build but content is **NOT uploaded** to the live site.

**THE SOLUTION**:

Always use `cp -r` (copy) in `.readthedocs.yaml`, NEVER use `ln -s` (symlink).

## Dual-Platform Deployment

ras-commander documentation deploys to **TWO platforms**:

### 1. GitHub Pages
- **URL**: https://gpt-cmdr.github.io/ras-commander/
- **Build file**: `.github/workflows/docs.yml`
- **Symlink support**: ✅ Yes (but we use copy for consistency)
- **Build trigger**: Push to main branch
- **Build time**: ~2-3 minutes

### 2. ReadTheDocs
- **URL**: https://ras-commander.readthedocs.io
- **Build file**: `.readthedocs.yaml`
- **Symlink support**: ❌ No (STRIPPED during deployment!)
- **Build trigger**: Push + Pull Requests
- **Build time**: ~3-5 minutes

## The Notebook Integration Challenge

### Problem

Example notebooks are in `examples/` but need to appear in `docs/notebooks/` for MkDocs.

### Solution Options

| Method | Command | GitHub Pages | ReadTheDocs | Recommended |
|--------|---------|--------------|-------------|-------------|
| **Symlink** | `ln -s ../examples docs/notebooks` | ✅ Works | ❌ Stripped | No |
| **Copy** | `cp -r examples docs/notebooks` | ✅ Works | ✅ Works | **Yes** |

**Conclusion**: Use `cp -r` in both platforms for consistency.

## GitHub Actions Configuration

**File**: `.github/workflows/docs.yml`

```yaml
name: Deploy Documentation

on:
  push:
    branches:
      - main
    paths:
      - 'docs/**'
      - 'ras_commander/**'
      - 'mkdocs.yml'
      - '.github/workflows/docs.yml'
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # For git-revision-date-localized plugin

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Cache pip dependencies
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-docs-${{ hashFiles('docs/requirements-docs.txt') }}

      - name: Install documentation dependencies
        run: |
          pip install --upgrade pip
          pip install -r docs/requirements-docs.txt
          pip install -e .

      - name: Copy notebooks into docs
        run: |
          rm -rf docs/notebooks
          cp -r examples docs/notebooks

      - name: Build documentation
        run: |
          mkdocs build --strict
```

**Key points**:
- Clean `docs/notebooks` before copying (prevents stale files)
- Use `cp -r`, not `ln -s` (for consistency with ReadTheDocs)
- `--strict` flag fails build on warnings (catches errors early)
- Cache pip dependencies for faster builds

## ReadTheDocs Configuration

**File**: `.readthedocs.yaml`

```yaml
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.11"
  jobs:
    pre_build:
      # CRITICAL: MUST use cp, NOT ln -s (symlinks get stripped!)
      - cp -r examples docs/notebooks

mkdocs:
  configuration: mkdocs.yml

python:
  install:
    - requirements: docs/requirements-docs.txt
    - method: pip
      path: .
```

**Critical details**:
- `pre_build` runs before MkDocs build
- **MUST use `cp -r`**, NOT `ln -s` (symlinks stripped!)
- Same Python version as GitHub Actions (3.11)
- Same dependency file (`docs/requirements-docs.txt`)

## Git Ignore Configuration

**.gitignore entry**:
```gitignore
# Ignore docs/notebooks/ (generated from examples during build)
docs/notebooks/
```

**Why**:
- `docs/notebooks/` created during build (copy from `examples/`)
- Should NOT be committed to git (duplicates content)
- Prevents repository bloat and sync issues

## MkDocs Configuration

**File**: `mkdocs.yml`

### Validation Settings

```yaml
validation:
  links:
    unrecognized_links: info  # Permissive for AGENTS.md links
```

**Why**: AGENTS.md files contain relative links to Python source files (e.g., `../ras_commander/core.py`). These work in repository but may not validate during build.

**Levels**:
- `ignore`: Silent (not recommended)
- `info`: Log warning, continue build ✅ **Used**
- `warn`: Log warning, continue build
- `error`: Fail build (default, too strict)

### Jupyter Plugin Configuration

```yaml
plugins:
  - search
  - mkdocs-jupyter:
      include_source: true          # Show source code in docs
      execute: false                # DON'T run notebooks during build
      include: ["notebooks/*.ipynb"]
      ignore: ["notebooks/example_projects/**"]
      ignore_h1_titles: true        # Use nav titles from mkdocs.yml
```

**Key settings explained**:

**include_source: true**:
- Shows source code cells in documentation
- Users can see and copy code

**execute: false** (CRITICAL):
- Notebooks **NOT** run during build
- Notebooks may require HEC-RAS installed
- Execution can be slow and fail in CI
- **Result**: Notebooks must be pre-executed with outputs saved

**include**:
- Glob pattern for notebooks to process
- `notebooks/*.ipynb` matches all top-level notebooks

**ignore**:
- Exclude subdirectories (extracted example projects)
- Prevents processing thousands of files

**ignore_h1_titles: true**:
- Use navigation titles from mkdocs.yml
- Ignore H1 from notebook first cell
- Allows shorter, more flexible nav titles

## Platform Differences Summary

| Aspect | GitHub Pages | ReadTheDocs |
|--------|--------------|-------------|
| **Notebook handling** | Copy (`cp -r`) | Copy (`cp -r`) |
| **Build file** | `.github/workflows/docs.yml` | `.readthedocs.yaml` |
| **Symlink support** | ✅ Yes (not used) | ❌ No (stripped) |
| **Build trigger** | Push to main | Push + PR |
| **Build time** | ~2-3 min | ~3-5 min |
| **Caching** | Limited | Good |
| **URL** | github.io | readthedocs.io |
| **Custom domain** | Possible | Possible |

## Common Pitfalls and Solutions

### ❌ Pitfall 1: Using Symlinks in ReadTheDocs

**Problem**:
```yaml
# .readthedocs.yaml
build:
  jobs:
    pre_build:
      - ln -s ../examples docs/notebooks  # ❌ WRONG!
```

**Result**:
- Build succeeds (symlink created)
- Deployment strips symlink
- Live site has no notebooks!

**Solution**:
```yaml
build:
  jobs:
    pre_build:
      - cp -r examples docs/notebooks  # ✅ CORRECT
```

### ❌ Pitfall 2: Committing docs/notebooks/

**Problem**: `docs/notebooks/` committed to git

**Result**:
- Repository bloat (notebooks duplicated)
- Sync issues (examples/ and docs/notebooks/ out of sync)
- Merge conflicts

**Solution**: Add to `.gitignore`:
```gitignore
docs/notebooks/
```

### ❌ Pitfall 3: Forgetting H1 in Notebooks

**Problem**: Notebook missing H1 title in first cell

**Result**: Documentation page title is filename ("01_basic_usage")

**Solution**: Always include H1 markdown cell first:
```markdown
# Descriptive Title

Brief introduction...
```

### ❌ Pitfall 4: Using execute: true

**Problem**:
```yaml
plugins:
  - mkdocs-jupyter:
      execute: true  # ❌ WRONG!
```

**Result**:
- Build fails if HEC-RAS not installed
- Slow builds (notebooks execute every time)
- Non-deterministic (execution may fail randomly)

**Solution**:
```yaml
plugins:
  - mkdocs-jupyter:
      execute: false  # ✅ CORRECT
```

Pre-execute notebooks locally and commit with outputs.

### ❌ Pitfall 5: Out-of-Sync Dependency Files

**Problem**: Different packages in GitHub Actions vs ReadTheDocs

**Result**:
- Builds succeed on one platform but fail on the other
- Different rendering or missing features

**Solution**: Keep `docs/requirements-docs.txt` as single source of truth for both platforms.

## Testing Documentation Builds

### Local Build Test

```bash
# Clean previous build
rm -rf docs/notebooks/ site/

# Copy notebooks (simulate ReadTheDocs)
cp -r examples docs/notebooks

# Build docs
mkdocs build

# Check for errors
echo $?  # Should be 0

# Serve locally
mkdocs serve

# Visit http://127.0.0.1:8000
```

**Verify**:
- No build errors or warnings
- Notebooks render correctly
- H1 titles appear
- Code highlighting works
- Links resolve
- Images/plots display
- Navigation works

### GitHub Pages Test

```bash
# Create test branch
git checkout -b test-docs

# Make changes
# ... edit files ...

# Push to trigger build
git push origin test-docs

# Check GitHub Actions
# Visit: https://github.com/gpt-cmdr/ras-commander/actions

# If successful, merge to main
git checkout main
git merge test-docs
git push origin main
```

### ReadTheDocs Test

**Trigger**: Push or create Pull Request

**Monitor**: https://readthedocs.org/projects/ras-commander/builds/

**Check**:
1. Build log shows `cp -r examples docs/notebooks`
2. Build succeeds (green checkmark)
3. Live site has notebooks visible
4. Navigation works

## Debugging Build Failures

### Notebooks Missing on ReadTheDocs

**Symptoms**:
- Build succeeds
- Navigation shows notebook links
- Clicking links shows 404

**Debug checklist**:
1. Does `.readthedocs.yaml` use `cp` not `ln -s`? ✅
2. Does `pre_build` step execute? (check build log)
3. Does build log show notebooks copied?
4. Does `mkdocs.yml` include notebooks in nav?

**Fix**: Update `.readthedocs.yaml` to use `cp -r`.

### Notebooks Missing on GitHub Pages

**Symptoms**:
- Build succeeds
- gh-pages branch exists
- Notebooks don't appear

**Debug checklist**:
1. Does `.github/workflows/docs.yml` copy notebooks?
2. Does workflow succeed? (check Actions tab)
3. Does `gh-pages` branch have notebooks?
4. Is Pages enabled in repo settings?

**Fix**: Verify workflow copies notebooks correctly.

### Validation Errors

**Symptoms**: Build fails with "unrecognized links" errors

**Example error**:
```
ERROR - Doc file 'notebooks/01_example.ipynb' contains an unrecognized link
```

**Fix**: Update `mkdocs.yml`:
```yaml
validation:
  links:
    unrecognized_links: info  # More permissive
```

### Plugin Errors

**Symptoms**: Build fails with mkdocs-jupyter errors

**Common causes**:
- Missing dependency
- Incompatible mkdocs-jupyter version
- Malformed notebook JSON

**Fix**:
1. Check `docs/requirements-docs.txt` has correct versions
2. Validate notebook JSON: `python -m json.tool notebook.ipynb`
3. Re-run notebook locally and save

## Best Practices

### ✅ Keep Configs in Sync

Both `.github/workflows/docs.yml` and `.readthedocs.yaml` should:
- Install same dependencies
- Use same Python version
- Build from same `mkdocs.yml`
- Only differ in notebook handling (both use `cp -r`)

### ✅ Test Both Platforms Before Merging

1. Create test branch
2. Push to trigger GitHub Actions build
3. Create PR to trigger ReadTheDocs build
4. Verify both builds succeed
5. Check notebooks appear on both platforms
6. Merge to main

### ✅ Use Consistent Commands

**Both platforms use same command**:
```bash
cp -r examples docs/notebooks
```

**Why**: Consistency reduces maintenance burden and prevents platform-specific bugs.

### ✅ Document Platform Differences

In `CONTRIBUTING.md` or `README.md`:
```markdown
## Documentation Deployment

- **GitHub Pages**: https://gpt-cmdr.github.io/ras-commander/
- **ReadTheDocs**: https://ras-commander.readthedocs.io

Both use `cp -r` to copy notebooks (ReadTheDocs strips symlinks).
```

## Deployment Workflow

### Making Documentation Changes

1. **Edit content**:
   - Notebooks in `examples/`
   - Markdown in `docs/`
   - Config in `mkdocs.yml`

2. **Test locally**:
   ```bash
   cp -r examples docs/notebooks
   mkdocs serve
   ```

3. **Verify**:
   - Notebooks render correctly
   - Links work
   - No build errors

4. **Commit and push**:
   ```bash
   git add examples/ docs/ mkdocs.yml
   git commit -m "Update documentation"
   git push origin main
   ```

5. **Monitor builds**:
   - GitHub Actions: Check Actions tab
   - ReadTheDocs: Check builds page

6. **Verify deployment**:
   - Visit GitHub Pages URL
   - Visit ReadTheDocs URL
   - Check notebooks appear on both

## See Also

- **SUBAGENT.md** - Complete documentation-generator guide
- **notebook-standards.md** - Notebook creation standards
- `.claude/rules/documentation/mkdocs-config.md` - Detailed MkDocs configuration
- `.claude/rules/documentation/notebook-standards.md` - Full notebook standards

---

**Key Takeaway**: ReadTheDocs STRIPS symlinks during deployment. Always use `cp -r examples docs/notebooks` in `.readthedocs.yaml`, NEVER `ln -s`. Keep GitHub Actions and ReadTheDocs configs in sync. Test both platforms before merging to main.
