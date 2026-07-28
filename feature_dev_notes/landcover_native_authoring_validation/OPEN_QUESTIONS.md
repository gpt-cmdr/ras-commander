# Open Questions and API Dispositions

## What “fail closed” means

“Fail closed” means the public method raises `NotImplementedError` before it
changes a project. It does **not** mean every historical implementation was
proven incapable of working. It means the current public name promised more
safety, portability, or solver authority than the evidence supported.

The dispositions below separate four different cases that were previously
grouped together too broadly.

## Direct generated `/Mann` writes

`GeomLandCover.override_2d_mannings_n` edited an existing generated `/Mann`
column in a geometry HDF. The investigation found no completed-plan proof that
HEC-RAS consumed that edit, preserved it through a native property-table
rebuild, or produced the intended final cell and face arrays.

The production replacement is not another final-array writer:

1. edit the native land-cover parameter table or a durable geometry Manning
   input;
2. ask RASMapper/HEC-RAS to recompute property tables;
3. run the plan;
4. verify the final cell and face Manning arrays.

The old method therefore remains disabled under its production-sounding name.
If retained for forensic work, it should return under an explicitly unsafe,
private API with backups and read-back validation.

RASDecomp found no public or internal RasMapperLib setter for the final cell or
face Manning arrays in 5.0.7 through 7.0.

## Selective geometry-HDF deletion

`GeomPreprocessor.clear_geompre_hdf` was not wholly nonfunctional. Executed
notebook 213 showed that deleting a known set of 12 cached datasets in a
HEC-RAS 6.6 Bald Eagle fixture forced a rebuild and changed 2,740 of 19,597
cell Manning values.

That proof was narrow. The deleted paths are schema-version-dependent, the
operation is not transactional, and an interrupted or incomplete rebuild can
leave an apparently readable but inconsistent geometry HDF.

RASDecomp identified native invalidation/rebuild operations:

- 5.0.7 through 7.0:
  `SetPinnedPropertyTables(false)` followed by
  `EnsurePropertyTables(forceRecompute=true, ...)`;
- 6.3.1 and newer:
  `CleanPropertyTables()` or `CleanPropertyTables(meshIdx)`, then native
  recomputation;
- all versions:
  `ComputePropertyTablesCommand.Execute(...)` performs a forced native
  recompute.

Those operations replace the routine need for selective dataset deletion.
Direct deletion still has a place as an explicit legacy-recovery/forensic tool,
but not as the default invalidation contract. Deleting a classification polygon
is a separate operation and should use native feature-layer CRUD.

`clear_geompre_files` remains supported for deleting legacy `.c##` geometry
preprocessor files. Its lost decorators were restored during this exercise.

## Classification-polygon mutation

The old custom classification-polygon writer also was not wholly
nonfunctional. Notebook 213 added two simple box overrides in HEC-RAS 6.6,
rebuilt the property tables, and changed final cell Manning values.

It was nevertheless underqualified:

- only add was proved, not update/delete;
- only simple boxes were proved, not holes or multipart geometries;
- only one HEC-RAS version and one project were proved;
- it wrote an HDF attribute column named `Classification`, while the native
  feature table uses `Name`;
- it coupled feature-table edits to direct HDF cache deletion.

Pythonnet can replace this custom writer. In HEC-RAS 6.0 and newer,
`LandCoverLayer.Nodes[0]` is a
`LandCoverClassificationLayer` that can be treated as the public
`PolygonFeatureLayer`. Its public workflow is:

1. `StartEditing()`;
2. `AddFeature(Polygon)`, `DeleteFeature(fid)`, or geometry update;
3. `SetFeatureName(fid, className)`;
4. `SaveFeatureTable()`;
5. `StopEditing(true)`;
6. native property-table recompute and completed-plan verification.

Geometry Manning regions are even more direct:
`RASGeometry.LandCoverRegions` is a public `ManningsNPolygonLayer` from 5.0.7
forward and exposes feature CRUD plus `SetLandCoverMapping`.

Recommended input rule: accept exactly one polygonal feature per operation.
A `MultiPolygon` with one nonempty member may be normalized to `Polygon`;
multiple nonempty members must be rejected with a clear error.

Resolved by final-array qualification: although native persistence retains
interior rings, HEC-RAS 6.0 through 7.0.1 flattens them in the land-cover
classification resampler and fills the hole. Add/update therefore reject
interior rings before mutation. List/read stays hole-aware. CRS,
invalid/self-intersecting geometry, missing class names, rollback, and
add/update/delete are covered by the native and runtime gates.

## Soils and infiltration sidecars

This question is resolved for native layer creation, sidecar parameter
editing, and geometry infiltration overrides in HEC-RAS 6.0 and newer.
Pythonnet/RASMapper is now the production path:

- native `LandCoverFile` and `LandCoverComputable`;
- `DefaultSoils()`, `DefaultInfiltration()`, `InfiltrationDC()`,
  `InfiltrationSCS()`, and `InfiltrationGA()` helpers;
- native `LandCoverType.Soils` / infiltration types;
- `LandCoverLayer.TryLoadLayer(...)`, parameter-table assignment, `Save()`,
  reload, and verification;
- `RASGeometry.InfiltrationOverrideRegions` and
  `PercentImperviousOverrideRegions` for geometry overrides.

The former ambiguous `HdfInfiltration.scale_infiltration_data()` name now
fails before mutation and identifies three explicit replacements:
geometry-wide `scale_infiltration_base_overrides()`, selected-region
`scale_infiltration_region_overrides()`, and sidecar
`scale_infiltration_sidecar_parameters()`. Deprecated historical spellings
remain working wrappers through v1.1.x. Runtime selection is exact and rejects
a process that has already loaded a different RasMapper assembly.

Native creation/save/reload was exercised in fresh HEC-RAS 6.0, 6.6, and 7.0
processes. Notebook 218 supplies the end-to-end HEC-RAS 7.0 final geometry and
plan-array gate for geometry-wide Base Overrides plus a named regional table.
HEC-RAS 5.0.7 has no native hydrologic soils/infiltration sidecar or geometry
override system and remains intentionally unsupported.

`SedimentSoilsFilename` is sediment bed material, not the hydrologic soils
layer, and must not be used as a substitute.

The remaining open surface is soils/infiltration **classification-polygon
CRUD**. Its native save did not return reliably, so those polygon mutations
fail closed. This does not limit the qualified native layer creation,
parameter-table setters, or geometry infiltration-region APIs above.

## Direct `HdfMesh` solver-array writers

**EXPERIMENTAL — not recommended for production or any other
non-experimental use.** The only tested contract is HEC-RAS 7.0 April 2026 in
notebook 414's Windows-preprocess/Linux-solve temporary-HDF workflow. All other
versions and workflows are untested.

These utilities are not all “broken.” Executed notebook 414 proved a narrow,
important workflow in HEC-RAS 7.0:

- 11,164 face property tables edited;
- 440,633 rows added;
- the Linux solver completed;
- 487,688 output rows were preserved;
- 4,890 of 5,391 active cells changed water surface elevation by more than
  0.001 ft.

That is valid evidence for the exact 7.0 Windows-preprocess/Linux-solve
two-phase workflow. It is not evidence for generic land-cover authoring,
all-version Windows use, or arbitrary direct final-array mutation.

Disposition:

- keep the proven functions as explicit advanced/research APIs;
- require `.tmp.hdf`, exact version/workflow guards, backup, schema checks,
  read-back, and solver regression;
- do not call them from routine land-cover, soils, or infiltration workflows;
- use the canonical `set_mesh_pinned_attribute()` name; retain
  `pin_property_tables()` only as a deprecated compatibility wrapper;
- keep the equal-class curve sampler explicitly named
  `sample_linux_tmp_face_mannings_n_from_landcover_curves()` and documented as
  a class-presence heuristic. Its historical
  `recompute_face_mannings_n_from_landcover_curves()` name remains a deprecated
  wrapper; length/fraction or conveyance weighting is still required before a
  broader production claim.

Pythonnet cannot currently replace final solver-array setters because
RASMapperLib exposes no equivalent setter. Pythonnet **can** replace the
upstream inputs: sidecar parameters, classification polygons, geometry
override regions, and property-table lifecycle.

## Compute result semantics

`RasCmdr.compute_plan(required_hdf_datasets=...)` now prevents a successful
return when specifically requested final arrays are missing or empty. The
qualification matrix found the inverse legacy edge case in 6.0: the plan HDF
ended in `Complete Process` and contained every requested array, but the
message parser treated the nonfatal line
`WRITE ATTR ERROR: ... River Edge Lines not found` as a fatal compute error.

The matrix therefore records three independent facts:

- launcher return/result;
- `Complete Process` plus structural HDF completion;
- exact required final datasets plus semantic Manning deltas.

The parser now treats that exact completed-run 6.0 line as a nonfatal
exclusion; the required-array gate remains unchanged.
