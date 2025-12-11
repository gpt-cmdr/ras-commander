# MkDocs Configuration - Critical Platform Differences

**Context**: Documentation build for GitHub Pages and ReadTheDocs
**Priority**: Critical - incorrect config breaks deployment
**Auto-loads**: Yes (all code)
**Path-Specific**: Relevant to documentation builds

## Critical Issue: ReadTheDocs Strips Symlinks

**THE PROBLEM**:

ReadTheDocs uses `rsync --safe-links` during deployment, which **removes symbolic links for security**. Symlinks work during build but content is **NOT uploaded** to the live site.

## Dual-Platform Deployment

ras-commander documentation deploys to TWO platforms:

1. **GitHub Pages**: https://gpt-cmdr.github.io/ras-commander/
   - Build: `.github/workflows/docs.yml`
   - **Symlinks OK**: GitHub Actions preserves symlinks

2. **ReadTheDocs**: https://ras-commander.readthedocs.io
   - Build: `.readthedocs.yaml`
   - **Symlinks STRIPPED**: Must use `cp` instead of `ln -s`

## Notebook Integration Pattern

### The Challenge

Example notebooks are in `examples/` but need to appear in `docs/notebooks/` for MkDocs.

**Options**:
1. **Symlink**: `ln -s ../examples docs/notebooks` (fast, but ReadTheDocs strips)
2. **Copy**: `cp -r examples docs/notebooks` (works on ReadTheDocs)

### GitHub Actions (Symlinks Work)

**File**: `.github/workflows/docs.yml`

```yaml
name: Build Documentation

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install mkdocs mkdocs-material mkdocs-jupyter

      - name: Create notebooks symlink
        run: ln -s ../examples docs/notebooks  # ✅ Works on GitHub Pages

      - name: Build and deploy
        run: mkdocs gh-deploy --force
```

### ReadTheDocs (MUST Use Copy)

**File**: `.readthedocs.yaml`

```yaml
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.10"
  jobs:
    pre_build:
      # ✅ MUST use cp, NOT ln -s (symlinks get stripped!)
      - cp -r examples docs/notebooks

mkdocs:
  configuration: mkdocs.yml

python:
  install:
    - method: pip
      path: .
```

**Why `pre_build`**: Runs before MkDocs build, creates notebooks directory

**Why `cp` not `ln -s`**: ReadTheDocs strips symlinks during rsync

## Git Ignore Pattern

**.gitignore Entry**:
```gitignore
# Ignore docs/notebooks/ (generated from examples during build)
docs/notebooks/
```

**Why**: `docs/notebooks/` is created during build (either symlink or copy), should not be committed

## Validation Configuration

### Handling AGENTS.md Links

**Problem**: AGENTS.md files contain relative links to Python source files:
```markdown
- See `../ras_commander/core.py` for implementation
```

These links work in repository but may not validate during doc build.

**Solution**: Configure MkDocs validation to be permissive

**mkdocs.yml**:
```yaml
validation:
  links:
    unrecognized_links: info  # ✅ Logs warnings, doesn't fail build
```

**Alternative Levels**:
- `ignore`: Silent (not recommended)
- `info`: Log warning, continue build
- `warn`: Log warning, continue build
- `error`: Fail build (default, strict)

**Why `info`**: Balances validation with flexibility for AGENTS.md cross-references

## mkdocs-jupyter Configuration

### Plugin Settings

**mkdocs.yml**:
```yaml
plugins:
  - search
  - mkdocs-jupyter:
      include_source: true          # Show source code in notebooks
      execute: false                # DON'T run notebooks during build
      include: ["notebooks/*.ipynb"]  # Which notebooks to include
      ignore: ["notebooks/example_projects/**"]  # Ignore extracted projects
      ignore_h1_titles: true        # Use nav titles, not notebook H1
```

### Key Settings Explained

**include_source: true**:
- Shows source code cells in documentation
- Users can see and copy code

**execute: false**:
- **Critical**: Don't run notebooks during build
- Notebooks may require HEC-RAS installed
- Execution can be slow and fail in CI

**include**:
- Glob pattern for notebooks to process
- `notebooks/*.ipynb` matches all top-level notebooks

**ignore**:
- Exclude subdirectories (e.g., extracted example projects)
- Prevents processing thousands of files

**ignore_h1_titles: true**:
- Use navigation titles from mkdocs.yml
- Ignore H1 from notebook (may be redundant)

## Notebook Title Requirements

### H1 Title in First Cell

**Requirement**: Each notebook MUST have markdown cell with H1 heading as first cell

**Example** (`01_basic_usage.ipynb` first cell):
```markdown
# Basic Usage of ras-commander

This notebook demonstrates basic usage...
```

**Why Required**:
- mkdocs-jupyter uses H1 for page title
- Missing H1 causes title to be filename
- H1 provides context in documentation

### Nav Title vs Notebook H1

**With `ignore_h1_titles: false`** (default):
- Documentation uses H1 from notebook

**With `ignore_h1_titles: true`** (recommended):
- Documentation uses title from mkdocs.yml nav
- Allows shorter nav titles
- More control over documentation structure

**mkdocs.yml nav example**:
```yaml
nav:
  - Home: index.md
  - Examples:
    - Basic Usage: notebooks/01_basic_usage.ipynb  # ← This title used
    - Advanced: notebooks/02_advanced.ipynb
```

## Platform-Specific Differences Summary

| Aspect | GitHub Pages | ReadTheDocs |
|--------|--------------|-------------|
| **Notebooks** | Symlink (`ln -s`) | Copy (`cp -r`) |
| **Build File** | `.github/workflows/docs.yml` | `.readthedocs.yaml` |
| **Symlink Support** | ✅ Yes | ❌ No (stripped) |
| **Build Trigger** | Push to main | Push + PR |
| **Build Time** | ~2-3 min | ~3-5 min |
| **Caching** | Limited | Good |

## Common Pitfalls

### ❌ Using Symlinks in ReadTheDocs

**Problem**:
```yaml
# .readthedocs.yaml
build:
  jobs:
    pre_build:
      - ln -s ../examples docs/notebooks  # ❌ WRONG!
```

**Result**: Symlink created during build, but stripped during deployment. Live site has no notebooks!

**Solution**:
```yaml
build:
  jobs:
    pre_build:
      - cp -r examples docs/notebooks  # ✅ CORRECT
```

### ❌ Committing docs/notebooks/

**Problem**: `docs/notebooks/` committed to git

**Result**:
- Repository bloat (notebooks duplicated)
- Sync issues (examples/ and docs/notebooks/ out of sync)
- Merge conflicts

**Solution**: Add to `.gitignore`:
```gitignore
docs/notebooks/
```

### ❌ Forgetting H1 in Notebooks

**Problem**: Notebook missing H1 title in first cell

**Result**: Documentation page title is filename ("01_basic_usage")

**Solution**: Always include H1 markdown cell first:
```markdown
# Descriptive Title

Brief introduction...
```

### ❌ Using execute: true

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

## Testing Configuration

### Local Build Test

```bash
# Clean previous build
rm -rf docs/notebooks/ site/

# Copy notebooks (simulate ReadTheDocs)
cp -r examples docs/notebooks

# Build docs
mkdocs build

# Serve locally
mkdocs serve
```

### GitHub Pages Test

```bash
# Push to test branch
git push origin my-branch

# Check GitHub Actions
# Visit: https://github.com/user/repo/actions

# If successful, merge to main for deployment
```

### ReadTheDocs Test

**Trigger**: Push or create Pull Request

**Monitor**: https://readthedocs.org/projects/ras-commander/builds/

**Check**:
1. Build log shows `cp -r examples docs/notebooks`
2. Build succeeds
3. Live site has notebooks visible

## Debugging

### Notebooks Missing on ReadTheDocs

**Check**:
1. `.readthedocs.yaml` uses `cp` not `ln -s`?
2. `pre_build` step executes?
3. Build log shows notebooks copied?
4. `mkdocs.yml` includes notebooks in nav?

**Debug**: Check ReadTheDocs build log for errors

### Notebooks Missing on GitHub Pages

**Check**:
1. `.github/workflows/docs.yml` creates symlink?
2. Workflow succeeds?
3. `gh-pages` branch has notebooks?

**Debug**: Check GitHub Actions log

### Validation Errors

**Symptom**: Build fails with "unrecognized links"

**Fix**: Update mkdocs.yml:
```yaml
validation:
  links:
    unrecognized_links: info  # More permissive
```

## Best Practices

### ✅ Keep Configs in Sync

**Both configs should**:
- Install same dependencies
- Build from same mkdocs.yml
- Only differ in notebook handling (symlink vs copy)

### ✅ Test Both Platforms

Before merging:
1. Test GitHub Pages build (create test branch)
2. Test ReadTheDocs build (create PR)
3. Verify notebooks appear on both sites

### ✅ Document Platform Differences

**In README.md or CONTRIBUTING.md**:
```markdown
## Documentation Builds

- **GitHub Pages**: Uses symlinks (.github/workflows/docs.yml)
- **ReadTheDocs**: Uses copy (.readthedocs.yaml)

NEVER use symlinks in .readthedocs.yaml - they get stripped!
```

## See Also

- **Notebook Standards**: `.claude/rules/documentation/notebook-standards.md`
- **GitHub Workflows**: `.github/workflows/` directory
- **MkDocs Config**: `mkdocs.yml` in root

---

**Key Takeaway**: ReadTheDocs STRIPS symlinks. Always use `cp -r` in `.readthedocs.yaml`, never `ln -s`. Keep `.github/workflows/docs.yml` and `.readthedocs.yaml` in sync except for notebook handling.
