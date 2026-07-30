# Native Land-Cover Authoring Findings

## Conclusion

Land-cover authoring must be delegated to the RasMapperLib shipped with the
target HEC-RAS generation. The former ras-commander path rasterized the source
with rasterio and reconstructed RAS-owned HDF datasets with h5py. Its files
could be opened and associated, but RasMapper sampled class `0` at every mesh
cell and the solver received one default Manning value.

`RasProcess.exe` does not expose a land-cover creation operation in the tested
5.0.7, 6.0, 6.6, or 7.0 builds. It remains useful for terrain and other
operations, but it is not the land-cover authoring backend.

## Native workflows recovered with RASDecomp

### HEC-RAS 5.0.7

1. Load 32-bit RasMapperLib in a process whose executable directory exposes
   the HEC 5 `GDAL` directory.
2. Set `SharedData.SRSFilename` from the project rasmap.
3. Create `LandCoverFile`, populate `ValueToOutput`, and call
   `SetInputToByteMap`.
4. Run the legacy `LandCoverComputable` with a
   `Dictionary<string, Tuple<byte, float>>`.
5. Register the raster in rasmap as `Type="LandCover"` with the `.tif`.
6. Associate it with `RASGeometry.LandCover = new LandCover(name, tif)`.
7. Run native property-table/plan computation.

Class IDs are bytes and therefore cannot exceed 255. The native sidecar has the
root arrays `IDs`, `Names`, and `ManningsN`. The geometry association points to
the TIFF, not the HDF.

### HEC-RAS 6.0 and newer

1. Load the selected RasMapperLib with pythonnet and initialize the project SRS.
2. Create `LandCoverFile`, populate `ValueToOutput`, and call `SetNameIDMap`.
3. Run `LandCoverComputable` with `LandCoverLayerHelper.ManningsN()`, parameter
   payload arrays, and payload-column indexes.
4. Require `Success()`.
5. Load with `LandCoverLayer.TryLoadLayer`, require non-null classification,
   parameters, and resampler, then call `Save()`.
6. Register `Type="LandCoverLayer"` with the `.hdf`.
7. Associate through `SetGeometryAssociationCommand`.
8. Run `ComputePropertyTablesCommand` and/or the plan.

The post-compute `Save()` is required: it performs the same V1-to-V2
normalization used by the RASMapper UI and produces compound `Raster Map` and
`Variables` datasets.

## Native raster invariants

Both qualified outputs are tiled GeoTIFFs, DEFLATE compressed, have overviews,
and declare no GDAL NoData value. Pixel `0` is a mapped RAS `NoData`
classification; declaring GDAL `nodata=0` made the former pipeline discard that
class and was one contributor to the collapse.

The former custom raster was striped, LZW compressed, lacked overviews, and
declared `nodata=0`. Matching only visible HDF datasets was insufficient because
RAS also depends on native raster/resampler and serialization conventions.

## End-to-end proof

The compact Muncie project is copied into a new disposable directory for every
version and processed through the public ras-commander APIs in a fresh Python
process:

- source:
  `G:\RasProcess Testing\wine_compare\Muncie_simple_test\Muncie.prj`
- plan/geometry: `p04` / `g04`
- flow area: `2D Interior Area`
- native authoring: `RasMap.add_landcover_layer`
- native association: `RasMap.associate_geometry_layers`
- final computation: `RasCmdr.compute_plan(..., force_rerun=True)`
- qualification-only structural check: private `_read_solver_arrays(...)`
- final audit: `HdfLandCover.audit_final_mannings_n`

Every row includes three completed plans:

1. native authoring and association baseline;
2. geometry base `Urban` Manning change from `0.10` to `0.11`;
3. `Qualification Probe` sidecar Manning change from `0.070` to `0.077`
   (native rebuild on 5.0.7).

The expected modern deltas are 1,418 cells / 11,248 face rows for the base
change and 36 cells / 314 face rows for the sidecar change. HEC-RAS 5.0.7 does
not emit the cell-center array, so its authoritative proof uses the same face
row deltas. Non-Manning face-table columns must remain byte-for-byte equal in
both edit scenarios.

The material values in both outputs are approximately `0.036`, `0.040`,
`0.054`, `0.060`, `0.072`, `0.080`, `0.090`, `0.100`, `0.120`, and `100`.
The value `100` is expected for this fixture: its source Building class uses
`n=10` and the existing regional calibration multiplies it by ten.

The result HDFs are marked `Complete Geometry=True`; exact hashes, raster class
counts, associations, message parsing, and cell/face deltas are recorded in the
version-matrix JSON evidence.

## Validation semantics

Dataset existence is not enough. The previous notebook gate counted 13
“distinct” values that were only `0.035000` versus `0.035003` floating-point
noise. The production audit now collapses values within `1e-4`, requires the
land-cover association, requires `Complete Geometry=True` by default, and
checks final face values. On 6.x it also reports cell-center values.

The qualification harness separately fails closed when its required face
arrays are missing or empty, and requires the cell-center array on 6.x and
newer. This niche structural contract remains private to the harness rather
than expanding the general `RasCmdr.compute_plan()` API.

HEC-RAS 5.x does not emit `Cells Center Manning's n`; its authoritative final
roughness is column four of `Faces Area Elevation Values`. HEC-RAS 6.x emits
both datasets.

Notebooks 212 and 213 are excluded from the published notebook catalog pending
replacement. Notebook 212's prior diversity assertion accepted floating noise,
and notebook 213 exercised a custom-HDF classification-polygon writer that is
now disabled pending a native `PolygonFeatureLayer` implementation. Notebook
213 did prove a narrow 6.6 simple-box workflow; it should not be described as a
complete failure. See `OPEN_QUESTIONS.md`.

## Geometry associations and overrides

The text `LCMann Table=<number>` value is the row count, not a table identifier.
The repaired base-table writer correctly preserves/updates that count. Native
geometry associations and existing regional overrides were present in both
qualified runs and explain the final scaled values. Neither the association
label nor the base override table caused the prior class-zero collapse.

Every version-matrix result uses the native association layer name
`LandCover`. HEC-RAS 5.0.7 associates the `.tif`; HEC-RAS 6.0 through 7.0
associate the `.hdf`. The former Python label `NLCD Land Cover` is not used.
