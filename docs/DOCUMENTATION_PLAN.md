# Documentation Improvement Plan

This document tracks remaining documentation improvements based on migration review.

## Completed (Rounds 1 & 2)

- [x] Static class pattern warning
- [x] RASMapper flag inversion warning
- [x] Input flexibility with `@standardize_input`
- [x] PsExec setup checklist, Group Policy, troubleshooting
- [x] Count interpretation rules table
- [x] Manning's n format variations
- [x] Edge cases and validation strategies
- [x] Missing HDF classes (HdfXsec, HdfInfiltration, HdfUtils)
- [x] `@standardize_input` decorator documentation
- [x] `ExecutionResult` dataclass documentation
- [x] Docker troubleshooting section
- [x] FORTRAN-era context and visual diagrams
- [x] Workflows and patterns guide

---

## Priority 1: High-Value User Content ✓

These additions have direct impact on users trying to accomplish tasks.

### 1.1 Boundary Conditions Guide ✓
**File:** `docs/user-guide/boundary-conditions.md`
**Status:** Completed
**Content:**
- [x] Accessing `ras.boundaries_df`
- [x] Filtering by boundary type
- [x] Visualizing boundary data
- [x] Using `RasUnsteady.extract_tables()` for modification
- [x] Limitations (read-only via df)

### 1.2 RASMapper & Spatial Data Guide ✓
**File:** `docs/user-guide/spatial-data.md`
**Status:** Completed
**Content:**
- [x] Using `ras.rasmap_df`
- [x] Terrain/land cover/soil layers
- [x] Manning's n calibration workflow
- [x] Infiltration data handling

### 1.3 DataFrame Reference Examples ✓
**File:** Added to `docs/getting-started/project-initialization.md`
**Status:** Completed
**Content:**
- [x] Example outputs for `ras.plan_df`, `ras.flow_df`, etc.
- [x] Common query patterns
- [x] Column descriptions

---

## Priority 2: API Completeness ✓

These fill gaps in the API reference but won't block most users.

### 2.1 RasControl Complete Documentation ✓
**File:** `docs/api/core.md`
**Status:** Completed
**Content:**
- [x] `get_comp_msgs()` with fallback behavior
- [x] "Max WS" timestep explanation
- [x] RasControl vs RasCmdr comparison table
- [x] Version support details

### 2.2 RasUtils Method Documentation ✓
**File:** `docs/api/core.md`
**Status:** Completed
**Content:**
- [x] ~25 utility methods currently undocumented
- [x] File operations, path handling, data conversion
- [x] Statistical analysis methods (RMSE, NSE, etc.)

### 2.3 HDF Internal Path References ✓
**File:** `docs/reference/hdf-structure.md`
**Status:** Completed
**Content:**
- [x] Complete HDF path table for all data types
- [x] Example paths for common queries
- [x] Cross-reference with methods

---

## Priority 3: Developer/Advanced Content ✓

Useful for those extending the library or doing advanced work.

### 3.1 Implementation Patterns ✓
**File:** Add to `docs/reference/geometry-parsing.md`
**Status:** Completed
**Content:**
- [x] State machine patterns for section parsing
- [x] Backup-modify-write patterns
- [x] HDF reading patterns

### 3.2 Quick Reference Tables ✓
**File:** `docs/reference/quick-reference.md` (new)
**Status:** Completed
**Content:**
- [x] Common section keywords
- [x] HDF path lookup table
- [x] Format type cheat sheet

### 3.3 DockerWorker Advanced Parameters ✓
**File:** `docs/parallel-compute/worker-types.md`
**Status:** Completed
**Content:**
- [x] `docker_host`, `share_path`, `remote_staging_path`
- [x] `max_runtime_minutes`, `cpu_limit`, `memory_limit`
- [x] `preprocess_on_host` detailed explanation

---

## Estimated Effort

| Priority | Items | Est. Lines | Impact | Status |
|----------|-------|------------|--------|--------|
| P1 | 3 items | ~400 lines | High - user workflows | ✓ Complete |
| P2 | 3 items | ~300 lines | Medium - API completeness | ✓ Complete |
| P3 | 3 items | ~200 lines | Low - advanced users | ✓ Complete |

**Total:** ~900 lines of documentation

---

## Recommendation

**Current Status:** All priorities (P1 + P2 + P3) complete - full documentation parity achieved.

**Remaining:** None.

**Complete:** All items for full parity with old documentation.

---

## Notes

- Old docs in `docs_old/` can be deleted after P1+P2 completion
- Some content may be auto-generated via mkdocstrings if docstrings are good
- Consider whether all RasUtils methods need user-facing docs vs code comments
