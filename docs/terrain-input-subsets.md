# Lossless native terrain modification subsets

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
attributes, coordinates, profiles, priorities, enabled flags and dataset metadata.
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
