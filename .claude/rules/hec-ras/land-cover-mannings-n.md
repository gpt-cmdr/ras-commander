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

## Per-cell Manning's n comes from the land-cover ASSOCIATION, not from the two flags

> **Correction (2026-06-01):** a prior version of this rule claimed that
> `spatially_varied_mann_on_faces` and `composite_classification` "must be enabled for per-cell
> land cover Manning's n," and that with `spatially_varied_mann_on_faces=False` HEC-RAS uses a
> uniform n regardless of land cover. **That is wrong.** Cell-center land-cover Manning's n is
> driven by the **land-cover association** (sidecar `LandCover.hdf` + raster, referenced from the
> `.rasmap` / geometry HDF), independent of those two flags.

**Verified empirically** (`BaldEagleCrkMulti2D` g01): both flags are `False`, the `2mannings_n`
default attribute is a single value (0.04), yet the preprocessed
`Geometry/2D Flow Areas/<area>/Cells Center Manning's n` is spatially varied (**0.03–0.15 per cell**,
89,879 cells) derived directly from the land-cover association. The uniform default attribute is
only a fallback used where no association/class applies.

What the two flags actually control:

- `spatially_varied_mann_on_faces` — enables **depth-varying Manning's n on cell FACES**: a per-face
  n that varies with flow depth, derived from the sub-grid land cover within each face (see the
  CLB-757 depth-varying face-n API). This is a face-level refinement, **not** the on/off switch for
  cell-center land-cover n.
- `composite_classification` — composite (area-weighted) classification of face Manning's n.

```python
# Optional refinement (depth-varying FACE n). NOT required for cell-center land-cover n,
# which is applied whenever a land-cover association exists.
from ras_commander.geom import GeomStorage
GeomStorage.set_2d_flow_area_settings(
    geom_file, flow_area_name,
    spatially_varied_mann_on_faces=True,
    composite_classification=True,
)
```

### Propagating an LCMann / sidecar change to per-cell n (matters for sensitivity/Monte Carlo)

The preprocessed `Cells Center Manning's n` is **cached in the `.g##.hdf`**. Editing the plain-text
`LCMann Table` (or the sidecar `Variables`) does **not** change per-cell n until the geometry
preprocessor re-derives it.

**Historical hazard:** earlier, `clear_geompre=True` only deleted `.c##` and **preserved** the
`.g##.hdf` (and its cached per-cell n), so a plain-text `LCMann Table` edit was silently **ignored at
compute time** — a Monte Carlo ensemble that perturbed the `LCMann Table` across 30 samples produced
**byte-identical per-cell n and identical WSE** in every sample.

**Resolved (layer 1 — the cache):** `GeomPreprocessor.clear_geompre_files()` now also calls
`GeomPreprocessor.clear_geompre_hdf()`, which deletes the cached `Cells Center Manning's n` +
property tables **inside the `.g##.hdf` in place** (mirroring HEC-RAS's own `CleanPropertyTables`)
while **preserving** the mesh topology and the land-cover association. Once that clearing runs,
HEC-RAS re-derives per-cell n from the (perturbed) land-cover source.

**Still live (layer 2 — the smart skip):** clearing only helps if `compute_plan()` gets far enough
to do it. The smart skip is evaluated **before** the `clear_geompre` branch, and
`are_plan_results_current()` compares only `.p##`/`.g##`/`.u##` mtimes against the results HDF. A
sidecar/`LCMann` perturbation leaves all three untouched, so results still look "current",
`compute_plan(clear_geompre=True)` returns success **without clearing and without running**, and the
sample silently reuses the previous per-cell n. That reproduces the byte-identical symptom above
even with layer 1 fixed. Pinned by
`tests/test_rascmdr_compute_plan_control_flow.py::test_compute_plan_clear_geompre_is_skipped_when_results_are_current`.

**When this bites, and when it doesn't.** The skip only fires when the results genuinely look newer
than `.p##`/`.g##`/`.u##`. Anything that refreshes one of those mtimes defeats it:

| Ensemble shape | Skip fires? | What to use |
|---|---|---|
| `RasMonteCarlo.run_ensemble(clone_geom=True, clear_geompre=True)` | No — cloning gives each `.g##` a fresh mtime | `clear_geompre=True` is sufficient |
| Fresh `dest_folder` per sample | No — copied results are not current | `clear_geompre=True` is sufficient |
| Perturb sidecar in place, reuse one geometry | **Yes** — `.g##` mtime never changes | `force_geompre=True` |

```python
# In-place sidecar perturbation: force the run past the skip.
RasCmdr.compute_plan(plan_number, force_geompre=True, ras_object=ras)
```

## Preprocessing: clear_geompre vs force_geompre

When land cover associations exist in the geometry HDF:

- **`clear_geompre=True`**: Deletes `.c##` binary files **and** clears the geometry-preprocessor tables (incl. cached per-cell `Cells Center Manning's n`) inside the `.g##.hdf` in place via `clear_geompre_hdf()`, while **preserving** the land cover filename attribute / association. Forces per-cell n re-derivation on next compute. **Use this.**
- **`force_geompre=True`**: Does the same in-place clearing, then rebuilds the property tables immediately via `RasProcess.exe CompleteGeometry` instead of leaving the work to the solver. Also **implies `force_rerun`** — the currency check compares only `.p##`/`.g##`/`.u##` mtimes, so it cannot see a perturbed sidecar and would otherwise skip the run outright. **Use this for land cover sweeps** where the `.g##` mtime never changes.

```python
RasCmdr.compute_plan(plan_number, clear_geompre=True)   # geometry edited: mtime changed, no skip
RasCmdr.compute_plan(plan_number, force_geompre=True)   # sidecar/LCMann edited: mtime unchanged
```

> **Corrected (2026-07-16):** a prior version of this rule said `force_geompre=True` "deletes both
> `.g##.hdf` AND `.c##`... destroys the land cover filename attribute... **Avoid when land cover is
> configured**." That was true, and is now fixed: `force_geompre` clears the cached tables in place
> rather than deleting the geometry HDF, so the association survives. Verified on
> `BaldEagleCrkMulti2D` (HEC-RAS 7.0): after clear + rebuild, per-cell n returns identical
> (89,879 cells, 0.030–0.150) with `Land Cover Filename` intact.
>
> Note `clear_geompre=True` alone does **not** defeat the smart skip. If the perturbation leaves the
> `.g##` mtime untouched — the exact Monte Carlo case above — the run is skipped and `clear_geompre`
> never fires. Use `force_geompre=True` (or add `force_rerun=True`) for those ensembles.

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
