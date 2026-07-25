# Land-Cover and Manning API Audit

## Production-qualified

| API | Disposition | Evidence |
|---|---|---|
| `RasMap.add_landcover_layer` | Replaced custom raster/HDF construction with version-aware native `LandCoverComputable` | Live 5.0.7 and 6.6 Muncie authoring; raster and schema gates |
| `RasMap.associate_geometry_layers` | Replaced direct geometry-attribute writes with native association | 5.x `RASGeometry.LandCover`; 6.x `SetGeometryAssociationCommand`; final result attributes verified |
| `RasMap.recompute_property_tables` | Routes to the selected native RASMapper generation | Both version paths exercised as part of native geometry/plan processing |
| `GeomLandCover.replace_base_mannings_n` / `set_base_mannings_n` | Retain | Durable text geometry input; `LCMann Table` is correctly treated as row count |
| `GeomLandCover.set_region_mannings_n` | Retain | Durable text geometry input; existing regional overrides propagated in both final result HDFs |
| `HdfLandCover.get_preprocessed_mannings_n` | Retain read-only | Authoritative 6.x cell-center reader |
| `HdfLandCover.audit_final_mannings_n` | New production gate | Material-tolerance, association, complete-geometry, 5.x face, and 6.x cell/face checks |
| `HdfLandCover.set_landcover_raster_map` | Reimplemented for 6+ through `LandCoverLayer.TryAssigningNewParamtersUsingTable` | Native save and reload verified; 5.x fails closed because RAS exposes no native setter |

## Disabled or explicitly non-authoritative

| API | Disposition | Reason |
|---|---|---|
| `GeomLandCover.override_2d_mannings_n` | Disabled; raises `NotImplementedError` | Wrote generated `/Mann` solver output |
| `GeomPreprocessor.clear_geompre_hdf` | Disabled; raises `NotImplementedError` | Selective deletion can leave internally inconsistent geometry HDFs |
| `HdfLandCover.compute_final_mannings_raster` | Deprecated alias | Python composition is useful for visualization but is not RASMapper's authoritative final layer |
| `HdfLandCover.estimate_final_mannings_raster` | Retained as estimate | Name and documentation now state the boundary |
| historical custom `set_landcover_raster_map` implementation | Removed from public path | Direct h5py sidecar edits bypass RASMapper save semantics |
| `RasMap.add/update/delete_land_classification_polygon` | Disabled | Former implementation hand-authored `Classification Polygons`, `Raster Map`, and `Variables`; read-only listing remains |

## Advanced solver-artifact utilities

The following `HdfMesh` methods directly edit solver-owned arrays and are not
qualified as land-cover authoring or production preprocessing contracts:

- `set_mesh_face_property_tables`
- `extend_face_property_tables`
- `set_face_mannings_n_values`
- `recompute_face_mannings_n_from_landcover_curves`
- `pin_property_tables`

They should remain isolated as explicit research/forensic utilities until each
has an end-to-end HEC-RAS regression fixture. No land-cover workflow introduced
here calls them.

## Related execution gates

`RasCmdr.compute_plan(required_hdf_datasets=...)` verifies that requested arrays
exist and are nonempty. It cannot prove that classifications or Manning values
are hydraulically meaningful. Call `HdfLandCover.audit_final_mannings_n` after
the completed plan for the semantic gate.

`RasProcess.compute_geometry` and `RasGeometryCompute.compute_geometry` use
legacy 1D completion heuristics that are insufficient for land-cover refresh
validation. The qualified path uses native association/property computation and
the completed plan HDF audit.

`RasProcess.exe` has no land-cover creation operation in the inspected 5.0.7,
6.0, 6.6, or 7.0 builds.

The existing soils and infiltration creation paths also construct sidecars in
Python and are not qualified by this land-cover exercise. They are follow-up
candidates for the same version-aware `LandCoverComputable` adapter and should
not be presented as solver-qualified until they have equivalent final-result
gates.
