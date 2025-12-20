# MkDocs Configuration - Unified Build Approach

**Context**: Documentation build for GitHub Pages and ReadTheDocs
**Priority**: Critical - incorrect config breaks deployment
**Auto-loads**: Yes (all code)
**Path-Specific**: Relevant to documentation builds

## Overview: Pre-Converted Markdown Approach

Both documentation platforms now use the **same unified approach**: pre-convert notebooks to markdown before MkDocs build. This is ~30x faster than using mkdocs-jupyter and ensures consistency.

**Key insight**: `mkdocs-jupyter` plugin is slow with many notebooks. Pre-converting with `nbconvert` in batch mode is much faster.

## Dual-Platform Deployment

ras-commander documentation deploys to TWO platforms:

1. **GitHub Pages**: https://gpt-cmdr.github.io/ras-commander/
   - Build: `.github/workflows/docs.yml`

2. **ReadTheDocs**: https://ras-commander.readthedocs.io
   - Build: `.readthedocs.yaml`

**Both now use identical notebook handling** via `.claude/scripts/prepare_notebooks_for_docs.py`.

## How the Unified Approach Works

### The Pre-Conversion Script

**File**: `.claude/scripts/prepare_notebooks_for_docs.py`

**What it does**:
1. Converts all `examples/*.ipynb` → `docs/notebooks/*.md` using `nbconvert`
2. Updates `mkdocs.yml` at build time:
   - Changes `.ipynb` references to `.md` in navigation
   - Comments out `mkdocs-jupyter` plugin (not needed for .md files)

**Script is run during build, not committed changes**:
- `mkdocs.yml` remains unchanged in git (references `.ipynb`)
- Script modifies `mkdocs.yml` temporarily during build
- Generated markdown files are not committed

### GitHub Actions Configuration

**File**: `.github/workflows/docs.yml`

```yaml
- name: Prepare notebooks for docs
  run: |
    # Pre-convert notebooks to markdown (30x faster than mkdocs-jupyter)
    python .claude/scripts/prepare_notebooks_for_docs.py
    # Copy supporting files
    cp examples/README.md docs/notebooks/ || true
    cp examples/AGENTS.md docs/notebooks/ || true

- name: Build and deploy documentation
  run: |
    mkdocs gh-deploy --force
```

**Triggers**: Builds on changes to:
- `docs/**`
- `examples/**` (notebook changes)
- `ras_commander/**`
- `.claude/**`
- `mkdocs.yml`
- `.github/workflows/docs.yml`

### ReadTheDocs Configuration

**File**: `.readthedocs.yaml`

```yaml
build:
  os: ubuntu-22.04
  tools:
    python: "3.11"
  jobs:
    pre_build:
      # Pre-convert notebooks to markdown (30x faster than mkdocs-jupyter)
      - python .claude/scripts/prepare_notebooks_for_docs.py
      # Copy supporting files
      - cp examples/README.md docs/notebooks/ || true
      - cp examples/AGENTS.md docs/notebooks/ || true
```

## Git Ignore Pattern

**`.gitignore` Entry**:
```gitignore
# Ignore docs/notebooks/ (generated from examples during build)
docs/notebooks/
```

**Why**: `docs/notebooks/` is generated at build time, should not be committed.

## Requirements

**`docs/requirements-docs.txt`** includes:
```
# For notebook pre-conversion to markdown (30x faster than mkdocs-jupyter)
nbconvert>=7.0.0
jupyter>=1.0.0
```

**Note**: `mkdocs-jupyter` is NOT required - it's disabled at build time.

## mkdocs.yml Configuration

The `mkdocs.yml` file in git still references `.ipynb` files and includes the `mkdocs-jupyter` plugin:

```yaml
plugins:
  - search
  - mkdocs-jupyter:  # Disabled at build time by script
      include_source: true
      execute: false
      include: ["notebooks/*.ipynb"]
      ignore_h1_titles: true

nav:
  - Example Notebooks:
    - Using RasExamples: notebooks/100_using_ras_examples.ipynb  # Changed to .md at build
```

**At build time**, the script:
1. Comments out `mkdocs-jupyter` plugin
2. Changes all `.ipynb` → `.md` in nav

This keeps the source `mkdocs.yml` clean and maintainable while still working with the pre-conversion approach.

## Notebook Title Requirements

### H1 Title in First Cell

**Requirement**: Each notebook MUST have markdown cell with H1 heading as first cell

**Example** (`100_using_ras_examples.ipynb` first cell):
```markdown
# Using RasExamples

This notebook demonstrates how to work with example projects...
```

**Why Required**:
- `nbconvert` preserves H1 as markdown heading
- Provides page title in documentation
- H1 provides context for readers

## Validation Configuration

**mkdocs.yml**:
```yaml
validation:
  links:
    unrecognized_links: info  # Logs warnings, doesn't fail build
```

This allows AGENTS.md files with relative links to source code without breaking builds.

## Platform Comparison

| Aspect | GitHub Pages | ReadTheDocs |
|--------|--------------|-------------|
| **Build File** | `.github/workflows/docs.yml` | `.readthedocs.yaml` |
| **Notebook Handling** | Pre-convert to .md | Pre-convert to .md |
| **Script Used** | `prepare_notebooks_for_docs.py` | `prepare_notebooks_for_docs.py` |
| **Build Trigger** | Push to main | Push + PR |
| **Deployment** | `mkdocs gh-deploy` | ReadTheDocs native |

## Agent/Automation Guidelines

### No Markdown Maintenance Needed

Since markdown is **generated at build time**:
- ✅ Update notebooks in `examples/` normally
- ✅ Commit `.ipynb` changes
- ✅ Push triggers doc rebuild
- ✅ Markdown regenerated automatically
- ❌ Don't commit anything to `docs/notebooks/`
- ❌ Don't manually maintain markdown copies

### When Updating Notebooks

1. Edit the `.ipynb` file in `examples/`
2. Commit and push
3. GitHub Actions / ReadTheDocs rebuild docs
4. Fresh markdown generated from current notebooks

## Testing Configuration

### Local Build Test

```bash
# Clean previous build
rm -rf docs/notebooks/ site/

# Run the conversion script (modifies mkdocs.yml temporarily)
python .claude/scripts/prepare_notebooks_for_docs.py

# Build docs
mkdocs build

# Serve locally
mkdocs serve

# IMPORTANT: Restore mkdocs.yml after testing
git checkout mkdocs.yml
```

### Verify Conversion Works

```bash
# Run script and check output
python .claude/scripts/prepare_notebooks_for_docs.py

# Should show:
# - "Converting 47 notebooks to markdown..."
# - "Created 47 markdown files"
# - "Updated mkdocs.yml"

# Check generated files
ls docs/notebooks/*.md | head -10
```

## Common Pitfalls

### ❌ Committing docs/notebooks/

**Problem**: Generated markdown committed to git

**Result**:
- Repository bloat
- Sync issues between examples/ and docs/notebooks/
- Merge conflicts

**Solution**: Ensure `docs/notebooks/` is in `.gitignore`

### ❌ Committing Modified mkdocs.yml

**Problem**: Running script locally modifies `mkdocs.yml`, then committing

**Result**:
- mkdocs.yml has .md references instead of .ipynb
- Script fails on next run (can't find .ipynb references)

**Solution**: Always restore after local testing:
```bash
git checkout mkdocs.yml
```

### ❌ Forgetting H1 in Notebooks

**Problem**: Notebook missing H1 title in first cell

**Result**: Documentation page has poor title (filename)

**Solution**: Always include H1 markdown cell first:
```markdown
# Descriptive Title

Brief introduction...
```

## Debugging

### Build Fails on Missing Notebooks

**Symptom**: MkDocs can't find `notebooks/XXX.md`

**Check**:
1. Did `prepare_notebooks_for_docs.py` run?
2. Are notebooks present in `examples/`?
3. Does notebook filename match nav entry?

### Notebooks Not Updating

**Symptom**: Documentation shows old notebook content

**Check**:
1. Did you push notebook changes?
2. Did build trigger? (check Actions/ReadTheDocs)
3. Is there caching? Try manual rebuild

### Script Errors

**Symptom**: `prepare_notebooks_for_docs.py` fails

**Check**:
1. Is `nbconvert` installed? (`pip install nbconvert jupyter`)
2. Are notebooks valid? (try opening in Jupyter)
3. Check script output for specific errors

## Performance Comparison

| Approach | Build Time (47 notebooks) | Notes |
|----------|---------------------------|-------|
| **mkdocs-jupyter** | ~5-10 minutes | Processes each notebook individually |
| **Pre-conversion** | ~15-30 seconds | Batch nbconvert + plain markdown |
| **Improvement** | **~20-30x faster** | Significant CI/CD savings |

## See Also

- **Notebook Standards**: `.claude/rules/documentation/notebook-standards.md`
- **Conversion Script**: `.claude/scripts/prepare_notebooks_for_docs.py`
- **GitHub Workflow**: `.github/workflows/docs.yml`
- **ReadTheDocs Config**: `.readthedocs.yaml`
- **MkDocs Config**: `mkdocs.yml` in root

---

**Key Takeaway**: Both platforms use `prepare_notebooks_for_docs.py` to pre-convert notebooks to markdown before build. This is ~30x faster than mkdocs-jupyter. Notebooks are edited in `examples/`, markdown is generated at build time, nothing in `docs/notebooks/` should be committed.
