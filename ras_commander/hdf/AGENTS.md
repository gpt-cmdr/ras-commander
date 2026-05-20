# HDF Subpackage Contract

This file is the canonical local instruction file for `ras_commander/hdf/`.

## Scope

- Parent guidance from `ras_commander/AGENTS.md` and the repo root still applies.
- This directory handles HEC-RAS geometry and results HDF access.

## Module Families

- Core helpers: `HdfBase`, `HdfUtils`, `HdfPlan`
- Geometry readers: `HdfMesh`, `HdfXsec`, `HdfBndry`, `HdfStruc`, `HdfHydraulicTables`
- Results readers: `HdfResultsPlan`, `HdfResultsMesh`, `HdfResultsXsec`, `HdfResultsBreach`
- Infrastructure and land surface: `HdfPipe`, `HdfPump`, `HdfInfiltration`, `HdfLandCover`
- Plotting and analysis: `HdfPlot`, `HdfResultsPlot`, `HdfBenefitAreas`, `HdfChannelCapacity`, `HdfFluvialPluvial`

## Implementation Rules

- Follow the existing static-class pattern.
- Public methods should use `@staticmethod`, `@log_call`, and `@standardize_input(...)` when the surrounding module already does.
- Keep heavy dependencies lazy-loaded inside methods when practical:
  - `geopandas`
  - `shapely`
  - `xarray`
  - `matplotlib`
  - `scipy`
- Use `h5py.File(..., "r")` context managers for direct file access.
- Distinguish clearly between `plan_hdf` inputs and `geom_hdf` inputs when adding or modifying decorators.

## Input And Output Rules

- Accept the flexible HDF-facing input forms already used in this package: plan numbers, prefixed plan numbers, paths, and open HDF handles where the decorator pattern already allows them.
- Return pandas or GeoPandas objects in the shapes established by nearby code. Do not invent a new container style for one method unless the surrounding API also changes.
- Log read failures with enough file context to debug the issue.

## Common Entry Points

- Plan metadata and compute messages: `HdfResultsPlan`
- 2D cell geometry and face geometry: `HdfMesh`
- 2D face property table write (Manning's n vs Elevation): `HdfMesh.set_mesh_face_property_tables()`, `extend_face_property_tables()`, `set_face_mannings_n_values()`, `pin_property_tables()`
- 2D face spatial filtering (polygon mask): `HdfMesh.get_face_ids_in_polygon()`, `get_face_ids_in_calibration_region()`
- Both `extend_face_property_tables()` and `set_face_mannings_n_values()` accept optional `polygon` and `region_name` parameters for selective face application (precedence: `face_ids` > `region_name` > `polygon` > all faces)
- 2D results extraction: `HdfResultsMesh`
- 1D cross section geometry and results: `HdfXsec`, `HdfResultsXsec`
- Land cover and infiltration preprocessing: `HdfLandCover`, `HdfInfiltration`
- Infiltration group authoring: `HdfInfiltration.create_infiltration_group()`, `HdfInfiltration.set_infiltration_baseoverrides()`

## Testing

- Use real example HDF files when validating behavior.
- Prefer targeted tests over synthetic HDF fixtures unless a regression cannot be reproduced against real examples.
