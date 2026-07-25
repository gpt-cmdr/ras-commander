# Native Land-Cover Authoring Validation

## Objective

Determine and qualify the HEC-RAS-native workflow for creating land-cover
classification layers and applying spatial Manning's n values. Custom HDF
authoring is not accepted as production-ready unless it is proven
byte/schema-compatible and changes the final solver Manning data.

## Required proof

- Trace the relevant RASMapperLib and RasProcess APIs with RASDecomp.
- Exercise representative HEC-RAS 5.x and 6.x example projects.
- Create the land-cover layer through native HEC APIs where available.
- Associate it with a compiled geometry through the native association API.
- Recompute property tables and the plan through HEC-RAS itself.
- Verify expected, materially distinct Manning values in the final results HDF.
- Inventory all related ras-commander APIs as qualified, repairable, deprecated,
  or removed.

## Folder layout

- `rasdecomp/` — versioned reflection/decompilation evidence.
- `scripts/` — reproducible probes and validation harnesses.
- `fixtures/` — small manifests and input tables; large HEC-RAS projects remain
  outside git and are referenced by hash/path manifests.
- `results/` — machine-readable validation summaries and HDF schema diffs.
- `API_AUDIT.md` — public API disposition and evidence.
- `FINDINGS.md` — technical conclusions and recommended native workflow.

## Status

Qualified on the Muncie example with HEC-RAS 5.0.7 and 6.6. Both runs used
native RASMapper authoring and association, completed successfully through
`RasCmdr.compute_plan`, and produced ten materially distinct final face Manning
values. The 6.6 result also contains the same ten values in
`Cells Center Manning's n`.

The custom rasterio/h5py writer is no longer on the public authoring path.
Direct mutation of solver-owned geometry HDF datasets is disabled. See
`FINDINGS.md`, `API_AUDIT.md`, and `results/`.
