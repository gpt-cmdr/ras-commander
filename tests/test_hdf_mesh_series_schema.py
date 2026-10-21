"""Qualification of legacy and Location-labelled mesh time series."""

import logging

import h5py
import numpy as np
import pytest

from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh as Mesh


BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
AREA = "Area"
GEOMETRY = f"Geometry/2D Flow Areas/{AREA}"
SERIES = f"{BASE}/2D Flow Areas/{AREA}"


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "schema.p01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.require_group("Plan Data/Plan Information").attrs[
            "Simulation Start Time"
        ] = "01Jan2024 00:00:00"
        hdf.create_dataset(f"{BASE}/Time", data=np.arange(3) / 24.0)
        hdf.create_dataset(
            f"{BASE}/Time Date Stamp (ms)",
            data=np.array([f"01Jan2024 0{hour}:00:00.000".encode() for hour in range(3)]),
        )
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array([(AREA.encode(), 2)], dtype=[("Name", "S16"), ("Cell Count", "i4")]),
        )
        # Equal stored counts deliberately cannot disambiguate the domains.
        hdf.create_dataset(f"{GEOMETRY}/Cells Center Coordinate", data=np.zeros((4, 2)))
        hdf.create_dataset(f"{GEOMETRY}/Faces FacePoint Indexes", data=np.zeros((4, 2), dtype=int))
        group = hdf.require_group(SERIES)
        for name in ["Depth", "Water Surface", "Face Velocity", "Face Shear Stress", "Face Area", "Face Manning's n", "Unknown Face Diagnostic"]:
            group.create_dataset(name, data=np.arange(12, dtype=np.float32).reshape(3, 4))
        group.create_dataset("Time Step", data=np.array([0.0, 0.5, 0.25], dtype=np.float32))
    return path


def read(path, name, mode, **kwargs):
    if mode == "eager":
        return Mesh.get_mesh_timeseries(path, AREA, name, truncate=False, **kwargs)
    if mode == "lazy":
        return Mesh.get_mesh_timeseries(path, AREA, name, truncate=False, return_type="view", **kwargs).to_xarray()
    import xarray as xr

    return xr.concat(list(Mesh.iter_mesh_timeseries(path, AREA, name, batch_size=2, **kwargs)), dim="time")


@pytest.mark.parametrize("mode", ["eager", "lazy", "stream"])
@pytest.mark.parametrize("name,domain", [
    ("Depth", "cell_id"), ("Water Surface", "cell_id"),
    ("Face Velocity", "face_id"), ("Face Shear Stress", "face_id"),
    ("Face Area", "face_id"), ("Face Manning's n", "face_id"),
])
def test_missing_location_exact_legacy_schema(source, name, domain, mode, caplog):
    with caplog.at_level(logging.DEBUG, logger="ras_commander.hdf.HdfResultsMesh"):
        result = read(source, name, mode, include_ghost_cells=True)
    with h5py.File(source, "r") as hdf:
        dataset = hdf[f"{SERIES}/{name}"]
        assert "Location" not in dataset.attrs
        assert result.values.dtype == dataset.dtype
        assert result.values.tobytes() == dataset[:].tobytes()
    assert result.dims == ("time", domain)
    assert "Legacy stable-core" in caplog.text and name in caplog.text
    if domain == "cell_id":
        if mode == "eager":
            assert result.is_ghost_cell.values.tolist() == [False, False, True, True]
        assert read(source, name, mode).shape == (3, 2)
    else:
        assert "is_ghost_cell" not in result.coords


@pytest.mark.parametrize("mode", ["eager", "lazy", "stream"])
def test_time_only_preserves_exact_values_and_coordinates(source, mode):
    result = read(source, "Time Step", mode)
    with h5py.File(source, "r") as hdf:
        assert result.values.tobytes() == hdf[f"{SERIES}/Time Step"][:].tobytes()
    assert result.dims == ("time",)
    assert set(result.coords) == {"time"}
    assert read(source, "Time Step", mode, time_selection=slice(1, 3)).shape == (2,)
    with pytest.raises(ValueError, match="spatial selection"):
        read(source, "Time Step", mode, spatial_selection=0)


@pytest.mark.parametrize("mode", ["eager", "lazy", "stream"])
@pytest.mark.parametrize("location", [b"", b"Unknown", 1, [b"Cells", b"Cells"], b"\xff"])
def test_invalid_present_location_never_falls_back(source, mode, location):
    with h5py.File(source, "r+") as hdf:
        hdf[f"{SERIES}/Water Surface"].attrs["Location"] = location
    with pytest.raises(ValueError, match="Location"):
        read(source, "Water Surface", mode)
    with h5py.File(source, "r") as hdf:
        assert "Water Surface" not in Mesh._discover_mesh_series(hdf, AREA)


@pytest.mark.parametrize("location,domain", [(b"Faces", "face_id"), ([b"Faces"], "face_id"), (b"Cell", "cell_id"), (b"Cells", "cell_id")])
def test_present_location_overrides_familiar_name_at_equal_counts(source, location, domain):
    with h5py.File(source, "r+") as hdf:
        hdf[f"{SERIES}/Water Surface"].attrs["Location"] = location
    result = read(source, "Water Surface", "eager", include_ghost_cells=True)
    assert result.dims == ("time", domain)


@pytest.mark.parametrize("mode", ["eager", "lazy", "stream"])
def test_conflicting_present_domain_refused_even_when_legacy_count_matches(source, mode):
    with h5py.File(source, "r+") as hdf:
        hdf[f"{SERIES}/Water Surface"].attrs["Location"] = b"Faces"
        del hdf[f"{GEOMETRY}/Faces FacePoint Indexes"]
        hdf.create_dataset(f"{GEOMETRY}/Faces FacePoint Indexes", data=np.zeros((5, 2)))
    with pytest.raises(ValueError, match="geometry count"):
        read(source, "Water Surface", mode)


@pytest.mark.parametrize("mode", ["eager", "lazy", "stream"])
def test_unknown_missing_location_never_infers_from_shape_or_substring(source, mode):
    # The cell count is unique here; that still cannot qualify an unknown name.
    with h5py.File(source, "r+") as hdf:
        del hdf[f"{GEOMETRY}/Faces FacePoint Indexes"]
        hdf.create_dataset(f"{GEOMETRY}/Faces FacePoint Indexes", data=np.zeros((5, 2)))
    with pytest.raises(ValueError, match="no qualified legacy schema"):
        read(source, "Unknown Face Diagnostic", mode)


@pytest.mark.parametrize("location", [None, b"Cells"])
@pytest.mark.parametrize("mutation", ["missing_geometry", "geometry_count", "scalar_geometry", "physical_count", "time_length", "time_rank", "time_text", "missing_time"])
def test_malformed_time_and_geometry_refused_on_both_domain_paths(source, location, mutation):
    with h5py.File(source, "r+") as hdf:
        if location is not None:
            hdf[f"{SERIES}/Water Surface"].attrs["Location"] = location
        if mutation in {"missing_geometry", "geometry_count", "scalar_geometry"}:
            del hdf[f"{GEOMETRY}/Cells Center Coordinate"]
            if mutation != "missing_geometry":
                hdf.create_dataset(f"{GEOMETRY}/Cells Center Coordinate", data=np.zeros((5, 2)) if mutation == "geometry_count" else 4)
        elif mutation == "physical_count":
            attrs = hdf["Geometry/2D Flow Areas/Attributes"][:]
            attrs["Cell Count"] = 5
            hdf["Geometry/2D Flow Areas/Attributes"][:] = attrs
        else:
            del hdf[f"{BASE}/Time"]
            if mutation != "missing_time":
                values = {"time_length": np.arange(2), "time_rank": np.zeros((3, 1)), "time_text": [b"a", b"b", b"c"]}[mutation]
                hdf.create_dataset(f"{BASE}/Time", data=values)
    with pytest.raises(ValueError):
        read(source, "Water Surface", "lazy")


@pytest.mark.parametrize("mode", ["eager", "lazy", "stream"])
def test_one_row_wind_is_not_broadcast(source, mode):
    with h5py.File(source, "r+") as hdf:
        dataset = hdf.create_dataset(f"{SERIES}/Face Wind Term", data=np.ones((1, 4)))
        dataset.attrs["Location"] = b"Faces"
    with pytest.raises(ValueError, match="Time axis"):
        read(source, "Face Wind Term", mode)


def test_legacy_schema_is_confined_to_canonical_namespace(source):
    with h5py.File(source, "r+") as hdf:
        dataset = hdf.create_dataset("Other/Water Surface", data=np.ones((3, 4)))
        with pytest.raises(ValueError, match="no qualified legacy schema"):
            Mesh._mesh_series_id_dim(hdf, AREA, dataset)


def test_time_only_rejects_contradictory_present_location(source):
    with h5py.File(source, "r+") as hdf:
        hdf[f"{SERIES}/Time Step"].attrs["Location"] = b"Cells"
    with pytest.raises(ValueError, match="time-only schema"):
        read(source, "Time Step", "lazy")


@pytest.mark.parametrize("mode", ["eager", "lazy", "stream"])
@pytest.mark.parametrize("located", [False, True])
@pytest.mark.parametrize("domain", ["cell", "face"])
@pytest.mark.parametrize("schema", ["rank_one", "rank_three", "one_column", "text", "boolean", "complex"])
def test_matching_geometry_count_does_not_qualify_bad_axes(source, domain, located, mode, schema):
    name = "Water Surface" if domain == "cell" else "Face Velocity"
    table = "Cells Center Coordinate" if domain == "cell" else "Faces FacePoint Indexes"
    values = {
        "rank_one": np.zeros(4), "rank_three": np.zeros((4, 2, 1)),
        "one_column": np.zeros((4, 1)), "text": np.full((4, 2), b"0"),
        "boolean": np.zeros((4, 2), dtype=bool), "complex": np.zeros((4, 2), dtype=complex),
    }[schema]
    with h5py.File(source, "r+") as hdf:
        if located:
            hdf[f"{SERIES}/{name}"].attrs["Location"] = b"Cells" if domain == "cell" else b"Faces"
        del hdf[f"{GEOMETRY}/{table}"]
        hdf.create_dataset(f"{GEOMETRY}/{table}", data=values)
    with pytest.raises(ValueError, match="geometry schema"):
        read(source, name, mode)
    with h5py.File(source, "r") as hdf:
        assert name not in Mesh._discover_mesh_series(hdf, AREA)


@pytest.mark.parametrize("mode", ["eager", "lazy", "stream"])
def test_face_point_indexes_require_integer_pairs(source, mode):
    with h5py.File(source, "r+") as hdf:
        del hdf[f"{GEOMETRY}/Faces FacePoint Indexes"]
        hdf.create_dataset(f"{GEOMETRY}/Faces FacePoint Indexes", data=np.zeros((4, 2), dtype=float))
    with pytest.raises(ValueError, match="geometry schema"):
        read(source, "Face Velocity", mode)
