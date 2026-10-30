"""Tiny HDF format regressions for stored velocity qualification and fallback.

The controlled arrays expose schema edge cases absent from official examples.
Real Davis geometry/result comparisons are recorded in the implementation report.
"""
import importlib

import h5py
import numpy as np
import pytest

q = importlib.import_module("ras_commander.hdf.HdfResultsQuery")
TIME = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


def write_velocity_hdf(path, meshes=("Area",)):
    with h5py.File(path, "w") as f:
        f.create_dataset(f"{TIME}/Time", data=[0., 1., 2.])
        f.require_group("Geometry").attrs["SI Units"] = False
        for mesh in meshes:
            g = f.require_group(f"Geometry/2D Flow Areas/{mesh}")
            # One physical cell, one ghost: reconstruction has orthogonal faces.
            g.create_dataset("Cells Center Coordinate", data=[[0., 0.], [1., 0.]])
            g.create_dataset("Cells Face and Orientation Info", data=[[0, 2], [0, 2]])
            g.create_dataset("Cells Face and Orientation Values", data=[[0, 1], [1, 1]])
            g.create_dataset("Faces Cell Indexes", data=[[0, -1], [0, -1]])
            g.create_dataset("Faces NormalUnitVector and Length", data=[[1., 0., 1.], [0., 1., 1.]])
            r = f.require_group(f"{TIME}/2D Flow Areas/{mesh}")
            r.create_dataset("Face Velocity", data=np.tile([6., 8.], (3, 1)))
    return path


def add_component(path, axis, value, *, stored=True, mesh="Area"):
    name = ("Cell Velocity - " if stored else "") + f"Velocity {axis}"
    with h5py.File(path, "r+") as f:
        d = f.create_dataset(f"{TIME}/2D Flow Areas/{mesh}/{name}", data=np.full((3, 2), value, dtype=float))
        if stored:
            d.attrs["Location"] = "Cells"
            d.attrs["Units"] = "ft/s"


def cache(meshes=("Area",)):
    return {"mesh_order": list(meshes), "mesh_slices": {m: slice(i, i + 1) for i, m in enumerate(meshes)}}


def values(path, variable="Velocity", meshes=("Area",)):
    return q._get_unsteady_variable_values(path, cache(meshes), variable, 1, path)


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("missing", ["X", "Y"])
@pytest.mark.parametrize("legacy", ["complete", "absent", "X", "Y"])
def test_incomplete_stored_pair_never_mixes_sources(tmp_path, missing, legacy):
    path = write_velocity_hdf(tmp_path / "partial.p01.hdf")
    present = "Y" if missing == "X" else "X"
    add_component(path, present, 4 if present == "Y" else 3)
    for axis, value in (("X", 30), ("Y", 40)):
        if legacy == "complete" or legacy == axis:
            add_component(path, axis, value, stored=False)
    expected = 50 if legacy == "complete" else 10
    np.testing.assert_allclose(values(path), [expected])
    # A direct single-axis request can still use its qualified stored component.
    np.testing.assert_allclose(values(path, f"Velocity {present}"), [4 if present == "Y" else 3])


@pytest.mark.synthetic_hdf_layout
def test_complete_stored_pair_wins_and_trims_ghosts(tmp_path):
    path = write_velocity_hdf(tmp_path / "complete.p01.hdf")
    for axis, stored, legacy in (("X", 3, 30), ("Y", 4, 40)):
        add_component(path, axis, stored)
        add_component(path, axis, legacy, stored=False)
    for variable, expected in (("Velocity", 5), ("Velocity X", 3), ("Velocity Y", 4)):
        np.testing.assert_allclose(values(path, variable), [expected])


@pytest.mark.synthetic_hdf_layout
def test_multiple_meshes_select_complete_sources_independently(tmp_path):
    meshes = ("Stored", "Legacy", "Faces")
    path = write_velocity_hdf(tmp_path / "multi.p01.hdf", meshes)
    for axis, value in (("X", 3), ("Y", 4)):
        add_component(path, axis, value, mesh="Stored")
        add_component(path, axis, value * 10, stored=False, mesh="Legacy")
    add_component(path, "X", 99, mesh="Legacy")
    add_component(path, "Y", 99, mesh="Faces")
    np.testing.assert_allclose(values(path, meshes=meshes), [5, 50, 10])
    vx, vy = q._get_cell_velocity_components(path, path, cache(meshes), 1, False)
    np.testing.assert_allclose(vx, [3, 30, 6])
    np.testing.assert_allclose(vy, [4, 40, 8])


def replace_schema(path, target, schema):
    with h5py.File(path, "r+") as f:
        del f[target]
        if isinstance(schema, str) and schema == "group":
            f.create_group(target)
        else:
            f.create_dataset(target, data=schema)


@pytest.mark.parametrize("schema", [np.zeros((3, 2)), np.array([b"0", b"1", b"2"]), np.array(0.), "group", np.arange(2), np.array([True, False, True]), np.zeros(3, dtype=complex)], ids=["rank2", "text", "scalar", "group", "length", "bool", "complex"])
def test_malformed_time_refused(tmp_path, schema):
    path = write_velocity_hdf(tmp_path / "time.p01.hdf")
    add_component(path, "X", 3)
    add_component(path, "Y", 4)
    replace_schema(path, f"{TIME}/Time", schema)
    with pytest.raises(ValueError, match="Time|time"):
        values(path)


@pytest.mark.parametrize("schema", [np.zeros(2), np.zeros((2, 1)), np.zeros((2, 2, 1)), np.full((2, 2), b"0"), "group", np.zeros((3, 2))], ids=["rank1", "width1", "rank3", "text", "group", "count"])
def test_malformed_cell_geometry_refused(tmp_path, schema):
    path = write_velocity_hdf(tmp_path / "geometry.p01.hdf")
    add_component(path, "X", 3)
    add_component(path, "Y", 4)
    replace_schema(path, "Geometry/2D Flow Areas/Area/Cells Center Coordinate", schema)
    with pytest.raises(ValueError, match="cell|geometry"):
        values(path)


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("legacy", [True, False])
def test_invalid_incomplete_stored_schema_cannot_hide_behind_fallback(tmp_path, legacy):
    path = write_velocity_hdf(tmp_path / "invalid.p01.hdf")
    add_component(path, "X", 3)
    with h5py.File(path, "r+") as f:
        f[f"{TIME}/2D Flow Areas/Area/Cell Velocity - Velocity X"].attrs["Location"] = "Faces"
    if legacy:
        add_component(path, "X", 30, stored=False)
        add_component(path, "Y", 40, stored=False)
    with pytest.raises(ValueError, match="Location"):
        values(path)


@pytest.mark.synthetic_hdf_layout
def test_face_only_reconstruction_unchanged(tmp_path):
    path = write_velocity_hdf(tmp_path / "faces.p01.hdf")
    for variable, expected in (("Velocity", 10), ("Velocity X", 6), ("Velocity Y", 8)):
        np.testing.assert_allclose(values(path, variable), [expected])


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("axis", ["X", "Y"])
@pytest.mark.parametrize("attribute,value", [("Location", "Faces"), ("Location", ["Cells", "Cells"]), ("Units", "mph"), ("Units", ["ft/s", "ft/s"])])
def test_invalid_stored_metadata_refused_for_vector_and_direct_axis(tmp_path, axis, attribute, value):
    path = write_velocity_hdf(tmp_path / "metadata.p01.hdf")
    add_component(path, "X", 3)
    add_component(path, "Y", 4)
    with h5py.File(path, "r+") as f:
        f[f"{TIME}/2D Flow Areas/Area/Cell Velocity - Velocity {axis}"].attrs[attribute] = value
    for variable in ("Velocity", f"Velocity {axis}"):
        with pytest.raises(ValueError):
            values(path, variable)


@pytest.mark.parametrize("schema", [np.ones(3), np.full((3, 2), b"3"), "group"])
def test_invalid_present_component_dataset_refused(tmp_path, schema):
    path = write_velocity_hdf(tmp_path / "component.p01.hdf")
    add_component(path, "X", 3)
    replace_schema(path, f"{TIME}/2D Flow Areas/Area/Cell Velocity - Velocity X", schema)
    add_component(path, "X", 30, stored=False)
    add_component(path, "Y", 40, stored=False)
    with pytest.raises(ValueError, match="schema"):
        values(path)


def test_invalid_legacy_pair_cannot_hide_behind_faces(tmp_path):
    path = write_velocity_hdf(tmp_path / "legacy.p01.hdf")
    add_component(path, "X", 30, stored=False)
    add_component(path, "Y", 40, stored=False)
    replace_schema(path, f"{TIME}/2D Flow Areas/Area/Velocity X", np.full((3, 2), b"30"))
    with pytest.raises(ValueError, match="schema"):
        values(path)


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("time_index", [0, 1, -1])
def test_public_point_query_uses_coherent_legacy_pair(tmp_path, time_index):
    from pyproj import CRS
    from types import SimpleNamespace
    import pandas as pd

    path = write_velocity_hdf(tmp_path / "public.p01.hdf")
    with h5py.File(path, "r+") as f:
        f.attrs["Projection"] = CRS.from_epsg(26915).to_wkt()
        f.require_group("Plan Data/Plan Information").attrs["Simulation Start Time"] = "01Jan2024 00:00:00"
        f.create_dataset("Geometry/2D Flow Areas/Attributes", data=np.array([(b"Area", 1)], dtype=[("Name", "S16"), ("Cell Count", "i4")]))
    add_component(path, "X", 3)
    add_component(path, "X", 30, stored=False)
    add_component(path, "Y", 40, stored=False)
    ras_object = SimpleNamespace(plan_df=pd.DataFrame(), geom_df=pd.DataFrame())
    result = q.HdfResultsQuery.query_point(str(path), 0., 0., variable="Velocity", time_index=time_index, ras_object=ras_object)
    assert result["value"] == 50
    assert result["cell_id"] == 0
    assert result["mesh_name"] == "Area"
    frame = q.HdfResultsQuery.query_points(path, [(0., 0.)], variable="Velocity", time_index=time_index, ras_object=ras_object)
    assert frame["value"].tolist() == [50]
