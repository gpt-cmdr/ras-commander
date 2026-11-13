"""Native effective terrain (``rasmapper-effective-terrain/1`` and ``/2``) wiring in RasFim.

Unit tests use synthetic terrain HDFs and, where an engine is needed, the
installed ``ras2fim-batch`` (skipped when it lacks the method). Conformance to
RAS Mapper's export is qualified in ras-commander-fast-map
(``scripts/qualify_effective_terrain.py``); set
RAS_COMMANDER_FIM_EFFECTIVE_TERRAIN_CASE to a JSON document with
``terrain_hdf`` and ``export`` (a 1x ``RasTerrain.export_rasmapper_terrain``)
to re-run it through RasFim.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
rasterio = pytest.importorskip("rasterio")

from ras_commander.fim import RasFim, _effective_terrain  # noqa: E402
from ras_commander.fim.errors import FimUnsupportedError  # noqa: E402

from test_fim_terrain_scope_adr_velocity import _terrain  # noqa: E402


def _engine_with_method():
    try:
        return RasFim.supports_effective_terrain()
    except Exception:
        return False


def test_source_groups_follow_proven_priority(tmp_path):
    hdf = _terrain(tmp_path, ["coarse", "channel"], priorities=[1, 0], vrt=["channel", "coarse"])
    info = RasFim.top_priority_terrain_source(hdf)
    assert info["source_groups"] == ["T.channel", "T.coarse"]


def test_stage_writes_every_mask_and_the_stitch_tin(tmp_path):
    hdf = _terrain(tmp_path, ["coarse", "channel"], priorities=[1, 0])
    points = np.array([[0, 0, 1, 2], [1, 0, 2, 2], [0, 1, 3, 2]], dtype="<f8")
    triangles = np.array([[0, 1, 2]], dtype="<i4")
    with h5py.File(hdf, "a") as f:
        f["Terrain"].create_dataset("Stitch TIN Points", data=points)
        f["Terrain"].create_dataset("Stitch TIN Triangles", data=triangles)
        f["Terrain/T.coarse/0/Mask"][0, :4] = [3, 0, 1, 2]
    info = RasFim.top_priority_terrain_source(hdf)
    staged = _effective_terrain.stage(info, tmp_path)
    assert [Path(s["path"]).name for s in staged["sources"]] == ["T.channel.tif", "T.coarse.tif"]
    with h5py.File(hdf, "r") as f:
        for index, group in enumerate(["T.channel", "T.coarse"]):
            raw = (tmp_path / f"mask{index}.u1").read_bytes()
            assert raw == f[f"Terrain/{group}/0/Mask"][()].tobytes()
            assert staged["sources"][index]["mask"] == {
                "path": f"mask{index}.u1", "dtype": "|u1", "shape": [4, 65536],
            }
    assert (tmp_path / "tin_points.f8").read_bytes() == points.tobytes()
    assert (tmp_path / "tin_triangles.i4").read_bytes() == triangles.tobytes()
    assert staged["stitch_tin"]["triangles"]["shape"] == [1, 3]


def test_stage_without_a_stitch_tin(tmp_path):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    staged = _effective_terrain.stage(RasFim.top_priority_terrain_source(hdf), tmp_path)
    assert staged["stitch_tin"] is None and len(staged["sources"]) == 1


def test_engine_without_the_method_is_refused(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["a", "b"], priorities=[0, 1])
    monkeypatch.setattr(_effective_terrain._engine, "find_engine", lambda path=None: Path("engine.exe"))
    monkeypatch.setattr(_effective_terrain._engine, "engine_method", lambda engine: {"sloping": {}})
    assert RasFim.supports_effective_terrain() is False
    with pytest.raises(FimUnsupportedError, match="rasmapper-effective-terrain/1"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")


def test_modified_terrain_is_refused_before_the_engine(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["a", "b"], priorities=[0, 1], modifications=True)
    monkeypatch.setattr(_effective_terrain._engine, "find_engine", lambda path=None: Path("engine.exe"))
    monkeypatch.setattr(
        _effective_terrain._engine, "engine_method",
        lambda engine: {"effective_terrain": {"method_id": _effective_terrain.METHOD_ID}},
    )

    def no_engine(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("engine called for a modified terrain")

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", no_engine)
    with pytest.raises(FimUnsupportedError, match="modifications"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    assert not (tmp_path / "out.tif").exists()


def test_output_must_be_a_tif(tmp_path):
    with pytest.raises(ValueError, match=".tif"):
        RasFim.build_effective_terrain(tmp_path / "T.hdf", tmp_path / "out.vrt")


@pytest.mark.skipif(not _engine_with_method(), reason="installed engine lacks effective_terrain")
def test_real_engine_on_a_synthetic_single_source_terrain(tmp_path):
    """One source, mask everywhere: the effective terrain is the source on its own lattice."""
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        f["Terrain/T.only/0/Mask"][...] = 1
    out = tmp_path / "out" / "effective.tif"
    receipt = RasFim.build_effective_terrain(hdf, out, threads=1, max_working_mib=256)
    assert receipt["method_id"] in (_effective_terrain.METHOD_ID, _effective_terrain.METHOD_ID_V2)
    assert receipt["modification_layers"] == []
    assert json.loads(out.with_suffix(".tif.json").read_text())["output"] == str(out)
    with rasterio.open(out) as a, rasterio.open(tmp_path / "T.only.tif") as b:
        assert a.nodata == -9999 and a.crs == b.crs
        got = a.read(1)
        assert got.shape[0] >= b.height - 1 and got.shape[1] >= b.width - 1
    assert not [p for p in out.parent.iterdir() if p.name.startswith(".effective-terrain-")]


_CASE = os.environ.get("RAS_COMMANDER_FIM_EFFECTIVE_TERRAIN_CASE")


@pytest.mark.skipif(not _CASE, reason="set RAS_COMMANDER_FIM_EFFECTIVE_TERRAIN_CASE for real qualification")
def test_real_terrain_matches_the_rasmapper_export(tmp_path):
    case = json.loads(Path(_CASE).read_text(encoding="utf-8"))
    out = tmp_path / "effective.tif"
    RasFim.build_effective_terrain(case["terrain_hdf"], out, threads=4, max_working_mib=6144)
    mask_diff = 0
    with rasterio.open(out) as a, rasterio.open(case["export"]) as b:
        assert (a.width, a.height) == (b.width, b.height)
        for _, window in b.block_windows(1):
            x, y = a.read(1, window=window), b.read(1, window=window)
            mask_diff += int(((x != a.nodata) != (y != b.nodata)).sum())
    assert mask_diff == 0


def _fake_engine(monkeypatch, record, reported):
    """An engine advertising ``record`` that reports ``reported`` (None: no method_id)."""
    monkeypatch.setattr(_effective_terrain._engine, "find_engine", lambda path=None: Path("engine.exe"))
    monkeypatch.setattr(_effective_terrain._engine, "engine_method",
                        lambda engine: {"effective_terrain": record})
    monkeypatch.setattr(_effective_terrain._engine, "terrain_identity",
                        lambda *a, **k: {"epsg": 26915, "crs_identity": {"kind": "epsg"}})
    requests = []

    def run_engine(args, what, timeout=None):
        from types import SimpleNamespace

        requests.append(json.loads(Path(args[2]).read_text(encoding="utf-8")))
        out = Path(args[3])
        out.mkdir(parents=True)
        (out / "effective_terrain.tif").write_bytes(b"tif")
        report = {"status": "complete"}
        if reported is not None:
            report["method_id"] = reported
        (out / "report.json").write_text(json.dumps(report), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", run_engine)
    return requests


V1, V2 = _effective_terrain.METHOD_ID, _effective_terrain.METHOD_ID_V2
S1, S2 = _effective_terrain.SCHEMA, _effective_terrain.SCHEMA_V2


@pytest.mark.parametrize("record, reported, schema", [
    # Current engine: /2 only, both request schemas, /2 receipts for both.
    ({"method_id": V2, "request_schemas": [S1, S2], "modifications": {"supported": {}}}, V2, S2),
    # Interim engine: /2 with /1 listed as compatible.
    ({"method_id": V2, "compatible_method_ids": [V1], "modifications": {}}, V2, S2),
    # /2 without a modifications record: schema 1, which may report /2.
    ({"method_id": V2}, V2, S1),
    # Older /1-only engine, with and without a reported method_id.
    ({"method_id": V1}, V1, S1),
    ({"method_id": V1}, None, S1),
])
def test_unmodified_terrain_on_every_engine_generation(tmp_path, monkeypatch, record, reported, schema):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    requests = _fake_engine(monkeypatch, record, reported)
    assert RasFim.supports_effective_terrain() is True
    receipt = RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    assert requests[0]["schema"] == schema and requests[0]["modifications"] == 0
    assert receipt["method_id"] == (reported or V1)
    assert receipt["modification_layers"] == []


@pytest.mark.parametrize("record, reported", [
    ({"method_id": V2, "request_schemas": [S1, S2], "modifications": {}}, V1),  # schema 2 must report /2
    ({"method_id": V1}, "rasmapper-effective-terrain/9"),
])
def test_unexpected_reported_method_is_an_engine_error(tmp_path, monkeypatch, record, reported):
    from ras_commander.fim.errors import FimEngineError

    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    _fake_engine(monkeypatch, record, reported)
    with pytest.raises(FimEngineError, match="reported method"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    assert not (tmp_path / "out.tif").exists()


def test_engine_without_schema_2_is_not_used_for_modifications(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    _fake_engine(monkeypatch, {"method_id": V2, "request_schemas": [S1], "modifications": {}}, V2)
    assert _effective_terrain.engine_supports(Path("engine.exe"), modifications=True) is False
    assert _effective_terrain.engine_supports(Path("engine.exe")) is True


# ESRI:102630 is NAD83 / Alabama West (US survey feet). PROJ identifies it only
# by its ESRI code: EPSG has no US-feet Alabama West CRS (EPSG:26930 is metres).
ESRI_ONLY_CRS = "ESRI:102630"


def _esri_only_terrain(root):
    """Synthetic single-source terrain whose source TIFF is in ESRI:102630."""
    from rasterio.crs import CRS

    hdf = _terrain(root, ["only"], priorities=[0])
    with h5py.File(hdf, "a") as f:
        f["Terrain/T.only/0/Mask"][...] = 1
    with rasterio.open(Path(root) / "T.only.tif", "r+") as src:
        src.crs = CRS.from_user_input(ESRI_ONLY_CRS)
    with rasterio.open(Path(root) / "T.only.tif") as src:
        assert src.crs.to_epsg() is None
    return hdf


@pytest.mark.parametrize("pin", [None, "f15e991dcc6bd62d"])
def test_esri_only_crs_is_refused_with_the_engine_epsg_requirement(tmp_path, monkeypatch, pin):
    """The effective-terrain request needs an EPSG code: the engine labels the
    output GeoTIFF from it. A WKT pin cannot replace it, so the refusal says
    so and names the RAS Mapper export, before anything is staged or run."""
    hdf = _esri_only_terrain(tmp_path)
    requests = _fake_engine(monkeypatch, {"method_id": V2, "request_schemas": [S1, S2],
                                          "modifications": {}}, V2)
    with pytest.raises(FimUnsupportedError) as caught:
        RasFim.build_effective_terrain(hdf, tmp_path / "out" / "e.tif", terrain_crs_fnv1a64=pin)
    message = str(caught.value)
    assert "ESRI:102630" in message and "has no EPSG code" in message
    assert "writes the output GeoTIFF's CRS" in message
    assert "export_rasmapper_terrain" in message
    assert ("does not replace it" in message) is (pin is not None)
    assert requests == []
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def _engine_with_crs_any():
    try:
        from ras_commander.fim import _engine
        return _engine.crs_any(_effective_terrain._record(_engine.find_engine(None)))
    except Exception:
        return False


@pytest.mark.skipif(not _engine_with_method() or _engine_with_crs_any(),
                    reason="installed engine lacks effective_terrain, or takes any CRS (test_fim_crs_any)")
def test_real_engine_reports_no_epsg_for_an_esri_only_terrain(tmp_path):
    """The installed engine identifies no EPSG code for ESRI:102630 either; the
    request is refused in RasFim with the actionable reason, even with the
    engine's own WKT hash supplied."""
    import subprocess

    from ras_commander.fim import _engine

    hdf = _esri_only_terrain(tmp_path)
    engine = _engine.find_engine(None)
    info = json.loads(subprocess.run(
        [str(engine), "terrain-info", str(tmp_path / "T.only.tif")],
        capture_output=True, text=True, check=True,
    ).stdout)
    assert info.get("epsg") is None and info.get("crs_wkt_fnv1a64")
    with pytest.raises(FimUnsupportedError, match="has no EPSG code"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out" / "e.tif",
                                       terrain_crs_fnv1a64=info["crs_wkt_fnv1a64"])


def test_misnamed_rasmap_group_is_unmodified_and_reported_in_the_receipt(tmp_path, monkeypatch):
    """Layers in a "Hydroconnectors" group are not applied by RAS Mapper: the
    terrain builds unmodified and the receipt carries the reason code."""
    hdf = _terrain(tmp_path, ["only"], priorities=[0], modifications=True)
    rasmap = tmp_path / "m.rasmap"
    rasmap.write_text(
        '<RASMapper><Terrains><Layer Name="T" Type="TerrainLayer" Filename=".\\T.hdf">'
        '<Layer Name="Hydroconnectors" Type="ElevationModificationGroup">'
        '<Layer Name="Channel" Type="GroundLineModificationLayer" /></Layer>'
        "</Layer></Terrains></RASMapper>",
        encoding="utf-8",
    )
    requests = _fake_engine(monkeypatch, {"method_id": V2, "request_schemas": [S1, S2],
                                          "modifications": {}}, V2)
    receipt = RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", rasmap_path=rasmap)
    assert requests[0]["modifications"] == 0 and requests[0]["modification_layers"] == []
    assert receipt["modification_layers"] == [] and receipt["hecras_version"] is None
    assert [(w["code"], w["group"]) for w in receipt["rasmap_warnings"]] == [
        ("modification_group_misnamed", "Hydroconnectors")
    ]


_STORED = {"method_id": V2, "request_schemas": [S1, S2], "modifications": {},
           "bases": ["export", "stored_map"],
           "stored_map": {"rule_id": _effective_terrain.STORED_MAP_RULE_ID}}


def _fake_basis_engine(monkeypatch, record, reported_basis):
    """``_fake_engine`` whose report echoes ``reported_basis`` (None: no basis field)."""
    requests = _fake_engine(monkeypatch, record, V2)
    run = _effective_terrain._engine.run_engine

    def run_engine(args, what, timeout=None):
        proc = run(args, what, timeout)
        if reported_basis is not None:
            out = Path(args[3]) / "report.json"
            report = json.loads(out.read_text(encoding="utf-8"))
            report["basis"] = reported_basis
            out.write_text(json.dumps(report), encoding="utf-8")
        return proc

    monkeypatch.setattr(_effective_terrain._engine, "run_engine", run_engine)
    return requests


def test_export_basis_requests_are_unchanged(tmp_path, monkeypatch):
    """The default sends no ``basis`` field, so old and new engines get the same request."""
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    requests = _fake_basis_engine(monkeypatch, _STORED, None)
    receipt = RasFim.build_effective_terrain(hdf, tmp_path / "out.tif")
    assert "basis" not in requests[0]
    assert receipt["basis"] == "export" and receipt["basis_rule_id"] is None
    receipt = RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", basis="export")
    assert "basis" not in requests[1]


def test_stored_map_basis_is_sent_and_checked(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    requests = _fake_basis_engine(monkeypatch, _STORED, "stored_map")
    assert RasFim.supports_effective_terrain_basis("stored_map") is True
    receipt = RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", basis="stored_map")
    assert requests[0]["basis"] == "stored_map"
    assert receipt["basis"] == "stored_map"
    assert receipt["basis_rule_id"] == "rasmapper-stored-map-terrain/1"
    assert json.loads((tmp_path / "out.tif.json").read_text())["basis"] == "stored_map"


def test_stored_map_basis_reported_as_export_is_an_engine_error(tmp_path, monkeypatch):
    from ras_commander.fim.errors import FimEngineError

    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    _fake_basis_engine(monkeypatch, _STORED, None)
    with pytest.raises(FimEngineError, match="reported basis"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", basis="stored_map")
    assert not (tmp_path / "out.tif").exists()


@pytest.mark.parametrize("record", [
    {"method_id": V2, "request_schemas": [S1, S2], "modifications": {}},
    {"method_id": V2, "bases": ["export", "stored_map"]},  # no stored_map record
    {"method_id": V2, "bases": ["export"], "stored_map": {"rule_id": _effective_terrain.STORED_MAP_RULE_ID}},
])
def test_stored_map_basis_needs_the_engine_record(tmp_path, monkeypatch, record):
    hdf = _terrain(tmp_path, ["only"], priorities=[0])
    requests = _fake_basis_engine(monkeypatch, record, "stored_map")
    assert RasFim.supports_effective_terrain_basis("stored_map") is False
    assert RasFim.supports_effective_terrain_basis("export") is True
    with pytest.raises(FimUnsupportedError, match="basis 'stored_map'"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", basis="stored_map")
    assert requests == []


def test_stored_map_basis_refuses_multi_source_terrains_before_the_engine(tmp_path, monkeypatch):
    hdf = _terrain(tmp_path, ["fine", "coarse"], priorities=[0, 1])
    requests = _fake_basis_engine(monkeypatch, _STORED, "stored_map")
    with pytest.raises(FimUnsupportedError, match="single-source"):
        RasFim.build_effective_terrain(hdf, tmp_path / "out.tif", basis="stored_map")
    assert requests == []


def test_unknown_basis_is_a_value_error(tmp_path):
    with pytest.raises(ValueError, match="basis"):
        RasFim.build_effective_terrain(tmp_path / "T.hdf", tmp_path / "out.tif", basis="renderer")
    with pytest.raises(ValueError, match="basis"):
        _effective_terrain.engine_supports_basis(Path("engine.exe"), "renderer")


def test_supports_basis_without_an_engine(monkeypatch):
    from ras_commander.fim.errors import FimEngineNotFoundError

    def missing(path=None):
        raise FimEngineNotFoundError("no engine")

    monkeypatch.setattr(_effective_terrain._engine, "find_engine", missing)
    assert RasFim.supports_effective_terrain_basis("stored_map") is False
