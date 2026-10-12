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
        "mode=sys.argv[1];config=json.loads(sys.argv[2])\n"
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
        ' if config.get("mode")=="profile": values={"station":[0.,1.],"elevation":[100.,99.],"warning":""}\n'
        ' print(json.dumps({"result":values}),flush=True)\n'
        'if mode=="missing_finish": sys.exit(0)\n'
        'execution={"mode":"single-clr-pool-worker-v1","called_on_pool_worker":True,"runtime_restored":mode!="bad_restore","sampling_max_threads":[1,1]}\n'
        'if mode=="bad_thread_type": execution["sampling_max_threads"]=[True,True]\n'
        'print(json.dumps({"finished":execution}),flush=True)\n'
        'if mode=="exit_after_finish": sys.exit(3)\n'
    )
    original = subprocess.Popen
    observed = []

    def launch(command, **kwargs):
        observed.append(command)
        return original(
            [sys.executable, "-I", str(worker), protocol_worker.mode, command[-1]],
            **kwargs,
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
        [np.full((65536, 2), 1.123456789012345, dtype="float64")],
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
    assert "65536" in worker.read_text()


@pytest.mark.parametrize(
    "mode", ["missing_finish", "bad_restore", "exit_after_finish", "bad_thread_type"]
)
def test_incomplete_or_unrestored_execution_cannot_complete(
    tmp_path, protocol_worker, mode
):
    globals()["protocol_worker"].mode = mode
    mapper = tmp_path / "model.rasmap"
    mapper.touch()
    record = tmp_path / "runtime.json"
    with pytest.raises(RuntimeError):
        list(
            RasTerrainMod.iter_terrain_point_elevations(
                mapper,
                "Terrain",
                [np.ones((2, 2))],
                1.0,
                isolated=True,
                runtime_record=record,
            )
        )
    assert json.loads(record.read_text()).get("status") != "completed"


def test_profile_iterator_reuses_one_session_and_preserves_raw_arrays(
    tmp_path, protocol_worker
):
    mapper, geometry, record = (
        tmp_path / "model.rasmap",
        tmp_path / "model.g01.hdf",
        tmp_path / "runtime.json",
    )
    mapper.touch()
    geometry.touch()
    profiles = [[[1.123456789012345, 2.0], [3.0, 4.0]], [[5.0, 6.0], [7.0, 8.0]]]
    result = list(
        RasTerrainMod.iter_terrain_profiles(
            mapper, geometry, profiles, 0, runtime_record=record
        )
    )
    assert len(protocol_worker) == 1 and len(result) == 2
    assert all(
        p.to_dict("list") == {"station": [0.0, 1.0], "elevation": [100.0, 99.0]}
        for p in result
    )
    assert all(p.attrs["warning"] == "" for p in result)
    assert json.loads(record.read_text())["status"] == "completed"


@pytest.mark.parametrize(
    "profile",
    [
        [],
        [[1.0, 2.0]],
        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
        [[float("nan"), 2.0], [3.0, 4.0]],
    ],
)
def test_profile_iterator_rejects_incomplete_nonfinite_coordinates(
    tmp_path, protocol_worker, profile
):
    mapper, geometry = tmp_path / "model.rasmap", tmp_path / "model.g01.hdf"
    mapper.touch()
    geometry.touch()
    with pytest.raises(ValueError):
        list(RasTerrainMod.iter_terrain_profiles(mapper, geometry, [profile]))


def test_native_extent_bounds_are_read_once_per_bounded_batch():
    import math
    import struct

    tree = ast.parse(
        Path(query.__file__).with_name("_terrain_query_worker.py").read_text()
    )
    reader = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_point_reader"
    )
    evaluator = next(
        n
        for n in reader.body
        if isinstance(n, ast.FunctionDef) and n.name == "evaluate"
    )
    counts = {key: 0 for key in ("MinX", "MaxX", "MinY", "MaxY")}

    class Extent:
        def __getattr__(self, name):
            counts[name] += 1
            return 0.0 if name.startswith("Min") else 10.0

    class Point:
        def __init__(self, x, y):
            self.X, self.Y = x, y

    class Arrays:
        def __getitem__(self, cls):
            return list

    extent_object = Extent()

    class Terrain:
        Extent = extent_object

        def ComputePointElevations(self, points, modifications, size):
            return [p.X + p.Y for p in points]

    scope = {
        "math": math,
        "struct": struct,
        "terrain": Terrain(),
        "PointM": Point,
        "Array": Arrays(),
        "modifications": True,
        "cell_size": 1.0,
    }
    exec(  # noqa: S102 - execute only the tracked evaluator with synthetic native objects
        compile(
            ast.Module(body=[evaluator], type_ignores=[]), "native-evaluator", "exec"
        ),
        scope,
    )
    assert (
        scope["evaluate"]([[1.123456789012345, 2.0]] * 65536)
        == [1.123456789012345 + 2.0] * 65536
    )
    assert set(counts.values()) == {1}
    with pytest.raises(ValueError, match="outside"):
        scope["evaluate"]([[11.0, 2.0]])
