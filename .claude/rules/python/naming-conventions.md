# Naming Conventions

**Context**: Consistent naming across ras-commander codebase
**Priority**: High - affects code readability and consistency
**Auto-loads**: Yes (applies to all Python code)

## Overview

ras-commander follows Python PEP 8 naming conventions with specific domain abbreviations for HEC-RAS terminology. Consistency in naming makes the code more readable and maintainable.

## Core Rules

### Functions and Variables: snake_case

**✅ Correct**:
```python
def compute_plan(plan_number):
    dest_folder = Path("/output")
    num_cores = 4
    return execute_simulation()
```

**❌ Incorrect**:
```python
def ComputePlan(planNumber):  # Wrong - use snake_case
    destFolder = Path("/output")  # Wrong - use snake_case
    NumCores = 4  # Wrong - use snake_case
```

### Classes: PascalCase

**✅ Correct**:
```python
class RasCmdr:
    pass

class HdfResultsPlan:
    pass

class GaugeMatcher:
    pass
```

**❌ Incorrect**:
```python
class ras_cmdr:  # Wrong - use PascalCase
    pass

class hdf_results_plan:  # Wrong - use PascalCase
    pass
```

### Constants: UPPER_CASE

**✅ Correct**:
```python
MAX_PLAN_NUMBER = 99
DEFAULT_NUM_CORES = 4
HEC_RAS_VERSIONS = ["6.3", "6.5", "6.6"]
```

**❌ Incorrect**:
```python
max_plan_number = 99  # Wrong - use UPPER_CASE for constants
MaxPlanNumber = 99    # Wrong - use UPPER_CASE for constants
```

## Approved Abbreviations

### HEC-RAS Domain Abbreviations

These abbreviations are **standard and required** in ras-commander:

| Abbreviation | Full Term | Usage |
|--------------|-----------|--------|
| **ras** | River Analysis System | `RasCmdr`, `ras_object`, `init_ras_project()` |
| **prj** | Project | `RasPrj`, `prj_file`, `project` OK too |
| **geom** | Geometry | `geom_file`, `geom_df`, `RasGeometry` |
| **geompre** | Geometry Preprocessor | `clear_geompre`, `geompre_folder` |
| **num** | Number | `plan_num`, `num_cores` |
| **init** | Initialize | `init_ras_project()`, `initialize` OK too |
| **BC** | Boundary Condition | `bc_data`, `generate_bc()` |
| **IC** | Initial Condition | `ic_line`, `create_ic()` |
| **TW** | Tailwater | `tw_elevation` |
| **hdf** | Hierarchical Data Format | `Hdf Base`, `hdf_file` |
| **dss** | Data Storage System | `RasDss`, `dss_file` |
| **usgs** | U.S. Geological Survey | `RasUsgs`, `usgs_data` |

**Rationale**: These are standard abbreviations in the HEC-RAS domain that users expect to see.

### When to Spell Out vs Abbreviate

**Abbreviate in compound names**:
```python
# Good - abbreviations in compounds
geom_file = "/path/to/geometry.g01"
bc_generation = generate_boundary_conditions()
num_cores = 4
```

**Spell out when standalone or public API**:
```python
# Good - spell out for clarity
def initialize_project(path):  # Not init_project (public API)
    pass

boundary_conditions = load_bc()  # Variable can spell out
```

## Variable Naming Patterns

### Descriptive, Not Abbreviated

**✅ Good**:
```python
cross_section_data = get_cross_sections()
water_surface_elevation = hdf.get_wse()
simulation_results = execute_plan()
```

**❌ Bad**:
```python
xs_data = get_cross_sections()  # Too abbreviated
wse = hdf.get_wse()  # Context-dependent
res = execute_plan()  # Too generic
```

### Context-Specific Naming

**Different contexts, different names**:
```python
# File paths
geom_file = Path("geometry.g01")
plan_file = Path("plan.p01")

# Dataframes
geom_df = ras.geom_df
plan_df = ras.plan_df

# Objects
geom_object = RasGeometry(geom_file)
```

### Boolean Variables

**Use is_, has_, can_, should_ prefixes**:
```python
is_steady_plan = hdf.is_steady_plan()
has_results = check_for_results()
can_execute = validate_prerequisites()
should_overwrite = dest_folder.exists()
```

## Function Naming

### Verb-Noun Pattern

**✅ Good**:
```python
def compute_plan(plan_number):
    pass

def extract_results(hdf_file):
    pass

def validate_geometry(geom_file):
    pass

def generate_boundary_conditions():
    pass
```

**❌ Bad**:
```python
def plan(plan_number):  # Missing verb
    pass

def results(hdf_file):  # Missing verb
    pass
```

### Get vs Extract vs Read

**Different verbs mean different things**:

- **get_**: Retrieve existing data (fast, no computation)
  ```python
  def get_plan_name(plan_number):  # Lookup, no parsing
      return ras.plan_df.loc[plan_number, 'name']
  ```

- **extract_**: Parse and extract data (computation required)
  ```python
  def extract_cross_sections(geom_file):  # Parse file, extract data
      # Parsing logic...
      return cross_sections
  ```

- **read_**: Read raw file content
  ```python
  def read_geometry_file(geom_file):  # Read text
      return geom_file.read_text()
  ```

### Compute vs Calculate

- **compute_**: Heavy operation (run HEC-RAS, long-running)
  ```python
  def compute_plan(plan_number):  # Runs HEC-RAS (minutes)
      ...
  ```

- **calculate_**: Mathematical operation (fast)
  ```python
  def calculate_area(width, height):  # Simple math (microseconds)
      return width * height
  ```

## Class Naming

### Domain Classes

**Prefix with domain**:
```python
class RasCmdr:  # HEC-RAS commands
class RasGeometry:  # HEC-RAS geometry
class HdfBase:  # HDF operations
class RasUsgsCore:  # USGS data retrieval
```

### Worker Classes

**Suffix with Worker**:
```python
class PsexecWorker:  # Remote execution worker
class LocalWorker:  # Local execution worker
class DockerWorker:  # Docker execution worker
```

### Result/Data Classes

**Descriptive of content**:
```python
class FixResults:  # Geometry fix results
class FixMessage:  # Individual fix message
class FixAction:  # Fix action taken
```

## Module and Package Naming

### Lowercase with Underscores

**✅ Good**:
```python
ras_commander/
├── core.py
├── hdf_base.py
├── geometry.py
├── usgs/
│   ├── core.py
│   ├── real_time.py
│   └── validation.py
```

**❌ Bad**:
```python
ras_commander/
├── Core.py  # Wrong - use lowercase
├── HdfBase.py  # Wrong - use lowercase
├── USGS/  # Wrong - use lowercase
```

## Private vs Public

### Single Underscore: Internal Use

```python
def _internal_helper(data):
    """Internal function, not part of public API"""
    pass

class RasCmdr:
    def _validate_params(self, plan_number):
        """Internal validation, not documented"""
        pass
```

### Double Underscore: Name Mangling (Rare)

```python
class MyClass:
    def __private_method(self):
        """Strongly private (name mangled)"""
        pass
```

**Note**: Rare in ras-commander, prefer single underscore

## Common Pitfalls

### ❌ Inconsistent Abbreviations

**Bad**:
```python
geom_file = get_geometry()  # Mixed - pick one!
geometry_df = load_geom()
```

**Good**:
```python
geom_file = get_geometry_file()  # Consistent
geom_df = get_geometry_dataframe()
```

### ❌ Too Generic Names

**Bad**:
```python
def process(data):  # What does this process?
    pass

result = compute()  # Compute what?
```

**Good**:
```python
def process_geometry_file(geom_file):
    pass

simulation_result = compute_plan(plan_number)
```

### ❌ Mixing Naming Styles

**Bad**:
```python
# Mixed styles in one module
def ComputePlan(plan_number):  # PascalCase function (wrong)
    destFolder = ...  # camelCase variable (wrong)
    NUM_CORES = 4  # Constant treated as variable (wrong context)
```

**Good**:
```python
def compute_plan(plan_number):  # snake_case function
    dest_folder = ...  # snake_case variable
    num_cores = 4  # snake_case variable (not constant here)
```

## Naming Test

**Quick check for good names**:

1. ✅ Can someone unfamiliar with code understand the name?
2. ✅ Does it follow the correct case convention (snake_case, PascalCase, UPPER_CASE)?
3. ✅ Is it specific enough (not too generic)?
4. ✅ Does it use approved abbreviations correctly?
5. ✅ Is it consistent with similar names in the codebase?

**Example**:
```python
# Test this name: compute_plan()
1. ✅ Clear - computes a HEC-RAS plan
2. ✅ snake_case for function
3. ✅ Specific - not just "compute()"
4. ✅ Uses approved "plan" abbreviation (could be plan_number)
5. ✅ Consistent with compute_parallel(), compute_test_mode()

# Result: GOOD NAME
```

## See Also

- **Function Naming Technological Lineage**: `CLAUDE.md` (root) - Legacy vs modern naming rationale
- **Static Classes**: `.claude/rules/python/static-classes.md` - Class organization patterns
- **Documentation Standards**: `.claude/rules/documentation/` - Docstring conventions

---

**Key Takeaway**: Use snake_case for functions/variables, PascalCase for classes, UPPER_CASE for constants. Use approved HEC-RAS abbreviations (ras, geom, num, BC, IC, etc.) consistently.
