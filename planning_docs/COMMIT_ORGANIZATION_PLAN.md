# Commit Organization Plan

**Branch**: feature/hierarchical-knowledge
**Date**: 2025-12-11
**Uncommitted Changes**: 14 modified + 20 untracked files

---

## Change Analysis

### Modified Files (14)

**USGS Module** (4 files):
- `usgs/__init__.py` (+68 lines) - Export new modules (catalog, rate_limiter, boundary_generation, time_series)
- `usgs/core.py` (+7 lines) - Core functionality enhancements
- `usgs/real_time.py` (+10 lines) - Real-time monitoring updates
- `usgs/spatial.py` (+26 lines) - Spatial query improvements

**Remote Module** (2 files):
- `remote/DockerWorker.py` (+29 lines) - SSH key path support
- `remote/RasWorker.py` (+26 lines) - Worker base class enhancements

**Example Notebooks** (4 files):
- `examples/18_breach_results_extraction.ipynb` (335 lines changed) - Updated
- `examples/23_remote_execution_psexec.ipynb` (+130 lines) - Remote execution updates
- `examples/24_aorc_precipitation.ipynb` (+27 lines) - AORC updates
- `examples/README.md` (+108 lines) - Documentation for USGS examples

**Tools** (4 files deleted):
- `tools/1D Mannings to L-MC-R/` - Entire directory (exe, py, README, ico)

### Untracked Files (20)

**New USGS Modules** (2 files):
- `usgs/catalog.py` - Gauge catalog generation (NEW v0.89.0+)
- `usgs/rate_limiter.py` - API rate limiting utilities

**New Example Notebooks** (6 files):
- `examples/29_usgs_gauge_data_integration.ipynb` - Complete workflow
- `examples/29_usgs_gauge_data_integration_executed.ipynb` - Executed version
- `examples/31_bc_generation_from_live_gauge.ipynb` - BC generation
- `examples/31_bc_generation_from_live_gauge_executed.ipynb` - Executed version
- `examples/32_model_validation_with_usgs.ipynb` - Validation workflow
- `examples/33_gauge_catalog_generation.ipynb` - Catalog demo (v0.89.0+)

**AI Tools Notebooks** (6 files):
- `ai_tools/llm_knowledge_bases/example_notebooks_cleaned/*.ipynb`

**Planning Docs** (4 files):
- `planning_docs/PHASE_3_PREPARATION.md`
- `planning_docs/SESSION_SUMMARY_2025-12-11.md`
- `planning_docs/SKILL_ANALYZING_AORC_SUMMARY.md`
- `planning_docs/skill_refactor_geometry_parsing.md`

**Project Catalog** (1 file):
- `example_projects.csv`

---

## Recommended Commit Sequence

### Commit 1: USGS Catalog and Rate Limiter (New Features)

**Files**:
- `usgs/catalog.py` (new)
- `usgs/rate_limiter.py` (new)

**Message**:
```
Add USGS gauge catalog generation and rate limiting (v0.89.0+)

New Modules:
- catalog.py: Standardized "USGS Gauge Data" folder generation
  - generate_gauge_catalog(): One-command gauge discovery and download
  - load_gauge_catalog(): Load gauge catalog from standard location
  - load_gauge_data(): Load historical data for specific gauge
  - Standard folder structure (gauge_catalog.csv, gauge_locations.geojson, per-gauge folders)

- rate_limiter.py: API rate limiting utilities
  - UsgsRateLimiter: Token bucket rate limiter
  - retry_with_backoff(): Exponential backoff decorator
  - configure_api_key(): USGS API key helper
  - Respectful API usage (default 1 req/sec)

Benefits:
- One-command gauge data organization
- Standard project structure for engineering review
- Prevents USGS API rate limit issues
- Supports reproducible workflows

Follows ras-commander patterns:
- Static class methods
- @log_call decorators
- pathlib.Path usage
- Comprehensive docstrings
```

### Commit 2: USGS Module Integration

**Files**:
- `usgs/__init__.py`

**Message**:
```
Integrate catalog and rate limiter into usgs module exports

Updates:
- Export catalog functions (generate_gauge_catalog, load_gauge_catalog, etc.)
- Export rate limiting utilities (UsgsRateLimiter, retry_with_backoff, etc.)
- Export boundary generation and time series processing classes
- Add package-level convenience functions

Enables:
- from ras_commander.usgs import generate_gauge_catalog
- from ras_commander.usgs import UsgsRateLimiter
```

### Commit 3: USGS Core Module Enhancements

**Files**:
- `usgs/core.py`
- `usgs/real_time.py`
- `usgs/spatial.py`

**Message**:
```
Enhance USGS core, real-time, and spatial modules

Updates:
- core.py: Enhanced data retrieval with better error handling
- real_time.py: Improved caching and refresh logic
- spatial.py: Better gauge filtering and metadata

Improvements:
- More robust API error handling
- Better cache management
- Enhanced spatial query capabilities
```

### Commit 4: New USGS Example Notebooks

**Files**:
- `examples/29_usgs_gauge_data_integration.ipynb`
- `examples/29_usgs_gauge_data_integration_executed.ipynb`
- `examples/31_bc_generation_from_live_gauge.ipynb`
- `examples/31_bc_generation_from_live_gauge_executed.ipynb`
- `examples/32_model_validation_with_usgs.ipynb`
- `examples/33_gauge_catalog_generation.ipynb`

**Message**:
```
Add USGS integration example notebooks (29, 31-33)

New Notebooks:
- 29_usgs_gauge_data_integration.ipynb: Complete workflow demonstration
  - Spatial discovery → data retrieval → gauge matching → validation
  - Full end-to-end example with real project

- 31_bc_generation_from_live_gauge.ipynb: Boundary condition generation
  - Retrieve USGS data
  - Resample to HEC-RAS interval
  - Generate fixed-width boundary tables
  - Update .u## files

- 32_model_validation_with_usgs.ipynb: Model validation workflow
  - Compare modeled vs observed flow/stage
  - Calculate NSE, KGE, peak error metrics
  - Generate publication-quality plots

- 33_gauge_catalog_generation.ipynb: Catalog generation (v0.89.0+)
  - One-command gauge data organization
  - Standard folder structure demonstration
  - Reproducible workflow pattern

All notebooks:
- Use RasExamples for reproducibility
- Include H1 title in first cell
- Executed versions show expected outputs
- Follow notebook-standards.md patterns
```

### Commit 5: Examples README Update

**Files**:
- `examples/README.md`

**Message**:
```
Update examples README with USGS integration section

Additions:
- USGS Integration section documenting notebooks 29-33
- Links to usgs/CLAUDE.md for complete workflow reference
- Brief descriptions of each workflow

Follows documentation patterns from hierarchical-knowledge-best-practices
```

### Commit 6: Remote Worker Enhancements

**Files**:
- `remote/DockerWorker.py`
- `remote/RasWorker.py`

**Message**:
```
Add SSH key path support to DockerWorker

Enhancements:
- ssh_key_path parameter for Docker SSH authentication
- Path expansion (~ support)
- Documentation for use with system SSH vs paramiko
- Integration with SSH config files

Use cases:
- Docker hosts requiring specific SSH keys
- ~/.ssh/config integration
- Better SSH authentication control
```

### Commit 7: Updated Example Notebooks

**Files**:
- `examples/18_breach_results_extraction.ipynb`
- `examples/23_remote_execution_psexec.ipynb`
- `examples/24_aorc_precipitation.ipynb`

**Message**:
```
Update example notebooks 18, 23, 24

Updates:
- 18_breach_results_extraction.ipynb: Improved output formatting
- 23_remote_execution_psexec.ipynb: SSH key path documentation
- 24_aorc_precipitation.ipynb: Minor clarifications

All notebooks re-executed to show current output
```

### Commit 8: Planning Documentation

**Files**:
- `planning_docs/PHASE_3_PREPARATION.md`
- `planning_docs/SESSION_SUMMARY_2025-12-11.md`
- `planning_docs/SKILL_ANALYZING_AORC_SUMMARY.md`
- `planning_docs/skill_refactor_geometry_parsing.md`

**Message**:
```
Add planning documentation for previous sessions

Documentation:
- PHASE_3_PREPARATION.md: Phase 3 preparation and planning
- SESSION_SUMMARY_2025-12-11.md: Session work summary
- SKILL_ANALYZING_AORC_SUMMARY.md: AORC skill analysis
- skill_refactor_geometry_parsing.md: Geometry parsing refactor notes

Historical context for hierarchical knowledge implementation
```

### Commit 9: Remove Obsolete Tools

**Files**:
- `tools/1D Mannings to L-MC-R/` (delete entire directory)

**Message**:
```
Remove obsolete 1D Manning's tools directory

Removed:
- 1D_Mannings_to_L-MC-R.exe (11 MB binary)
- 1D_Mannings_to_L-MC-R.py (script)
- README.md
- water_icon.ico

Reason: Replaced by integrated ras-commander functionality
```

### Decision Needed: AI Tools Notebooks

**Files**:
- `ai_tools/llm_knowledge_bases/example_notebooks_cleaned/*.ipynb` (6 files)

**Options**:

**Option 1: Add to .gitignore** (Recommended)
```bash
# Add to .gitignore
echo "ai_tools/" >> .gitignore
git add .gitignore
git commit -m "Ignore ai_tools directory (LLM knowledge bases)"
```

**Rationale**:
- Internal AI tooling, not part of library
- Cleaned notebooks derived from examples/
- Prevents repository bloat
- Can be regenerated if needed

**Option 2: Commit as Internal Tooling**
```bash
git add ai_tools/
git commit -m "Add cleaned example notebooks for LLM knowledge bases"
```

**Rationale**:
- Documents LLM integration approach
- Shows notebook cleaning process
- Preserved for reference

**Recommendation**: Option 1 (.gitignore) - keeps repository focused on library code

### Decision Needed: Example Projects CSV

**File**:
- `example_projects.csv`

**Options**:

**Option 1: Commit as documentation**
```bash
git add example_projects.csv
git commit -m "Add example projects catalog"
```

**Option 2: Add to .gitignore**
```bash
echo "example_projects.csv" >> .gitignore
```

**Question**: What is this file? Is it:
- A catalog of available example projects?
- Test data for examples?
- Internal development reference?

**Recommendation**: Review file content first to determine appropriate action

---

## Execution Plan

### Step 1: Review AI Tools and CSV
```bash
# Check ai_tools notebooks
ls -lh ../ai_tools/llm_knowledge_bases/example_notebooks_cleaned/

# Check example_projects.csv content
head -20 ../example_projects.csv
```

### Step 2: Execute Commits 1-9 in Sequence
```bash
# Commit 1: USGS catalog and rate limiter
git add usgs/catalog.py usgs/rate_limiter.py
git commit -m "..."

# Commit 2: USGS integration
git add usgs/__init__.py
git commit -m "..."

# ... continue through Commit 9
```

### Step 3: Handle Decision Items
```bash
# Based on Step 1 review, either:
# - Add to .gitignore, or
# - Commit with appropriate message
```

### Step 4: Push Branch
```bash
git push origin feature/hierarchical-knowledge
```

---

## Summary

**Total Commits Planned**: 9 required + 2 decision items = 9-11 commits

**Logical Grouping**:
1. New features (USGS catalog, rate limiter)
2. Module integration (exports)
3. Module enhancements (core, real-time, spatial)
4. New documentation (notebooks)
5. Documentation updates (README)
6. Feature enhancements (remote workers)
7. Maintenance (notebook updates)
8. Historical docs (planning)
9. Cleanup (obsolete tools)

**Benefits of This Organization**:
- Each commit has clear purpose
- Related changes grouped together
- Easy to understand in git history
- Can cherry-pick or revert individual features
- Follows conventional commit structure

**Next Steps**:
1. Review ai_tools and example_projects.csv
2. Execute commits in sequence
3. Push feature branch
4. Prepare for PR to main (if ready)
