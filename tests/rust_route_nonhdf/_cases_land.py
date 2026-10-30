"""ROUTE-NONHDF cases: terrain, land classification, geometry association, RASMapper helpers.

Every case is read-only. Writers in these modules (association, sidecar authoring,
terrain-modification copy/export, infiltration clearing) are never called; their
read-only validation and inspection helpers are exercised instead (``helper`` names
the public workflow that needs HEC-RAS/.NET).
"""
from pathlib import Path

import h5py

from ._case import Case

SIDECAR = {"sidecar"}
GEOMETRY = {"geom", "plan"}


def _crs_text(crs):
    return None if crs is None else crs.to_wkt()


def _records(records):
    import shapely
    return [dict(r, geometry=shapely.to_wkb(r["geometry"])) for r in records]


def _has(path, *names):
    with h5py.File(path, "r") as f:
        return all(n in f for n in names)


def _ga():
    from ras_commander import _geometry_association
    return _geometry_association


def _lch():
    from ras_commander import _land_classification_helper
    return _land_classification_helper


def _lcn():
    from ras_commander import _landcover_native
    return _landcover_native


def _rch():
    from ras_commander import _rasmap_control_helper
    return _rasmap_control_helper


def _writer():
    from ras_commander.terrain.RasTerrainModWriter import RasTerrainModWriter
    return RasTerrainModWriter


def _sidecar_call(func, *required):
    def call(path):
        if required and not _has(path, *required):
            import pytest
            pytest.skip(f"fixture has no {required}")
        return func(Path(path))
    return call


def _validate_native_landcover(path):
    legacy = _has(path, "IDs")
    return _lcn().validate_native_landcover(Path(path), expected_class_ids=set(), legacy=legacy)


def _validate_native_landcover_classes(path):
    """Expect the layer's own class IDs (harness read) so the full validation runs."""
    with h5py.File(path, "r") as f:
        if "IDs" in f:
            legacy, ids = True, {int(v) for v in f["IDs"][()]}
        elif "Raster Map" in f:
            legacy, ids = False, {int(row["ID"]) for row in f["Raster Map"][()]}
        else:
            import pytest
            pytest.skip("fixture has no IDs or Raster Map")
    return _lcn().validate_native_landcover(Path(path), expected_class_ids=ids, legacy=legacy)


def _validate_registration(path):
    from ras_commander.terrain import _lossless_create
    return _lossless_create.validate_registration(Path(path), Path(path).with_suffix(".tif"))


def _terrain_features(path):
    from ras_commander import _terrain_modification_subset
    frame = _terrain_modification_subset.read_features(Path(path), "EPSG:4326")
    return frame


def _registered_terrain_source(path):
    from ras_commander.RasBenefits import RasBenefits
    return RasBenefits.get_registered_terrain_source(Path(path))


def _geometry_path(path):
    from ras_commander import _infiltration_override_native
    return _infiltration_override_native._geometry_path(Path(path))


def _sidecar_projection(path):
    from ras_commander import _land_classification_polygon_native as m
    return m._sidecar_projection(Path(path))


def _require_landcover(path):
    from ras_commander import _land_classification_polygon_native as m
    return m._require_landcover_sidecar(Path(path))


CASES = {
    # _geometry_association (read side of the association writers)
    "_geometry_association.validate_geometry_extents_for_2d_classification": Case(
        lambda p: _ga().validate_geometry_extents_for_2d_classification(Path(p)), kinds=GEOMETRY),
    "_geometry_association.read_geometry_association": Case(
        lambda p: _ga().read_geometry_association(Path(p), include_2d_area_attrs=True), kinds=GEOMETRY),
    "_geometry_association.read_geometry_association[raw]": Case(
        lambda p: _ga().read_geometry_association(Path(p), resolve_paths=False), kinds=GEOMETRY),
    "_infiltration_override_native._geometry_path": Case(
        _geometry_path, kinds=GEOMETRY, helper="set_infiltration_overrides (.NET)"),
    # _land_classification_helper
    "_land_classification_helper._read_raster_map_rows": Case(
        _sidecar_call(lambda p: _lch()._read_raster_map_rows(p), "Raster Map"), kinds=SIDECAR),
    "_land_classification_helper._read_layer_ids_for_symbology": Case(
        _sidecar_call(lambda p: _lch()._read_layer_ids_for_symbology(p)), kinds=SIDECAR),
    "_land_classification_helper._read_landcover_variable_lookup": Case(
        _sidecar_call(lambda p: _lch()._read_landcover_variable_lookup(p)), kinds=SIDECAR),
    "_land_classification_helper._classification_sidecar_crs": Case(
        _sidecar_call(lambda p: _crs_text(_lch()._classification_sidecar_crs(p))), kinds=SIDECAR),
    "_land_classification_helper.read_land_classification_polygon_records": Case(
        _sidecar_call(lambda p: _records(_lch().read_land_classification_polygon_records(p))), kinds=SIDECAR),
    "_land_classification_helper._read_infiltration_variable_rows": Case(
        _sidecar_call(lambda p: _lch()._read_infiltration_variable_rows(p), "Variables"), kinds=SIDECAR),
    "_land_classification_polygon_native._sidecar_projection": Case(_sidecar_projection, kinds=SIDECAR),
    "_land_classification_polygon_native._require_landcover_sidecar": Case(_require_landcover, kinds=SIDECAR),
    # _landcover_native (.NET authoring postconditions)
    "_landcover_native._validate_property_tables_postcondition": Case(
        lambda p: _lcn()._validate_property_tables_postcondition(Path(p)), kinds=GEOMETRY,
        helper="compute_property_tables (.NET worker)"),
    "_landcover_native.validate_native_landcover": Case(
        _validate_native_landcover, kinds=SIDECAR, helper="create_landcover (RASMapper)"),
    "_landcover_native.validate_native_landcover[classes]": Case(
        _validate_native_landcover_classes, kinds=SIDECAR, helper="create_landcover (RASMapper)"),
    # _rasmap_control_helper
    "_rasmap_control_helper.geometry_layer_bounds": Case(
        lambda p: _rch().geometry_layer_bounds(Path(p)), kinds=GEOMETRY),
    "_rasmap_control_helper.geometry_layer_bounds[lateral]": Case(
        lambda p: _rch().geometry_layer_bounds(Path(p), layer_type="LateralStructureLayer"), kinds=GEOMETRY),
    "_rasmap_control_helper.list_geometry_features": Case(
        lambda p: _rch().list_geometry_features(Path(p)), kinds=GEOMETRY),
    # terrain
    "_terrain_modification_subset.read_features": Case(_terrain_features, kinds=SIDECAR),
    "RasTerrainModWriter.list_modifications": Case(lambda p: _writer().list_modifications(Path(p)), kinds=SIDECAR),
    "RasTerrainModWriter._terrain_source_raster_paths": Case(
        lambda p: _writer()._terrain_source_raster_paths(Path(p)), kinds=SIDECAR,
        helper="RasTerrainModWriter.add_polygon_modification(elevation_method='boundary_from_terrain')"),
    "_lossless_create.validate_registration": Case(
        _validate_registration, kinds=SIDECAR, helper="RasTerrain lossless create (.NET CreateTerrain)"),
    "RasBenefits.get_registered_terrain_source": Case(_registered_terrain_source, kinds=SIDECAR),
}
