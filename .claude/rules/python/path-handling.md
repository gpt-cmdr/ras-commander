# Path Handling

**Context**: Consistent path handling with pathlib.Path
**Priority**: High - affects all file operations
**Auto-loads**: Yes (applies to all Python code)

## Overview

ras-commander uses `pathlib.Path` consistently for all path operations. This provides cross-platform compatibility, cleaner code, and better type safety than string-based paths.

## Core Principle

**Always use `pathlib.Path` objects internally**, but **accept both string paths and Path objects** in function parameters.

```python
from pathlib import Path

def my_function(file_path):
    # Convert to Path if string
    file_path = Path(file_path)

    # Now use Path methods
    if file_path.exists():
        content = file_path.read_text()
```

## Why pathlib.Path?

**Advantages over string paths**:
1. **Cross-platform**: Handles Windows (`\`) and Unix (`/`) separators automatically
2. **Object-oriented**: Rich methods (`.exists()`, `.read_text()`, `.glob()`, etc.)
3. **Type safety**: Clear distinction between paths and strings
4. **Composability**: Join paths with `/` operator
5. **Immutability**: Paths are immutable, preventing accidental modification

## Standard Pattern

### Function Parameters - Accept Both Types

**✅ Correct**:
```python
from pathlib import Path

def read_geometry_file(geom_file):
    """
    Read geometry file.

    Args:
        geom_file: Path to geometry file (str or Path)
    """
    # Convert to Path (idempotent if already Path)
    geom_file = Path(geom_file)

    # Use Path methods
    if not geom_file.exists():
        raise FileNotFoundError(f"Geometry file not found: {geom_file}")

    return geom_file.read_text()
```

**Why**: Users can pass either `"/path/to/file"` or `Path("/path/to/file")`

### Internal Use - Always Path Objects

**✅ Correct**:
```python
from pathlib import Path

def process_project(project_folder):
    project_folder = Path(project_folder)

    # All internal paths use Path objects
    prj_file = project_folder / "project.prj"
    geom_file = project_folder / "geometry.g01"
    plan_file = project_folder / "plan.p01"

    # Path operations
    if prj_file.exists():
        content = prj_file.read_text()
```

**Benefits**: Consistent API, cross-platform, readable

## Windows Path Handling

### Forward Slashes Work on Windows

**✅ Correct (works on all platforms)**:
```python
Path("/path/to/file")  # Works on Windows too!
Path("C:/Users/name/Documents/project.prj")  # Preferred on Windows
```

**❌ Avoid (but still works)**:
```python
Path("C:\\Users\\name\\Documents\\project.prj")  # Excessive escaping
```

### Raw Strings for Windows Paths

**✅ Correct**:
```python
# Raw string (r prefix) avoids escape issues
Path(r"C:\Users\name\Documents\project.prj")
```

### pathlib Handles Separators

```python
from pathlib import Path

# These are equivalent on Windows
p1 = Path("C:/Users/name/file.txt")
p2 = Path(r"C:\Users\name\file.txt")

assert p1 == p2  # True - pathlib normalizes
```

## Path Composition

### Use `/` Operator to Join Paths

**✅ Correct**:
```python
from pathlib import Path

base = Path("/project/folder")
geom_file = base / "geometry.g01"
plan_file = base / "plans" / "plan.p01"
```

**❌ Avoid**:
```python
# String concatenation - BAD
geom_file = str(base) + "/" + "geometry.g01"  # Platform-dependent

# os.path.join - UNNECESSARY
import os
geom_file = Path(os.path.join(base, "geometry.g01"))  # Verbose
```

### Building Complex Paths

```python
from pathlib import Path

# Start with base
project = Path("/projects/muncie")

# Build up with /
geometry_folder = project / "geometry"
geom_v1 = geometry_folder / "v1" / "geometry.g01"
geom_v2 = geometry_folder / "v2" / "geometry.g02"

# Alternative: Chain in one expression
plan_file = project / "plans" / "run_001" / "plan.p01"
```

## Common Path Operations

### Check Existence

```python
from pathlib import Path

file_path = Path("/path/to/file.txt")

if file_path.exists():
    print("File exists")

if file_path.is_file():
    print("Is a file")

if file_path.is_dir():
    print("Is a directory")
```

### Read/Write Files

```python
from pathlib import Path

# Read text
content = Path("file.txt").read_text()

# Read bytes
data = Path("file.bin").read_bytes()

# Write text
Path("output.txt").write_text("Content")

# Write bytes
Path("output.bin").write_bytes(b"\x00\x01")
```

### Get File Info

```python
from pathlib import Path

p = Path("/project/geometry.g01")

# Parts
print(p.name)        # geometry.g01
print(p.stem)        # geometry
print(p.suffix)      # .g01
print(p.parent)      # /project
print(p.parts)       # ('/', 'project', 'geometry.g01')

# Absolute path
print(p.absolute())  # Full absolute path
print(p.resolve())   # Resolves symlinks too
```

### Glob Patterns

```python
from pathlib import Path

project = Path("/project/folder")

# All .g## geometry files
geom_files = project.glob("*.g??")

# Recursive search
all_hdf = project.glob("**/*.hdf")

# Specific pattern
plans = project.glob("plan.p[0-9][0-9]")
```

## @standardize_input Decorator

For automatic Path conversion, use the `@standardize_input` decorator:

```python
from ras_commander.utils import standardize_input
from pathlib import Path

@standardize_input
def process_file(file_path, output_folder):
    # file_path and output_folder automatically converted to Path
    assert isinstance(file_path, Path)
    assert isinstance(output_folder, Path)

    # Use Path methods directly
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
```

**See**: `.claude/rules/python/decorators.md` for decorator details

## HEC-RAS Project Paths

### Standard Project Structure

```python
from pathlib import Path

def get_project_files(project_folder):
    project_folder = Path(project_folder)

    # Find .prj file
    prj_files = list(project_folder.glob("*.prj"))
    if not prj_files:
        raise ValueError(f"No .prj file in {project_folder}")

    prj_file = prj_files[0]

    # Derive other paths
    base_name = prj_file.stem  # e.g., "Muncie"

    return {
        'prj': prj_file,
        'geometry': project_folder / f"{base_name}.g01",
        'plan': project_folder / f"{base_name}.p01",
        'flow': project_folder / f"{base_name}.f01",
    }
```

## Common Pitfalls

### ❌ Mixing Strings and Paths

**Problem**:
```python
from pathlib import Path

base = Path("/project")
file_path = str(base) + "/file.txt"  # Now it's a string!

# This fails - file_path is string, not Path
if file_path.exists():  # AttributeError
    pass
```

**Solution**:
```python
base = Path("/project")
file_path = base / "file.txt"  # Still a Path

# This works
if file_path.exists():
    pass
```

### ❌ Forgetting to Convert Input Parameters

**Problem**:
```python
def my_function(file_path):
    # file_path might be string!
    if file_path.exists():  # AttributeError if string
        pass
```

**Solution**:
```python
from pathlib import Path

def my_function(file_path):
    file_path = Path(file_path)  # Always convert
    if file_path.exists():
        pass
```

### ❌ Hard-Coding Platform-Specific Separators

**Problem**:
```python
# Windows-only code
path = "C:\\Users\\name\\file.txt"  # Fails on Linux/Mac
```

**Solution**:
```python
# Platform-independent
path = Path("C:/Users/name/file.txt")  # Works everywhere
# Or better, use Path.home()
path = Path.home() / "file.txt"
```

## Best Practices

### ✅ Use Path.home() for User Directories

```python
from pathlib import Path

# Cross-platform user home
config_file = Path.home() / ".ras_commander" / "config.json"
```

### ✅ Use Path.cwd() for Current Directory

```python
from pathlib import Path

# Current working directory
current = Path.cwd()
project = current / "projects" / "my_project"
```

### ✅ Use Absolute Paths When Possible

```python
from pathlib import Path

# Convert relative to absolute
rel_path = Path("geometry.g01")
abs_path = rel_path.absolute()

# Or resolve (follows symlinks)
resolved = rel_path.resolve()
```

### ✅ Handle Missing Files Gracefully

```python
from pathlib import Path

def safe_read(file_path):
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.is_file():
        raise ValueError(f"Not a file: {file_path}")

    return file_path.read_text()
```

## See Also

- **Decorators**: `.claude/rules/python/decorators.md` - @standardize_input decorator
- **Error Handling**: `.claude/rules/python/error-handling.md` - FileNotFoundError patterns
- **Testing**: `.claude/rules/testing/tdd-approach.md` - Path handling in tests

---

**Key Takeaway**: Always use `pathlib.Path` for internal operations, but accept both strings and Path objects in function parameters. Use `/` operator to join paths.