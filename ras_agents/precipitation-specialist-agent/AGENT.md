# Precipitation Specialist Agent

**Purpose**: Production-ready reference documentation for AORC precipitation data integration, HEC-RAS 6.6 precipitation HDF format, and Atlas 14 design storms.

**Domain**: Precipitation data download, processing, and HEC-RAS boundary condition generation

**Status**: Production (migrated from docs_old with security verification)

---

## Primary Sources

**AORC Implementation**:
- `reference/aorc-implementation/IMPLEMENTATION_PLAN.md` (19.5 KB) - Complete module design for `ras_commander/precip/`
  - Module structure and architecture
  - AORC download workflow patterns
  - HDF precipitation data format specifications
  - Integration with HEC-RAS projects
- `reference/aorc-implementation/RESEARCH_NOTES.md` (10.5 KB) - Data source research
  - AORC (Analysis of Record for Calibration) overview
  - MRMS (Multi-Radar/Multi-Sensor) data
  - QPF (Quantitative Precipitation Forecast) sources
  - Data source comparison and selection criteria
- `reference/aorc-implementation/HDF_PRECIPITATION_STRUCTURE.md` (5.2 KB) - HEC-RAS HDF format requirements
  - Exact HDF dataset structure for precipitation
  - Required attributes and metadata
  - Coordinate system specifications
  - Data type and array shape requirements
- `reference/aorc-implementation/README.md` (4.5 KB) - Implementation summary and quick reference

**Format Breakthrough Documentation**:
- `reference/format-breakthrough/PRECIPITATION_HDF_FORMAT_BREAKTHROUGH.md` (12.1 KB) - **CRITICAL: HEC-RAS 6.6 format discovery**
  - Documents format change from HEC-RAS 5.x to 6.6
  - Reverse-engineering methodology (decompilation, byte-level comparison)
  - Exact specification differences
  - Validation against HEC-RAS GUI-generated files
- `reference/format-breakthrough/PRECIPITATION_INVESTIGATION_FINAL_SUMMARY.md` (5.6 KB) - Root cause analysis
  - Why previous implementations failed
  - Format evolution timeline
  - Testing methodology
- `reference/format-breakthrough/README_precipitation_investigation.md` (7.3 KB) - Investigation overview

**Test Scripts**:
- `reference/test-scripts/test_aorc_download.py` (1.8 KB) - AORC data download validation
- `reference/test-scripts/test_full_workflow.py` (2.8 KB) - End-to-end workflow test
- `reference/test-scripts/test_project_extent.py` (1.5 KB) - Project spatial extent extraction
- `reference/test-scripts/test_april2020_single_storm.py` (1.3 KB) - Single storm event test

**Working Examples**:
- `examples/24_aorc_precipitation.ipynb` - Complete AORC workflow demonstration

**Skill Reference**:
- `.claude/skills/analyzing-aorc-precipitation/` - AORC precipitation skill for automated workflows

---

## Quick Reference

### AORC Data Download Pattern

**Access AORC Precipitation Data** (Public NOAA AWS S3):
```python
import s3fs

# Anonymous access to public NOAA AORC data
s3 = s3fs.S3FileSystem(anon=True)

# AORC data path pattern
aorc_path = "s3://noaa-nws-aorc-v1.1-1km/YYYY/YYYYMMDD*.nc"

# Example: Download April 2020 storm
files = s3.glob("s3://noaa-nws-aorc-v1.1-1km/2020/20200401*.nc")
```

**Note**: No API key required - public open data access

### HEC-RAS 6.6 Precipitation HDF Structure

**Required HDF Datasets** (from HDF_PRECIPITATION_STRUCTURE.md):
```
Precip/
├── Precipitation/ (3D array: [time, rows, cols])
├── Projection/ (string: spatial reference)
├── Cell Size/ (float: grid cell size in feet)
├── Lower Left X/ (float: lower left corner X coordinate)
└── Lower Left Y/ (float: lower left corner Y coordinate)
```

**Critical Format Requirement** (HEC-RAS 6.6):
- Precipitation values in **inches** (not mm or feet)
- Time dimension FIRST: shape = [n_timesteps, n_rows, n_cols]
- Coordinates in **feet** (project coordinate system)
- Cell size in **feet**

### Common Workflows

**1. Download AORC Data for Project Extent**:
→ See `reference/test-scripts/test_project_extent.py`
- Extract project bounding box from geometry
- Buffer extent to ensure coverage
- Download AORC files for date range
- Clip to project extent

**2. Convert AORC to HEC-RAS HDF Format**:
→ See `reference/aorc-implementation/IMPLEMENTATION_PLAN.md` Module 3
- Read AORC NetCDF files
- Reproject to project coordinate system
- Convert units (mm → inches)
- Write to HEC-RAS HDF structure
- Validate against format specifications

**3. Generate Design Storm from Atlas 14**:
→ See `reference/aorc-implementation/RESEARCH_NOTES.md` Section 4
- Query NOAA Atlas 14 API for design storm depths
- Apply temporal distribution (SCS Type II, etc.)
- Generate synthetic hyetograph
- Write to HEC-RAS precipitation HDF

**4. Validate Precipitation HDF Format**:
→ See `reference/test-scripts/test_full_workflow.py`
- Check dataset structure
- Verify coordinate system
- Validate units and dimensions
- Compare against GUI-generated reference

---

## Critical Warnings

### HEC-RAS 6.6 Format Change

**CRITICAL**: HEC-RAS 6.6 changed precipitation HDF format from version 5.x

**What Changed**:
- Array dimension order (time dimension FIRST)
- Coordinate attribute names
- Required metadata attributes

**Impact**: Code written for HEC-RAS 5.x will produce invalid precipitation data for 6.6

**Solution**: Use format specifications in `reference/format-breakthrough/PRECIPITATION_HDF_FORMAT_BREAKTHROUGH.md`

**Validation**: Always validate against GUI-generated reference file for your HEC-RAS version

### Public Data Sources Only

**AORC Data**: Public open data (NOAA AWS S3, anonymous access)

**No API Keys Required**: All precipitation data sources documented here use public open data

**If Using Proprietary Data**: Not documented here - would require separate authentication and licensing

---

## Navigation Map

**Need complete implementation plan?**
→ `reference/aorc-implementation/IMPLEMENTATION_PLAN.md` (module structure, workflows)

**Need HDF format specifications?**
→ `reference/aorc-implementation/HDF_PRECIPITATION_STRUCTURE.md` (exact HDF structure)
→ `reference/format-breakthrough/PRECIPITATION_HDF_FORMAT_BREAKTHROUGH.md` (6.6 format discovery)

**Need data source comparison?**
→ `reference/aorc-implementation/RESEARCH_NOTES.md` (AORC vs MRMS vs QPF)

**Need working code examples?**
→ `reference/test-scripts/` (4 validated test scripts)
→ `examples/24_aorc_precipitation.ipynb` (complete notebook)

**Need to understand format evolution?**
→ `reference/format-breakthrough/` (investigation methodology, timeline)

---

## AORC Data Sources

### AORC v1.1 (Analysis of Record for Calibration)

**Coverage**: Continental US
**Resolution**: 1 km spatial, 1 hour temporal
**Period**: 1979-present
**Source**: NOAA National Water Model
**Access**: Public AWS S3 (anonymous)

**Data Path**:
```
s3://noaa-nws-aorc-v1.1-1km/YYYY/YYYYMMDD_HHMM00.LDASIN_DOMAIN1.nc
```

**Variables**:
- `RAINRATE`: Precipitation rate (mm/s)
- `T2D`: 2-meter air temperature (K)
- `Q2D`: 2-meter specific humidity (kg/kg)
- `U2D`, `V2D`: 10-meter wind components (m/s)
- `PSFC`: Surface pressure (Pa)
- `SWDOWN`: Downward shortwave radiation (W/m²)
- `LWDOWN`: Downward longwave radiation (W/m²)

**For HEC-RAS**: Use `RAINRATE` variable, convert to cumulative inches

### Atlas 14 (NOAA Precipitation Frequency Estimates)

**Coverage**: US (varies by region)
**Resolution**: Point estimates
**Source**: NOAA National Weather Service
**Access**: Public API (no authentication)

**Use Case**: Design storm generation (2-year, 10-year, 100-year, etc.)

**API Endpoint**:
```
https://hdsc.nws.noaa.gov/cgi-bin/hdsc/new/cgi_readH5.py
```

**Parameters**: Latitude, longitude, storm duration, recurrence interval

---

## Implementation Status

### ras_commander/precip/ Module Status

**Current** (as of migration):
- Module structure defined in IMPLEMENTATION_PLAN.md
- Format specifications documented
- Test scripts validated
- HEC-RAS 6.6 format discovery complete

**Implementation Priority** (from IMPLEMENTATION_PLAN.md):
1. Module 1: Project extent extraction ✅ (test_project_extent.py)
2. Module 2: AORC download ✅ (test_aorc_download.py)
3. Module 3: AORC to HEC-RAS conversion (planned)
4. Module 4: Atlas 14 integration (planned)
5. Module 5: Design storm generation (planned)

**See**: `reference/aorc-implementation/IMPLEMENTATION_PLAN.md` for complete roadmap

---

## Key Insights

### Why This Research Matters

**Format Discovery**:
- HEC-RAS 6.6 format was undocumented
- Reverse-engineering via decompilation revealed exact specifications
- Validation against GUI output confirms accuracy

**Data Source Selection**:
- AORC chosen for continuous historical record
- Atlas 14 for design storm depths
- Both are public open data (no licensing required)

**Workflow Validation**:
- Test scripts demonstrate working implementation
- Each script tests specific component
- End-to-end test validates complete workflow

### Research Methodology

**Format Investigation**:
1. Create reference HDF using HEC-RAS GUI
2. Decompile RAS 6.6 assemblies to understand format
3. Byte-level comparison of programmatic vs GUI output
4. Iterate until pixel-perfect match achieved

**Data Source Research**:
1. Evaluate multiple precipitation data sources
2. Compare coverage, resolution, latency, cost
3. Test download and processing workflows
4. Select best option for each use case

**Validation Approach**:
1. Unit tests for individual components
2. Integration test for complete workflow
3. Comparison against HEC-RAS GUI output
4. Visual verification of results in HEC-RAS

---

## Migration Notes

**Source**: `docs_old/precip/` (80 KB) + `docs_old/precipitation_investigation/` (252 KB)

**Migrated**: 2025-12-12

**Content**: 11 files (~47 KB)
- 4 AORC implementation documents
- 4 test scripts
- 3 format breakthrough documents

**Excluded**:
- ❌ `LOCAL_REPOS.md` (contained local development file paths `C:\GH\`)
- ❌ Large test output files (generated data)
- ❌ Additional investigation scripts (available in source if needed)

**Security Verification**: PASSED ✅
- Zero API keys
- Zero credentials
- Zero client data
- Zero proprietary information
- Only public open data access patterns documented

**Original Content**: Available in gitignored `docs_old/` for development reference

---

**Last Updated**: 2025-12-12
**Status**: Production Ready ✅
**Security**: Audited and Verified ✅
**Public Data**: AORC (NOAA AWS S3), Atlas 14 (NOAA API) ✅
**Coverage**: AORC download, HEC-RAS 6.6 format, design storms ✅
