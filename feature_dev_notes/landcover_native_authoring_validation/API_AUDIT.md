# Land-Cover and Manning API Audit

## Qualified and bounded public APIs

| API | Disposition | Evidence |
|---|---|---|
| `RasMap.add_landcover_layer` | Replaced custom raster/HDF construction with version-aware native `LandCoverComputable` | Live 5.0.7 and 6.6 Muncie authoring; raster and schema gates |
| `RasMap.associate_geometry_layers` | Replaced direct geometry-attribute writes with native association | 5.x `RASGeometry.LandCover`; 6.x `SetGeometryAssociationCommand`; final result attributes verified |
| `RasMap.get_hdf_geometry_association` | Retain read-only; corrected 2D-area discovery | Only HDF group children are treated as flow areas, so structural datasets such as `Cell Info`, `Polygon Points`, and `Attributes` no longer emit bogus association rows |
| `RasMap.recompute_property_tables` | Routes to the selected native RASMapper generation | Both version paths exercised as part of native geometry/plan processing |
| `GeomLandCover.replace_base_mannings_n` / `set_base_mannings_n` | Retain | Durable text geometry input; `LCMann Table` is correctly treated as row count |
| `GeomLandCover.set_region_mannings_n` | Retain | Durable text geometry input; existing regional overrides propagated in both final result HDFs |
| `HdfLandCover.get_preprocessed_mannings_n` | Retain read-only | Authoritative 6.x cell-center reader |
| `HdfLandCover.audit_final_mannings_n` | New production gate | Material-tolerance, association, complete-geometry, 5.x face, and 6.x cell/face checks |
| `HdfLandCover.set_landcover_mannings_n` | Native 6+ setter through `LandCoverLayer.TryAssigningNewParamtersUsingTable` | Native save and reload verified; 5.x fails closed because RAS exposes no native setter |
| `HdfLandCover.set_landcover_raster_map` | Deprecated working alias through v1.1.x | Delegates to `set_landcover_mannings_n()`; removal no earlier than v1.2.0 |
| `RasMap.add/update/delete_land_classification_polygon` | Native existing-class land-cover polygon CRUD for 6.x and 7.0.x | Native `PolygonFeatureLayer` save/reload; rollback and CRS gates; true multipart and interior rings fail closed before mutation |
| `HdfInfiltration.create_infiltration_override_regions` | Native geometry infiltration-region authoring for 6.x and 7.0.x | Scoped `InterpretationOverrideLayer.Save()` and fresh native readback |
| `HdfInfiltration.set_infiltration_base_overrides` / `scale_infiltration_base_overrides` | Native geometry-wide Base Override editing for 6.x and 7.0.x | Guarded exact private `ParameterSet` ABI; backup, rollback, native readback |
| `HdfInfiltration.get/set/scale_infiltration_region_overrides` | Native selected-region parameter-table access for 6.x and 7.0.x | Public `GetParameterTable` / `SetParameterTable`; Base Overrides and unselected regions preserved; interior rings fail closed |
| `HdfInfiltration.set_infiltration_sidecar_parameters` / `scale_infiltration_sidecar_parameters` | Native sidecar editing for 6+ | RASMapper parameter-table save and reload |

Native persistence alone proved insufficient for interior rings: HEC-RAS
6.0 through 7.0.1 reloads them correctly, but its classification resampler
converts the native polygon to a single-ring object and fills the hole.
Notebook 213 therefore gates the supported contract: add/update/delete,
one-member hole-free `MultiPolygon` normalization, true multipart and
interior-ring rejection before mutation, backup/report metadata, native
geometry association/property-table recomputation, completed plan computation,
and a material final Manning-array delta.

## Disabled or explicitly non-authoritative

| API | Disposition | Reason |
|---|---|---|
| `GeomLandCover.override_2d_mannings_n` | Disabled; raises `NotImplementedError` | Wrote generated `/Mann` solver output |
| `GeomPreprocessor.clear_geompre_hdf` | Deprecated guarded legacy-recovery wrapper through v1.1.x | Requires an exact 5.x/6.x file-version assertion and explicit acknowledgement; native recomputation is canonical |
| `HdfLandCover.compute_final_mannings_raster` | Deprecated alias | Python composition is useful for visualization but is not RASMapper's authoritative final layer |
| `HdfLandCover.estimate_final_mannings_raster` | Retained as estimate | Name and documentation now state the boundary |
| historical custom `set_landcover_raster_map` implementation | Removed from public path | Direct h5py sidecar edits bypass RASMapper save semantics |
| `RasMap` soils/infiltration polygon mutation | Read-only/fail closed | Native mutation and save did not return reliably; rebuild the applicable sidecar through native authoring instead |
| `RasMap` polygon new-class creation or class removal | Fail closed | Native save persisted partial artifacts but did not return reliably; rebuild the sidecar classification table |
| `HdfInfiltration.scale_infiltration_data` | Fail-closed compatibility name through v1.1.x | Historical input was ambiguous between geometry HDF and sidecar; explicit native replacements are provided for both |

These APIs “fail closed” because the public method now raises before mutation.
That is a production-safety disposition, not a claim that every prior test
failed. See `OPEN_QUESTIONS.md` for the narrower successful evidence and the
native replacements.

## Advanced solver-artifact utilities

**EXPERIMENTAL — not recommended for production or any other
non-experimental use.** These utilities have been tested only with HEC-RAS 7.0
April 2026 in the exact Windows-preprocess/Linux-solve workflow exercised by
notebook 414. Every other HEC-RAS version and execution workflow is untested.

The following canonical `HdfMesh` methods directly edit only the exact
HEC-RAS 7.0 Linux solver-temporary `HEC-RAS Results` `*.p##.tmp.hdf` artifact.
They are not land-cover authoring or general production-preprocessing
contracts:

- `write_linux_tmp_face_property_tables`
- `extend_linux_tmp_face_property_tables`
- `transform_linux_tmp_face_mannings_n`
- `sample_linux_tmp_face_mannings_n_from_landcover_curves`
- `set_mesh_pinned_attribute`

Each canonical operation validates the file family and schema, creates a full
backup, mutates, and reads back. The former broad names remain working
compatibility wrappers through v1.1.x, with removal no earlier than v1.2.0.

Notebook 414 provides a completed HEC-RAS 7.0 Windows-preprocess/Linux-solve
regression for the face-table extension workflow. Keep that proven slice as an
explicit advanced API with exact workflow guards. Other versions and direct
final-array mutation remain unqualified. No land-cover workflow introduced here
calls them.

## Related execution gates

`RasCmdr.compute_plan()` owns execution and optional solver-completion
verification. It does not accept workflow-specific raw HDF dataset contracts.
The qualification harness privately verifies its exact solver arrays, then
calls `HdfLandCover.audit_final_mannings_n` after the completed plan for the
semantic gate.

`RasProcess.compute_geometry` and `RasGeometryCompute.compute_geometry` use
legacy 1D completion heuristics that are insufficient for land-cover refresh
validation. The qualified path uses native association/property computation and
the completed plan HDF audit.

`RasProcess.exe` has no land-cover creation operation in the inspected 5.0.7,
6.0, 6.6, or 7.0 builds.

Soils and infiltration sidecar creation now use HEC-RAS 6.0+
`LandCoverComputable`; HEC-RAS 5.0.7 has no equivalent native system and fails
closed. Geometry infiltration override creation, geometry-wide Base Override
editing, and per-region parameter editing use the native
`InterpretationOverrideLayer` path described above. The native
create/save/readback gate is complete; notebook 218 separately qualifies
recomputed and final plan-HDF infiltration arrays.
