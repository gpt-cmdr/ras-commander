"""Fail-closed spatial qualification of removable external connections."""

import os
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

mod = import_module('ras_commander.RasBreakout2D')


def classify(tmp_path, xy, **metadata):
    geom_file = tmp_path / "source.g01"
    name = metadata.get("Name", "Outside")
    routing = metadata.get("Conn Routing Type", 1)
    area = "Missing" if metadata.get("Type") == "Unknown" else "Area"
    coord_lines = [f"{x:16.7f}{y:16.7f}\n" for x, y in xy]
    lines = [
        "Geom Title=Control test\n",
        "Storage Area=Area,0,0\n",
        "Storage Area Is2D=-1\n",
        f"Connection={name},20,5\n",
        f"Connection Line={len(xy)}\n",
        *coord_lines,
        f"Connection Up SA={area}\n",
        f"Connection Dn SA={area}\n",
        f"Conn Routing Type={routing}\n",
        "Conn Weir WD=0.1\n",
        "Conn Weir Coef=1.5\n",
        "Conn Weir SE=2\n",
        "       0       3       6       3\n",
    ]
    if metadata.get("HasCulvert"):
        lines.append("Connection Culv=unknown\n")
    if metadata.get("HasGate"):
        lines.append("Conn Gate Name unsupported\n")
    geom_file.write_text("".join(lines), encoding="utf-8")
    return mod._classify_outside_connections(geom_file, box(0, 0, 10, 10), 0.01)


def test_verified_external_connection_retains_spatial_evidence(tmp_path):
    row = classify(tmp_path, [(20, 2), (20, 8)])[0]
    assert row['action'] == 'drop'
    assert row['name'] == 'Outside'
    assert row["geometry"].area > 0
    assert row['retained_measure'] == 0
    assert row["reason"]


@pytest.mark.parametrize(
    "xy",
    [
        [(5, -1), (5, 11)],
        [(10, 2), (10, 8)],
        [(10.005, 2), (10.005, 8)],
        [],
        [(20, 2)],
        [(np.nan, 2), (20, 8)],
    ],
)
def test_intersecting_or_unknown_extent_is_blocked(tmp_path, xy):
    assert classify(tmp_path, xy)[0]["action"] == "block"


def test_retained_inside_connection_is_kept(tmp_path):
    assert classify(tmp_path, [(2, 2), (8, 8)])[0]["action"] == "keep"


@pytest.mark.parametrize(
    "metadata",
    [
        {"HasCulvert": True},
        {"HasGate": True},
        {"Conn Routing Type": 32},
        {"Conn Routing Type": None},
        {"Type": "Unknown"},
        {"Name": ""},
    ],
)
def test_unqualified_extended_structures_fail_closed(tmp_path, metadata):
    assert classify(tmp_path, [(20, 2), (20, 8)], **metadata)[0]["action"] == "block"


def test_duplicate_names_block(tmp_path):
    classify(tmp_path, [(20, 2), (20, 8)])
    geom_file = tmp_path / "source.g01"
    raw = geom_file.read_text(encoding="utf-8")
    geom_file.write_text(raw + raw[raw.index("Connection=") :], encoding="utf-8")
    rows = mod._classify_outside_connections(geom_file, box(0, 0, 10, 10), 0.01)
    assert all(r['action'] == 'block' for r in rows)


@pytest.mark.parametrize(
    "count,other,action,expected",
    [
        (1, 0, "drop", True),
        (2, 0, "drop", False),
        (1, 1, "drop", False),
        (1, 0, "block", False),
        (0, 0, "drop", False),
        (1, 0, "keep", True),
    ],
)
def test_check_requires_inventory_agreement_and_no_other_structures(
    count, other, action, expected
):
    child = box(0, 0, 10, 10)
    actions = gpd.GeoDataFrame([{'feature_type': 'sa_2d_connection',
                                 'action': action, 'name': 'Outside', 'geometry': None}], crs=3857)
    checks = mod._build_checks(
        mod.Breakout2DSpec('01', 'Area', child, 'test'),
        pd.Series({'geometry_type': '2D', 'plan_type': 'unsteady_2d', 'plan_classification_valid': True}),
        pd.Series({'num_sa_2d_connections': count, 'num_bridges': other}),
        box(-10, -10, 30, 30), child, pd.DataFrame({'length': [40.]}), actions,
        mesh_area_count=1,
    )
    assert bool(checks.set_index('check_id').loc['unsupported_structures_absent', 'passed']) is expected


def test_real_austin_connection_outside_candidate():
    project = os.environ.get('RAS_TEST_AUSTIN_PROJECT')
    boundary = os.environ.get('RAS_TEST_AUSTIN_BOUNDARY')
    if not project or not boundary:
        pytest.skip('Set Austin project and boundary paths for real-source qualification')
    child = gpd.read_file(boundary).to_crs(6588).geometry.iloc[0]
    rows = mod._classify_outside_connections(Path(project)/'AustinOyster.g02', child, .001)
    assert len(rows) == 1
    assert rows[0]['name'] == '08079000'
    assert rows[0]['action'] == 'drop'
    assert rows[0]['geometry'].distance(child) > 40000


@pytest.mark.parametrize(
    "refresh,changed", [(False, False), (True, True), (True, False)]
)
def test_prepare_validates_decisions_before_any_text_edits(
    tmp_path, monkeypatch, refresh, changed
):
    classify(tmp_path, [(20, 2), (20, 8)])
    source_geom = tmp_path / "source.g01"
    unsteady = tmp_path / "child.u02"
    unsteady.write_bytes(b"unchanged unsteady")
    actions = gpd.GeoDataFrame(
        [
            {
                "feature_type": "sa_2d_connection",
                "name": "Outside",
                "action": "drop",
                "geometry": None,
            }
        ],
        crs=3857,
    )
    preflight = SimpleNamespace(
        is_ready=True,
        feature_actions=actions,
        child_boundary=gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=3857),
        spec=SimpleNamespace(containment_tolerance=0.001),
        connection_data=mod.GeomLateral.get_connection_data(source_geom),
    )
    clone = SimpleNamespace(
        boundaries_unchanged=True,
        unsteady_path=unsteady,
        cloned_unsteady_sha256=mod._sha256_file(unsteady),
        geometry_path=source_geom,
    )
    monkeypatch.setattr(
        mod,
        "_classify_outside_connections",
        lambda *_: [{"name": "Outside", "action": "block" if changed else "drop"}],
    )
    deleted = []
    monkeypatch.setattr(
        mod.GeomLateral,
        "delete_connection",
        lambda path, name, **_: deleted.append((path, name)),
    )

    def stop_before_other_edits(_):
        raise RuntimeError("stopped after verified deletion")

    monkeypatch.setattr(mod, "_retained_breakline_specs", stop_before_other_edits)
    if not refresh or changed:
        with pytest.raises(ValueError):
            mod.RasBreakout2D.prepare_cloned_geometry(
                preflight, clone, ras_object=None, refresh_hdf=refresh, remesh=False
            )
        assert not deleted
    else:
        with pytest.raises(RuntimeError, match="stopped after verified deletion"):
            mod.RasBreakout2D.prepare_cloned_geometry(
                preflight, clone, ras_object=None, refresh_hdf=True, remesh=False
            )
        assert not deleted
    assert unsteady.read_bytes() == b"unchanged unsteady"
