"""Union containment changes one preflight gate without relaxing source checks."""

from dataclasses import replace
from importlib import import_module

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from ras_commander import Breakout2DSpec

module = import_module("ras_commander.RasBreakout2D")


def checks(spec, union=None, **overrides):
    plan = pd.Series(
        {
            "geometry_type": "2D",
            "plan_type": "unsteady_2d",
            "plan_classification_valid": True,
        }
    )
    geometry = pd.Series(
        {**dict.fromkeys(module._UNSUPPORTED_STRUCTURE_COLUMNS, 0), **overrides}
    )
    child = spec.child_boundary
    segments = gpd.GeoDataFrame(
        {"length": [child.length]}, geometry=[child.boundary], crs=3857
    )
    features = gpd.GeoDataFrame(
        columns=["feature_type", "action", "name", "geometry"],
        geometry="geometry",
        crs=3857,
    )
    return module._build_checks(
        spec,
        plan,
        geometry,
        box(0, 0, 10, 10),
        child,
        segments,
        features,
        mesh_area_count=1,
        containment_parent=union,
    ).set_index("check_id")


def spec():
    return Breakout2DSpec("01", "Owner", box(2, 2, 18, 8), "union-test")


def test_contributor_identity_is_frozen_and_rechecked(tmp_path, monkeypatch):
    import hashlib

    from test_ras_breakout_2d_preparation import _preflight

    path = tmp_path / "Secondary.g01.hdf"
    path.write_bytes(b"qualified geometry")
    owner = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=3857)
    contributor = gpd.GeoDataFrame(geometry=[box(10, 0, 20, 10)], crs=3857)
    monkeypatch.setattr(module.HdfMesh, "get_mesh_areas", lambda path: contributor)
    declared = replace(spec(), contributing_geometry_hdfs=(path,))
    identities = []
    module._contributing_parent_union(declared, owner, identities=identities)
    preflight = _preflight(tmp_path / "owner")
    preflight.spec = declared
    preflight.contributing_geometry_identities = identities
    module._verify_contributing_geometry_snapshots(preflight)
    path.write_bytes(b"changed geometry")
    assert (
        preflight.to_manifest()["contributing_geometry_hdfs"][0]["sha256"]
        == hashlib.sha256(b"qualified geometry").hexdigest()
    )
    with pytest.raises(ValueError, match="changed since preflight"):
        module._verify_contributing_geometry_snapshots(preflight)


def test_contributor_mutation_during_read_rejected(tmp_path, monkeypatch):
    path = tmp_path / "Secondary.g01.hdf"
    path.write_bytes(b"before")
    owner = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=3857)

    def read_and_change(path):
        path.write_bytes(b"after")
        return gpd.GeoDataFrame(geometry=[box(10, 0, 20, 10)], crs=3857)

    monkeypatch.setattr(module.HdfMesh, "get_mesh_areas", read_and_change)
    with pytest.raises(RuntimeError, match="changed during preflight"):
        module._contributing_parent_union(
            replace(spec(), contributing_geometry_hdfs=(path,)), owner, identities=[]
        )


def test_straddling_child_requires_declared_union():
    baseline = checks(spec())
    union = checks(spec(), box(0, 0, 20, 10))
    assert not baseline.loc["child_within_parent", "passed"]
    assert union.loc["child_within_parent_union", "passed"]
    pd.testing.assert_frame_equal(
        baseline.drop("child_within_parent"), union.drop("child_within_parent_union")
    )
    assert union.loc["child_within_parent_union", "details"]["outside_parent_area"] > 0


def test_outside_union_still_blocks():
    assert not checks(spec(), box(0, 0, 15, 10)).loc[
        "child_within_parent_union", "passed"
    ]


def test_structures_still_block_in_union():
    assert not checks(spec(), box(0, 0, 20, 10), num_gates=1).loc[
        "unsupported_structures_absent", "passed"
    ]


def test_empty_contributors_preserve_single_parent():
    owner = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=3857)
    assert module._contributing_parent_union(spec(), owner) is None


def test_native_contributor_perimeters_supply_union(monkeypatch):
    owner = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=3857)
    contributor = gpd.GeoDataFrame(geometry=[box(10, 0, 20, 10)], crs=3857)
    monkeypatch.setattr(module.HdfMesh, "get_mesh_areas", lambda path: contributor)
    declared = replace(spec(), contributing_geometry_hdfs=("Secondary.g01.hdf",))
    assert module._contributing_parent_union(declared, owner).equals(box(0, 0, 20, 10))


@pytest.mark.parametrize("path", ["Secondary.p01.hdf", "unknown.hdf"])
def test_plan_results_rejected_before_read(monkeypatch, path):
    owner = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=3857)

    def no_read(path):
        pytest.fail("No payload may be read for a non-geometry contributor")

    monkeypatch.setattr(module.HdfMesh, "get_mesh_areas", no_read)
    with pytest.raises(ValueError, match="geometry .gNN.hdf"):
        module._contributing_parent_union(
            replace(spec(), contributing_geometry_hdfs=(path,)), owner
        )


@pytest.mark.parametrize("crs,count", [(4326, 1), (3857, 2), (None, 1)])
def test_mismatched_or_multiple_contributor_areas_rejected(monkeypatch, crs, count):
    owner = gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=3857)
    contributor = gpd.GeoDataFrame(geometry=[box(10, 0, 20, 10)] * count, crs=crs)
    monkeypatch.setattr(module.HdfMesh, "get_mesh_areas", lambda path: contributor)
    with pytest.raises(ValueError):
        module._contributing_parent_union(
            replace(spec(), contributing_geometry_hdfs=("Secondary.g01.hdf",)), owner
        )
