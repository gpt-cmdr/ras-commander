"""HdfMesh.get_mesh_corner_elevations: both storage layouts, every backend.

Synthetic files reproduce the stored schema observed in HEC-RAS 7.0/7.0.1 plan and
geometry HDFs and in RASMapper 7.0.1 ``PostProcessing.hdf`` caches (rank-one ``<f4``,
gzip, one value per ``FacePoints Coordinate`` row; cache attributes ``Terrain Filename``
and ``Terrain File Date``) with invented values. Every case runs with ``engine="h5py"``,
``"auto"`` and ``"native"``; ``auto`` and ``native`` must equal the h5py reference exactly
(native may refuse with ``FastHdfError`` only where h5py reports ``invalid``).

Real fixtures: set ``RAS_CORNER_ELEVATION_FIXTURES`` to a JSON manifest
``{"cases": [{"name", "hdf", "postprocessing"?, "source"?, "expect": {mesh: status},
"corners": {mesh: n}?}]}``; the real-file test is skipped otherwise.
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import fast_hdf
from ras_commander.hdf import CornerElevationError, HdfMesh, MeshCornerElevations

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rust_route_1._exact import assert_identical  # noqa: E402

GEOMETRY = "Geometry/2D Flow Areas"
CACHE = "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas"
CACHE_DATASET = "Processed Data/Profile (Horizontal)/FacePoint Elevation"
# NaN with payload, -0.0, +inf, -inf, smallest subnormal, the -9999 sentinel, ordinary values.
SPECIAL = np.array([0x7FC00001, 0x80000000, 0x7F800000, 0xFF800000, 0x00000001,
                    0xC61C3C00, 0x42C80000, 0x447A0000], dtype="<u4").view("<f4")
TERRAIN_DATE = "24OCT2026 18:49:00"


def _native_available():
    try:
        import ras_commander_fast_hdf as native
    except ImportError:
        return False
    return native.API_VERSION == 11 and hasattr(native, "mesh_corner_elevations")


ENGINES = ["h5py", "auto", pytest.param("native", marks=pytest.mark.skipif(
    not _native_available(), reason="ras-commander-fast-hdf without mesh_corner_elevations"))]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    yield
    fast_hdf.close_sessions()


def _text_attr(obj, name, value):
    obj.attrs.create(name, np.bytes_(value.encode()))


def _elevation(group, name, values, dtype="<f4"):
    values = np.asarray(values).astype(dtype)
    ds = group.create_dataset(name, data=values, chunks=values.shape or None, compression="gzip")
    _text_attr(ds, "Can Plot", "False")
    return ds


def _terrain_file(folder, date=TERRAIN_DATE):
    path = folder / "Terrain" / "Terrain.hdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"terrain")
    stamp = dt.datetime.strptime(date.title(), "%d%b%Y %H:%M:%S").timestamp()
    os.utime(path, (stamp, stamp))
    return path


def _plan(path, meshes):
    """meshes: {name: (corners, values or None, dtype)}."""
    with h5py.File(path, "w") as f:
        geometry = f.create_group("Geometry")
        _text_attr(geometry, "Terrain Filename", ".\\Terrain\\Terrain.hdf")
        _text_attr(geometry, "Terrain Layername", "Terrain")
        _text_attr(geometry, "Terrain File Date", TERRAIN_DATE)
        rows = np.array([(name.encode(), 1) for name in meshes], dtype=[("Name", "S16"), ("Cell Count", "<i4")])
        f.create_dataset(f"{GEOMETRY}/Attributes", data=rows)
        for name, (corners, values, dtype) in meshes.items():
            g = f.require_group(f"{GEOMETRY}/{name}")
            _text_attr(g, "Terrain Filename", ".\\Terrain\\Terrain.hdf")
            _text_attr(g, "Terrain File Date", TERRAIN_DATE)
            g.create_dataset("FacePoints Coordinate", data=np.arange(corners * 2, dtype="<f8").reshape(corners, 2))
            if values is not None:
                _elevation(g, "FacePoints Elevation", values, dtype)
    return path


def _cache(path, meshes, *, terrain="..\\Terrain\\Terrain.hdf", date=TERRAIN_DATE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as f:
        f.attrs.create("VERSION", np.bytes_(b"1.3"))
        for name, values in meshes.items():
            g = f.require_group(f"{CACHE}/{name}/Processed Data/Profile (Horizontal)")
            ds = g.create_dataset("FacePoint Elevation", data=np.asarray(values, dtype="<f4"),
                                  chunks=(len(values),), compression="gzip", compression_opts=1)
            _text_attr(ds, "Terrain Filename", terrain)
            _text_attr(ds, "Terrain File Date", date)
    return path


@pytest.fixture
def project(tmp_path):
    """A plan with two meshes and a fresh, agreeing cache in the plan's output folder."""
    _terrain_file(tmp_path)
    plan = _plan(tmp_path / "Model.p01.hdf", {
        "Mesh A": (8, SPECIAL, "<f4"),
        "Mesh B": (3, None, None),
    })
    cache = _cache(tmp_path / "Plan 01" / "PostProcessing.hdf", {"Mesh A": SPECIAL})
    later = os.path.getmtime(plan) + 10
    os.utime(cache, (later, later))
    return plan, cache


def _call(engine, *args, **kwargs):
    try:
        return "ok", HdfMesh.get_mesh_corner_elevations(*args, engine=engine, **kwargs)
    except Exception as exc:  # compared across engines
        return "raise", exc


def _plain(result):
    if isinstance(result, MeshCornerElevations):
        return result.as_dict()
    return {k: v.as_dict() for k, v in result.items()}


def _same_as_h5py(*args, **kwargs):
    """Run every engine; return the h5py outcome after proving the others identical."""
    reference = _call("h5py", *args, **kwargs)
    for engine in ("auto",) + (("native",) if _native_available() else ()):
        other = _call(engine, *args, **kwargs)
        if reference[0] == "ok" and other[0] == "ok":
            assert_identical(_plain(reference[1]), _plain(other[1]))
        elif engine == "native" and other[0] == "raise" and isinstance(other[1], fast_hdf.FastHdfError):
            continue
        else:
            assert reference[0] == other[0] == "raise", (engine, reference, other)
            assert type(reference[1]) is type(other[1]) and str(reference[1]) == str(other[1])
    return reference


def _bits(values):
    return np.asarray(values, dtype="<f4").view("<u4").tolist()


@pytest.mark.parametrize("engine", ENGINES)
def test_geometry_layout_preserves_every_bit_with_provenance(project, engine):
    plan, _ = project
    result = HdfMesh.get_mesh_corner_elevations(plan, "Mesh A", engine=engine)
    assert result.status == "ok" and result.reason is None
    values = result.require()
    assert values.dtype == np.dtype("<f4") and not values.flags.writeable
    assert _bits(values) == _bits(SPECIAL)
    assert values[5] == -9999.0
    source = result.source
    assert source.layout == "geometry" and Path(source.file) == plan.resolve()
    assert source.dataset == f"{GEOMETRY}/Mesh A/FacePoints Elevation"
    assert source.corner_count == result.corner_count == 8
    assert source.attributes == {"Can Plot": "False"}
    assert source.terrain["geometry"]["Terrain Layername"] == "Terrain"
    assert source.terrain["mesh"] == {"Terrain Filename": ".\\Terrain\\Terrain.hdf",
                                      "Terrain File Date": TERRAIN_DATE}
    assert result.checks == ()


@pytest.mark.parametrize("engine", ENGINES)
def test_cache_layout_reads_exactly_and_passes_staleness_checks(project, engine):
    plan, cache = project
    result = HdfMesh.get_mesh_corner_elevations(
        plan, "Mesh A", postprocessing_hdf=cache, source="mapping_cache", engine=engine)
    assert result.status == "ok", result.reason
    assert _bits(result.values) == _bits(SPECIAL)
    assert result.source.layout == "mapping_cache"
    assert result.source.dataset == f"{CACHE}/Mesh A/{CACHE_DATASET}"
    assert result.source.terrain == {"Terrain Filename": "..\\Terrain\\Terrain.hdf",
                                     "Terrain File Date": TERRAIN_DATE}
    assert [(c.name, c.status) for c in result.checks] == [
        ("corner_count", "passed"), ("terrain_file", "passed"), ("terrain_date", "passed"),
        ("terrain_current", "passed"), ("cache_after_hdf", "passed")]
    assert [c.layout for c in result.candidates] == ["mapping_cache"]


def test_both_layouts_agree_in_auto_and_every_engine_matches_h5py(project):
    plan, cache = project
    outcome, result = _same_as_h5py(plan, "Mesh A", postprocessing_hdf=cache)
    assert outcome == "ok" and result.status == "ok"
    assert result.source.layout == "geometry"
    assert [c.layout for c in result.candidates] == ["geometry", "mapping_cache"]
    assert ("agreement", "passed") in [(c.name, c.status) for c in result.checks]
    outcome, every = _same_as_h5py(plan, postprocessing_hdf=cache)
    assert list(every) == ["Mesh A", "Mesh B"]
    # Mesh B has neither layout: missing, never an empty array.
    assert every["Mesh B"].status == "missing" and every["Mesh B"].values is None
    with pytest.raises(CornerElevationError) as exc:
        every["Mesh B"].require()
    assert exc.value.status == "missing"


def test_conflicting_sources_are_reported_not_resolved(tmp_path):
    _terrain_file(tmp_path)
    plan = _plan(tmp_path / "Model.p01.hdf", {"Mesh A": (8, SPECIAL, "<f4")})
    other = SPECIAL.copy()
    other[6] = np.float32(100.5)
    cache = _cache(tmp_path / "Plan 01" / "PostProcessing.hdf", {"Mesh A": other})
    _, result = _same_as_h5py(plan, "Mesh A", postprocessing_hdf=cache)
    assert result.status == "conflict" and result.values is None and result.source is None
    assert "different values" in result.reason
    assert ("agreement", "failed") in [(c.name, c.status) for c in result.checks]
    assert {c.layout: c.status for c in result.candidates} == {"geometry": "ok", "mapping_cache": "ok"}
    assert result.candidates[0].sha256 != result.candidates[1].sha256
    # An explicit single source is the caller's choice, not a silent one.
    _, explicit = _same_as_h5py(plan, "Mesh A", source="geometry")
    assert explicit.status == "ok"


def test_corner_count_is_validated_in_both_layouts(tmp_path):
    _terrain_file(tmp_path)
    plan = _plan(tmp_path / "Model.p01.hdf", {
        "Short": (4, SPECIAL[:3], "<f4"),
        "Wide": (3, SPECIAL[:3], "<f8"),
        "Cache Only": (5, None, None),
    })
    cache = _cache(tmp_path / "Plan 01" / "PostProcessing.hdf", {"Cache Only": SPECIAL[:4]})
    _, short = _same_as_h5py(plan, "Short")
    assert short.status == "invalid" and "stores 3 corner elevations for 4 corners" in short.reason
    _, wide = _same_as_h5py(plan, "Wide")
    assert wide.status == "invalid" and "float32" in wide.reason
    _, cached = _same_as_h5py(plan, "Cache Only", postprocessing_hdf=cache, source="mapping_cache")
    assert cached.status == "invalid" and "stores 4 corner elevations for 5 corners" in cached.reason
    if _native_available():
        with pytest.raises(fast_hdf.FastHdfError):
            HdfMesh.get_mesh_corner_elevations(plan, "Short", engine="native")
        with pytest.raises(fast_hdf.FastHdfError):
            HdfMesh.get_mesh_corner_elevations(
                plan, "Cache Only", postprocessing_hdf=cache, source="mapping_cache", engine="native")


def test_a_cache_that_may_be_stale_is_not_used(tmp_path):
    _terrain_file(tmp_path)
    plan = _plan(tmp_path / "Model.p01.hdf", {"Mesh A": (8, None, None)})
    cache = _cache(tmp_path / "Plan 01" / "PostProcessing.hdf", {"Mesh A": SPECIAL},
                   terrain="..\\Terrain\\Other.hdf", date="01JAN2026 00:00:00")
    later = os.path.getmtime(plan) + 10
    os.utime(cache, (later, later))
    for source in ("auto", "mapping_cache"):
        _, result = _same_as_h5py(plan, "Mesh A", postprocessing_hdf=cache, source=source)
        assert result.status == "stale" and result.values is None, source
        failed = {c.name for c in result.checks if c.status == "failed"}
        assert failed == {"terrain_file", "terrain_date"}
        assert {c.name: c.status for c in result.checks}["terrain_current"] == "not_checked"
        assert result.candidates[-1].status == "ok"  # read and valid, but not trusted
    # A cache older than the plan is stale too.
    good = _cache(tmp_path / "Plan 02" / "PostProcessing.hdf", {"Mesh A": SPECIAL})
    earlier = os.path.getmtime(plan) - 10
    os.utime(good, (earlier, earlier))
    _, result = _same_as_h5py(plan, "Mesh A", postprocessing_hdf=good)
    assert result.status == "stale"
    assert [c.name for c in result.checks if c.status == "failed"] == ["cache_after_hdf"]


def test_missing_cache_mesh_and_absent_geometry_are_missing(project):
    plan, cache = project
    _, result = _same_as_h5py(plan, "Mesh B", postprocessing_hdf=cache, source="mapping_cache")
    assert result.status == "missing" and result.values is None
    assert result.candidates[0].status == "missing"
    assert CACHE_DATASET in result.reason


def test_requests_are_validated(project):
    plan, cache = project
    with pytest.raises(ValueError, match="source must be one of"):
        HdfMesh.get_mesh_corner_elevations(plan, source="cache")
    with pytest.raises(ValueError, match="omit postprocessing_hdf"):
        HdfMesh.get_mesh_corner_elevations(plan, postprocessing_hdf=cache, source="geometry")
    with pytest.raises(ValueError, match="needs postprocessing_hdf"):
        HdfMesh.get_mesh_corner_elevations(plan, source="mapping_cache")
    with pytest.raises(ValueError, match="is not a 2D flow area"):
        HdfMesh.get_mesh_corner_elevations(plan, "Nope")
    with pytest.raises(ValueError, match="engine must be"):
        HdfMesh.get_mesh_corner_elevations(plan, engine="rust-ish")


def test_environment_selects_the_backend(project, monkeypatch):
    plan, _ = project
    from ras_commander import _fast_hdf_typed
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "h5py")
    with _fast_hdf_typed.trace_reads() as trace:
        HdfMesh.get_mesh_corner_elevations(plan, "Mesh A")
    assert {r["backend"] for r in trace if r["route"] == "mesh_corner_elevations"} == {"h5py"}
    if _native_available():
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "native")
        with _fast_hdf_typed.trace_reads() as trace:
            HdfMesh.get_mesh_corner_elevations(plan, "Mesh A")
        assert {r["backend"] for r in trace if r["route"] == "mesh_corner_elevations"} == {"native-typed"}


def test_auto_falls_back_and_native_raises_on_engine_refusal(project, monkeypatch):
    if not _native_available():
        pytest.skip("native engine unavailable")
    plan, _ = project
    import ras_commander_fast_hdf as native

    def refuse(*args, **kwargs):
        raise RuntimeError("injected engine failure")

    monkeypatch.setattr(native, "mesh_corner_elevations", refuse)
    from ras_commander import _fast_hdf_typed
    with _fast_hdf_typed.trace_reads() as trace:
        result = HdfMesh.get_mesh_corner_elevations(plan, "Mesh A", engine="auto")
    assert result.status == "ok" and _bits(result.values) == _bits(SPECIAL)
    assert "h5py-fallback" in {r["backend"] for r in trace}
    with pytest.raises(fast_hdf.FastHdfError, match="injected engine failure"):
        HdfMesh.get_mesh_corner_elevations(plan, "Mesh A", engine="native")


# ---------------------------------------------------------------- real fixtures
_MANIFEST = os.environ.get("RAS_CORNER_ELEVATION_FIXTURES")
_CASES = json.loads(Path(_MANIFEST).read_text())["cases"] if _MANIFEST else []


@pytest.mark.skipif(not _MANIFEST, reason="Set RAS_CORNER_ELEVATION_FIXTURES to a real-fixture manifest")
@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_real_fixture(case):
    kwargs = {}
    if case.get("postprocessing"):
        kwargs["postprocessing_hdf"] = case["postprocessing"]
    if case.get("source"):
        kwargs["source"] = case["source"]
    outcome, results = _same_as_h5py(case["hdf"], **kwargs)
    assert outcome == "ok", results
    assert {m: r.status for m, r in results.items()} == case["expect"]
    for mesh, result in results.items():
        assert result.corner_count == case["corners"][mesh]
        if result.status == "ok":
            with h5py.File(result.source.file, "r") as f:
                stored = f[result.source.dataset][()]
            assert stored.dtype == np.dtype("<f4")
            assert stored.tobytes() == result.values.tobytes()
