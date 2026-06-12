"""Unit tests for GeomCulvertGIS pure-logic helpers.

End-to-end reconstruction and validation are exercised against the real
georeferenced USGS Squannacook stream-crossing model in
examples/204_culvert_gis_validation.ipynb (the primary validation per repo
testing policy). These tests cover the deterministic helper logic that needs no
HEC-RAS project: HDS-5 entrance-loss lookup, taxonomy inlet-label resolution,
and the per-zone reach-length selector.
"""
from pathlib import Path

import pytest

from ras_commander.geom import GeomCulvertGIS


class TestRecommendedKe:
    def test_groove_end_is_low_loss(self):
        assert GeomCulvertGIS._recommended_ke("Groove end entrance with headwall") == 0.2

    def test_square_edge_headwall(self):
        assert GeomCulvertGIS._recommended_ke("Square edge with headwall") == 0.5

    def test_mitered(self):
        assert GeomCulvertGIS._recommended_ke("Mitered to conform to slope") == 0.7

    def test_thin_wall_projecting_is_high(self):
        assert GeomCulvertGIS._recommended_ke("Thin wall projecting") == 0.9

    def test_unknown_label_returns_none(self):
        assert GeomCulvertGIS._recommended_ke("not a real inlet") is None

    def test_none_label_returns_none(self):
        assert GeomCulvertGIS._recommended_ke(None) is None

    def test_case_insensitive(self):
        assert GeomCulvertGIS._recommended_ke("GROOVE END") == 0.2

    def test_specific_wingwall_not_shadowed_by_generic_bevel(self):
        # Regression (QAQC M1): a specific wingwall-flare label that also contains
        # a generic edge word must resolve to the wingwall value (0.4), not have
        # the generic "beveled" (0.2) steal the match.
        assert GeomCulvertGIS._recommended_ke(
            "Wingwall flared 30 to 75 deg with beveled edge") == 0.4

    def test_thick_wall_projecting_specific(self):
        assert GeomCulvertGIS._recommended_ke("Thick wall projecting") == 0.7


class TestScaleLabel:
    def test_circular_chart1_scale1(self):
        # Chart 1 / Scale 1 maps to a square-edge headwall inlet
        label = GeomCulvertGIS._scale_label(1, 1)
        assert label is not None
        assert "square edge" in label.casefold()

    def test_invalid_returns_none(self):
        assert GeomCulvertGIS._scale_label(999, 999) is None

    def test_non_numeric_returns_none(self):
        assert GeomCulvertGIS._scale_label("x", "y") is None


class TestReachLengthAt:
    def test_left_overbank(self):
        assert GeomCulvertGIS._reach_length_at(10.0, left_bank=50, right_bank=80,
                                               lob=84.7, channel=86.9, rob=89.1) == 84.7

    def test_channel(self):
        assert GeomCulvertGIS._reach_length_at(65.0, left_bank=50, right_bank=80,
                                               lob=84.7, channel=86.9, rob=89.1) == 86.9

    def test_right_overbank(self):
        assert GeomCulvertGIS._reach_length_at(95.0, left_bank=50, right_bank=80,
                                               lob=84.7, channel=86.9, rob=89.1) == 89.1


def test_constants_are_sane():
    assert GeomCulvertGIS.TYPICAL_EXIT_LOSS == 1.0
    assert 0 < GeomCulvertGIS.ENTRANCE_LOSS_TOLERANCE < 1
    # HDS-5 table is ordered most-specific-first and non-empty
    assert len(GeomCulvertGIS.HDS5_ENTRANCE_LOSS) > 5


# ---------------------------------------------------------------------------
# Model-based regression tests against the real Squannacook stream-crossing
# geometry. These require network access (one-time ~9 MB download) and skip
# cleanly when the model cannot be fetched. They exercise the public
# reconstruct_barrels / validate_placement paths and the QAQC-fixed behaviors
# (consistent reach-length basis -> length near 40 ft; local-bed invert check).
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def squannacook_dir(tmp_path_factory):
    from ras_commander.sources.federal.usgs_sciencebase import UsgsScienceBase
    out = tmp_path_factory.mktemp("squannacook")
    try:
        UsgsScienceBase.download_model("squannacook", out, required_only=True)
    except Exception as exc:  # offline / ScienceBase unavailable
        pytest.skip(f"Squannacook model unavailable: {exc}")
    prj = UsgsScienceBase.get_project_path("squannacook", out)
    if not prj.exists():
        pytest.skip("Squannacook project not extracted")
    return prj.parent


# Meadow Road crossing (river 40273_Unnamed Tr) appears in every geometry variant.
MEADOW = ("40273_Unnamed Tr", "Meadow Road", "73")


class TestReconstructionRegression:
    def test_meadow_road_length_within_tolerance(self, squannacook_dir):
        # QAQC C1 regression: with a consistent reach-length basis the
        # reconstructed length must be close to the entered 40 ft (was 8.75% off).
        geom = squannacook_dir / "Squannacook.g06"  # existing pipe
        barrels = GeomCulvertGIS.reconstruct_barrels(geom, *MEADOW)
        assert len(barrels) == 1
        row = barrels.iloc[0]
        assert row["entered_length"] == 40.0
        assert row["length_error_pct"] < 3.0  # was 8.75 before the C1 fix

    def test_pipe_invert_buried_box_at_grade(self, squannacook_dir):
        # The SCS pipe sets the invert ~2 ft below the local bed (FAIL); the box
        # retrofit sits at grade (PASS).
        rep_pipe = GeomCulvertGIS.validate_placement(
            squannacook_dir / "Squannacook.g06", *MEADOW)
        rep_box = GeomCulvertGIS.validate_placement(
            squannacook_dir / "Squannacook.g16", *MEADOW)

        def status(rep, check):
            return rep[rep["check"] == check].iloc[0]["status"]

        assert status(rep_pipe, "us_invert") == "FAIL"
        assert status(rep_pipe, "ds_invert") == "FAIL"
        assert status(rep_box, "us_invert") == "PASS"
        assert status(rep_box, "ds_invert") == "PASS"

    def test_us_distance_scoped_to_reach(self, squannacook_dir):
        # _structure_us_distances must find exactly the culverts in this reach's
        # structure block (count matches get_culverts -> no raise, all placed).
        geom = squannacook_dir / "Squannacook.g06"
        barrels = GeomCulvertGIS.reconstruct_barrels(geom, *MEADOW)
        assert not barrels["planimetric_length"].isna().any()


# ---------------------------------------------------------------------------
# 2D: terrain-based mesh-cell-minimum invert validation. Requires rasterio, a
# generated 2D mesh, and a terrain raster; uses the BaldEagleCrkMulti2D example
# (downloaded once). Skips cleanly when rasterio or the model is unavailable.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def baldeagle_2d(tmp_path_factory):
    pytest.importorskip("rasterio")
    from ras_commander import RasExamples
    out = tmp_path_factory.mktemp("baldeagle2d")
    try:
        proj = Path(RasExamples.extract_project(
            "BaldEagleCrkMulti2D", output_path=out, suffix="culv2dtest"))
    except Exception as exc:
        pytest.skip(f"BaldEagleCrkMulti2D unavailable: {exc}")
    geom_hdf = proj / "BaldEagleDamBrk.g01.hdf"
    geom = proj / "BaldEagleDamBrk.g01"
    if not geom_hdf.exists():
        pytest.skip("BaldEagle geometry HDF not extracted")
    return geom, geom_hdf


def _connection_points(geom):
    from ras_commander.geom import GeomLateral
    from shapely.geometry import LineString
    import numpy as np
    conns = GeomLateral.get_connections(geom)
    twod = conns[conns["Type"] == "2D to 2D"]
    name = (twod.iloc[0] if len(twod) else conns.iloc[0])["Name"]
    line = GeomLateral.get_connection_line_coords(geom, name)
    ls = LineString(line[["X", "Y"]].to_numpy())
    return [(p.x, p.y) for p in (ls.interpolate(d, normalized=True)
                                 for d in np.linspace(0.2, 0.8, 4))]


class TestTerrainCellMin:
    def test_cell_min_from_terrain(self, baldeagle_2d):
        geom, geom_hdf = baldeagle_2d
        pts = _connection_points(geom)
        df = GeomCulvertGIS.mesh_cell_min_from_terrain(geom_hdf, pts)
        assert len(df) == len(pts)
        assert df["cell_id"].notna().all()
        assert df["cell_terrain_min"].notna().all()
        # Bald Eagle terrain elevations are a few hundred feet
        assert df["cell_terrain_min"].between(400, 900).all()

    def test_validate_2d_inverts_flags_too_low(self, baldeagle_2d):
        geom, geom_hdf = baldeagle_2d
        pts = _connection_points(geom)
        cmins = GeomCulvertGIS.mesh_cell_min_from_terrain(geom_hdf, pts)["cell_terrain_min"]
        too_low = [m - 5.0 for m in cmins]      # 5 ft below cell min -> all FAIL
        at_grade = [m + 1.0 for m in cmins]     # 1 ft above cell min -> all PASS
        rep_low = GeomCulvertGIS.validate_2d_inverts(geom_hdf, pts, too_low)
        rep_ok = GeomCulvertGIS.validate_2d_inverts(geom_hdf, pts, at_grade)
        assert (rep_low["status"] == "FAIL").all()
        assert (rep_ok["status"] == "PASS").all()

    def test_validate_2d_inverts_length_mismatch_raises(self, baldeagle_2d):
        geom, geom_hdf = baldeagle_2d
        pts = _connection_points(geom)
        with pytest.raises(ValueError):
            GeomCulvertGIS.validate_2d_inverts(geom_hdf, pts, [500.0])  # wrong length

    def test_offmesh_point_reported_not_validated(self, baldeagle_2d):
        # QAQC H2: a point far off the mesh must be OFF_MESH, not validated
        # against an arbitrary distant cell.
        geom, geom_hdf = baldeagle_2d
        pts = _connection_points(geom)
        off = [(pts[0][0] + 1_000_000.0, pts[0][1])]
        rep = GeomCulvertGIS.validate_2d_inverts(geom_hdf, off, [500.0],
                                                 max_dist_to_cell=500.0)
        assert rep.iloc[0]["status"] == "OFF_MESH"

    def test_all_touched_false_not_below_all_touched_true(self, baldeagle_2d):
        # QAQC H1: the default (pixel-center) minimum must not be LOWER than the
        # all_touched=True minimum (which can import neighbour-cell lows).
        geom, geom_hdf = baldeagle_2d
        pts = _connection_points(geom)
        strict = GeomCulvertGIS.mesh_cell_min_from_terrain(geom_hdf, pts, all_touched=False)
        loose = GeomCulvertGIS.mesh_cell_min_from_terrain(geom_hdf, pts, all_touched=True)
        for s, l in zip(strict["cell_terrain_min"], loose["cell_terrain_min"]):
            if s is not None and l is not None:
                assert s >= l - 1e-6
