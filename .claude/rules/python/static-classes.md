# Static Class Pattern

**Context**: Core architectural pattern for ras-commander classes
**Priority**: Critical - affects all class usage
**Auto-loads**: Yes (applies to all Python code in repository)

## Overview

The static class pattern is the foundational architectural pattern in ras-commander. Most classes use static methods with `@log_call` decorators, eliminating the need for instantiation and providing a cleaner, more functional API.

This pattern was chosen for:
- **Simplicity**: No need to manage class instances
- **Clarity**: Direct function calls without instantiation confusion
- **Consistency**: Uniform API across all modules
- **Logging**: Automatic call logging via decorators

## Core Pattern

### No Instantiation Required

**✅ Correct Usage**:
```python
from ras_commander import RasCmdr

# Call static methods directly
RasCmdr.compute_plan("01")
RasCmdr.compute_parallel(["01", "02", "03"])
```

**❌ Incorrect Usage**:
```python
from ras_commander import RasCmdr

# DON'T instantiate static classes!
cmdr = RasCmdr()  # This will fail or cause confusion
cmdr.compute_plan("01")
```

### Classes Following This Pattern

**Core Execution**:
- `RasCmdr` - HEC-RAS plan execution
- `RasCurrency` - Execution currency checking (NEW in v0.88.0)
- `RasControl` - Legacy COM interface (HEC-RAS 3.x-4.x)

**File Operations**:
- `RasPlan` - Plan file operations
- `RasGeo` - Geometry file operations (2D Manning's n)
- `RasGeometry` - Geometry parsing (1D cross sections, storage)
- `RasGeometryUtils` - Geometry parsing utilities
- `RasStruct` - Inline structure parsing (bridges, culverts)
- `RasBreach` - Breach parameter modification
- `RasUnsteady` - Unsteady flow file management
- `RasUtils` - Utility functions
- `RasMap` - RASMapper configuration parsing
- `RasExamples` - Example project management
- `RasDss` - HEC-DSS file operations
- `RasFixit` - Geometry repair automation

**HDF Data Processing**:
- `HdfBase` - Core HDF operations
- `HdfPlan` - Plan-level HDF operations
- `HdfMesh` - Mesh data extraction
- `HdfResults*` - Results processing (all variants)
- `HdfStruc` - Structure data extraction
- `HdfResultsBreach` - Breach results extraction
- `HdfHydraulicTables` - Cross section property tables
- `HdfPipe`, `HdfPump` - Infrastructure analysis
- `HdfPlot`, `HdfResultsPlot` - Visualization

**USGS Integration**:
- `RasUsgsCore` - Core data retrieval
- `UsgsGaugeSpatial` - Spatial queries
- `GaugeMatcher` - Gauge-to-model matching
- `RasUsgsTimeSeries` - Time series processing
- `InitialConditions` - IC generation
- `RasUsgsBoundaryGeneration` - BC generation
- `RasUsgsFileIo` - File I/O operations
- `RasUsgsRealTime` - Real-time monitoring

### Exceptions - Classes That ARE Instantiated

**Project Objects**:
- `RasPrj` - Project management (instantiate for multiple projects)
- `ras` - Global project object (created by `init_ras_project()`)

**Worker Classes** (remote execution):
- `PsexecWorker` - Remote Windows execution
- `LocalWorker` - Local parallel execution
- `DockerWorker` - Container execution
- Future workers: `SshWorker`, `WinrmWorker`, etc.

**Callback Classes** (execution monitoring):
- `ConsoleCallback` - Console output
- `FileLoggerCallback` - File logging
- `ProgressBarCallback` - Progress bars
- `SynchronizedCallback` - Thread-safe wrapper

**Result Classes** (data containers):
- `FixResults`, `FixMessage`, `FixAction` - Geometry repair results

## Multiple Projects Pattern

When working with multiple HEC-RAS projects simultaneously, pass the `ras_object` parameter:

```python
from ras_commander import RasPrj, init_ras_project, RasCmdr

# Project 1
project1 = RasPrj()
init_ras_project("/path/to/project1", "6.5", ras_object=project1)

# Project 2
project2 = RasPrj()
init_ras_project("/path/to/project2", "6.5", ras_object=project2)

# Execute plans on specific projects
RasCmdr.compute_plan("01", ras_object=project1)
RasCmdr.compute_plan("02", ras_object=project2)
```

**Default Behavior**: If `ras_object` is not specified, methods use the global `ras` object created by `init_ras_project()`.

## Common Pitfalls

### ❌ Instantiating Static Classes

**Problem**:
```python
cmdr = RasCmdr()  # Unnecessary and confusing
```

**Solution**:
```python
RasCmdr.compute_plan("01")  # Call directly
```

### ❌ Forgetting ras_object with Multiple Projects

**Problem**:
```python
# Working with project1
init_ras_project("/path/to/project1", "6.5", ras_object=project1)

# Working with project2
init_ras_project("/path/to/project2", "6.5", ras_object=project2)

# This uses the global ras object (last initialized)
RasCmdr.compute_plan("01")  # Which project???
```

**Solution**:
```python
# Explicit project specification
RasCmdr.compute_plan("01", ras_object=project1)
RasCmdr.compute_plan("02", ras_object=project2)
```

### ❌ Mixing Instantiation Patterns

**Problem**:
```python
# Some classes instantiated, others not - inconsistent
project = RasPrj()  # Instantiated (correct for RasPrj)
cmdr = RasCmdr()    # Instantiated (WRONG for RasCmdr)
```

**Solution**: Know which classes follow which pattern (see lists above)

## Implementation Details

### Why Static Methods?

1. **API Clarity**: Clear, functional interface
2. **No State Management**: No instance state to track
3. **Thread Safety**: No shared instance state
4. **Decorator Friendly**: `@log_call` works seamlessly
5. **Backward Compatible**: Easier to maintain stable API

### How It Works Internally

Static classes in ras-commander typically use:

```python
class RasCmdr:
    @staticmethod
    @log_call
    def compute_plan(plan_number, dest_folder=None, ras_object=None, ...):
        # Get ras object (use provided or global)
        _ras = ras_object if ras_object is not None else ras

        # Implementation using _ras
        ...
```

The `@staticmethod` decorator ensures methods can be called without instantiation.

The `@log_call` decorator automatically logs function calls (see `.claude/rules/python/decorators.md`).

## When to Create Instantiated Classes

**Create an instantiated class when**:
- The class represents a stateful object (projects, workers, callbacks)
- Multiple instances with different configurations needed
- Polymorphism required (worker abstraction)

**Use static class pattern when**:
- Stateless operations (parsing, computation, data extraction)
- Single responsibility, functional interface
- No need for multiple configurations
- Consistent with ras-commander conventions

## Testing Pattern

When testing static classes, call methods directly:

```python
from ras_commander import RasExamples, RasCmdr, init_ras_project

# Extract test project
project_path = RasExamples.extract_project("Muncie")

# Initialize
init_ras_project(project_path, "6.5")

# Execute plan
RasCmdr.compute_plan("01")

# No instantiation needed at any step
```

## See Also

- **Decorators**: `.claude/rules/python/decorators.md` - `@log_call`, `@staticmethod` usage
- **Error Handling**: `.claude/rules/python/error-handling.md` - LoggingConfig integration
- **Multiple Projects**: `ras_commander/CLAUDE.md` - RasPrj class documentation
- **Remote Workers**: `ras_commander/remote/CLAUDE.md` - Instantiated worker classes

---

**Key Takeaway**: Most ras-commander classes are static - call methods directly without instantiation. Only `RasPrj`, workers, callbacks, and result containers are instantiated.
