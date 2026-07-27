import json
import importlib
import inspect
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import psutil
import pytest
import rasterio
from rasterio.transform import from_origin

import ras_commander
from ras_commander import (
    GeoTiffWriteOptions,
    RasProcess,
    StoreMapPerformanceOptions,
)
from ras_commander.RasterPerformance import (
    ProcessTreeProfiler,
    StoreMapResourceEstimate,
    SystemMemorySnapshot,
    TerrainResourceEstimate,
)
from ras_commander.terrain import RasTerrain

ras_process_module = importlib.import_module("ras_commander.RasProcess")
terrain_module = importlib.import_module("ras_commander.terrain.RasTerrain")


def test_raster_performance_contracts_are_public_exports():
    expected = {
        "GeoTiffWriteOptions",
        "RasterOperationProfileResult",
        "StoreMapPerformanceOptions",
        "StoreMapProfileResult",
        "StoreMapResourceEstimate",
        "StoreMapResourceSample",
        "TerrainResourceEstimate",
    }
    assert expected <= set(ras_commander.__all__)
    assert all(hasattr(ras_commander, name) for name in expected)


def _estimate(selected_workers=2):
    return StoreMapResourceEstimate(
        plan_number="01",
        hecras_version="7.0",
        map_types=("wse", "depth", "velocity"),
        job_count=3,
        terrain=(),
        formula_version="float32-surface-v1",
        estimate_source="floor",
        surface_multiplier=4.0,
        fixed_overhead_mb=512,
        estimated_gdal_cache_mb=0,
        estimated_worker_private_mb=600,
        total_physical_mb=32768,
        available_physical_mb=20000,
        commit_total_mb=12000,
        commit_limit_mb=40000,
        commit_headroom_mb=28000,
        effective_reserve_mb=4096,
        cpu_limit=8,
        memory_limit=8,
        request_limit=8,
        job_limit=3,
        selected_workers=selected_workers,
        parallel_eligible=True,
    )


def _write_test_tiff(path: Path):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=8,
        height=6,
        count=1,
        dtype="float32",
        transform=from_origin(100, 200, 1, 1),
        crs="EPSG:32615",
        tiled=True,
    ) as destination:
        destination.write(np.arange(48, dtype="float32").reshape(6, 8), 1)


def test_store_map_options_are_typed_frozen_and_validate_override_policy():
    options = StoreMapPerformanceOptions(
        max_workers=None,
        gdal_num_threads_per_helper="all_cpus",
        gdal_cachemax_mb=256,
    )

    assert options.gdal_num_threads_per_helper == "ALL_CPUS"
    assert options.max_workers is None
    with pytest.raises(ValueError, match="requires memory_policy"):
        StoreMapPerformanceOptions(worker_memory_override_mb=512)
    with pytest.raises(Exception):
        options.max_workers = 3


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_workers": 2.5}, "max_workers"),
        ({"minimum_worker_memory_mb": 600.5}, "minimum_worker_memory_mb"),
        ({"reserve_memory_mb": 4096.0}, "reserve_memory_mb"),
        ({"gdal_cachemax_mb": 256.0}, "gdal_cachemax_mb"),
    ],
)
def test_store_map_options_reject_non_integer_integer_fields(kwargs, message):
    with pytest.raises(ValueError, match=message):
        StoreMapPerformanceOptions(**kwargs)


@pytest.mark.parametrize("invalid_value", [True, "600", 600.5])
def test_store_map_deprecated_memory_alias_uses_strict_validation(invalid_value):
    with pytest.warns(DeprecationWarning):
        with pytest.raises(ValueError, match="minimum_worker_memory_mb"):
            ras_process_module._coerce_store_map_performance_options(
                None,
                memory_per_worker_mb=invalid_value,
            )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"compression": "DEFLATE", "compression_level": 3.5}, "compression_level"),
        ({"predictor": 3.0}, "predictor"),
        ({"tile_size": 512.0}, "tile_size"),
        ({"gdal_cachemax_mb": 256.0}, "gdal_cachemax_mb"),
        ({"overview_levels": (2.9, 4)}, "overview_levels"),
        ({"create_overviews": 1}, "create_overviews"),
    ],
)
def test_geotiff_options_reject_non_integer_integer_fields(kwargs, message):
    with pytest.raises(ValueError, match=message):
        GeoTiffWriteOptions(**kwargs)


@pytest.mark.parametrize("resampling", ["bilinear", "rms"])
def test_geotiff_options_reject_resampling_missing_from_hecras_70_gdaladdo(
    resampling,
):
    with pytest.raises(ValueError, match="overview_resampling"):
        GeoTiffWriteOptions(overview_resampling=resampling)


def test_store_maps_preserves_legacy_positional_prefix():
    signature = inspect.signature(RasProcess.store_maps)
    names = list(signature.parameters)
    legacy_prefix = [
        "plan_number",
        "output_folder",
        "output_path",
        "profile",
        "render_mode",
        "wse",
        "depth",
        "velocity",
        "froude",
        "shear_stress",
        "depth_x_velocity",
        "depth_x_velocity_sq",
        "inundation_boundary",
        "arrival_time",
        "duration",
        "percent_inundated",
        "arrival_depth",
        "clear_existing",
        "fix_georef",
        "ras_object",
        "ras_version",
        "timeout",
        "_log_summary",
        "terrain_name",
        "benefit_area",
    ]

    assert names[: len(legacy_prefix)] == legacy_prefix
    assert all(
        signature.parameters[name].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        for name in legacy_prefix
    )
    assert all(
        signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        for name in (
            "performance",
            "max_workers",
            "memory_per_worker_mb",
            "reserve_memory_mb",
        )
    )
    assert "object at 0x" not in str(signature)


def test_estimate_store_map_resources_reports_memory_and_cpu_limiters(
    monkeypatch,
    tmp_path,
):
    plan_hdf = tmp_path / "Demo.p01.hdf"
    rasmap = tmp_path / "Demo.rasmap"
    plan_hdf.write_bytes(b"hdf")
    rasmap.write_text("<RASMapper />", encoding="utf-8")

    class FakeRas:
        project_folder = tmp_path
        project_name = "Demo"
        ras_version = "7.0"

        @staticmethod
        def check_initialized():
            return None

    terrain = TerrainResourceEstimate(
        path=tmp_path / "terrain.tif",
        width=10000,
        height=10000,
        dtype="float32",
        cell_count=100_000_000,
        float32_surface_mb=381.47,
    )
    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_rasmap_path",
        lambda _ras: rasmap,
    )
    monkeypatch.setattr(
        RasProcess,
        "_get_projection_info",
        staticmethod(
            lambda _path: ras_process_module.ProjectionInfo(
                prj_path=None,
                terrain_path=terrain.path,
                terrain_paths=(terrain.path,),
            )
        ),
    )
    monkeypatch.setattr(
        ras_process_module,
        "_terrain_resource_estimates",
        lambda _paths: ((terrain,), ()),
    )
    monkeypatch.setattr(
        ras_process_module,
        "get_system_memory_snapshot",
        lambda: SystemMemorySnapshot(32768, 12000, 20000, 40000),
    )
    monkeypatch.setattr(ras_process_module.os, "cpu_count", lambda: 8)

    result = RasProcess.estimate_store_map_resources(
        "1",
        performance=StoreMapPerformanceOptions(max_workers=None),
        ras_object=FakeRas(),
    )

    assert result.estimated_worker_private_mb == 2038
    assert result.effective_reserve_mb == 8192
    assert result.memory_limit == 1
    assert result.cpu_limit == 8
    assert result.selected_workers == 1
    assert result.terrain == (terrain,)

    monkeypatch.setattr(
        ras_process_module,
        "get_system_memory_snapshot",
        lambda: SystemMemorySnapshot(32768, 30000, 2000, 32768),
    )
    uncached = RasProcess.estimate_store_map_resources(
        "1",
        performance=StoreMapPerformanceOptions(max_workers=None),
        ras_object=FakeRas(),
    )
    cached = RasProcess.estimate_store_map_resources(
        "1",
        performance=StoreMapPerformanceOptions(
            max_workers=None,
            gdal_cachemax_mb=8192,
        ),
        ras_object=FakeRas(),
    )
    assert uncached.selected_workers == 3
    assert cached.estimated_gdal_cache_mb == 8192
    assert cached.estimated_worker_private_mb == 10230
    assert cached.memory_limit == 2
    assert cached.selected_workers == 2


def test_live_admission_waits_before_launch(monkeypatch, tmp_path):
    checks = iter([("memory pressure",), ()])
    monkeypatch.setattr(
        ras_process_module,
        "_store_map_admission_reasons",
        lambda _estimate: next(checks, ()),
    )
    launched = []

    def runner(map_key, helper_type, output_base):
        launched.append((map_key, helper_type, output_base))
        return subprocess.CompletedProcess([], 0, "ok", "")

    results = ras_process_module._run_memory_admitted_store_map_jobs(
        jobs=[("depth", "Depth", tmp_path / "Depth")],
        worker_count=1,
        performance=StoreMapPerformanceOptions(
            admission_poll_interval_seconds=0.001,
            admission_wait_timeout_seconds=1,
        ),
        estimate=_estimate(selected_workers=1),
        runner=runner,
    )

    assert list(results) == ["depth"]
    assert launched[0][0] == "depth"


def test_scheduler_stops_admitting_jobs_after_first_helper_failure(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        ras_process_module,
        "_store_map_admission_reasons",
        lambda _estimate: (),
    )
    second_started = __import__("threading").Event()
    release_second = __import__("threading").Event()
    launched = []

    def runner(map_key, _helper_type, _output_base):
        launched.append(map_key)
        if map_key == "wse":
            second_started.wait(timeout=1)
            return subprocess.CompletedProcess([], 7, "", "failed")
        if map_key == "depth":
            second_started.set()
            release_second.wait(timeout=1)
        return subprocess.CompletedProcess([], 0, "ok", "")

    def release_running_helper():
        second_started.wait(timeout=1)
        time.sleep(0.05)
        release_second.set()

    release_thread = __import__("threading").Thread(target=release_running_helper)
    release_thread.start()
    results = ras_process_module._run_memory_admitted_store_map_jobs(
        jobs=[
            ("wse", "Water Surface Elevation", tmp_path / "WSE"),
            ("depth", "Depth", tmp_path / "Depth"),
            ("velocity", "Velocity", tmp_path / "Velocity"),
        ],
        worker_count=2,
        performance=StoreMapPerformanceOptions(),
        estimate=_estimate(selected_workers=2),
        runner=runner,
    )
    release_thread.join(timeout=1)

    assert set(results) == {"wse", "depth"}
    assert results["wse"].returncode == 7
    assert "velocity" not in launched


def test_estimator_fails_closed_when_terrain_dimensions_are_unavailable(
    monkeypatch,
    tmp_path,
):
    rasmap = tmp_path / "Demo.rasmap"
    rasmap.write_text("<RASMapper />", encoding="utf-8")
    (tmp_path / "Demo.p01.hdf").write_bytes(b"hdf")

    class FakeRas:
        project_folder = tmp_path
        project_name = "Demo"
        ras_version = "7.0"

        @staticmethod
        def check_initialized():
            return None

    monkeypatch.setattr(
        ras_process_module.RasMap,
        "get_rasmap_path",
        lambda _ras: rasmap,
    )
    monkeypatch.setattr(
        RasProcess,
        "_get_projection_info",
        staticmethod(
            lambda _path: ras_process_module.ProjectionInfo(
                prj_path=None,
                terrain_path=None,
                terrain_paths=(),
            )
        ),
    )
    monkeypatch.setattr(
        ras_process_module,
        "get_system_memory_snapshot",
        lambda: SystemMemorySnapshot(131072, 120000, 10000, 131072),
    )

    result = RasProcess.estimate_store_map_resources(
        "01",
        map_types=("wse", "depth", "velocity"),
        performance=StoreMapPerformanceOptions(max_workers=None),
        ras_object=FakeRas(),
    )

    assert result.selected_workers == 1
    assert result.parallel_eligible is False
    assert any(
        "dimensions are unavailable" in reason for reason in result.fallback_reasons
    )


def test_single_helper_admission_enforces_commit_and_physical_policy(monkeypatch):
    monkeypatch.setattr(
        ras_process_module,
        "_store_map_admission_reasons",
        lambda _estimate: ("commit headroom is below required",),
    )

    with pytest.raises(MemoryError, match="commit headroom"):
        ras_process_module._wait_for_store_map_admission(
            _estimate(selected_workers=1),
            StoreMapPerformanceOptions(admission_wait_timeout_seconds=0),
        )

    ras_process_module._wait_for_store_map_admission(
        _estimate(selected_workers=1),
        StoreMapPerformanceOptions(
            memory_policy="warn",
            admission_wait_timeout_seconds=0,
        ),
    )


def test_profile_store_maps_writes_metrics_and_pixel_signatures(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        RasProcess,
        "estimate_store_map_resources",
        staticmethod(lambda *args, **kwargs: _estimate(selected_workers=1)),
    )

    def fake_store_maps(**kwargs):
        depth = Path(kwargs["output_path"]) / "Depth (Max).tif"
        _write_test_tiff(depth)
        return {"depth": [depth]}

    monkeypatch.setattr(RasProcess, "store_maps", staticmethod(fake_store_maps))
    report = tmp_path / "profile.json"

    result = RasProcess.profile_store_maps(
        "01",
        tmp_path,
        report,
        map_types=("depth",),
        sample_interval_seconds=0.01,
        ras_object=SimpleNamespace(project_folder=tmp_path),
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert result.generated_files["depth"][0].exists()
    assert payload["schema"] == "ras-commander.store-map-profile/1"
    assert payload["status"] == "complete"
    assert payload["settings"]["project_folder"]
    assert payload["settings"]["output_path"] == str(tmp_path)
    signature = next(iter(payload["output_signatures"].values()))
    assert len(signature["pixel_sha256"]) == 64
    assert payload["samples"]
    assert payload["performance_summary"]["logical_cpu_count"] >= 1
    assert "phase_inference_semantics" in payload["performance_summary"]
    assert isinstance(payload["phase_summary"], dict)


def test_geotiff_write_options_build_creation_and_overview_commands(
    monkeypatch,
    tmp_path,
):
    vrt = tmp_path / "terrain.vrt"
    vrt.write_text("<VRTDataset />", encoding="utf-8")
    output = tmp_path / "terrain.tif"
    gdal_bin = tmp_path / "GDAL" / "bin64"
    gdal_bin.mkdir(parents=True)
    translate = gdal_bin / "gdal_translate.exe"
    addo = gdal_bin / "gdaladdo.exe"
    translate.write_bytes(b"")
    addo.write_bytes(b"")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == str(translate):
            output.write_bytes(b"tif")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        RasTerrain,
        "_get_hecras_gdal_path",
        staticmethod(lambda _version: gdal_bin),
    )
    monkeypatch.setattr(terrain_module.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    options = GeoTiffWriteOptions(
        compression="zstd",
        compression_level=9,
        predictor=3,
        tile_size=512,
        gdal_num_threads="ALL_CPUS",
        gdal_cachemax_mb=256,
        overview_levels=(2, 8),
        overview_compression="DEFLATE",
    )

    result_path = RasTerrain.vrt_to_tiff(
        "terrain.vrt",
        "terrain.tif",
        write_options=options,
    )

    translate_command, translate_kwargs = calls[0]
    assert "COMPRESS=ZSTD" in translate_command
    assert "ZSTD_LEVEL=9" in translate_command
    assert "BLOCKXSIZE=512" in translate_command
    assert "BLOCKYSIZE=512" in translate_command
    assert "NUM_THREADS=ALL_CPUS" in translate_command
    assert translate_kwargs["env"]["GDAL_CACHEMAX"] == "256"
    assert Path(translate_command[-2]).is_absolute()
    assert Path(translate_command[-1]).is_absolute()
    assert result_path == output
    assert calls[1][0][1:4] == ["--config", "COMPRESS_OVERVIEW", "DEFLATE"]


def test_explicit_write_options_fail_closed_when_gdaladdo_fails(
    monkeypatch,
    tmp_path,
):
    vrt = tmp_path / "terrain.vrt"
    vrt.write_text("<VRTDataset />", encoding="utf-8")
    output = tmp_path / "terrain.tif"
    gdal_bin = tmp_path / "GDAL" / "bin64"
    gdal_bin.mkdir(parents=True)
    translate = gdal_bin / "gdal_translate.exe"
    addo = gdal_bin / "gdaladdo.exe"
    translate.write_bytes(b"")
    addo.write_bytes(b"")

    def fake_run(command, **_kwargs):
        if command[0] == str(translate):
            output.write_bytes(b"tif")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "unsupported codec")

    monkeypatch.setattr(
        RasTerrain,
        "_get_hecras_gdal_path",
        staticmethod(lambda _version: gdal_bin),
    )
    monkeypatch.setattr(terrain_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="gdaladdo failed"):
        RasTerrain.vrt_to_tiff(
            vrt,
            output,
            write_options=GeoTiffWriteOptions(),
        )

    # Legacy scalar calls retain their historical warn-and-return behavior.
    assert RasTerrain.vrt_to_tiff(vrt, output) == output


def test_profile_vrt_to_tiff_writes_report(monkeypatch, tmp_path):
    output = tmp_path / "terrain.tif"

    def fake_vrt_to_tiff(**kwargs):
        _write_test_tiff(Path(kwargs["output_path"]))
        return Path(kwargs["output_path"])

    monkeypatch.setattr(
        RasTerrain,
        "vrt_to_tiff",
        staticmethod(fake_vrt_to_tiff),
    )
    report = tmp_path / "terrain-profile.json"

    result = RasTerrain.profile_vrt_to_tiff(
        tmp_path / "terrain.vrt",
        output,
        report,
        write_options=GeoTiffWriteOptions(tile_size=512),
        sample_interval_seconds=0.01,
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert result.output_path == output
    assert payload["schema"] == "ras-commander.raster-operation-profile/1"
    assert payload["status"] == "complete"
    assert payload["settings"]["write_options"]["tile_size"] == 512
    assert payload["settings"]["vrt_path"] == str(tmp_path / "terrain.vrt")
    assert payload["settings"]["output_path"] == str(output)
    assert payload["settings"]["hecras_version"] == "7.0"
    assert payload["settings"]["sample_interval_seconds"] == 0.01
    assert len(payload["output_signature"]["pixel_sha256"]) == 64
    assert "average_machine_cpu_percent" in payload["performance_summary"]
    assert "peak_host_disk_write_iops" in payload["performance_summary"]
    assert isinstance(payload["phase_summary"], dict)


def test_process_tree_profiler_records_interval_cpu_io_and_host_load(tmp_path):
    profiler = ProcessTreeProfiler(
        sample_interval_seconds=0.02,
        watch_paths=(tmp_path,),
    )

    profiler.start()
    (tmp_path / "profiled.tif").write_bytes(b"raster" * 131_072)
    sum(value * value for value in range(300_000))
    time.sleep(0.05)
    profiler.stop()

    measured = [sample for sample in profiler.samples if sample.interval_seconds]
    assert measured
    assert all(sample.tree_cpu_percent >= 0 for sample in measured)
    assert all(sample.write_iops >= 0 for sample in measured)
    assert all(sample.host_disk_write_iops >= 0 for sample in measured)
    assert all(sample.host_network_send_mib_per_second >= 0 for sample in measured)
    assert any(sample.watched_file_count == 1 for sample in profiler.samples)

    summary = profiler.performance_summary()
    phases = profiler.phase_summary()
    assert summary["cpu_percent_semantics"].startswith("tree_cpu_percent")
    assert "machine-wide" in summary["host_counter_semantics"]
    assert "python_or_idle" in phases
    assert "average_host_disk_busy_equivalent_percent" in phases["python_or_idle"]


def test_process_tree_profiler_tolerates_unavailable_private_memory(monkeypatch):
    def unavailable_private_memory(_process):
        raise OSError(87, "NtQueryVirtualMemory is unavailable")

    monkeypatch.setattr(psutil.Process, "memory_full_info", unavailable_private_memory)

    counters = ProcessTreeProfiler._process_counters(psutil.Process())

    assert counters["rss"] > 0
    assert counters["private"] is None or counters["private"] >= 0


@pytest.mark.parametrize(
    ("process_counts", "output_growing", "expected"),
    [
        ({"gdaladdo.exe": 1}, False, "gdal_overviews"),
        ({"gdal_translate.exe": 1}, True, "gdal_translate_and_tiff_write"),
        ({"RasProcess.exe": 1}, False, "terrain_native"),
        (
            {"RasStoreMapHelper.exe": 1},
            True,
            "store_map_native_output_growing",
        ),
        (
            {"RasStoreMapHelper.exe": 1},
            False,
            "store_map_native",
        ),
        ({"python.exe": 1}, False, "python_or_idle"),
    ],
)
def test_process_tree_profiler_phase_inference(
    process_counts,
    output_growing,
    expected,
):
    assert ProcessTreeProfiler._infer_phase(process_counts, output_growing) == expected


def test_raster_signature_is_independent_of_native_tile_layout(tmp_path):
    data = np.arange(64 * 64, dtype="float32").reshape(64, 64)
    paths = []
    for block_size in (16, 32):
        path = tmp_path / f"tile-{block_size}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=64,
            height=64,
            count=1,
            dtype="float32",
            transform=from_origin(100, 200, 1, 1),
            crs="EPSG:32615",
            tiled=True,
            blockxsize=block_size,
            blockysize=block_size,
        ) as destination:
            destination.write(data, 1)
        paths.append(path)

    signatures = [RasTerrain._raster_signature(path) for path in paths]
    assert signatures[0]["block_shapes"] != signatures[1]["block_shapes"]
    assert signatures[0]["pixel_sha256"] == signatures[1]["pixel_sha256"]


def test_raster_signature_uses_unc_safe_path_stat():
    source = inspect.getsource(RasTerrain._raster_signature)
    assert "path.stat().st_size" in source
    assert '"\\\\?\\" + str(path)' not in source


def test_profile_vrt_to_tiff_writes_failure_report(monkeypatch, tmp_path):
    def fail_vrt_to_tiff(**kwargs):
        raise RuntimeError("codec unavailable")

    monkeypatch.setattr(
        RasTerrain,
        "vrt_to_tiff",
        staticmethod(fail_vrt_to_tiff),
    )
    report = tmp_path / "failed.json"

    with pytest.raises(RuntimeError, match="codec unavailable"):
        RasTerrain.profile_vrt_to_tiff(
            tmp_path / "terrain.vrt",
            tmp_path / "terrain.tif",
            report,
            sample_interval_seconds=0.01,
        )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["error_type"] == "RuntimeError"
    assert payload["settings"]["write_options"]["compression"] == "LZW"
    assert payload["settings"]["hecras_version"] == "7.0"


def test_profile_store_maps_failure_report_serializes_paths(monkeypatch, tmp_path):
    estimate = SimpleNamespace(to_dict=lambda: {"terrain_path": tmp_path / "terrain.tif"})
    monkeypatch.setattr(
        RasProcess,
        "estimate_store_map_resources",
        staticmethod(lambda *args, **kwargs: estimate),
    )

    def fail_store_maps(**_kwargs):
        raise MemoryError("insufficient memory")

    monkeypatch.setattr(RasProcess, "store_maps", staticmethod(fail_store_maps))
    report = tmp_path / "store-maps-failed.json"

    with pytest.raises(MemoryError, match="insufficient memory"):
        RasProcess.profile_store_maps(
            "03",
            tmp_path / "maps",
            report,
            map_types=("depth",),
            sample_interval_seconds=0.01,
            ras_object=SimpleNamespace(project_folder=tmp_path),
        )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["resource_estimate"]["terrain_path"] == str(
        tmp_path / "terrain.tif"
    )


def test_raster_performance_notebook_is_safe_and_uses_public_profilers():
    notebook_path = (
        Path(__file__).parents[1]
        / "examples"
        / "730_raster_processing_performance_profiling.ipynb"
    )
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )

    assert all(
        cell.get("execution_count") is None and not cell.get("outputs", [])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )
    assert "RUN_STORE_MAP_PROFILES = False" in code
    assert "RUN_TIFF_PROFILES = False" in code
    assert "RasProcess.estimate_store_map_resources" in code
    assert "RasProcess.profile_store_maps" in code
    assert "RasTerrain.profile_vrt_to_tiff" in code
    assert "semantic_signatures" in code
    assert "overviews_by_band" in code
    assert "H:/" not in code and "H:\\" not in code
