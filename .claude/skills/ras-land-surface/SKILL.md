---
name: ras-land-surface
description: "Prepare and audit HEC-RAS land-use, roughness, soil/infiltration layers and overrides, including geometry associations and final preprocessed values."
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# RAS land surface

Own the path from classified source grids and parameter tables to HEC-RAS cell properties. Keep rainfall generation with `ras-gridded-precipitation`; hand hydraulic execution to the execution workflow when needed.

1. Inspect the installed public `RasMap`, `HdfLandCover`, `HdfInfiltration`, and `ManningsFromLandCover` APIs. Record model/version, geometry/plan association, current terrain and sidecars, CRS/units, classification scheme, nodata footprint, and requested edits.
2. During planning, read the relevant [HEC references](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/development/hec-planning-references.md) and [workflow evidence](references/workflows.md). Establish infiltration method and parameter meanings before translating soil attributes. A soil class or land-use code alone is not a hydraulic parameter or calibration justification.
3. Work on an authorized copy, retaining existing associations and native backups. Discover supported layer creation and mutation APIs; do not hand-build HDF schemas. Keep categorical resampling distinct from continuous parameter interpolation, preserve source codes and unknown classes, and report gaps before assigning defaults.
4. Distinguish sidecar classification tables, geometry-wide Base Overrides, named regional overrides, and final preprocessed arrays. Use native association and recomputation APIs where required; honor `recompute_required`. Confirm fresh readback rather than trusting a write return alone.
5. Check expected class coverage and parameter units/ranges, preserve holes and region topology supported by the installed API, and audit final values by mesh and cell identity. Fully covered/disjoint cells and partially intersected cells need different attribution checks. Preserve ghost/unreconstructable rows explicitly rather than dropping them in a spatial join.
6. If a solve is authorized, require completed-plan HDF arrays and compare intended assignments with what the solver consumed. Report hydraulic response separately: an inactive region can have a valid parameter change without a material event response.

Use Commander for preprocessing/execution; never raw Ras.exe or direct edits to cached property tables. Report unsupported topology, methods, source-data acquisition gaps, and runtime requirements rather than inventing soil conversion or support.
