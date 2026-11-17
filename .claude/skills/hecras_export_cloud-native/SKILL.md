---
name: hecras_export_cloud-native
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
description: Export HEC-RAS data through current ras2cng contracts for cloud-native storage, GIS analysis, or map delivery. Use for authorized GeoParquet, PMTiles, archive, and database workflows.
---

# HEC-RAS Cloud Native Export

This compatibility name routes directly to `ras-cloud-native-export` for the current RAS-specific workflow. Use `cloud-native-gis` only when model family is unknown or a task spans RAS and HMS. Select ras2cng for RAS inputs, discover the installed public API/CLI and matching release guidance, and use only the dependencies needed for the requested operation. Do not preserve a historical command catalog as a current package contract.

Geometry, binary results, raster/gridded data, export-file generation, and database writes use the fuller Python/CLI path, never the informational MCP. Preserve source data, quantity/units, CRS/datum, time basis, output identity, and provenance. Export completion does not authorize upload or publication.
