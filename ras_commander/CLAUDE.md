# ras_commander Library Context

This file provides tactical guidance for working with the core `ras_commander/` library. For strategic overview, see the root `CLAUDE.md`. For detailed coding patterns, see `.claude/rules/`.

## Module Organization

The ras_commander library is organized into core modules and specialized subpackages.

### Core Modules

**Project Management**:
- `RasPrj` (`RasPrj.py`) - Project initialization and management
  - Initialize projects with `init_ras_project()`
  - Access project dataframes: `plan_df`, `geom_df`, `flow_df`, `unsteady_df`, `boundaries_df`
  - Helpers: `get_ras_exe()`, `is_valid_ras_folder()`

**Plan Execution**:
- `RasCmdr` (`RasCmdr.py`) - Plan execution engine (single/parallel/remote)
  - `compute_plan()` - Execute single plan with full parameter control
  - `compute_parallel()` - Execute multiple plans simultaneously
  - `compute_test_mode()` - Sequential execution in test folder

**File Operations**:
- `RasPlan` (`RasPlan.py`) - Plan file operations (clone, retarget, update parameters)
- `RasMap` (`RasMap.py`) - RASMapper configuration parsing and stored map processing
- `RasControl` (`RasControl.py`) - Legacy HEC-RAS 3.x-4.x COM interface

**Validation Framework**:
- `validation_base` (`validation_base.py`) - Core validation infrastructure
  - `ValidationSeverity` - Severity levels (INFO < WARNING < ERROR < CRITICAL)
  - `ValidationResult` - Single validation check result
  - `ValidationReport` - Comprehensive validation report
  - Used by `RasDss`, `RasMap`, and other modules for pre-flight checks

**HDF Data Access** (14+ modules):
- `HdfBase`, `HdfUtils` - Shared HDF helpers and utilities
- `HdfMesh`, `HdfBndry`, `HdfXsec`, `HdfStruc`, `HdfPlan` - Geometry and metadata extraction
- `HdfResultsMesh`, `HdfResultsPlan`, `HdfResultsXsec` - Results time series extraction
- `HdfPipe`, `HdfPump` - Infrastructure analysis (HEC-RAS 6.6+)
- `HdfPlot`, `HdfResultsPlot` - Visualization helpers

### Specialized Subpackages

Each subpackage has its own CLAUDE.md or AGENTS.md file with detailed guidance:

**hdf/** (14 modules):
- HDF data extraction and analysis
- See `ras_commander/hdf/AGENTS.md`

**geom/** (10 modules):
- Geometry parsing (1D cross sections, storage areas, connections)
- Plain text geometry file operations
- See `ras_commander/geom/AGENTS.md`

**remote/** (12 modules):
- Distributed execution across remote machines
- Worker types: PsexecWorker, DockerWorker, LocalWorker
- See `ras_commander/remote/AGENTS.md` and `.claude/rules/hec-ras/remote.md`

**usgs/** (14 modules):
- USGS gauge data integration and validation
- Real-time monitoring, boundary conditions, model validation
- See `ras_commander/usgs/CLAUDE.md` (after Phase 3 implementation)

**check/** (5 modules):
- Quality assurance (RasCheck framework)
- Automated validation following FEMA/USACE standards
- See `ras_commander/check/CLAUDE.md` (after Phase 3 implementation)

**precip/** (3 modules):
- AORC precipitation and Atlas 14 design storms
- See `ras_commander/precip/CLAUDE.md` (after Phase 3 implementation)

**mapping/** (3 modules):
- Programmatic result mapping and rasterization
- See `ras_commander/mapping/CLAUDE.md` (after Phase 3 implementation)

**dss/** (3 modules):
- DSS file operations for boundary conditions
- See `ras_commander/dss/AGENTS.md`

**fixit/** (6 modules):
- Automated geometry repair (RasFixit framework)
- See `ras_commander/fixit/AGENTS.md`

## Common Workflow Pattern

Most ras-commander workflows follow this progression:

1. **Initialize** - `init_ras_project()` → load project metadata
2. **Execute** - `RasCmdr.compute_plan()` → run HEC-RAS simulation
3. **Extract** - `HdfResults*` classes → extract results from HDF files

Example:
```python
from ras_commander import init_ras_project, RasCmdr, HdfResultsMesh

# 1. Initialize
init_ras_project("C:/Projects/MyModel", "C:/Program Files/HEC/HEC-RAS/6.6/Ras.exe")

# 2. Execute
RasCmdr.compute_plan("01", dest_folder="working/run01", overwrite_dest=True)

# 3. Extract
results = HdfResultsMesh.get_mesh_timeseries("01", variables=["Water Surface"])
```

## Static Class Pattern

Most classes in ras_commander use static methods and act as organized namespaces.

**DO NOT instantiate these classes**:
```python
# ❌ INCORRECT
cmdr = RasCmdr()
cmdr.compute_plan("01")

# ✅ CORRECT
RasCmdr.compute_plan("01")
```

**Classes using static pattern**:
- `RasCmdr`, `RasPlan`, `RasMap`, `RasControl`
- All `Hdf*` classes (`HdfMesh`, `HdfResultsPlan`, etc.)
- All `Ras*` geometry classes (`RasGeometry`, `RasStruct`, etc.)

See `.claude/rules/python/static-classes.md` for complete pattern details.

## Input Normalization

Many HDF-facing functions accept flexible inputs through the `@standardize_input` decorator:

**Accepted formats**:
- `h5py.File` object (direct HDF file handle)
- `Path` object (pathlib.Path to HDF file)
- String path (e.g., "C:/Projects/MyModel/MyPlan.p01.hdf")
- Plan/geometry number (e.g., "01", "p01", "g02")

**Example**:
```python
from ras_commander import HdfMesh

# All of these work:
cells = HdfMesh.get_mesh_cell_polygons("01")  # Plan number
cells = HdfMesh.get_mesh_cell_polygons("p01")  # Plan number with prefix
cells = HdfMesh.get_mesh_cell_polygons(Path("project/plan.p01.hdf"))  # Path
```

**Multiple projects**:
When working with multiple projects, pass `ras_object` parameter:
```python
project1 = RasPrj()
init_ras_project("C:/Model1", ras_object=project1)

cells = HdfMesh.get_mesh_cell_polygons("01", ras_object=project1)
```

## Key Conventions

### Plan Numbers
- Always use two-digit format: `"01"`, `"02"`, etc.
- Functions accept with or without prefix: `"01"` or `"p01"`

### Logging
All public methods should use the logging pattern:
```python
from ras_commander import get_logger, log_call

logger = get_logger(__name__)

@log_call
def my_function():
    logger.info("Processing...")
```

See `.claude/rules/python/decorators.md` for decorator details.

### Path Handling
Use pathlib.Path consistently:
```python
from pathlib import Path

project_folder = Path("C:/Projects/MyModel")
plan_file = project_folder / "MyPlan.p01"
```

See `.claude/rules/python/path-handling.md` for complete pattern.

### Imports
Follow standard order:
```python
# Standard library
from pathlib import Path
import logging

# Third-party
import pandas as pd
import h5py

# Local
from ras_commander import init_ras_project
```

See `.claude/rules/python/import-patterns.md` for details.

## When to Use Which Module

**Want to run HEC-RAS?**
→ Use `RasCmdr` for modern HEC-RAS 6.x
→ Use `RasControl` for legacy HEC-RAS 3.x-4.x

**Want to modify plan files?**
→ Use `RasPlan` for plan parameters (cores, intervals, titles)
→ Use `RasBreach` for dam breach parameters

**Want to extract results?**
→ Use `HdfResults*` classes for HEC-RAS 6.x HDF results
→ Use `RasControl.get_steady_results()` for legacy versions

**Want to parse geometry?**
→ Use `HdfMesh`, `HdfXsec`, `HdfStruc` for preprocessed geometry HDF
→ Use `RasGeometry`, `RasStruct` for plain text geometry file parsing

**Want to work with boundaries?**
→ Use `HdfBndry` to extract boundary metadata
→ Use `RasDss` to read DSS boundary time series
→ Use `ras_commander.usgs` to generate USGS-based boundaries

**Want to validate models?**
→ Use `ras_commander.check` (RasCheck framework)

**Want to repair geometry?**
→ Use `ras_commander.fixit` (RasFixit framework)

## Cross-References

For detailed patterns and guidance:

**Python Patterns** (`.claude/rules/python/`):
- `static-classes.md` - Static method pattern used throughout library
- `decorators.md` - @log_call, @standardize_input usage
- `path-handling.md` - pathlib.Path patterns
- `error-handling.md` - Exception handling standards
- `naming-conventions.md` - Function and variable naming
- `import-patterns.md` - Import organization

**HEC-RAS Specific** (`.claude/rules/hec-ras/`):
- `execution.md` - Four execution modes (single, parallel, sequential, remote)
- `remote.md` - Remote execution configuration and worker types

**Testing** (`.claude/rules/testing/`):
- `tdd-approach.md` - Test Driven Development with example projects

**Documentation** (`.claude/rules/documentation/`):
- `mkdocs-config.md` - ReadTheDocs configuration
- `notebook-standards.md` - Example notebook standards

## Performance Guidance

### CPU Core Usage
- `num_cores` parameter: Choose modest values (2-8) unless models benefit from higher parallelism
- For parallel execution: `max_workers * num_cores` should be conservative relative to physical cores and RAM

### Execution Modes
- **Single plan**: `compute_plan()` - Full parameter control, best for development
- **Parallel**: `compute_parallel()` - Maximum throughput for production
- **Sequential**: `compute_test_mode()` - Debugging and testing
- **Remote**: `compute_parallel_remote()` - Distributed across machines

See `.claude/rules/hec-ras/execution.md` for mode details.

### Immutability
Use `dest_folder` parameter to keep originals immutable:
```python
RasCmdr.compute_plan("01", dest_folder="working/run01", overwrite_dest=True)
```

## Testing with Example Projects

**DO use** official HEC-RAS example projects:
```python
from ras_commander import RasExamples

# Extract example project
path = RasExamples.extract_project("Muncie")
init_ras_project(path)
```

**DON'T use** synthetic data or mock objects - test with real HEC-RAS projects.

See `examples/AGENTS.md` for notebook index and `.claude/rules/testing/tdd-approach.md` for testing philosophy.

## Agent Development with Git Worktrees

When agents work on feature development or significant changes, use git worktrees for isolation.

### Commands

- `/agents-start-gitworktree` - Create isolated worktree for agent work
- `/agents-close-gitworktree` - Close out worktree when work is complete

### Tracking Registry

**File**: `agent_tasks/git_worktree_status.md`

This file tracks all agent worktrees with:
- Branch names and paths
- Purpose descriptions (enables recovery after context reset)
- Creation/closeout timestamps
- Status (active/merged/abandoned)

### Recovery After Context Reset

If an agent loses context and needs to find their worktree:
1. Read `agent_tasks/git_worktree_status.md`
2. Match purpose description to current task
3. Verify with `git worktree list`
4. Navigate to worktree and continue work

### Workflow Reference

See `agent_tasks/WORKTREE_WORKFLOW.md` for complete worktree + sideload workflow patterns.

## See Also

- **Root CLAUDE.md** - Strategic overview and LLM Forward philosophy
- **Subpackage AGENTS.md/CLAUDE.md** - Specialized guidance for each subpackage
- **.claude/rules/** - Detailed coding patterns and standards
- **examples/** - Example notebooks demonstrating complete workflows
- **agent_tasks/git_worktree_status.md** - Git worktree tracking for agents
