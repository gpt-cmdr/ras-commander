---
name: cloud-native-gis
description: "Coordinate cloud-native GIS and archival workflows for HEC-RAS and HEC-HMS using the installed ras2cng and hms2cng packages. Use for GeoParquet, PMTiles, DuckDB, PostGIS, terrain/results export, or map delivery tasks."
shared_corpus: true
harness_scope: shared
source_owner: gpt-cmdr
security_review: internal
---

# Cloud Native GIS

Coordinate cloud-native workflows through the current ras2cng or hms2cng public API/CLI. Use this skill when invoked directly or routed from RAS/HMS Commander. Read [runtime and MCP boundaries](../ras-commander/references/runtime-and-mcp.md) for version discipline and the informational-tool boundary.

1. Identify the source model family and requested output. Route HEC-RAS to ras2cng and HEC-HMS to hms2cng. Mixed tasks retain separate source identity and can share a declared output catalog.
2. Discover the installed version and supported command/signature. Read the selected package's current help, public docs, and available canonical AGENTS instructions. Resolve checkout paths from the environment; do not assume `C:/GH` or a NAS mount exists. Do not import the whole historical export skill as a current CLI contract.
3. Establish horizontal CRS, vertical datum where relevant, quantity/units, time/aggregation, geometry source, output location, and overwrite behavior. Preserve unknown metadata; do not relabel coordinates or water levels as a transformation. Use the package's canonical guidance for source-specific geometry distinctions and archival formats.
4. Use only the required extras and binaries for the operation. GIS, raster, DSS, map generation, and storage tools belong here in the Python/CLI path, not in an MCP information server. Missing dependencies or engine requirements must be reported before dependent work.
5. Preserve source projects for export/archive workflows. Operations that generate native maps, modify terrain, write databases, upload, or publish require the corresponding task authorization and documented side-effect review. No automatic publication follows a successful local export.
6. Return artifact paths, catalog/layer identity, versions, source provenance, CRS/datum/units, actual checks performed, and remaining limitations. Delegate a bounded domain task when useful; return summaries rather than large spatial arrays to the coordinator.

Use canonical package tools and opinions on demand. The same concept can have different contracts in ras2cng and hms2cng; do not duplicate their implementation or invent equivalence. Repository writing rules govern contributions, not the user's maps or deliverables.
