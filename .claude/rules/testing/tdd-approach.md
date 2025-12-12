# Test Driven Development with Real HEC-RAS Projects

**Context**: Testing strategy for ras-commander
**Priority**: Critical - affects all testing and validation
**Auto-loads**: Yes (all code)

## Core Philosophy

**ras-commander uses real HEC-RAS example projects instead of traditional unit tests with mocks.**

## Why Real Projects, Not Mocks?

### HEC-RAS is Complex

**Problem with Mocks**:
- HEC-RAS file formats are intricate and version-specific
- Fixed-width parsing with subtle edge cases
- Behavior varies by HEC-RAS version (3.x, 4.x, 5.x, 6.x)
- 2D mesh vs 1D cross sections have different structures
- Mocking all edge cases is impractical

**Real Projects Catch Real Issues**:
- Actual HEC-RAS file formats
- Real-world edge cases and variations
- Version-specific behavior differences
- Integration between components

### Examples Are Living Tests

**Dual Purpose**:
1. **Documentation**: Show users how to use ras-commander
2. **Functional Tests**: Validate library actually works

**Benefits**:
- Tests reflect actual use cases
- Documentation stays up-to-date (tested code)
- Examples serve as regression tests

## RasExamples Class

### Purpose

**Manage HEC-RAS example projects** that ship with ras-commander or are extracted for testing.

**Location**: `ras_commander/examples.py`

### Core Methods

**Extract Projects**:
```python
from ras_commander import RasExamples

# Extract single project
path = RasExamples.extract_project("Muncie")

# Extract to custom location
path = RasExamples.extract_project("Muncie", output_path="/my_tests")

# Extract multiple projects
paths = RasExamples.extract_project(["Muncie", "Balde Eagle Creek"])
```

**List Available Projects**:
```python
# All projects
all_projects = RasExamples.list_projects()

# By category
categories = RasExamples.list_categories()
unsteady_projects = RasExamples.list_projects("1D Unsteady Flow Hydraulics")
```

**Query Project Info**:
```python
# Get project metadata
info = RasExamples.get_project_info("Muncie")
print(info['category'])
print(info['description'])
```

## Example Projects Location

### Included with ras-commander

**Zip Archive**: `examples/Example_Projects_6_5.zip` (or similar)

**Projects Included**:
- Muncie (1D steady/unsteady)
- Balde Eagle Creek (2D unsteady)
- Dam Breaching (breach analysis)
- ... and others

**Size**: Typically 10-50 MB compressed

### Extraction Behavior

**Default**: Extracts to `example_projects/` in current directory

```python
# Extracts to ./example_projects/Muncie/
path = RasExamples.extract_project("Muncie")
```

**Custom Location**:
```python
# Extracts to /my_tests/Muncie/
path = RasExamples.extract_project("Muncie", output_path="/my_tests")
```

**Cleanup**: Example projects are temporary (gitignored)

## Testing Pattern

### Basic Test Structure

```python
from ras_commander import RasExamples, init_ras_project, RasCmdr
from pathlib import Path

def test_compute_plan_muncie():
    # 1. Extract example project
    project_path = RasExamples.extract_project("Muncie")

    # 2. Initialize
    init_ras_project(project_path, "6.5")

    # 3. Execute plan
    RasCmdr.compute_plan("01")

    # 4. Verify HDF created
    hdf_file = project_path / "Muncie.p01.hdf"
    assert hdf_file.exists(), "HDF file not created"

    # 5. Validate results
    from ras_commander.hdf import HdfResultsPlan
    hdf = HdfResultsPlan(hdf_file)
    wse = hdf.get_wse(time_index=-1)
    assert wse is not None, "No WSE results"
    assert len(wse) > 0, "Empty WSE results"
```

### Pytest Integration

**Test File**: `tests/test_ras_examples_initialization.py` (example)

```python
import pytest
from ras_commander import RasExamples, init_ras_project

@pytest.mark.parametrize("project_name", [
    "Muncie",
    "Balde Eagle Creek",
    "Dam Breaching",
])
def test_project_initialization(project_name):
    """Test that project initializes successfully"""
    path = RasExamples.extract_project(project_name)
    init_ras_project(path, "6.5")

    # Verify ras object populated
    from ras_commander import ras
    assert ras.prj_file is not None
    assert len(ras.plan_df) > 0
```

## Example Notebooks as Tests

### Notebook Testing

**All notebooks in `examples/` serve as functional tests**:
- `01_basic_usage.ipynb` - Tests basic API
- `02_parallel_execution.ipynb` - Tests parallel mode
- `03_hdf_extraction.ipynb` - Tests results extraction
- ... etc.

**Execution**:
```bash
# Run all notebooks (converts to Python and executes)
pytest --nbmake examples/*.ipynb
```

**Requirements**:
- Install `pytest-nbmake`: `pip install pytest-nbmake`
- Notebooks must be idempotent (safe to re-run)

### Notebook Best Practices

**✅ DO**:
- Extract example projects at start
- Clean up at end (or use temp folders)
- Include assertions/verifications
- Document expected behavior

**❌ DON'T**:
- Rely on external data (use RasExamples)
- Leave large files uncommitted
- Skip error handling
- Assume specific file paths

## Testing Different HEC-RAS Versions

### Version-Specific Projects

Some projects test version-specific features:

**HEC-RAS 6.x**:
- 2D unsteady flow
- HDF-based results
- Breach analysis

**HEC-RAS 5.x**:
- Legacy .txt results
- Mixed 1D/2D
- COM interface (RasControl)

**HEC-RAS 3.x-4.x**:
- Pure 1D steady/unsteady
- COM interface only

**Test Coverage**:
```python
@pytest.mark.parametrize("version,project", [
    ("6.5", "Muncie"),
    ("5.0.7", "Legacy Project"),
    ("4.1", "Old Project"),
])
def test_version_compatibility(version, project):
    path = RasExamples.extract_project(project)
    init_ras_project(path, version)
    # ... test version-specific features
```

## Validation Patterns

### Pattern: Geometry Validation

```python
def test_geometry_parsing():
    path = RasExamples.extract_project("Muncie")
    init_ras_project(path, "6.5")

    from ras_commander import RasGeometry

    # Get geometry file
    geom_file = ras.geom_df.iloc[0]['file_path']

    # Parse cross sections
    xs_data = RasGeometry.get_cross_sections(geom_file)

    # Validate structure
    assert 'river' in xs_data.columns
    assert 'reach' in xs_data.columns
    assert 'xs_id' in xs_data.columns
    assert len(xs_data) > 0
```

### Pattern: Results Validation

```python
def test_results_extraction():
    path = RasExamples.extract_project("Muncie")
    init_ras_project(path, "6.5")
    RasCmdr.compute_plan("01")

    from ras_commander.hdf import HdfResultsPlan

    hdf_file = ras.plan_df.iloc[0]['hdf_path']
    hdf = HdfResultsPlan(hdf_file)

    # Extract WSE
    wse = hdf.get_wse(time_index=-1)

    # Validate reasonable values
    assert wse.min() > -100, "WSE too low (likely error)"
    assert wse.max() < 10000, "WSE too high (likely error)"
    assert not wse.isna().all(), "All WSE values are NaN"
```

### Pattern: End-to-End Workflow

```python
def test_complete_workflow():
    # Extract project
    path = RasExamples.extract_project("Muncie")

    # Initialize
    init_ras_project(path, "6.5")

    # Modify geometry (optional)
    # ...

    # Execute
    RasCmdr.compute_plan("01", dest_folder="/output/test_run")

    # Extract results
    from ras_commander.hdf import HdfResultsPlan
    hdf = HdfResultsPlan("/output/test_run/Muncie.p01.hdf")

    # Process results
    wse_df = hdf.get_wse_dataframe()

    # Validate
    assert len(wse_df) > 0
    assert 'wse' in wse_df.columns
```

## Test Organization

### Directory Structure

```
tests/
├── test_ras_examples_initialization.py  # Basic initialization tests
├── test_execution.py                    # Execution tests
├── test_geometry_parsing.py             # Geometry parsing tests
├── test_hdf_extraction.py               # HDF results tests
├── example_projects/                    # Extracted projects (gitignored)
└── conftest.py                          # Pytest configuration
```

### Pytest Configuration

**`tests/conftest.py`**:
```python
import pytest
from ras_commander import RasExamples
from pathlib import Path

@pytest.fixture(scope="session")
def muncie_project():
    """Extract Muncie project once per test session"""
    path = RasExamples.extract_project("Muncie", output_path="tests/example_projects")
    return path

@pytest.fixture(scope="session")
def cleanup_projects():
    """Clean up extracted projects after tests"""
    yield
    # Cleanup logic here
    import shutil
    shutil.rmtree("tests/example_projects", ignore_errors=True)
```

## Running Tests

### Run All Tests

```bash
# Run all pytest tests
pytest tests/

# Run with verbose output
pytest -v tests/

# Run specific test file
pytest tests/test_execution.py
```

### Run Notebook Tests

```bash
# Test all notebooks
pytest --nbmake examples/*.ipynb

# Test specific notebook
pytest --nbmake examples/01_basic_usage.ipynb
```

### Run with Coverage

```bash
# Generate coverage report
pytest --cov=ras_commander --cov-report=html tests/

# View report
open htmlcov/index.html
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: windows-latest  # HEC-RAS is Windows-only

    steps:
    - uses: actions/checkout@v2

    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.10'

    - name: Install dependencies
      run: |
        pip install -e .
        pip install pytest pytest-cov

    - name: Run tests
      run: pytest tests/

    # Note: Actual HEC-RAS execution requires HEC-RAS installed
    # For full integration tests, use self-hosted runner with HEC-RAS
```

## Common Pitfalls

### ❌ Using Mocks for HEC-RAS Files

**Bad**:
```python
def test_parse_geometry():
    # Creating fake geometry file content
    fake_content = "River Reach=MyRiver,MyReach"
    # ... this will miss real-world edge cases
```

**Good**:
```python
def test_parse_geometry():
    path = RasExamples.extract_project("Muncie")
    init_ras_project(path, "6.5")
    geom_file = ras.geom_df.iloc[0]['file_path']
    # Parse real HEC-RAS geometry file
```

### ❌ Not Cleaning Up Extracted Projects

**Problem**: Fills disk with extracted projects

**Solution**: Use pytest fixtures with cleanup or gitignore

```python
@pytest.fixture
def temp_project(tmp_path):
    """Extract to pytest's temp directory (auto-cleanup)"""
    path = RasExamples.extract_project("Muncie", output_path=tmp_path)
    return path
```

## See Also

- **Example Projects**: `examples/README.md` - Notebook index
- **Error Handling**: `.claude/rules/python/error-handling.md` - Test assertions
- **Path Handling**: `.claude/rules/python/path-handling.md` - Temp folders

---

**Key Takeaway**: Test with real HEC-RAS example projects using `RasExamples.extract_project()`, not mocks. Example notebooks serve as both documentation and functional tests.
