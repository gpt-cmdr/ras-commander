---
name: ras-meteorological-forcings
description: "Acquire, inspect, convert, and validate supported external meteorological grids and DSS forcing records through RAS Commander, native fast-dss, or HEC-Vortex. Use for forcing ingestion and grid processing, not automatic hydraulic parameter selection."
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# Meteorological forcings

**Cardinal rule:** For professional model revisions, build the specification with the engineer/scientist, including report-quality, relevant figures/maps that are actually visually reviewed; the engineer may explicitly defer it. For research, **proceed with approval and document** within the agreed envelope. Follow the [shared specification and reporting workflow](../../references/model-revisions/specification.md), using ras2cng for rich maps when useful. Existing authorization remains valid; do not repeat routine approval requests.

Own source acquisition, quantity/time semantics, conversion, and forcing-file validation. Hand off the validated product to `ras-gridded-precipitation` for precipitation plan attachment or `ras-boundary-conditions` for non-gridded hydraulic boundaries. A format the importer can read is not proof HEC-RAS accepts every variable in that format.

## Planning

Select the meteorology, DSS, and relevant HEC-RAS version topics in [HEC planning references](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/development/hec-planning-references.md) before choosing variables, accumulation periods, or model input types. Read [native/Vortex evidence](references/workflow-evidence.md) for route-specific limits and actual notebook demonstrations.

Record source product/cycle, retrieval and valid times, geographic/time coverage, quantity, units, amount/rate/cumulative semantics, CRS, resolution, missing values, and the intended model consumer. For forecasts, distinguish cycle time, lead time, and valid interval; do not concatenate reset cumulative totals as interval rainfall.

## Select and process

1. Discover installed `ras-commander` and `ras-commander-fast-dss` versions and current public signatures. Query `RasDssGrid.get_features()` and `RasDss.get_capabilities()`; inspect installed engine help for options forwarded by thin wrappers. Development-source examples do not establish installed support.
2. Use `RasDssGrid` for supported native imports, array/Zarr inputs, grid arithmetic, sanitation, clipping, normalization, shifts, temporal resampling, and zonal extraction. This wrapper always uses the native engine regardless of `RasDss.backend`; missing capabilities are reported, not silently replaced.
3. Use `VortexCli` when the selected workflow requires an available Vortex route. Preserve explicit backend choice and disclose prerequisite/runtime differences. Do not claim general native/Vortex equivalence. The separate `PrecipMrms.to_dss` native adapter is restricted to one-hour QPE; it is not the whole `RasDssGrid` capability set.
4. Write derivatives outside immutable sources and retain source hashes plus transformation settings. Time shifting is timestamp arithmetic, not a timezone conversion. Missing coverage does not mean zero; zero-tail extension or normalization requires an explicit task assumption.
5. Read every resulting DSS grid/series back through public APIs. Check quantities, period/type, pathname family, lattice/CRS, units, finite/missing coverage, and totals. For reprojection, compare against a suitable independently constructed source warp over the full relevant extent; nonzero output alone cannot detect spatial truncation. Before coverage, peaks, volumes or totals, identify backend-specific missing markers and mask them as missing in analysis copies. Java series can retain finite HEC markers (`-FLT_MAX`, approximately `-3.4028235e38`, and `-901`/`-902`); null/finiteness checks alone are insufficient. Grid missing-value normalization also differs by backend; inspect record metadata and the installed contract, preserve the missing mask, and do not replace gaps with zero.


Return a forcing manifest, validated paths/pathnames, transformation and coverage checks, and an explicit consumer handoff. Report source-to-file evidence separately from plan preprocessing and completed-solver evidence. Execute HEC-RAS only through RAS Commander when authorized; source conversion does not itself authorize a model run.
