"""Protocol and import-boundary regressions; native identity is qualified separately."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ras_commander import _terrain_query as query
from ras_commander.terrain import RasTerrainMod


@pytest.fixture
def protocol_worker(tmp_path, monkeypatch):
    install = tmp_path / "6.6"
    install.mkdir()
    monkeypatch.setattr(
        query,
        "find_hecras_install",
        lambda version: (
            install if version == "6.6" else pytest.fail("wrong native version")
        ),
    )
    worker = tmp_path / "protocol.py"
    worker.write_text(
        "import sys,json,time\n"
        "mode=sys.argv[1]\n"
        'ready={"dll_identity_verified":True,"managed_hdf5_threadsafe":mode!="foreign","python_gis_hdf_imported":False}\n'
        'if mode=="hang": time.sleep(30)\n'
        'print(json.dumps({"ready":ready}),flush=True)\n'
        'if mode=="hang_after_ready": time.sleep(30)\n'
        "for line in sys.stdin:\n"
        ' r=json.loads(line); n=len(r["coordinates"])\n'
        ' if mode=="crash": sys.exit(3)\n'
        ' if mode=="error": print(json.dumps({"error":"native failure"}),flush=True);sys.exit(1)\n'
        ' values=[100.0]*(n-1 if mode=="short" else n)\n'
        ' if mode=="nodata": values[0]=-9999.0\n'
        ' print(json.dumps({"result":values}),flush=True)\n'
    )
    original = subprocess.Popen
    observed = []

    def launch(command, **kwargs):
        observed.append(command)
        return original(
            [sys.executable, "-I", str(worker), protocol_worker.mode], **kwargs
        )

    protocol_worker.mode = "ok"
    monkeypatch.setattr(query.subprocess, "Popen", launch)
    return observed


def test_isolated_points_keep_batches_coords_bounds_and_new_runtime_record(
    tmp_path, protocol_worker
):
    mapper = tmp_path / "model.rasmap"
    mapper.touch()
    record = tmp_path / "runtime.json"
    points = np.column_stack(
        [np.arange(9001, dtype="float64") + 0.123, np.full(9001, 4.5)]
    )
    original = points.tobytes()
    values = list(
        RasTerrainMod.iter_terrain_point_elevations(
            mapper,
            "Terrain",
            [points],
            1.0,
            isolated=True,
            runtime_record=record,
            timeout_seconds=10,
        )
    )
    assert len(values) == 1 and values[0].shape == (9001,)
    assert np.all(values[0] == 100) and points.tobytes() == original
    assert protocol_worker[0][1] == "-I"
    assert Path(protocol_worker[0][2]).name == "_terrain_query_worker.py"
    assert "-m" not in protocol_worker[0]
    assert json.loads(record.read_text())["dll_identity_verified"]
    with pytest.raises(ValueError, match="already exists"):
        list(
            RasTerrainMod.iter_terrain_point_elevations(
                mapper,
                "Terrain",
                [points],
                1.0,
                isolated=True,
                runtime_record=record,
            )
        )


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("foreign", "identity failed"),
        ("hang", "timed out"),
        ("hang_after_ready", "timed out"),
        ("crash", "complete response"),
        ("error", "native failure"),
        ("short", "incomplete values"),
        ("nodata", "nodata elevations"),
    ],
)
def test_isolated_failures_never_yield_partial_batch(
    tmp_path, protocol_worker, mode, expected
):
    globals()["protocol_worker"].mode = mode
    mapper = tmp_path / "model.rasmap"
    mapper.touch()
    iterator = RasTerrainMod.iter_terrain_point_elevations(
        mapper,
        "Terrain",
        [np.full((4096, 2), 1.123456789012345, dtype="float64")],
        1.0,
        isolated=True,
        timeout_seconds=0.5 if mode in {"hang", "hang_after_ready"} else 10,
    )
    with pytest.raises(RuntimeError, match=expected):
        next(iterator)


def test_native_worker_does_not_import_commander_or_python_hdf_gis():
    worker = Path(query.__file__).with_name("_terrain_query_worker.py")
    parsed = ast.parse(worker.read_text())
    imports = []
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(
        n.split(".")[0] in {"ras_commander", "h5py", "numpy", "rasterio", "geopandas"}
        for n in imports
    )
    assert "_initialize_runtime(install)" in worker.read_text()
    assert "4096" in worker.read_text()
