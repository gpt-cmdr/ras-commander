# Louisiana Watershed Initiative EnDMC

`LouisianaEndmc` reads the Louisiana Watershed Initiative (LWI)
[Environmental Data and Model Catalog](https://lwi.endmc.org) (EnDMC) and
downloads its public model and data files. EnDMC is operated by The Water
Institute. It catalogs HEC-RAS, HEC-HMS, HEC-FIA, and Go-Consequences model
applications and supporting datasets for the eight LWI regions.

No account is required. RAS Commander never logs in to EnDMC and accepts no
credentials for this source.

| Need | Public endpoint |
|---|---|
| Catalog | `GET https://lwi.endmc.org/search` with `Accept: application/json` (the request the public search page makes) |
| Software per resource | the same endpoint with `software=<id>` |
| Resource details | public page `https://lwi.endmc.org/view/<kind>/<id>` |
| Files | anonymous S3 `ListObjectsV2` and range `GET` on bucket `lwi-model-data` (us-east-1) |

Files live at `endmc-managed/{model_application|dataset}/{24-hex id}/`.
A dated snapshot of the public catalog fields (id, kind, title, software,
record date, keywords) ships with the package and is used automatically when
the live catalog is unreachable.

The executed example notebook
[932: Louisiana LWI EnDMC](../notebooks/932_louisiana_endmc_public_models.md)
walks through each step below on live public data.

## Browse the catalog

```python
from ras_commander.sources.state import LouisianaEndmc

catalog = LouisianaEndmc.list_resources()                 # model applications + datasets
ras = LouisianaEndmc.list_resources(software="HEC-RAS", region=2)
coastal = LouisianaEndmc.list_resources(search="coastal")  # site full-text search
offline = LouisianaEndmc.list_resources(source="snapshot")

details = LouisianaEndmc.get_resource_metadata("6a3d7158f74d9b1d5415493a")
details["fields"]["Coordinate system"], details["containing_packages"]
```

`region` is derived from titles and keywords (`"Region 5"`); a few
statewide or pilot resources have none. `date` is the record date from the
bundled snapshot; use `get_resource_metadata()` for resources published after
the snapshot. `list_s3_resource_ids()` inventories the bucket directly, which
can reveal prefixes that are not in the public catalog.

## Inspect a resource's files

```python
objects = LouisianaEndmc.list_objects("685d772c2ecdbd05b0cb03d1")
objects.groupby("component")["size"].sum().sort_values()
```

Each object is classified into one component:

| Component | Contents |
|---|---|
| `ras_project` | `.prj` project, `.p##`, `.g##`, `.u##`, `.f##`, `.rasmap`, `.u##.hdf` |
| `geometry_hdf`, `plan_hdf` | `.g##.hdf`, `.p##.hdf` |
| `ras_run_artifact` | `.b##`, `.bco##`, `.c##`, `.x##`, `.o##`, `.rst`, backups, snapshots, compute messages |
| `terrain`, `land_cover`, `infiltration` | rasters and RAS Mapper layer HDFs in terrain, land-cover, or soils folders |
| `output_depth`, `output_wse`, `output_velocity`, `output_raster_other` | flood output rasters and stored maps |
| `hms`, `dss`, `gis`, `docs`, `metadata`, `other` | HEC-HMS files, DSS, GIS layers, documents, catalog metadata, everything else |

Classification is a path heuristic tuned to the published deliveries. Raster
sidecars (`.aux.xml`, `.ovr`, `.tif.xml`) follow their raster. Review the
`other` rows before relying on a component filter for completeness.

## Download selected components

```python
result = LouisianaEndmc.download_resource(
    "6a3d7158f74d9b1d5415493a",
    r"H:\Testing\endmc\abbeville",
    components=["ras_project", "geometry_hdf", "terrain", "land_cover", "dss"],
    max_workers=4,
)
result["status"].value_counts(), result.attrs["receipt_path"]
```

- **Resumable.** Each file is assembled in `<name>.part`. Files larger than
  `chunk_size` (64 MiB) are fetched as parallel byte ranges, and completed
  ranges are recorded in `<name>.part.json`. Rerun the same call to resume.
  Ranges carry `If-Match` with the listed ETag, so a file replaced on the
  server restarts rather than mixing versions.
- **Verified.** Every file is checked against the listed byte length.
  `verify="checksum"` also compares the full-object checksum S3 stored at
  upload, using the algorithm the listing reports. Published objects carry
  CRC32 (verified with the standard library) or CRC64NVME (requires the
  optional `awscrt` package, `pip install awscrt`). Objects without a stored
  checksum fall back to size and are counted in `attrs["size_only"]`. S3 ETags
  for multipart uploads are not MD5 digests.
- **Receipt.** `_endmc_<resource_id>.json` in the destination records the key,
  size, ETag, modification time, status, and verification of each file.
- **Short paths.** Resource paths are already long. The default
  `max_path_length=240` refuses a download whose destination paths would leave
  no `MAX_PATH` headroom for HEC-RAS; choose a short destination such as
  `H:\Testing\endmc\<short-name>`.
- **Guards.** `dry_run=True` returns the plan with sizes. `max_bytes` refuses
  oversized selections; `download_model()` (the `ModelCatalog` entry point)
  defaults to a 50 GiB limit because design-storm resources exceed 400 GiB.

Measured throughput from one workstation (November 2026) was about 60 MB/s on
one stream and about 120 MB/s with four streams.

## Read rasters without downloading

```python
rasters = LouisianaEndmc.get_raster_urls("69fc95b64c0345e94060a3bc")
path = rasters.loc[rasters["component"] == "output_depth", "vsicurl"].iloc[0]

import rasterio
with rasterio.open(path) as src:          # HTTP range reads through GDAL
    print(src.crs, src.nodata, src.overviews(1))
```

`LouisianaEndmc.read_range(key, start, length)` returns raw bytes for any
object.

## Data notes

These observations describe published files reviewed in November 2026. They
are not library behavior; the library does not modify downloaded data.

- Region 2 online output rasters declare EPSG:6477 (NAD83(2011) Louisiana
  North, US survey feet), which matches their coordinates.
- Region 2 WSE and velocity rasters also carry a vertical CRS named
  "NAVD88 depth". That vertical component is not meaningful for velocity and
  should not be read as a datum statement for those values.
- Region 7 mosaicked rasters use a nodata value of about 3.4e38 (the float32
  maximum); mask it before computing statistics.
- Product sets differ by resource. A resource may publish representative
  events (for example seven Atlas 14 return periods at one duration) rather
  than every modeled scenario.
