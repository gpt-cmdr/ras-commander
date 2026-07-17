# Example Library Publishing Contract

This file is the canonical agent-facing runbook for building and publishing the
RAS Commander Example Project Library. It is operational guidance and must not
be copied onto the public Example Project Library page.

## Publication Architecture

- Do not commit raw HEC-RAS projects or large generated GIS artifacts to this
  repository.
- Acquire or extract source projects through RAS Commander, compute or inspect
  them through the normal RAS Commander workflow, and export cloud-native
  artifacts with `ras2cng`.
- Post-process terrain, geometry, raw vector results, and RASMapper Stored Map
  rasters into validated MapLibre-ready PMTiles and COGs.
- Publish artifacts to the dedicated RAS Commander WebGIS service, then link the
  docs viewer to its hosted catalog and manifest.
- The public artifact namespace is `/data/rasexamples/hec-ras-7.0/`.
- `rascommander.info` reverse-proxies `/data/*` to the isolated WebGIS artifact
  service. Do not put local file paths in public manifests.

## Infrastructure Boundary

- Run HEC-RAS, `ras2cng`, terrain consolidation, COG generation, and other heavy
  processing on the designated numbered processing hosts or workstations, not
  on CLB-WebGIS.
- Use CLB03 as the trusted publication source and the restricted publisher path
  implemented by `publish_webgis_artifacts.py`.
- Keep the RAS Commander artifact service isolated from the other
  `gis.clbengineering.com` containers and services, even when they share the
  CLB-WebGIS physical host.
- Before changing deployment hosts, addresses, SSH routes, or storage paths,
  reread the current migration records under
  `H:/Backups/proxmox/CLB Router/`. Infrastructure references in older scripts
  may be stale during migration.

## Artifact Contract

- Use GeoParquet as the analysis/archive format for geometry and raw
  element-level result attributes.
- Use vector PMTiles for browser delivery of commonly reviewed geometry and
  queryable raw-result layers.
- Use `join_index` metadata to relate result tables to geometry without
  duplicating geometry in the archive layer.
- Generate visual result maps through RASMapper/RasProcess Stored Maps. Publish
  the numeric result as a COG and, where useful, a raster PMTiles display
  derivative with HTTP byte-range support.
- Do not present raw vector results as a continuous visual result surface. Raw
  vectors expose source-element values; RASMapper Stored Maps provide the
  interpolated raster visualization.
- Publish terrain as a numeric COG and optional PMTiles derivative with HTTP
  byte-range support.
- Preserve nodata as transparent in terrain and result display derivatives.

## Required Result Gate

Every public project must have a successfully computed plan and every
applicable result family populated:

1. **Vector Results** from raw HDF values joined to applicable cross sections,
   2D cells/faces, structures, pipes, and reference elements.
2. **Raster Results** generated from RASMapper Stored Maps. Every applicable
   plan must publish the complete standard set: Depth, WSE, Velocity, Froude
   Number, Shear Stress, Depth x Velocity, Depth x Velocity Squared, Arrival
   Time, Duration, Percent Time Inundated, and Inundation Boundary. This family
   is required for every 2D plan and every terrain-backed 1D plan.

A pure 1D source project that contains no RASMapper terrain must still publish
its computed raw cross-section results, but continuous Stored Map rasters are
not applicable. Record that capability explicitly in manifest v2; do not add a
substitute terrain or mislabel a derived surface as a RASMapper Stored Map.

Treat either of these public viewer messages as a failed publication:

```text
No RASMapper Stored Map rasters are published.
No raw HDF vector result layers are published.
```

Hold the project out of the public catalog until it runs successfully and both
result branches pass validation. Preserve plan, geometry, profile/time, units,
source HDF, map type, and interpolation authority in result metadata.

## Terrain Gate

- Discover every TIFF/VRT member associated with each named terrain.
- Consolidate all source members of one named terrain into one authoritative
  COG. Never merge distinct named terrain surfaces.
- Never upsample terrain. The published cell size must be at least 5 ft.
- If native cells are finer than 5 ft, use the smallest whole-number multiple of
  the native cell size that is at least 5 ft.
- If native terrain is already 5 ft or coarser, retain its native resolution,
  including terrain coarser than 10 ft.
- Mixed-native-resolution source sets require an explicit recorded target. Use
  a whole-number multiple of the coarsest native source grid so mixed 2-foot
  and 1-meter mosaics do not require an impractically coarse common multiple.
  Record every source resolution and resampling factor, and do not silently
  upsample any source during consolidation.
- When relocated RASMapper paths cannot be resolved, call ras2cng's
  `consolidate_terrain_files()` with the explicit priority-ordered TIFF list;
  do not replace the provenance-bearing pipeline with an ad hoc GDAL command.
- Preserve source priority, grid alignment, horizontal and vertical units and
  datums, resampling method, cutline, and source-file inventory.
- Build tiled, compressed COGs with statistics and overviews, and verify that
  nodata remains transparent in the browser derivative.
- Require an associated, queryable terrain COG for every 2D model.

## Viewer Defaults

- Enable hybrid satellite imagery and Model Extents on individual project maps.
- Enable terrain on individual 2D project maps, but not on the library landing
  map.
- Enable only the first/default geometry initially.
- For a 1D default geometry, enable rivers/reaches. For a 2D default geometry,
  enable breaklines and refinement regions where available.
- Keep large geometry, result, and optional derivative layers disabled unless
  they are required for the initial review view.

## Catalog Admission Checklist

Add projects one at a time only after all checks pass:

- source license permits publication;
- project CRS is valid and catalog bounds are valid WGS84;
- `HdfProject.get_project_extent(geometry_type="footprint")` produced the raw
  WGS84 model-limit polygon used by the catalog;
- at least one plan computed successfully;
- raw HDF vector results are populated, and RASMapper Stored Map rasters are
  populated for every 2D or terrain-backed plan;
- each 2D model has a consolidated, validated terrain COG;
- manifests use hosted URLs and contain no local paths;
- PMTiles and COG endpoints support HTTP range requests;
- large layers have sensible default visibility;
- desktop and mobile viewers open from the public docs URL;
- Identify distinguishes raw HDF values from RASMapper raster values;
- paired RASMapper/web review covers geometry, terrain, vector results, and
  raster results.

Do not add the 1D steady BLE collection to this landing page. Publish it later
as a separate consolidated map after its grouping, symbology, and metadata
contract is established.

## Current Expansion Priority

1. Populate terrain and Stored Map results for larger 2D releases.
2. Add eligible public model releases after CRS, license, result, terrain, and
   viewer validation.

Use the scripts in this directory for catalog creation, terrain preparation,
staging, and restricted WebGIS publication. Do not bypass the CLB03 staging and
publisher controls embedded in `publish_webgis_artifacts.py`.

After publishing a manifest v2 release with numeric COGs, install or upgrade the
bounded runtime inside CT230 with `provision_webgis_raster_service.sh`. Keep its
application listener on `127.0.0.1:8087`; CT230 Nginx and the docs-origin proxy
are the only public route to `/ras-raster/`.
Run `provision_rasdocs_raster_proxy.sh` inside CLB-Web01 CT210 and the active
serve-only rasdocs replica CT213 only after the CT230 health check passes. It
adds the path-scoped Caddy proxy without changing the existing `/data/*`
artifact route.
