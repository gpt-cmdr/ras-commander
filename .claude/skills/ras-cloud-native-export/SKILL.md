---
name: ras-cloud-native-export
description: "Use ras2cng to inspect and archive HEC-RAS projects, export geometry/results/terrain, and validate GeoParquet, COG, or tile delivery."
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# RAS cloud-native export

Own RAS-specific cloud-native conversion and delivery; the broader `cloud-native-gis` skill remains the RAS/HMS router. Read canonical installed ras2cng guidance and command help instead of maintaining a copied CLI/API catalog.

1. Record installed ras2cng and ras-commander versions, selected project/geometry/plan, available results, intended formats, and permitted outputs. Inspect before exporting. Source `main` examples can exceed the installed release; preserve pins and report missing capabilities.
2. Use [workflow and notebook references](references/workflows.md) to choose geometry-only, results, archive, terrain, or map delivery. During planning, consult the relevant [HEC references](https://github.com/gpt-cmdr/ras-commander/blob/main/docs/development/hec-planning-references.md) for quantity and RAS Mapper semantics. Canonical ras2cng docs own storage and delivery policy.
3. Establish source identity, horizontal CRS, vertical datum/units where relevant, quantity and time aggregation, and analytical versus display use. Preserve unknown CRS/datum; never guess an EPSG authority or relabel a coordinate system as a transformation.
4. Preserve source projects. Use supported public export/archive APIs or CLI into an authorized destination. HDF export does not itself require recomputation. Native map generation does require its documented qualified runtime; do not run HEC-RAS simply to export existing results.
5. Validate the manifest, expected geometries/plans/layers, row counts and schemas, composite mesh/element join identities, CRS, missing/unpaired rows, and representative source-to-output values. For raster delivery inspect nodata masks, bounds, units, compression tolerance, overviews, and COG validity through canonical validators. Request lossless output when values feed calculations; display compression defaults must not silently become analytical inputs.
6. Return local artifacts and provenance with actual completeness and validation status. Database writes, remote sync, upload, and publication require task scope; local export success does not authorize them.

Hand creation or numerical qualification of hydraulic maps to `ras-mapping`. Keep raw spatial/gridded data on the Python/CLI path, outside project MCP information tools. Never invoke Ras.exe directly or duplicate ras2cng's parsers and delivery implementation.
