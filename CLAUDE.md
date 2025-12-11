# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## AGENTS.md Standard (Read Me First)

This repository now uses the AGENTS.md standard alongside CLAUDE.md.

- Treat any `AGENTS.md` in the current folder (and its parents up to the repo root) the same way you treat `CLAUDE.md` files.
- Scope and precedence:
  - The `AGENTS.md` at a folder applies to that folder and all subfolders.
  - More-deeply-nested `AGENTS.md` files override parent guidance when conflicts arise.
  - Direct, explicit instructions in the task or doc you’re reading take precedence.
- Always read both `CLAUDE.md` and `AGENTS.md` for the working directory before editing code or running tools.
- Key locations with scoped guidance:
  - `/AGENTS.md` (root)
  - `/ras_commander/AGENTS.md` (library API and coding conventions)
  - `/ras_commander/remote/AGENTS.md` (remote execution subpackage)
  - `/examples/AGENTS.md` (notebook index and extraction workflow)
  - `/examples/data/AGENTS.md` (small reference datasets; read-only)
  - `/examples/example_projects/AGENTS.md` (large HEC‑RAS examples; do not commit extractions)
  - `/ai_tools/AGENTS.md` (maintainer-only; ignore when using the library)

Important highlights from AGENTS.md:
- Ignore `ai_tools/` and any generated knowledge bases; they are maintainer-only.
- Prefer cleaned notebooks; otherwise treat notebooks as reference and extract logic into scripts.
- Use a single uv-managed venv at the repo root and install in editable mode (`uv venv .venv`, `uv pip install -e .`).

## Project Overview

**ras-commander** is a Python library for automating HEC-RAS (Hydrologic Engineering Center's River Analysis System) operations. It provides a comprehensive API for interacting with HEC-RAS project files, executing simulations, and processing results through HDF data analysis.

## Development Environment

### Build Commands
- **Build package**: `python setup.py sdist bdist_wheel`
- **Clean build**: Remove `build/`, `dist/`, and `*.egg-info` directories before building
- **Install locally**: `pip install -e .` (for development)
- **Install from build**: `pip install ras-commander`

### Testing Strategy
- Uses **Test Driven Development** with HEC-RAS example projects instead of traditional unit tests
- Example projects are located in `examples/` and `tests/example_projects/`
- Test scripts are in `tests/` directory (e.g., `test_ras_examples_initialization.py`)
- All example notebooks in `examples/` serve as both documentation and functional tests
- Run example tests: `python test_ras_examples_initialization.py`

### Dependencies
- **Python**: Requires 3.10+
- **Core packages**: h5py, numpy, pandas, geopandas, matplotlib, shapely, scipy, xarray, tqdm, requests, rasterstats, rtree
- **Legacy support**: pywin32>=227 (COM interface), psutil>=5.6.6 (process management)
- **Optional**:
  - tkinterdnd2 (for GUI applications with drag-and-drop)
  - dataretrieval (for USGS gauge data integration)
  - paramiko (for Docker/SSH remote execution)
- Install dependencies: `pip install h5py numpy pandas requests tqdm scipy xarray geopandas matplotlib shapely pathlib rasterstats rtree pywin32 psutil`
- Install optional: `pip install dataretrieval` (USGS data), `pip install paramiko docker` (remote execution)

### Environment Management
- Supports both pip and uv for package management
- Development pattern: Clone repo and use `sys.path.append()` method (see examples for import pattern)
- Create virtual environment recommended: `python -m venv venv` or `conda create`

## Architecture Overview

### Core Classes and Execution Model

**Primary Execution Class**: `RasCmdr` - Static class for HEC-RAS plan execution
- `RasCmdr.compute_plan(plan_number, dest_folder=None, ras_object=None, clear_geompre=False, num_cores=None, overwrite_dest=False, stream_callback=None)`
- `RasCmdr.compute_parallel()` - Parallel execution across multiple worker processes
- `RasCmdr.compute_test_mode()` - Sequential execution in test environment

**Legacy Version Support**: `RasControl` - COM interface for HEC-RAS 3.x-4.x
- Uses ras-commander style API (plan numbers, not file paths)
- Integrates with `init_ras_project()` and `ras` object
- Open-operate-close pattern prevents conflicts with modern workflows
- Supported versions: 3.1, 4.1, 5.0.x (501, 503, 505, 506), 6.0, 6.3, 6.6
- Public methods (ras-commander style):
  - `init_ras_project(path, "4.1")` - Initialize with version
  - `RasControl.run_plan("02")` - Run plan by number
  - `RasControl.get_steady_results("02")` - Extract steady profiles
  - `RasControl.get_unsteady_results("01", max_times=10)` - Extract time series
  - `RasControl.get_output_times("01")` - List unsteady timesteps
  - `RasControl.set_current_plan("Steady Flow Run")` - Switch active plan
- Private methods handle all COM interface details
- See `examples/17_extracting_profiles_with_hecrascontroller.ipynb` for complete usage

**Project Management**: `RasPrj` class and global `ras` object
- Initialize projects: `init_ras_project(path, ras_version, ras_object=None)`
- Global `ras` object available for single-project workflows
- Multiple project support via separate `RasPrj` instances

**File Operations Classes**:
- `RasPlan` - Plan file operations and modifications
- `RasGeo` - Geometry file operations (2D Manning's n land cover)
- `RasGeometry` - Geometry parsing (1D cross sections, storage, connections)
- `RasGeometryUtils` - Geometry parsing utilities (fixed-width, count interpretation)
- `RasStruct` - Inline structure parsing (bridges, culverts, inline weirs) **NEW**
- `RasBreach` - Breach parameter modification in plan files
- `RasUnsteady` - Unsteady flow file management
- `RasUtils` - Utility functions for file operations
- `RasMap` - RASMapper configuration parsing
- `RasExamples` - HEC-RAS example project management and extraction

**HDF Data Processing Classes**:
- `HdfBase`, `HdfPlan`, `HdfMesh` - Core HDF file operations
- `HdfResults*` classes - Results processing and analysis (unsteady and **steady state**)
- `HdfStruc` - Structure data and SA/2D connection listings
- `HdfResultsBreach` - Dam breach results extraction from HDF files **NEW**
- `HdfHydraulicTables` - Cross section property tables (HTAB) **NEW**
- `HdfPipe`, `HdfPump` - Infrastructure analysis
- `HdfPlot`, `HdfResultsPlot` - Visualization utilities

**New Steady State Support** (as of v0.80.3+):
- `HdfResultsPlan.is_steady_plan()` - Check if HDF contains steady state results
- `HdfResultsPlan.get_steady_profile_names()` - Extract steady state profile names
- `HdfResultsPlan.get_steady_wse()` - Extract water surface elevations for profiles
- `HdfResultsPlan.get_steady_info()` - Extract steady flow metadata
- See `examples/19_steady_flow_analysis.ipynb` for complete usage examples

**New Geometry Parsing Support** (as of v0.81.0+):
- `RasGeometry` - Comprehensive geometry parsing and modification
  - Cross sections: `get_cross_sections()`, `get_station_elevation()`, `set_station_elevation()`
  - Manning's n: `get_mannings_n()`, bank stations, expansion/contraction coefficients
  - Storage areas: `get_storage_areas()`, `get_storage_elevation_volume()`
  - Lateral structures: `get_lateral_structures()`, `get_lateral_weir_profile()`
  - SA/2D connections: `get_connections()`, `get_connection_weir_profile()`, `get_connection_gates()`
- `HdfHydraulicTables` - Extract property tables (HTAB) from preprocessed geometry HDF
  - `get_xs_htab()` - Area, conveyance, wetted perimeter vs elevation
  - Enables rating curves without re-running HEC-RAS
- **Critical Features**: Automatic bank station interpolation, 450 point limit enforcement
- See `research/geometry file parsing/api-geom.md` for complete API reference
- See `research/geometry file parsing/example_notebooks/02_complete_geometry_operations.ipynb`

**Dam Breach Operations** (as of v0.81.0+):
- **Architectural Pattern**: Plain text (Ras*) vs HDF (Hdf*) separation
- `RasBreach` - Breach PARAMETERS in plan files (.p##)
  - `list_breach_structures_plan()` - List structures from plan file
  - `read_breach_block()` - Read breach parameters
  - `update_breach_block()` - Modify breach parameters
- `HdfResultsBreach` - Breach RESULTS from HDF files (.p##.hdf)
  - `get_breach_timeseries()` - Complete time series (flow, stage, geometry)
  - `get_breach_summary()` - Summary statistics (peaks, timing)
  - `get_breaching_variables()` - Breach geometry evolution
  - `get_structure_variables()` - Structure flow variables
- **Important**: Use plan file names for parameters, HDF may have different naming
- See `examples/18_breach_results_extraction.ipynb` for workflow examples

**DSS File Operations** (as of v0.82.0+):
- `RasDss` - Read HEC-DSS files (V6 and V7) for boundary conditions **NEW**
  - `get_catalog(dss_file)` - List all paths in DSS file
  - `read_timeseries(dss_file, pathname)` - Read time series as DataFrame
  - `read_multiple_timeseries(dss_file, pathnames)` - Batch read multiple paths
  - `extract_boundary_timeseries(boundaries_df, ras_object)` - Auto-extract all DSS boundary data
  - `get_info(dss_file)` - File summary and statistics
- **Technology**: HEC Monolith libraries (auto-downloaded on first use, ~17 MB)
- **Java Bridge**: pyjnius (pip installable, lazy loaded)
- **Dependencies**: Requires `pip install pyjnius` and Java 8+ (JRE or JDK)
- **Lazy Loading**: No overhead unless DSS methods are called
- **Tested**: 84 DSS files (6.64 GB), 88% success rate, handles files up to 1.3 GB
- See `examples/22_dss_boundary_extraction.ipynb` for complete workflow

**Inline Structure Parsing** (as of v0.84.0+):
- `RasStruct` - Parse inline structures from geometry files (.g##) **NEW**
  - Inline Weirs: `get_inline_weirs()`, `get_inline_weir_profile()`, `get_inline_weir_gates()`
  - Bridges: `get_bridges()`, `get_bridge_deck()`, `get_bridge_piers()`, `get_bridge_abutment()`
  - Bridge Details: `get_bridge_approach_sections()`, `get_bridge_coefficients()`, `get_bridge_htab()`
  - Culverts: `get_culverts()`, `get_all_culverts()`
- **Culvert Shape Codes**: 1=Circular, 2=Box, 3=Pipe Arch, 4=Ellipse, 5=Arch, 6=Semi-Circle, 7=Low Profile Arch, 8=High Profile Arch, 9=Con Span
- **Parsing**: Uses 8-character fixed-width and comma-separated formats
- See `research/geometry file parsing/api-geom.md` for complete API reference

**Geometry Repair (Fixit Module)**:
- `RasFixit` - Automated geometry repair for common HEC-RAS issues
  - `fix_blocked_obstructions()` - Fix overlapping blocked obstructions using elevation envelope algorithm
  - `detect_obstruction_overlaps()` - Non-destructive detection of obstruction issues
- **Result Classes**: `FixResults`, `FixMessage`, `FixAction` for detailed fix reporting
- **Log Parsing**: `log_parser` submodule parses HEC-RAS compute logs for error detection
- **Verification Outputs**: Before/after PNG visualizations, timestamped backups, audit trails
- **Algorithm**: Uses max elevation in overlap zones (hydraulically conservative), inserts 0.02-unit gaps
- **Example Project**: HCFCD M3 Model A120-00-00 included in `examples/example_projects/`
- See `examples/27_fixit_blocked_obstructions.ipynb` for complete workflow

**USGS Gauge Data Integration** (as of v0.86.0+):
- `ras_commander.usgs` - Complete workflow for integrating USGS gauge data with HEC-RAS models **NEW**
- **Core Data Retrieval** (`RasUsgsCore`):
  - `retrieve_flow_data()` - Retrieve flow time series from USGS NWIS (instantaneous or daily)
  - `retrieve_stage_data()` - Retrieve stage/elevation time series
  - `get_gauge_metadata()` - Get gauge metadata (location, drainage area, station name)
  - `check_data_availability()` - Check if data exists for a time period
- **Spatial Queries** (`UsgsGaugeSpatial`):
  - `find_gauges_in_project()` - Query USGS gauges within HEC-RAS project bounds
  - `get_project_gauges_with_data()` - Find gauges with available data for simulation period
- **Gauge Matching** (`GaugeMatcher`):
  - `match_gauge_to_cross_section()` - Match gauge to nearest 1D cross section
  - `match_gauge_to_2d_area()` - Match gauge to 2D flow area
  - `auto_match_gauges()` - Automatically match multiple gauges to model features
- **Time Series Processing** (`RasUsgsTimeSeries`):
  - `resample_to_hecras_interval()` - Resample to HEC-RAS intervals (15MIN, 1HOUR, etc.)
  - `check_data_gaps()` - Detect and report data quality issues
  - `align_timeseries()` - Align observed and modeled data for validation
- **Initial Conditions** (`InitialConditions`):
  - `create_ic_line()` - Generate properly formatted IC lines for .u## files
  - `get_ic_value_from_usgs()` - Extract IC value from USGS data at simulation start
  - `parse_initial_conditions()` - Parse existing IC lines from unsteady files
- **Boundary Conditions** (`RasUsgsBoundaryGeneration`):
  - `generate_flow_hydrograph_table()` - Create fixed-width flow table for .u## files
  - `generate_stage_hydrograph_table()` - Create stage boundary condition table
  - `update_boundary_hydrograph()` - Update existing boundary condition in unsteady file
- **Validation Metrics** (`metrics` module):
  - `nash_sutcliffe_efficiency()` - NSE metric for model performance
  - `kling_gupta_efficiency()` - KGE metric with components (correlation, bias, variability)
  - `calculate_peak_error()` - Peak flow/stage error and timing
  - `calculate_all_metrics()` - Comprehensive suite of validation metrics
- **Visualization** (`visualization` module):
  - `plot_timeseries_comparison()` - Publication-quality observed vs modeled plots
  - `plot_scatter_comparison()` - Scatter plots with 1:1 line and statistics
  - `plot_residuals()` - 4-panel residual diagnostics
- **File I/O** (`RasUsgsFileIo`):
  - `cache_gauge_data()` - Save USGS data to standardized CSV format
  - `load_cached_gauge_data()` - Load cached data with metadata
  - `get_gauge_data_dir()` - Create gauge_data/ directory structure
- **Dependencies**: Requires `pip install dataretrieval` for USGS NWIS access
- **Lazy Loading**: Module loads without dataretrieval; methods check on first use
- See `examples/29_usgs_gauge_data_integration.ipynb` for complete workflow

**Real-Time Computation Messages** (as of v0.88.0+):
- `stream_callback` parameter for `RasCmdr.compute_plan()` - Monitor HEC-RAS execution progress in real-time
- **BcoMonitor** - Utility class for .bco file monitoring
  - `enable_detailed_logging()` - Automatically enable "Write Detailed=1" in plan files
  - `monitor_until_signal()` - Poll .bco file for execution messages and signals
  - Thread-safe incremental file reading with encoding resilience
- **ExecutionCallback Protocol** - Type-safe callback interface (all methods optional)
  - `on_prep_start()` - Called before geometry preprocessing
  - `on_prep_complete()` - Called after preprocessing complete
  - `on_exec_start()` - Called when HEC-RAS subprocess starts
  - `on_exec_message()` - Called for each new .bco file message (real-time streaming)
  - `on_exec_complete()` - Called when execution finishes (success or failure)
  - `on_verify_result()` - Called after HDF verification (if verify=True)
- **Example Callbacks** (`ras_commander.callbacks`):
  - `ConsoleCallback` - Simple console output (verbose mode available)
  - `FileLoggerCallback` - Per-plan log files with thread-safe file operations
  - `ProgressBarCallback` - tqdm progress bars (requires: pip install tqdm)
  - `SynchronizedCallback` - Thread-safe wrapper for non-thread-safe callbacks
- **Thread Safety**: All example callbacks use threading.Lock for safe parallel execution
- **Backward Compatible**: Optional parameter (default None), no impact on existing code
- Usage: `RasCmdr.compute_plan("01", stream_callback=ConsoleCallback())`

### Execution Modes
1. **Single Plan**: `RasCmdr.compute_plan()` - Execute one plan with full parameter control
2. **Parallel**: `RasCmdr.compute_parallel()` - Run multiple plans simultaneously using worker folders
3. **Sequential**: `RasCmdr.compute_test_mode()` - Run multiple plans in order in test folder
4. **Distributed**: `compute_parallel_remote()` - Execute plans across remote machines via PsExec/SSH/cloud

**Remote Execution Subpackage**: `ras_commander.remote` (as of v0.85.0+)
- Refactored from single module to subpackage with lazy loading
- `init_ras_worker()` - Factory function to create and validate remote workers
- `compute_parallel_remote()` - Execute plans across distributed worker pool
- **PsexecWorker** - Windows remote execution via PsExec over network shares (✓ implemented)
- **LocalWorker** - Local parallel execution (✓ implemented)
- **DockerWorker** - Container execution via Docker over SSH (✓ implemented, requires: docker, paramiko)
- **Future workers**: SshWorker, WinrmWorker, SlurmWorker, AwsEc2Worker, AzureFrWorker
- Worker abstraction enables heterogeneous execution (local + remote + cloud simultaneously)
- Queue-aware wave scheduling across all worker types
- **Lazy loading**: Remote module only loaded when `init_ras_worker` or workers are accessed
- **Optional dependencies**: `pip install ras-commander[remote-ssh]`, `[remote-aws]`, `[remote-all]`
- See `examples/23_remote_execution_psexec.ipynb` for complete usage
- See `feature_dev_notes/RasRemote/REMOTE_WORKER_SETUP_GUIDE.md` for setup instructions
- See `ras_commander/remote/AGENTS.md` for subpackage-specific guidance

**Critical for HEC-RAS Remote Execution:**
- HEC-RAS is a GUI application and requires session-based execution
- Use `session_id=2` (typical for workstations), NOT `system_account=True`
- Remote machine requires Group Policy configuration (network access, local logon, batch job rights)
- Registry key `LocalAccountTokenFilterPolicy=1` required
- Remote Registry service must be running
- User must be in Administrators group

## Key Development Patterns

### Static Class Pattern
- Most classes use static methods with `@log_call` decorators
- No instantiation required: `RasCmdr.compute_plan()` not `RasCmdr().compute_plan()`
- Pass `ras_object` parameter when working with multiple projects

### Import Flexibility Pattern
```python
# Flexible imports for development vs installed package
try:
    from ras_commander import init_ras_project, RasCmdr, RasPlan
except ImportError:
    current_file = Path(__file__).resolve()
    parent_directory = current_file.parent.parent
    sys.path.append(str(parent_directory))
    from ras_commander import init_ras_project, RasCmdr, RasPlan
```

### Path Handling
- Use `pathlib.Path` objects consistently
- Support both string paths and Path objects in function parameters
- Handle Windows paths with proper escaping

### Error Handling and Logging
- Comprehensive logging using centralized `LoggingConfig`
- Use `@log_call` decorator for automatic function call logging
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs written to both console and rotating file (`ras_commander.log`)

### Naming Conventions
- **Functions/Variables**: snake_case (`compute_plan`, `plan_number`)
- **Classes**: PascalCase (`RasCmdr`, `HdfBase`)
- **Constants**: UPPER_CASE
- **Abbreviations**: ras, prj, geom, geompre, num, init, BC, IC, TW

### Function Naming: Technological Lineage

Function names in ras-commander reflect the conventions of their underlying technology source. This creates consistency with the data structures and APIs they interact with.

#### RasControl Class - Legacy HEC-RAS Conventions
- **Naming Style**: Abbreviated, matching HECRASController COM interface
- **Example**: `get_comp_msgs()` uses "comp_msgs" to match legacy .txt filename convention
- **Rationale**: Maintains consistency with pre-5.x HEC-RAS terminology and file naming
- **Versions**: Targets HEC-RAS 3.x-4.x (with 5.x/6.x fallback support)

#### HdfResultsPlan Class - Modern HDF Structure Conventions
- **Naming Style**: Descriptive, matching HDF dataset/group names
- **Example**: `get_compute_messages()` uses "compute_messages" to match HDF path naming
- **Rationale**: Function names mirror the actual HDF structure: `Results/Summary/Compute Messages (text)`
- **Pattern**: Read HDF file structure and derive Python method names from group/dataset names
- **Versions**: Targets HEC-RAS 6.x+ HDF-based results

#### Why Names Differ Between Classes
The naming differences are **intentional and contextually appropriate**:
- `RasControl.get_comp_msgs()` - reflects `.comp_msgs.txt` and `.computeMsgs.txt` file conventions
- `HdfResultsPlan.get_compute_messages()` - reflects `Compute Messages (text)` HDF dataset naming

This is not inconsistency, but **technological lineage** - each reflects its underlying data source conventions. Users benefit from predictable mapping between Python methods and the data structures they access.

#### Guideline for New Functions
When adding new functions:
1. **For RasControl**: Match legacy HEC-RAS/HECRASController naming conventions
2. **For HdfResultsPlan**: Inspect HDF structure and mirror group/dataset names
3. **For other classes**: Follow snake_case with descriptive, unabbreviated names

### Documentation Standards
- Comprehensive docstrings with Args, Returns, Raises, Examples sections
- Include usage examples in all major functions
- Document parameter types and optional parameters clearly

## Working with HEC-RAS Projects

### Project Initialization
```python
# Single project (uses global ras object)
init_ras_project(r"/path/to/project", "6.5")

# Multiple projects
project1 = RasPrj()
init_ras_project(r"/path/to/project1", "6.5", ras_object=project1)
```

### Accessing Project Data
- `ras.plan_df` - Plans dataframe
- `ras.geom_df` - Geometry files dataframe  
- `ras.flow_df` - Flow files dataframe
- `ras.unsteady_df` - Unsteady files dataframe
- `ras.boundaries_df` - Boundary conditions dataframe

### Plan Execution Parameters
- `plan_number`: Plan ID (string, e.g., "01", "02")
- `dest_folder`: Optional computation folder (None = modify original)
- `clear_geompre`: Clear geometry preprocessor files (Boolean)
- `num_cores`: Number of processing cores (Integer)
- `overwrite_dest`: Overwrite existing destination (Boolean)
- `stream_callback`: Optional callback for real-time progress monitoring (Callable, default None)

### Example Project Management with RasExamples
```python
# Extract HEC-RAS example projects for testing
# Default extraction to 'example_projects' folder
path = RasExamples.extract_project("Muncie")

# Extract to custom location (relative or absolute path)
path = RasExamples.extract_project("Dam Breaching", output_path="my_tests")
paths = RasExamples.extract_project(["Muncie", "Balde Eagle Creek"], output_path="C:/tests")

# List available projects and categories
all_projects = RasExamples.list_projects()
categories = RasExamples.list_categories()
category_projects = RasExamples.list_projects("1D Unsteady Flow Hydraulics")
```

## GUI Application Development

### Existing GUI Pattern
- See `tools/1D Mannings to L-MC-R/1D_Mannings_to_L-MC-R.py` for tkinter GUI example
- Uses tkinterdnd2 for drag-and-drop functionality
- Progress bars and real-time logging display
- Error handling with user-friendly messages
- PyInstaller compilation for exe distribution

### Recommended GUI Libraries
- **tkinter** - Built-in, good for simple applications
- **tkinterdnd2** - Add drag-and-drop support
- **PyQt5/PySide2** - For more advanced GUIs
- **PyInstaller** - Create standalone executables

## File Structure Conventions

### Project Organization
- Main library code in `ras_commander/`
- Examples and documentation in `examples/`
- Test projects in `tests/example_projects/`
- GUI applications in `apps/` (create if needed)
- Utility tools in `tools/`
- AI/LLM resources in `ai_tools/`
- **Planning documents in `planning_docs/`** - All temporary markdown files, analysis reports, and planning documents created during development should be placed here, not in the repository root

### Planning Documents Rule
When creating planning documents, analysis reports, or temporary markdown/text files during development:
- **Always place them in `planning_docs/`** subfolder, not in the repository root
- This keeps the root directory clean and focused on repository essentials
- Planning docs are not committed to the repository (add to .gitignore if needed)
- Examples of files that belong in `planning_docs/`:
  - Implementation plans (e.g., `DOCUMENTATION_REVISION_PLAN.md`)
  - Analysis reports (e.g., `HDF_COMPARISON_REPORT.md`)
  - Comparison outputs (e.g., `precipitation_comparison_output.txt`)
  - Temporary test scripts created during investigation

### Creating New Applications
- Create subdirectory in `apps/` or `tools/`
- Include separate `requirements.txt` or `pyproject.toml`
- Follow existing naming patterns (snake_case for directories)
- Include README.md with installation and usage instructions
- Use uv for environment management when possible

## AI/LLM Integration Notes

- Repository has extensive AI tooling in `ai_tools/`
- Knowledge bases generated automatically during build process
- Cursor IDE integration with `.cursorrules`
- Optimized for LLM code assistance and generation
- Examples serve dual purpose as documentation and tests to reduce hallucination

## Agent Coordination for Long-Running Tasks

For complex, multi-session development tasks, use the agent coordination system located at:
**`agent_tasks/`** (in repository root)

### When to Use Agent Coordination

**Use for:**
- Multi-session features (can't finish in one context window)
- Complex tasks requiring exploration and planning
- Work involving multiple files and components
- Tasks where decisions and rationale need tracking

**Don't use for:**
- Simple bug fixes or single-file changes
- Quick documentation updates
- Obvious, straightforward implementations

### Session Lifecycle

**Every session start:**
1. Read `agent_tasks/.agent/STATE.md` - Current project state
2. Read `agent_tasks/.agent/PROGRESS.md` (last 2 entries) - Recent context
3. Check `agent_tasks/.agent/BACKLOG.md` - Pick next task if nothing in progress

**During session:**
- Work on ONE task at a time
- Make incremental commits
- Document decisions in PROGRESS.md
- Update STATE.md if blocked

**Every session end:**
1. Update `.agent/STATE.md` with current status
2. Append to `.agent/PROGRESS.md` with session summary
3. Update `.agent/BACKLOG.md` (mark completed, add new tasks)
4. Write detailed handoff notes (assume next session knows nothing)

### Memory System Files

- **STATE.md** - Single source of truth for project state (health, current focus, blockers)
- **CONSTITUTION.md** - Project principles, constraints, quality standards
- **BACKLOG.md** - Task queue (ready/blocked/completed)
- **PROGRESS.md** - Append-only session log with handoff notes
- **LEARNINGS.md** - What worked, what didn't, project-specific patterns

### Task Organization

Active tasks use folder structure: `agent_tasks/tasks/{task-id}-{name}/`
- Each task folder contains TASK.md, work files, and RESULT.md
- Completed tasks archived to `agent_tasks/.old/tasks/`
- Planning docs go in `agent_tasks/.old/planning/`

### Key Principle

**Every session starts with amnesia - only files persist.** The memory system ensures context continuity across sessions by maintaining structured state in markdown files.

See `agent_tasks/README.md` for complete coordination system documentation.

### Strategic Planning

The repository includes comprehensive strategic planning documents:

**Development Roadmap** (`agent_tasks/ROADMAP.md`):
- 15 major feature areas analyzed
- Organized in 4 phases by priority and complexity
- Timeline estimates and resource allocation guidance
- Generated from `feature_dev_notes/` and `planning_docs/` analysis

**Git Worktree Workflow** (`agent_tasks/WORKTREE_WORKFLOW.md`):
- Develop features in isolated worktrees
- Sideload `feature_dev_notes/` and `planning_docs/` for research access
- Share `agent_tasks/` memory system across all worktrees
- Clean git history with branch isolation

These planning documents provide long-term direction and recommended development patterns.

## Documentation Build Configuration

### Dual-Platform Deployment
Documentation is deployed to two platforms:
- **GitHub Pages**: https://gpt-cmdr.github.io/ras-commander/ (via `.github/workflows/docs.yml`)
- **ReadTheDocs**: https://ras-commander.readthedocs.io (via `.readthedocs.yaml`)

### Notebook Integration
Example notebooks from `examples/` are integrated into docs at `docs/notebooks/`:

**GitHub Actions** (`.github/workflows/docs.yml`):
```yaml
- name: Create notebooks symlink
  run: ln -s ../examples docs/notebooks
```

**ReadTheDocs** (`.readthedocs.yaml`):
```yaml
build:
  jobs:
    pre_build:
      - cp -r examples docs/notebooks  # MUST use cp, NOT ln -s
```

### Critical: ReadTheDocs Strips Symlinks
**ReadTheDocs uses `rsync --safe-links` during deployment, which removes symlinks for security.**
- Symlinks work during build but content is NOT uploaded to the live site
- Always use `cp -r` instead of `ln -s` in `.readthedocs.yaml`
- The `.gitignore` includes `docs/notebooks/` to prevent committing copied files

### Validation Configuration
The `mkdocs.yml` includes validation settings to handle AGENTS.md files (which contain relative links to Python source files):
```yaml
validation:
  links:
    unrecognized_links: info  # Prevents strict mode failures
```

### mkdocs-jupyter Configuration
```yaml
- mkdocs-jupyter:
    include_source: true
    execute: false
    include: ["notebooks/*.ipynb"]
    ignore: ["notebooks/example_projects/**"]
    ignore_h1_titles: true  # Use nav titles, not notebook H1
```

### Notebook Title Requirements
Each notebook must have a markdown cell with an H1 heading as its first cell. This title is used in navigation when `ignore_h1_titles: false`, but with `ignore_h1_titles: true`, the nav entry title takes precedence.

## Common Pitfalls to Avoid

- Don't instantiate static classes like `RasCmdr()`
- Always specify `ras_object` parameter when working with multiple projects
- Use pathlib.Path for all path operations
- Don't forget `@log_call` decorator on new functions
- Ensure HEC-RAS project is initialized before calling compute functions
- Handle file permissions carefully on Windows systems
- Test with actual HEC-RAS example projects, not synthetic data
- **Never use symlinks in ReadTheDocs builds** - they get stripped during deployment
- **Keep `.readthedocs.yaml` and `.github/workflows/docs.yml` in sync** for notebook handling
