"""Lazy and bounded 2D HDF result-reader coverage."""

from __future__ import annotations

import os
import pickle
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from pyproj import CRS

from ras_commander import HdfResultView
from ras_commander.hdf.HdfMesh import HdfMesh
from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh

MESH_NAME = "Test Mesh"
BASE = "Results/Unsteady/Output/Output Blocks/Base Output"
TIME_BASE = f"{BASE}/Unsteady Time Series"
SUMMARY_BASE = f"{BASE}/Summary Output/2D Flow Areas/{MESH_NAME}"
REAL_HDF_ENV = "RAS_COMMANDER_RESULT_VIEW_TEST_HDF"


def _write_result_hdf(path: Path) -> tuple[Path, np.ndarray]:
    values = np.array(
        [
            [0.0, 0.0, 0.0, 0.0],
            [1.0, 2.0, np.nan, 4.0],
            [2.0, 3.0, 6.0, 5.0],
            [4.0, np.inf, 7.0, 1.0],
            [0.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = CRS.from_epsg(26915).to_wkt()
        plan_info = hdf_file.require_group("Plan Data/Plan Information")
        plan_info.attrs["Simulation Start Time"] = "01Jan2024 00:00:00"
        hdf_file.create_dataset(
            f"{TIME_BASE}/Time",
            data=np.arange(len(values), dtype=float) / 24.0,
        )
        attributes = np.array(
            [(MESH_NAME.encode(), len(values[0]))],
            dtype=np.dtype([("Name", "S64"), ("Cell Count", "i4")]),
        )
        hdf_file.create_dataset("Geometry/2D Flow Areas/Attributes", data=attributes)
        hdf_file.create_dataset(
            f"Geometry/2D Flow Areas/{MESH_NAME}/Cells Center Coordinate",
            data=np.array(
                [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]],
                dtype=float,
            ),
        )
        dataset = hdf_file.create_dataset(
            f"{TIME_BASE}/2D Flow Areas/{MESH_NAME}/Water Surface",
            data=values,
            chunks=(1, values.shape[1]),
        )
        dataset.attrs["Units"] = "ft"
        summary = hdf_file.create_dataset(
            f"{SUMMARY_BASE}/Maximum Water Surface",
            data=np.array(
                [[4.0, 3.0, 7.0, 5.0], [3 / 24, 2 / 24, 3 / 24, 2 / 24]],
                dtype=np.float32,
            ),
        )
        summary.attrs["Units"] = "ft"
    return path, values


def test_view_creation_is_lazy_and_publicly_exported(tmp_path, monkeypatch):
    hdf_path, _ = _write_result_hdf(tmp_path / "lazy.p01.hdf")
    reads = []
    original = h5py.Dataset.__getitem__

    def record_read(dataset, key):
        if dataset.name.endswith("/Water Surface"):
            reads.append(key)
        return original(dataset, key)

    monkeypatch.setattr(h5py.Dataset, "__getitem__", record_read)
    view = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        MESH_NAME,
        "Water Surface",
        truncate=False,
        return_type="view",
    )

    assert isinstance(view, HdfResultView)
    assert view.shape == (5, 4)
    assert view.dtype == np.dtype("float32")
    assert reads == []


def test_eager_selection_is_pushed_down_and_preserves_labels(tmp_path, monkeypatch):
    hdf_path, values = _write_result_hdf(tmp_path / "slice.p01.hdf")
    reads = []
    original = h5py.Dataset.__getitem__

    def record_read(dataset, key):
        if dataset.name.endswith("/Water Surface"):
            reads.append(key)
        return original(dataset, key)

    monkeypatch.setattr(h5py.Dataset, "__getitem__", record_read)
    result = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        MESH_NAME,
        "Water Surface",
        truncate=False,
        time_selection=slice(1, 3),
        spatial_selection=slice(1, 4, 2),
    )

    np.testing.assert_allclose(result.values, values[1:3, 1:4:2])
    assert result.dims == ("time", "cell_id")
    assert result["cell_id"].values.tolist() == [1, 3]
    assert reads == [(slice(1, 3, 1), slice(1, 4, 2))]


def test_view_batches_are_bounded_and_reassemble_exactly(tmp_path):
    hdf_path, values = _write_result_hdf(tmp_path / "batches.p01.hdf")
    view = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        MESH_NAME,
        "Water Surface",
        truncate=False,
        return_type="view",
    ).select(time=slice(1, 5), spatial=slice(0, 3))

    batches = list(view.iter_batches(batch_size=2))

    assert [batch.shape for batch in batches] == [(2, 3), (2, 3)]
    np.testing.assert_allclose(
        np.vstack([batch.values for batch in batches]),
        values[1:5, :3],
    )


def test_public_iterator_uses_established_xarray_batches(tmp_path):
    hdf_path, values = _write_result_hdf(tmp_path / "iterator.p01.hdf")

    batches = list(
        HdfResultsMesh.iter_mesh_timeseries(
            hdf_path,
            MESH_NAME,
            "Water Surface",
            time_selection=slice(1, 4),
            spatial_selection=slice(2, 4),
            batch_size=2,
        )
    )

    assert [batch.shape for batch in batches] == [(2, 2), (1, 2)]
    np.testing.assert_allclose(
        np.vstack([batch.values for batch in batches]),
        values[1:4, 2:4],
    )


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("max", [4.0, 3.0, 7.0, 5.0]),
        ("min", [0.0, 0.0, 0.0, 0.0]),
        ("mean", [1.4, 1.25, 3.25, 2.0]),
        ("argmax", [3, 2, 3, 2]),
    ],
)
def test_view_bounded_reductions(tmp_path, operation, expected):
    hdf_path, _ = _write_result_hdf(tmp_path / f"{operation}.p01.hdf")
    view = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        MESH_NAME,
        "Water Surface",
        truncate=False,
        return_type="view",
    )

    result = view.reduce(operation, max_chunk_bytes=2 * 4 * 4)

    np.testing.assert_allclose(result.values, expected)
    assert result.dims == ("cell_id",)
    if operation != "argmax":
        assert result.dtype == np.dtype("float32")


def test_lazy_truncation_matches_existing_eager_contract(tmp_path):
    hdf_path, values = _write_result_hdf(tmp_path / "truncate.p01.hdf")
    view = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        MESH_NAME,
        "Water Surface",
        return_type="view",
    )

    result = view.to_xarray()

    np.testing.assert_allclose(result.values, values[1:4], equal_nan=True)


def test_geometry_free_summary_matches_spatial_summary_values(tmp_path):
    hdf_path, _ = _write_result_hdf(tmp_path / "summary.p01.hdf")

    values = HdfResultsMesh.get_mesh_summary_values(
        hdf_path,
        "Maximum Water Surface",
    )
    spatial = HdfResultsMesh.get_mesh_summary(
        hdf_path,
        "Maximum Water Surface",
    )

    assert not hasattr(values, "geometry")
    assert "geometry" not in values.columns
    assert "geometry" in spatial.columns
    pd.testing.assert_frame_equal(
        values.reset_index(drop=True),
        pd.DataFrame(spatial.drop(columns="geometry")).reset_index(drop=True),
    )


def test_spatial_summary_builds_cell_geometry_once_for_multiple_meshes(
    tmp_path,
    monkeypatch,
):
    hdf_path, _ = _write_result_hdf(tmp_path / "multi_summary.p01.hdf")
    second = "Second Mesh"
    with h5py.File(hdf_path, "a") as hdf_file:
        del hdf_file["Geometry/2D Flow Areas/Attributes"]
        attributes = np.array(
            [(MESH_NAME.encode(), 4), (second.encode(), 2)],
            dtype=np.dtype([("Name", "S64"), ("Cell Count", "i4")]),
        )
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=attributes,
        )
        hdf_file.create_dataset(
            f"Geometry/2D Flow Areas/{second}/Cells Center Coordinate",
            data=np.array([[10.0, 0.0], [11.0, 0.0]]),
        )
        hdf_file.create_dataset(
            f"{BASE}/Summary Output/2D Flow Areas/{second}/"
            "Maximum Water Surface",
            data=np.array([[8.0, 9.0], [1 / 24, 2 / 24]], dtype=np.float32),
        )

    calls = 0
    original = HdfMesh.get_mesh_cell_points

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(HdfMesh, "get_mesh_cell_points", counted)
    result = HdfResultsMesh.get_mesh_summary(
        hdf_path,
        "Maximum Water Surface",
    )

    assert calls == 1
    assert set(result["mesh_name"]) == {MESH_NAME, second}
    assert len(result) == 6


def test_view_is_pickleable_and_detects_source_changes(tmp_path):
    hdf_path, _ = _write_result_hdf(tmp_path / "fingerprint.p01.hdf")
    view = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        MESH_NAME,
        "Water Surface",
        truncate=False,
        return_type="view",
    )
    restored = pickle.loads(pickle.dumps(view))
    np.testing.assert_allclose(restored.to_numpy(), view.to_numpy(), equal_nan=True)

    with hdf_path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(RuntimeError, match="source changed"):
        restored.to_numpy()


def test_view_arrow_conversion_uses_long_labeled_rows(tmp_path):
    pytest.importorskip("pyarrow")
    hdf_path, _ = _write_result_hdf(tmp_path / "arrow.p01.hdf")
    view = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        MESH_NAME,
        "Water Surface",
        truncate=False,
        time_selection=slice(1, 3),
        spatial_selection=slice(0, 2),
        return_type="view",
    )

    table = view.to_arrow()

    assert table.column_names == ["time", "cell_id", "Water Surface"]
    assert table.num_rows == 4


def test_view_reports_moved_source_clearly(tmp_path):
    hdf_path, _ = _write_result_hdf(tmp_path / "moved.p01.hdf")
    view = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        MESH_NAME,
        "Water Surface",
        truncate=False,
        return_type="view",
    )
    hdf_path.rename(tmp_path / "elsewhere.p01.hdf")

    with pytest.raises(FileNotFoundError, match="no longer exists"):
        view.to_numpy()


def test_view_supports_independent_concurrent_readers(tmp_path):
    hdf_path, values = _write_result_hdf(tmp_path / "concurrent.p01.hdf")
    view = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        MESH_NAME,
        "Water Surface",
        truncate=False,
        return_type="view",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(view.select(time=index).to_numpy)
            for index in (1, 3)
        ]

    np.testing.assert_allclose(futures[0].result(), values[1:2], equal_nan=True)
    np.testing.assert_allclose(futures[1].result(), values[3:4], equal_nan=True)


@pytest.mark.skipif(
    not os.environ.get(REAL_HDF_ENV),
    reason=f"set {REAL_HDF_ENV} to a representative computed plan HDF",
)
def test_real_result_view_matches_direct_hdf_slices_and_reduction():
    """Opt-in qualification against a real, computed RasExamples plan HDF."""
    hdf_path = Path(os.environ[REAL_HDF_ENV])
    with h5py.File(hdf_path, "r") as hdf_file:
        area_names = HdfResultsMesh._get_available_meshes(hdf_file)
        assert area_names
        mesh_name = area_names[0]
        dataset_path = HdfResultsMesh._get_mesh_timeseries_output_path(
            mesh_name,
            "Water Surface",
        )
        dataset = hdf_file[dataset_path]
        assert dataset.ndim == 2 and dataset.shape[0] > 1
        spatial_stop = min(512, dataset.shape[1])
        expected_slice = dataset[1:2, :spatial_stop]
        eager_subset = dataset[:, :spatial_stop]

    view = HdfResultsMesh.get_mesh_timeseries(
        hdf_path,
        mesh_name,
        "Water Surface",
        truncate=False,
        return_type="view",
    ).select(spatial=slice(0, spatial_stop))
    selected = view.select(time=1).to_numpy()
    reduced = view.reduce("max", max_chunk_bytes=64 * 1024)

    finite_subset = eager_subset.astype(np.float32, copy=True)
    finite_subset[~np.isfinite(finite_subset)] = np.nan
    expected_maximum = np.fmax.reduce(finite_subset, axis=0)
    np.testing.assert_allclose(selected, expected_slice, equal_nan=True)
    np.testing.assert_allclose(
        reduced.values,
        expected_maximum,
        equal_nan=True,
    )
