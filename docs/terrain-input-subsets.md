# Lossless native terrain modification subsets

## Portable native verification helpers

`RasMap.create_terrain_sampling_map(source_mapper, terrain_hdf, projection_prj,
output_mapper)` writes a new export-only Mapper containing one unchanged native
terrain registration. It matches one unique terrain basename, repairs stale
source directory spellings in the sampling copy, and preserves modification
enable flags. The source Mapper/terrain remain read-only. Grid, CRS, units and
native modification records are unchanged. The output must not exist.

`RasMap.relocate_rasmap_assets(rasmap_path, assets)` updates only Filename
attributes in a caller-owned clone. Supplied asset basenames must be unique and
files must exist; duplicate names are rejected before mutation. Paths become
relative to the clone Mapper. Result-map profile and other parameters retain
their semantics. The return value lists changed elements and filenames.

`RasMap.audit_terrain_associations(rasmap_path, geometry_hdfs)` reads the final
material terrain/classification/projection references and native geometry
association attributes. It returns `status: pass|hold`, registered terrain
names, every material path's existence and relative state, problems, and stale
result-map terrain names. It changes no files or coordinates. Unrelated display
layers and missing parent result files are outside this terrain-specific audit.
A pass after the complete bundle is renamed verifies portability of the
relative material links; it is not hydraulic approval.

FIM's exact native verification uses the existing public
`RasTerrain.export_rasmapper_terrain` for parent/child/base exports and
`RasTerrainMod.get_terrain_profile` for retained complete modification profiles.
Source-derived crops require their original 256-pixel tile phase and the
H5Assist-compatible chunked modification writer. No polygon record is truncated
or dropped to make a subset succeed. Polygon/native singleton-profile cases
remain explicit qualification holds.

These experimental boundary APIs support native polyline/profile modification
records. Polygon and unknown layouts raise `ValueError`; they are never silently
omitted. Native replay and engineering acceptance require project qualification.
Synthetic tests establish record preservation, not native hydraulic equivalence.

```python
from ras_commander import RasMap
from ras_commander.terrain import RasTerrain, RasTerrainModWriter

features = RasTerrainModWriter.get_modification_features(source_hdf, terrain_crs)
# CRS must be the terrain CRS. support_distance uses its horizontal units.
footprints = features.geometry.buffer(features.support_distance)
selected = features.loc[footprints.intersects(buffered_domain)]
indexes = selected.groupby("group_name").feature_index.apply(list).to_dict()
# Keep complete feature geometry; expand terrain support for crossing features.
RasTerrainModWriter.export_modification_features(
    source_hdf, source_mapper, new_bundle_dir, indexes
)
RasTerrain.create_terrain_hdf(
    precut_source_tiffs, child_hdf, projection_prj,
    units="Feet", stitch=True, hecras_version="6.6"
)
# Only on a versioned child clone; source files remain immutable.
RasMap.remove_terrain_layers(child_mapper)
RasMap.add_terrain_layer(child_hdf, rasmap_path=child_mapper, layer_name="Child")
local_indexes = {name: list(range(len(ids))) for name, ids in indexes.items() if ids}
RasTerrainModWriter.copy_modification_features(
    new_bundle_dir / "modifications.hdf", child_hdf,
    new_bundle_dir / "modifications.rasmap", child_mapper, local_indexes
)
RasMap.reassign_result_map_terrains(
    child_mapper, {"Source": "Child", "Source.Modified": "Child"}
)
for child_geometry in child_geometry_hdfs:
    RasMap.set_geometry_association(child_geometry, terrain_hdf_path=child_hdf)
```

`terrain_modification_features` is registered in `ras_commander.schemas`.
Its exact columns are `group_name` (native group), `feature_index` (zero-based
Attributes row), `support_distance` (Max Reach/Max Extent in horizontal CRS units),
and `geometry` (complete LineString/MultiLineString, or Point for a native
single-vertex record). The caller supplies the CRS;
there is no reprojection or inference. Empty frames keep their columns and CRS.

Export creates a new folder with `modifications.hdf` and `modifications.rasmap`.
The HDF contains source root metadata and complete selected native modification
records, without terrain grid/index data. This is a method-native boundary input,
not an executable terrain. Copy preserves native feature order, structured
attributes, coordinates, profiles, priorities, enabled flags, dataset values,
dtypes and HDF attributes. Nonempty native tables are recreated with the shared
writer's H5Assist-compatible chunked storage; empty tables use its existing
fallback. Physical storage layout is not preserved. These storage checks do not
establish native terrain identity.
It rewrites compact feature-level point/part/profile offsets and Mapper filenames
only. Polyline Parts offsets remain feature-local and byte-preserved. Caller
indexes must be unique integers; unknown groups and invalid offsets fail.
Existing output folders and destination modifications are refused. Failed copies
restore the destination pair; completed export uses an atomic folder rename.
This is single-writer mutation, not a concurrent transaction or crash-recovery
protocol. The caller must isolate and claim its destination.

`remove_terrain_layers` changes only terrain registrations in the supplied Mapper
XML and returns removed names. It leaves geometry/plan registrations and all asset
files intact. It does not update geometry HDFs. The caller explicitly registers
the replacement and reassigns every geometry referenced by plans, then verifies
native readback. These methods never convert elevations or units.

`reassign_result_map_terrains(rasmap_path, terrain_names)` replaces exact terrain
names in result-map `MapParameters.Terrain` attributes and calculated-layer
`Terrain.Name` attributes. Supply an explicit old-to-new dictionary; every new
name must already be registered. Other map parameters, formulas, result/plan
filenames and geometry associations remain unchanged. The helper validates the
complete mapping before mutation, atomically writes the Mapper clone only when
references change, and returns records containing `plan_name`, `element`,
`attribute`, `old_terrain_name` and `new_terrain_name`. Repeating the same mapping
returns an empty list and preserves the file bytes. Geometry HDF associations
still require `set_geometry_association`; this helper never opens plan-result HDFs.

Source Mapper lookup prefers exactly one resolved path. If none matches, a single
basename registration may support a caller-verified stale delivered layout; its
source bytes/provenance must be verified by the caller. Multiple exact or fallback
matches fail before mutation. Destination lookup requires one exact path.
Returned decisions record source registration name and matching basis. The reader
supports exactly the six native Attributes/Polyline Info/Parts/Points/Profile
Info/Values tables; extra native tables fail pending an explicit supported layout.

Native single-vertex polyline records return Point support geometry for conservative
selection, preserving the complete original native record. They are not repaired
or promoted to valid channel lines; native execution may still reject a retained
record. Mixed multipart lines containing isolated single vertices are unsupported.


For a cloned bundle whose terrain is beside the project folder, register it with
`RasMap.add_terrain_layer(..., relative_paths=True)`. This keeps same-drive terrain
and projection references relative, including sibling folders, so renaming the
run's temporary folder does not invalidate its Mapper. Different-drive assets
keep absolute references. This option does not change geometry associations;
set those separately and verify the finalized bundle.

`RasMap.create_terrain_sampling_map(..., geometry_hdf=None)` creates a new
isolated Mapper without geometry by default. Supplying an existing caller-owned
geometry copy registers it for native profile sampling; source files are never
changed. `RasMap.audit_terrain_associations(mapper, geometry_hdfs)` requires at
least one geometry and checks each terrain association resolves to a registered
native terrain HDF. Missing, wrong-but-existing, absolute, or unresolved material
paths hold; result-map names must also be registered. This read-only audit does
not qualify elevations or hydraulic acceptance.
# Terrain import dependencies

Terrain creation, modification inspection and replay do not load the USGS
downloader. `Usgs3depAws` and `TerrainBuildError` remain public class exports and
load their downloader module on first access. That module requires `requests`;
an absent HTTP dependency produces an actionable import error when the downloader
is requested, without blocking local terrain operations.

