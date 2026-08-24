"""Focused coverage for maximum 2D mesh depth extraction."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import geopandas as gpd
import h5py
import numpy as np
import pytest
from pyproj import CRS
from shapely.geometry import Point

from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh

MESH_NAME = "Test Mesh"
LOGGER_NAME = "ras_commander.hdf.HdfResultsMesh"
BASE_PATH = (
    "Results/Unsteady/Output/Output Blocks/Base Output/"
    "Unsteady Time Series/2D Flow Areas"
)
REAL_HDF_ENV = "RAS_COMMANDER_MAX_DEPTH_TEST_HDF"
STORED_DEPTH_HDF_ENV = "RAS_COMMANDER_STORED_DEPTH_TEST_HDF"
STORED_DEPTH_FIXTURE_SHA256 = (
    "455d849e60836421fce175610b1eac1d5794ff7fe01ceb755a1484514a66d40f"
)
MISSING = object()


def _write_mesh_hdf(
    path: Path,
    *,
    centers=MISSING,
    depth=MISSING,
    water_surface=MISSING,
    minimum_elevation=MISSING,
    include_mesh: bool = True,
) -> None:
    """Write a minimal synthetic HDF test artifact; not HEC-RAS output."""
    if centers is MISSING:
        centers = np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float64)

    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = np.bytes_(CRS.from_epsg(3451).to_wkt())
        if not include_mesh:
            return

        attributes_dtype = np.dtype([("Name", "S64"), ("Cell Count", "i4")])
        cell_count = 0 if centers is None else len(centers)
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array(
                [(MESH_NAME.encode("utf-8"), cell_count)],
                dtype=attributes_dtype,
            ),
        )
        geometry_group = hdf_file.require_group(
            f"Geometry/2D Flow Areas/{MESH_NAME}"
        )
        if centers is not None:
            geometry_group.create_dataset(
                "Cells Center Coordinate",
                data=np.asarray(centers),
            )
        if minimum_elevation is not MISSING:
            geometry_group.create_dataset(
                "Cells Minimum Elevation",
                data=np.asarray(minimum_elevation),
            )

        result_group = hdf_file.require_group(f"{BASE_PATH}/{MESH_NAME}")
        if depth is not MISSING:
            result_group.create_dataset("Depth", data=np.asarray(depth))
        if water_surface is not MISSING:
            result_group.create_dataset(
                "Water Surface",
                data=np.asarray(water_surface),
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode_ras_name(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8").rstrip("\x00").strip()
    return str(value).rstrip("\x00").strip()


def _provenance_messages(caplog):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME
        and record.levelno == logging.INFO
        and record.getMessage().startswith("Maximum-depth source for mesh")
    ]


def _independent_finite_maximum(dataset, chunk_rows=17):
    maximum = np.full(dataset.shape[1], np.nan, dtype=np.float32)
    for start in range(0, dataset.shape[0], chunk_rows):
        values = np.array(
            dataset[start:start + chunk_rows, :],
            dtype=np.float32,
            copy=True,
        )
        values[~np.isfinite(values)] = np.nan
        np.fmax(maximum, np.fmax.reduce(values, axis=0), out=maximum)
    return maximum


class _SliceOnlyDataset:
    """Dataset double that rejects whole-array conversion."""

    def __init__(self, values):
        self.values = np.asarray(values)
        self.shape = self.values.shape
        self.ndim = self.values.ndim
        self.reads = []

    def __array__(self, *args, **kwargs):
        raise AssertionError("whole dataset must not be materialized")

    def __getitem__(self, key):
        assert isinstance(key, tuple)
        assert len(key) == 2
        assert isinstance(key[0], slice)
        assert key[1] == slice(None)
        self.reads.append(key)
        return self.values[key]


def test_temporal_maximum_reads_stored_depth_in_bounded_slices():
    values = np.array(
        [
            [1.0, np.nan, np.inf, -2.0],
            [2.0, 3.0, -np.inf, -1.0],
            [np.nan, 4.0, np.nan, -3.0],
            [5.0, np.nan, np.inf, -4.0],
            [4.0, 2.0, -np.inf, -5.0],
        ],
        dtype=np.float32,
    )
    dataset = _SliceOnlyDataset(values)
    source_values = values.copy()
    expected_values = values.copy()
    expected_values[~np.isfinite(expected_values)] = np.nan
    expected = np.fmax.reduce(expected_values, axis=0)

    result = HdfResultsMesh._get_mesh_temporal_maximum(
        dataset,
        max_chunk_bytes=2 * values.shape[1] * np.dtype(np.float32).itemsize,
    )

    np.testing.assert_allclose(result, expected, equal_nan=True)
    np.testing.assert_array_equal(dataset.values, source_values)
    assert result.dtype == np.dtype("float32")
    assert [read[0] for read in dataset.reads] == [
        slice(0, 2),
        slice(2, 4),
        slice(4, 5),
    ]


def test_temporal_maximum_reads_wse_fallback_in_bounded_slices():
    water_surface = np.array(
        [
            [10.0, 19.0, np.inf],
            [12.0, 21.0, -np.inf],
            [np.nan, 18.0, np.nan],
            [11.0, 25.0, np.nan],
        ],
        dtype=np.float32,
    )
    minimum_elevation = np.array([8.0, 20.0, 5.0], dtype=np.float32)
    dataset = _SliceOnlyDataset(water_surface)
    source_values = water_surface.copy()
    expected_values = water_surface - minimum_elevation[np.newaxis, :]
    finite_values = np.isfinite(expected_values)
    np.maximum(
        expected_values,
        0.0,
        out=expected_values,
        where=finite_values,
    )
    expected_values[~finite_values] = np.nan
    expected = np.fmax.reduce(expected_values, axis=0)

    result = HdfResultsMesh._get_mesh_temporal_maximum(
        dataset,
        minimum_elevation=minimum_elevation,
        max_chunk_bytes=water_surface.shape[1] * np.dtype(np.float32).itemsize,
    )

    np.testing.assert_allclose(result, expected, equal_nan=True)
    np.testing.assert_array_equal(dataset.values, source_values)
    assert result.dtype == np.dtype("float32")
    assert [read[0] for read in dataset.reads] == [
        slice(0, 1),
        slice(1, 2),
        slice(2, 3),
        slice(3, 4),
    ]


def test_max_depth_falls_back_to_water_surface_and_handles_nonfinite_cells(
    tmp_path,
    caplog,
):
    """Synthetic artifact exercises derived-in-memory provenance."""
    hdf_path = tmp_path / "fallback.p01.hdf"
    _write_mesh_hdf(
        hdf_path,
        centers=np.array(
            [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]
        ),
        minimum_elevation=np.array([8.0, 20.0, 5.0, 0.0]),
        water_surface=np.array(
            [
                [10.0, 19.0, np.nan, np.inf],
                [12.0, 21.0, 8.0, -np.inf],
                [np.nan, np.nan, 6.0, np.nan],
            ],
            dtype=np.float32,
        ),
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = HdfResultsMesh.get_mesh_max_depth(hdf_path)

    np.testing.assert_allclose(
        result["maximum_depth"].to_numpy(),
        np.array([4.0, 1.0, 3.0, np.nan], dtype=np.float32),
        equal_nan=True,
    )
    assert result["maximum_depth"].dtype == np.dtype("float32")
    assert result.crs.to_epsg() == 3451
    assert _provenance_messages(caplog) == [
        "Maximum-depth source for mesh 'Test Mesh' in 'fallback.p01.hdf': "
        "derived in memory by ras-commander from HEC-RAS HDF 'Water Surface' "
        "minus 'Cells Minimum Elevation'; no 'Depth' dataset was created or "
        "written."
    ]


def test_max_depth_prefers_stored_depth_and_ignores_nonfinite_samples(
    tmp_path,
    caplog,
):
    """Synthetic artifact exercises stored-Depth precedence and provenance."""
    hdf_path = tmp_path / "stored-depth.p01.hdf"
    _write_mesh_hdf(
        hdf_path,
        centers=np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]),
        depth=np.array(
            [[1.0, np.nan, np.inf], [2.0, 3.0, -np.inf]],
            dtype=np.float32,
        ),
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = HdfResultsMesh.get_mesh_max_depth(hdf_path)

    np.testing.assert_allclose(
        result["maximum_depth"].to_numpy(),
        np.array([2.0, 3.0, np.nan], dtype=np.float32),
        equal_nan=True,
    )
    assert _provenance_messages(caplog) == [
        "Maximum-depth source for mesh 'Test Mesh' in 'stored-depth.p01.hdf': "
        "stored HEC-RAS HDF 'Depth' time series (read only)."
    ]


def test_synthetic_mixed_meshes_log_exactly_one_source_per_mesh(
    tmp_path,
    caplog,
):
    """Synthetic mixed artifact proves one provenance message per mesh."""
    hdf_path = tmp_path / "mixed-provenance.p01.hdf"
    stored_mesh = "Stored Mesh"
    derived_mesh = "Derived Mesh"
    attributes_dtype = np.dtype([("Name", "S64"), ("Cell Count", "i4")])
    with h5py.File(hdf_path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = np.bytes_(CRS.from_epsg(3451).to_wkt())
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array(
                [
                    (stored_mesh.encode("utf-8"), 2),
                    (derived_mesh.encode("utf-8"), 2),
                ],
                dtype=attributes_dtype,
            ),
        )
        for mesh_name in (stored_mesh, derived_mesh):
            geometry_group = hdf_file.require_group(
                f"Geometry/2D Flow Areas/{mesh_name}"
            )
            geometry_group.create_dataset(
                "Cells Center Coordinate",
                data=np.array([[0.0, 0.0], [1.0, 1.0]]),
            )
        hdf_file[f"Geometry/2D Flow Areas/{derived_mesh}"].create_dataset(
            "Cells Minimum Elevation",
            data=np.array([8.0, 9.0], dtype=np.float32),
        )
        hdf_file.create_dataset(
            f"{BASE_PATH}/{stored_mesh}/Depth",
            data=np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
        )
        hdf_file.create_dataset(
            f"{BASE_PATH}/{derived_mesh}/Water Surface",
            data=np.array([[9.0, 9.0], [10.0, 12.0]], dtype=np.float32),
        )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = HdfResultsMesh.get_mesh_max_depth(hdf_path)

    assert list(result.columns) == [
        "mesh_name",
        "cell_id",
        "maximum_depth",
        "geometry",
    ]
    assert _provenance_messages(caplog) == [
        "Maximum-depth source for mesh 'Stored Mesh' in "
        "'mixed-provenance.p01.hdf': stored HEC-RAS HDF 'Depth' time series "
        "(read only).",
        "Maximum-depth source for mesh 'Derived Mesh' in "
        "'mixed-provenance.p01.hdf': derived in memory by ras-commander from "
        "HEC-RAS HDF 'Water Surface' minus 'Cells Minimum Elevation'; no "
        "'Depth' dataset was created or written.",
    ]


def test_max_depth_returns_typed_spatial_empty_result_with_source_crs(tmp_path):
    hdf_path = tmp_path / "no-mesh.p01.hdf"
    _write_mesh_hdf(hdf_path, include_mesh=False)

    result = HdfResultsMesh.get_mesh_max_depth(hdf_path)

    assert result.empty
    assert list(result.columns) == [
        "mesh_name",
        "cell_id",
        "maximum_depth",
        "geometry",
    ]
    assert result.geometry.name == "geometry"
    assert str(result.geometry.dtype) == "geometry"
    assert result["mesh_name"].dtype == np.dtype("object")
    assert result["cell_id"].dtype == np.dtype("int64")
    assert result["maximum_depth"].dtype == np.dtype("float32")
    assert result.crs.to_epsg() == 3451


def test_max_depth_returns_typed_empty_result_for_zero_cell_mesh(tmp_path):
    hdf_path = tmp_path / "zero-cell.p01.hdf"
    _write_mesh_hdf(
        hdf_path,
        centers=np.empty((0, 2), dtype=np.float64),
        depth=np.empty((2, 0), dtype=np.float32),
    )

    result = HdfResultsMesh.get_mesh_max_depth(hdf_path)

    assert result.empty
    assert result.geometry.name == "geometry"
    assert result["cell_id"].dtype == np.dtype("int64")
    assert result["maximum_depth"].dtype == np.dtype("float32")
    assert result.crs.to_epsg() == 3451


def test_max_depth_fails_closed_when_fallback_input_is_missing(tmp_path):
    hdf_path = tmp_path / "missing-fallback.p01.hdf"
    _write_mesh_hdf(
        hdf_path,
        water_surface=np.array([[10.0, 11.0]], dtype=np.float32),
    )

    with pytest.raises(
        ValueError,
        match="Water Surface plus Cells Minimum Elevation",
    ) as exc_info:
        HdfResultsMesh.get_mesh_max_depth(hdf_path)

    assert isinstance(exc_info.value.__cause__, ValueError)


def test_max_depth_fails_closed_when_cell_centers_are_missing(tmp_path):
    hdf_path = tmp_path / "missing-centers.p01.hdf"
    _write_mesh_hdf(
        hdf_path,
        centers=None,
        depth=np.array([[1.0, 2.0]], dtype=np.float32),
    )

    with pytest.raises(ValueError, match="Cell centers are missing"):
        HdfResultsMesh.get_mesh_max_depth(hdf_path)


@pytest.mark.parametrize(
    ("fixture_kwargs", "message"),
    [
        (
            {
                "centers": np.array([[0.0, 0.0, 1.0]]),
                "depth": np.array([[1.0]]),
            },
            "Cell-center shape",
        ),
        (
            {"depth": np.array([[1.0]])},
            "Depth shape",
        ),
        (
            {
                "minimum_elevation": np.array([[8.0, 9.0]]),
                "water_surface": np.array([[10.0, 11.0]]),
            },
            "Cells Minimum Elevation shape",
        ),
        (
            {
                "minimum_elevation": np.array([8.0]),
                "water_surface": np.array([[10.0, 11.0]]),
            },
            "Water Surface shape",
        ),
    ],
)
def test_max_depth_rejects_inconsistent_dimensions(
    tmp_path,
    fixture_kwargs,
    message,
):
    hdf_path = tmp_path / "inconsistent.p01.hdf"
    _write_mesh_hdf(hdf_path, **fixture_kwargs)

    with pytest.raises(ValueError, match=message):
        HdfResultsMesh.get_mesh_max_depth(hdf_path)


def test_export_max_depth_raster_filters_values_and_coordinates_together(
    tmp_path,
    monkeypatch,
):
    import scipy.interpolate

    valid_points = np.array(
        [[0.0, 0.0], [32.0, 0.0], [0.0, 32.0], [32.0, 32.0]]
    )
    valid_values = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
    gdf = gpd.GeoDataFrame(
        {
            "mesh_name": [MESH_NAME] * 7,
            "cell_id": range(7),
            "maximum_depth": [1.0, 2.0, 3.0, 4.0, np.nan, 5.0, 6.0],
        },
        geometry=[
            Point(0.0, 0.0),
            Point(32.0, 0.0),
            Point(0.0, 32.0),
            Point(32.0, 32.0),
            Point(16.0, 16.0),
            Point(np.inf, 16.0),
            Point(16.0, np.nan),
        ],
        crs="EPSG:3451",
    )
    monkeypatch.setattr(
        HdfResultsMesh,
        "get_mesh_max_depth",
        staticmethod(lambda _hdf_path: gdf),
    )

    captured = {}
    original_griddata = scipy.interpolate.griddata

    def recording_griddata(*, points, values, xi, method, fill_value):
        captured["points"] = points.copy()
        captured["values"] = values.copy()
        return original_griddata(
            points=points,
            values=values,
            xi=xi,
            method=method,
            fill_value=fill_value,
        )

    monkeypatch.setattr(scipy.interpolate, "griddata", recording_griddata)
    output_path = tmp_path / "filtered.tif"
    hdf_path = tmp_path / "unused.p01.hdf"
    hdf_path.touch()

    result = HdfResultsMesh.export_max_depth_raster(
        hdf_path,
        output_path=output_path,
        resolution_m=1.0,
    )

    assert result == output_path
    assert output_path.is_file()
    np.testing.assert_array_equal(captured["points"], valid_points)
    np.testing.assert_array_equal(captured["values"], valid_values)


def test_export_max_depth_raster_fails_when_no_finite_points_remain(
    tmp_path,
    monkeypatch,
):
    gdf = gpd.GeoDataFrame(
        {
            "mesh_name": [MESH_NAME, MESH_NAME],
            "cell_id": [0, 1],
            "maximum_depth": [np.nan, np.inf],
        },
        geometry=[Point(0.0, 0.0), Point(np.nan, 1.0)],
        crs="EPSG:3451",
    )
    monkeypatch.setattr(
        HdfResultsMesh,
        "get_mesh_max_depth",
        staticmethod(lambda _hdf_path: gdf),
    )
    output_path = tmp_path / "must-not-exist.tif"
    hdf_path = tmp_path / "unused.p01.hdf"
    hdf_path.touch()

    with pytest.raises(ValueError, match="No usable finite depth points"):
        HdfResultsMesh.export_max_depth_raster(
            hdf_path,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_export_max_depth_raster_does_not_allocate_temp_before_griddata_failure(
    tmp_path,
    monkeypatch,
):
    import tempfile

    from scipy.spatial import QhullError

    gdf = gpd.GeoDataFrame(
        {
            "mesh_name": [MESH_NAME] * 3,
            "cell_id": range(3),
            "maximum_depth": [1.0, 2.0, 3.0],
        },
        geometry=[Point(0.0, 0.0), Point(16.0, 16.0), Point(32.0, 32.0)],
        crs="EPSG:3451",
    )
    monkeypatch.setattr(
        HdfResultsMesh,
        "get_mesh_max_depth",
        staticmethod(lambda _hdf_path: gdf),
    )
    temp_allocated = False

    def forbidden_temporary_file(*args, **kwargs):
        nonlocal temp_allocated
        temp_allocated = True
        raise AssertionError("temporary output allocated before interpolation")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbidden_temporary_file)
    hdf_path = tmp_path / "unused.p01.hdf"
    hdf_path.touch()

    with pytest.raises(QhullError):
        HdfResultsMesh.export_max_depth_raster(hdf_path, output_path=None)

    assert temp_allocated is False


def test_export_max_depth_raster_removes_owned_temp_after_write_failure(
    tmp_path,
    monkeypatch,
):
    import tempfile

    import rasterio

    gdf = gpd.GeoDataFrame(
        {
            "mesh_name": [MESH_NAME] * 4,
            "cell_id": range(4),
            "maximum_depth": [1.0, 2.0, 3.0, 4.0],
        },
        geometry=[
            Point(0.0, 0.0),
            Point(32.0, 0.0),
            Point(0.0, 32.0),
            Point(32.0, 32.0),
        ],
        crs="EPSG:3451",
    )
    monkeypatch.setattr(
        HdfResultsMesh,
        "get_mesh_max_depth",
        staticmethod(lambda _hdf_path: gdf),
    )

    original_temporary_file = tempfile.NamedTemporaryFile
    allocated_paths = []

    def recording_temporary_file(*args, **kwargs):
        temporary_file = original_temporary_file(
            *args,
            dir=tmp_path,
            **kwargs,
        )
        allocated_paths.append(Path(temporary_file.name))
        return temporary_file

    expected_error = RuntimeError("synthetic raster write failure")
    opened_paths = []
    writer_events = []

    class FailingRasterWriter:
        def __enter__(self):
            writer_events.append("entered")
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            writer_events.append("exited")
            return False

        def write(self, values, band):
            writer_events.append("write")
            assert values.shape == (2, 2)
            assert band == 1
            raise expected_error

    def recording_raster_open(path, *args, **kwargs):
        opened_path = Path(path)
        opened_paths.append(opened_path)
        assert allocated_paths == [opened_path]
        assert opened_path.is_file()
        return FailingRasterWriter()

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", recording_temporary_file)
    monkeypatch.setattr(rasterio, "open", recording_raster_open)
    hdf_path = tmp_path / "unused.p01.hdf"
    hdf_path.touch()

    with pytest.raises(RuntimeError) as exc_info:
        HdfResultsMesh.export_max_depth_raster(
            hdf_path,
            output_path=None,
            resolution_m=32.0,
        )

    assert exc_info.value is expected_error
    assert opened_paths == allocated_paths
    assert writer_events == ["entered", "write", "exited"]
    assert len(allocated_paths) == 1
    assert allocated_paths[0].suffix == ".tif"
    assert not allocated_paths[0].exists()


@pytest.mark.integration
def test_max_depth_on_real_completed_hdf_without_stored_depth(tmp_path, caplog):
    """Read a pre-existing HEC-RAS producer HDF; generate no model output."""
    configured_path = os.environ.get(REAL_HDF_ENV)
    if not configured_path:
        pytest.skip(
            f"Set {REAL_HDF_ENV} to a completed 2D plan HDF without stored Depth"
        )

    hdf_path = Path(configured_path)
    if not hdf_path.is_file():
        pytest.skip(f"Configured real plan HDF does not exist: {hdf_path}")

    expected_samples = {}
    expected_counts = {}
    with h5py.File(hdf_path, "r") as hdf_file:
        area_attributes = hdf_file["Geometry/2D Flow Areas/Attributes"]
        for area_attribute in area_attributes[:]:
            mesh_name = _decode_ras_name(area_attribute[0])
            result_group = hdf_file[f"{BASE_PATH}/{mesh_name}"]
            assert "Depth" not in result_group

            water_surface = result_group["Water Surface"]
            minimum_elevation = hdf_file[
                f"Geometry/2D Flow Areas/{mesh_name}/Cells Minimum Elevation"
            ]
            centers = hdf_file[
                f"Geometry/2D Flow Areas/{mesh_name}/Cells Center Coordinate"
            ]
            assert water_surface.ndim == 2
            assert minimum_elevation.shape == (water_surface.shape[1],)
            assert centers.shape == (water_surface.shape[1], 2)

            sample_ids = np.unique(
                np.array([0, water_surface.shape[1] // 2, water_surface.shape[1] - 1])
            )
            sampled_depth = (
                np.asarray(water_surface[:, sample_ids], dtype=np.float32)
                - np.asarray(minimum_elevation[sample_ids], dtype=np.float32)
            )
            finite_samples = np.isfinite(sampled_depth)
            np.maximum(
                sampled_depth,
                0.0,
                out=sampled_depth,
                where=finite_samples,
            )
            sampled_depth[~finite_samples] = np.nan
            expected_samples[mesh_name] = (
                sample_ids,
                np.fmax.reduce(sampled_depth, axis=0),
            )
            expected_counts[mesh_name] = water_surface.shape[1]

    source_digest = _sha256(hdf_path)
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = HdfResultsMesh.get_mesh_max_depth(hdf_path)

    assert set(result["mesh_name"]) == set(expected_counts)
    assert len(result) == sum(expected_counts.values())
    assert result.crs is not None
    for mesh_name, (sample_ids, expected) in expected_samples.items():
        mesh_result = result[result["mesh_name"] == mesh_name].set_index("cell_id")
        np.testing.assert_allclose(
            mesh_result.loc[sample_ids, "maximum_depth"].to_numpy(),
            expected,
            equal_nan=True,
        )

    assert _provenance_messages(caplog) == [
        "Maximum-depth source for mesh "
        f"'{mesh_name}' in '{hdf_path.name}': derived in memory by "
        "ras-commander from HEC-RAS HDF 'Water Surface' minus 'Cells Minimum "
        "Elevation'; no 'Depth' dataset was created or written."
        for mesh_name in expected_counts
    ]
    caplog.clear()

    finite_rows = (
        np.isfinite(result["maximum_depth"].to_numpy())
        & np.isfinite(result.geometry.x.to_numpy())
        & np.isfinite(result.geometry.y.to_numpy())
    )
    usable = result.loc[finite_rows]
    assert not usable.empty

    x_min, y_min, x_max, y_max = usable.total_bounds
    resolution = max(x_max - x_min, y_max - y_min) / 40.0
    output_path = tmp_path / "real-max-depth.tif"
    HdfResultsMesh.export_max_depth_raster(
        hdf_path,
        output_path=output_path,
        resolution_m=resolution,
    )

    import rasterio
    from scipy.interpolate import griddata as scipy_griddata

    cols = max(2, int(np.ceil((x_max - x_min) / resolution)) + 1)
    rows = max(2, int(np.ceil((y_max - y_min) / resolution)) + 1)
    grid_x = np.linspace(x_min, x_max, cols)
    grid_y = np.linspace(y_max, y_min, rows)
    gx, gy = np.meshgrid(grid_x, grid_y)
    expected_grid = scipy_griddata(
        points=np.column_stack([usable.geometry.x, usable.geometry.y]),
        values=usable["maximum_depth"].to_numpy(dtype=np.float64),
        xi=(gx, gy),
        method="linear",
        fill_value=-9999.0,
    ).astype(np.float32)
    expected_grid = np.where(np.isnan(expected_grid), -9999.0, expected_grid)

    with rasterio.open(output_path) as raster:
        np.testing.assert_allclose(raster.read(1), expected_grid)
        assert raster.nodata == -9999.0

    assert _sha256(hdf_path) == source_digest


@pytest.mark.integration
def test_max_depth_on_real_completed_hdf_with_stored_depth(caplog):
    """Read authentic HEC-RAS 5.0.7 stored Depth; generate no model output."""
    configured_path = os.environ.get(STORED_DEPTH_HDF_ENV)
    if not configured_path:
        pytest.skip(
            f"Set {STORED_DEPTH_HDF_ENV} to the completed Spring p06 HDF"
        )

    hdf_path = Path(configured_path)
    if not hdf_path.is_file():
        pytest.skip(f"Configured stored-Depth plan HDF does not exist: {hdf_path}")

    source_digest = _sha256(hdf_path)
    assert source_digest == STORED_DEPTH_FIXTURE_SHA256

    expected_by_mesh = {}
    expected_counts = {}
    with h5py.File(hdf_path, "r") as hdf_file:
        solution = hdf_file["Results/Unsteady/Summary"].attrs["Solution"]
        assert "Finished Successfully" in _decode_ras_name(solution)

        area_attributes = hdf_file["Geometry/2D Flow Areas/Attributes"]
        for area_attribute in area_attributes[:]:
            mesh_name = _decode_ras_name(area_attribute[0])
            result_group = hdf_file[f"{BASE_PATH}/{mesh_name}"]
            assert "Depth" in result_group
            assert "Water Surface" in result_group

            depth = result_group["Depth"]
            centers = hdf_file[
                f"Geometry/2D Flow Areas/{mesh_name}/Cells Center Coordinate"
            ]
            minimum_elevation = hdf_file[
                f"Geometry/2D Flow Areas/{mesh_name}/Cells Minimum Elevation"
            ]
            assert depth.dtype == np.dtype("float32")
            assert depth.ndim == 2
            assert centers.shape == (depth.shape[1], 2)
            assert minimum_elevation.shape == (depth.shape[1],)

            expected_by_mesh[mesh_name] = _independent_finite_maximum(depth)
            expected_counts[mesh_name] = depth.shape[1]

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = HdfResultsMesh.get_mesh_max_depth(hdf_path)

    assert list(result.columns) == [
        "mesh_name",
        "cell_id",
        "maximum_depth",
        "geometry",
    ]
    assert result.geometry.name == "geometry"
    assert result["mesh_name"].dtype == np.dtype("object")
    assert result["cell_id"].dtype == np.dtype("int64")
    assert result["maximum_depth"].dtype == np.dtype("float32")
    assert result.crs.to_epsg() == 2278
    assert set(result["mesh_name"]) == set(expected_counts)
    assert len(result) == sum(expected_counts.values())
    assert _provenance_messages(caplog) == [
        "Maximum-depth source for mesh "
        f"'{mesh_name}' in '{hdf_path.name}': stored HEC-RAS HDF 'Depth' time "
        "series (read only)."
        for mesh_name in expected_counts
    ]

    for mesh_name, expected in expected_by_mesh.items():
        mesh_result = result[result["mesh_name"] == mesh_name].sort_values(
            "cell_id"
        )
        np.testing.assert_array_equal(
            mesh_result["cell_id"].to_numpy(),
            np.arange(expected_counts[mesh_name]),
        )
        np.testing.assert_array_equal(
            mesh_result["maximum_depth"].to_numpy(),
            expected,
        )

    assert _sha256(hdf_path) == source_digest
