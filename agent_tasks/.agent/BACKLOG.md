# Backlog

This backlog is organized by roadmap phases. See `ROADMAP.md` for detailed descriptions.

## Phase 1: Quick Wins (Ready - High Priority)

### Library Improvements
- [x] `lib-001` **Real-time computation messages** - Callback support for streaming `.bco` file monitoring ✓ (v0.88.0+, Session 5)
- [ ] `lib-002` **Atlas 14 caching** - Prevent duplicate NOAA API calls
- [ ] `lib-003` **Testing suite** - Create tests for formalized functions

### Notebook Updates
- [ ] `nb-001` **Tier 1 improvements** - StormGenerator, ParameterSweep, HdfBatch, mesh utilities
- [ ] `nb-002` **Tier 2 improvements** - Project setup helpers, plan cloning configurations
- [ ] `nb-003` **Tier 3 improvements** - RasPrj convenience methods, parallel config helpers

### Documentation
- [x] `doc-001` **Deploy ReadTheDocs fix** - Commit and push .readthedocs.yaml changes (5 minutes) ✓ (Commit 6c418eb, deployed)

## Phase 2: Core Features (Ready - Medium-High Priority)

### cHECk-RAS Completion
- [ ] `check-001` **Floodway structure variants** - 8 missing checks
- [ ] `check-002` **Bridge ground data checks** - 6 missing checks
- [ ] `check-003` **Culvert flow type checks** - 5 missing checks
- [ ] `check-004` **Starting WSE method checks** - 4 missing checks
- [ ] `check-005` **Levee checks** - 6 missing checks
- [ ] `check-006` **Enhanced reporting** - PDF export, Excel export, interactive HTML

### Gauge Data Import ✅ COMPLETE (v0.86.0+)
- [x] `gauge-001` **Initial conditions from USGS** - Set starting water levels from gauge data ✓
- [x] `gauge-002` **Historic storm simulation** - Convert USGS flows to boundary conditions ✓
- [x] `gauge-003` **Forecasting model boundary conditions** - Real-time USGS data for operational forecasting ✓
- [x] `gauge-004` **Model validation** - NSE, KGE, RMSE, PBIAS metrics ✓
- [x] `gauge-005` **Example notebook** - End-to-end workflow with Bald Eagle Creek ✓

### Permutation Logic
- [ ] `perm-001` **Core API implementation** - RasPermutation class, ParameterRange, PermutationConfig
- [ ] `perm-002` **Batch splitting logic** - 99-plan limit handling
- [ ] `perm-003` **CSV tracking** - Per-batch and master logs
- [ ] `perm-004` **Example notebook** - Sensitivity analysis workflow

### DSS Grid Writing
- [ ] `dss-001` **Grid writing methods** - Extend RasDss with spatial grid support
- [ ] `dss-002` **SHG projection utilities** - EPSG:5070 conversion
- [ ] `dss-003` **AORC integration** - NetCDF → DSS conversion pipeline
- [ ] `dss-004` **Update example** - Enhance 24_aorc_precipitation.ipynb

### MRMS Precipitation Integration
- [ ] `mrms-001` **MRMS data retrieval** - Access AWS S3/GCP, GRIB2 parsing
- [ ] `mrms-002` **Spatial processing** - Clip, reproject, aggregate to model domain
- [ ] `mrms-003` **Temporal aggregation** - 2-min → hourly/sub-hourly conversion
- [ ] `mrms-004` **HEC-RAS format conversion** - Convert to DSS or GDAL/HDF
- [ ] `mrms-005` **Example notebook** - End-to-end MRMS workflow

## Phase 3: Advanced Features (Planned - Medium Priority)

### Floodway Analysis
- [ ] `fw-001` **1D floodway solver** - Iterative encroachment with surcharge convergence
- [ ] `fw-002` **1D FDT generation** - Floodway Data Table creation
- [ ] `fw-003` **2D hazard screening** - DxV computation and core identification
- [ ] `fw-004` **2D encroachment** - Null cells, raised terrain, lateral weirs
- [ ] `fw-005` **2D surcharge evaluation** - Per-cell and evaluation line averaging
- [ ] `fw-006` **2D FDT generation** - Floodway Data Table with compliance reporting
- [ ] `fw-007` **Example notebooks** - 1D and 2D workflows

### National Water Model
- [ ] `nwm-001` **NwmClient wrapper** - hydrotools.nwm-client integration
- [ ] `nwm-002` **NhdMapping utilities** - COMID/NHDPlus operations
- [ ] `nwm-003` **RatingCurve generator** - Synthetic rating curves from batch runs
- [ ] `nwm-004` **ModelCutter** - Trim models to NWM reach extents
- [ ] `nwm-005` **Example notebooks** - Forecast BC and rating curve workflows

### HMS-RAS Linked Models (TP-40 → Atlas 14)
- [ ] `hms-ras-001` **Review hms-commander history** - Identify existing Atlas 14 upgrade agents
- [ ] `hms-ras-002` **HMS outlet to RAS BC mapping** - Spatial/name-based matching
- [ ] `hms-ras-003` **Flow import from HMS DSS** - Convert HMS flows to RAS boundary conditions
- [ ] `hms-ras-004` **Linked plan generation** - Multi-event plan suite creation
- [ ] `hms-ras-005` **Agent coordination protocol** - HMS agent → RAS agent communication
- [ ] `hms-ras-006` **Validation workflow** - TP-40 vs Atlas 14 comparison
- [ ] `hms-ras-007` **Example notebook** - End-to-end HMS-RAS upgrade workflow
- [ ] `hms-ras-008` **HCFCD M3 model testing** - Validate with real linked models

## Phase 4: Long-Term (Planned - Lower Priority)

### RASMapper Sloped Interpolation
- [ ] `rmap-001` **Mesh topology extraction** - Parse from geometry HDF
- [ ] `rmap-002` **Face WSE computation** - 6+ branching code paths
- [ ] `rmap-003` **Vertex WSE computation** - Planar regression
- [ ] `rmap-004` **Triangle rasterization** - Pixel-perfect grid alignment
- [ ] `rmap-005` **Integration and validation** - Compare against RASMapper TIFs

### Documentation Revision
- [ ] `doc-002` **PRJ parsing reference** - File structure and patterns
- [ ] `doc-003` **Unsteady parsing reference** - Boundary condition formats
- [ ] `doc-004` **Steady parsing reference** - Flow distribution formats
- [ ] `doc-005` **HDF writing guide** - Safe modification patterns

## Blocked / Research

### Decompilation (Ongoing Research)
- [ ] `decomp-001` **Decompile RAS.dll** - Core .NET assembly
- [ ] `decomp-002` **Decompile RasProcess.exe** - Execution engine
- [ ] `decomp-003` **Decompile Geospatial.GDALAssist.dll** - GDAL interface
- [ ] `decomp-004` **Decompile H5Assist.dll** - HDF helper library
- [ ] `decomp-005` **Reorganize decompiled code** - Consolidate into organized structure

**Note**: Ongoing research as needed for feature development.

## Completed

- [x] `task-000` **Initialize agent coordination system** - Session 1 ✓
- [x] `task-001` **Roadmap analysis and creation** - Session 2 ✓
- [x] `task-002` **Worktree workflow documentation** - Session 2 ✓
- [x] `precip-aorc` **AORC/GDAL precipitation import** - v0.8x+ (example: 24_aorc_precipitation.ipynb) ✓
- [x] `gauge-001` to `gauge-005` **USGS Gauge Data Integration** - v0.86.0+ (Session 3, see above for details) ✓
- [x] `lib-001` **Real-time computation messages** - v0.88.0+ (Session 5, BcoMonitor + ExecutionCallback + example callbacks) ✓

---

**Total Features**: 18 major areas (15 original + MRMS + USGS forecasting BC + HMS-RAS linked)
**Total Tasks**: 73+ identified
**Estimated Timeline**: 18-24 months for full roadmap

**Cross-Repository Coordination**: HMS-RAS linked model features require coordination with hms-commander repository.

See `ROADMAP.md` for detailed descriptions, dependencies, and resource allocation guidance.
