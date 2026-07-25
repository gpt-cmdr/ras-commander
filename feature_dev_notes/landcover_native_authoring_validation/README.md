# Native Land-Cover Authoring Validation

## Objective

Determine and qualify the HEC-RAS-native workflow for creating land-cover
classification layers and applying spatial Manning's n values. Custom HDF
authoring is not accepted as production-ready unless it is proven
byte/schema-compatible and changes the final solver Manning data.

## Required proof

- Trace the relevant RASMapperLib and RasProcess APIs with RASDecomp.
- Exercise every stable installed HEC-RAS generation from 5.0.7 through 7.0.
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
- `OPEN_QUESTIONS.md` — precise explanation of disabled APIs, narrower
  successful evidence, and pythonnet replacement options.

## Status

The initial 5.0.7 and 6.6 proof has been expanded to a fresh-process,
three-scenario matrix across the stable installed releases from 5.0.7 through
7.0. Each row authors and associates the native layer, changes a geometry base
Manning value, changes one sidecar class Manning value (or performs a native
5.x rebuild), recomputes, solves, and verifies exact final-array deltas.
Every stable-release row passed; HEC-RAS 6.7 Beta 5 also passed as a
supplemental between-release check.

The custom rasterio/h5py writer is no longer on the public authoring path.
Routine direct mutation of solver-owned geometry HDF datasets is disabled;
narrow, proven forensic/advanced uses are documented separately. Native
existing-class land-cover polygon CRUD is now qualified for HEC-RAS 6.x and
7.0.x. Native geometry infiltration-region creation and Base Override
authoring are qualified for 6.x and 7.0.x with scoped save, rollback, and fresh
native readback; 5.0.7 lacks that API and fails closed. See `FINDINGS.md`,
`API_AUDIT.md`, `OPEN_QUESTIONS.md`,
`infiltration_override_native/`, and `results/`.
