"""Terrain-CRS override (``terrain_crs_fnv1a64``) for sloping mapping.

The unit tests run without the engine: ``terrain_identity`` is driven by a
simulated ``terrain-info`` report, and the public entry points are checked for
passing the override through. The real test is opt-in: set
RAS_COMMANDER_SLOPING_UNKNOWN_CRS_CASE to a JSON document with ``hdf``,
``terrain`` (a GeoTIFF whose WKT the engine cannot map to an EPSG code, such as
HEC-RAS 7.0.1 Davis ``PROJCS["unknown", ...]``), ``crs_wkt_fnv1a64`` and
optionally ``epsg_terrain`` (the same pixels with an EPSG-declared CRS) and
``engine``. No HEC-RAS execution or download occurs.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin

from ras_commander.fim import _engine, _sloping
from ras_commander.fim.errors import FimEngineError, FimUnsupportedError

UNKNOWN_WKT = (
    'PROJCS["unknown",GEOGCS["NAD83",DATUM["North_American_Datum_1983",'
    'SPHEROID["GRS 1980",6378137,298.257222101]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433]],PROJECTION["Lambert_Conformal_Conic_2SP"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",0],'
    'PARAMETER["standard_parallel_1",1],PARAMETER["standard_parallel_2",2],'
    'PARAMETER["false_easting",0],PARAMETER["false_northing",0],'
    'UNIT["metre",1]]'
)


@pytest.fixture
def terrain(tmp_path):
    path = tmp_path / "terrain.tif"
    with rasterio.open(path, "w", driver="GTiff", width=4, height=3, count=1, dtype="float32",
                       crs="EPSG:2871", transform=from_origin(100.0, 200.0, 2.0, 2.0),
                       nodata=-9999.0) as dst:
        dst.write(np.zeros((1, 3, 4), dtype=np.float32))
    return path


def fake_info(monkeypatch, terrain, *, epsg, wkt=UNKNOWN_WKT, fnv="e446f7bd6bdb4d7f"):
    with rasterio.open(terrain) as src:
        report = {"width": src.width, "height": src.height,
                  "geo_transform": list(src.transform.to_gdal()),
                  "epsg": epsg, "crs": {"epsg": epsg, "wkt": wkt}, "crs_wkt_fnv1a64": fnv}
    monkeypatch.setattr(_engine, "run_engine", lambda *a, **k: json.dumps(report).encode())
    monkeypatch.setattr(_engine, "_json_stdout", lambda raw, *a: json.loads(raw))


def test_unknown_engine_crs_refused_without_override(monkeypatch, terrain):
    fake_info(monkeypatch, terrain, epsg=None)
    with pytest.raises(FimUnsupportedError, match="differs from rasterio"):
        _engine.terrain_identity(Path("engine"), terrain, "EPSG:2871")


def test_matching_override_is_accepted_and_recorded(monkeypatch, terrain):
    fake_info(monkeypatch, terrain, epsg=None)
    block = _engine.terrain_identity(Path("engine"), terrain, "EPSG:2871", "e446f7bd6bdb4d7f")
    assert block["epsg"] == 2871
    assert block["crs_identity"] == {"kind": "caller_verified_wkt", "fnv1a64": "e446f7bd6bdb4d7f"}


def test_mismatched_override_is_refused(monkeypatch, terrain):
    fake_info(monkeypatch, terrain, epsg=None)
    with pytest.raises(FimEngineError, match="does not match the engine WKT hash e446f7bd6bdb4d7f"):
        _engine.terrain_identity(Path("engine"), terrain, "EPSG:2871", "0000000000000000")


def test_override_does_not_relax_results_crs(monkeypatch, terrain):
    fake_info(monkeypatch, terrain, epsg=None)
    with pytest.raises(FimUnsupportedError, match="results CRS must equal the terrain CRS"):
        _engine.terrain_identity(Path("engine"), terrain, "EPSG:2226", "e446f7bd6bdb4d7f")


def test_engine_epsg_takes_precedence_over_override(monkeypatch, terrain):
    fake_info(monkeypatch, terrain, epsg=2871)
    block = _engine.terrain_identity(Path("engine"), terrain, "EPSG:2871", "0000000000000000")
    assert block["crs_identity"] == {"kind": "epsg"}


def test_map_sloping_profiles_passes_override(monkeypatch, tmp_path):
    from ras_commander import RasFim

    seen = {}
    monkeypatch.setattr(_sloping, "map_profiles", lambda *a, **k: seen.update(k) or "mapped")
    assert RasFim.map_sloping_profiles(tmp_path / "a.hdf", tmp_path / "t.tif", tmp_path / "out",
                                       terrain_crs_fnv1a64="e446f7bd6bdb4d7f") == "mapped"
    assert seen["terrain_crs_fnv1a64"] == "e446f7bd6bdb4d7f"
    RasFim.map_sloping_profiles(tmp_path / "a.hdf", tmp_path / "t.tif", tmp_path / "out")
    assert seen["terrain_crs_fnv1a64"] is None


def test_prepare_sloping_model_passes_override(monkeypatch, tmp_path):
    from ras_commander import RasFim
    from ras_commander.fim import _sloping_context

    seen = {}

    class Prepared:
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(_sloping_context, "FimPreparedSlopingModel", Prepared)
    RasFim.prepare_sloping_model(tmp_path / "a.hdf", tmp_path / "t.tif",
                                 terrain_crs_fnv1a64="e446f7bd6bdb4d7f")
    assert seen["terrain_crs_fnv1a64"] == "e446f7bd6bdb4d7f"


def test_prepared_override_is_fixed(tmp_path):
    class Prepared:
        _invalid_policy = "repair"
        _terrain_crs_fnv1a64 = "e446f7bd6bdb4d7f"

    with pytest.raises(ValueError, match="terrain_crs_fnv1a64 is fixed when the sloping model is prepared"):
        _sloping.map_profiles(tmp_path / "a.hdf", tmp_path / "t.tif", tmp_path / "out",
                              terrain_crs_fnv1a64="0000000000000000", _prepared=Prepared())


# --------------------------------------------------------------------------- #
# Real model (opt-in)
# --------------------------------------------------------------------------- #
@pytest.fixture
def unknown_crs_case():
    filename = os.environ.get("RAS_COMMANDER_SLOPING_UNKNOWN_CRS_CASE")
    if not filename:
        pytest.skip("set RAS_COMMANDER_SLOPING_UNKNOWN_CRS_CASE for the real terrain-CRS override test")
    document = json.loads(Path(filename).read_text(encoding="utf-8"))
    for key in ("hdf", "terrain", "crs_wkt_fnv1a64"):
        assert key in document
    return document


def products(folder):
    out = {}
    for path in sorted(Path(folder).glob("*.tif")):
        with rasterio.open(path) as src:
            out[path.name] = (src.transform, src.crs, src.read(1).view(np.uint32).copy())
    return out


def test_real_unknown_terrain_crs_maps_with_override(unknown_crs_case, tmp_path):
    from ras_commander import RasFim

    case = unknown_crs_case
    common = dict(profiles={"Max": "Max"}, engine_path=case.get("engine"), threads=4)
    with pytest.raises(FimUnsupportedError):
        RasFim.map_sloping_profiles(case["hdf"], case["terrain"], tmp_path / "refused", **common)

    direct = RasFim.map_sloping_profiles(case["hdf"], case["terrain"], tmp_path / "direct",
                                         terrain_crs_fnv1a64=case["crs_wkt_fnv1a64"], **common)
    assert list(direct.status) == ["complete"]
    manifest = json.loads((tmp_path / "direct" / "fim_manifest.json").read_text(encoding="utf-8"))
    assert manifest["terrain_crs_identity"] == {"kind": "caller_verified_wkt",
                                                "fnv1a64": case["crs_wkt_fnv1a64"]}

    with RasFim.prepare_sloping_model(case["hdf"], case["terrain"], profiles={"Max": "Max"},
                                      engine_path=case.get("engine"), threads=4,
                                      terrain_crs_fnv1a64=case["crs_wkt_fnv1a64"]) as model:
        assert model.info["terrain_crs_identity"]["fnv1a64"] == case["crs_wkt_fnv1a64"]
        model.map_profiles(tmp_path / "prepared")

    expected = products(tmp_path / "direct")
    assert expected
    for name, (transform, crs, bits) in products(tmp_path / "prepared").items():
        assert expected[name][0] == transform and expected[name][1] == crs
        assert np.array_equal(expected[name][2], bits)

    if case.get("epsg_terrain"):
        RasFim.map_sloping_profiles(case["hdf"], case["epsg_terrain"], tmp_path / "epsg", **common)
        copied = products(tmp_path / "epsg")
        assert copied.keys() == expected.keys()
        for name, (transform, crs, bits) in copied.items():
            assert expected[name][0] == transform and expected[name][1] == crs
            assert np.array_equal(expected[name][2], bits)
