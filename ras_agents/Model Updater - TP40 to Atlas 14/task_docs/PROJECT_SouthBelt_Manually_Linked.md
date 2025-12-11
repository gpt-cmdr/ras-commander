# Project Analysis: South Belt (Manually-Linked)

**Project ID**: A520-03-00-E003
**Project Name**: South Belt Stormwater Detention Basin
**Analysis Status**: IN PROGRESS

---

## Project Overview

| Attribute | Value |
|-----------|-------|
| Linkage Type | Manually-Linked (copy/paste from HMS to RAS tables) |
| HMS Version | 3.3 |
| RAS Version | 4.1 |
| Template Location | `Template Models/Manually-Linked_A520-03-00-E003_SouthBelt/` |

---

## HMS Model Structure

### Project Files
- **HMS Project**: `HMS_3.3/A100_B100/` (nested folder structure)
- **Basin File**: TBD
- **DSS Output**: TBD

### Subbasins
*To be extracted from HMS project - CRITICAL for time series matching*

| Subbasin Name | Area (sq mi) | Centroid Lat | Centroid Lon |
|---------------|--------------|--------------|--------------|
| TBD | TBD | TBD | TBD |

### DSS Output Structure
*Need to read HMS DSS file to extract available time series*

| DSS Path | Subbasin | Peak Flow (cfs) | Time to Peak |
|----------|----------|-----------------|--------------|
| TBD | TBD | TBD | TBD |

---

## RAS Model Structure

### Project Files
- **RAS Project**: `RAS_4.1/A100_00_00.prj`
- **Geometry Files**: Multiple .g## files
- **Plan Files**: Multiple .p## files (.p14 through .p19+)
- **Unsteady Files**: 6 files (.u01 through .u06)

### Unsteady Flow Files Inventory

| File | Title | BC Count (estimated) |
|------|-------|---------------------|
| .u01 | A100+A119+A120ph1_unst_10yr | Multiple |
| .u02 | TBD | TBD |
| .u03 | TBD | TBD |
| .u04 | TBD | TBD |
| .u05 | TBD | TBD |
| .u06 | TBD | TBD |

---

## Boundary Conditions Analysis

### Key Observations from .u01
- All boundaries have `Use DSS=False`
- Inline hydrograph tables with format `Flow Hydrograph= N` (N = data points)
- Example: `Flow Hydrograph= 898` means 898 time-value pairs follow

### Extracted Boundary Conditions from .u01
*Initial extraction - to be completed*

| # | River | Reach | Station Range | BC Type | Data Points | Peak Flow (est) |
|---|-------|-------|---------------|---------|-------------|-----------------|
| 1 | A100-00-00 | A100-00-00_0000 | 176737.7-166625.9 | Uniform Lateral | TBD | TBD |
| 2 | A100-00-00 | A100-00-00_0000 | 164557.7-129920.7 | Uniform Lateral | TBD | TBD |
| 3 | A100-00-00 | A100-00-00_Lower | 3858 | Gate? | TBD | TBD |
| 4 | Turkey Creek | A119-00-00 | 23601.19 | Flow Hydrograph | 898 | TBD |
| 5 | Turkey Creek | A119-00-00 | 19814.41 | TBD | TBD | TBD |
| 6 | Turkey Creek | A119-00-00 | 19345.9-15011.6 | Uniform Lateral | TBD | TBD |
| ... | ... | ... | ... | ... | ... | ... |

---

## Time Series Matching Strategy

### Goal
Match each RAS inline hydrograph table to the HMS subbasin that produced it.

### Algorithm
1. **Extract RAS time series** from inline tables
2. **Extract HMS time series** from DSS output
3. **Temporal comparison**:
   - Normalize time series to common interval
   - Compute correlation coefficient
   - Compute RMSE
   - Check peak flow magnitude match
   - Check time-to-peak alignment
4. **Spatial verification**:
   - Export HMS subbasin polygons
   - Export RAS cross-section locations
   - Check if BC location is within/adjacent to candidate subbasin
5. **Combined scoring**:
   - Temporal score (0-1)
   - Spatial score (0/1 boolean or distance-based)
   - Final match = high temporal AND spatial confirmation

### Match Confidence Levels
- **HIGH**: Temporal correlation > 0.99 AND spatial intersection confirmed
- **MEDIUM**: Temporal correlation > 0.95 OR spatial intersection confirmed
- **LOW**: Temporal correlation > 0.90, no spatial data
- **UNMATCHED**: No suitable candidate found

---

## Extracted Time Series Catalog

*To be populated during analysis*

### RAS Boundary Time Series
| BC ID | Location | Start Time | End Time | Interval | Count | Peak | Time to Peak |
|-------|----------|------------|----------|----------|-------|------|--------------|
| BC001 | A100-00-00/A100-00-00_0000/176737.7 | TBD | TBD | TBD | TBD | TBD | TBD |
| BC002 | ... | ... | ... | ... | ... | ... | ... |

### HMS Subbasin Time Series
| Subbasin | DSS Path | Start Time | End Time | Interval | Count | Peak | Time to Peak |
|----------|----------|------------|----------|----------|-------|------|--------------|
| TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

---

## Match Results

*To be populated after running matching algorithm*

| RAS BC ID | HMS Subbasin | Correlation | RMSE | Spatial Check | Confidence |
|-----------|--------------|-------------|------|---------------|------------|
| BC001 | TBD | TBD | TBD | TBD | TBD |

---

## Spatial Data

### HMS Subbasin Polygons
*To be exported using HmsGeo or manual extraction*
- Output file: `task_docs/spatial/hms_subbasins.geojson`
- CRS: EPSG:2278 (NAD83 / Texas South Central)

### RAS Cross-Section Locations
*To be exported using ras-commander*
- Output file: `task_docs/spatial/ras_cross_sections.geojson`
- CRS: EPSG:2278 (NAD83 / Texas South Central)

---

## Update Workflow

### Step 1: Complete Time Series Matching
1. Parse all .u## files
2. Extract inline hydrograph tables
3. Read HMS DSS output
4. Run matching algorithm
5. Verify with spatial check
6. Document matches

### Step 2: Update HMS Precipitation
1. Clone HMS project with Atlas 14 suffix
2. Update precipitation depths
3. Configure DSS output with clear subbasin naming

### Step 3: Run HMS
1. Execute all AEP scenarios
2. Generate new DSS output files

### Step 4: Convert RAS to DSS-Linked
1. Clone .u## files for Atlas 14 scenarios
2. Replace inline tables with DSS references:
   - Change `Use DSS=False` to `Use DSS=True`
   - Add `DSS File=` path to new HMS output
   - Add `DSS Path=` using matched subbasin name
   - Remove inline `Flow Hydrograph= N` data
3. Clone .p## plan files

### Step 5: Validate
1. Run RAS with new DSS links
2. Compare results to original manual tables

---

## Notes & Issues

1. **Complexity**: This project requires solving the subbasin-to-boundary matching problem before DSS conversion can proceed.

2. **Rivers identified**: A100-00-00, Turkey Creek (A119-00-00)

3. **HMS folder structure**: Nested A100_B100 folder - need to verify correct project location

---

## Analysis Log

| Date | Action | Findings |
|------|--------|----------|
| 2024-12-10 | Initial setup | Copied template, verified .u files, confirmed manual table format |
| 2024-12-10 | .u01 analysis | Identified multiple BC types: Flow Hydrograph, Uniform Lateral, Gate |
| 2024-12-10 | Exhaustive DSS matching | 1.46M comparisons → 855 exact matches, 100% BC identification |
| 2024-12-10 | Linkage consolidation | 35 BCs mapped to HMS subbasins (32 EXACT, 3 CLOSE) |
| **2025-12-11** | **HMS Atlas 14 update** | **HMS updated to NOAA Atlas 14: 13.5"→14.7" (+8.9%)** |
| **2025-12-11** | **Handoff documentation** | **Created HMS_ATLAS14_TO_RAS_LINKAGE.md with complete workflow** |
| | | **Status**: ✅ DSS linkages determined, ⏳ HMS execution pending |
