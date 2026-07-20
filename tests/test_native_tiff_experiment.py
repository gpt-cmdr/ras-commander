"""Focused safety and contract tests for the copied TiffAssist experiment."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "scripts" / "benchmarks" / "native_tiff_experiments"


def load_module(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, EXPERIMENT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_patch_is_version_pinned_and_opt_in():
    prepare = load_module("prepare_copied_assembly.py", "native_tiff_prepare")
    assert prepare.PATCH_ID == "tiffassist-parallel-tiles-v2"
    assert set(prepare.KNOWN_HEC_RAS_70) == {
        "TiffAssist.dll",
        "RasMapperLib.dll",
        "BitMiracle.LibTiff.NET.dll",
        "Utility.Core.dll",
    }
    source = (EXPERIMENT / "patches" / "ExperimentalTiffIO.cs").read_text(
        encoding="utf-8"
    )
    assert 'Enabled => ReadBoolean("RASCOMMANDER_TIFF_EXPERIMENT", false)' in source
    assert "MinimumBatchBytes = 64 * 1024" in source
    assert "MaximumBatchBytes = 64 * 1024 * 1024" in source
    assert 'ReadInteger("RASCOMMANDER_TIFF_PIPELINE_WORKERS", 0)' in source
    assert 'ReadInteger("RASCOMMANDER_TIFF_PIPELINE_QUEUE_DEPTH", fallback)' in source
    assert "int fallback = 2;" in source
    assert "BlockingCollection<TileWorkItem>" in source
    assert "ExperimentalRawTileEncoder" in source
    assert "outputPool.Rent(_maximumEncodedBytes)" in source
    assert "RawCommitTicks" in source
    prepare_source = (EXPERIMENT / "prepare_copied_assembly.py").read_text(
        encoding="utf-8"
    )
    assert "WriteRawTileInternal" in prepare_source
    assert "_tiffImage.SetWriteOffset(0L);" in prepare_source


def test_replace_exact_fails_closed_when_decompilation_anchor_drifts():
    prepare = load_module("prepare_copied_assembly.py", "native_tiff_replace")
    assert prepare.replace_exact("alpha beta", "beta", "gamma", "demo") == (
        "alpha gamma"
    )
    with pytest.raises(RuntimeError, match="occurred 0 times"):
        prepare.replace_exact("alpha", "beta", "gamma", "demo")
    with pytest.raises(RuntimeError, match="occurred 2 times"):
        prepare.replace_exact("beta beta", "beta", "gamma", "demo")


def test_manifest_loader_requires_safety_proof(tmp_path):
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_benchmark")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "ras-commander.native-tiff-patch-manifest/1",
                "patch_id": "tiffassist-parallel-tiles-v2",
                "safety": {"installed_hashes_unchanged": False},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="installed hashes"):
        benchmark.load_manifest(manifest)


def _file_identity(path: Path):
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_valid_manifest(benchmark, tmp_path: Path) -> Path:
    experiment_root = tmp_path / "copied-experiment"
    install_dir = tmp_path / "installed"
    originals = experiment_root / "assemblies" / "original"
    runtime_patched = experiment_root / "runtime_patched"
    runtime_original = experiment_root / "runtime_original_minimal"
    runtime_patched_minimal = experiment_root / "runtime_patched_minimal"
    harness_original_dir = experiment_root / "harness_original"
    harness_patched_dir = experiment_root / "harness_patched"
    build_dir = experiment_root / "source" / "bin"
    for folder in (
        install_dir,
        originals,
        runtime_patched,
        runtime_original,
        runtime_patched_minimal,
        harness_original_dir,
        harness_patched_dir,
        build_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)

    pinned_hashes = {}
    inventory_files = {}
    copied_inputs = {}
    for name in benchmark.EXPECTED_HEC_RAS_70_HASHES:
        payload = f"pinned-{name}".encode()
        installed = install_dir / name
        copied = originals / name
        installed.write_bytes(payload)
        copied.write_bytes(payload)
        pinned_hashes[name] = hashlib.sha256(payload).hexdigest()
        inventory_files[name] = _file_identity(installed)
        copied_inputs[name] = _file_identity(copied)

    benchmark.EXPECTED_HEC_RAS_70_HASHES = pinned_hashes
    patched_payload = b"patched-tiffassist"
    built = build_dir / "TiffAssist.dll"
    patched_runtime_dll = runtime_patched / "TiffAssist.dll"
    patched_minimal_dll = runtime_patched_minimal / "TiffAssist.dll"
    original_runtime_dll = runtime_original / "TiffAssist.dll"
    for path in (built, patched_runtime_dll, patched_minimal_dll):
        path.write_bytes(patched_payload)
    original_runtime_dll.write_bytes(b"pinned-TiffAssist.dll")
    harness_original = harness_original_dir / "TiffAssistExperimentHarness.exe"
    harness_patched = harness_patched_dir / "TiffAssistExperimentHarness.exe"
    harness_original.write_bytes(b"original-harness")
    harness_patched.write_bytes(b"patched-harness")

    manifest = {
        "schema": "ras-commander.native-tiff-patch-manifest/1",
        "patch_id": benchmark.EXPECTED_PATCH_ID,
        "safety": {
            "installed_files_opened_for_write": False,
            "installed_hashes_unchanged": True,
            "patched_assembly_enabled_by_default": False,
        },
        "source_inventory": {
            "install_dir": str(install_dir.resolve()),
            "files": inventory_files,
            "known_build": True,
        },
        "copied_inputs": copied_inputs,
        "build": {"assembly": _file_identity(built)},
        "artifacts": {
            "runtime_patched": str(runtime_patched.resolve()),
            "runtime_original_minimal": str(runtime_original.resolve()),
            "runtime_patched_minimal": str(runtime_patched_minimal.resolve()),
            "harness_original": str(harness_original.resolve()),
            "harness_patched": str(harness_patched.resolve()),
        },
        "artifact_identities": {
            "runtime_patched_tiffassist": _file_identity(patched_runtime_dll),
            "runtime_original_tiffassist": _file_identity(original_runtime_dll),
            "runtime_patched_minimal_tiffassist": _file_identity(patched_minimal_dll),
            "harness_original_exe": _file_identity(harness_original),
            "harness_patched_exe": _file_identity(harness_patched),
        },
    }
    path = experiment_root / "patch_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_manifest_loader_rejects_wrong_patch_id_even_with_safety_true(tmp_path):
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_patch_id")
    manifest = _write_valid_manifest(benchmark, tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["patch_id"] = "forged"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="patch_id"):
        benchmark.load_manifest(manifest)


def test_manifest_loader_rejects_tampered_copied_assembly(tmp_path):
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_tamper")
    manifest = _write_valid_manifest(benchmark, tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    patched = Path(payload["artifact_identities"]["runtime_patched_tiffassist"]["path"])
    patched.write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="identity does not match"):
        benchmark.load_manifest(manifest)


def test_manifest_loader_accepts_complete_pinned_manifest(tmp_path):
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_valid")
    manifest = _write_valid_manifest(benchmark, tmp_path)

    loaded = benchmark.load_manifest(manifest)

    assert loaded["patch_id"] == benchmark.EXPECTED_PATCH_ID


def test_batch_and_statistics_parsers_enforce_supported_matrix():
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_parsers")
    assert benchmark.parse_csv_ints("65536,262144,1048576,8388608,67108864") == [
        65536,
        262144,
        1048576,
        8388608,
        67108864,
    ]
    assert benchmark.parse_batch_bytes("16777216") == 16777216
    assert benchmark.parse_stats_modes("native,serial") == ["native", "serial"]
    assert benchmark.parse_stats_modes("serial,none") == ["serial", "none"]
    assert benchmark.parse_worker_counts("0,1,4,8") == [0, 1, 4, 8]
    assert benchmark.parse_queue_depths("0,4,16") == [0, 4, 16]
    with pytest.raises(Exception):
        benchmark.parse_csv_ints("4096")
    with pytest.raises(Exception):
        benchmark.parse_csv_ints("134217728")
    with pytest.raises(Exception):
        benchmark.parse_batch_bytes("65536,262144")
    with pytest.raises(Exception):
        benchmark.parse_stats_modes("invalid")
    with pytest.raises(Exception):
        benchmark.parse_worker_counts("33")
    with pytest.raises(Exception):
        benchmark.parse_queue_depths("129")


def test_benchmark_defaults_cover_large_batches_and_propose_two_mib():
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_defaults")

    args = benchmark.build_parser().parse_args(
        [
            "synthetic",
            "--manifest",
            "manifest.json",
            "--output-root",
            "output",
        ]
    )

    assert args.store_map_batch_bytes == 2 * 1024 * 1024
    assert args.batch_bytes == [
        64 * 1024,
        256 * 1024,
        1024 * 1024,
        2 * 1024 * 1024,
        8 * 1024 * 1024,
        16 * 1024 * 1024,
        64 * 1024 * 1024,
    ]


def test_statistics_equivalence_allows_only_tiny_numeric_roundoff():
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_metadata")
    reference = {
        "STATISTICS_STDDEV": "13.8189824136967",
        "TYPE": "Depth",
    }
    assert benchmark.numeric_tag_equivalence(
        reference,
        {"STATISTICS_STDDEV": "13.8189824136931", "TYPE": "Depth"},
    )
    assert not benchmark.numeric_tag_equivalence(
        reference,
        {"STATISTICS_STDDEV": "13.81898", "TYPE": "Depth"},
    )
    assert not benchmark.numeric_tag_equivalence(
        reference,
        {"STATISTICS_STDDEV": "13.8189824136967", "TYPE": "Velocity"},
    )


def test_semantic_equivalence_rejects_missing_overviews():
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_overviews")
    base = {
        "pixel_sha256": "same",
        "profile": {
            "driver": "GTiff",
            "width": 10,
            "height": 10,
            "count": 1,
            "dtypes": ["float32"],
            "nodata": -9999.0,
            "crs": "EPSG:32615",
            "transform": [1, 0, 0, 0, -1, 0],
            "overviews_by_band": [[2, 4, 8]],
        },
        "dataset_tags": {},
        "band_tags": {},
        "band_tags_by_band": [{}],
        "dataset_metadata_domains": {},
        "band_metadata_domains": [{}],
        "file_sha256": "a",
    }
    candidate = json.loads(json.dumps(base))
    candidate["profile"]["overviews_by_band"] = []

    result = benchmark.semantic_equivalence(base, candidate)

    assert result["equivalent"] is False
    assert result["comparisons"]["semantic_profile"] is False


def test_semantic_equivalence_ignores_path_and_storage_metadata_domains():
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_domains")
    assert benchmark.NON_SEMANTIC_METADATA_NAMESPACES == {
        "DERIVED_SUBDATASETS",
        "IMAGE_STRUCTURE",
    }

    # These domains are excluded while signatures are collected because the
    # first embeds the output path and the second records physical TIFF layout.
    # Arbitrary application metadata remains subject to exact comparison.
    reference = {
        "pixel_sha256": "same",
        "profile": {
            "driver": "GTiff",
            "width": 10,
            "height": 10,
            "count": 1,
            "dtypes": ["float32"],
            "nodata": -9999.0,
            "crs": "EPSG:32615",
            "transform": [1, 0, 0, 0, -1, 0],
            "overviews_by_band": [[2, 4]],
        },
        "dataset_tags": {},
        "band_tags": {},
        "band_tags_by_band": [{}],
        "dataset_metadata_domains": {"CUSTOM": {"PRODUCT": "Depth"}},
        "band_metadata_domains": [{}],
        "file_sha256": "different-physical-layout-is-allowed",
    }
    candidate = json.loads(json.dumps(reference))

    assert benchmark.semantic_equivalence(reference, candidate)["equivalent"]
    candidate["dataset_metadata_domains"]["CUSTOM"]["PRODUCT"] = "Velocity"
    assert not benchmark.semantic_equivalence(reference, candidate)["equivalent"]


def test_native_pixel_digest_is_independent_of_tile_layout(tmp_path):
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_layout")
    data = np.arange(64 * 64, dtype="float32").reshape(64, 64)
    signatures = []
    for size in (16, 32):
        path = tmp_path / f"tile-{size}.tif"
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
            blockxsize=size,
            blockysize=size,
        ) as destination:
            destination.write(data, 1)
        signatures.append(benchmark.raster_signature(path))

    assert (
        signatures[0]["profile"]["block_shapes"]
        != signatures[1]["profile"]["block_shapes"]
    )
    assert signatures[0]["pixel_sha256"] == signatures[1]["pixel_sha256"]


def test_store_map_cli_fails_when_source_hdf_is_not_preserved(monkeypatch, tmp_path):
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_hdf")
    runs = [
        {
            "result_hdf_preserved": False,
            "equivalence": {"equivalent": True},
        }
    ]
    report = {
        "runs": runs,
        "all_semantically_equivalent": benchmark.store_map_runs_equivalent(runs),
    }
    monkeypatch.setattr(benchmark, "load_manifest", lambda _path: {})
    monkeypatch.setattr(benchmark, "store_map_pair", lambda _args, _manifest: report)
    monkeypatch.setattr(
        benchmark.sys,
        "argv",
        [
            "benchmark_copied_tiffassist.py",
            "store-map",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--output-root",
            str(tmp_path / "output"),
            "--project-folder",
            str(tmp_path / "project"),
        ],
    )

    assert benchmark.main() == 3


def test_store_map_experiment_rejects_non_pinned_ras_version(tmp_path):
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_version")
    args = benchmark.build_parser().parse_args(
        [
            "store-map",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--output-root",
            str(tmp_path / "output"),
            "--project-folder",
            str(tmp_path / "project"),
            "--ras-version",
            "6.6",
        ]
    )

    with pytest.raises(ValueError, match="pinned to HEC-RAS 7.0"):
        benchmark.store_map_pair(args, {})


def test_store_map_experiment_rejects_no_statistics_mode(tmp_path):
    benchmark = load_module("benchmark_copied_tiffassist.py", "native_tiff_no_stats")
    args = benchmark.build_parser().parse_args(
        [
            "store-map",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--output-root",
            str(tmp_path / "output"),
            "--project-folder",
            str(tmp_path / "project"),
            "--store-map-statistics-modes",
            "none",
        ]
    )

    with pytest.raises(ValueError, match="synthetic-only"):
        benchmark.store_map_pair(args, {})


def test_safe_remove_rejects_paths_outside_owned_working_root(tmp_path):
    prepare = load_module("prepare_copied_assembly.py", "native_tiff_remove")
    with pytest.raises(RuntimeError, match="outside experiment working root"):
        prepare.safe_remove(tmp_path)
