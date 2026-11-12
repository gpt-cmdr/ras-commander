"""Wrappers over ras-commander-fast-dss (0.1.1 API, run on 0.1.2): ``sync=`` on the RasDss writers,
``RasDss`` profile and location methods, and the ``RasDssGrid`` namespace.

Every wrapper passes its arguments to the engine and returns the engine's result
unchanged. These tests write small synthetic DSS files in ``tmp_path`` (and read the
public synthetic grid fixtures), and check the stored data, the pass-through and the
gating. No JVM is started and no HEC model is run. Skips without
ras_commander_fast_dss.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

dc = pytest.importorskip("ras_commander_fast_dss")

from ras_commander import RasDss, RasDssGrid  # noqa: E402
from ras_commander.dss import _backend, _errors  # noqa: E402

if not _backend.native_writes_available():  # pragma: no cover - depends on the wheel
    pytest.skip("installed ras-commander-fast-dss has no writers", allow_module_level=True)

TIMES = pd.date_range("2020-01-01 01:00", periods=24, freq="h")
TS_PATH = "/A/B/FLOW//1HOUR/F/"
PROFILE_PATH = "/LAKE/DAM/TEMP-WATER//1Day/OBS/"
DEPTHS = np.array([0.0, 5.0, 10.0])
PROFILE_VALUES = np.arange(12.0).reshape(4, 3)

# A 5 x 4 SHG grid of 2000 m cells, three hourly frames. Row 0 of FRAMES is north.
FRAMES = np.arange(3 * 4 * 5, dtype=np.float32).reshape(3, 4, 5)
T0 = dt.datetime(2020, 1, 1)
WINDOWS = [(T0 + dt.timedelta(hours=i), T0 + dt.timedelta(hours=i + 1)) for i in range(3)]
TRANSFORM = (100000.0, 2000.0, 208000.0, -2000.0)
GRID_PARTS = {"A": "SHG", "B": "TEST", "F": "SYN"}

# Two zones in longitude and latitude (NAD83) that split the grid between its second and
# third column, with a 1000 m margin outside it, so no cell centre is near an edge.
ZONE_WEST = [[-95.033091, 24.820631], [-94.984261, 24.820154], [-94.983216, 24.911567],
             [-95.032096, 24.912044], [-95.033091, 24.820631]]
ZONE_EAST = [[-94.984261, 24.820154], [-94.9159, 24.819447], [-94.914784, 24.910859],
             [-94.983216, 24.911567], [-94.984261, 24.820154]]


@pytest.fixture(autouse=True)
def native_backend(monkeypatch):
    monkeypatch.setattr(RasDss, "backend", "native")
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)


def _spy(monkeypatch, module, name):
    """Record the keyword arguments of every call to ``module.name``; still call it."""
    real = getattr(module, name)
    calls = []

    def wrapper(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)
    return calls


def _grid_info():
    return {"cellsize": 2000.0, "origin": (100000.0, 200000.0), "crs": "SHG",
            "units": "MM", "data_type": "PER-CUM"}


# ---------------------------------------------------------------------------
# sync= on the RasDss writers
# ---------------------------------------------------------------------------


def test_unstated_sync_is_not_passed_so_the_engine_default_applies(tmp_path, monkeypatch):
    calls = _spy(monkeypatch, dc, "write_timeseries")
    RasDss.write_timeseries(tmp_path / "a.dss", TS_PATH, TIMES, np.arange(24.0))
    assert len(calls) == 1 and "sync" not in calls[0]
    assert _backend.native_sync_kwargs() == {}


@pytest.mark.parametrize("sync", [False, True])
def test_write_timeseries_passes_sync_unchanged_and_stores_the_data(tmp_path, monkeypatch, sync):
    calls = _spy(monkeypatch, dc, "write_timeseries")
    target = tmp_path / "a.dss"
    RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0), sync=sync)
    assert calls[0]["sync"] is sync
    assert _backend.native_sync_kwargs() == {}  # the stated value does not outlive the call
    df = RasDss.read_timeseries(target, TS_PATH)
    np.testing.assert_array_equal(df["value"].to_numpy(), np.arange(24.0))


def test_sync_is_the_engines_value_not_a_bool_this_wrapper_checks(tmp_path, monkeypatch):
    """A value a later engine may add reaches the engine as given (0.1.2 refuses it)."""
    seen = []

    def fake(*args, **kwargs):
        seen.append(kwargs.get("sync"))
        return {"blocks": []}

    target = tmp_path / "a.dss"
    RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0))
    monkeypatch.setattr(dc, "write_timeseries", fake)
    RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0), sync="per_step")
    assert seen == ["per_step"]
    monkeypatch.undo()  # also restores the environment override, so clear it again
    monkeypatch.setattr(RasDss, "backend", "native")
    monkeypatch.delenv(_backend.ENV_VAR, raising=False)
    # The engine's own refusal, unchanged: TypeError in 0.1.1, ValueError in 0.1.2.
    with pytest.raises((TypeError, ValueError), match="sync"):
        RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0), sync="per_step")


def test_write_timeseries_from_dataframe_passes_sync(tmp_path, monkeypatch):
    calls = _spy(monkeypatch, dc, "write_timeseries")
    frame = pd.DataFrame({"value": np.arange(24.0)}, index=TIMES)
    RasDss.write_timeseries_from_dataframe(tmp_path / "a.dss", TS_PATH, frame, sync=False)
    assert calls[0]["sync"] is False


def test_write_paired_data_passes_sync(tmp_path, monkeypatch):
    calls = _spy(monkeypatch, dc, "write_paired_data")
    target = tmp_path / "pd.dss"
    RasDss.write_paired_data(
        target, "/A/B/STAGE-FLOW///F/", [1.0, 2.0, 3.0], [10.0, 20.0, 30.0],
        x_units="FT", y_units="CFS", x_type="LINEAR", y_type="LINEAR", sync=False,
    )
    assert calls[0]["sync"] is False
    frame = RasDss.read_paired_data(target, "/A/B/STAGE-FLOW///F/")
    np.testing.assert_array_equal(frame.iloc[:, -1].to_numpy(), [10.0, 20.0, 30.0])
    RasDss.write_paired_data(
        target, "/A/B/STAGE-FLOW///G/", [1.0, 2.0], [10.0, 20.0],
        x_units="FT", y_units="CFS", x_type="LINEAR", y_type="LINEAR",
    )
    assert "sync" not in calls[1]


def test_write_grid_timeseries_passes_sync_to_every_record(tmp_path, monkeypatch):
    calls = _spy(monkeypatch, dc, "write_grid")
    target = tmp_path / "grid.dss"
    stamps = [T0 + dt.timedelta(hours=i) for i in range(4)]
    written = RasDss.write_grid_timeseries(
        target, "/SHG/TEST/PRECIP///SYN/", FRAMES, stamps[1:], _grid_info(), sync=False,
    )
    assert len(written) == len(calls) == 3
    assert all(call["sync"] is False for call in calls)
    grid = RasDss.read_grid(target, written[0])
    assert grid["data"].shape == (4, 5)


def test_copy_grid_with_zero_tail_passes_sync(tmp_path, monkeypatch):
    source = tmp_path / "grid.dss"
    stamps = [T0 + dt.timedelta(hours=i) for i in range(1, 4)]
    RasDss.write_grid_timeseries(source, "/SHG/TEST/PRECIP///SYN/", FRAMES, stamps, _grid_info())
    calls = _spy(monkeypatch, dc, "write_grid")
    result = RasDss.copy_grid_with_zero_tail(
        source, tmp_path / "tail.dss", "/SHG/TEST/PRECIP///SYN/", 2, sync=False,
    )
    assert calls and all(call["sync"] is False for call in calls)
    assert (tmp_path / "tail.dss").exists() and result


def test_write_precip_grid_arrays_passes_sync(tmp_path, monkeypatch):
    pytest.importorskip("affine")
    pytest.importorskip("pyproj")
    calls = _spy(monkeypatch, dc, "write_grid")
    bounds = pd.date_range("2020-01-01", periods=4, freq="h")
    paths = RasDss.write_precip_grid_arrays(
        tmp_path / "precip.dss", "/UTM15/BASIN/PRECIP///SYN/", FRAMES, bounds,
        transform=(2000.0, 0.0, 500000.0, 0.0, -2000.0, 3308000.0), crs="EPSG:26915",
        units="mm", sync=False,
    )
    assert len(paths) == len(calls) == 3
    assert all(call["sync"] is False for call in calls)


def test_stated_sync_needs_the_engine_feature_and_touches_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "FEATURES", frozenset(dc.FEATURES) - {"write_sync_policy"})
    assert RasDss.get_capabilities().attrs["native_write_sync_available"] is False
    target = tmp_path / "gated.dss"
    with pytest.raises(_errors.get("DssCapabilityError"), match="write_sync_policy"):
        RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0), sync=False)
    assert not target.exists()
    RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0))  # unstated still writes
    assert target.exists()
    monkeypatch.undo()
    assert _backend.native_sync_available() is True


def test_java_backend_does_not_use_sync_and_a_nested_unstated_call_keeps_it():
    with _backend.write_sync(False, "java"):
        assert _backend.native_sync_kwargs() == {"sync": False}
        with _backend.write_sync(None, "native"):
            assert _backend.native_sync_kwargs() == {"sync": False}
        with _backend.write_sync(True, "native"):
            assert _backend.native_sync_kwargs() == {"sync": True}
        assert _backend.native_sync_kwargs() == {"sync": False}
    assert _backend.native_sync_kwargs() == {}
    assert _backend.native_sync_kwargs(True) == {"sync": True}


# ---------------------------------------------------------------------------
# Profiles and locations
# ---------------------------------------------------------------------------


def _write_profile(target, **kwargs):
    return RasDss.write_profile(
        target, PROFILE_PATH, DEPTHS, PROFILE_VALUES, start="01JAN2024 2400",
        depth_units="ft", value_units="DEG F", data_type="INST-VAL", **kwargs,
    )


@pytest.mark.parametrize("backend", ["java", "native", "shadow"])
def test_profile_round_trip_runs_on_the_engine_on_every_backend(tmp_path, monkeypatch, backend):
    monkeypatch.setattr(RasDss, "backend", backend)
    target = tmp_path / "profile.dss"
    report = _write_profile(target)
    assert report["blocks"][0]["record_type"] == 107
    assert dc.file_signature(target)["version"] == 7
    profile = RasDss.read_profile(target, PROFILE_PATH)
    assert isinstance(profile, dc.Profile)
    np.testing.assert_array_equal(profile.depths, DEPTHS)
    np.testing.assert_array_equal(profile.values, PROFILE_VALUES)
    assert (profile.depth_units, profile.value_units) == ("ft", "DEG F")
    frame = profile.to_dataframe()
    assert frame.shape == (4, 3)
    assert frame.index[0] == pd.Timestamp("2024-01-02")
    window = RasDss.read_profile(target, PROFILE_PATH, "03JAN2024 0000", "04JAN2024 0000")
    np.testing.assert_array_equal(window.values, PROFILE_VALUES[1:3])


def test_write_profile_passes_sync_and_other_options(tmp_path, monkeypatch):
    calls = _spy(monkeypatch, dc, "write_profile")
    target = tmp_path / "profile.dss"
    _write_profile(target)
    _write_profile(target, sync=False, value_type="double", quality=[0, 0, 0, 0])
    assert "sync" not in calls[0]
    assert calls[1]["sync"] is False and calls[1]["value_type"] == "double"
    assert RasDss.read_profile(target, PROFILE_PATH).quality is not None


def test_write_profile_file_rules(tmp_path):
    missing = tmp_path / "missing.dss"
    with pytest.raises(FileNotFoundError):
        _write_profile(missing, create_if_missing=False)
    assert not missing.exists()
    with pytest.raises(ValueError):  # the engine refuses a 1-D values array
        RasDss.write_profile(
            missing, PROFILE_PATH, DEPTHS, np.arange(3.0), start="01JAN2024 2400",
            depth_units="ft", value_units="DEG F", data_type="INST-VAL",
        )
    assert not missing.exists()  # the file this call created is removed again
    dss6 = tmp_path / "six.dss"
    RasDss.write_timeseries(dss6, TS_PATH, TIMES, np.arange(24.0), dss_version=6)
    with pytest.raises(ValueError, match="version 6"):
        _write_profile(dss6)


def test_read_profile_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        RasDss.read_profile(tmp_path / "missing.dss", PROFILE_PATH)
    target = tmp_path / "ts.dss"
    RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0))
    with pytest.raises(dc.DssUnsupportedRecordError):
        RasDss.read_profile(target, TS_PATH)
    with pytest.raises(dc.DssPathnameNotFoundError):
        RasDss.read_profile(target, PROFILE_PATH)


def test_location_round_trip_dss7(tmp_path, monkeypatch):
    calls = _spy(monkeypatch, dc, "write_location")
    target = tmp_path / "loc.dss"
    RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0))
    assert RasDss.read_associated_location(target, TS_PATH) is None
    report = RasDss.write_location(target, TS_PATH, x=-90.07, y=29.95, z=3.2,
                                   supplemental="note:test", sync=False)
    assert calls[0]["sync"] is False
    assert report["blocks"][0]["pathname"] == "/A/B/Location Info////"
    location = RasDss.read_associated_location(target, TS_PATH)
    assert isinstance(location, dc.Location)
    assert location.coordinates == (-90.07, 29.95, 3.2)
    assert location.supplemental == "note:test"
    assert RasDss.read_location(target, "/A/B/Location Info////").coordinates == (-90.07, 29.95, 3.2)
    RasDss.write_location(target, TS_PATH, z=4.0)  # a partial update keeps the other fields
    assert "sync" not in calls[1]
    assert RasDss.read_associated_location(target, TS_PATH).coordinates == (-90.07, 29.95, 4.0)
    with pytest.raises(dc.DssPathnameNotFoundError):
        RasDss.read_location(target, "/NO/SUCH/Location Info////")


def test_location_in_a_dss6_time_series_header(tmp_path):
    target = tmp_path / "six.dss"
    RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0), dss_version=6)
    RasDss.write_location(target, TS_PATH, x=1.5, y=2.5, z=3.5)
    assert RasDss.read_associated_location(target, TS_PATH).coordinates == (1.5, 2.5, 3.5)
    df = RasDss.read_timeseries(target, TS_PATH)
    np.testing.assert_array_equal(df["value"].to_numpy(), np.arange(24.0))
    with pytest.raises(dc.DssUnsupportedRecordError):
        RasDss.read_location(target, "/A/B/Location Info////")


def test_location_needs_an_existing_file(tmp_path):
    missing = tmp_path / "missing.dss"
    for call in (lambda: RasDss.write_location(missing, TS_PATH, x=1.0),
                 lambda: RasDss.read_location(missing, TS_PATH),
                 lambda: RasDss.read_associated_location(missing, TS_PATH)):
        with pytest.raises(FileNotFoundError):
            call()
    assert not missing.exists()


@pytest.mark.parametrize("feature, attr, call", [
    ("write_profile", "native_profile_write_available",
     lambda target: _write_profile(target)),
    ("write_location", "native_location_write_available",
     lambda target: RasDss.write_location(target, TS_PATH, x=1.0)),
])
def test_profile_and_location_writers_are_gated_on_engine_features(
    tmp_path, monkeypatch, feature, attr, call
):
    target = tmp_path / "gated.dss"
    RasDss.write_timeseries(target, TS_PATH, TIMES, np.arange(24.0))
    before = target.read_bytes()
    monkeypatch.setattr(dc, "FEATURES", frozenset(dc.FEATURES) - {feature})
    assert RasDss.get_capabilities().attrs[attr] is False
    with pytest.raises(_errors.get("DssCapabilityError"), match=feature):
        call(target)
    assert target.read_bytes() == before
    monkeypatch.undo()
    assert RasDss.get_capabilities().attrs[attr] is True


def test_capabilities_list_the_engine_only_operations():
    caps = RasDss.get_capabilities().set_index("operation")
    for operation in ("read_profile", "write_profile", "read_location",
                      "read_associated_location", "write_location"):
        assert list(caps.loc[operation, ["java", "native", "shadow"]]) == ["gated"] * 3
        assert callable(getattr(RasDss, operation))


# ---------------------------------------------------------------------------
# RasDssGrid
# ---------------------------------------------------------------------------


@pytest.fixture
def grids(tmp_path):
    """Three hourly SHG precipitation grids imported from arrays."""
    target = tmp_path / "grids.dss"
    result = RasDssGrid.import_arrays(
        FRAMES, target, times=WINDOWS, transform=TRANSFORM, crs="SHG",
        variable="precipitation", source_units="mm", parts=GRID_PARTS,
    )
    assert [record["outcome"] for record in result.records] == ["added"] * 3
    return target, result.pathnames


@pytest.fixture
def zones(tmp_path):
    path = tmp_path / "zones.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"NAME": "WEST"},
         "geometry": {"type": "Polygon", "coordinates": [ZONE_WEST]}},
        {"type": "Feature", "properties": {"NAME": "EAST"},
         "geometry": {"type": "Polygon", "coordinates": [ZONE_EAST]}},
    ]}))
    return path


def test_namespace_is_exported_and_static():
    import ras_commander
    from ras_commander.dss import RasDssGrid as from_subpackage

    assert ras_commander.RasDssGrid is RasDssGrid is from_subpackage
    assert "RasDssGrid" in ras_commander.__all__
    assert set(_backend.GRIDDED_FEATURES) <= set(vars(RasDssGrid))
    for name in _backend.GRIDDED_FEATURES:
        assert callable(getattr(dc.gridded, name)), name
    assert all(RasDssGrid.get_features().values())


def test_import_arrays_writes_the_frames(grids):
    target, pathnames = grids
    assert pathnames[0] == "/SHG/TEST/PRECIPITATION/01JAN2020:0000/01JAN2020:0100/SYN/"
    info = RasDssGrid.series_info(target, pathnames[0])
    assert (info["records"], info["nx"], info["ny"], info["units"]) == (3, 5, 4, "MM")
    assert (info["start"], info["end"]) == ("01JAN2020:0000", "01JAN2020:0300")
    stored = RasDss.read_grid(target, pathnames[1])["data"]
    assert sorted(np.asarray(stored).ravel().tolist()) == FRAMES[1].ravel().tolist()


def test_import_gridded_reads_an_ascii_grid(tmp_path):
    source = tmp_path / "depth.asc"
    source.write_text(
        "ncols 3\nnrows 2\nxllcorner 100000\nyllcorner 200000\ncellsize 2000\n"
        "NODATA_value -9999\n1 2 3\n4 5 6\n"
    )
    (tmp_path / "depth.prj").write_text(dc.SHG_WKT)
    assert isinstance(RasDssGrid.list_variables(source), list)
    target = tmp_path / "out.dss"
    result = RasDssGrid.import_gridded(
        source, target, variable=RasDssGrid.list_variables(source)[0], target_crs=None,
        cell_size=None, parts={"A": "SHG", "B": "ASC", "C": "DEPTH", "F": "T"},
        units="MM", data_type="INST-VAL", sync=False,
    )
    assert len(result.pathnames) == 1
    stored = np.asarray(RasDss.read_grid(target, result.pathnames[0])["data"])
    assert sorted(stored.ravel().tolist()) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]



@pytest.mark.parametrize("method", ["near", "bilinear", "average"])
def test_resampling_method_keyword_reaches_the_engine(tmp_path, monkeypatch, method):
    """``method=`` is the engine's resampling option; the wrapper must not take it."""
    source = tmp_path / "depth.asc"
    source.write_text("\n".join([
        "ncols 4", "nrows 4", "xllcorner 100000", "yllcorner 200000", "cellsize 1000",
        "NODATA_value -9999", "1 2 3 4", "5 6 7 8", "9 10 11 12", "13 14 15 16", "",
    ]))
    (tmp_path / "depth.prj").write_text(dc.SHG_WKT)
    calls = _spy(monkeypatch, dc.gridded, "import_gridded")
    result = RasDssGrid.import_gridded(
        source, tmp_path / "out.dss", variable=RasDssGrid.list_variables(source)[0],
        target_crs="SHG", cell_size=2000, method=method,
        parts={"A": "SHG", "B": "ASC", "C": "DEPTH", "F": method.upper()},
        units="MM", data_type="INST-VAL",
    )
    assert calls[0]["method"] == method
    assert len(result.pathnames) == 1

def test_calculate_and_sanitize(grids, tmp_path):
    target, pathnames = grids
    doubled = RasDssGrid.calculate(target, tmp_path / "x2.dss", multiply=2.0,
                                   parts={**GRID_PARTS, "F": "X2"})
    assert len(doubled.pathnames) == 3 and doubled.pathnames[0].endswith("/X2/")
    np.testing.assert_array_equal(
        np.asarray(RasDss.read_grid(tmp_path / "x2.dss", doubled.pathnames[0])["data"]),
        2 * np.asarray(RasDss.read_grid(target, pathnames[0])["data"]),
    )
    floored = RasDssGrid.sanitize(target, tmp_path / "floor.dss", minimum=5.0,
                                  minimum_replacement=0.0, parts=GRID_PARTS)
    cells = np.asarray(RasDss.read_grid(tmp_path / "floor.dss", floored.pathnames[0])["data"])
    source = np.asarray(RasDss.read_grid(target, pathnames[0])["data"])
    np.testing.assert_array_equal(cells, np.where(source <= 5.0, 0.0, source))


def test_calculate_raster_with_a_static_dss_factor(grids, tmp_path):
    target, pathnames = grids
    result = RasDssGrid.calculate_raster(
        target, target, tmp_path / "sq.dss", operation="multiply",
        raster_variable=pathnames[0], variables=[pathnames[0]], parts=GRID_PARTS,
    )
    cells = np.asarray(RasDss.read_grid(tmp_path / "sq.dss", result.pathnames[0])["data"])
    source = np.asarray(RasDss.read_grid(target, pathnames[0])["data"])
    np.testing.assert_array_equal(cells, source * source)


def test_clip_keeps_the_cells_inside_the_envelope(grids, tmp_path):
    target, _ = grids
    result = RasDssGrid.clip(target, tmp_path / "clip.dss", parts=GRID_PARTS,
                             envelope=(102000.0, 202000.0, 108000.0, 206000.0),
                             envelope_crs="SHG")
    assert {(r["nx"], r["ny"]) for r in result.records} == {(3, 2)}
    assert {(r["lower_left_cell_x"], r["lower_left_cell_y"]) for r in result.records} == {(51, 101)}


def test_normalize_scales_to_the_normals(grids, tmp_path):
    target, pathnames = grids
    normals = tmp_path / "normals.dss"
    RasDssGrid.calculate(target, normals, multiply=3.0, parts={**GRID_PARTS, "F": "NORMAL"})
    result = RasDssGrid.normalize(
        target, normals, tmp_path / "norm.dss", start=T0, end=T0 + dt.timedelta(hours=3),
        interval=dt.timedelta(hours=3), parts=GRID_PARTS,
    )
    assert result.sources_left_out == [] and result.normals_left_out == []
    assert result.intervals[0]["sources"] == result.intervals[0]["normals"] == 3
    source = np.asarray(RasDss.read_grid(target, pathnames[2])["data"])
    cells = np.asarray(RasDss.read_grid(tmp_path / "norm.dss", pathnames[2])["data"])
    np.testing.assert_allclose(cells, 3.0 * source, rtol=1e-6)


def test_time_tools(grids, tmp_path):
    target, pathnames = grids
    shifted = RasDssGrid.shift_times(target, tmp_path / "shift.dss",
                                     shift=dt.timedelta(hours=6), parts=GRID_PARTS)
    assert shifted.pathnames[0] == "/SHG/TEST/PRECIPITATION/01JAN2020:0600/01JAN2020:0700/SYN/"
    np.testing.assert_array_equal(
        np.asarray(RasDss.read_grid(tmp_path / "shift.dss", shifted.pathnames[0])["data"]),
        np.asarray(RasDss.read_grid(target, pathnames[0])["data"]),
    )
    assert 180 in RasDssGrid.time_steps()
    resampled = RasDssGrid.resample_times(target, tmp_path / "3h.dss", 180, parts=GRID_PARTS)
    assert resampled.pathnames == ["/SHG/TEST/PRECIPITATION/01JAN2020:0000/01JAN2020:0300/SYN/"]
    assert resampled.dropped_tail_seconds == 0
    total = np.asarray(RasDss.read_grid(tmp_path / "3h.dss", resampled.pathnames[0])["data"])
    assert float(total.sum()) == float(FRAMES.sum())  # PER-CUM keeps the volume
    window = RasDssGrid.read_window(target, pathnames[0], "01JAN2020:0000", "01JAN2020:0300")
    np.testing.assert_array_equal(window.data, FRAMES.sum(axis=0)[::-1])  # rows south to north
    nearest = RasDssGrid.read_nearest(target, pathnames[0], "01JAN2020:0100")
    np.testing.assert_array_equal(nearest.data, FRAMES[1][::-1])
    low, high = RasDssGrid.read_min_max(target, pathnames[0], "01JAN2020:0000", "01JAN2020:0300")
    np.testing.assert_array_equal(low.data, FRAMES[0][::-1])
    np.testing.assert_array_equal(high.data, FRAMES[2][::-1])


def test_zonal_statistics_and_grid_to_point(grids, zones, tmp_path):
    target, _ = grids
    masks = RasDssGrid.zone_masks(target, zones, "NAME", assume_no_datum_shift=True)
    assert {name: len(cells) for name, cells in masks.items()} == {"WEST": 8, "EAST": 12}
    table = RasDssGrid.zonal_statistics(target, zones, "NAME", assume_no_datum_shift=True)
    assert isinstance(table, pd.DataFrame) and len(table) == 6
    west = np.array([FRAMES[i][:, :2].mean() for i in range(3)])
    east = np.array([FRAMES[i][:, 2:].mean() for i in range(3)])
    out = tmp_path / "points.dss"
    result = RasDssGrid.grid_to_point(target, zones, "NAME", out,
                                      assume_no_datum_shift=True,
                                      parts={"A": "SHG", "F": "SYN"})
    assert result.pathnames == ["/SHG/WEST/PRECIP-INC//1Hour/SYN/",
                                "/SHG/EAST/PRECIP-INC//1Hour/SYN/"]
    for pathname, expected in zip(result.pathnames, (west, east)):
        df = RasDss.read_timeseries(out, pathname)
        np.testing.assert_allclose(df["value"].to_numpy(), expected, rtol=1e-6)
        assert df.index[0] == pd.Timestamp("2020-01-01 01:00")


def test_zonal_statistics_frame_matches_its_schema(grids, zones):
    """The live RasDssGrid.zonal_statistics frame against schemas.DATAFRAME_SCHEMAS."""
    from pandas.api import types

    from ras_commander.schemas import DATAFRAME_SCHEMAS

    schema = DATAFRAME_SCHEMAS["dss_grid_zonal_statistics"]
    target, _ = grids
    table = RasDssGrid.zonal_statistics(target, zones, "NAME", assume_no_datum_shift=True)
    assert list(table.columns) == [column["name"] for column in schema["columns"]]
    assert schema["extra_columns"] is False and schema["dynamic"] is False
    assert isinstance(table.index, pd.RangeIndex)
    checks = {
        "str": lambda s: types.is_string_dtype(s) or types.is_object_dtype(s),
        "datetime64": types.is_datetime64_dtype,
        "float64": lambda s: s.dtype == np.float64,
    }
    for column in schema["columns"]:
        assert checks[column["dtype"]](table[column["name"]]), (column["name"], table[column["name"]].dtype)
    assert table["units"].eq("MM").all()
    assert table["pct_gt_0"].between(0, 100).all() and table["pct_gt_q1"].between(0, 100).all()
    # Rows by frame, then zone (in the zones file's order).
    assert list(table["zone"]) == ["WEST", "EAST"] * 3
    assert (table["end"] > table["start"]).all()


def test_read_tools_on_the_public_grid_fixture():
    fixture = Path(__file__).parent / "fixtures" / "dss_native_public" / "synthetic_grid7.dss"
    if not fixture.exists():  # pragma: no cover
        pytest.skip("public grid fixture not present")
    pathname = "/PUBLIC/ALBERS/PRECIP/01JAN2020:0000/01JAN2020:0100/SYNTH/"
    info = RasDssGrid.series_info(fixture, pathname)
    assert (info["records"], info["data_type"], info["nx"], info["ny"]) == (1, "PER-CUM", 2, 2)
    nearest = RasDssGrid.read_nearest(fixture, pathname, "01JAN2020:0000")
    stored = np.asarray(RasDss.read_grid(fixture, pathname)["data"], dtype=np.float32)
    np.testing.assert_array_equal(np.sort(nearest.data.ravel()), np.sort(stored.ravel()))


def test_sync_reaches_the_engine_tools_only_when_stated(grids, tmp_path, monkeypatch):
    target, _ = grids
    calls = _spy(monkeypatch, dc.gridded, "calculate")
    RasDssGrid.calculate(target, tmp_path / "a.dss", add=1.0, parts=GRID_PARTS)
    RasDssGrid.calculate(target, tmp_path / "b.dss", add=1.0, parts=GRID_PARTS, sync=False)
    assert "sync" not in calls[0]
    assert calls[1]["sync"] is False


def test_sync_on_a_tool_without_the_option_is_a_capability_error(
        grids, zones, tmp_path, monkeypatch):
    target, _ = grids

    def grid_to_point_0_1_1(grids, zones, zone_field, output, *, statistics=("average",),
                            assume_no_datum_shift=False):  # no sync= (0.1.1)
        raise AssertionError("must not be called")

    monkeypatch.setattr(dc.gridded, "grid_to_point", grid_to_point_0_1_1)
    out = tmp_path / "points.dss"
    with pytest.raises(_errors.get("DssCapabilityError"), match="sync"):
        RasDssGrid.grid_to_point(target, zones, "NAME", out, assume_no_datum_shift=True,
                                 sync=False)
    assert not out.exists()


def test_tools_are_gated_on_engine_features(grids, tmp_path, monkeypatch):
    target, _ = grids
    monkeypatch.setattr(dc, "FEATURES", frozenset(dc.FEATURES) - {"grid_tools"})
    assert RasDssGrid.get_features()["grid_tools"] is False
    with pytest.raises(_errors.get("DssCapabilityError"), match="grid_tools"):
        RasDssGrid.calculate(target, tmp_path / "gated.dss", add=1.0)
    assert not (tmp_path / "gated.dss").exists()
    assert RasDssGrid.time_steps()  # another feature group is unaffected


def test_a_refused_run_leaves_no_output(grids, tmp_path):
    target, _ = grids
    out = tmp_path / "refused.dss"
    with pytest.raises(ValueError):
        RasDssGrid.calculate(target, out, add=1.0, multiply=2.0)
    assert not out.exists()
