# Example Project Library

<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.css">
<link rel="stylesheet" href="../../assets/stylesheets/ras-example-library.css?v=20260714Tlibrarytable01">

!!! warning "Under construction"
    The Example Project Library is moving to a RAS Commander MapLibre viewer
    backed by PMTiles and WebGIS-hosted artifacts. The current promotion set
    includes HEC examples, ScienceBase releases, and an eBFE/BLE delivery.

RAS Commander uses repeatable HEC-RAS project fixtures for examples, tests,
documentation, and regression checks. The library combines several source
families rather than treating one archive as the entire example set:

- HEC tutorial and example projects
- HEC special sample datasets
- publicly available USGS ScienceBase model releases
- organized FEMA eBFE/BLE deliveries
- other public state, county, and federal model catalogs as they are reviewed

HEC's example projects are instructional fixtures, not production studies. They
are still useful because they are the same projects that HEC-RAS tutorials and
manual examples are based on. Public ScienceBase and eBFE/BLE sources play a
different role: they expose real delivery structure, metadata, scale, path
issues, and model packaging details.

Only projects with a verified coordinate reference system are eligible for the
web map viewer. Projects without a CRS can remain useful for notebook examples,
but they are not published as map-review targets until their CRS is resolved.

<details class="ras-library-details" markdown="1">
<summary>ScienceBase model acquisition and validation details</summary>

`RasExamples` exposes only ScienceBase HEC-RAS archives explicitly promoted as
runnable. Every execution dependency must exist and be portable. Promotion
normally also requires a representative plan to complete a fresh
version-appropriate RAS Commander run (`RasCmdr` for HEC-RAS 6.x and
`RasControl` for legacy versions). A curator may explicitly accept a reviewed,
long-running archive without repeating a full compute; that exception and its
incomplete-compute evidence remain visible in catalog metadata. Listing the
catalog performs no network request and does not initialize or download the
standard example collection.

```python
from ras_commander import RasExamples

models = RasExamples.list_sciencebase_models()
```

Candidate and rejected releases are intentionally absent from that result. A
curator can review them with
`UsgsScienceBase.list_catalog_models(validated_only=False)`.

| Catalog entry | Model software | Promotion status | Evidence or blocker |
| --- | --- | --- | --- |
| [Kalamazoo River](https://www.sciencebase.gov/catalog/item/67a38201d34ee33d441d2f22) | HEC-RAS 6.6 | Validated | All 21 plans and dependencies resolve; fresh plan 44 run verified with zero compute-message errors or warnings |
| [Fox River Chain of Lakes](https://www.sciencebase.gov/catalog/item/661e9565d34e7eb9eb7e3ce4) | HEC-RAS 6.5 | Solver-ready; curator-accepted and promoted | The 12.0 GB archive is complete; an exact three-reference DSS repair leaves all 6 plans, 3 geometries, and 6 unsteady-flow files portable with zero missing-path issues. Plan 01 then ran under HEC-RAS 6.6 for 97.97 minutes, loaded every DSS boundary record, and produced zero errors or warnings before an intentional curator stop. The curator explicitly waived another multi-hour completion test; `compute_verified=False` remains visible in metadata |
| [Silver Creek / Scott AFB](https://www.sciencebase.gov/catalog/item/644c1526d34e45f6ddcd4a3a) | HEC-HMS 4.9 + HEC-RAS 6.5; validated with HEC-RAS 6.6 | Validated and promoted | The exact 68.5 GB archive was selectively extracted to its runnable RAS tree. A deterministic two-reference DSS repair and pruning of three unreferenced unsteady-flow entries leave 35 plans, 8 geometries, and 38 unsteady-flow files with zero path issues. Fresh plan 10 completed its 66-hour simulation with 0 errors, 0 warnings, and 0.001495% volume error |
| Squannacook River Crossings | HEC-RAS 6.x | Pending | Geometry archive has not yet passed the execution gate |
| [St. Joseph River](https://www.sciencebase.gov/catalog/item/584197dfe4b04fc80e518b6b) | HEC-RAS 4.1 | Validated after curated repair | The delivered final plan 24 is complete; pruning 42 stale project-index references leaves plan 24, geometry 18, and flow 01. A fresh forced `RasControl` run completed with zero compute-message errors or warnings and returned 588 result rows across 7 profiles and 84 locations |

The St. Joseph ZIP is retained unchanged. On extraction,
`download_sciencebase_model()` applies a narrowly registered repair to the
working copy: it removes plans 01–23 and geometries 01–17, 19, and 20 only when
those exact files are absent and the retained plan 24 dependencies exist. Any
different missing-file pattern is rejected instead of being guessed at. The
repair is idempotent.

The Fox River ZIP is also retained unchanged. Its registered working-copy repair
replaces exactly three references in unsteady-flow file 01 to use the USGS DSS
file that is present in the archive. The repair is rejected if the expected
reference count or delivered replacement file differs. After repair, all six
plans pass the portable-path audit. A controlled HEC-RAS 6.6 readiness run then
loaded all six April/May 2022 DSS records and sustained 97.97 minutes of stable
hydraulic computation with zero errors or warnings before an intentional stop.
The curator confirmed the archive runs and explicitly waived another multi-hour
completion test. Fox is therefore included by
`RasExamples.list_sciencebase_models()`, while its `solver_ready` status,
`compute_verified=False`, and full-compute caveat remain explicit.

Silver Creek uses the registry's reviewed `model_run_files/HEC-RAS_model`
archive prefix, so a normal `RasExamples` download extracts the runnable RAS
delivery rather than expanding the unrelated HMS meteorology payload. The
published 7-Zip archive remains unchanged. In the extracted working copy, the
registered repair redirects two stale March 23 DSS references to the updated
DSS delivered in the same archive and removes project-index entries for three
unreferenced unsteady files whose older DSS inputs were not delivered. The
post-repair audit found zero path issues across all 35 retained plans. Plan 10's
29 DSS boundary series all read successfully and cover the full simulation
window. A forced fresh HEC-RAS 6.6 run then completed the 66-hour simulation in
1.904 hours using the workstation's 8 available solver cores, with zero
compute-message errors or warnings and 0.3273 acre-ft (0.001495%) overall
volume error. Silver Creek is therefore included by
`RasExamples.list_sciencebase_models()`.

Fox and Silver Creek are public ScienceBase cloud attachments. They do not
require a ScienceBase account, but ScienceBase requires a browser CAPTCHA before
issuing each temporary large-file URL. `UsgsScienceBase.get_download_manifest()`
reports the official CAPTCHA page and exact local destination. After the CAPTCHA,
pass the temporary URL to `download_model(..., signed_download_urls={...})`, or
place the browser download at the reported destination. Downloads use the same
resumable `.part` workflow as eBFE deliveries and must match the authoritative
ScienceBase byte count. ZIP and 7-Zip deliveries are then safely extracted with
member-path and member-size checks; complete extractions are not repeated.

```python
from pathlib import Path
from ras_commander.sources.federal.usgs_sciencebase import UsgsScienceBase

download_root = Path(r"H:\Testing\USGS Sciencebase Models\ScienceBase Downloads")
manifest = UsgsScienceBase.get_download_manifest("fox-river", download_root)

# After completing the public CAPTCHA and copying its temporary URL:
temporary_url = "https://temporary-download-url-issued-by-sciencebase"
model_root = UsgsScienceBase.download_model(
    "fox-river",
    download_root,
    signed_download_urls={"model_archive.zip": temporary_url},
)

# If the browser downloaded the archive directly to the manifest destination,
# continue entirely offline without another ScienceBase request:
model_root = UsgsScienceBase.extract_local_model("fox-river", download_root)

# Preserve the published hierarchy and write MANIFEST.md plus agent audit files.
audit = UsgsScienceBase.organize_model("fox-river", download_root)
assert audit["paths_validated"]
```

After extraction, use `inspect_sciencebase_model()` to check plan, geometry,
flow, DSS, restart, gridded meteorology, terrain, land-classification, and
projection paths across every discovered HEC-RAS project. Then use
`validate_sciencebase_model()` with an explicit project and plan to force a fresh run
in an isolated output folder. The validator uses HDF verification for modern
HEC-RAS and fresh detailed compute messages for legacy HEC-RAS. Pending and
rejected candidates cannot be downloaded through the public `RasExamples`
facade.

SRH-2D, CE-QUAL-W2, and derived raster inundation collections are outside this
catalog regardless of whether their source archives are otherwise useful.

</details>

## Project Explorer

The explorer shows one model-limit polygon per promoted MapLibre project.
Click a polygon to review source metadata and open that project's webmap. The
table below is the same published catalog: each project name is linked once to
its viewer and the Project Information column summarizes the current bundle.
Projects stay out of this map until they have a valid CRS, a WGS84 model limit,
and a published MapLibre webmap.

<div class="ras-example-library" data-ras-example-library data-index="https://rascommander.info/data/rasexamples/hec-ras-7.0/example-projects.geojson?v=20260715Tterrainalpha01">
  <div class="ras-library-map-shell">
    <div class="ras-library-map" data-library-map></div>
  </div>
  <div class="ras-library-map-footer">
    <span data-library-status>Published MapLibre project extents</span>
    <span>Click a model extent to open its webmap.</span>
  </div>
  <div class="ras-library-table-wrap">
    <table class="ras-library-table">
      <thead>
        <tr>
          <th scope="col">Project</th>
          <th scope="col">Project Information</th>
          <th scope="col">Source</th>
          <th scope="col">CRS</th>
        </tr>
      </thead>
      <tbody data-project-table></tbody>
    </table>
  </div>
</div>

<script src="https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/pmtiles@4.3.0/dist/pmtiles.js"></script>
<script src="../../assets/javascripts/ras-example-projects-data.js?v=20260715Tterrainalpha01"></script>
<script src="../../assets/javascripts/ras-example-library.js?v=20260714Tlibrarytable01"></script>

## Related Workflows

- [Using RasExamples](../notebooks/100_using_ras_examples.md)
- [RASMapper Spatial Review](../notebooks/122_rasmapper_spatial_review.md)
- [Model Sources Showcase](../notebooks/958_model_sources_showcase.md)
- [Cloud-Native Geometry Export](../notebooks/960_cloud_native_geometry_export.md)
- [Cloud-Native Results Export](../notebooks/961_cloud_native_results_export.md)
- [Cloud-Native COG Results](../notebooks/962_cloud_native_cog_results_export.md)
- [Cloud-Native Export with ras2cng](../user-guide/cloud-native-export.md)
