# ras2cng workflow evidence

Use installed ras2cng help and canonical contracts for exact commands and options. These notebooks explain the operation sequence and acceptance surfaces; avoid their installation cells and historical capability counts.

- [Geometry export](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/960_cloud_native_geometry_export.ipynb) exports mesh cells and additional HDF/text layers, reads GeoParquet back with CRS and feature counts, queries with DuckDB, and optionally creates PMTiles when tools exist. Geometry export is distinct from model execution; do not rerun a completed model merely to produce geometry.
- [Results export](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/961_cloud_native_results_export.ipynb) joins maximum WSE to mesh geometry, queries by mesh, and demonstrates project inspection/archive. When existing results are sufficient, skip its demonstration solve. Current canonical contracts require mesh identity plus element ID where IDs restart across 2D areas; verify joins and unpaired rows rather than trusting a map image.
- [COG results export](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/962_cloud_native_cog_results_export.ipynb) generates native stored maps and converts core/extended products, with raster metadata and depth-threshold checks. Read this for map-generation prerequisites, not a promise that every current runtime has identical support.
- [Headless Linux/Wine setup](https://github.com/gpt-cmdr/ras-commander/blob/main/examples/511_headless_linux_wine_ras2cng.ipynb) documents isolated prefixes/projects, topology preflight, version-specific native comparisons, and serial stored-map generation within a prefix. Use the setup skill only for a task that needs that runtime; export of existing HDF data does not require Wine.

Canonical package references:

- [Project archive](https://rascommander.info/ras2cng/user-guide/project-archive/) owns archive catalog and extraction policy. Inspect current manifest/schema rather than assuming all plans share one geometry.
- [Raster delivery](https://rascommander.info/ras2cng/user-guide/raster-delivery/) owns COG compression, overviews, nodata, and validation. Record lossy tolerance explicitly; analytical rasters need the supported lossless setting. Area-aware overview policy and source CRS preservation are not optional cosmetic details.
- [ras2cng source and contract](https://github.com/gpt-cmdr/ras2cng) are authoritative for current implementation, required extras, and schema guarantees. Read relevant installed guidance on demand rather than copying the package's APIs into this skill.

Export validation should establish source-to-artifact identity and declared completeness. Numerical mapping parity belongs to `ras-mapping`; successful archival does not demonstrate hydraulic adequacy or grant permission to publish.
