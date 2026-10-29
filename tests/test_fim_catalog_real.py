"""Opt-in real computed models; no HEC-RAS execution."""

import json
import os
from pathlib import Path
import threading

import numpy as np
import pytest
import rasterio

from ras_commander import RasFim
from ras_commander.fim import FimMappingError


@pytest.fixture
def case():
    filename = os.environ.get("RAS_COMMANDER_FIM_CATALOG_CASE")
    if not filename:
        pytest.skip(
            "set RAS_COMMANDER_FIM_CATALOG_CASE to a computed 2D model/terrain/polygon case"
        )
    return json.loads(Path(filename).read_text(encoding="utf-8"))


def jobs(case, method="sloping"):
    return [
        dict(
            job_id="a",
            reach_id="reach-a",
            hdf_path=case["hdf"],
            terrain_path=case["terrain"],
            polygon=case["polygon"],
            polygon_layer=case.get("polygon_layer"),
            timesteps=case.get("timesteps", [48, 49, 48]),
            interpolation=method,
        )
    ]


def exact(actual, expected):
    for band in ("depth_tif", "wse_tif"):
        with rasterio.open(actual[band]) as a, rasterio.open(expected[band]) as b:
            assert a.shape == b.shape and a.transform == b.transform and a.crs == b.crs
            x, y = a.read(1, masked=True), b.read(1, masked=True)
            np.testing.assert_array_equal(np.ma.getmaskarray(x), np.ma.getmaskarray(y))
            valid = ~np.ma.getmaskarray(x)
            np.testing.assert_array_equal(
                x.data[valid].view("u4"), y.data[valid].view("u4")
            )


@pytest.mark.parametrize("method", ["sloping", "horizontal"])
def test_catalog_waves_order_aliases_and_current_path_bits(case, tmp_path, method):
    tasks = jobs(case, method)
    result = RasFim.map_catalog(
        tasks, tmp_path / "catalog", max_profiles_per_batch=2, max_workers=2
    )
    assert list(result.timestep) == tasks[0]["timesteps"]
    assert list(result.request_ordinal) == list(range(len(result)))
    assert set(result.status) == {"complete"}
    assert result.attrs["catalog_status"] == "complete"
    assert not (tmp_path / "catalog/.catalog-control").exists()
    if method == "sloping":
        baseline = RasFim.map_sloping_profiles(
            case["hdf"],
            case["terrain"],
            tmp_path / "baseline",
            profiles={f"p{i:06d}": v for i, v in enumerate(tasks[0]["timesteps"])},
            polygon=case["polygon"],
            polygon_layer=case.get("polygon_layer"),
            threads=4,
            max_working_mib=2048,
        )
        for a, b in zip(
            result.to_dict("records"), baseline.to_dict("records"), strict=True
        ):
            exact(a, b)
    else:
        # The separate one-shot catalog path also uses the public horizontal
        # mapper; compare independently staged calls against the shared table.
        for index, selector in enumerate(tasks[0]["timesteps"]):
            single = jobs(case, method)[0]
            single["timesteps"] = [selector]
            baseline = RasFim.map_catalog([single], tmp_path / f"baseline-{index}")
            exact(result.iloc[index], baseline.iloc[0])


def test_catalog_native_failure_retains_aborted_receipt(case, tmp_path):
    folder = tmp_path / "failed"
    with pytest.raises(FimMappingError) as failure:
        RasFim.map_catalog(jobs(case), folder, timeout=0.00001)
    assert failure.value.manifest.attrs["catalog_status"] == "aborted"
    assert (
        json.loads((folder / "catalog_manifest.json").read_text())["status"]
        == "aborted"
    )
    assert not list(folder.rglob("*.tif"))
    assert not (folder / ".catalog-control").exists()


def test_cancelled_catalog_returns_manifest_and_releases_workers(case, tmp_path):
    stop = threading.Event()
    stop.set()
    folder = tmp_path / "cancelled"
    result = RasFim.map_catalog(
        jobs(case), folder, cancel_event=stop, raise_on_failure=False
    )
    assert set(result.status) == {"cancelled"}
    assert result.attrs["catalog_status"] == "cancelled"
    assert not list(folder.rglob("*.tif"))
    assert not (folder / ".catalog-control").exists()


def test_two_cpu_partitions_and_duplicate_destinations_remain_independent(
    case, tmp_path
):
    tasks = jobs(case)
    tasks.append(dict(tasks[0], job_id="b", timesteps=[tasks[0]["timesteps"][0]]))
    result = RasFim.map_catalog(
        tasks, tmp_path / "parallel", max_workers=2, strategy="parallel"
    )
    assert list(result.job_id) == ["a"] * len(tasks[0]["timesteps"]) + ["b"]
    receipt = json.loads(Path(result.attrs["catalog_manifest"]).read_text())
    assert receipt["effective_workers"] == 2
    left, right = receipt["cpu_partitions"]
    import psutil
    assert not set(left) & set(right)
    assert len(left) + len(right) == min(4, len(psutil.Process().cpu_affinity()))
    exact(result.iloc[0], result.iloc[-1])


def test_later_failure_preserves_committed_job(case, tmp_path):
    tasks = jobs(case)
    tasks[0]["timesteps"] = [tasks[0]["timesteps"][0]]
    tasks.append(dict(tasks[0], job_id="later", timesteps=[1000000]))
    folder = tmp_path / "partial"
    result = RasFim.map_catalog(
        tasks, folder, strategy="parallel", raise_on_failure=False
    )
    assert list(result.status) == ["complete", "failed"]
    assert result.attrs["catalog_status"] == "aborted"
    assert Path(result.iloc[0].depth_tif).exists()
    assert not list((folder / "later").glob("*.tif"))


@pytest.mark.parametrize("writer", ["rasterio", "native"])
def test_active_cancellation_preserves_only_acknowledged_products(case, tmp_path, writer):
    import psutil

    folder = tmp_path / "active-cancel"
    stop = threading.Event()
    owned = []
    native_name = Path(RasFim.get_engine_info()["engine_path"]).name.lower()
    if writer == "native" and not RasFim.get_engine_info()["method"]["sloping"].get("native_geotiff_outputs"):
        pytest.skip("native writer requires a capable engine")

    def cancel_on_native():
        import time

        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            for child in psutil.Process().children(recursive=True):
                try:
                    if child.name().lower() == native_name:
                        owned.append(child)
                        stop.set()
                        return
                except psutil.NoSuchProcess:
                    pass
            time.sleep(0.01)
        stop.set()

    thread = threading.Thread(target=cancel_on_native, daemon=True)
    thread.start()
    result = RasFim.map_catalog(
        jobs(case), folder, cancel_event=stop, raise_on_failure=False, product_writer=writer
    )
    thread.join(timeout=50)
    assert result.attrs["catalog_status"] == "cancelled"
    assert owned and all(not p.is_running() for p in owned)
    assert not (folder / ".catalog-control").exists()
    retained = {
        Path(row[key])
        for row in result.to_dict("records")
        for key in ("depth_tif", "wse_tif")
        if row[key]
    }
    assert set(folder.rglob("*.tif")) == retained


def test_persistent_session_reuse_close_and_timeout_retry(case, tmp_path):
    import psutil
    from ras_commander.fim import FimEngineError

    with RasFim.prepare_sloping_model(
        case["hdf"],
        case["terrain"],
        profiles={"a": jobs(case)[0]["timesteps"][0]},
        threads=4,
        max_working_mib=2048,
    ) as model:
        controls = dict(
            polygon=case["polygon"], polygon_layer=case.get("polygon_layer")
        )
        staged = Path(model._temporary.name)
        with pytest.raises(FimEngineError):
            model.map_profiles(tmp_path / "timeout", timeout=0.00001, **controls)
        assert model._native_session is None
        one = model.map_profiles(tmp_path / "one", **controls)
        pid = model._native_session.process.pid
        two = model.map_profiles(tmp_path / "two", **controls)
        assert model._native_session.process.pid == pid
        session = two.attrs["performance"]["engine_report"]["session"]
        assert (
            session["geometry_reused"]
            and session["terrain_reused"]
            and session["window_reused"]
        )
        exact(one.iloc[0], two.iloc[0])
    assert not staged.exists() and not psutil.pid_exists(pid)
