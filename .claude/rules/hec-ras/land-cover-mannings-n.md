# Land Cover Manning's n Architecture

**Context**: How HEC-RAS resolves per-cell Manning's n from land cover layers
**Priority**: High - misunderstanding causes silent incorrect roughness
**Auto-loads**: Yes (land cover and Manning's n workflows)
**Discovered**: 2026-05-18 (CLB-828 investigation, verified against L: drive production models)

## Overview

HEC-RAS uses a **layered override architecture** for land cover Manning's n. Understanding the data hierarchy prevents misdiagnosing NaN calibration entries and ensures correct roughness authoring.

## Data Hierarchy

```
Sidecar HDF Variables           <- authoritative base n-values per class
  | overridden by
LCMann Table= (plain text .g##) <- base n-value overrides (optional)
  | overridden by
LCMann Region Table=            <- per-region calibration overrides (optional)
  | written to
Geometry HDF Calibration Table  <- final preprocessed values (NaN = use sidecar)
  | sampled to
Per-cell Manning's n            <- composite classification per mesh face
```

### Layer 1: Sidecar HDF (base values)

The land cover sidecar HDF (e.g., `Land Classification/LandCover.hdf`) stores the **authoritative base Manning's n** in its `Variables` dataset:

```
Variables dataset: [('Name', 'S28'), ('ManningsN', '<f4'), ('Percent Impervious', '<f4')]
```

These values are set when the sidecar is authored (via RASMapper GUI or `RasMap.add_landcover_layer()`). HEC-RAS reads them directly during preprocessing when no overrides exist.

### Layer 2: Plain-text overrides (optional)

The `.g##` geometry file may contain `LCMann Table=N` with per-class n-value overrides:

```
LCMann Table=23
Estuarine Scrub-Shrub Wetland,0.07125
Grassland-Herbaceous,0.03125
...
```

- `LCMann Table=0` means **no overrides defined** (empty table)
- Class names must match the sidecar's `Raster Map` names exactly
- These override the sidecar base values; they do NOT replace them

### Layer 3: Regional calibration overrides (optional)

`LCMann Region Table=N` blocks provide per-region n-value adjustments for calibration. Each region can have different n-values for the same land cover classes.

### Layer 4: Geometry HDF Calibration Table (computed)

During geometry preprocessing, HEC-RAS writes the final calibration table to:

```
Geometry/Land Cover (Manning's n)/Calibration Table
```

**NaN in the calibration table means "no override defined" -- not "missing value."** HEC-RAS uses the sidecar base value when the calibration entry is NaN.

## No Class Count Limit

HEC-RAS does **NOT** have a 16-class limit. Verified with production models:

| Model | Classes | Calibration Rows | Status |
|-------|---------|-------------------|--------|
| ECLC (CCAP land cover) | 24 | 25 | All valid n-values |
| Lower Calcasieu (NLCD) | 16 | 16 | All NaN (no overrides, uses sidecar) |
| Bayou Pierre (NLCD) | 18 | 16 | All NaN (no overrides, uses sidecar) |

Models with `LCMann Table=0` show all-NaN calibration entries because no overrides are defined. This is normal -- HEC-RAS reads the sidecar `Variables` directly.

## Special Characters in Class Names

HEC-RAS rejects `/` and `\` in land cover class names. NLCD classes like `Shrub/Scrub` and `Pasture/Hay` must be sanitized before writing to the sidecar or geometry text.

Production models use `-` as replacement: `Shrub-Scrub`, `Pasture-Hay`.

```python
from ras_commander.geom import ManningsFromLandCover

# sanitize_names=True (default) replaces / and \ with -
table = ManningsFromLandCover.default_landcover_classification_table()
```

## Required Flags for Spatial Manning's n

Two flags in the plain-text `.g##` must be enabled for per-cell land cover Manning's n:

```python
from ras_commander.geom import GeomStorage

GeomStorage.set_2d_flow_area_settings(
    geom_file, flow_area_name,
    spatially_varied_mann_on_faces=True,   # use LCMann Table per cell
    composite_classification=True,          # composite weighting per face
)
```

When `spatially_varied_mann_on_faces=False`, HEC-RAS assigns uniform base Manning's n to every cell regardless of land cover.

## Preprocessing: clear_geompre vs force_geompre

When land cover associations exist in the geometry HDF:

- **`clear_geompre=True`**: Deletes only `.c##` binary files. Preserves the `.g##.hdf` with its land cover filename attribute. **Use this.**
- **`force_geompre=True`**: Deletes both `.g##.hdf` AND `.c##`. Destroys the land cover filename attribute that tells HEC-RAS where the sidecar is. **Avoid when land cover is configured.**

```python
RasCmdr.compute_plan(plan_number, clear_geompre=True)  # correct
```

## Authoring Workflow

Complete workflow for programmatic land cover Manning's n:

```python
from ras_commander import RasMap, RasCmdr, init_ras_project
from ras_commander.geom import GeomLandCover, GeomStorage, ManningsFromLandCover

# 1. Create sidecar HDF from NLCD raster (base values in sidecar)
classification_table = ManningsFromLandCover.default_landcover_classification_table()
authored_hdf = RasMap.add_landcover_layer(
    ras_project_path, nlcd_raster,
    classification_table=classification_table,
    layer_name="NLCD Land Cover",
)

# 2. Optionally write base overrides to plain-text geometry
GeomLandCover.replace_base_mannings_n(geom_file, classification_table)

# 3. Enable spatial flags
GeomStorage.set_2d_flow_area_settings(
    geom_file, flow_area_name,
    spatially_varied_mann_on_faces=True,
    composite_classification=True,
)

# 4. Associate sidecar with geometry HDF
RasMap.associate_geometry_layers(rasmap_path, geom_hdf_path)

# 5. Run with clear_geompre (preserves HDF associations)
RasCmdr.compute_plan(plan_number, clear_geompre=True)
```

## Cross-References

**Primary sources**:
- `examples/212_landcover_mannings_n_write.ipynb` -- Complete land cover workflow
- `ras_commander/geom/GeomLandCover.py` -- Plain-text LCMann Table read/write
- `ras_commander/geom/ManningsFromLandCover.py` -- NLCD defaults and classification table
- `ras_commander/_land_classification_helper.py` -- Sidecar HDF authoring
- `ras_commander/hdf/HdfLandCover.py` -- Preprocessed Manning's n extraction

**Rules** (related):
- `.claude/rules/hec-ras/geometry.md` -- Geometry file overview, subgrid sampling
- `.claude/rules/hec-ras/execution.md` -- clear_geompre vs force_geompre

---

**Key Takeaway**: The sidecar HDF holds the authoritative base Manning's n. The plain-text LCMann Table is an optional override layer. NaN in the geometry HDF calibration table means "use sidecar default" -- not "missing." There is no class count limit.
