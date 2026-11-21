"""Coupled mapping with an invalid physical 2D cell ring (opt-in shared invalid-cell policy).

Strict native assembly refuses a mesh in which one cell's perimeter face
crosses another face of the same cell. The coupled route keeps that refusal by
default; ``invalid_cells="repair"``/``"hull"`` applies the shared policy of the
2D sloping route to the refused cells only and records them, and refuses any
result that would split or empty a physical cell.
"""
import geopandas as gpd
import pytest
from shapely.geometry import box

from ras_commander import HdfMesh
from ras_commander.fim import FimUnsupportedError
from ras_commander.fim import _coupled, _invalid_cells
from ras_commander.hdf.HdfMesh import MeshCellPolygonError


def _cells():
    return gpd.GeoDataFrame({"mesh_name": ["m", "m"], "cell_id": [0, 1]},
                            geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs="EPSG:6477")


def _refusing_strict(monkeypatch):
    def strict(*args, **kwargs):
        raise MeshCellPolygonError("cell 1: cell ring self-intersection or nonadjacent touch")
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", strict)


def _record(**overrides):
    record = dict(mesh="m", cell_id=1, reason="cell ring self-intersection", action="repaired",
                  original_area=1.0, fallback_area=0.99, pieces=1, overlap_with=[], extent=box(1, 0, 2, 1))
    record.update(overrides)
    return record


def test_default_keeps_strict_refusal(monkeypatch):
    _refusing_strict(monkeypatch)
    with pytest.raises(MeshCellPolygonError, match="self-intersection"):
        _coupled._coupled_cells("model.p01.hdf", 1, None)


def test_valid_mesh_keeps_strict_polygons_under_a_policy(monkeypatch):
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda *a, **k: _cells())
    monkeypatch.setattr(_invalid_cells, "load_cells", lambda *a, **k: pytest.fail("non-strict path used"))
    cells, record = _coupled._coupled_cells("model.p01.hdf", 1, "repair")
    assert len(cells) == 2 and record == {"policy": "repair", "cells": []}


def test_repair_records_rebuilt_cell(monkeypatch):
    _refusing_strict(monkeypatch)
    monkeypatch.setattr(_invalid_cells, "load_cells", lambda *a, **k: (_cells(), [_record()]))
    cells, record = _coupled._coupled_cells("model.p01.hdf", 2, "repair")
    assert len(cells) == 2
    assert record["policy"] == "repair"
    (cell,) = record["cells"]
    assert (cell["mesh"], cell["cell_id"], cell["action"], cell["pieces"]) == ("m", 1, "repaired", 1)
    assert "extent" not in cell


@pytest.mark.parametrize("bad", [dict(pieces=2), dict(fallback_area=0.0), dict(fallback_area=None)])
def test_split_or_empty_cells_are_refused(monkeypatch, bad):
    _refusing_strict(monkeypatch)
    monkeypatch.setattr(_invalid_cells, "load_cells", lambda *a, **k: (_cells(), [_record(**bad)]))
    with pytest.raises(FimUnsupportedError, match="one polygon per physical cell"):
        _coupled._coupled_cells("model.p01.hdf", 1, "repair")


@pytest.mark.parametrize("policy", ["omit", "raise", "fix"])
def test_only_single_polygon_policies_are_offered(policy):
    with pytest.raises(ValueError, match="invalid_cells must be None or one of"):
        _coupled.prepare_coupled_model("missing.p01.hdf", "missing.tif", "out", allow_unqualified=True,
                                       invalid_cells=policy)


# Real repair through the shared helper (no mocks of load_cells), on the synthetic
# self-crossing meshes of test_fim_invalid_cells.
@pytest.mark.parametrize("policy, action", [("repair", "repaired"), ("hull", "convex_hull")])
def test_real_self_crossing_cell_is_rebuilt_as_one_polygon_per_cell(tmp_path, policy, action):
    pytest.importorskip("ras_commander_fast_hdf")
    from test_fim_invalid_cells import MAIN_LOBE_AREA, _write_bowtie_mesh

    hdf = _write_bowtie_mesh(tmp_path / "bowtie.hdf")
    with pytest.raises(MeshCellPolygonError):
        _coupled._coupled_cells(hdf, 1, None)
    cells, record = _coupled._coupled_cells(hdf, 1, policy)
    assert cells["cell_id"].tolist() == [0, 1, 2]  # one ownership row per physical cell
    assert cells.geometry.is_valid.all()
    rebuilt = {c["cell_id"]: c for c in record["cells"]}
    assert rebuilt[0]["action"] == action and rebuilt[0]["pieces"] == 1
    if policy == "repair":
        assert rebuilt[0]["fallback_area"] == pytest.approx(MAIN_LOBE_AREA)
    assert rebuilt[2]["action"] == "overlap_trimmed" and rebuilt[2]["pieces"] == 1


def test_real_repair_that_splits_a_neighbour_is_refused(tmp_path):
    pytest.importorskip("ras_commander_fast_hdf")
    from test_fim_invalid_cells import _write_cells

    hdf = _write_cells(tmp_path / "split.hdf", [box(4, -1, 6, 11), box(0, 0, 10, 10)])
    with pytest.raises(FimUnsupportedError, match="one polygon per physical cell"):
        _coupled._coupled_cells(hdf, 1, "repair")
