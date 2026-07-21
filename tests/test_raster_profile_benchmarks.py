"""Structural tests for the opt-in raster profiling harnesses."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ROOT / "scripts" / "benchmarks"


def _load_script(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, BENCHMARKS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_watched_output_snapshot_does_not_recurse(tmp_path):
    benchmark = _load_script(
        "benchmark_store_maps_memory_test",
        "benchmark_store_maps_memory.py",
    )
    (tmp_path / "direct.tif").write_bytes(b"direct")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "nested.tif").write_bytes(b"nested")

    monitor = benchmark.ProcessTreeMonitor(0.1, watch_paths=[tmp_path])

    assert monitor._watched_file_snapshot() == (1, len(b"direct"))


def test_matrix_lock_rejects_a_live_owner_and_releases(tmp_path):
    matrix = _load_script(
        "run_raster_profile_matrix_test",
        "run_raster_profile_matrix.py",
    )
    descriptor, lock_path = matrix._acquire_matrix_lock(tmp_path)

    with pytest.raises(RuntimeError, match="Another profile matrix owns"):
        matrix._acquire_matrix_lock(tmp_path)

    matrix._release_matrix_lock(descriptor, lock_path)
    assert not lock_path.exists()


def test_matrix_boolean_arguments_are_explicit():
    matrix = _load_script(
        "run_raster_profile_matrix_boolean_test",
        "run_raster_profile_matrix.py",
    )

    assert matrix._arguments_to_cli(
        {
            "overviews": False,
            "fix_georef": True,
            "skip_hdf_hash": True,
            "unused": False,
        }
    ) == ["--no-overviews", "--fix-georef", "--skip-hdf-hash"]


def test_store_map_benchmark_builds_typed_child_performance_options():
    benchmark = _load_script(
        "benchmark_store_maps_options_test",
        "benchmark_store_maps_memory.py",
    )
    args = benchmark.build_parser().parse_args(
        [
            "--project-folder",
            "project",
            "--output-path",
            "output",
            "--report-path",
            "report.json",
            "--max-workers",
            "2",
            "--memory-per-worker-mb",
            "700",
            "--reserve-memory-mb",
            "5000",
            "--gdal-cachemax-mb",
            "256",
            "--gdal-num-threads",
            "ALL_CPUS",
        ]
    )

    options = benchmark._performance_options_from_args(args)

    assert options.max_workers == 2
    assert options.minimum_worker_memory_mb == 700
    assert options.reserve_memory_mb == 5000
    assert options.gdal_cachemax_mb == 256
    assert options.gdal_num_threads_per_helper == "ALL_CPUS"


def test_terrain_benchmark_builds_typed_gdal_write_options():
    _load_script("benchmark_store_maps_memory", "benchmark_store_maps_memory.py")
    benchmark = _load_script(
        "benchmark_terrain_options_test",
        "benchmark_terrain_functions.py",
    )
    args = benchmark.build_parser().parse_args(
        [
            "--operation",
            "vrt_to_tiff",
            "--input",
            "terrain.vrt",
            "--output",
            "terrain.tif",
            "--report-path",
            "report.json",
            "--compression",
            "DEFLATE",
            "--threads",
            "ALL_CPUS",
            "--gdal-cachemax-mb",
            "256",
        ]
    )

    options = benchmark._write_options_from_args(args, [2, 4, 8])

    assert options.compression == "DEFLATE"
    assert options.gdal_num_threads == "ALL_CPUS"
    assert options.gdal_cachemax_mb == 256
    assert options.overview_levels == (2, 4, 8)


def test_bald_eagle_matrix_covers_functions_storage_and_settings():
    manifest = json.loads(
        (BENCHMARKS / "fixtures" / "bald_eagle_raster_profile_matrix.json").read_text(
            encoding="utf-8"
        )
    )
    runs = manifest["runs"]
    store_runs = [run for run in runs if run["runner"] == "store_maps"]
    terrain_runs = [run for run in runs if run["runner"] == "terrain"]

    assert manifest["schema"] == "ras-commander.raster-profile-matrix/1"
    assert sum(int(run.get("repeat", 1)) for run in runs) == 45
    assert {run["args"]["operation"] for run in store_runs} == {
        "store_maps",
        "store_maps_at_timesteps",
        "store_all_maps",
    }
    assert {run["args"]["operation"] for run in terrain_runs} == {
        "vrt_to_tiff",
        "create_terrain_hdf",
        "create_terrain_from_rasters",
    }

    run_ids = {run["id"] for run in runs}
    for stem in (
        "store_depth_serial",
        "store_all3_serial",
        "store_all3_workers2",
        "store_all3_auto",
        "timesteps_depth_serial",
        "timesteps_all3_workers2",
        "store_all_plans_depth_serial",
        "store_all_plans_all3_workers2",
        "terrain_hdf_threads1",
        "terrain_hdf_allcpus",
        "terrain_convenience_threads1",
        "terrain_convenience_allcpus",
        "vrt_lzw_threads1_overviews",
        "vrt_lzw_allcpus_overviews",
        "vrt_lzw_threads1_no_overviews",
        "vrt_deflate_allcpus_overviews",
    ):
        assert f"{stem}_local" in run_ids
        assert f"{stem}_network" in run_ids

    assert {run["args"].get("max_workers") for run in store_runs} >= {"1", "2", "auto"}
    assert {run["args"].get("gdal_cachemax_mb") for run in runs} >= {None, "64", "256"}
    assert any(run["args"].get("fix_georef") is False for run in runs)


def test_spring_matrix_is_selected_and_memory_safe():
    manifest = json.loads(
        (BENCHMARKS / "fixtures" / "spring_river_raster_profile_matrix.json").read_text(
            encoding="utf-8"
        )
    )
    runs = manifest["runs"]

    assert len(runs) == 6
    assert all(run["args"]["skip_hdf_hash"] is True for run in runs)
    assert all(run["args"]["max_workers"] in {"1", "auto"} for run in runs)
    assert {"local", "network"} == {
        suffix for run in runs for suffix in (run["id"].rsplit("_", 1)[-1],)
    }
