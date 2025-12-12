# ras-commander Development Roadmap

**Generated**: 2025-12-10
**Based on**: feature_dev_notes/ and planning_docs/ analysis

This roadmap synthesizes all work-in-progress and completed features from the repository's development folders. It provides a strategic plan for advancing ras-commander capabilities organized by priority, complexity, and estimated timelines.

---

## Executive Summary

**Current Status**: ras-commander v0.87.1 with 21 major feature areas identified (3 new features added 2025-12-10)

| Category | Features | Status | Priority |
|----------|----------|--------|----------|
| **Complete & Integrated** | 4 | ✅ Done | - |
| **In Progress (50%+)** | 3 | 🔄 Active | High |
| **Planning Complete** | 12 | 📋 Ready | Medium-High |
| **Research Phase** | 1 | 🔬 Early | Low |
| **NEW (Session 4)** | 3 | ⭐ New | High-Medium |

**Total Estimated Work**: 22-28 months for full implementation across all priorities

**Note**: This roadmap also coordinates with **hms-commander** repository for HMS-RAS linked model workflows.

**Recent Additions (2025-12-10)**:
- ⭐ **Probabilistic Flood Risk Analysis** (Phase 2.3) - AEP mapping, quantile surfaces
- ⭐ **2D Model Quality Assurance** (Phase 3.2) - Extends RasCheck to 2D models
- ⭐ **1D Floodplain Mapping** (Phase 3.1b) - Automates 1D inundation mapping

---

## Feature Status Matrix

| Feature | Status | Priority | Complexity | LOC Est. | Timeline | Phase |
|---------|--------|----------|------------|----------|----------|-------|
| **DSS Integration** | 100% ✅ | - | High | 730 | Complete | v0.82.0+ |
| **HCFCD M3 Models** | 100% ✅ | Low | Low | 300 | Complete | Integrated |
| **ReadTheDocs Fix** | 100% ✅ | - | Low | 10 | Complete | Ready to deploy |
| **cHECk-RAS** | 83% 🔄 | High | Medium | 8,700 | 3-5 weeks | Phase 2 |
| **Gauge Data Import** | 50% 🔄 | High | High | 1,500+ | 4-6 weeks | Phase 2 |
| **Library Improvements** | 64% 🔄 | High | Low-Med | 1,200 | 2-3 weeks | Phase 1 |
| **RASMapper Interpolation** | 40% 🔄 | Low | Very High | 1,600+ | 8-10 weeks | Phase 4 |
| **Permutation Logic** | 0% 📋 | Medium | Medium | 800+ | 3-4 weeks | Phase 2 |
| **Floodway Analysis** | 0% 📋 | Medium | High | 2,000+ | 6-8 weeks | Phase 3 |
| **National Water Model** | 0% 📋 | Medium | High | 2,000+ | 6-8 weeks | Phase 3 |
| **Notebook Updates** | 0% 📋 | High | Low | 500+ | 2-3 weeks | Phase 1 |
| **DSS Grid Writing** | 0% 📋 | Medium | Medium | 400+ | 2-3 weeks | Phase 2 |
| **Documentation Revision** | 0% 📋 | Low | Low | 1,000+ | 2-3 weeks | Phase 4 |
| **Decompilation** | 0% 🔬 | Low | High | Ongoing | Variable | Research |
| **Precipitation AORC/GDAL** | 100% ✅ | - | High | Done | Complete | v0.8x+ |
| **MRMS Precipitation** | 0% 📋 | Medium | Medium | 600+ | 3-4 weeks | Phase 2 |
| **USGS Forecasting BC** | 0% 📋 | High | Medium | 400+ | 2-3 weeks | Phase 2 |
| **HMS-RAS Linked Models** | 0% 📋 | High | High | 1,200+ | 6-8 weeks | Phase 3 |

---

## Phase 1: Quick Wins & High-ROI Features (4-6 weeks)

**Goal**: Complete high-value, low-complexity features with immediate user benefit

### 1.1 Library Improvements - PRIORITY 1
**Status**: 64% complete (16/25 items)
**Effort**: 2-3 weeks
**Complexity**: Low-Medium

**Remaining Tasks**:
- Real-time computation messages (callback support for streaming `.bco` file monitoring)
- Caching for Atlas 14 downloads (prevent duplicate API calls)
- Testing suite for formalized functions

**Completed**:
- ✅ HdfMesh spatial utilities (`find_nearest_face()`, `find_nearest_cell()`, `get_faces_along_profile_line()`)
- ✅ StormGenerator module (NOAA Atlas 14, Alternating Block Method)
- ✅ RasPlan enhancements (`clone_plan()` with advanced parameters)
- ✅ RasPrj convenience methods (`get_plans_with_results()`, `get_plan_info()`)

**Impact**: 40-60% reduction in notebook code, cleaner API, better DX

---

### 1.2 Notebook Updates - PRIORITY 2
**Status**: 0% (planning complete)
**Effort**: 2-3 weeks
**Complexity**: Low

**Key Improvements**:
- Tier 1 (Critical): StormGenerator, ParameterSweep, HdfBatch, mesh utilities
- Tier 2 (High): Project setup helpers, plan cloning configurations
- Tier 3 (Medium): RasPrj convenience methods, parallel config helpers

**Impact**: 200+ LOC saved per notebook, improved maintainability

---

### 1.3 ReadTheDocs Deployment - PRIORITY 3
**Status**: 100% (code ready, deployment pending)
**Effort**: 5 minutes
**Complexity**: Trivial

**Actions**:
1. Commit `.readthedocs.yaml` changes (symlink → copy)
2. Update `.gitignore` for `docs/notebooks/`
3. Push to trigger rebuild

**Impact**: Fixes 0-cell notebook rendering issue on ReadTheDocs

---

## Phase 2: Core Feature Completion (8-12 weeks)

**Goal**: Complete partially-implemented features and high-priority new capabilities

### 2.1 cHECk-RAS Quality Assurance - PRIORITY 1
**Status**: 83% complete (155/187 checks)
**Effort**: 3-5 weeks
**Complexity**: Medium

**Implementation Status**:
- ✅ NT (Manning's n): 17/17 checks (100%)
- ✅ XS (Cross Sections): 54/59 checks (92%)
- ✅ Profiles: 6/6 checks (100%)
- 🔄 Structures: 52/80 checks (65%)
- 🔄 Floodways: 27/45 checks (60%)

**Remaining High-Priority Gaps**:
1. Floodway structure variants (8 checks)
2. Bridge ground data variants (6 checks)
3. Culvert flow type checks (5 checks)
4. Starting WSE method checks (4 checks)
5. Levee station/elevation checks (6 checks)

**Enhancement Opportunities**:
- PDF export capability
- Excel export for check results
- Interactive HTML navigation
- Cross section/structure summary tables

**Dependencies**: None (all infrastructure in place)

**Deliverables**:
- `ras_commander/check/` subpackage complete to 95%+ coverage
- Example notebook: `examples/28_quality_assurance_rascheck.ipynb`
- Full documentation in CLAUDE.md

---

### 2.2 Gauge Data Import (USGS Integration) - PRIORITY 2
**Status**: 50% complete (gauge matching done)
**Effort**: 4-6 weeks
**Complexity**: High

**Completed**:
- ✅ Gauge matching module (537 LOC)
  - `transform_gauge_coords()` - CRS conversion
  - `match_gauge_to_cross_section()` - 1D XS matching
  - `match_gauge_to_2d_area()` - 2D area matching
  - `auto_match_gauges()` - Batch matching

**Remaining Tasks**:
1. **Initial Conditions from USGS Data** (2 weeks)
   - Set HEC-RAS starting water levels from observed gauge data
   - Auto-map gauge stage to XS initial conditions

2. **Historic Storm Simulation** (1-2 weeks)
   - Convert USGS flow hydrographs to boundary conditions
   - Integration with RasUnsteady for flow file generation

3. **Forecasting Model Boundary Conditions** (2-3 weeks) **NEW**
   - Real-time USGS gauge data retrieval
   - Automated boundary condition setup for forecast models
   - Integration with NWM/operational workflows
   - Flow/stage time series conversion to HEC-RAS BC format

4. **Model Validation** (2 weeks)
   - Compare HEC-RAS vs observed USGS data
   - Metrics: NSE, KGE, RMSE, PBIAS
   - Time series alignment and statistics

5. **Example Notebook** (1 week)
   - End-to-end workflow: USGS retrieval → BC setup → simulation → validation
   - Bald Eagle Creek test case

**Dependencies**:
- dataretrieval>=1.0.0 (USGS water data)
- pygeohydro (optional, USGS integration)
- pynhd (optional, stream network)

**Deliverables**:
- `ras_commander/usgs/` subpackage
- Example: `examples/29_usgs_gauge_data_integration.ipynb`

**Use Cases**:
- Historic event reconstruction
- Model calibration and validation
- **Operational forecasting with real-time boundary conditions**

---

### 2.3 Probabilistic Flood Risk Analysis - PRIORITY 3 ⭐ NEW
**Status**: 0% (research complete, reference implementations identified)
**Effort**: 4-6 weeks
**Complexity**: High
**Feature Gap**: CRITICAL - No probabilistic post-processing capability

**Purpose**: Enable Annual Exceedance Probability (AEP) mapping and quantile surface generation from multiple HEC-RAS scenarios

**Reference Implementations**:
- ✅ **fema-ffrd/multi-ras-to-aep-mapper** (Python) - Frequency grid generation
- ✅ **HEC Quantile-Map-Calculator** (C#/.NET, Official USACE) - Production quantile mapping

**Key Capabilities**:
1. **Multi-Plan Aggregation** - Combine results from ensemble HEC-RAS runs
2. **Frequency Grid Generation** - Create gridded AEP surfaces
3. **Quantile Map Calculation** - Extract depth/WSE quantiles (10%, 50%, 90%)
4. **Official Tool Wrapper** - Python CLI for HEC Quantile-Map-Calculator
5. **Probabilistic Visualization** - Maps showing flood frequency

**Implementation Tasks**:
1. **Analyze FEMA tool** (1 week)
   - Clone multi-ras-to-aep-mapper repository
   - Document frequency grid algorithm
   - Extract core methodology

2. **Design `ras_commander.probabilistic` module** (1 week)
   - `RasAEP` class for frequency grids
   - `RasQuantile` wrapper for official HEC tool
   - Multi-scenario aggregation functions

3. **Implement Core Functionality** (2-3 weeks)
   - Frequency grid generation (Python native)
   - Quantile extraction methods
   - C#/.NET tool wrapper (subprocess integration)
   - Result visualization helpers

4. **Testing & Validation** (1-2 weeks)
   - Test on HCFCD multi-event scenarios
   - Validate against FEMA standards
   - Compare Python vs official HEC tool outputs

**Proposed API**:
```python
from ras_commander.probabilistic import RasAEP, RasQuantile

# Run multiple scenarios
scenarios = ["10yr", "25yr", "50yr", "100yr", "500yr"]
for scenario in scenarios:
    RasCmdr.compute_plan(scenario)

# Option 1: Python native frequency grids
aep = RasAEP()
aep.load_scenarios(scenarios, variable="Water Surface")
frequency_grid = aep.compute_frequency_grid()
quantiles = aep.get_quantile_maps([0.1, 0.5, 0.9])

# Option 2: Official HEC tool (wrapper)
hec_quantile = RasQuantile()
hec_quantile.run(
    plan_hdfs=["10yr.hdf", "50yr.hdf", "100yr.hdf"],
    quantiles=[0.1, 0.5, 0.9],
    output_dir="quantile_results"
)
```

**Dependencies**:
- .NET 7.0+ SDK (for official HEC tool, optional)
- numpy, scipy (for Python frequency grid calculations)

**Deliverables**:
- `ras_commander/probabilistic/` subpackage
- Example: `examples/XX_probabilistic_flood_mapping.ipynb`
- Integration guide for HEC Quantile-Map-Calculator

**Use Cases**:
- FEMA flood insurance studies (AEP requirements)
- Climate change adaptation planning (ensemble analysis)
- Regulatory compliance (frequency-based flood mapping)
- Risk assessment and uncertainty quantification

---

### 2.4 Permutation Logic for Sensitivity Analysis - PRIORITY 4
**Status**: 0% (architecture documented, reference implementation exists)
**Effort**: 3-4 weeks
**Complexity**: Medium

**Purpose**: Generate multiple HEC-RAS plan variations for sensitivity analysis with sophisticated 99-plan limit handling

**Reference Implementation**:
- TECH WARMS Dashboard: `permutation_utils.py`, `permutation_runner.py`, `breach_io.py`
- Proven algorithms for Cartesian product generation, batch splitting, CSV tracking

**Proposed ras-commander API**:
```python
class RasPermutation:
    @staticmethod
    def generate(
        project_path: Path,
        config: PermutationConfig,
        progress_callback: Callable = None
    ) -> PermutationResult

class ParameterRange:
    minimum: float
    maximum: float
    step: float

class PermutationConfig:
    parameters: Dict[str, ParameterRange]
    max_plans_per_batch: int = 99
```

**Key Capabilities**:
1. Parameter range definition (min/max/step)
2. Automatic 99-plan batch splitting
3. Cross-structure permutation generation
4. CSV tracking (per-batch + master logs)
5. Integration with `RasCmdr.compute_parallel()`

**Use Cases**:
- Breach parameter sensitivity (width, elevation, formation time)
- Manning's n roughness variations
- Boundary condition ranges
- Geometry modifications

**Deliverables**:
- `ras_commander/permutation/` subpackage
- Example: `examples/30_sensitivity_analysis_permutations.ipynb`

---

### 2.5 DSS Grid Writing (AORC → DSS) - PRIORITY 5
**Status**: 0% (research complete, infrastructure in place)
**Effort**: 2-3 weeks
**Complexity**: Medium

**Purpose**: Convert AORC precipitation from NetCDF to DSS format for HEC-RAS 6.6 boundary conditions

**Current Alternative** ✅:
- **HDF/GDAL Gridded Precipitation** is working and supported in HEC-RAS 6.3.1+
- Example notebook: `examples/24_aorc_precipitation.ipynb`
- Status: Production-ready
- DSS grid writing remains a future enhancement for legacy workflow compatibility

**Infrastructure Available**:
- ✅ HEC Monolith libraries (via RasDss module)
- ✅ `hec.heclib.grid.GriddedData` class with `storeGriddedData()` method
- ✅ NetCDF reading (xarray, AORC examples exist)

**Implementation Tasks**:
1. Extend RasDss with grid writing methods
2. SHG projection (EPSG:5070) conversion utilities
3. AORC → DSS metadata mapping
4. Batch writing for multi-timestep grids

**Integration**:
- Connects to existing `PrecipAorc` module (NetCDF reading)
- Provides alternative to HDF/GDAL precipitation import for users preferring DSS format

**Deliverables**:
- `RasDss.write_spatial_grid()` method
- Update `examples/24_aorc_precipitation.ipynb` with DSS option

---

### 2.6 Geospatial Data Downloaders - PRIORITY 4 ⭐ NEW
**Status**: 33% (terrain research complete, NLCD/SSURGO planned)
**Effort**: 8-12 hours total (3-4 hrs each)
**Complexity**: Medium
**Feature Gap**: CRITICAL - No automated geospatial data acquisition

**Purpose**: Automate download of critical geospatial datasets for HEC-RAS project setup using project spatial extents

**Components**:

**2.6.1 USGS 3DEP Terrain Downloader** (Research Complete - Priority HIGH)
- **Status**: Research complete (py3dep integration guide ready)
- **Effort**: 2-3 hours
- **Source**: `feature_dev_notes/data-downloaders/terrain/py3dep-specialist.md` (451 lines)
- **Capabilities**:
  - Download USGS 3DEP DEMs (1m to 60m resolution)
  - Project extent-based spatial queries with automatic buffering
  - Terrain derivatives (slope, aspect, hillshade)
  - Integration with HyRiver ecosystem (py3dep)
- **Proposed API**:
  ```python
  from ras_commander.terrain import download_dem

  dem_path = download_dem(
      project_folder="/path/to/project",
      resolution=10,  # meters
      buffer_miles=1.0,
      output_folder="terrain"
  )
  ```

**2.6.2 NLCD Land Cover Downloader** (Planning - Priority MEDIUM)
- **Status**: Planning complete
- **Effort**: 3-4 hours
- **Source**: `feature_dev_notes/data-downloaders/nlcd/PLANNING.md`
- **Capabilities**:
  - Download NLCD rasters (30m resolution, 2001-2021)
  - Project extent-based download
  - Land cover class to Manning's n mapping (Anderson/Chow)
  - RASMapper-compatible layer export
- **Proposed API**:
  ```python
  from ras_commander.landcover import download_nlcd, generate_mannings_from_nlcd

  nlcd_path = download_nlcd(project_folder="/path/to/project", year=2021)
  mannings_raster = generate_mannings_from_nlcd(nlcd_path, mapping="anderson")
  ```

**2.6.3 USGS SSURGO Soils Downloader** (Planning - Priority MEDIUM)
- **Status**: Planning complete
- **Effort**: 4-5 hours
- **Source**: `feature_dev_notes/data-downloaders/ssurgo/PLANNING.md`
- **Capabilities**:
  - Download gSSURGO rasters (10m resolution)
  - Extract soil properties (Ksat, porosity, HSG)
  - Generate Green-Ampt infiltration parameters
  - Generate SCS Curve Numbers (with NLCD integration)
  - RASMapper-compatible infiltration layer export
- **Proposed API**:
  ```python
  from ras_commander.soils import download_ssurgo, generate_greenampt_from_ssurgo

  ssurgo_path = download_ssurgo(project_folder="/path/to/project", data_type="gSSURGO")
  greenampt_params = generate_greenampt_from_ssurgo(ssurgo_path, method="rawls_brakensiek")
  ```

**Existing Soils Tool**:
- ✅ Soil Stats Tool (post-processing) - Analyzes soils already imported into RASMapper
- Location: `feature_dev_notes/data-downloaders/soils-post-processing/`

**Integration Workflow**:
```python
from ras_commander import init_ras_project
from ras_commander.data import download_all_geospatial

# One-command project data setup
data_paths = download_all_geospatial(
    project_folder="/path/to/project",
    terrain_resolution=10,    # 10m DEM
    nlcd_year=2021,           # Latest land cover
    ssurgo_type="gSSURGO",    # Gridded soils
    buffer_miles=1.0
)
```

**Dependencies**:
- `py3dep` (HyRiver) - USGS 3DEP elevation data
- `requests`, `rasterio` - Already in ras-commander
- USGS TNM API, MRLC API, NRCS SDA API (public access)

**Use Cases**:
- Automated project setup (terrain + roughness + infiltration)
- Ungauged watershed modeling (derive parameters from geospatial data)
- Baseline parameter estimation (calibration starting point)
- Multi-scenario analysis with land cover change

**Deliverables**:
- `ras_commander/terrain/` or `ras_commander/data/terrain.py`
- `ras_commander/landcover/` or `ras_commander/data/landcover.py`
- `ras_commander/soils/` or `ras_commander/data/soils.py`
- Example notebooks for each downloader + integrated workflow
- Skills for automated data acquisition

**Timeline**:
- Phase 1 (Terrain): Q1 2026 (2-3 hours)
- Phase 2 (NLCD): Q2 2026 (3-4 hours)
- Phase 3 (SSURGO): Q2-Q3 2026 (4-5 hours)
- Phase 4 (Integration): Q3 2026 (2 hours)

---

## Phase 3: Advanced Feature Development (12-16 weeks)

**Goal**: Implement complex, specialized features requiring significant research and development

### 3.1 Floodway Analysis Automation - PRIORITY 1
**Status**: 0% (research/planning complete)
**Effort**: 6-8 weeks
**Complexity**: High

**Purpose**: Automate FEMA-compliant floodway analysis for 1D, 2D, and hybrid HEC-RAS models

**FEMA Requirements** (per November 2023 Guidance):
1. **1D Floodway**: Equal-conveyance encroachment, iterative surcharging to allowable limits (typically ≤1.0 ft)
2. **2D Floodway**: DxV/hazard-based encroachment with evaluation line averaging
3. **No-Rise Certification**: Effective vs proposed comparison (0.00 ft surcharge requirement)

**1D Workflow** (3-4 weeks):
1. Clone base plan for floodway iterations
2. Set encroachment stations on cross sections
3. Iteratively run plans, adjust encroachments to converge to allowable surcharge
4. Generate Floodway Data Table (FDT)

**2D Workflow** (4-5 weeks, multi-stage):
- **Stage 1**: Hazard screening (compute DxV, identify core via thresholds)
- **Stage 2**: Encroachment implementation (null cells, raised terrain, or lateral weirs)
- **Stage 3**: Surcharge evaluation (per-cell, evaluation line averaging)
- **Stage 4**: Output generation (floodway polygons, FDT, compliance reports)

**Proposed API**:
```python
class RasFloodway:
    # 1D Methods
    @staticmethod
    def solve_1d_floodway(base_plan, fw_plan, allowed_surcharge_ft)
    @staticmethod
    def build_fdt_1d(base_plan, fw_plan)

    # 2D Methods
    @staticmethod
    def compute_dv_metrics(base_plan, mesh_name)
    @staticmethod
    def build_initial_floodway_polygon(dv_gdf, dv_threshold)
    @staticmethod
    def create_2d_floodway_plan(base_plan, encroachment_poly, method)
    @staticmethod
    def evaluate_2d_floodway(base_plan, fw_plan, eval_lines_gdf)
    @staticmethod
    def build_fdt_2d(...)
```

**Leverages Existing ras-commander Capabilities**:
- Plan/geometry cloning (`RasPlan`, `RasGeometry`)
- Parallel execution (`RasCmdr.compute_parallel()`)
- HDF mesh access (`HdfMesh.get_mesh_cell_polygons()`)
- WSE/depth time series (`HdfResultsMesh`)
- Cross section results (`HdfResultsXsec`)

**Test Data**: Bald Eagle Creek multi-2D project

**Deliverables**:
- `ras_commander/floodway/` subpackage
- Example: `examples/31_floodway_analysis_1d.ipynb`
- Example: `examples/32_floodway_analysis_2d.ipynb`

---

### 3.1b 1D Floodplain Mapping - PRIORITY 1b ⭐ NEW
**Status**: 0% (research complete, reference implementations identified)
**Effort**: 4-6 weeks
**Complexity**: Medium-High
**Feature Gap**: Moderate - Manual GIS process needs automation

**Purpose**: Automate floodplain inundation mapping from HEC-RAS 1D cross-sectional output

**Problem**: HEC-RAS 1D produces cross-sectional water surface elevations, but creating continuous floodplain extent maps requires:
- Interpolation between cross sections
- Terrain comparison (WSE vs ground elevation)
- Raster generation for spatial analysis
- FEMA compliance for floodplain delineations

**Reference Implementations**:
- ✅ **dunnand2/Floodplain-Inundation-Mapping** (ArcPy) - Primary reference
- ✅ **mikebannis/FHAD_Tools** - FEMA compliance toolkit
- ✅ **HydroSynapseKR/hecras-tools** - Geometry parsing library
- ✅ **quantum-dan/hecxs** (R) - Cross-section visualization

**Key Capabilities**:
1. **WSE Interpolation** - Create continuous surface from 1D cross-section data
2. **Terrain Comparison** - Compare WSE with DEM to generate depth rasters
3. **FEMA Compliance** - QA checks from FHAD_Tools
4. **Multiple Output Formats**:
   - GeoTIFF rasters (depth, extent, WSE)
   - Shapefiles/GeoPackage polygons
   - Cloud-Optimized GeoTIFF (COG)

**Implementation Tasks**:
1. **Research Phase** (1-2 weeks)
   - Clone and analyze reference repositories
   - Document interpolation algorithms
   - Extract FEMA standards from FHAD_Tools

2. **Core Development** (2-3 weeks)
   - Cross-section WSE extraction from HDF
   - Interpolation algorithm (TIN, IDW, or custom)
   - Terrain comparison (WSE - DEM = depth)
   - Raster/vector generation

3. **FEMA Compliance** (1 week)
   - Implement FHAD_Tools QA checks
   - Metadata generation
   - Quality assurance reporting

4. **Testing & Examples** (1 week)
   - Test on HCFCD M3 Models (1D steady flow)
   - Create example notebook
   - Performance benchmarking

**Proposed API**:
```python
from ras_commander import HdfResultsPlan
from ras_commander.floodplain import RasFloodplain1D

# Extract WSE from HDF
hdf = HdfResultsPlan("plan.hdf")
wse_df = hdf.get_steady_wse(profile="100yr")

# Generate floodplain
floodplain = RasFloodplain1D(dem_path="terrain.tif")
floodplain.interpolate_wse(wse_df, method="tin")
floodplain.generate_depth_raster(output="depth_100yr.tif")
floodplain.generate_extent_polygon(output="extent_100yr.shp")
```

**Technology Decisions**:
- **Primary**: GDAL/Rasterio (open source, widely accessible)
- **Optional**: ArcPy support (for users with ArcGIS licenses)
- **Interpolation**: Study dunnand2 approach, implement GDAL version

**Deliverables**:
- `ras_commander/floodplain/` subpackage
- Example: `examples/XX_1d_floodplain_mapping.ipynb`
- FEMA compliance guide documentation

**Use Cases**:
- 1D model floodplain delineation (no 2D terrain required)
- FEMA mapping support
- Rapid flood extent estimation
- GIS-ready output generation

---

### 3.2 2D Model Quality Assurance - PRIORITY 2 ⭐ NEW
**Status**: 0% (concept phase, builds on RasCheck foundations)
**Effort**: 4-6 weeks
**Complexity**: Medium-High
**Related**: Extends existing cHECk-RAS work (Phase 2.1)

**Purpose**: Apply RasCheck quality assurance principles to HEC-RAS 2D models with best practices validation

**Rationale**:
- Current cHECk-RAS (Phase 2.1) focuses on 1D models
- 2D models have unique QA requirements (mesh quality, Manning's n rasters, boundary conditions)
- FEMA and industry best practices for 2D modeling need systematic checking

**Key Validation Areas**:

**1. Mesh Quality Checks**:
- Cell size consistency and gradation
- Aspect ratio limits (< 5:1 recommended)
- Internal angle constraints (30°-150° range)
- Break line alignment with mesh faces
- Refinement region coverage

**2. Manning's n Raster Validation**:
- Land cover classification completeness
- Manning's n value ranges (physical limits)
- Spatial resolution consistency with mesh
- Missing data / null value checks
- Manning's regions vs raster comparison

**3. Boundary Condition Checks**:
- 2D flow area connections (SA/2D, 2D/2D)
- Boundary condition line placement
- Time series completeness
- Flow vs stage boundary appropriateness
- Normal depth slope validation

**4. Geometry Validation**:
- Terrain resolution adequacy
- Elevation data gaps
- Storage area volume curves
- Lateral structure configurations
- Inline structure placement

**5. Computational Settings**:
- Time step stability (Courant number)
- Warm-up period adequacy
- Mapping interval appropriateness
- Solver tolerance settings

**Implementation Approach**:
1. **Analyze existing `RasCheck` class** (1 week)
   - Extract core QA principles and patterns
   - Identify reusable infrastructure
   - Document architecture for extension

2. **Research 2D best practices** (1 week)
   - FEMA 2D modeling guidance
   - Industry standards (ASCE, FHWA)
   - HEC-RAS 2D user manual QA sections
   - Academic literature review

3. **Develop 2D check modules** (2-3 weeks)
   - `RasCheck2DMesh` - Mesh quality validation
   - `RasCheck2DMannings` - Roughness validation
   - `RasCheck2DBoundary` - BC validation
   - `RasCheck2DGeometry` - Terrain and structure checks
   - `RasCheck2DComputational` - Settings validation

4. **Integration and testing** (1-2 weeks)
   - Test on diverse 2D projects
   - Create comprehensive check report template
   - Develop example notebook

**Proposed API**:
```python
from ras_commander.check import RasCheck2D

# Initialize 2D QA checker
checker = RasCheck2D(project_path, plan="01")

# Run all 2D checks
results = checker.run_all_checks()

# Or run specific check categories
mesh_results = checker.check_mesh_quality()
mannings_results = checker.check_mannings_raster()
bc_results = checker.check_boundary_conditions()

# Generate report
checker.export_report("2d_qa_report.html")
```

**Reference Sources**:
- Existing `cHECk-RAS/` feature folder
- FEMA 2D modeling guidance documents
- `floodway analysis/fema_rm-floodway-analysis-and-mapping-nov-2023.pdf`

**Deliverables**:
- `ras_commander/check/ras_check_2d.py` module
- Example: `examples/XX_2d_model_quality_assurance.ipynb`
- Best practices documentation in CLAUDE.md
- HTML report template for 2D checks

**Dependencies**:
- Extends existing `ras_commander.check` infrastructure
- Leverages `HdfMesh`, `RasGeometry`, `RasMap` classes

---

### 3.3 National Water Model Integration - PRIORITY 3
**Status**: 0% (planning complete)
**Effort**: 6-8 weeks
**Complexity**: High

**Purpose**: Enable HEC-RAS simulations driven by NOAA National Water Model forecasts

**Key Workflows**:
1. **NWM Forecast → HEC-RAS BC**: Convert COMID-based forecasts to boundary conditions
2. **Synthetic Rating Curve Generation**: Batch steady flow runs to create rating libraries
3. **Model Cutting**: Trim HEC-RAS models to NWM hydrofabric reach extents

**Proposed Module Structure**:
```
ras_commander/nwm/
├── NwmClient.py         # hydrotools.nwm-client wrapper
├── NhdMapping.py        # COMID/NHDPlus utilities via PyNHD
├── RatingCurve.py       # Synthetic rating curve generation
└── ModelCutter.py       # Model trimming to NWM reaches
```

**External References**:
- NOAA-OWP/hydrotools - Official NWM data retrieval from GCP
- Dewberry/ripple1d - Production HEC-RAS NWM utilities (reference)
- NOAA-OWP/ras2fim - Rating curve generation reference

**Data Sources**:
- NWM Operational Forecasts (Google Cloud Platform)
- NWM Retrospective 1979-2023 (AWS S3)
- NHDPlus/COMID topology (EPA WATERS, USGS)
- AORC forcing data (already integrated via PrecipAorc)

**Dependencies**:
- hydrotools.nwm-client (NOAA official library)
- pynhd (NHDPlus utilities)
- geopandas (spatial operations)

**Use Cases**:
- Operational flood forecasting
- Historic event reconstruction
- Rating curve libraries for flood inundation mapping

**Deliverables**:
- `ras_commander/nwm/` subpackage
- Example: `examples/33_nwm_forecast_bc.ipynb`
- Example: `examples/34_synthetic_rating_curves.ipynb`

---

### 3.3 HMS-RAS Linked Model Workflows (TP-40 → Atlas 14) - PRIORITY 3
**Status**: 0% (planning, requires hms-commander coordination)
**Effort**: 6-8 weeks
**Complexity**: High

**Purpose**: Develop coordinated workflows between hms-commander and ras-commander for upgrading linked HMS-RAS models from legacy TP-40 precipitation to NOAA Atlas 14, with automated boundary condition linking.

**Background**:
- Many HEC-RAS models use HEC-HMS for hydrology (linked models)
- Legacy models use TP-40 precipitation frequency (outdated, replaced by Atlas 14 in 2004+)
- Upgrading requires coordinated changes in both HMS and RAS

**Cross-Repository Coordination**:
This feature requires collaboration between:
- **hms-commander** (`C:\GH\hms-commander\`) - HMS model upgrades and flow generation
- **ras-commander** (this repository) - RAS boundary condition setup and simulation

**Workflow Components**:

**Phase A: HMS Precipitation Upgrade** (hms-commander)
1. **Atlas 14 Integration** - Replace TP-40 with Atlas 14 precipitation depths
2. **HMS Plan Execution** - Run upgraded HMS models to generate flow hydrographs
3. **DSS Output Export** - Extract computed flows from HMS DSS results
4. **Validation** - Compare upgraded vs legacy flow hydrographs

**Phase B: RAS Boundary Condition Linking** (ras-commander)
1. **Automated BC Mapping** - Match HMS basin outlets to RAS boundary locations
2. **Flow Series Import** - Import HMS flows as RAS boundary conditions
3. **Plan Generation** - Create RAS plans for each HMS event/scenario
4. **Batch Execution** - Run all linked scenarios in parallel

**Phase C: Agent Coordination** (cross-repository)
1. **HMS Agent** - Handles HMS model upgrades and execution (hms-commander)
2. **Linking Agent** - Coordinates HMS outputs → RAS inputs
3. **RAS Agent** - Handles RAS plan generation and execution (ras-commander)
4. **Validation Agent** - Compares TP-40 vs Atlas 14 results

**Proposed ras-commander API**:
```python
class HmsRasLink:
    @staticmethod
    def map_hms_outlets_to_ras_boundaries(
        hms_project_path: Path,
        ras_project_path: Path,
        mapping_strategy: str = 'spatial'  # or 'manual', 'name_match'
    ) -> OutletBoundaryMapping

    @staticmethod
    def import_hms_flows_to_ras(
        hms_dss_path: Path,
        ras_project_path: Path,
        mapping: OutletBoundaryMapping,
        plan_template: str
    ) -> List[str]  # Created plan numbers

    @staticmethod
    def create_linked_plan_suite(
        hms_events: List[str],  # e.g., ['10yr', '25yr', '50yr', '100yr', '500yr']
        ras_base_plan: str,
        output_folder: Path
    ) -> PermutationResult
```

**Integration with Existing Features**:
- **RasDss** - Read HMS DSS flow results
- **RasUnsteady** - Write boundary condition flow files
- **RasPlan** - Clone and modify plans for each event
- **RasCmdr.compute_parallel()** - Execute all scenarios in batch
- **StormGenerator** - Access Atlas 14 data (already implemented)

**Research Requirements**:
- **Review hms-commander conversation history** - Identify existing Atlas 14 upgrade agents
- **HMS-RAS linking patterns** - Document common linking configurations
- **Validation metrics** - Define acceptable differences between TP-40 and Atlas 14 results

**Example Use Case**: Harris County Flood Control District Models
- HCFCD has 22 linked HMS-RAS models (from M3Model integration)
- Many still use TP-40 precipitation
- Upgrade workflow:
  1. Run hms-commander agent to update HMS model to Atlas 14
  2. Execute HMS to generate Atlas 14 flows
  3. Use ras-commander linking agent to import flows as RAS BCs
  4. Run RAS scenarios in parallel
  5. Compare results and validate model performance

**Dependencies**:
- hms-commander repository and agents
- Coordination between repositories via shared file protocols
- DSS file handling (already available via RasDss)
- NOAA Atlas 14 data access (already available via StormGenerator)

**Deliverables**:
- `ras_commander/hms_link/` subpackage
  - `OutletMapping.py` - HMS outlet → RAS boundary mapping
  - `FlowImport.py` - HMS DSS flows → RAS flow files
  - `LinkedPlanGenerator.py` - Multi-event plan creation
- Example: `examples/36_hms_ras_linked_atlas14_upgrade.ipynb`
- Documentation: Integration guide for HMS-RAS workflows
- Coordination protocol: Document for cross-repository agent communication

**Timeline**:
- Week 1-2: Review hms-commander history, design coordination protocol
- Week 3-4: Implement outlet mapping and flow import
- Week 5-6: Develop linked plan generation and batch execution
- Week 7: Testing with HCFCD example models
- Week 8: Documentation and example notebook

**Critical Success Factors**:
1. **Agent Communication** - Clear protocol for HMS agent → RAS agent handoff
2. **Validation Workflow** - Automated comparison of TP-40 vs Atlas 14 results
3. **Error Handling** - Robust handling of missing outlets, flow mismatches
4. **Scalability** - Support for large model suites (20+ linked models)

**Note**: This feature requires access to `C:\GH\hms-commander\` repository and review of its Claude conversation history to identify existing Atlas 14 upgrade agent implementations.

---

## Phase 4: Long-Term & Specialized Features (16+ weeks)

**Goal**: Complete complex algorithms and comprehensive documentation

### 4.1 RASMapper Sloped Interpolation (Cell Corners Method) - PRIORITY 1
**Status**: 40% complete (horizontal method done, sloped in progress)
**Effort**: 8-10 weeks
**Complexity**: Very High

**Purpose**: Reverse-engineer RASMapper's water surface rasterization algorithms for programmatic raster generation

**Completed**:
- ✅ Horizontal Interpolation Method (validated against RASMapper exports)

**In Progress: Sloped (Cell Corners) Method**
- Status: Planning phase, 800 LOC estimated
- Ground truth project: `BaldEagleCrkMulti2D - Sloped - Cell Corners`
- 10 test plans with HDF available (p01-p06, p13, p15, p17-p19)

**Technical Components** (5-phase implementation):

1. **Mesh Topology Extraction** (~200 LOC, 2 weeks)
   - Parse face/cell/vertex relationships from geometry HDF
   - Build spatial index for efficient queries

2. **Face WSE Computation** (~150 LOC, 2-3 weeks)
   - High complexity: 6+ branching code paths
   - Hydraulic connectivity logic with terrain integration

3. **Vertex WSE Computation** (~100 LOC, 1-2 weeks)
   - Planar regression implementation
   - Match C# floating-point behavior exactly

4. **Triangle Rasterization** (~200 LOC, 2-3 weeks)
   - Pixel-perfect grid alignment with terrain rasters
   - Triangle-to-grid scanning algorithms

5. **Integration & Validation** (~150 LOC, 1-2 weeks)
   - Compare against RASMapper TIFs pixel-by-pixel
   - Edge case handling (dry cells, terrain masks)

**Challenges**:
- Mesh topology interpretation from HDF
- Terrain elevation integration (face/cell minimums)
- Complex hydraulic connectivity branching
- Floating-point precision matching

**Deliverables**:
- `RasMap.map_ras_results()` enhancement with `method='cell_corners'`
- Update `examples/25_programmatic_result_mapping.ipynb`

---

### 4.2 Documentation Revision - PRIORITY 2
**Status**: 0% (planning complete with detailed outlines)
**Effort**: 2-3 weeks
**Complexity**: Low

**Planned Content**:

1. **PRJ File Parsing Reference** (`docs/reference/prj-parsing.md`)
   - File structure, data types, parsing patterns
   - Examples of reading/writing PRJ fields

2. **Unsteady File Parsing Reference** (`docs/reference/unsteady-parsing.md`)
   - Boundary condition formats
   - Flow series, stage series, lateral inflows
   - DSS integration patterns

3. **Steady File Parsing Reference** (`docs/reference/steady-parsing.md`)
   - Flow distribution formats
   - Boundary conditions for steady flow

4. **HDF Writing Guide** (`docs/reference/hdf-writing-guide.md`)
   - Safe modification patterns
   - Critical technical requirements (chunking, compression, field types)
   - Infiltration override example
   - Data provenance considerations

**Key Insights to Document**:
- Plain text files are authoritative; HDF is derived
- Modification strategy: Edit plain text → let HEC-RAS regenerate HDF
- Safe HDF modifications: Override parameters only (e.g., infiltration rates)

**Deliverables**:
- 4 new reference documents in `docs/reference/`
- Updated HDF structure page with provenance section

---

### 4.3 Decompilation & Reverse Engineering - ONGOING RESEARCH
**Status**: Partial (RasMapperLib.dll done, RAS.dll/RasProcess.exe pending)
**Effort**: Variable (ongoing research)
**Complexity**: High

**Completed Decompilation**:
- ✅ RasMapperLib.dll (120+ C# files)
  - Water surface interpolation algorithms extracted
  - Basis for RASMapper Interpolation feature development

**Pending Decompilation Targets**:
1. **RAS.dll** - Core HEC-RAS .NET assembly
   - Precipitation import logic (GDAL format generation)
   - Plan file parsing/writing
   - Geometry processing

2. **RasProcess.exe** - Plan execution engine
   - Computation orchestration
   - HDF writing sequences

3. **Geospatial.GDALAssist.dll** - GDAL interface
   - Raster import utilities
   - Projection transformations

4. **H5Assist.dll** - HDF helper library
   - HDF schema definitions
   - Write operation patterns

**Note on Ras.exe**: Fortran-based (not .NET), requires different decompilation approach (IDA Pro/Ghidra)

**Reorganization Plan**:
- Consolidate decompiled code into `feature_dev_notes/Decompilation Agent/decompiled/`
- Organize by assembly and functionality
- Document key findings in assembly-specific markdown files

**Use Cases**:
- Resolve precipitation GDAL format incompatibility (blocked on RAS.dll decompilation)
- Understand HDF write patterns for safe programmatic modification
- Extract undocumented algorithms

**Deliverables**: Ongoing research outputs as needed for feature development

---

## Phase 2 Additional Features

### 2.5 MRMS Precipitation Integration - PRIORITY 4
**Status**: 0% (planned)
**Effort**: 3-4 weeks
**Complexity**: Medium

**Purpose**: Integrate Multi-Radar/Multi-Sensor System (MRMS) precipitation data for high-resolution, real-time precipitation forcing in HEC-RAS models.

**MRMS Overview**:
- NOAA's operational radar-based precipitation product
- 1 km spatial resolution, 2-minute temporal resolution
- Real-time and archive data available
- Multiple products: radar-only, gauge-corrected, QPE (Quantitative Precipitation Estimate)

**Key Workflows**:
1. **MRMS Data Retrieval**
   - Access via NOAA's Big Data Program (AWS S3, Google Cloud)
   - GRIB2 format parsing
   - Temporal aggregation (2-min → hourly/sub-hourly)

2. **Spatial Processing**
   - Clip to HEC-RAS model domain
   - Reproject from MRMS native grid (EPSG:4326 or Lambert Conformal)
   - Convert to HEC-RAS precipitation format (DSS or GDAL/HDF)

3. **Temporal Processing**
   - Aggregate 2-minute data to model timestep (e.g., 15-min, hourly)
   - Handle missing data periods
   - Quality control and flagging

**Proposed Module Structure**:
```
ras_commander/mrms/
├── MrmsClient.py        # Data retrieval from AWS/GCP
├── MrmsProcessor.py     # Spatial/temporal processing
└── MrmsToRas.py         # Conversion to HEC-RAS formats
```

**Integration Points**:
- Leverage existing `RasDss` for DSS grid writing
- Use `PrecipAorc` patterns for NetCDF/GDAL processing
- Integrate with `RasUnsteady` for boundary condition setup

**Data Sources**:
- MRMS Archive: AWS S3 `s3://noaa-mrms-pds/`
- Real-time MRMS: NOAA's SBN/LDM
- GRIB2 format (requires pygrib or cfgrib)

**Dependencies**:
- s3fs or boto3 (AWS S3 access)
- cfgrib or pygrib (GRIB2 reading)
- xarray (multi-dimensional data handling)
- rasterio (spatial operations)

**Use Cases**:
- High-resolution historic storm reconstruction
- Real-time/near-real-time flood forecasting
- Calibration with observed precipitation
- Comparison with AORC or gauge-based precipitation

**Deliverables**:
- `ras_commander/mrms/` subpackage
- Example: `examples/35_mrms_precipitation.ipynb`
- Documentation on MRMS data access and processing

**Estimated Timeline**: 3-4 weeks
- Week 1: MRMS retrieval and GRIB2 parsing
- Week 2: Spatial/temporal processing utilities
- Week 3: HEC-RAS format conversion (DSS/GDAL)
- Week 4: Testing, example notebook, documentation

---

## Completed & Integrated Features

### DSS Integration (v0.82.0+) ✅
**Completion**: v0.82.0
**Status**: Production-ready, shipping in v0.87.1

**Capabilities**:
- Read DSS V6 and V7 files
- Extract boundary condition time series
- Auto-map boundary conditions to HEC-RAS projects
- HEC Monolith auto-download (~20 MB, one-time)

**Testing**: 84 DSS files (6.64 GB), 88% success rate

**Documentation**:
- CLAUDE.md: DSS File Operations section
- `examples/22_dss_boundary_extraction.ipynb`
- `ras_commander/dss/AGENTS.md`

**Outstanding (Minor)**:
- Add `pyjnius` to `setup.py` extras_require
- Highlight DSS support in main README

---

### HCFCD M3 Models Integration ✅
**Completion**: Integrated
**Status**: Production-ready

**Capabilities**:
- Automated access to 22 HCFCD Current FEMA Effective models
- Direct downloads from files.m3models.org
- Channel-to-model mapping via ArcGIS REST API
- Model management (list, extract, cache)

**API**:
```python
M3Model.list_models()
M3Model.extract_model('C')  # Sims Bayou
M3Model.get_model_by_channel('BRAYS BAYOU')
```

**Integration Pattern**: Follows `RasExamples` architecture

---

### ReadTheDocs Notebook Rendering Fix ✅
**Completion**: Code ready, deployment pending
**Effort**: 5 minutes to deploy

**Problem**: Symlinks stripped by ReadTheDocs → 0 cells rendered
**Solution**: Change `.readthedocs.yaml` to use `cp -r` instead of `ln -s`

**Actions**:
1. Commit `.readthedocs.yaml` changes
2. Update `.gitignore`
3. Push to trigger rebuild

---

### Precipitation AORC/GDAL Import ✅
**Completion**: Integrated in v0.8x+
**Status**: Production-ready

**Capabilities**:
- AORC (Analysis of Record for Calibration) precipitation import
- GDAL raster-based precipitation grids
- NetCDF to HEC-RAS HDF conversion
- Spatial precipitation for unsteady models

**Documentation**:
- Example notebook: `examples/24_aorc_precipitation.ipynb`
- Research in `planning_docs/` (format investigation and implementation)

---

## Blocked / Research Phase Features

### Precipitation AORC/GDAL Import ✅
**Status**: Complete and integrated
**Implementation**: Example notebook `24_aorc_precipitation.ipynb`

**Capabilities**:
- AORC (Analysis of Record for Calibration) precipitation import
- GDAL raster-based precipitation grids
- NetCDF to HEC-RAS HDF conversion
- Spatial precipitation for HEC-RAS unsteady models

**Note**: Initial research documents in `planning_docs/` explored format compatibility issues, but solution was successfully implemented and is production-ready.

---

## Priority Recommendations

### Immediate (Next 4-6 weeks)
1. **Complete Library Improvements** - Highest ROI, immediate DX gains
2. **Deploy ReadTheDocs Fix** - 5 minutes, fixes documentation
3. **Finish Notebook Updates** - Cleaner examples, better maintainability

### Short-Term (6-12 weeks)
1. **Complete cHECk-RAS** - High user value, 83% done
2. **Finish Gauge Data Import** - Critical for USGS workflows
3. **Implement Permutation Logic** - Enable sensitivity analysis workflows
4. **DSS Grid Writing** - Alternative to blocked GDAL precipitation

### Medium-Term (12-18 weeks)
1. **Floodway Analysis** - Specialized but comprehensive FEMA compliance
2. **National Water Model** - Enable operational forecasting workflows

### Long-Term (18+ weeks)
1. **RASMapper Sloped Interpolation** - Complex algorithm, lower priority
2. **Documentation Revision** - Comprehensive reference material
3. **Decompilation** - Ongoing research as needed

---

## Resource Allocation Guidance

### High-Impact, Low-Effort (Do First)
- Library Improvements (2-3 weeks)
- Notebook Updates (2-3 weeks)
- ReadTheDocs Fix (5 minutes)

### High-Impact, Medium-Effort (Priority Queue)
- cHECk-RAS completion (3-5 weeks)
- Gauge Data Import (4-6 weeks)
- Permutation Logic (3-4 weeks)

### High-Impact, High-Effort (Plan Carefully)
- Floodway Analysis (6-8 weeks)
- National Water Model (6-8 weeks)

### Medium-Impact, Very High-Effort (Long-Term)
- RASMapper Sloped Interpolation (8-10 weeks)

---

## Git Worktree Strategy

See `WORKTREE_WORKFLOW.md` for complete details on using git worktrees with sideloaded `feature_dev_notes/` and `planning_docs/` folders.

**Quick Pattern**:
```bash
# Create feature worktree
git worktree add -b feature/check-ras ../ras-commander-worktrees/feature-check-ras

# Sideload development folders
cd ../ras-commander-worktrees/feature-check-ras
mklink /J feature_dev_notes C:\GH\ras-commander\feature_dev_notes
mklink /J planning_docs C:\GH\ras-commander\planning_docs
mklink /J agent_tasks C:\GH\ras-commander\agent_tasks

# Work, commit, merge
```

**Benefits**:
- Branch isolation without switching
- Access to all research materials
- Shared memory system across worktrees

---

## Maintenance & Support

### Version Planning
- **v0.88.0**: Library improvements, notebook updates, ReadTheDocs fix
- **v0.89.0**: cHECk-RAS completion
- **v0.90.0**: Gauge data import, permutation logic
- **v0.91.0**: DSS grid writing
- **v1.0.0**: Floodway analysis, National Water Model (major milestone)

### Documentation Priorities
1. ReadTheDocs deployment (immediate)
2. Enhanced README with feature highlights
3. Reference documentation for file formats
4. Performance optimization guide (blog content extraction)

### Testing Strategy
- Example notebooks serve as functional tests
- HEC-RAS example projects for validation
- Ground truth comparison for algorithm verification (RASMapper, cHECk-RAS)

---

## Summary

ras-commander has a robust pipeline of features in various stages of completion. The recommended strategy:

1. **Quick Wins First**: Complete high-ROI, low-effort items (library improvements, notebook updates)
2. **Finish What's Started**: Complete partially-implemented features (cHECk-RAS, gauge import)
3. **Strategic Additions**: Implement high-value planned features (permutation logic, floodway, NWM)
4. **Long-Term Excellence**: Complex algorithms and comprehensive documentation

Total estimated timeline for full roadmap execution: **18-24 months** with sustained development effort.

All feature development materials are available in `feature_dev_notes/` and `planning_docs/` for detailed implementation guidance.
