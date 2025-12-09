# HDF Writing Guide

Safe practices for programmatically modifying HEC-RAS HDF files.

## When to Write to HDF

!!! warning "Proceed with Caution"
    Direct HDF modification is an advanced technique. HEC-RAS validates HDF structure strictly and will silently ignore or corrupt data that doesn't match its expectations.

Only write directly to HDF when:

1. **The data type is HDF-only** - No plain text equivalent exists
2. **You need to modify gridded/raster data** - Precipitation, land cover, terrain
3. **You're implementing automation that HEC-RAS doesn't support** - Custom calibration workflows

## HDF-Only Data Types

These data types exist **only in HDF** - there is no plain text representation:

| Data Category | HDF File Type | HDF Location |
|---------------|---------------|--------------|
| Gridded Precipitation | `.p##.hdf` | `/Event Conditions/Meteorology/` |
| Gridded Land Cover | `Land Cover.*.hdf` | `//Raster Map`, `//Variables` |
| Gridded Soils | `Soils.*.hdf` | `//Raster Map`, `//Variables` |
| Infiltration Overrides | `.g##.hdf` | `/Geometry/Infiltration/Base Overrides` |
| Pipe Networks | `.g##.hdf` | `/Geometry/Pipe Networks/` |
| Terrain Data | `Terrain.hdf` | `//Elevation` |
| Computed Results | `.p##.hdf` | `/Results/` |
| Computed Mesh | `.g##.hdf` | `/Geometry/2D Flow Areas/*/Cells` |

For these data types, direct HDF editing is the **only** option.

## The Golden Rule

!!! danger "Match HEC-RAS Exactly"
    HEC-RAS is extremely particular about HDF structure. Your modified files must be **byte-for-byte identical** in structure to what HEC-RAS would create natively.

This includes:
- Structured array field names
- Data types (f4 vs f8, string lengths)
- Compression type and level
- Chunk sizes
- Fill values
- Dataset attributes

## Safe Modification Workflow

### Step 1: Create Reference Files

Before writing any code, generate reference files by completing the workflow manually:

1. Start with a working HEC-RAS model
2. Make the desired change manually in RASMapper or the GUI
3. Save the project
4. Export/copy the HDF files before and after the change

### Step 2: Analyze Structure with HDFView

Use [HDFView](https://www.hdfgroup.org/downloads/hdfview/) to examine the exact structure:

1. Open the HDF file
2. Navigate to the dataset you want to modify
3. Right-click → "Show Properties" → "General Object Info"
4. Note these critical properties:
   - **Datatype**: Field names, types, sizes
   - **Dataspace**: Shape, dimensions
   - **Storage layout**: Chunking
   - **Filters**: Compression type and level

### Step 3: Understand the Structure

```python
import h5py

def inspect_dataset(hdf_path, dataset_path):
    """Print detailed dataset information."""
    with h5py.File(hdf_path, 'r') as hdf:
        if dataset_path not in hdf:
            print(f"Dataset not found: {dataset_path}")
            return

        ds = hdf[dataset_path]
        print(f"Dataset: {dataset_path}")
        print(f"  Shape: {ds.shape}")
        print(f"  Dtype: {ds.dtype}")
        print(f"  Chunks: {ds.chunks}")
        print(f"  Compression: {ds.compression}")
        print(f"  Compression opts: {ds.compression_opts}")

        # For structured arrays, show field details
        if ds.dtype.names:
            print(f"  Fields:")
            for name in ds.dtype.names:
                field_dtype = ds.dtype[name]
                print(f"    {name}: {field_dtype}")

        # Show attributes
        print(f"  Attributes:")
        for attr_name, attr_value in ds.attrs.items():
            print(f"    {attr_name}: {attr_value}")
```

### Step 4: Implement with Exact Matching

Use the delete-then-create pattern:

```python
import h5py
import numpy as np
from pathlib import Path

def safe_write_dataset(hdf_path, dataset_path, data, reference_hdf=None):
    """
    Safely write dataset matching HEC-RAS structure.

    Args:
        hdf_path: Path to HDF file to modify
        dataset_path: Path within HDF (e.g., '/Geometry/Infiltration/Base Overrides')
        data: Numpy structured array with exact dtype
        reference_hdf: Optional reference file to copy structure from
    """
    # Get structure from existing or reference file
    source_path = reference_hdf or hdf_path
    with h5py.File(source_path, 'r') as hdf:
        if dataset_path not in hdf:
            raise ValueError(f"Dataset {dataset_path} not found in {source_path}")

        ds = hdf[dataset_path]
        existing_dtype = ds.dtype
        existing_chunks = ds.chunks
        existing_compression = ds.compression
        existing_compression_opts = ds.compression_opts

    # Verify data matches expected dtype
    if data.dtype != existing_dtype:
        raise ValueError(f"Data dtype {data.dtype} doesn't match expected {existing_dtype}")

    # Write with exact matching options
    with h5py.File(hdf_path, 'a') as hdf:
        # Delete existing dataset
        if dataset_path in hdf:
            del hdf[dataset_path]

        # Create new dataset with exact same options
        hdf.create_dataset(
            dataset_path,
            data=data,
            dtype=existing_dtype,
            compression=existing_compression,
            compression_opts=existing_compression_opts,
            chunks=existing_chunks,
            maxshape=(None,) if existing_chunks else None
        )

    print(f"Successfully wrote {len(data)} records to {dataset_path}")
```

### Step 5: Validate Results

After modification, verify:

1. **HEC-RAS loads the file** without errors
2. **Data appears in the GUI** correctly
3. **Geometry preprocessor runs** without regenerating your data
4. **Simulation produces expected results**

## Example: Infiltration Base Overrides

This example demonstrates the complete workflow for modifying infiltration parameters:

### The Problem

Infiltration calibration regions store base overrides in the geometry HDF. Unlike most geometry data, these are **HDF-only** - no plain text equivalent exists.

HDF Location: `/Geometry/Infiltration/Base Overrides`

### Inspect Existing Structure

```python
from pathlib import Path
import h5py

geom_hdf = Path("MyProject.g01.hdf")

with h5py.File(geom_hdf, 'r') as hdf:
    table_path = '/Geometry/Infiltration/Base Overrides'
    if table_path in hdf:
        ds = hdf[table_path]
        print(f"Dtype: {ds.dtype}")
        print(f"Compression: {ds.compression}, opts: {ds.compression_opts}")
        print(f"Chunks: {ds.chunks}")
        print(f"Data:\n{ds[:]}")
```

Output:
```
Dtype: [('Land Cover Name', 'S7'), ('Maximum Deficit', '<f4'),
        ('Initial Deficit', '<f4'), ('Potential Percolation Rate', '<f4')]
Compression: gzip, opts: 1
Chunks: (100,)
Data:
[(b'Forest ', 1.5, 0.5, 0.1)
 (b'Urban  ', 0.5, 0.1, 0.05)
 ...]
```

### Create Structured Array

```python
import numpy as np
import pandas as pd

# Define dtype matching HEC-RAS exactly
dt = np.dtype([
    ('Land Cover Name', 'S7'),           # 7-byte string
    ('Maximum Deficit', '<f4'),           # float32, little-endian
    ('Initial Deficit', '<f4'),
    ('Potential Percolation Rate', '<f4')
])

# Create data (e.g., from calibration results)
calibration_data = [
    ('Forest', 1.8, 0.6, 0.12),    # Scaled values
    ('Urban', 0.6, 0.12, 0.06),
    ('Water', 0.0, 0.0, 0.0),
]

# Build structured array
data = np.zeros(len(calibration_data), dtype=dt)
for i, (name, max_def, init_def, perc_rate) in enumerate(calibration_data):
    data[i]['Land Cover Name'] = name.encode('utf-8').ljust(7)[:7]
    data[i]['Maximum Deficit'] = max_def
    data[i]['Initial Deficit'] = init_def
    data[i]['Potential Percolation Rate'] = perc_rate
```

### Write to HDF

```python
def write_infiltration_overrides(geom_hdf_path, infiltration_data):
    """Write infiltration base overrides to geometry HDF."""
    table_path = '/Geometry/Infiltration/Base Overrides'

    with h5py.File(geom_hdf_path, 'a') as hdf:
        # Delete existing
        if table_path in hdf:
            del hdf[table_path]

        # Create with HEC-RAS-compatible options
        hdf.create_dataset(
            table_path,
            data=infiltration_data,
            compression='gzip',
            compression_opts=1,
            chunks=(100,),
            maxshape=(None,)
        )

# Apply
write_infiltration_overrides(geom_hdf, data)
```

### Using HdfInfiltration Class

The ras-commander library provides a safer interface:

```python
from ras_commander import HdfInfiltration
import pandas as pd

# Read current values
current_df = HdfInfiltration.get_infiltration_baseoverrides(geom_hdf)
print(current_df)

# Scale values
scale_factors = {
    'Maximum Deficit': 1.2,
    'Initial Deficit': 1.2,
    'Potential Percolation Rate': 1.1
}

scaled_df = HdfInfiltration.scale_infiltration_data(
    geom_hdf,
    current_df,
    scale_factors
)
```

## Common HDF Structures

### Land Cover Variables

Location: `//Variables` in land cover HDF files

```python
dt = np.dtype([
    ('Name', f'S{max_name_length}'),
    ('Manning n', '<f4'),
    ('Percent Impervious', '<f4')
])
```

### Infiltration Layer Data

Location: `//Variables` in infiltration HDF files

```python
dt = np.dtype([
    ('Name', f'S{max_name_length}'),
    ('Curve Number', '<f4'),
    ('Abstraction Ratio', '<f4'),
    ('Minimum Infiltration Rate', '<f4')
])
```

### Raster Maps

Location: `//Raster Map` in land cover/soil HDF files

```python
dt = np.dtype([
    ('Raster Value', '<i4'),      # int32
    ('Name', f'S{max_name_length}')
])
```

## Troubleshooting

### HEC-RAS Ignores My Changes

**Symptoms**: Data appears correct in HDFView but HEC-RAS shows zeros or defaults.

**Common causes**:
1. Wrong field names (case-sensitive!)
2. Wrong numeric precision (f4 vs f8)
3. Wrong string byte length
4. Missing or wrong fill values
5. Incorrect chunk size

**Solution**: Compare your file byte-by-byte with a HEC-RAS-created reference:

```bash
h5diff -v reference.g01.hdf modified.g01.hdf "/Geometry/Infiltration/Base Overrides"
```

### Data Appears as NaN or Invalid

**Symptoms**: Values show as NaN, -9999, or obviously wrong numbers.

**Common causes**:
1. Byte order mismatch (big vs little endian)
2. Encoding issues with strings
3. Incompatible data types

**Solution**: Explicitly specify byte order and encoding:

```python
# Ensure little-endian (Windows native)
dt = np.dtype([
    ('Value', '<f4'),  # '<' means little-endian
])

# Ensure ASCII encoding for strings
name_bytes = name.encode('ascii').ljust(7)[:7]
```

### File Won't Open in HEC-RAS

**Symptoms**: HEC-RAS reports corruption or refuses to open file.

**Common causes**:
1. Incomplete write (crash during save)
2. Wrong HDF5 library version
3. Structural corruption

**Solution**: Always use context managers and verify writes:

```python
try:
    with h5py.File(hdf_path, 'a') as hdf:
        # ... modifications ...
        hdf.flush()  # Ensure data is written
except Exception as e:
    print(f"Write failed: {e}")
    # Restore from backup
```

## Best Practices

### 1. Always Create Backups

```python
import shutil
from datetime import datetime

def backup_hdf(hdf_path):
    """Create timestamped backup before modification."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = hdf_path.with_suffix(f'.{timestamp}.bak')
    shutil.copy2(hdf_path, backup_path)
    return backup_path
```

### 2. Use Read-Modify-Write Pattern

```python
def modify_dataset(hdf_path, dataset_path, modify_func):
    """Safe read-modify-write pattern."""
    backup = backup_hdf(hdf_path)

    try:
        # Read
        with h5py.File(hdf_path, 'r') as hdf:
            original_data = hdf[dataset_path][:]
            dtype = hdf[dataset_path].dtype

        # Modify
        modified_data = modify_func(original_data)

        # Write
        safe_write_dataset(hdf_path, dataset_path, modified_data)

    except Exception as e:
        # Restore backup on failure
        shutil.copy2(backup, hdf_path)
        raise RuntimeError(f"Modification failed, restored backup: {e}")
```

### 3. Validate Before and After

```python
def validate_hdf_structure(hdf_path, expected_datasets):
    """Validate HDF file has expected structure."""
    with h5py.File(hdf_path, 'r') as hdf:
        for ds_path, expected_dtype in expected_datasets.items():
            if ds_path not in hdf:
                return False, f"Missing dataset: {ds_path}"
            if hdf[ds_path].dtype != expected_dtype:
                return False, f"Wrong dtype at {ds_path}"
    return True, "OK"
```

### 4. Use LLM-Assisted Development

For complex HDF modifications:

1. **Generate reference files manually** using HEC-RAS GUI
2. **Use LLM agent** to analyze structure differences
3. **Human-in-the-loop validation** by H&H Engineer
4. **Iterate** until output matches reference exactly

## See Also

- [HDF Structure Reference](hdf-structure.md) - Complete HDF path reference
- [HdfInfiltration API](../api/hdf.md#hdfinfiltration) - Infiltration modification methods
- [Infiltration Override Deep Dive](https://github.com/gpt-cmdr/HEC-Commander/blob/main/Blog/8._Deep_Dive_Infiltration_Overrides.md) - Original methodology
- [h5py Documentation](https://docs.h5py.org/) - Python HDF5 library
- [HDFView](https://www.hdfgroup.org/downloads/hdfview/) - HDF file viewer
