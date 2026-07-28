# HDF Writing Guide

Safe practices for programmatically modifying HEC-RAS HDF files.

## Native-First Policy

!!! danger "Do not hand-author RAS-owned schemas"
    The absence of a plain-text equivalent does not authorize direct HDF
    mutation. HEC-RAS depends on object state, metadata, compound shapes,
    resamplers, and save semantics that are not captured by a visible dataset
    dtype. A file can open while the solver silently ignores the change.

Use this precedence:

1. Edit a durable plain-text component through its Ras Commander API when one
   exists.
2. For RAS-owned HDF data, use the native RasMapperLib, RasProcess, or
   HEC-RAS automation API and validate a fresh reload.
3. Use `h5py` for read-only inspection.
4. Direct writes are permitted only through an explicitly version-, role-, and
   schema-qualified Ras Commander recovery/solver-temporary-file API that
   creates a full backup and validates readback.

## RAS-Owned HDF Data

These categories are stored in HDF and must be authored by HEC-RAS or a
qualified native wrapper:

| Data Category | HDF File Type | HDF Location |
|---------------|---------------|--------------|
| Gridded Precipitation | `.p##.hdf` | `/Event Conditions/Meteorology/` |
| Gridded Land Cover | `Land Cover.*.hdf` | `//Raster Map`, `//Variables` |
| Gridded Soils | `Soils.*.hdf` | `//Raster Map`, `//Variables` |
| Infiltration Base Overrides | `.g##.hdf` | `/Geometry/Infiltration/Base Overrides` |
| Infiltration Region Overrides | `.g##.hdf` | `/Geometry/Infiltration/Variables/*` |
| Pipe Networks | `.g##.hdf` | `/Geometry/Pipe Networks/` |
| Terrain Data | `Terrain.hdf` | `//Elevation` |
| Computed Results | `.p##.hdf` | `/Results/` |
| Computed Mesh | `.g##.hdf` | `/Geometry/2D Flow Areas/*/Cells` |

Computed results and mesh arrays are normally read-only. The only current
solver-temporary direct-write exception is the guarded HEC-RAS 7.0 Linux face
property-table workflow in `HdfMesh`, restricted to verified
`HEC-RAS Results` `*.p##.tmp.hdf` files. A separate legacy-recovery exception,
`GeomPreprocessor.invalidate_legacy_geometry_hdf_preprocessor_cache()`, is
restricted to exact 5.x/6.x geometry HDFs and requires both an exact file
version and explicit acknowledgement. Native recomputation remains canonical.

## Geometry Association Attributes

Compiled geometry HDFs also carry `/Geometry` associations to RASMapper assets
such as terrain, land cover, infiltration, and sediment bed-material soils.
`RasMap.associate_geometry_layers()` delegates this operation to the selected
HEC-RAS generation's native geometry-association API and validates the native
readback.

```python
from ras_commander import RasMap

RasMap.associate_geometry_layers(
    project_path,
    "MyModel.g01.hdf",
    terrain_hdf_path="Terrain/ExistingTerrain.hdf",
    landcover_hdf_path="Land Classification/LandCover.hdf",
)

association = RasMap.get_hdf_geometry_association("MyModel.g01.hdf")
print(association["terrain_hdf_path"])
```

!!! warning "Do not confuse association with compilation"
    Association updates an existing compiled geometry through HEC-RAS. It does
    not create `.g##.hdf` from plain-text `.g##` geometry and does not
    regenerate 2D mesh or property-table datasets.

## The Golden Rule

!!! danger "Let HEC-RAS define the schema"
    HEC-RAS is extremely particular about HDF structure. Matching the visible
    datasets is not sufficient; use the native object and save path that owns
    the artifact.

This includes:
- Structured array field names
- Data types (f4 vs f8, string lengths)
- Compression type and level
- Chunk sizes
- Fill values
- Dataset attributes

## Native Qualification Workflow

### Step 1: Create Reference Files

Before adding a native writer, generate reference files by completing the
workflow manually:

1. Start with a working HEC-RAS model
2. Make the desired change manually in RASMapper or the GUI
3. Save the project
4. Export/copy the HDF files before and after the change

### Step 2: Decompile and Inspect

Use RASDecomp or reflection to identify the exact native object, method, and
save boundary. Use HDFView only to compare the resulting artifact; HDF
inspection does not establish a safe writer.

Use [HDFView](https://www.hdfgroup.org/downloads/hdfview/) to examine the exact structure:

1. Open the HDF file
2. Navigate to the dataset you want to modify
3. Right-click → "Show Properties" → "General Object Info"
4. Note these critical properties:
   - **Datatype**: Field names, types, sizes
   - **Dataspace**: Shape, dimensions
   - **Storage layout**: Chunking
   - **Filters**: Compression type and level

### Step 3: Inspect Read-Only

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

### Step 4: Implement Through the Native Owner

Load the DLL from the requested HEC-RAS installation, reject a mismatched
already-loaded runtime, constrain the mutation to the smallest native layer or
command, create a durable backup, and validate a fresh native reload. Do not
substitute a generic delete-and-recreate `h5py` writer.

### Step 5: Validate End to End

After modification, verify:

1. **HEC-RAS loads the file** without errors
2. **Data appears in the GUI** correctly
3. **Geometry preprocessor runs** without regenerating your data
4. **Simulation produces expected results**

## Example: Infiltration Base Overrides

This example demonstrates the complete workflow for modifying geometry-wide
infiltration parameters:

### The Problem

HEC-RAS stores two different infiltration-override surfaces in the geometry
HDF. The Base Overrides table is a geometry-wide class-to-parameter fallback.
Each named calibration polygon has a separate parameter table under
`Variables`; the polygon does not spatially constrain Base Overrides. Unlike
most geometry data, both surfaces are **HDF-only**—no plain-text equivalent
exists.

HDF locations:

- geometry-wide fallback: `/Geometry/Infiltration/Base Overrides`
- per-region tables: `/Geometry/Infiltration/Variables/*`

### Read and Update Through HEC-RAS

Treat the compound datasets below `/Geometry/Infiltration` as RAS-owned.
Matching only the visible NumPy dtype is insufficient: HEC-RAS also depends on
native parameter tables, feature layers, metadata, and save behavior. Do not
delete or recreate these datasets with `h5py`.

Use the native RasMapper-backed API instead:

```python
from ras_commander import HdfInfiltration
from pathlib import Path

geom_hdf = Path("MyProject.g01.hdf")

# Read current values
current_df = HdfInfiltration.get_infiltration_baseoverrides(geom_hdf)
print(current_df)

# Scale active values. -9999 sentinel values remain unchanged.
scale_factors = {
    "Curve Number": 1.02,
    "Minimum Infiltration Rate": 0.9,
}

scaled_df = HdfInfiltration.scale_infiltration_base_overrides(
    geom_hdf,
    current_df,
    scale_factors,
    hecras_version="7.0",
)

# Apply a distinct table only inside one named native region.
regional_df = HdfInfiltration.set_infiltration_region_overrides(
    geom_hdf,
    current_df,
    region_name="Main Channel",
    hecras_version="7.0",
)
```

If the geometry has no infiltration override region yet, call
`create_infiltration_override_regions()` first. It copies the existing native
Manning-region polygons and asks RasMapper to author the complete infiltration
schema. Creating those regions materializes both the geometry-wide Base
Overrides table and each region's parameter table; it does not make the Base
Overrides spatially regional. These geometry override APIs are qualified for
HEC-RAS 6.x and 7.0.x; 5.x fails with explicit migration guidance.

Regional override polygons must be hole-free. HEC-RAS 6.0–7.0.1 drops
interior-ring topology while converting these polygons for parameter
resampling, so Ras Commander rejects a selected region with a hole. Represent
the same coverage as explicit, non-overlapping, hole-free polygons.

To edit an infiltration *sidecar* rather than geometry Base Overrides, use
`set_infiltration_sidecar_parameters()` or
`scale_infiltration_sidecar_parameters()`. Sidecar values are ignored whenever
the associated geometry contains active Base Overrides, so choose the artifact
explicitly.

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

**Solution**: Stop using the modified artifact, restore the durable pre-edit
backup, and rerun the native HEC-RAS authoring operation in a fresh process.
Do not attempt to repair an unknown RAS-owned schema in place.

## Best Practices

### 1. Require Durable Backups and Rollback

Public native writers should create uniquely named, timestamped pre-edit
backups and restore a separate transaction snapshot on any failure. Return the
backup path in the result/report rather than relying only on a log message.

### 2. Keep `h5py` Read-Only

Read-only inspection is valuable for postconditions and diagnostics:

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

### 3. Validate Native Reload and Solver Output

After native save, release the native object, reload it in a fresh process,
compare the persisted semantic values, run the applicable geometry/plan
computation, and inspect the final solver arrays. Dataset existence alone is
not proof that HEC-RAS used the change.

### 4. Use Agent-Assisted Development

For new native integrations:

1. **Generate reference files manually** using HEC-RAS GUI
2. **Use RASDecomp and an agent** to identify the native ownership/save path
3. **Human-in-the-loop validation** by H&H Engineer
4. **Qualify every supported HEC-RAS family** in fresh processes

## See Also

- [HDF Structure Reference](hdf-structure.md) - Complete HDF path reference
- [HdfInfiltration API](../api/hdf.md#hdfinfiltration) - Infiltration modification methods
- [Infiltration Override Deep Dive](https://github.com/gpt-cmdr/HEC-Commander/blob/main/Blog/8._Deep_Dive_Infiltration_Overrides.md) - Original methodology
- [h5py Documentation](https://docs.h5py.org/) - Python HDF5 library
- [HDFView](https://www.hdfgroup.org/downloads/hdfview/) - HDF file viewer
