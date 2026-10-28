"""Complete cell identity, dry conventions and atomic caller-profile staging."""

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from ras_commander.fim._supplied_wsel import DRY, snapshot, stage
from ras_commander.fim.errors import FimUnsupportedError


@pytest.fixture
def table():
    return pd.DataFrame(dict(mesh_name=["A", "A", "A", "B", "B"],
        cell_id=[0, 1, 2, 0, 1], q1=[10., -0., np.nan, -9999., 20.],
        q2=[11., 12., 13., 14., 15.]))


MESHES = [dict(mesh_name="B", cell_count=2), dict(mesh_name="A", cell_count=3)]


def test_shuffled_local_ids_preserve_bits_dry_marker_and_all_meshes(table, tmp_path):
    before = table.copy(deep=True)
    supplied = snapshot(table.sample(frac=1, random_state=13), tmp_path / "p.hdf")
    units, size, metadata = stage(supplied, tmp_path, MESHES)
    assert size == 40
    assert metadata["kind"] == "caller-cell-wsel/1"
    assert list(supplied.selection) == ["q1", "q2"]
    values = np.fromfile(tmp_path / units[0]["values_files"][1], dtype="<f4")
    np.testing.assert_array_equal(values.view("u4"), np.array([10., -0., DRY], dtype="<f4").view("u4"))
    np.testing.assert_array_equal(np.fromfile(tmp_path / units[0]["values_files"][0], dtype="<f4"), [-9999., 20.])
    pd.testing.assert_frame_equal(table, before)


def test_snapshot_owns_values_and_hashes_ignore_row_order(table, tmp_path):
    supplied = snapshot(table, tmp_path / "p.hdf")
    table.loc[:, "q1"] = 999.
    assert supplied.values["q1"][0] == 10.
    assert not supplied.values["q1"].flags.writeable
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir(); second.mkdir()
    _, _, a = stage(supplied, first, MESHES)
    reordered = pd.DataFrame(dict(mesh_name=["B", "A", "B", "A", "A"],
        cell_id=[1, 2, 0, 1, 0], q1=[20., np.nan, -9999., -0., 10.], q2=[15., 13., 14., 12., 11.]))
    _, _, b = stage(snapshot(reordered, tmp_path / "p.hdf"), second, MESHES)
    assert a["profiles"] == b["profiles"]


@pytest.mark.parametrize("bad", [np.inf, -np.inf, 1e300, True, "12", 2+1j])
def test_invalid_values_refuse(table, tmp_path, bad):
    table["q1"] = bad
    with pytest.raises(ValueError):
        snapshot(table, tmp_path / "p.hdf")


@pytest.mark.parametrize("ids", [[0., 1., 2., 0., 1.], [0, -1, 2, 0, 1],
    [True]*5, ["0", "1", "2", "0", "1"], [0, 1, 2, 0, 2**63]])
def test_invalid_cell_identity_types_refuse(table, tmp_path, ids):
    table["cell_id"] = ids
    with pytest.raises(ValueError):
        snapshot(table, tmp_path / "p.hdf")


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "unknown_mesh", "out_of_range", "extra"])
def test_missing_extra_and_duplicate_including_ghost_ids_refuse_before_files(table, tmp_path, mutation):
    if mutation == "duplicate":
        table.loc[2, "cell_id"] = 1
    elif mutation == "missing":
        table = table.drop(index=2)  # A:2 is a required perimeter/ghost row.
    elif mutation == "unknown_mesh":
        table.loc[0, "mesh_name"] = "Unknown"
    elif mutation == "out_of_range":
        table.loc[2, "cell_id"] = 9
    else:
        table.loc[5] = ["A", 3, 1., 2.]
    with pytest.raises(ValueError):
        stage(snapshot(table, tmp_path / "p.hdf"), tmp_path, MESHES)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("names", [["q1", "Q1"], ["CON", "q2"], ["nul.txt", "q2"],
    ["q.", "q2"], ["bad/name", "q2"], ["..", "q2"], ["q1", "q1"]])
def test_unsafe_and_colliding_output_names_refuse(table, tmp_path, names):
    table.columns = ["mesh_name", "cell_id", *names]
    with pytest.raises(ValueError):
        snapshot(table, tmp_path / "p.hdf")


def test_source_and_crs_binding(table, tmp_path):
    table.attrs["fim_source_hdf"] = str(tmp_path / "p.hdf")
    table.attrs["crs"] = "EPSG:2871"
    supplied = snapshot(table, tmp_path / "p.hdf")
    supplied.check_crs("EPSG:2871")
    with pytest.raises(ValueError, match="CRS"):
        supplied.check_crs("EPSG:3433")
    with pytest.raises(ValueError, match="source HDF"):
        snapshot(table, tmp_path / "other.hdf")


def test_exclusive_selectors_and_budgets(table, tmp_path):
    with pytest.raises(ValueError, match="mutually exclusive"):
        snapshot(table, tmp_path / "p.hdf", profiles={"q1": "Max"})
    with pytest.raises(FimUnsupportedError, match="snapshot"):
        snapshot(table, tmp_path / "p.hdf", max_bytes=1)
    with pytest.raises(FimUnsupportedError, match="max_prepared"):
        stage(snapshot(table, tmp_path / "p.hdf"), tmp_path, MESHES, max_staged_bytes=1)
    assert not list(tmp_path.iterdir())


def test_staging_failure_cleans_only_owned_files(table, tmp_path, monkeypatch):
    from ras_commander.fim import _horizontal_engine
    (tmp_path / "keep").write_text("original")
    write = _horizontal_engine._write_array
    calls = []
    def fail(path, values):
        calls.append(path)
        write(path, values)
        if len(calls) == 2:
            raise OSError("injected write failure")
    monkeypatch.setattr(_horizontal_engine, "_write_array", fail)
    with pytest.raises(OSError, match="injected"):
        stage(snapshot(table, tmp_path / "p.hdf"), tmp_path, MESHES)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep"]


def test_preexisting_staged_values_preserved(table, tmp_path):
    destination = tmp_path / "values-1-1.bin"
    destination.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        stage(snapshot(table, tmp_path / "p.hdf"), tmp_path, MESHES)
    assert destination.read_bytes() == b"original"
    assert len(list(tmp_path.iterdir())) == 1


def test_nullable_numeric_dry_cells(table, tmp_path):
    table["q1"] = pd.array([10., pd.NA, 12., 13., 14.], dtype="Float64")
    assert snapshot(table, tmp_path / "p.hdf").values["q1"][1] == DRY


def test_public_api_passes_supplied_table_without_selector_substitution(table, tmp_path, monkeypatch):
    from ras_commander import RasFim
    from ras_commander.fim import _sloping
    seen = {}
    def record(*args, **kwargs):
        seen.update(kwargs)
        return "called"
    monkeypatch.setattr(_sloping, "map_profiles", record)
    assert RasFim.map_sloping_profiles("p.hdf", "terrain.tif", tmp_path, wsel_profiles=table) == "called"
    assert seen["wsel_profiles"] is table and seen["profiles"] is None
