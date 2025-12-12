# Phase 4 Preparation - Subagents & Skills

**Created**: 2025-12-11
**Purpose**: Prepare context for Phase 4 implementation before conversation compacts
**Branch**: feature/hierarchical-knowledge

---

## Current Status Summary

### ✅ COMPLETED
- **Phase 1**: Foundation (directory structure, ras_skills migration) - Commit 573a62d
- **Phase 2**: Content migration (11 rules files, root CLAUDE.md condensed) - Commits 2f36b7a, cf50712
- **Phase 3**: Subpackage CLAUDE.md files (5 created, 6 reviewed) - Commit 7cfdc49
- **LLM Forward Integration**: Phases 1-3 complete - Commit dd0285c

### 🎯 NEXT: Phase 4 - Create Subagents & Skills

**Goal**: Enable specialist delegation and workflow discovery through Claude framework

**Timeline**: Week 4-5 of 6-week implementation

**Success Criteria**:
- [ ] 7 specialist subagents defined
- [ ] 8 library workflow skills created
- [ ] Trigger-rich descriptions for discovery
- [ ] Progressive disclosure working
- [ ] All skills testable with real projects

---

## Phase 4.1: Specialist Subagents

Create 7 subagent definitions in `.claude/subagents/`. Each subagent focuses on a specific domain within ras-commander.

### Subagent Structure Pattern

Based on existing `hierarchical-knowledge-agent-skill-memory-curator/`:

```
.claude/subagents/{subagent-name}/
├── SUBAGENT.md           # Main definition with YAML frontmatter
├── reference/
│   ├── api-patterns.md   # API usage patterns
│   ├── workflows.md      # Common workflows
│   └── troubleshooting.md # Common issues
└── examples/
    ├── basic.md          # Simple examples
    └── advanced.md       # Complex scenarios
```

**SUBAGENT.md Template**:
```yaml
---
name: {subagent-name}
model: sonnet  # or haiku for simple tasks
tools:
  - Read
  - Grep
  - Glob
  - Bash
working_directory: ras_commander/{subpackage}
description: |
  {Trigger-rich description with what, when, and keywords}
---

# {Subagent Name}

## Purpose
{What this subagent does}

## When to Delegate
{Conditions that should trigger this subagent}

## Workflows
{Common workflow patterns}

## Reference
- See [reference/api-patterns.md](reference/api-patterns.md)
```

---

### 1. HDF Analyst Subagent

**Name**: `hdf-analyst`
**Location**: `.claude/subagents/hdf-analyst/`
**Target Size**: SUBAGENT.md ~200 lines, reference/ ~400 lines total

**Purpose**: HEC-RAS HDF5 file operations, result extraction, and data analysis.

**SUBAGENT.md Content**:
```yaml
---
name: hdf-analyst
model: sonnet
tools:
  - Read
  - Grep
  - Glob
  - Bash
working_directory: ras_commander/hdf
description: |
  Analyzes HEC-RAS HDF5 files (.p##.hdf, .g##.hdf) using ras_commander.hdf
  subpackage (18 classes). Extracts mesh results, cross section data, structure
  geometry, and steady/unsteady time series. Use when working with HDF files,
  extracting results, analyzing water surface elevations, velocities, depths,
  or querying HEC-RAS output data.
---

# HDF Analyst

## Purpose
Extract and analyze data from HEC-RAS HDF5 files using the 18-class hdf subpackage.

## When to Delegate
- "Analyze this HDF file"
- "Extract water surface elevations"
- "Get maximum depth from results"
- "Read mesh cell polygons"
- "What's in this .p01.hdf file?"

## Class Organization
**Geometry** (5 classes):
- HdfMesh - 2D mesh operations
- HdfXsec - Cross section geometry
- HdfBndry - Boundary features
- HdfStruc - Structure geometry
- HdfHydraulicTables - HTAB extraction

**Results** (4 classes):
- HdfResultsPlan - Plan results (steady/unsteady)
- HdfResultsMesh - Mesh time series
- HdfResultsXsec - Cross section time series
- HdfResultsBreach - Dam breach results

**Infrastructure** (3 classes):
- HdfPipe - Pipe networks
- HdfPump - Pump stations
- HdfInfiltration - Infiltration parameters

**Core** (3 classes):
- HdfBase - Foundation class
- HdfUtils - Utility functions
- HdfPlan - Plan file metadata

**Visualization** (2 classes):
- HdfPlot - General plotting
- HdfResultsPlot - Results visualization

**Analysis** (1 class):
- HdfFluvialPluvial - Fluvial-pluvial delineation

## Common Workflows
1. Check if steady or unsteady: `HdfResultsPlan.is_steady_plan()`
2. Extract steady WSE: `HdfResultsPlan.get_steady_wse()`
3. Get mesh time series: `HdfResultsMesh.get_mesh_timeseries()`
4. Extract maximum envelope: `HdfResultsMesh.get_mesh_maximum()`

## Critical Patterns
- **Lazy Loading**: Heavy dependencies (geopandas, matplotlib) loaded inside methods
- **@standardize_input**: Accepts plan numbers, paths, or h5py.File objects
- **Static Methods**: Never instantiate (e.g., `HdfMesh.method()` not `HdfMesh().method()`)

## Reference
- Detailed API: [reference/api-patterns.md](reference/api-patterns.md)
- Lazy loading: [reference/lazy-loading.md](reference/lazy-loading.md)
- See: `ras_commander/hdf/AGENTS.md` for implementation details
```

**reference/api-patterns.md** (~150 lines):
- Complete API for all 18 classes
- Input normalization patterns
- Return value types
- Example usage for each class

**reference/lazy-loading.md** (~100 lines):
- Three-level lazy loading architecture
- Dependency timing table
- Import patterns

**reference/workflows.md** (~150 lines):
- Steady flow extraction workflow
- Unsteady results time series
- 2D mesh analysis
- Structure data extraction

---

### 2. Geometry Parser Subagent

**Name**: `geometry-parser`
**Location**: `.claude/subagents/geometry-parser/`
**Target Size**: SUBAGENT.md ~200 lines

**Purpose**: Parse and modify HEC-RAS plain text geometry files (.g##).

**SUBAGENT.md Content**:
```yaml
---
name: geometry-parser
model: sonnet
tools:
  - Read
  - Edit
  - Grep
working_directory: ras_commander/geom
description: |
  Parses and modifies HEC-RAS plain text geometry files (.g##) using
  ras_commander.geom subpackage (9 modules). Handles 1D cross sections,
  storage areas, lateral structures, connections, inline weirs, bridges,
  culverts, and 2D Manning's n tables. Use when parsing geometry, modifying
  cross sections, reading bridges/culverts, or updating roughness values.
---

# Geometry Parser

## Purpose
Parse and modify HEC-RAS geometry files using fixed-width FORTRAN format.

## When to Delegate
- "Parse this geometry file"
- "Get cross section data"
- "Modify Manning's n values"
- "Read bridge geometry"
- "Update storage area elevation-volume curve"

## Module Organization (9 modules)
**Parsing**:
- GeomParser - Fixed-width parsing utilities
- GeomPreprocessor - Geometry preprocessor management

**1D Features**:
- GeomCrossSection - Cross section operations
- GeomStorage - Storage area elevation-volume
- GeomLateral - Lateral structures and connections

**Structures**:
- GeomInlineWeir - Inline weir structures
- GeomBridge - Bridge/culvert geometry
- GeomCulvert - Culvert data extraction

**2D Features**:
- GeomLandCover - 2D Manning's n land cover tables

## Critical Patterns
**Fixed-Width Format**:
- 8-character columns (FORTRAN-era)
- 10 values per line (80 characters)
- Count interpretation: "#Sta/Elev= 40" means 40 PAIRS (80 values)

**Bank Station Interpolation**:
- Bank stations MUST appear as exact points in station/elevation data
- GeomCrossSection.set_station_elevation() handles automatically

**450 Point Limit**:
- HEC-RAS enforces 450 points per cross section
- Validate before writing

## Common Workflows
1. Get all cross sections: `GeomCrossSection.get_cross_sections()`
2. Read XS geometry: `GeomCrossSection.get_station_elevation()`
3. Modify XS: `GeomCrossSection.set_station_elevation()`
4. Read bridge: `GeomBridge.get_deck()`, `.get_piers()`

## Reference
- API details: [reference/api-patterns.md](reference/api-patterns.md)
- Fixed-width parsing: [reference/parsing-algorithms.md](reference/parsing-algorithms.md)
- See: `ras_commander/geom/AGENTS.md` for implementation details
```

---

### 3. Remote Executor Subagent

**Name**: `remote-executor`
**Location**: `.claude/subagents/remote-executor/`
**Target Size**: SUBAGENT.md ~200 lines

**Purpose**: Distributed execution coordination across local, remote, and cloud resources.

**SUBAGENT.md Content**:
```yaml
---
name: remote-executor
model: sonnet
tools:
  - Read
  - Write
  - Bash
working_directory: ras_commander/remote
description: |
  Coordinates distributed HEC-RAS execution across local, remote (PsExec, SSH,
  Docker), and cloud workers (AWS, Azure, Slurm). Manages worker initialization,
  queue scheduling, and result aggregation. Use when setting up remote workers,
  distributed computation, parallel execution across machines, or cloud-based
  HEC-RAS workflows.
---

# Remote Executor

## Purpose
Coordinate distributed HEC-RAS execution using heterogeneous worker pools.

## When to Delegate
- "Setup remote workers"
- "Configure PsExec execution"
- "Run plans on Docker containers"
- "Distribute models across machines"
- "Setup cloud workers"

## Worker Types (12 modules)
**Implemented**:
- PsexecWorker - Windows remote via PsExec
- LocalWorker - Local parallel execution
- DockerWorker - Container execution over SSH

**Stubs** (require dependencies):
- SshWorker - Direct SSH execution
- WinrmWorker - Windows Remote Management
- SlurmWorker - HPC cluster scheduling
- AwsEc2Worker - AWS EC2 instances
- AzureFrWorker - Azure Functions/Batch

## Critical Configuration
**PsExec Worker**:
- **CRITICAL**: `session_id=2` (typical workstation desktop)
- **NEVER**: `system_account=True` (HEC-RAS needs desktop GUI)
- Group Policy: Network access, local logon, batch job rights
- Registry: `LocalAccountTokenFilterPolicy=1`
- Service: Remote Registry must be running

**Docker Worker**:
- Requires: `docker` and `paramiko` packages
- Preprocessing runs locally (Windows-only)
- Path conversion: `/mnt/c/` → `C:/`
- SSH key authentication for remote Docker hosts

## Common Workflows
1. Initialize worker: `init_ras_worker(worker_type="psexec", ...)`
2. Validate worker: Worker validates in `__post_init__()`
3. Execute distributed: `compute_parallel_remote(workers=...)`

## Reference
- Worker setup: [reference/worker-configuration.md](reference/worker-configuration.md)
- Troubleshooting: [reference/common-issues.md](reference/common-issues.md)
- See: `ras_commander/remote/AGENTS.md` for implementation details
- See: `.claude/rules/hec-ras/remote.md` for session_id requirement
```

---

### 4. USGS Integrator Subagent

**Name**: `usgs-integrator`
**Location**: `.claude/subagents/usgs-integrator/`
**Target Size**: SUBAGENT.md ~200 lines

**Purpose**: USGS gauge data integration, from spatial discovery to model validation.

**SUBAGENT.md Content**:
```yaml
---
name: usgs-integrator
model: sonnet
tools:
  - Read
  - Write
  - Bash
working_directory: ras_commander/usgs
description: |
  Integrates USGS NWIS gauge data with HEC-RAS models (14 modules). Handles
  spatial discovery, data retrieval, gauge matching, time series processing,
  boundary condition generation, initial conditions, real-time monitoring,
  and model validation. Use when working with USGS data, generating boundaries
  from gauges, validating models, or monitoring real-time conditions.
---

# USGS Integrator

## Purpose
Complete USGS gauge data integration workflow from discovery to validation.

## When to Delegate
- "Find USGS gauges near this model"
- "Download gauge data"
- "Generate boundary conditions from USGS"
- "Validate model with observed data"
- "Setup real-time monitoring"

## Workflow Stages (14 modules)
**Spatial Discovery**:
- UsgsGaugeSpatial - Find gauges in project bounds
- GaugeMatcher - Match gauges to HEC-RAS features

**Data Retrieval**:
- RasUsgsCore - Retrieve flow/stage data from NWIS
- RasUsgsFileIo - Cache data locally

**Processing**:
- RasUsgsTimeSeries - Resample to HEC-RAS intervals
- RasUsgsBoundaryGeneration - Create .u## file tables
- InitialConditions - Extract IC values

**Real-Time** (v0.87.0+):
- RasUsgsRealTime - Monitor gauges with callbacks
- Threshold detection, rapid change alerts

**Catalog** (v0.89.0+):
- Generate standardized "USGS Gauge Data" folder
- Master catalog with historical data

**Validation**:
- metrics - NSE, KGE, peak error
- visualization - Time series plots, residuals

## Common Workflows
1. Spatial discovery → data retrieval → gauge matching
2. Time series processing → boundary generation
3. Real-time monitoring with threshold alerts
4. Model validation with observed data

## Dependencies
- **Required**: pandas, geopandas, requests
- **Lazy-loaded**: dataretrieval (pip install dataretrieval)

## Reference
- Complete workflow: [reference/end-to-end.md](reference/end-to-end.md)
- Real-time monitoring: [reference/real-time.md](reference/real-time.md)
- Validation metrics: [reference/validation.md](reference/validation.md)
- See: `ras_commander/usgs/CLAUDE.md` for user workflows
```

---

### 5. Precipitation Specialist Subagent

**Name**: `precipitation-specialist`
**Location**: `.claude/subagents/precipitation-specialist/`
**Target Size**: SUBAGENT.md ~150 lines

**Purpose**: AORC historical precipitation and Atlas 14 design storm generation.

**SUBAGENT.md Content**:
```yaml
---
name: precipitation-specialist
model: haiku  # Simpler tasks, faster model
tools:
  - Read
  - Write
  - Bash
working_directory: ras_commander/precip
description: |
  Integrates precipitation data into HEC-RAS/HMS models using AORC (historical
  calibration) and NOAA Atlas 14 (design storms). Handles spatial averaging,
  temporal distributions (SCS Type II), areal reduction factors, and DSS export.
  Use when working with precipitation data, design storms, AORC retrieval, or
  generating HEC-RAS boundary conditions from rainfall.
---

# Precipitation Specialist

## Purpose
Integrate AORC and Atlas 14 precipitation into HEC-RAS/HMS workflows.

## When to Delegate
- "Get AORC precipitation for this watershed"
- "Generate 100-year design storm"
- "Create Atlas 14 hyetograph"
- "Apply areal reduction factor"

## Module Organization (3 modules)
**AORC (Historical)**:
- PrecipAorc - NOAA AORC grid retrieval
- Spatial averaging over watersheds
- Temporal aggregation to HEC-RAS intervals

**Atlas 14 (Design Storms)**:
- StormGenerator - NOAA precipitation frequency
- AEP events (50% to 0.2%)
- Temporal distributions (SCS Type II/IA/III)
- Areal reduction factors

## Data Sources
**AORC**:
- Period: 1979-present
- Resolution: ~4 km grid, hourly
- Coverage: CONUS

**Atlas 14**:
- Provider: NOAA National Weather Service
- Coverage: CONUS, Hawaii, Puerto Rico
- AEPs: Standard suite (50% to 0.2%)

## Common Workflows
1. AORC: Retrieve → spatial average → aggregate → export
2. Atlas 14: Query frequency → generate hyetograph → export
3. Multi-event: Loop AEPs → batch generate storms

## Reference
- AORC workflow: [reference/aorc.md](reference/aorc.md)
- Atlas 14 workflow: [reference/atlas14.md](reference/atlas14.md)
- See: `ras_commander/precip/CLAUDE.md` for user workflows
```

---

### 6. Quality Assurance Subagent

**Name**: `quality-assurance`
**Location**: `.claude/subagents/quality-assurance/`
**Target Size**: SUBAGENT.md ~200 lines

**Purpose**: Automated quality checks (RasCheck) and geometry repair (RasFixit).

**SUBAGENT.md Content**:
```yaml
---
name: quality-assurance
model: sonnet
tools:
  - Read
  - Write
  - Edit
  - Bash
working_directory: ras_commander/check
description: |
  Performs automated quality assurance using RasCheck (5 check types) and
  RasFixit (geometry repair). Validates Manning's n, cross sections, structures,
  floodways, and profiles against FEMA/USACE standards. Repairs blocked
  obstructions using elevation envelope algorithm. Use when validating models,
  checking geometry, fixing errors, or ensuring FEMA compliance.
---

# Quality Assurance

## Purpose
Automated validation and repair of HEC-RAS models.

## When to Delegate
- "Check this model for errors"
- "Validate Manning's n values"
- "Fix blocked obstructions"
- "Run quality assurance checks"
- "Ensure FEMA compliance"

## Module Organization
**RasCheck** (5 modules):
- RasCheck - Main QA interface (5 check types)
- messages - Standardized validation messages
- report - Multi-format reporting (text, CSV, HTML, JSON)
- thresholds - Configurable standards (FEMA/USACE)

**RasFixit** (6 modules):
- RasFixit - Main repair interface
- obstructions - Elevation envelope algorithm
- results - Fix tracking and reporting
- visualization - Before/after PNG generation
- log_parser - HEC-RAS log parsing

## Check Types (RasCheck)
1. **NT Check**: Manning's n validation
2. **XS Check**: Cross section spacing/geometry
3. **Structure Check**: Bridge/culvert validation
4. **Floodway Check**: Surcharge limits (1.0 ft FEMA, 0.5 ft USACE)
5. **Profiles Check**: Water surface reasonableness

## Repair Capabilities (RasFixit)
- **Blocked Obstructions**: Elevation envelope with 0.02-unit gaps
- Future: Ineffective flow areas, station reversals

## Integration Pattern
1. **Check**: Identify issues with RasCheck
2. **Fix**: Repair issues with RasFixit
3. **Verify**: Re-run checks to confirm

## Reference
- Check types: [reference/checks.md](reference/checks.md)
- Repair algorithms: [reference/repairs.md](reference/repairs.md)
- See: `ras_commander/check/CLAUDE.md`, `ras_commander/fixit/AGENTS.md`
```

---

### 7. Documentation Generator Subagent

**Name**: `documentation-generator`
**Location**: `.claude/subagents/documentation-generator/`
**Target Size**: SUBAGENT.md ~150 lines

**Purpose**: Generate example notebooks, API documentation, and mkdocs content.

**SUBAGENT.md Content**:
```yaml
---
name: documentation-generator
model: sonnet
tools:
  - Read
  - Write
  - Bash
working_directory: examples
description: |
  Generates example Jupyter notebooks, API documentation, and mkdocs markdown
  content. Follows notebook standards (H1 titles, no execution during build),
  creates reproducible workflows using RasExamples, and maintains ReadTheDocs
  compatibility. Use when creating examples, writing documentation, updating
  notebooks, or generating API references.
---

# Documentation Generator

## Purpose
Create and maintain ras-commander documentation and examples.

## When to Delegate
- "Create example notebook for USGS integration"
- "Update API documentation"
- "Generate mkdocs content"
- "Write tutorial for remote execution"

## Documentation Types
**Example Notebooks**:
- Jupyter .ipynb files in examples/
- Must have H1 title in first cell
- Use RasExamples.extract_project() for reproducibility
- No execution during mkdocs build (execute: false)

**API Documentation**:
- mkdocstrings for API reference
- Markdown for user guides
- Cross-references between pages

**mkdocs Content**:
- User guides in docs/user-guide/
- Example notebook integration
- ReadTheDocs deployment (NO symlinks!)

## Critical Standards
**Notebooks**:
- H1 title required (first cell)
- RasExamples for test data
- Cleaned versions for LLM context (ai_tools/llm_knowledge_bases/)

**ReadTheDocs**:
- **CRITICAL**: Use `cp -r` NOT `ln -s` (symlinks stripped!)
- GitHub Actions can use symlinks
- Validation: `unrecognized_links: info`

## Common Workflows
1. Create notebook → add H1 → use RasExamples → test
2. Update mkdocs.yml → verify navigation
3. Generate API docs → test locally → deploy

## Reference
- Notebook standards: `.claude/rules/documentation/notebook-standards.md`
- mkdocs config: `.claude/rules/documentation/mkdocs-config.md`
- See: `examples/AGENTS.md` for notebook index
```

---

## Phase 4.2: Library Workflow Skills

Create 8 skills in `.claude/skills/`. Each skill documents a common multi-step workflow.

### Skill Structure Pattern

```
.claude/skills/{skill-name}/
├── SKILL.md              # Main instructions with YAML frontmatter
├── reference/
│   ├── api.md            # Detailed API reference
│   └── advanced.md       # Advanced patterns
├── examples/
│   ├── basic.py          # Simple example script
│   └── advanced.py       # Complex workflow
└── README.md             # Overview (optional)
```

**SKILL.md Template**:
```yaml
---
name: {skill-name}
description: |
  {Trigger-rich description with what, when, trigger terms}
---

# {Skill Title}

## Quick Start
{50-100 line basic example}

## Common Patterns
{Frequently used variations}

## Reference
- Detailed API: [reference/api.md](reference/api.md)
- Advanced patterns: [reference/advanced.md](reference/advanced.md)
```

---

### Phase 1 Skills: Core Operations

#### 1. executing-hecras-plans

**Location**: `.claude/skills/executing-hecras-plans/`
**Target Size**: SKILL.md ~300 lines

**Description**:
```yaml
description: |
  Executes HEC-RAS plans using RasCmdr.compute_plan(), handles parallel
  execution across multiple plans, manages destination folders, and monitors
  real-time progress with callbacks. Use when running HEC-RAS simulations,
  computing plans, executing models, parallel workflows, or setting up
  distributed computation.
```

**Content Outline**:
- Single plan execution (compute_plan)
- Parallel execution (compute_parallel)
- Sequential test mode (compute_test_mode)
- Real-time monitoring (stream_callback parameter)
- Destination folder management
- Core parameter reference (num_cores, overwrite_dest, clear_geompre)

**reference/api.md**: Complete RasCmdr API
**reference/callbacks.md**: Real-time monitoring patterns
**examples/basic.py**: Simple plan execution
**examples/parallel.py**: Parallel execution with 4 plans

---

#### 2. extracting-hecras-results

**Location**: `.claude/skills/extracting-hecras-results/`
**Target Size**: SKILL.md ~350 lines

**Description**:
```yaml
description: |
  Extracts results from HEC-RAS HDF files using HdfResults* classes. Handles
  steady and unsteady flows, 2D mesh time series, cross section profiles,
  maximum envelopes, and breach results. Use when extracting water surface
  elevations, depths, velocities, reading HDF files, or analyzing results.
```

**Content Outline**:
- Steady vs unsteady detection (is_steady_plan)
- Steady flow extraction (get_steady_wse, get_steady_profile_names)
- Unsteady time series (get_mesh_timeseries, get_xsec_timeseries)
- Maximum envelopes (get_mesh_maximum)
- Cross section results (HdfResultsXsec)
- Breach results (HdfResultsBreach)

**reference/api.md**: HdfResults* class reference
**reference/steady-vs-unsteady.md**: Detection and extraction patterns
**examples/steady.py**: Steady flow extraction
**examples/unsteady.py**: Unsteady time series

---

#### 3. parsing-hecras-geometry

**Location**: `.claude/skills/parsing-hecras-geometry/`
**Target Size**: SKILL.md ~300 lines

**Description**:
```yaml
description: |
  Parses and modifies HEC-RAS plain text geometry files (.g##) using fixed-width
  FORTRAN format. Handles cross sections, storage areas, bridges, culverts,
  lateral structures, and Manning's n tables. Use when reading geometry files,
  modifying cross sections, updating roughness, or extracting structure data.
```

**Content Outline**:
- Fixed-width parsing (8-character columns)
- Cross section operations (GeomCrossSection)
- Bridge/culvert data (GeomBridge, GeomCulvert)
- Storage areas (GeomStorage)
- Manning's n land cover (GeomLandCover)
- Bank station interpolation
- 450-point limit enforcement

**reference/parsing.md**: Fixed-width parsing algorithms
**reference/modification.md**: Safe geometry modification patterns
**examples/read-geometry.py**: Parse cross sections
**examples/modify-xs.py**: Modify cross section geometry

---

### Phase 2 Skills: Advanced Features

#### 4. integrating-usgs-gauges

**Location**: `.claude/skills/integrating-usgs-gauges/`
**Target Size**: SKILL.md ~400 lines

**Description**:
```yaml
description: |
  Complete USGS gauge data integration workflow from spatial discovery to
  model validation. Handles gauge finding, data retrieval, matching to HEC-RAS
  features, boundary condition generation, and validation metrics. Use when
  working with USGS data, generating boundaries from gauges, calibrating models,
  or validating with observed data.
```

**Content Outline**:
- Spatial discovery (UsgsGaugeSpatial.find_gauges_in_project)
- Data retrieval (RasUsgsCore.retrieve_flow_data)
- Gauge matching (GaugeMatcher.auto_match_gauges)
- Time series processing (resample_to_hecras_interval)
- Boundary generation (generate_flow_hydrograph_table)
- Validation metrics (NSE, KGE)
- Real-time monitoring (RasUsgsRealTime)

**reference/workflow.md**: Complete end-to-end workflow
**reference/validation.md**: Validation metrics and interpretation
**examples/complete-workflow.py**: Discovery → validation
**examples/real-time.py**: Real-time monitoring

---

#### 5. analyzing-aorc-precipitation

**Location**: `.claude/skills/analyzing-aorc-precipitation/`
**Target Size**: SKILL.md ~250 lines

**Description**:
```yaml
description: |
  Retrieves and processes AORC precipitation data for HEC-RAS/HMS models.
  Handles spatial averaging over watersheds, temporal aggregation, and DSS
  export. Use when working with historical precipitation, AORC data, calibration
  workflows, or generating precipitation boundary conditions.
```

**Content Outline**:
- AORC data retrieval (retrieve_aorc_data)
- Spatial averaging over watersheds
- Temporal aggregation to HEC-RAS intervals
- DSS export for HEC-RAS boundaries
- Storm event extraction
- Atlas 14 design storms (brief reference)

**reference/aorc-api.md**: Complete AORC API
**reference/atlas14.md**: Design storm generation
**examples/aorc-retrieval.py**: Basic AORC workflow
**examples/design-storm.py**: Atlas 14 generation

---

#### 6. repairing-geometry-issues

**Location**: `.claude/skills/repairing-geometry-issues/`
**Target Size**: SKILL.md ~250 lines

**Description**:
```yaml
description: |
  Automated geometry repair using RasFixit and quality validation using RasCheck.
  Handles blocked obstructions, generates before/after visualizations, and
  creates audit trails. Use when fixing geometry errors, repairing obstructions,
  validating models, or ensuring FEMA compliance.
```

**Content Outline**:
- Check → Fix → Verify workflow
- Blocked obstruction repair (elevation envelope algorithm)
- RasCheck validation (5 check types)
- Before/after visualization
- Backup and audit trail requirements
- Professional review requirements

**reference/rascheck.md**: RasCheck validation types
**reference/rasfixit.md**: Repair algorithms
**examples/check-fix-verify.py**: Complete workflow
**examples/obstruction-repair.py**: Blocked obstruction fix

---

### Phase 3 Skills: Specialized

#### 7. executing-remote-plans

**Location**: `.claude/skills/executing-remote-plans/`
**Target Size**: SKILL.md ~350 lines

**Description**:
```yaml
description: |
  Distributed HEC-RAS execution across remote workers (PsExec, Docker, SSH,
  cloud). Handles worker initialization, queue scheduling, and result aggregation.
  Use when setting up remote execution, distributed computation, cloud workflows,
  or scaling HEC-RAS across machines.
```

**Content Outline**:
- Worker initialization (init_ras_worker)
- PsExec configuration (session_id=2 CRITICAL)
- Docker worker setup (SSH + Docker)
- Distributed execution (compute_parallel_remote)
- Queue-aware wave scheduling
- Result collection

**reference/workers.md**: Worker type reference
**reference/psexec-setup.md**: PsExec critical configuration
**reference/docker-setup.md**: Docker worker configuration
**examples/psexec-worker.py**: PsExec execution
**examples/docker-worker.py**: Docker execution

---

#### 8. reading-dss-boundary-data

**Location**: `.claude/skills/reading-dss-boundary-data/`
**Target Size**: SKILL.md ~200 lines

**Description**:
```yaml
description: |
  Reads HEC-DSS files (V6 and V7) for boundary condition extraction using
  RasDss class. Handles JVM configuration, HEC Monolith download, catalog
  reading, and time series extraction. Use when working with DSS files,
  extracting boundary data, reading HEC-HMS output, or integrating DSS workflows.
```

**Content Outline**:
- Lazy loading (JVM configuration on first use)
- HEC Monolith auto-download
- Catalog reading (get_catalog)
- Time series extraction (read_timeseries)
- Batch extraction (read_multiple_timeseries)
- Boundary condition mapping (extract_boundary_timeseries)

**reference/dss-api.md**: Complete RasDss API
**reference/troubleshooting.md**: Java/JVM issues
**examples/read-catalog.py**: List DSS contents
**examples/extract-boundaries.py**: Extract all BC data

---

## Implementation Order (Recommended)

### Week 4 (Days 1-3): Subagents
**Day 1**:
1. ✅ Create hdf-analyst subagent (most complex, 18 classes)
2. ✅ Create geometry-parser subagent

**Day 2**:
3. ✅ Create remote-executor subagent (critical session_id guidance)
4. ✅ Create usgs-integrator subagent (14 modules)

**Day 3**:
5. ✅ Create precipitation-specialist subagent
6. ✅ Create quality-assurance subagent
7. ✅ Create documentation-generator subagent

### Week 4 (Days 4-5): Phase 1 Skills
**Day 4**:
1. ✅ Create executing-hecras-plans skill
2. ✅ Create extracting-hecras-results skill

**Day 5**:
3. ✅ Create parsing-hecras-geometry skill

### Week 5 (Days 1-2): Phase 2 Skills
**Day 1**:
4. ✅ Create integrating-usgs-gauges skill
5. ✅ Create analyzing-aorc-precipitation skill

**Day 2**:
6. ✅ Create repairing-geometry-issues skill

### Week 5 (Days 3-5): Phase 3 Skills + Testing
**Day 3**:
7. ✅ Create executing-remote-plans skill
8. ✅ Create reading-dss-boundary-data skill

**Days 4-5**:
- Test all subagent triggers
- Verify skill discovery
- Validate progressive disclosure
- Create testing checklist

---

## Key Implementation Patterns

### Trigger-Rich Descriptions

**Good** (discoverable):
```yaml
description: |
  Executes HEC-RAS plans using RasCmdr.compute_plan(), handles parallel
  execution across multiple plans, and monitors real-time progress. Use when
  running HEC-RAS simulations, computing plans, executing models, or setting
  up parallel workflows.
```

**Bad** (not discoverable):
```yaml
description: |
  Plan execution functionality.
```

**Why**: Trigger-rich descriptions include action verbs, specific class names, and common user phrases.

### Progressive Disclosure

**Main File** (SKILL.md or SUBAGENT.md):
- Quick start (50-100 lines)
- Common patterns (100-200 lines)
- Links to reference/ for details

**Reference Files**:
- Detailed API documentation
- Advanced patterns
- Troubleshooting

**Examples**:
- Executable scripts (run without loading context!)
- Basic and advanced scenarios

### Cross-References

**Subagents reference**:
- Parent CLAUDE.md files
- Subpackage AGENTS.md for technical details
- .claude/rules/ for coding patterns
- Relevant skills

**Skills reference**:
- Subpackage CLAUDE.md for workflows
- .claude/rules/ for implementation details
- Related skills
- Example notebooks

---

## Testing Checklist

After Phase 4 completion:

**Subagent Testing**:
- [ ] All 7 subagents created with YAML frontmatter
- [ ] Trigger descriptions tested with natural language queries
- [ ] Working directory paths verified
- [ ] Tool lists appropriate for each subagent
- [ ] Cross-references working (CLAUDE.md ↔ AGENTS.md ↔ rules/)

**Skill Testing**:
- [ ] All 8 skills created with YAML frontmatter
- [ ] Discovery phrases tested ("How do I run a plan?" → executing-hecras-plans)
- [ ] Progressive disclosure working (main < 500 lines, details in reference/)
- [ ] Example scripts executable
- [ ] Cross-references to CLAUDE.md and .claude/rules/ valid

**Integration Testing**:
- [ ] Subagent delegation working (main agent → specialist)
- [ ] Skill activation from natural language
- [ ] Context inheritance verified (root → subpackage → technical)
- [ ] No circular references
- [ ] File sizes appropriate

---

## Success Metrics

**Quantitative**:
- 7 subagents defined (100%)
- 8 library skills created (100%)
- Average subagent size: ~200 lines main file
- Average skill size: ~300 lines main file
- Reference files: ~150-400 lines per topic

**Qualitative**:
- Trigger-rich descriptions enable discovery
- Progressive disclosure working (metadata → main → reference)
- Specialist delegation clear and testable
- Cross-references comprehensive
- Example scripts executable without context loading

---

## Next Session Preparation

**Files to create** (15 subagent files + 24 skill files = 39 total):

**Subagents** (7 × ~2-3 files each = 15 files):
- hdf-analyst/{SUBAGENT.md, reference/*.md}
- geometry-parser/{SUBAGENT.md, reference/*.md}
- remote-executor/{SUBAGENT.md, reference/*.md}
- usgs-integrator/{SUBAGENT.md, reference/*.md}
- precipitation-specialist/{SUBAGENT.md, reference/*.md}
- quality-assurance/{SUBAGENT.md, reference/*.md}
- documentation-generator/{SUBAGENT.md, reference/*.md}

**Skills** (8 × ~3 files each = 24 files):
- executing-hecras-plans/{SKILL.md, reference/*.md, examples/*.py}
- extracting-hecras-results/{SKILL.md, reference/*.md, examples/*.py}
- parsing-hecras-geometry/{SKILL.md, reference/*.md, examples/*.py}
- integrating-usgs-gauges/{SKILL.md, reference/*.md, examples/*.py}
- analyzing-aorc-precipitation/{SKILL.md, reference/*.md, examples/*.py}
- repairing-geometry-issues/{SKILL.md, reference/*.md, examples/*.py}
- executing-remote-plans/{SKILL.md, reference/*.md, examples/*.py}
- reading-dss-boundary-data/{SKILL.md, reference/*.md, examples/*.py}

**Tools needed**:
- Write (for creating new files)
- Read (for referencing existing CLAUDE.md/AGENTS.md)
- Grep (for finding API patterns in code)

**Estimated effort**: ~8 hours total
- Subagents: ~4 hours (7 subagents × 30-40 min each)
- Skills: ~4 hours (8 skills × 30 min each)

---

## Handoff Notes

This document preserves:
1. Complete specifications for 7 subagents
2. Complete specifications for 8 skills
3. Implementation order and timeline
4. Success criteria and testing checklist
5. Example YAML frontmatter and content structures

When resuming:
- Start with hdf-analyst (most complex, sets pattern)
- Use trigger-rich descriptions for discovery
- Implement progressive disclosure (main → reference)
- Cross-reference to existing CLAUDE.md/AGENTS.md/.claude/rules/

**Branch**: feature/hierarchical-knowledge
**Ready for**: Phase 4 implementation

---

**Phase 4 Status**: 🎯 READY TO START
**Preparation Complete**: ✅ All specifications documented
**Next Action**: Create `.claude/subagents/hdf-analyst/SUBAGENT.md`
