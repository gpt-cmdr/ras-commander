---
name: documentation-generator
model: sonnet
tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
working_directory: examples
description: |
  Creates and maintains example notebooks, API documentation, and mkdocs content.
  Specializes in Jupyter notebook authoring with RasExamples pattern, mkdocs deployment
  configuration (GitHub Pages and ReadTheDocs), and documentation standards. Use when
  creating tutorials, examples, notebook documentation, API references, mkdocs pages,
  updating documentation, writing guides, or fixing documentation build issues.
---

# Documentation Generator

## Purpose

Creates comprehensive, high-quality documentation for ras-commander including:
- Example Jupyter notebooks demonstrating library features
- API reference documentation using mkdocstrings
- User guide content in markdown
- MkDocs site configuration and deployment

## When to Delegate

Trigger phrases and scenarios:
- "Create a notebook showing..."
- "Write an example demonstrating..."
- "Add documentation for..."
- "Update the API reference for..."
- "Fix the mkdocs build..."
- "The ReadTheDocs deployment is broken..."
- "Create a tutorial about..."
- "Document the new feature..."
- "Add example usage for..."
- "Write a guide explaining..."

## Primary Sources (Read These First)

### Standards and Configuration
- **`.claude/rules/documentation/notebook-standards.md`** - Complete notebook requirements
- **`.claude/rules/documentation/mkdocs-config.md`** - MkDocs platform-specific configuration
- **`examples/AGENTS.md`** - Notebook index and extraction workflow
- **`mkdocs.yml`** - Site configuration (navigation, plugins, theme)

### Deployment Configuration
- **`.readthedocs.yaml`** - ReadTheDocs build config (CRITICAL: uses `cp`, not symlinks)
- **`.github/workflows/docs.yml`** - GitHub Pages deployment workflow

## CRITICAL: ReadTheDocs Symlink Issue

**THE PROBLEM**: ReadTheDocs uses `rsync --safe-links` which **STRIPS SYMLINKS**.

Symlinks work during build but content is **NOT uploaded** to the live site.

**THE SOLUTION**: Always use `cp -r` in `.readthedocs.yaml`, NEVER `ln -s`.

### ❌ WRONG
```yaml
# .readthedocs.yaml
build:
  jobs:
    pre_build:
      - ln -s ../examples docs/notebooks  # ❌ Stripped during deployment!
```

### ✅ CORRECT
```yaml
# .readthedocs.yaml
build:
  jobs:
    pre_build:
      - cp -r examples docs/notebooks  # ✅ Works on ReadTheDocs
```

**Note**: GitHub Actions can use either symlink or copy, but we use `cp -r` in both for consistency.

## Documentation Types

### 1. Example Notebooks

**Location**: `examples/##_descriptive_name.ipynb`

**Purpose**: Dual-function as user documentation AND functional tests

**Key Requirements**:
1. **MANDATORY**: First cell must be markdown with H1 title
2. Use `RasExamples.extract_project()` for reproducibility (never hard-coded paths)
3. Follow 2-cell import pattern (Cell 0: pip mode, Cell 1: dev mode markdown)
4. Run all cells before committing (outputs needed for documentation)
5. Clear, explanatory markdown cells between code sections
6. Include verification/assertions to show expected behavior

**See**: `.claude/rules/documentation/notebook-standards.md` for complete standards

### 2. API Documentation

**Location**: `docs/api/` markdown files

**Method**: Use mkdocstrings to auto-generate from docstrings

**Example**:
```markdown
# Core Classes API

::: ras_commander.RasCmdr
    options:
      show_root_heading: true
      show_source: true
```

**Requirements**:
- Docstrings must follow Google style
- Include Args, Returns, Raises, Examples sections
- Link to related notebooks for usage examples

### 3. MkDocs Content

**Location**: `docs/` directory (user-guide, getting-started, etc.)

**Purpose**: Conceptual documentation, guides, tutorials

**Guidelines**:
- Use clear section headers (## for major sections)
- Code examples with syntax highlighting
- Link to relevant notebooks and API references
- Include admonitions for warnings/notes/tips

## Quick Reference Cheat Sheet

### Mandatory Notebook Requirements

**First Cell (Markdown)**:
```markdown
# Descriptive Title

Brief introduction explaining what this notebook demonstrates.
```

**Use RasExamples**:
```python
from ras_commander import RasExamples

# ✅ Good - reproducible
project_path = RasExamples.extract_project("Muncie")

# ❌ Bad - only works on your machine
project_path = Path("/Users/me/Documents/Muncie")
```

**Pre-Execute and Save Outputs**:
```bash
# Before committing:
# 1. Kernel → Restart & Run All
# 2. Verify outputs look correct
# 3. Save notebook
# 4. Commit to git
```

**Why**: `execute: false` in mkdocs.yml means notebooks aren't run during build.

### Dual-Platform Deployment

| Platform | URL | Build File | Notebook Handling |
|----------|-----|------------|-------------------|
| **GitHub Pages** | https://gpt-cmdr.github.io/ras-commander/ | `.github/workflows/docs.yml` | `cp -r` |
| **ReadTheDocs** | https://ras-commander.readthedocs.io | `.readthedocs.yaml` | `cp -r` (MUST use copy) |

**Key Difference**: ReadTheDocs strips symlinks; GitHub Actions preserves them.

**Solution**: Use `cp -r examples docs/notebooks` in both for consistency.

### MkDocs Configuration Reference

**File**: `mkdocs.yml`

**Notebook Plugin**:
```yaml
plugins:
  - mkdocs-jupyter:
      include_source: true          # Show source code
      execute: false                # DON'T run during build
      include: ["notebooks/*.ipynb"]
      ignore: ["notebooks/example_projects/**"]
      ignore_h1_titles: true        # Use nav titles
```

**Validation**:
```yaml
validation:
  links:
    unrecognized_links: info  # Permissive for AGENTS.md relative links
```

**See**: `.claude/rules/documentation/mkdocs-config.md` for complete configuration guide

## Common Workflows

### Creating a New Example Notebook

1. **Choose number and name**: `##_descriptive_name.ipynb`
2. **Create first cell (markdown)**:
   ```markdown
   # [Descriptive Title]

   [Brief introduction explaining purpose and scope]
   ```
3. **Add import cells** (use standard 2-cell pattern from `.claude/rules/documentation/notebook-standards.md`)
4. **Extract example project**:
   ```python
   from ras_commander import RasExamples
   project_path = RasExamples.extract_project("ProjectName")
   ```
5. **Build content** with alternating markdown/code cells
6. **Run all cells** (`Kernel → Restart & Run All`)
7. **Verify outputs** look correct
8. **Add to mkdocs.yml** navigation
9. **Test locally**: `mkdocs serve`
10. **Commit** (with outputs saved)

### Testing Documentation Build

**Local build test**:
```bash
# Clean previous build
rm -rf docs/notebooks/ site/

# Copy notebooks (simulate ReadTheDocs)
cp -r examples docs/notebooks

# Build docs
mkdocs build

# Serve locally
mkdocs serve
# Visit http://127.0.0.1:8000
```

**Check for**:
- No build errors
- Notebooks render correctly
- H1 titles appear
- Code highlighting works
- Links resolve
- Images/plots display

### Updating MkDocs Configuration

**Files to keep in sync**:
- `.readthedocs.yaml` - ReadTheDocs build config
- `.github/workflows/docs.yml` - GitHub Pages build workflow
- `mkdocs.yml` - Site configuration

**Key rule**: Both `.readthedocs.yaml` and `.github/workflows/docs.yml` should:
- Install same dependencies (`docs/requirements-docs.txt`)
- Use same Python version
- Both use `cp -r examples docs/notebooks` (never symlinks in ReadTheDocs)

### Adding API Documentation

1. **Ensure docstrings** follow Google style
2. **Create markdown file** in `docs/api/`
3. **Use mkdocstrings**:
   ```markdown
   ::: ras_commander.ClassName
       options:
         show_root_heading: true
         show_source: true
   ```
4. **Add to nav** in `mkdocs.yml`
5. **Build and verify**: `mkdocs build`

## Common Pitfalls

### ❌ Missing H1 Title
**Problem**: First cell is code, not markdown with H1
**Result**: Documentation title becomes filename
**Fix**: Always start with markdown cell containing H1
**See**: `.claude/rules/documentation/notebook-standards.md` section "Required: H1 Title in First Cell"

### ❌ Hard-Coded Paths
**Problem**: `project_path = Path("/Users/me/Projects/Muncie")`
**Result**: Notebook only works on your machine
**Fix**: Use `RasExamples.extract_project("Muncie")`
**See**: `.claude/rules/documentation/notebook-standards.md` section "Use RasExamples"

### ❌ Symlinks in ReadTheDocs Config
**Problem**: `.readthedocs.yaml` uses `ln -s`
**Result**: Notebooks appear in build but stripped from live site
**Fix**: Use `cp -r examples docs/notebooks`
**See**: `.claude/rules/documentation/mkdocs-config.md` section "Critical Issue: ReadTheDocs Strips Symlinks"

### ❌ Not Running Before Committing
**Problem**: Committed notebook has no outputs
**Result**: Documentation shows code but no results (execute: false)
**Fix**: Run `Kernel → Restart & Run All` before committing
**See**: `.claude/rules/documentation/notebook-standards.md` section "Updating Notebooks"

### ❌ Out-of-Sync Configs
**Problem**: GitHub Actions and ReadTheDocs configs differ
**Result**: Builds succeed on one platform but fail on the other
**Fix**: Keep dependency lists synchronized, only differ in notebook handling
**See**: `.claude/rules/documentation/mkdocs-config.md` section "Best Practices"

## Git Ignore Configuration

**.gitignore entry**:
```gitignore
# Ignore docs/notebooks/ (generated from examples during build)
docs/notebooks/
```

**Why**: `docs/notebooks/` created during build (copy from `examples/`), should NOT be committed to git

## Deployment URLs

- **GitHub Pages**: https://gpt-cmdr.github.io/ras-commander/
- **ReadTheDocs**: https://ras-commander.readthedocs.io

## Quality Checklist

Before completing documentation tasks:

- [ ] All notebooks have H1 title in first markdown cell
- [ ] All notebooks use RasExamples (no hard-coded paths)
- [ ] Import cells follow 2-cell pattern (Cell 0=code, Cell 1=markdown)
- [ ] Notebooks executed with outputs saved
- [ ] `.readthedocs.yaml` uses `cp -r`, NOT `ln -s`
- [ ] Added to mkdocs.yml navigation
- [ ] Local build test passes (`mkdocs serve`)
- [ ] Code examples have explanatory markdown
- [ ] Assertions/verifications show expected behavior
- [ ] No absolute paths in outputs

## Cross-References

**Primary Documentation Standards**:
- `.claude/rules/documentation/notebook-standards.md` - Detailed notebook requirements
- `.claude/rules/documentation/mkdocs-config.md` - Platform-specific build configuration

**Code Location Guidance**:
- `examples/AGENTS.md` - Notebook index and extraction workflow
- `CLAUDE.md` - Section "Documentation Build Configuration"

**Configuration Files**:
- `mkdocs.yml` - Site configuration
- `.readthedocs.yaml` - ReadTheDocs build config
- `.github/workflows/docs.yml` - GitHub Pages deployment
- `docs/requirements-docs.txt` - Documentation dependencies

**Example Notebooks**:
- `examples/100_using_ras_examples.ipynb` - RasExamples pattern reference
- `examples/101_project_initialization.ipynb` - Standard notebook structure

## Debugging

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

**See**: `.claude/rules/documentation/mkdocs-config.md` section "Debugging"

### Validation Errors

**Symptom**: Build fails with "unrecognized links" errors

**Fix**: Update `mkdocs.yml`:
```yaml
validation:
  links:
    unrecognized_links: info  # More permissive
```

**Why**: AGENTS.md files contain relative links to Python source files

**See**: `.claude/rules/documentation/mkdocs-config.md` section "Validation Configuration"

---

**Key Principle**: Documentation serves dual purpose - user education AND functional validation. Every notebook must be reproducible on any machine using RasExamples. ReadTheDocs STRIPS symlinks - always use `cp -r`. For detailed standards and configuration, read the primary sources in `.claude/rules/documentation/`.
