# PRJ File Parsing Reference

Reference for HEC-RAS project file (.prj) structure and parsing.

## Overview

The PRJ file serves as the **master index** for a HEC-RAS project. It's an ASCII text file that references all plan, geometry, flow, and unsteady files in the project. The format uses simple `key=value` pairs with entry numbering.

## File Location

```
{project_folder}/{project_name}.prj
```

Example: `C:\Projects\Muncie\Muncie.prj`

## File Structure

### Header Section

```
Proj Title=My HEC-RAS Project
Current Plan=p01
Default Exp/Contr=0.3,0.1
SI Units=0
English Units=1
```

| Key | Description |
|-----|-------------|
| `Proj Title=` | Project display name |
| `Current Plan=` | Active plan reference (e.g., `p01`) |
| `Default Exp/Contr=` | Default expansion/contraction coefficients |
| `SI Units=` | SI units flag (0 or 1) |
| `English Units=` | English units flag (0 or 1) |

### Main Window Section

```
Begin Main Window
   X=200
   Y=100
   Width=1200
   Height=800
End Main Window
```

Stores the HEC-RAS GUI window position and size. Generally not relevant for automation.

### Entry Sections

Each file type has numbered entries:

```
Geom File=g01
Geom Title=Base Geometry
Flow File=f01
Flow Title=100-Year Flow
Unsteady File=u01
Unsteady Title=Hurricane Event
Plan File=p01
Plan Title=Base Plan - 100 Year
```

## Entry Pattern

All entries follow the same pattern:

```
{Type} File={prefix}{number}
{Type} Title={title}
```

| Entry Type | Prefix | Extension | Example |
|------------|--------|-----------|---------|
| Plan | `p` | `.p##` | `Plan File=p01` |
| Geometry | `g` | `.g##` | `Geom File=g01` |
| Steady Flow | `f` | `.f##` | `Flow File=f01` |
| Unsteady Flow | `u` | `.u##` | `Unsteady File=u01` |

### Entry Numbering

- Two-digit format: `01` through `99`
- Numbers are stored without the prefix in the PRJ file
- Full filename is constructed as: `{project_name}.{prefix}{number}`

## Complete Example

```
Proj Title=Muncie Example
Current Plan=p01
Default Exp/Contr=0.3,0.1
SI Units=0
English Units=1
Begin Main Window
   X=100
   Y=100
   Width=1024
   Height=768
End Main Window
Geom File=g01
Geom Title=2D Mesh with Terrain
Geom File=g02
Geom Title=Refined Mesh
Flow File=f01
Flow Title=Steady 100-Year
Unsteady File=u01
Unsteady Title=Unsteady 100-Year Hydrograph
Unsteady File=u02
Unsteady Title=Hurricane Event with Rain-on-Grid
Plan File=p01
Plan Title=Steady Flow Analysis
Plan File=p02
Plan Title=Unsteady - 100 Year
Plan File=p03
Plan Title=Hurricane Event
```

## Parsing Implementation

### RasPrj Methods

The `RasPrj` class provides methods to parse PRJ files:

| Method | Description |
|--------|-------------|
| `_get_prj_entries(entry_type)` | Parse entries of a specific type |
| `get_plan_entries()` | Get all plan entries as DataFrame |
| `get_geom_entries()` | Get all geometry entries as DataFrame |
| `get_flow_entries()` | Get all steady flow entries as DataFrame |
| `get_unsteady_entries()` | Get all unsteady flow entries as DataFrame |

### Parsing Algorithm

```python
def _get_prj_entries(self, entry_type):
    """Parse entries from PRJ file."""
    entries = []
    with open(self.prj_file, 'r') as f:
        content = f.read()

    # Pattern: "{Type} File={value}"
    file_pattern = f"{entry_type} File=(.+)"
    title_pattern = f"{entry_type} Title=(.+)"

    file_matches = re.findall(file_pattern, content)
    title_matches = re.findall(title_pattern, content)

    for i, file_ref in enumerate(file_matches):
        entry = {
            f'{entry_type.lower()}_number': file_ref.strip(),
            f'{entry_type.lower()}_title': title_matches[i] if i < len(title_matches) else ''
        }
        entries.append(entry)

    return pd.DataFrame(entries)
```

### DataFrame Output Structure

After parsing, entries are available as DataFrames:

**plan_df columns:**
- `plan_number` - Plan identifier (e.g., "01")
- `plan_title` - Plan display name
- `full_path` - Full path to plan file
- `geom_number` - Associated geometry number
- `unsteady_number` - Associated unsteady file (if applicable)
- `flow_type` - "Steady" or "Unsteady"

**geom_df columns:**
- `geom_number` - Geometry identifier
- `geom_title` - Geometry display name
- `full_path` - Full path to geometry file

**flow_df columns:**
- `flow_number` - Steady flow identifier
- `flow_title` - Flow display name
- `full_path` - Full path to flow file

**unsteady_df columns:**
- `unsteady_number` - Unsteady flow identifier
- `unsteady_title` - Unsteady display name
- `full_path` - Full path to unsteady file

## Usage Examples

### Initialize Project and Access DataFrames

```python
from ras_commander import init_ras_project, ras

# Initialize project
init_ras_project(r"C:\Projects\Muncie", "6.5")

# Access parsed entries
print(ras.plan_df)
print(ras.geom_df)
print(ras.flow_df)
print(ras.unsteady_df)
```

### Get Specific Entry Information

```python
# Get plan 01 information
plan_01 = ras.plan_df[ras.plan_df['plan_number'] == '01']
print(f"Plan Title: {plan_01['plan_title'].iloc[0]}")
print(f"Geometry: {plan_01['geom_number'].iloc[0]}")
```

### List All Available Plans

```python
for _, plan in ras.plan_df.iterrows():
    print(f"Plan {plan['plan_number']}: {plan['plan_title']}")
    print(f"  Type: {plan['flow_type']}")
    print(f"  Geometry: g{plan['geom_number']}")
```

## Encoding Handling

HEC-RAS project files may use different character encodings. The parser attempts multiple encodings:

1. UTF-8 (preferred)
2. Latin-1
3. CP1252 (Windows)
4. ISO-8859-1

```python
def read_file_with_fallback_encoding(file_path):
    """Read file trying multiple encodings."""
    encodings = ['utf-8', 'latin1', 'cp1252', 'iso-8859-1']
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read(), encoding
        except UnicodeDecodeError:
            continue
    return None, None
```

## Relationship to Other Files

The PRJ file is the **entry point** for loading a HEC-RAS project:

```
.prj (Project Index)
  ├── .p## (Plan Files)
  │     ├── References → .g## (Geometry)
  │     └── References → .u## or .f## (Flow)
  ├── .g## (Geometry Files)
  │     └── .g##.hdf (Preprocessed Geometry)
  ├── .f## (Steady Flow Files)
  └── .u## (Unsteady Flow Files)
        └── .u##.hdf (Unsteady HDF if using gridded data)
```

## Edge Cases

### Missing Titles

Titles are optional. If a file entry exists without a corresponding title:

```
Geom File=g01
Geom File=g02
Geom Title=Second Geometry
```

The parser handles this by using empty string for missing titles.

### Duplicate Entries

HEC-RAS may create duplicate entries in some cases. The parser returns all entries in order.

### File References vs Actual Files

The PRJ file lists references, but files may not exist:
- File was deleted
- Project was copied without all files
- PRJ was manually edited

Always verify file existence before operations:

```python
from pathlib import Path

for _, geom in ras.geom_df.iterrows():
    geom_path = Path(geom['full_path'])
    if not geom_path.exists():
        print(f"Warning: Geometry {geom['geom_number']} file missing")
```

## See Also

- [HEC-RAS File Formats](file-formats.md) - Overview of all file types
- [Project Initialization](../getting-started/project-initialization.md) - Using `init_ras_project()`
- [Plan Execution](../user-guide/plan-execution.md) - Running plans
