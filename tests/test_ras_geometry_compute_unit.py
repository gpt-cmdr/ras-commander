"""Unit tests for RasGeometryCompute guard logic (no HEC-RAS required).

These verify the fail-closed safety behavior surfaced by the Codex review:
the overwrite/backup guard must never run a destructive compute when it cannot
confirm existing state or produce a backup, validation must fail closed, and the
Windows guard and deprecated alias must behave as documented. They monkeypatch
the platform and the pythonnet-touching internals so they run anywhere.
"""

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

pytest.importorskip("geopandas")
pytest.importorskip("h5py")

from ras_commander import RasGeometryCompute, RasProcess
from ras_commander.schemas import DATAFRAME_SCHEMAS, SCHEMA_VERSION


@pytest.fixture
def geom_file(tmp_path):
    p = tmp_path / "model.g01.hdf"
    p.write_bytes(b"\x89HDF\r\n\x1a\n")  # dummy; existence is all that's checked
    return p


@pytest.fixture
def on_windows(monkeypatch):
    """Make _require_windows pass regardless of the host OS."""
    monkeypatch.setattr("platform.system", lambda: "Windows")


def _forbid_compute(monkeypatch):
    """Make reaching the pythonnet layer a hard failure."""
    def _boom(*a, **k):
        raise AssertionError("destructive compute must not run")
    monkeypatch.setattr(RasGeometryCompute, "_ensure_clr", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(RasGeometryCompute, "_load_geometry", staticmethod(_boom))


def test_windows_guard_raises(monkeypatch, geom_file):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="Windows"):
        RasGeometryCompute.generate_edge_lines(geom_file, overwrite=True)


def test_skip_when_present_no_compute(monkeypatch, on_windows, geom_file):
    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(lambda p, g: True))
    _forbid_compute(monkeypatch)
    r = RasGeometryCompute.generate_flow_paths(geom_file)  # overwrite=False
    assert r.success and r.skipped


def test_fail_closed_on_inspect_error(monkeypatch, on_windows, geom_file):
    def _raise(p, g):
        raise OSError("HDF locked")
    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(_raise))
    _forbid_compute(monkeypatch)
    r = RasGeometryCompute.generate_flow_paths(geom_file, overwrite=True)
    assert not r.success and "inspect" in (r.error or "").lower()


def test_fail_closed_backup_returns_none(monkeypatch, on_windows, geom_file):
    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(lambda p, g: True))
    monkeypatch.setattr(RasGeometryCompute, "_backup_layer", staticmethod(lambda p, t, r: None))
    _forbid_compute(monkeypatch)
    r = RasGeometryCompute.generate_flow_paths(geom_file, overwrite=True, backup=True)
    assert not r.success and "backup" in (r.error or "").lower()


def test_fail_closed_backup_raises(monkeypatch, on_windows, geom_file):
    def _raise_backup(p, t, r):
        raise IOError("disk full")
    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(lambda p, g: True))
    monkeypatch.setattr(RasGeometryCompute, "_backup_layer", staticmethod(_raise_backup))
    _forbid_compute(monkeypatch)
    r = RasGeometryCompute.generate_flow_paths(geom_file, overwrite=True, backup=True)
    assert not r.success and "backup failed" in (r.error or "").lower()


def test_backup_false_allows_overwrite_without_backup(monkeypatch, on_windows, geom_file):
    """With backup=False the caller has explicitly opted out; compute proceeds."""
    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(lambda p, g: True))
    reached = {"compute": False}
    monkeypatch.setattr(RasGeometryCompute, "_ensure_clr", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(RasGeometryCompute, "_resolve_rasmap", staticmethod(lambda *a, **k: None))

    class _FakeGeom:
        class FlowPathLines:
            @staticmethod
            def ComputeFlowPathLines():
                reached["compute"] = True
                return True
    monkeypatch.setattr(RasGeometryCompute, "_load_geometry", staticmethod(lambda *a, **k: _FakeGeom()))
    r = RasGeometryCompute.generate_flow_paths(geom_file, overwrite=True, backup=False)
    assert reached["compute"] is True
    assert r.backup_path is None


def test_compute_geometry_no_skip_when_interp_absent(monkeypatch, on_windows, geom_file):
    """overwrite=False must still run when edge lines exist but interp surface does not."""
    state = {"computed": False}

    def fake_layer_exists(p, group):
        if "River Edge Lines" in group:
            return True
        if "Interpolation Surface" in group:
            return state["computed"]   # absent before compute, present after
        return False  # flow paths

    class _FakeGeom:
        def CompleteForComputations(self, force, prog):
            state["computed"] = True
            return True

    monkeypatch.setattr(RasGeometryCompute, "_layer_exists", staticmethod(fake_layer_exists))
    monkeypatch.setattr(RasGeometryCompute, "_ensure_clr", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(RasGeometryCompute, "_resolve_rasmap", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(RasGeometryCompute, "_load_geometry", staticmethod(lambda *a, **k: _FakeGeom()))

    cr = RasGeometryCompute.compute_geometry(geom_file)  # overwrite=False
    assert state["computed"] is True, "must not skip when interpolation surface is absent"
    assert cr.success and cr.edge_lines_written and cr.interpolation_surface_written


def test_validate_fail_closed(monkeypatch, on_windows, geom_file):
    monkeypatch.setattr(RasGeometryCompute, "_ensure_clr", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(RasGeometryCompute, "_resolve_rasmap", staticmethod(lambda *a, **k: None))

    class _FakeGeom:
        def ValidateGeometry(self, flag):
            raise RuntimeError("validator crashed")
    monkeypatch.setattr(RasGeometryCompute, "_load_geometry", staticmethod(lambda *a, **k: _FakeGeom()))

    report = RasGeometryCompute.validate_geometry(geom_file)
    assert not report.empty
    assert (report["severity"] == "ERROR").any()
    assert RasGeometryCompute.is_valid_geometry(geom_file) is False


def test_parse_feature_name():
    assert RasGeometryCompute._parse_feature_name("White, Muncie (1980.776)") == \
        ("White", "Muncie", "1980.776")
    assert RasGeometryCompute._parse_feature_name("0, 0") == (None, None, None)
    assert RasGeometryCompute._parse_feature_name("") == (None, None, None)


def test_complete_geometry_alias_signature_preserved():
    assert (inspect.signature(RasProcess.complete_geometry)
            == inspect.signature(RasProcess.compute_geometry))


def test_rasprocess_compute_geometry_prefers_project_executable(monkeypatch, tmp_path):
    geom = tmp_path / "model.g01.hdf"
    geom.write_bytes(b"not a real hdf")
    ras_dir = tmp_path / "HEC-RAS"
    ras_dir.mkdir()
    ras_exe = ras_dir / "Ras.exe"
    rasprocess_exe = ras_dir / "RasProcess.exe"
    ras_exe.touch()
    rasprocess_exe.touch()
    project = SimpleNamespace(
        ras_exe_path=ras_exe, initialized=False, project_folder=None
    )
    captured = {}

    def fake_run(executable, args, **kwargs):
        captured["executable"] = Path(executable)
        captured["args"] = args
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        RasProcess,
        "find_rasprocess",
        staticmethod(lambda version=None: (_ for _ in ()).throw(
            AssertionError("version discovery should not run")
        )),
    )
    monkeypatch.setattr(RasProcess, "_run_rasprocess", staticmethod(fake_run))

    result = RasProcess.compute_geometry(geom, ras_object=project)

    assert captured["executable"] == rasprocess_exe
    assert captured["args"][0] == "CompleteGeometry"
    assert result["return_code"] == 0


def test_rasprocess_compute_geometry_rejects_stderr_error(monkeypatch, tmp_path):
    import h5py

    geom = tmp_path / "model.g01.hdf"
    with h5py.File(geom, "w") as hdf:
        hdf.create_group("Geometry/River Edge Lines")
    rasprocess_exe = tmp_path / "RasProcess.exe"
    rasprocess_exe.touch()

    monkeypatch.setattr(
        RasProcess, "find_rasprocess", staticmethod(lambda version=None: rasprocess_exe)
    )
    monkeypatch.setattr(
        RasProcess,
        "_run_rasprocess",
        staticmethod(lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="", stderr="Error: invalid argument"
        )),
    )

    result = RasProcess.compute_geometry(geom, ras_version="7.0")

    assert result["edge_lines_written"] is True
    assert result["return_code"] == 0
    assert result["success"] is False


def _diff_frames(left, channel, right):
    import geopandas as gpd
    from shapely.geometry import LineString
    line = LineString([(0, 0), (1, 0)])
    stored = gpd.GeoDataFrame({
        "River": ["R", "R", "R", "R"], "Reach": ["A", "A", "A", "A"],
        "RS": ["4", "3", "2", "1"],
        "Len Left": [100.0, 200.0, 300.0, 400.0],
        "Len Channel": [100.0, 200.0, 300.0, 400.0],
        "Len Right": [100.0, 200.0, 300.0, 400.0],
        "geometry": [line] * 4,
    })
    recomputed = gpd.GeoDataFrame({
        "River": ["R", "R", "R", "R"], "Reach": ["A", "A", "A", "A"],
        "RS": ["4", "3", "2", "1"],
        "Len Left": left, "Len Channel": channel, "Len Right": right,
        "geometry": [line] * 4,
    })
    return stored, recomputed


def test_reach_length_diff():
    nan = float("nan")
    # RS4: <tol; RS3: +10; RS2: partial NaN (invalid); RS1: all-NaN reach end
    stored, recomputed = _diff_frames(
        left=[100.2, 210.0, nan, nan],
        channel=[100.0, 200.0, 300.0, nan],
        right=[100.0, 200.0, 300.0, nan],
    )
    d = RasGeometryCompute._reach_length_diff(stored, recomputed, tolerance=0.5).set_index("RS")
    assert bool(d.loc["4", "changed"]) is False            # 0.2 < 0.5 tolerance
    assert bool(d.loc["3", "changed"]) is True and abs(d.loc["3", "delta_left"] - 10.0) < 1e-6
    assert bool(d.loc["2", "invalid_recompute"]) is True   # only left NaN -> anomaly
    assert bool(d.loc["2", "changed"]) is True             # invalid recompute is flagged
    assert bool(d.loc["2", "reach_end"]) is False
    assert bool(d.loc["1", "reach_end"]) is True           # all recomputed NaN
    assert bool(d.loc["1", "invalid_recompute"]) is False
    assert bool(d.loc["1", "changed"]) is False


def test_reach_length_diff_row_count_mismatch_raises():
    stored, recomputed = _diff_frames([1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4])
    with pytest.raises(ValueError, match="counts differ"):
        RasGeometryCompute._reach_length_diff(stored, recomputed.iloc[:3], tolerance=0.5)


def test_reach_length_diff_identity_mismatch_raises():
    stored, recomputed = _diff_frames([1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4])
    recomputed = recomputed.copy()
    recomputed.loc[0, "RS"] = "99"  # reorder/relabel -> identity mismatch
    with pytest.raises(ValueError, match="identity/order"):
        RasGeometryCompute._reach_length_diff(stored, recomputed, tolerance=0.5)


def test_audit_reach_lengths_rejects_bad_flow_paths_mode(geom_file):
    with pytest.raises(ValueError, match="flow_paths"):
        RasGeometryCompute.audit_reach_lengths(geom_file, flow_paths="bogus")


def test_audit_reach_lengths_rejects_negative_tolerance(geom_file):
    with pytest.raises(ValueError, match="tolerance"):
        RasGeometryCompute.audit_reach_lengths(geom_file, tolerance=-1.0)


def test_flow_path_policy_regenerate_when_overbanks_match():
    nan = float("nan")
    stored, recomputed = _diff_frames(
        left=[100.5, 199.0, 301.5, nan],
        channel=[100.0, 200.0, 300.0, nan],
        right=[99.5, 201.0, 298.5, nan],
    )
    audit = RasGeometryCompute._reach_length_diff(
        stored, recomputed, tolerance=0.0
    )
    metrics = RasGeometryCompute._augment_reach_length_metrics(audit, 0.01)
    summary = RasGeometryCompute._summarize_flow_path_policy(
        metrics,
        tolerance_fraction=0.01,
        source_flow_path_counts={("R", "A"): 0},
    )

    assert summary.iloc[0]["recommended_policy"] == "regenerate_and_recompute"
    assert summary.iloc[0]["overbank_match_fraction"] == 1.0
    assert summary.iloc[0]["reason_codes"] == ()
    assert list(metrics.columns) == [
        item["name"] for item in DATAFRAME_SCHEMAS["flow_path_policy_xs_metrics"]["columns"]
    ]
    assert list(summary.columns) == [
        item["name"]
        for item in DATAFRAME_SCHEMAS["flow_path_policy_reach_metrics"]["columns"]
    ]


def test_flow_path_policy_preserves_when_regeneration_does_not_match():
    nan = float("nan")
    stored, recomputed = _diff_frames(
        left=[102.0, 200.0, 300.0, nan],
        channel=[100.0, 200.0, 300.0, nan],
        right=[100.0, 200.0, 300.0, nan],
    )
    audit = RasGeometryCompute._reach_length_diff(
        stored, recomputed, tolerance=0.0
    )
    metrics = RasGeometryCompute._augment_reach_length_metrics(audit, 0.01)
    summary = RasGeometryCompute._summarize_flow_path_policy(
        metrics,
        tolerance_fraction=0.01,
        source_flow_path_counts={("R", "A"): 2},
    )

    assert (
        summary.iloc[0]["recommended_policy"]
        == "preserve_and_recompute_only_at_join_boundary"
    )
    assert "REGENERATED_OVERBANK_LENGTH_MISMATCH" in summary.iloc[0][
        "reason_codes"
    ]


def test_flow_path_policy_preserves_distinct_overbanks_without_source_paths():
    nan = float("nan")
    stored, recomputed = _diff_frames(
        left=[100.0, 200.0, 300.0, nan],
        channel=[100.0, 200.0, 300.0, nan],
        right=[100.0, 200.0, 300.0, nan],
    )
    stored.loc[0, "Len Left"] = 110.0
    recomputed.loc[0, "Len Left"] = 110.0
    audit = RasGeometryCompute._reach_length_diff(
        stored, recomputed, tolerance=0.0
    )
    metrics = RasGeometryCompute._augment_reach_length_metrics(audit, 0.01)
    summary = RasGeometryCompute._summarize_flow_path_policy(
        metrics,
        tolerance_fraction=0.01,
        source_flow_path_counts={("R", "A"): 0},
    )

    assert (
        summary.iloc[0]["recommended_policy"]
        == "preserve_and_recompute_only_at_join_boundary"
    )
    assert (
        "MISSING_SOURCE_FLOW_PATHS_WITH_DISTINCT_OVERBANK_LENGTHS"
        in summary.iloc[0]["reason_codes"]
    )


def test_main_channel_relative_error_is_informative():
    nan = float("nan")
    stored, recomputed = _diff_frames(
        left=[100.0, 200.0, 300.0, nan],
        channel=[102.0, 200.0, 300.0, nan],
        right=[100.0, 200.0, 300.0, nan],
    )
    audit = RasGeometryCompute._reach_length_diff(
        stored, recomputed, tolerance=0.0
    )
    metrics = RasGeometryCompute._augment_reach_length_metrics(audit, 0.01)

    first = metrics.set_index("RS").loc["4"]
    assert first["relative_error_channel"] == pytest.approx(0.02)
    assert bool(first["main_channel_flagged"])
    assert bool(first["overbank_lengths_within_tolerance"])


def test_measure_main_channel_lengths_uses_river_polyline_distance():
    import geopandas as gpd
    from shapely.geometry import LineString

    xs = gpd.GeoDataFrame(
        {
            "River": ["R", "R", "R"],
            "Reach": ["A", "A", "A"],
            "RS": ["30", "20", "10"],
            "Length_Channel": [2.0, 2.2, 0.0],
            "geometry": [
                LineString([(0, 4), (10, 4)]),
                LineString([(0, 2), (10, 2)]),
                LineString([(0, 0), (10, 0)]),
            ],
        },
        geometry="geometry",
        crs="EPSG:2277",
    )
    centerlines = gpd.GeoDataFrame(
        {
            "River": ["R"],
            "Reach": ["A"],
            "geometry": [LineString([(5, 5), (5, -1)])],
        },
        geometry="geometry",
        crs=xs.crs,
    )

    result = RasGeometryCompute._measure_main_channel_lengths(
        xs, centerlines, tolerance_fraction=0.01
    )
    indexed = result.set_index("RS")

    assert indexed.loc["30", "len_channel_recomputed"] == pytest.approx(2.0)
    assert bool(indexed.loc["30", "main_channel_flagged"]) is False
    assert indexed.loc["20", "relative_error_channel"] == pytest.approx(0.2 / 2.2)
    assert bool(indexed.loc["20", "main_channel_flagged"]) is True
    assert bool(indexed.loc["10", "reach_end"]) is True
    assert bool(indexed.loc["10", "main_channel_flagged"]) is False
    assert list(result.columns) == [
        item["name"]
        for item in DATAFRAME_SCHEMAS["main_channel_length_audit"]["columns"]
    ]


def test_clip_join_flow_path_segments_returns_review_geometry():
    import geopandas as gpd
    from shapely.geometry import LineString

    cross_sections = gpd.GeoDataFrame(
        {
            "River": ["River", "River"],
            "Reach": ["Main", "Main"],
            "RS": ["100", "90"],
            "geometry": [
                LineString([(0, 8), (10, 8)]),
                LineString([(0, 6), (10, 6)]),
            ],
        },
        geometry="geometry",
        crs="EPSG:2277",
    )
    centerlines = gpd.GeoDataFrame(
        {
            "River Name": ["River"],
            "Reach Name": ["Main"],
            "geometry": [LineString([(5, 10), (5, 0)])],
        },
        geometry="geometry",
        crs=cross_sections.crs,
    )
    flow_paths = gpd.GeoDataFrame(
        {
            "flow_path_id": [0, 1],
            "geometry": [
                LineString([(2, 10), (2, 0)]),
                LineString([(8, 10), (8, 0)]),
            ],
        },
        geometry="geometry",
        crs=cross_sections.crs,
    )

    segments = RasGeometryCompute._clip_join_flow_path_segments(
        flow_paths,
        cross_sections,
        centerlines,
        ("River", "Main", "100"),
        ("River", "Main", "90"),
    )

    assert list(segments["side"]) == ["left", "right"]
    assert list(segments["length"]) == pytest.approx([2.0, 2.0])
    assert bool(segments.geometry.is_valid.all())
    assert list(segments.columns) == [
        item["name"] for item in DATAFRAME_SCHEMAS["flow_path_join_segments"]["columns"]
    ]


def test_count_flow_paths_by_reach_requires_two_xs_intersections():
    import geopandas as gpd
    from shapely.geometry import LineString

    metrics = gpd.GeoDataFrame(
        {
            "River": ["R", "R", "R"],
            "Reach": ["A", "A", "A"],
            "geometry": [
                LineString([(0, 3), (10, 3)]),
                LineString([(0, 2), (10, 2)]),
                LineString([(0, 1), (10, 1)]),
            ],
        },
        geometry="geometry",
    )
    flow_paths = gpd.GeoDataFrame(
        {
            "geometry": [
                LineString([(2, 4), (2, 0)]),
                LineString([(8, 4), (8, 2.5)]),
            ]
        },
        geometry="geometry",
    )

    counts = RasGeometryCompute._count_flow_paths_by_reach(flow_paths, metrics)

    assert counts == {("R", "A"): 1}


@pytest.mark.parametrize("value", [-0.01, 1.01, float("inf")])
def test_flow_path_policy_rejects_invalid_fraction(value):
    with pytest.raises(ValueError, match="tolerance_fraction"):
        RasGeometryCompute._validate_tolerance_fraction(value)


def test_reach_length_policy_schema_version():
    assert SCHEMA_VERSION == "1.12"
