"""Terrain CRSs without an EPSG code on the native route (Fast-Map ``crs_any``).

Fast-Map 0.19+ advertises ``crs_any`` on methods that take ``crs_geokeys``:
the GeoKey tags of a GeoTIFF in the CRS, which the engine writes back verbatim.
Unit tests drive a simulated engine; the real tests run when the installed
engine (``RAS_COMMANDER_FIM_ENGINE``) advertises ``crs_any`` and check the
GDAL/pyproj round trip of the output CRS. ESRI:102630 is NAD83 / Alabama West
in US survey feet, which has no EPSG code (EPSG:26930 is metres).
"""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
rasterio = pytest.importorskip("rasterio")
from pyproj import CRS  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

from ras_commander.fim import RasFim, _effective_terrain, _engine  # noqa: E402
from ras_commander.fim.errors import FimUnsupportedError  # noqa: E402

from test_fim_terrain_scope_adr_velocity import _terrain  # noqa: E402

ESRI = "ESRI:102630"
KEYS = {"directory": [1, 1, 0, 2, 1024, 0, 1, 1, 3072, 0, 1, 32767], "doubles": [], "ascii": ""}
V2, S1, S2 = (_effective_terrain.METHOD_ID_V2, _effective_terrain.SCHEMA,
              _effective_terrain.SCHEMA_V2)
RECORD = {"method_id": V2, "request_schemas": [S1, S2], "modifications": {}}


def _tif(path, crs):
    with rasterio.open(path, "w", driver="GTiff", width=4, height=3, count=1, dtype="float32",
                       crs=crs, transform=from_origin(2_150_000.0, 1_200_000.0, 3.25, 3.25),
                       nodata=-9999.0) as dst:
        dst.write(np.zeros((1, 3, 4), dtype=np.float32))
    return path


def _info(path, *, epsg=None, keys=KEYS):
    with rasterio.open(path) as src:
        return {"width": src.width, "height": src.height, "geo_transform": list(src.transform.to_gdal()),
                "epsg": epsg, "crs": {"epsg": epsg, "wkt": src.crs.to_wkt() if src.crs else None},
                "crs_wkt_fnv1a64": "cf70d6f4c8bb75f0", "geokeys": keys,
                "geokeys_fnv1a64": "75e62e03cd623fb7" if keys else None}


def _terrain_info(monkeypatch, info):
    monkeypatch.setattr(_engine, "run_engine", lambda *a, **k: json.dumps(info).encode())
    monkeypatch.setattr(_engine, "_json_stdout", lambda raw, *a: json.loads(raw))


def test_capability_and_request_fields():
    assert _engine.crs_any({"crs_any": True}) is True
    assert _engine.crs_any({"crs_any": "yes"}) is False
    assert _engine.crs_any(None) is False
    assert _engine.request_crs({"epsg": 2277}) == {"epsg": 2277}
    assert _engine.request_crs({"epsg": None, "crs_geokeys": KEYS}) == {"crs_geokeys": KEYS}


def test_identity_without_capability_keeps_the_refusal(monkeypatch, tmp_path):
    terrain = _tif(tmp_path / "t.tif", ESRI)
    _terrain_info(monkeypatch, _info(terrain))
    with pytest.raises(FimUnsupportedError, match="does not advertise crs_any"):
        _engine.terrain_identity(Path("engine"), terrain, ESRI)


def test_identity_with_capability_copies_the_terrain_keys(monkeypatch, tmp_path):
    terrain = _tif(tmp_path / "t.tif", ESRI)
    # terrio's own (mis)identification never overrides rasterio's "no EPSG code".
    _terrain_info(monkeypatch, _info(terrain, epsg=4185))
    block = _engine.terrain_identity(Path("engine"), terrain, ESRI, crs_any=True)
    assert block["epsg"] is None and block["crs_identity"] == {"kind": "geokeys"}
    assert block["crs_geokeys"] == KEYS
    assert _engine.request_crs(block) == {"crs_geokeys": KEYS}
    # The results CRS must still equal the terrain CRS.
    with pytest.raises(FimUnsupportedError, match="results CRS must equal"):
        _engine.terrain_identity(Path("engine"), terrain, "EPSG:26930", crs_any=True)
    # No keys to copy: refused.
    _terrain_info(monkeypatch, _info(terrain, keys=None))
    with pytest.raises(FimUnsupportedError, match="no GeoKey tags"):
        _engine.terrain_identity(Path("engine"), terrain, ESRI, crs_any=True)


def test_epsg_terrains_are_unchanged_with_capability(monkeypatch, tmp_path):
    terrain = _tif(tmp_path / "t.tif", "EPSG:2277")
    _terrain_info(monkeypatch, _info(terrain, epsg=2277))
    block = _engine.terrain_identity(Path("engine"), terrain, "EPSG:2277", crs_any=True)
    assert block == {"path": str(terrain), "epsg": 2277, "crs_identity": {"kind": "epsg"}}
    assert _engine.request_crs(block) == {"epsg": 2277}


def _fake_effective_engine(monkeypatch, record, info):
    """An engine whose ``terrain-info`` returns ``info(path)``; records requests."""
    monkeypatch.setattr(_effective_terrain._engine, "find_engine", lambda path=None: Path("engine.exe"))
    monkeypatch.setattr(_effective_terrain._engine, "engine_method",
                        lambda engine: {"effective_terrain": record})
    requests = []

    def run_engine(args, what, timeout=None):
        if args[1] == "terrain-info":
            return SimpleNamespace(returncode=0, stdout=json.dumps(info(Path(args[2]))), stderr="")
        requests.append(json.loads(Path(args[2]).read_text(encoding="utf-8")))
        out = Path(args[3])
        out.mkdir(parents=True)
        (out / "effective_terrain.tif").write_bytes(b"tif")
        (out / "report.json").write_text(json.dumps({"status": "complete", "method_id": V2}))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", run_engine)
    monkeypatch.setattr(_engine, "_json_stdout", lambda proc, *a: json.loads(proc.stdout))
    return requests


def _untagged_terrain(root, projection=ESRI):
    """A RAS Mapper-style terrain: the source TIFF has no CRS; the HDF holds it."""
    hdf = _terrain(root, ["only"], priorities=[0])
    tif = Path(root) / "T.only.tif"
    with rasterio.open(tif) as src:
        profile, data = src.profile, src.read()
    profile.pop("crs", None)
    tif.unlink()
    with rasterio.open(tif, "w", **profile) as dst:
        dst.write(data)
    with h5py.File(hdf, "a") as f:
        f["Terrain/T.only/0/Mask"][...] = 1
        if projection is None:
            f.attrs.pop("Projection", None)
        else:
            f.attrs["Projection"] = CRS.from_user_input(projection).to_wkt().encode()
    with rasterio.open(Path(root) / "T.only.tif") as src:
        assert not src.crs
    return hdf


def test_tagged_esri_terrain_sends_its_keys(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with rasterio.open(tmp_path / "T.only.tif", "r+") as src:
        src.crs = rasterio.crs.CRS.from_user_input(ESRI)
    requests = _fake_effective_engine(monkeypatch, dict(RECORD, crs_any=True), lambda p: _info(p))
    receipt = RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    request = requests[0]
    assert "epsg" not in request and request["crs_geokeys"] == KEYS
    assert request["crs_identity"] == {"kind": "geokeys"}
    assert receipt["crs"] == {"kind": "geokeys", "basis": "source_tiff_geokeys", "source_identity": "geokeys"}


def test_untagged_source_takes_the_terrain_hdf_crs(tmp_path, monkeypatch):
    hdf = _untagged_terrain(tmp_path)
    requests = _fake_effective_engine(monkeypatch, dict(RECORD, crs_any=True), lambda p: _info(p))
    receipt = RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    request = requests[0]
    assert request["crs_identity"] == {"kind": "untagged"} and request["crs_geokeys"] == KEYS
    assert "epsg" not in request
    assert receipt["crs"]["basis"] == "terrain_hdf_projection"
    assert CRS.from_wkt(receipt["crs"]["crs"]).equals(CRS.from_user_input(ESRI))


def test_untagged_source_without_a_projection_is_refused(tmp_path, monkeypatch):
    hdf = _untagged_terrain(tmp_path, projection=None)
    requests = _fake_effective_engine(monkeypatch, dict(RECORD, crs_any=True), lambda p: _info(p))
    with pytest.raises(FimUnsupportedError, match="no readable Projection"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    assert requests == []


def test_engine_without_capability_still_refuses_esri_terrain(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with rasterio.open(tmp_path / "T.only.tif", "r+") as src:
        src.crs = rasterio.crs.CRS.from_user_input(ESRI)
    requests = _fake_effective_engine(monkeypatch, RECORD, lambda p: _info(p))
    with pytest.raises(FimUnsupportedError, match="has no EPSG code"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    assert requests == []


def test_geokeys_for_crs_refuses_without_engine_keys(tmp_path, monkeypatch):
    _terrain_info(monkeypatch, {"geokeys": None, "geokeys_error": "unreadable"})
    with pytest.raises(Exception, match="no GeoKeys"):
        _engine.geokeys_for_crs(Path("engine"), ESRI, tmp_path / "crs")


def _real_engine_crs_any():
    try:
        engine = _engine.find_engine(None)
        record = _engine.engine_method(engine)
    except Exception:
        return False
    return _engine.crs_any(record.get("effective_terrain")) and _engine.crs_any(record.get("sloping"))


@pytest.mark.skipif(not _real_engine_crs_any(), reason="installed engine lacks crs_any")
@pytest.mark.parametrize("untagged", [False, True])
def test_real_engine_round_trips_an_esri_terrain(tmp_path, untagged):
    """GDAL/pyproj read the effective terrain's CRS as the source's, US feet included."""
    if untagged:
        hdf = _untagged_terrain(tmp_path)
    else:
        hdf = _terrain(tmp_path, ["only"], priorities=[0])
        with h5py.File(hdf, "a") as f:
            f["Terrain/T.only/0/Mask"][...] = 1
        with rasterio.open(tmp_path / "T.only.tif", "r+") as src:
            src.crs = rasterio.crs.CRS.from_user_input(ESRI)
    out = tmp_path / "out" / "effective.tif"
    receipt = RasFim.build_effective_terrain(hdf, out, threads=1, max_working_mib=256)
    assert receipt["crs"]["kind"] == "geokeys"
    reference = CRS.from_user_input(ESRI)
    with rasterio.open(out) as a:
        got = CRS.from_wkt(a.crs.to_wkt())
        assert a.crs.to_epsg() is None
    assert got.equals(reference) and got.to_authority() == ("ESRI", "102630")
    assert got.axis_info[0].unit_name == "US survey foot"
    if not untagged:
        with rasterio.open(tmp_path / "T.only.tif") as b:
            assert got.is_exact_same(CRS.from_wkt(b.crs.to_wkt()))


def _one_d_files(tmp_path, crs):
    from test_fim_one_d import inputs

    hdf = tmp_path / "model.p01.hdf"
    with h5py.File(hdf, "w") as f:
        f.attrs["Units System"] = "US Customary"
        f.attrs["Projection"] = rasterio.crs.CRS.from_user_input(crs).to_wkt()
        f.create_group("Geometry").attrs["SI Units"] = False
        for name, value in inputs().items():
            base = ("Geometry/Cross Section Interpolation Surfaces/"
                    if name.startswith("TIN") or name == "XSIDs" else "Geometry/Cross Sections/")
            f.create_dataset(base + name, data=value)
        base = "Results/Unsteady/Output/Output Blocks/Base Output/"
        attrs = np.zeros(2, dtype=[("River", "S8"), ("Reach", "S8"), ("Station", "S8")])
        attrs["River"] = b"Main"
        f.create_dataset(base + "Unsteady Time Series/Cross Sections/Cross Section Attributes", data=attrs)
        f.create_dataset(base + "Summary Output/Cross Sections/Maximum Water Surface", data=[[10., 20.]])
        f.create_dataset(base + "Unsteady Time Series/Cross Sections/Water Surface", data=[[5., 10.], [10., 20.]])
    terrain = tmp_path / "terrain.tif"
    with rasterio.open(terrain, "w", driver="GTiff", width=512, height=512, count=1, dtype="float32",
                       crs=crs, transform=from_origin(0, 256, 1, 1), tiled=True, blockxsize=256,
                       blockysize=256) as dst:
        dst.write(np.zeros((512, 512), dtype="float32"), 1)
    return hdf, terrain


@pytest.mark.parametrize("advertised", [True, False])
def test_one_d_final_format_sends_geokeys_for_an_esri_model(tmp_path, monkeypatch, advertised):
    from test_fim_one_d import _fake_one_d_engine, _native_final_flags

    from ras_commander.fim.errors import FimMappingError

    hdf, terrain = _one_d_files(tmp_path, ESRI)
    flags = _native_final_flags()
    if advertised:
        flags["native_final_format"]["crs_any"] = True
    exe, requests = _fake_one_d_engine(monkeypatch, tmp_path, flags, crs_any_label=ESRI)
    calls = []

    def keys(engine, crs, folder, timeout=None):
        calls.append(CRS.from_user_input(crs))
        return KEYS

    monkeypatch.setattr(_engine, "geokeys_for_crs", keys)
    run = lambda: RasFim.map_one_d_profiles(  # noqa: E731
        hdf, terrain, tmp_path / "out", profiles=["Max"], allow_unqualified=True, max_working_mib=64,
        engine_path=exe, bbox=(0, 0, 100, 100), final_format={"nodata": -9999.0, "block_size": 16})
    if not advertised:
        with pytest.raises((FimUnsupportedError, FimMappingError), match="crs_any"):
            run()
        assert requests == []
        return
    out = run()
    assert out.status.tolist() == ["complete"]
    assert requests[0]["crs_geokeys"] == KEYS and "epsg" not in requests[0]
    assert len(calls) == 1 and calls[0].equals(CRS.from_user_input(ESRI))
