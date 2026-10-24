"""Unit tests of the subdomain breakout helpers that need no HEC-RAS runtime."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("shapely")
from shapely.geometry import Polygon, box  # noqa: E402

from ras_commander.subdomain import _breakouts as bo  # noqa: E402


def test_perimeter_stretch_follows_shared_parent_edges():
    parent = box(0, 0, 100, 100)
    # Child in the parent's lower-left corner: its west and south sides lie on the parent perimeter.
    child = Polygon([(0, 0), (40, 0), (40, 30), (0, 30)])
    pieces = bo._perimeter_stretches(child, parent)
    assert len(pieces) == 1  # one contiguous stretch around the corner
    assert pieces[0].length == pytest.approx(70.0)


def test_perimeter_stretches_split_where_the_child_leaves_the_edge():
    parent = box(0, 0, 100, 100)
    # A U-shaped child along the south edge, notched up into the interior in the middle.
    child = Polygon([(10, 0), (30, 0), (30, 20), (60, 20), (60, 0), (90, 0), (90, 40), (10, 40)])
    pieces = sorted(bo._perimeter_stretches(child, parent), key=lambda g: g.length)
    assert [round(g.length, 6) for g in pieces] == [20.0, 30.0]


def test_interior_child_has_no_perimeter_stretch():
    assert bo._perimeter_stretches(box(20, 20, 40, 40), box(0, 0, 100, 100)) == []


def test_whole_parent_is_one_closed_stretch():
    parent = box(0, 0, 100, 100)
    pieces = bo._perimeter_stretches(parent, parent)
    assert len(pieces) == 1 and pieces[0].length == pytest.approx(400.0)


def test_result_hdf_pattern():
    assert bo._RESULT_HDF.search("Model.p01.hdf")
    assert bo._RESULT_HDF.search("Model.p12.tmp.hdf")
    assert not bo._RESULT_HDF.search("Model.g01.hdf")
    assert not bo._RESULT_HDF.search("Model.u01.hdf")
    assert not bo._RESULT_HDF.search("Model.p01")


def _fake_project(root: Path) -> SimpleNamespace:
    (root / "Input").mkdir(parents=True)
    (root / "Terrain").mkdir()
    (root / "Input" / "M.prj").write_text("Proj Title=M\n")
    (root / "Input" / "M.g01").write_text("Geom Title=g\n")
    (root / "Input" / "M.g01.hdf").write_bytes(b"geometry")
    (root / "Input" / "M.p01").write_text("Plan Title=p\n")
    (root / "Input" / "M.p01.hdf").write_bytes(b"results")
    (root / "Terrain" / "Terrain.hdf").write_bytes(b"terrain")
    rasmap_df = pd.DataFrame({"terrain_hdf_path": [[str(root / "Terrain" / "Terrain.hdf")]],
                              "projection_path": [None]})
    return SimpleNamespace(prj_file=str(root / "Input" / "M.prj"), rasmap_df=rasmap_df)


def test_working_copy_keeps_sibling_assets_and_skips_results(tmp_path):
    ras = _fake_project(tmp_path / "parent")
    prj, record = bo._stage_working_copy(ras, tmp_path / "work")
    assert prj == tmp_path / "work" / "Input" / "M.prj"
    assert (tmp_path / "work" / "Terrain" / "Terrain.hdf").read_bytes() == b"terrain"
    assert (tmp_path / "work" / "Input" / "M.g01.hdf").is_file()
    assert not (tmp_path / "work" / "Input" / "M.p01.hdf").exists()
    assert record["skipped_result_hdfs"] == [str(tmp_path / "parent" / "Input" / "M.p01.hdf")]
    assert (tmp_path / "parent" / "Input" / "M.p01.hdf").is_file()  # parent untouched


def test_working_copy_refuses_destination_inside_parent(tmp_path):
    ras = _fake_project(tmp_path / "parent")
    with pytest.raises(ValueError, match="outside the parent"):
        bo._stage_working_copy(ras, tmp_path / "parent" / "Input" / "work")


def test_blocking_labels_cover_uncuttable_shapes():
    assert set(bo.BLOCKING_LABELS) == {"HOLES", "MULTIPART", "STRUCTURE_ON_SPLIT_LINE"}
    assert "INTERIOR_SUBDOMAIN" not in bo.BLOCKING_LABELS  # a band between split lines can be cut


@pytest.mark.parametrize("text, expected", [
    ("Computation Interval=30SEC\nComputation Time Step Use Courant=        -1\n"
     "Computation Time Step Max Halving=1\n", "15SEC"),
    ("Computation Interval=1MIN\nComputation Time Step Use Courant=-1\n"
     "Computation Time Step Max Halving=2\n", "15SEC"),
    ("Computation Interval=2MIN\nComputation Time Step Use Courant= 0\n", "2MIN"),
    ("Computation Interval=10SEC\n", "10SEC"),
])
def test_parent_minimum_interval(tmp_path, text, expected):
    plan = tmp_path / "M.p01"
    plan.write_text("Plan Title=p\n" + text)
    assert bo.parent_minimum_interval(plan) == expected


def test_parent_minimum_interval_requires_an_interval(tmp_path):
    plan = tmp_path / "M.p01"
    plan.write_text("Plan Title=p\n")
    with pytest.raises(ValueError, match="Computation Interval"):
        bo.parent_minimum_interval(plan)
