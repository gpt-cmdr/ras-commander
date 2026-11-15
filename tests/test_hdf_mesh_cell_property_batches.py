"""Bounded reads of real HDF datasets preserve the original cell-table API."""

import hashlib
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import fast_hdf
from ras_commander.hdf import _cell_property_batches as batches
from ras_commander.hdf.HdfMesh import HdfMesh


@pytest.fixture
def cell_hdf(tmp_path, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "python")
    path = tmp_path / "cells.g01.hdf"
    with h5py.File(path, "w") as source:
        areas = source.create_group("Geometry/2D Flow Areas")
        areas.create_dataset("Names", data=np.array([b"First", b"Second", b"Missing"]))
        # Gaps, zero-count ghost cells, overlapping and out-of-order ranges.
        info = np.array([[2, 2], [4, 1], [0, 0], [9, 2], [1, 3], [22, 4]], dtype="i4")
        values = np.arange(48, dtype="f8").reshape(24, 2)
        values[1] = [-0.0, 0.0]
        values[2] = [np.nan, np.inf]
        values[3] = [-np.inf, -0.0]
        for name, dtype in [("First", "f8"), ("Second", "f4")]:
            mesh = areas.create_group(name)
            mesh.create_dataset("Cells Volume Elevation Info", data=info)
            mesh.create_dataset(
                "Cells Volume Elevation Values", data=values.astype(dtype)
            )
        areas.create_group("Missing")
    return path


def _assembled(path, batch_cells, **kwargs):
    frames = {}
    for name, frame in HdfMesh.iter_mesh_cell_property_tables(
        path, batch_cells=batch_cells, **kwargs
    ):
        frames.setdefault(name, []).append(frame)
    return {name: pd.concat(items, ignore_index=True) for name, items in frames.items()}


def _assert_frames(actual, expected):
    assert list(actual) == list(expected)
    for name in expected:
        pd.testing.assert_frame_equal(actual[name], expected[name], check_exact=True)
        # Includes the sign of zero and NaN payload, beyond pandas equality.
        for column in actual[name]:
            if actual[name][column].dtype.kind in "fi":
                assert (
                    actual[name][column].to_numpy().tobytes()
                    == expected[name][column].to_numpy().tobytes()
                )


@pytest.mark.parametrize("batch_cells", [1, 2, 3, 1024, 8192, 65536, np.int64(2)])
def test_batches_equal_legacy_frames_without_mutation(cell_hdf, batch_cells):
    before = hashlib.sha256(cell_hdf.read_bytes()).digest()
    expected = HdfMesh.get_mesh_cell_property_tables(cell_hdf)
    _assert_frames(_assembled(str(cell_hdf), batch_cells), expected)
    assert hashlib.sha256(cell_hdf.read_bytes()).digest() == before


def test_mesh_selection_and_unknown_mesh(cell_hdf):
    expected = HdfMesh.get_mesh_cell_property_tables(cell_hdf)
    _assert_frames(
        _assembled(cell_hdf, 2, mesh_name="Second"), {"Second": expected["Second"]}
    )
    assert (
        list(HdfMesh.iter_mesh_cell_property_tables(cell_hdf, mesh_name="absent")) == []
    )


def test_nonempty_batch_matches_declared_schema(cell_hdf):
    from ras_commander.schemas import DATAFRAME_SCHEMAS

    _, frame = next(HdfMesh.iter_mesh_cell_property_tables(cell_hdf))
    columns = DATAFRAME_SCHEMAS["mesh_cell_property_batch"]["columns"]
    assert list(frame) == [column["name"] for column in columns]
    assert [str(dtype) for dtype in frame.dtypes] == [
        column["dtype"] for column in columns
    ]


@pytest.mark.parametrize("batch_cells", [0, -1, True, 1.5, "2"])
def test_invalid_batch_budget(cell_hdf, batch_cells):
    with pytest.raises(ValueError, match="batch_cells"):
        HdfMesh.iter_mesh_cell_property_tables(cell_hdf, batch_cells=batch_cells)


@pytest.mark.parametrize(
    "info", [np.empty((0, 2), dtype="i4"), np.array([[0, 0], [2, 0]])]
)
def test_present_empty_tables_have_legacy_empty_schema(cell_hdf, info):
    with h5py.File(cell_hdf, "r+") as source:
        mesh = source["Geometry/2D Flow Areas/First"]
        del mesh["Cells Volume Elevation Info"]
        mesh.create_dataset("Cells Volume Elevation Info", data=info)
    expected = HdfMesh.get_mesh_cell_property_tables(cell_hdf)
    _assert_frames(_assembled(cell_hdf, 1), expected)


def test_reads_are_bounded_and_no_handles_survive_yield(cell_hdf, monkeypatch):
    original = batches.read_dataset
    reads = []
    datasets = []

    def record(dataset, selection, **kwargs):
        datasets.append(dataset)
        reads.append((dataset.name, selection[0]))
        return original(dataset, selection, **kwargs)

    monkeypatch.setattr(batches, "read_dataset", record)
    iterator = HdfMesh.iter_mesh_cell_property_tables(
        cell_hdf, mesh_name="First", batch_cells=2
    )
    first_name, first = next(iterator)
    assert first_name == "First" and len(first) == 3
    assert datasets and all(not dataset.id.valid for dataset in datasets)
    # On Windows this also refuses if an HDF/native session is still open.
    renamed = cell_hdf.with_name("renamed.g01.hdf")
    cell_hdf.rename(renamed)
    renamed.rename(cell_hdf)
    list(iterator)
    info_slices = [selection for name, selection in reads if name.endswith("Info")]
    value_slices = [selection for name, selection in reads if name.endswith("Values")]
    assert all(selection.stop - selection.start <= 2 for selection in info_slices)
    assert [(selection.start, selection.stop) for selection in value_slices] == [
        (2, 5),
        (9, 11),
        (1, 4),
        (22, 24),
    ]
    assert all(not dataset.id.valid for dataset in datasets)


def test_required_failure_is_not_swallowed(cell_hdf, monkeypatch):
    failure = fast_hdf.FastHdfError("injected native refusal")

    def refuse(*args, **kwargs):
        raise failure

    monkeypatch.setattr(batches, "read_dataset", refuse)
    with pytest.raises(fast_hdf.FastHdfError) as raised:
        list(HdfMesh.iter_mesh_cell_property_tables(cell_hdf))
    assert raised.value is failure


def test_auto_native_failure_falls_back_to_exact_python_frames(cell_hdf, monkeypatch):
    expected = _assembled(cell_hdf, 2)
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise RuntimeError("injected native refusal")

    # Native shape/path metadata remains real; only the native numeric call fails.
    monkeypatch.setattr(
        fast_hdf, "_native", lambda mode: SimpleNamespace(HdfSession=refuse)
    )
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    _assert_frames(_assembled(cell_hdf, 2), expected)
    assert attempts


def test_required_native_batches_match_python_and_close_sessions(cell_hdf, monkeypatch):
    if not fast_hdf.available():
        pytest.skip("published native extension unavailable")
    expected = _assembled(cell_hdf, 2)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    monkeypatch.setenv("RAS_COMMANDER_HDF_SESSION_CACHE", "persist")
    _assert_frames(_assembled(cell_hdf, 2), expected)
    assert not fast_hdf._sessions
