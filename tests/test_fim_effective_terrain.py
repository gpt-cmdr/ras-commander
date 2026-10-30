"""Native effective terrain (``rasmapper-effective-terrain/1``) wiring in RasFim.

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
    assert receipt["method_id"] == _effective_terrain.METHOD_ID
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
