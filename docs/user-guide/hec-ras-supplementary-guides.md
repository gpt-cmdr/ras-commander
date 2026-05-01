# HEC-RAS Supplementary Guide Coverage

The official HEC-RAS Guides and Tutorials site includes a short Guides section for modeling techniques, RAS Mapper workflows, and troubleshooting notes. This page maps those supplementary guides to current ras-commander APIs and example notebooks so users can tell what is automated today and what still requires HEC-RAS or RAS Mapper.

Source: [USACE HEC-RAS Guides and Tutorials](https://www.hec.usace.army.mil/confluence/rasdocs/hgt/latest).

## Coverage Matrix

| Guide | ras-commander coverage | Current APIs and examples | Follow-up need |
|-------|------------------------|---------------------------|----------------|
| Downloading Terrain Data | Partial | `Usgs3depAws` discovers USGS 3DEP projects and downloads 1 m tiles; `RasTerrain.create_terrain_hdf()` creates RAS Terrain HDFs; `RasMap.add_terrain_layer()` registers terrain layers; notebook `examples/920_terrain_creation.ipynb` demonstrates the workflow. | Add 10 m/30 m direct download parity, product-table selection helpers, and a single documented acquisition-to-terrain workflow. |
| GDAL Projection File Warning | Documentation only | `RasMapValidation.check_layer_crs()` and `HdfBase.get_projection()` can inspect CRS metadata; `RasTerrain._generate_prj_from_raster()` can emit ESRI WKT from a raster CRS. | Keep as troubleshooting guidance. No notebook is needed. |
| Skip SRS Translation For Terrain Imports | Documentation only | `RasTerrain.create_terrain_hdf()` currently requires an explicit project `.prj`; ras-commander does not intentionally skip source-raster SRS translation. | Keep as a manual RAS Mapper workaround and document when not to automate it. |
| Export Channel Data for Terrain | Gap | `GeomCrossSection`, `HdfXsec`, and geometry parsers can read cross sections; `RasTerrain` can build terrain from rasters. | Add XS-to-GeoTIFF channel export and merge workflow before writing a notebook. |
| Re-projecting Model Geometry | Gap | ras-commander can read CRS metadata and validate layer CRS; eBFE helpers include targeted raster reprojection for delivery repair. | Add a public model-geometry reprojection API with preflight, backup, and post-conversion QA. |
| Creating a Terrain Dataset to Model a Flume Experiment | Partial | Synthetic raster creation can feed `RasTerrain.create_terrain_from_rasters()`; `RasTerrainModWriter` can create channel terrain modifications. | A focused notebook is feasible after the channel-export gap is resolved or with a raster-first synthetic terrain approach. |
| Modeling Steep Reaches | Partial | `RasPlan.update_plan_intervals()` adjusts computation/output intervals; `RasPlan` manages HDF output settings; `RasModPuls` supports a different 2D storage-outflow extraction workflow. | Add 1D Hydrologic Unsteady Routing / Modified Puls region setup and rating-curve import support if this RAS feature is in scope. |
| Aligning Cell Faces in Channels with Refinement Regions | Medium | `GeomMesh.add_refinement_region()`, `set_refinement_region_spacing()`, `set_breakline_spacing()`, and `generate()` support refinement regions and mesh regeneration when a current geometry HDF exists; notebook `examples/230_mesh_sensitivity_analysis.ipynb` covers mesh sensitivity and refinement management. | Add a flowline-buffer-to-refinement-region helper and a guide-specific notebook when mesh authoring coverage is stable. |
| Creating a Combined 1D/2D Model | Partial | `GeomLateral` and `RasGeometry` read lateral structures and SA/2D connections; `HdfMesh`, `HdfResultsMesh`, and `RasCheck` support 2D results and stability review; notebooks `examples/202_2d_plaintext_geometry.ipynb`, `410_2d_hdf_data_extraction.ipynb`, and `412_2d_detail_face_data_extraction.ipynb` cover parts of the review workflow. | Add connection-authoring or audit helpers before a full combined-model build notebook. |
| Modeling Weirs in 2D Areas | Gap | `GeomLateral` can read SA/2D connection profiles and gates; `HdfStruc` can list SA/2D connection results; `RasCheck` contains structure and velocity checks. | Add SA/2D connection and 2D internal weir creation/editing APIs, including overflow-method and mesh-placement QA. |

## CRS and SRS Troubleshooting Notes

RAS Mapper expects project projection files in an ESRI-compatible `.prj` form. When a raster or projection file carries CRS metadata that HEC-RAS cannot translate, first inspect the data outside the model and only then decide whether a manual RAS Mapper workaround is appropriate.

Recommended ras-commander checks:

```python
from ras_commander import RasMapValidation
from ras_commander.terrain import RasTerrain

RasMapValidation.check_layer_crs("terrain_source.tif", expected_epsg=5070)
RasTerrain._generate_prj_from_raster("terrain_source.tif", "Projection.prj")
```

Use the manual "skip SRS translation" workflow only when the raster is already in the intended project coordinates and the embedded SRS is missing or malformed. Do not use it to hide a real CRS mismatch; a bad mismatch will usually show up later as misplaced terrain, bad geometry associations, or failed 2D property-table extraction.

## Notebook Scope

The current notebook set already covers terrain creation, mesh sensitivity, terrain modifications, SA/2D parsing, 2D HDF extraction, and map-layer validation. New notebooks should be added only when the underlying API can perform the repeatable part of the guide without relying on manual GUI actions.

Candidate follow-up notebooks:

| Guide | Notebook scope |
|-------|----------------|
| Flume terrain | Build a small synthetic terrain from a raster, register it in RAS Mapper, and inspect the result. |
| Refinement-region cell alignment | Convert channel flowlines to buffered refinement regions, set spacing, regenerate mesh, and compare face alignment. |
| Combined 1D/2D model review | Audit lateral structures, terrain associations, mesh cells, time-step/HDF settings, and key stability outputs on a real example project. |
| 2D weir review | Inspect SA/2D connection profiles, mesh faces, max velocity, and submergence indicators once authoring/editing APIs exist. |
