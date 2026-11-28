"""Engine forms of ras-commander-fast-map 0.23.0 reaching the effective-terrain caller.

fast-map's ``feat/terrain-mods-native-parity`` branch (unreleased) reproduces
four forms that older engines refuse: polygon boundary elevations sampled from
the terrain, ground lines without a profile (RAS Mapper's default profile),
consecutive repeated ground-line vertices, and a terrain source tagged with
another NAD83 realization of the session's projection, pinned by its WKT hash.
The caller lifts its own refusals for them only for an engine at
``_effective_terrain.ENGINE_FORMS_MIN_VERSION`` and only under the 7.0.1 rule;
an older engine keeps every refusal. Parity with RAS Mapper is qualified in
fast-map (``feature_dev_notes/effective_terrain_modifications``).

The unit tests use synthetic HDFs. The real-data tests use the
BaldEagleCrkMulti2D example terrain (``Terrain50``, two sources, EPSG:2271)
and run only when ``RAS_COMMANDER_FIM_ENGINE_FORMS_ENGINE`` names a
``ras2fim-batch`` built from that branch. A build of the branch still reports
0.22.0, so those tests stand in the release number for it (and check that the
real 0.22.0 report keeps the forms refused).
"""

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
rasterio = pytest.importorskip("rasterio")
pyproj = pytest.importorskip("pyproj")

from ras_commander.fim import RasFim, _effective_terrain, _terrain_mods  # noqa: E402
from ras_commander.fim.errors import FimUnsupportedError  # noqa: E402

from test_fim_terrain_mods import (  # noqa: E402
    _capture_request, _control_point_group, _ground_line, _hdf, _polygon, _Stop,
)
from test_fim_terrain_scope_adr_velocity import _terrain  # noqa: E402

ALL = _terrain_mods.ENGINE_FORMS
MIN = ".".join(map(str, _effective_terrain.ENGINE_FORMS_MIN_VERSION))
V2_RECORD = {
    "method_id": _effective_terrain.METHOD_ID_V2,
    "request_schemas": [_effective_terrain.SCHEMA, _effective_terrain.SCHEMA_V2],
    "modifications": {"supported": {}, "hecras_version": "release label"},
}


def _bare_line(mods, name, priority, **kw):
    g = _ground_line(mods, name, priority, **kw)
    del g["Profile Values"]  # no stored profile at all
    return g


def _repeated_line(mods, name, priority):
    return _ground_line(mods, name, priority,
                        lines=[[(0.0, 0.0), (100.0, 0.0), (100.0, 0.0), (150.0, 50.0)]])


def _read(build, version="7.0.1", forms=ALL, tmp_path=None):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        build(f["Modifications"])
    return _terrain_mods.read_layers(hdf, hecras_version=version, engine_forms=forms)


# --- reader: the three refusals lifted only with the engine form and 7.0.1 ----------------

@pytest.mark.parametrize("build, reason", [
    (lambda m: _polygon(m, "Sampled", 0, gen=1), "sampled from the terrain"),
    (lambda m: _bare_line(m, "Bare", 0), "no stored profile and no control points"),
    (lambda m: _repeated_line(m, "Repeat", 0), "repeated vertex"),
])
def test_forms_stay_refused_without_the_engine_form(tmp_path, build, reason):
    with pytest.raises(FimUnsupportedError, match=reason):
        _read(build, forms=(), tmp_path=tmp_path)


def test_engine_forms_are_staged_under_7_0_1(tmp_path):
    hdf = _hdf(tmp_path)
    with h5py.File(hdf, "a") as f:
        mods = f["Modifications"]
        _polygon(mods, "Sampled", 0, gen=1)
        _bare_line(mods, "Bare", 1)
        _repeated_line(mods, "Repeat", 2)
    layers = {layer["name"]: layer
              for layer in _terrain_mods.read_layers(hdf, engine_forms=ALL)}
    sampled = layers["Sampled"]["features"][0]
    assert sampled["generate_boundary"] is True and sampled["profile"] == []
    assert "control_points" not in layers["Sampled"]
    assert layers["Bare"]["features"][0]["profile"] == []
    # Sent as stored: the engine drops the repeat, as RAS Mapper does.
    assert layers["Repeat"]["features"][0]["points"] == [
        [0.0, 0.0], [100.0, 0.0], [100.0, 0.0], [150.0, 50.0]]
    json.dumps(list(layers.values()))


@pytest.mark.parametrize("form, build, reason", [
    (_terrain_mods.TERRAIN_SAMPLED_BOUNDARY, lambda m: _polygon(m, "S", 0, gen=1),
     "sampled from the terrain"),
    (_terrain_mods.DEFAULT_GROUND_LINE_PROFILE, lambda m: _bare_line(m, "B", 0),
     "no stored profile and no control points"),
    (_terrain_mods.REPEATED_GROUND_LINE_VERTICES, lambda m: _repeated_line(m, "R", 0),
     "repeated vertex"),
])
def test_each_form_lifts_only_its_own_refusal(tmp_path, form, build, reason):
    others = tuple(f for f in ALL if f != form)
    with pytest.raises(FimUnsupportedError, match=reason):
        _read(build, forms=others, tmp_path=tmp_path)
    folder = tmp_path / "lifted"
    folder.mkdir()
    assert _read(build, forms=(form,), tmp_path=folder)


@pytest.mark.parametrize("version", ["6.6", "6.7"])
@pytest.mark.parametrize("build, reason", [
    (lambda m: _polygon(m, "Sampled", 0, gen=1), "sampled from the terrain|HEC-RAS 6.6"),
    (lambda m: _bare_line(m, "Bare", 0), "no stored profile and no control points"),
    (lambda m: _repeated_line(m, "Repeat", 0), "repeated vertex"),
])
def test_engine_forms_stay_refused_under_6_6_and_6_7(tmp_path, version, build, reason):
    with pytest.raises(FimUnsupportedError, match=reason):
        _read(build, version=version, tmp_path=tmp_path)


@pytest.mark.parametrize("build, reason", [
    # A one-station profile is neither a stored profile nor RAS Mapper's default.
    (lambda m: _set_profile(_ground_line(m, "One", 0), [[0.0, 10.0]]),
     "no stored profile and no control points"),
    # Named features without a profile are not qualified.
    (lambda m: _bare_line(m, "Named", 0, system=b"sys"), "no stored profile and no control points"),
    (lambda m: _ground_line(m, "Point", 0, lines=[[(5.0, 5.0), (5.0, 5.0), (5.0, 5.0)]]),
     "single distinct vertex"),
    # Unchanged refusals.
    (lambda m: _control_point_group(_ground_line(m, "NamedCp", 0, system=b"s"), [[0.0, 0.0]], [1.0]),
     "control points"),
    (lambda m: _set_attr(_polygon(m, "ShapeZ", 0), "Use ShapeFile Z Elevations", 1), "shapefile Z"),
])
def test_other_refusals_are_unchanged_with_every_form(tmp_path, build, reason):
    with pytest.raises(FimUnsupportedError, match=reason):
        _read(build, tmp_path=tmp_path)


def _set_profile(group, values):
    del group["Profile Info"], group["Profile Values"]
    group.create_dataset("Profile Info", data=np.array([[0, len(values)]], np.int32))
    group.create_dataset("Profile Values", data=np.asarray(values, np.float32))
    return group


def _set_attr(group, column, value):
    attrs = group["Attributes"][()]
    attrs[column] = value
    group["Attributes"][...] = attrs
    return group


def test_unknown_engine_form_is_a_value_error(tmp_path):
    with pytest.raises(ValueError, match="engine_forms"):
        _terrain_mods.read_layers(_hdf(tmp_path), engine_forms=("everything",))


# --- engine gate -------------------------------------------------------------------------------

def _engine(monkeypatch, version, record=V2_RECORD):
    monkeypatch.setattr(_effective_terrain._engine, "find_engine", lambda path=None: Path("engine.exe"))
    method = {"effective_terrain": record}
    if version is not None:
        method["engine"] = {"package": "ras-commander-fast-map", "version": version}
    monkeypatch.setattr(_effective_terrain._engine, "engine_method", lambda engine: method)


@pytest.mark.parametrize("version, record, expected", [
    (None, V2_RECORD, frozenset()),
    ("0.22.0", V2_RECORD, frozenset()),
    ("0.22.9", V2_RECORD, frozenset()),
    ("not a version", V2_RECORD, frozenset()),
    (MIN, {"method_id": _effective_terrain.METHOD_ID}, frozenset()),
    (MIN, V2_RECORD, frozenset((*ALL, _effective_terrain.PINNED_NAD83_REALIZATION))),
    ("1.0.0-rc1", V2_RECORD, frozenset((*ALL, _effective_terrain.PINNED_NAD83_REALIZATION))),
])
def test_engine_forms_follow_the_engine_release(monkeypatch, version, record, expected):
    _engine(monkeypatch, version, record)
    assert _effective_terrain.engine_modification_forms(Path("engine.exe")) == expected


def _sampled_terrain(tmp_path):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        mods = f.create_group("Modifications")
        _polygon(mods, "Sampled", 0, gen=1)
        _bare_line(mods, "Bare", 1)
        _repeated_line(mods, "Repeat", 2)
    return hdf


def test_older_engine_refuses_the_forms_before_it_runs(tmp_path, monkeypatch):
    hdf = _sampled_terrain(tmp_path)
    _engine(monkeypatch, "0.22.0")

    def no_engine(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("engine called for a form it does not reproduce")

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", no_engine)
    # Layers are read in HDF (name) order, so the bare ground line is met first.
    with pytest.raises(FimUnsupportedError, match="no stored profile and no control points"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", hecras_version="7.0.1")
    record = RasFim.read_terrain_modifications(hdf, hecras_version="7.0.1")
    assert record["status"] == "refused" and "no stored profile" in record["refusal"]


def test_engine_release_receives_the_forms_and_the_stitch_tin(tmp_path, monkeypatch):
    hdf = _sampled_terrain(tmp_path)
    with h5py.File(hdf, "a") as f:
        f.create_dataset("Terrain/Stitch TIN Points", data=np.zeros((3, 4)))
        f.create_dataset("Terrain/Stitch TIN Triangles", data=np.array([[0, 1, 2]], np.int32))
    _engine(monkeypatch, MIN)
    captured = _capture_request(monkeypatch)
    with pytest.raises(_Stop):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", hecras_version="7.0.1")
    assert captured["schema"] == _effective_terrain.SCHEMA_V2
    assert sorted(layer["name"] for layer in captured["modification_layers"]) == [
        "Bare", "Repeat", "Sampled"]
    # The terrain profiler falls back to the stored stitch TIN.
    assert captured["stitch_tin"]["triangles"]["shape"] == [1, 3]
    assert "hecras_version" not in captured
    record = RasFim.read_terrain_modifications(hdf, hecras_version="7.0.1")
    assert record["status"] == "staged" and len(record["layers"]) == 3
    # The same engine under the 6.6 rule: refused before it runs.
    with pytest.raises(FimUnsupportedError, match="no stored profile and no control points"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", hecras_version="6.6")


# --- NAD83 realization pins ----------------------------------------------------------------

CRS = pyproj.CRS


@pytest.mark.parametrize("other, expected", [
    (6563, None),  # NAD83(2011) / Pennsylvania North (ftUS)
    (3363, None),  # NAD83(HARN) / Pennsylvania North (ftUS)
    (3650, None),  # NAD83(NSRS2007) / Pennsylvania North (ftUS)
    (6562, "axis units"),  # NAD83(2011) / Pennsylvania North, metres
    (32128, "axis units"),  # NAD83 / Pennsylvania North, metres
    (6565, "Latitude of false origin"),  # NAD83(2011) / Pennsylvania South (ftUS)
    (26917, "projection methods"),  # NAD83 / UTM 17N
    (32617, "NAD83 realization"),  # WGS 84 / UTM 17N
    (32028, "NAD83 realization"),  # NAD27 / Pennsylvania North
    (4269, "projected 2D"),  # geographic NAD83
    ("EPSG:6563+5703", "projected 2D"),  # compound
])
def test_nad83_realization_check(other, expected):
    other = CRS.from_user_input(other if isinstance(other, str) else f"EPSG:{other}")
    mismatch = _effective_terrain.nad83_realization_mismatch(CRS.from_epsg(2271), other)
    if expected is None:
        assert mismatch is None
    else:
        assert expected in mismatch


def _two_source_terrain(tmp_path, second_epsg):
    """Two-source terrain HDF whose second source is tagged ``second_epsg``."""
    from rasterio.transform import from_origin

    root = tmp_path / "terrain"
    root.mkdir()
    hdf = _terrain(root, ["first", "second"], priorities=[0, 1])
    for name, epsg in (("first", 2271), ("second", second_epsg)):
        path = root / f"T.{name}.tif"
        with rasterio.open(path) as src:
            data, profile = src.read(), src.profile
        profile.update(crs=CRS.from_epsg(epsg).to_wkt(), transform=from_origin(2.0e6, 3.0e5, 10, 10))
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(data)
    return hdf, root


def _fake_identity_engine(monkeypatch, version, hashes):
    """An engine release whose terrain-info reports ``hashes[file name]``; runs stop at the build."""
    _engine(monkeypatch, version)
    monkeypatch.setattr(_effective_terrain._engine, "terrain_identity",
                        lambda *a, **k: {"epsg": 2271, "crs_identity": {"kind": "epsg"}})
    captured = {}

    def run_engine(args, what, timeout=None):
        if what == "terrain-info":
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                {"crs_wkt_fnv1a64": hashes[Path(args[2]).name]}), stderr="")
        captured.update(json.loads(Path(args[2]).read_text(encoding="utf-8")))
        raise _Stop

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", run_engine)
    return captured


PIN = "0123456789abcdef"


def test_a_source_in_another_nad83_realization_is_refused_without_a_pin(tmp_path, monkeypatch):
    hdf, _ = _two_source_terrain(tmp_path, 6563)
    _fake_identity_engine(monkeypatch, MIN, {"T.second.tif": PIN})
    with pytest.raises(FimUnsupportedError, match="not in the first source's CRS.*source_crs_pins"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")


def test_a_verified_pin_reaches_the_engine(tmp_path, monkeypatch):
    hdf, _ = _two_source_terrain(tmp_path, 6563)
    captured = _fake_identity_engine(monkeypatch, MIN, {"T.second.tif": PIN})
    with pytest.raises(_Stop):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif",
                                       source_crs_pins={"T.second.tif": PIN.upper()})
    second = captured["sources"][1]
    assert second["crs_identity"] == {"kind": "caller_verified_wkt", "fnv1a64": PIN}
    assert captured["epsg"] == 2271
    assert "crs_identity" not in captured["sources"][0]


@pytest.mark.parametrize("version, epsg, pins, error, match", [
    # An engine that does not draw such a source: refused before staging.
    ("0.22.0", 6563, {"T.second.tif": PIN}, FimUnsupportedError, "source_crs_pins need an engine"),
    # Not another NAD83 realization of the same projection and units.
    (MIN, 6562, {"T.second.tif": PIN}, FimUnsupportedError, "axis units"),
    (MIN, 32617, {"T.second.tif": PIN}, FimUnsupportedError, "NAD83 realization"),
    # The engine reads another WKT than the one the caller verified.
    (MIN, 6563, {"T.second.tif": "fedcba9876543210"}, FimUnsupportedError, "does not match"),
    # Pins must name exactly one lower-priority source that needs one.
    (MIN, 2271, {"T.second.tif": PIN}, ValueError, "nothing to pin"),
    (MIN, 6563, {"T.first.tif": PIN}, ValueError, "first source"),
    (MIN, 6563, {"T.other.tif": PIN}, ValueError, "not exactly one terrain source"),
    (MIN, 6563, {"T.second.tif": "not-a-hash"}, ValueError, "16-digit"),
    (MIN, 6563, {}, ValueError, "non-empty"),
])
def test_pins_are_explicit_and_verified(tmp_path, monkeypatch, version, epsg, pins, error, match):
    hdf, _ = _two_source_terrain(tmp_path, epsg)
    _fake_identity_engine(monkeypatch, version, {"T.second.tif": PIN, "T.first.tif": PIN})
    with pytest.raises(error, match=match):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", source_crs_pins=pins)


# --- real data: BaldEagleCrkMulti2D Terrain50 with an engine built from the branch ------------

_BRANCH_ENGINE = os.environ.get("RAS_COMMANDER_FIM_ENGINE_FORMS_ENGINE")
real_engine = pytest.mark.skipif(
    not _BRANCH_ENGINE, reason="set RAS_COMMANDER_FIM_ENGINE_FORMS_ENGINE to a fast-map build with the forms")


@pytest.fixture(scope="module")
def bald_eagle_terrain(tmp_path_factory):
    from ras_commander import RasExamples

    try:
        project = RasExamples.extract_project(
            "BaldEagleCrkMulti2D", output_path=tmp_path_factory.mktemp("examples"), suffix="_forms")
    except Exception as exc:  # pragma: no cover - offline
        pytest.skip(f"RasExamples BaldEagleCrkMulti2D unavailable: {exc}")
    project = project[0] if isinstance(project, list) else project
    return Path(project) / "Terrain"


def _branch_release(monkeypatch):
    """Report the branch build as the release that carries its forms."""
    real = _effective_terrain.engine_version
    engine = Path(_BRANCH_ENGINE)
    assert real(engine) is not None
    monkeypatch.setattr(
        _effective_terrain, "engine_version",
        lambda e: max(real(e), _effective_terrain.ENGINE_FORMS_MIN_VERSION))


def _valid_area(tif, size_px=60):
    """Map coordinates of a ``size_px`` square fully inside valid data, near the source centre."""
    with rasterio.open(tif) as src:
        data = src.read(1, masked=True)
        valid = ~np.ma.getmaskarray(data)
        rows, cols = valid.shape
        for radius in range(0, max(rows, cols) // 2, size_px):
            for r0 in (rows // 2 - radius, rows // 2 + radius):
                for c0 in range(cols // 4, 3 * cols // 4, size_px):
                    if 0 <= r0 <= rows - size_px and valid[r0:r0 + size_px, c0:c0 + size_px].all():
                        x0, y0 = src.xy(r0, c0)
                        x1, y1 = src.xy(r0 + size_px, c0 + size_px)
                        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    raise AssertionError("no valid area found")


@real_engine
@pytest.mark.slow
def test_real_engine_draws_the_forms_on_bald_eagle(tmp_path, bald_eagle_terrain, monkeypatch):
    terrain = tmp_path / "Terrain"
    shutil.copytree(bald_eagle_terrain, terrain)
    hdf = terrain / "Terrain50.hdf"
    x0, y0, x1, y1 = _valid_area(terrain / "Terrain50.dtm_20ft.tif")
    w = x1 - x0
    with h5py.File(hdf, "a") as f:
        mods = f.create_group("Modifications")
        poly = _polygon(mods, "Sampled", 0, gen=1, et=b"SetIfHigher")
        ring = [(x0 + 0.1 * w, y0 + 0.1 * w), (x0 + 0.5 * w, y0 + 0.1 * w), (x0 + 0.5 * w, y0 + 0.5 * w),
                (x0 + 0.1 * w, y0 + 0.5 * w), (x0 + 0.1 * w, y0 + 0.1 * w)]
        poly["Polygon Points"][...] = np.asarray(ring)
        _bare_line(mods, "Bare", 1, et=b"SetValue", width=40.0, reach=120.0,
                   lines=[[(x0 + 0.6 * w, y0 + 0.2 * w), (x0 + 0.9 * w, y0 + 0.25 * w)]])
        a, b, c = (x0 + 0.6 * w, y0 + 0.7 * w), (x0 + 0.75 * w, y0 + 0.7 * w), (x0 + 0.9 * w, y0 + 0.8 * w)
        _ground_line(mods, "Repeat", 2, et=b"SetValue", width=40.0, reach=120.0, lines=[[a, b, b, c]])
        # The same line without the repeat, kept outside /Modifications for the second build.
        _ground_line(f.create_group("Stash"), "Repeat", 2, et=b"SetValue", width=40.0, reach=120.0,
                     lines=[[a, b, c]])

    # The real 0.22.0 report keeps every form refused (the bare line is read first).
    with pytest.raises(FimUnsupportedError, match="no stored profile and no control points"):
        RasFim.build_effective_terrain(hdf, tmp_path / "refused.tif", engine_path=_BRANCH_ENGINE,
                                       hecras_version="7.0.1")
    _branch_release(monkeypatch)
    # Under HEC-RAS 6.6 still refused, before the engine runs.
    with pytest.raises(FimUnsupportedError, match="no stored profile and no control points"):
        RasFim.build_effective_terrain(hdf, tmp_path / "refused.tif", engine_path=_BRANCH_ENGINE,
                                       hecras_version="6.6")
    out = tmp_path / "forms.tif"
    receipt = RasFim.build_effective_terrain(hdf, out, engine_path=_BRANCH_ENGINE, threads=4,
                                             max_working_mib=6144, hecras_version="7.0.1")
    assert receipt["hecras_version"] == "7.0.1" and receipt["stitch_tin"] is True
    report = receipt["engine_report"]
    assert report["stitch_tin"]["used"] is True
    changed = {layer["name"]: layer["changed_pixels"] for layer in report["modifications"]["layers"]}
    assert set(changed) == {"Sampled", "Bare", "Repeat"} and all(changed.values()), changed

    # The repeated vertex is drawn as the line without it.
    with h5py.File(hdf, "a") as f:
        for name in ("Sampled", "Bare", "Repeat"):
            del f[f"Modifications/{name}"]
        f.move("Stash/Repeat", "Modifications/Repeat")
        del f["Stash"]
    plain = tmp_path / "plain.tif"
    RasFim.build_effective_terrain(hdf, plain, engine_path=_BRANCH_ENGINE, threads=4,
                                   max_working_mib=6144, hecras_version="7.0.1")
    window = rasterio.windows.from_bounds(x0 + 0.55 * w, y0 + 0.6 * w, x1, y1,
                                          transform=rasterio.open(out).transform)
    with rasterio.open(out) as a_src, rasterio.open(plain) as b_src:
        assert np.array_equal(a_src.read(1, window=window), b_src.read(1, window=window))


@real_engine
@pytest.mark.slow
def test_real_engine_draws_a_pinned_nad83_2011_source_unchanged(tmp_path, bald_eagle_terrain, monkeypatch):
    original = tmp_path / "original"
    retagged = tmp_path / "retagged"
    shutil.copytree(bald_eagle_terrain, original)
    shutil.copytree(bald_eagle_terrain, retagged)
    lower = "Terrain50.baldeagledem.tif"  # the lower-priority source (VRT order)
    with rasterio.open(retagged / lower, "r+") as src:
        src.crs = CRS.from_epsg(6563)  # NAD83(2011) / Pennsylvania North (ftUS): tags only
    with rasterio.open(retagged / lower) as src:
        assert CRS.from_user_input(src.crs).to_epsg() == 6563
    info = json.loads(_effective_terrain._engine.run_engine(
        [_BRANCH_ENGINE, "terrain-info", str(retagged / lower)], "terrain-info").stdout)
    pin = info["crs_wkt_fnv1a64"]
    assert info.get("epsg") == 6563 and pin

    kwargs = dict(engine_path=_BRANCH_ENGINE, threads=4, max_working_mib=6144)
    # Without a pin, and with the real 0.22.0 report, the source is refused.
    with pytest.raises(FimUnsupportedError, match="not in the first source's CRS"):
        RasFim.build_effective_terrain(retagged / "Terrain50.hdf", tmp_path / "x.tif", **kwargs)
    with pytest.raises(FimUnsupportedError, match="source_crs_pins need an engine"):
        RasFim.build_effective_terrain(retagged / "Terrain50.hdf", tmp_path / "x.tif",
                                       source_crs_pins={lower: pin}, **kwargs)
    _branch_release(monkeypatch)
    with pytest.raises(FimUnsupportedError, match="does not match"):
        RasFim.build_effective_terrain(retagged / "Terrain50.hdf", tmp_path / "x.tif",
                                       source_crs_pins={lower: "0" * 16}, **kwargs)
    pinned = RasFim.build_effective_terrain(retagged / "Terrain50.hdf", tmp_path / "pinned.tif",
                                            source_crs_pins={lower: pin}, **kwargs)
    base = RasFim.build_effective_terrain(original / "Terrain50.hdf", tmp_path / "base.tif", **kwargs)
    [record] = pinned["source_crs_pins"]
    assert record["source"] == lower and record["fnv1a64"] == pin and record["reprojected"] is False
    assert (record["source_epsg"], record["terrain_epsg"]) == (6563, 2271)
    assert base["source_crs_pins"] == []
    assert _effective_terrain.PINNED_NAD83_REALIZATION in pinned["engine_forms"]
    with rasterio.open(tmp_path / "pinned.tif") as a, rasterio.open(tmp_path / "base.tif") as b:
        assert (a.width, a.height, a.transform, a.crs) == (b.width, b.height, b.transform, b.crs)
        for _, window in b.block_windows(1):
            assert np.array_equal(a.read(1, window=window), b.read(1, window=window))
