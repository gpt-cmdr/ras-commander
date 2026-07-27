"""Benchmark the original and copied TiffAssist assemblies.

Synthetic mode isolates TiffAssist itself. Store-map mode calls ras-commander's
native helper API against an explicit copied runtime and a disposable real
project. Both modes verify decoded pixels and TIFF metadata.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psutil
import rasterio

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ras_commander import init_ras_project  # noqa: E402
from ras_commander.RasterPerformance import ProcessTreeProfiler  # noqa: E402
from ras_commander._native_helper import run_store_map_helper  # noqa: E402

EXPERIMENT_ENVIRONMENT = (
    "RASCOMMANDER_TIFF_EXPERIMENT",
    "RASCOMMANDER_TIFF_BATCH_BYTES",
    "RASCOMMANDER_TIFF_REUSE_BUFFER",
    "RASCOMMANDER_TIFF_STATS_MODE",
    "RASCOMMANDER_TIFF_WRITE_PROFILE",
    "RASCOMMANDER_TIFF_PIPELINE_WORKERS",
    "RASCOMMANDER_TIFF_PIPELINE_QUEUE_DEPTH",
)
EXPECTED_PATCH_ID = "tiffassist-parallel-tiles-v2"
MINIMUM_BATCH_BYTES = 64 * 1024
MAXIMUM_BATCH_BYTES = 64 * 1024 * 1024
EXPECTED_HEC_RAS_70_HASHES = {
    "TiffAssist.dll": "acd6ada0dbaacf5aa314aca9a087fe5c6699ca582afac1c9060c8404f6a254c9",
    "RasMapperLib.dll": "614460c730d83fb0a1e1f98f6c2c6b1ae6b9f14dc228b0706e4517341523dbeb",
    "BitMiracle.LibTiff.NET.dll": "99d4c2698778134d94aa3cc8330a7235cfcbf65a34699c4f0728d75798e9c1f0",
    "Utility.Core.dll": "c3d97a8fca0f0071cd43c8169f4922e1e3b96ae3226cfdd096f3dbc3ecf00edf",
}
NON_SEMANTIC_METADATA_NAMESPACES = {
    # GDAL synthesizes these values from the current file path or physical
    # storage choices. They are not part of decoded raster semantics.
    "DERIVED_SUBDATASETS",
    "IMAGE_STRUCTURE",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def raster_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with rasterio.Env(GDAL_CACHEMAX=64):
        with rasterio.open(path) as source:
            for band in range(1, source.count + 1):
                # Hash full-width row strips so decoded-pixel identity does not
                # depend on the native block/tile layout under test.
                for row_offset in range(0, source.height, 256):
                    row_stop = min(source.height, row_offset + 256)
                    with warnings.catch_warnings():
                        warnings.filterwarnings(
                            "ignore",
                            message="Setting the shape on a NumPy array.*",
                            category=DeprecationWarning,
                        )
                        block = source.read(
                            band,
                            window=((row_offset, row_stop), (0, source.width)),
                        )
                    digest.update(block.tobytes(order="C"))
            profile = {
                "driver": source.driver,
                "width": source.width,
                "height": source.height,
                "count": source.count,
                "dtypes": list(source.dtypes),
                "nodata": source.nodata,
                "crs": str(source.crs) if source.crs else None,
                "transform": list(source.transform)[:6],
                "block_shapes": [list(shape) for shape in source.block_shapes],
                "compression": source.compression.name if source.compression else None,
                "interleaving": (
                    source.interleaving.name if source.interleaving else None
                ),
                "overviews_by_band": [
                    source.overviews(band) for band in range(1, source.count + 1)
                ],
            }
            dataset_metadata_domains = {
                namespace: dict(sorted(source.tags(ns=namespace).items()))
                for namespace in sorted(source.tag_namespaces())
                if namespace not in NON_SEMANTIC_METADATA_NAMESPACES
            }
            band_metadata_domains = []
            for band in range(1, source.count + 1):
                band_metadata_domains.append(
                    {
                        namespace: dict(sorted(source.tags(band, ns=namespace).items()))
                        for namespace in sorted(source.tag_namespaces(band))
                        if namespace not in NON_SEMANTIC_METADATA_NAMESPACES
                    }
                )
            return {
                "path": str(path),
                "bytes": path.stat().st_size,
                "file_sha256": sha256(path),
                "pixel_sha256": digest.hexdigest(),
                "profile": profile,
                "dataset_tags": dict(sorted(source.tags().items())),
                "band_tags": dict(sorted(source.tags(1).items())),
                "band_tags_by_band": [
                    dict(sorted(source.tags(band).items()))
                    for band in range(1, source.count + 1)
                ],
                "dataset_metadata_domains": dataset_metadata_domains,
                "band_metadata_domains": band_metadata_domains,
            }


@contextmanager
def experiment_environment(values: dict[str, str] | None) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in EXPERIMENT_ENVIRONMENT}
    try:
        for name in EXPERIMENT_ENVIRONMENT:
            os.environ.pop(name, None)
        for name, value in (values or {}).items():
            os.environ[name] = value
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def run_monitored(command: list[str], environment: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    tracked = psutil.Process(process.pid)
    peak_rss = 0
    peak_private = 0
    last_io = None
    last_cpu = None
    peak_threads = 0
    while process.poll() is None:
        try:
            memory = tracked.memory_info()
            last_io = tracked.io_counters()
            last_cpu = tracked.cpu_times()
            peak_threads = max(peak_threads, tracked.num_threads())
            peak_rss = max(peak_rss, memory.rss)
            peak_private = max(peak_private, getattr(memory, "private", memory.rss))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        time.sleep(0.02)
    stdout, stderr = process.communicate()
    elapsed = time.perf_counter() - started
    if process.returncode:
        raise RuntimeError(
            f"Harness exited {process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
    harness_report = json.loads(stdout.strip().splitlines()[-1])
    cpu_seconds = 0.0 if last_cpu is None else float(last_cpu.user + last_cpu.system)
    return {
        "wall_seconds": elapsed,
        "returncode": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "peak_rss_bytes": peak_rss,
        "peak_private_bytes": peak_private,
        "peak_threads": peak_threads,
        "cpu_seconds": cpu_seconds,
        "effective_logical_cpus": cpu_seconds / elapsed if elapsed else 0.0,
        "process_io": (
            None
            if last_io is None
            else {
                "read_bytes": last_io.read_bytes,
                "write_bytes": last_io.write_bytes,
                "read_operations": last_io.read_count,
                "write_operations": last_io.write_count,
                "mean_write_bytes": (
                    last_io.write_bytes / last_io.write_count
                    if last_io.write_count
                    else 0.0
                ),
                "write_iops": last_io.write_count / elapsed if elapsed else 0.0,
                "write_mib_per_second": (
                    last_io.write_bytes / (1024 * 1024) / elapsed if elapsed else 0.0
                ),
                "read_iops": last_io.read_count / elapsed if elapsed else 0.0,
                "read_mib_per_second": (
                    last_io.read_bytes / (1024 * 1024) / elapsed if elapsed else 0.0
                ),
            }
        ),
        "harness": harness_report,
    }


def numeric_tag_equivalence(
    reference: dict[str, str], candidate: dict[str, str]
) -> bool:
    """Compare metadata, allowing only floating reduction-order roundoff."""

    if reference.keys() != candidate.keys():
        return False
    numeric_prefixes = ("STATISTICS_", "FRACTION_NODATA")
    for name, expected in reference.items():
        actual = candidate[name]
        if name.startswith(numeric_prefixes):
            try:
                if not math.isclose(
                    float(expected), float(actual), rel_tol=1e-12, abs_tol=1e-12
                ):
                    return False
            except ValueError:
                if expected != actual:
                    return False
        elif expected != actual:
            return False
    return True


def semantic_equivalence(
    reference: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    semantic_profile_fields = (
        "driver",
        "width",
        "height",
        "count",
        "dtypes",
        "nodata",
        "crs",
        "transform",
        "overviews_by_band",
    )
    reference_band_tags = reference.get("band_tags_by_band", [reference["band_tags"]])
    candidate_band_tags = candidate.get("band_tags_by_band", [candidate["band_tags"]])
    comparisons = {
        "pixel_sha256": reference["pixel_sha256"] == candidate["pixel_sha256"],
        "semantic_profile": all(
            reference["profile"].get(field) == candidate["profile"].get(field)
            for field in semantic_profile_fields
        ),
        "dataset_tags": reference["dataset_tags"] == candidate["dataset_tags"],
        "band_tags_numeric": len(reference_band_tags) == len(candidate_band_tags)
        and all(
            numeric_tag_equivalence(expected, actual)
            for expected, actual in zip(reference_band_tags, candidate_band_tags)
        ),
        "dataset_metadata_domains": reference.get("dataset_metadata_domains", {})
        == candidate.get("dataset_metadata_domains", {}),
        "band_metadata_domains": reference.get("band_metadata_domains", [])
        == candidate.get("band_metadata_domains", []),
    }
    return {
        "equivalent": all(comparisons.values()),
        "comparisons": comparisons,
        "band_tags_exact": reference["band_tags"] == candidate["band_tags"],
        "file_bytes_identical": reference["file_sha256"] == candidate["file_sha256"],
    }


def _validate_file_identity(
    identity: dict[str, Any],
    *,
    description: str,
    required_root: Path | None = None,
) -> Path:
    try:
        artifact = Path(identity["path"]).resolve()
        expected_bytes = int(identity["bytes"])
        expected_hash = str(identity["sha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Incomplete file identity for {description}") from exc
    if required_root is not None:
        try:
            artifact.relative_to(required_root)
        except ValueError as exc:
            raise RuntimeError(
                f"Manifest {description} escapes the copied experiment root: {artifact}"
            ) from exc
    if not artifact.is_file():
        raise FileNotFoundError(f"Manifest {description} is missing: {artifact}")
    if artifact.stat().st_size != expected_bytes or sha256(artifact) != expected_hash:
        raise RuntimeError(f"Manifest {description} identity does not match disk")
    return artifact


def load_manifest(path: Path) -> dict[str, Any]:
    path = path.resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "ras-commander.native-tiff-patch-manifest/1":
        raise ValueError(f"Unexpected patch manifest schema: {path}")
    if manifest.get("patch_id") != EXPECTED_PATCH_ID:
        raise ValueError(f"Unexpected patch manifest patch_id: {path}")
    safety = manifest.get("safety", {})
    if not safety.get("installed_hashes_unchanged"):
        raise RuntimeError(
            "Patch manifest does not prove installed hashes were preserved"
        )
    if safety.get("installed_files_opened_for_write") is not False:
        raise RuntimeError(
            "Patch manifest does not prove installed files were read-only"
        )
    if safety.get("patched_assembly_enabled_by_default") is not False:
        raise RuntimeError("Patch manifest does not prove the patch is opt-in")

    root = path.parent.resolve()
    inventory = manifest.get("source_inventory", {})
    if inventory.get("known_build") is not True:
        raise RuntimeError("Patch manifest does not identify the pinned HEC-RAS build")
    install_dir = Path(inventory.get("install_dir", "")).resolve()
    inventory_files = inventory.get("files", {})
    copied_inputs = manifest.get("copied_inputs", {})
    for name, pinned_hash in EXPECTED_HEC_RAS_70_HASHES.items():
        installed_identity = inventory_files.get(name)
        copied_identity = copied_inputs.get(name)
        if not isinstance(installed_identity, dict) or not isinstance(
            copied_identity, dict
        ):
            raise RuntimeError(f"Patch manifest is missing pinned identity for {name}")
        installed = _validate_file_identity(
            installed_identity,
            description=f"installed {name}",
        )
        if installed != (install_dir / name).resolve():
            raise RuntimeError(f"Installed {name} path does not match install_dir")
        if installed_identity["sha256"] != pinned_hash:
            raise RuntimeError(f"Installed {name} is not the pinned HEC-RAS 7.0 file")
        _validate_file_identity(
            copied_identity,
            description=f"copied input {name}",
            required_root=root,
        )
        if copied_identity["sha256"] != pinned_hash:
            raise RuntimeError(f"Copied input {name} is not the pinned source file")

    artifact_identities = manifest.get("artifact_identities", {})
    required_artifacts = {
        "runtime_patched_tiffassist",
        "runtime_original_tiffassist",
        "runtime_patched_minimal_tiffassist",
        "harness_original_exe",
        "harness_patched_exe",
    }
    if set(artifact_identities) != required_artifacts:
        raise RuntimeError("Patch manifest artifact identities are incomplete")
    validated_artifacts = {
        name: _validate_file_identity(
            identity,
            description=name,
            required_root=root,
        )
        for name, identity in artifact_identities.items()
    }
    if (
        artifact_identities["runtime_original_tiffassist"]["sha256"]
        != EXPECTED_HEC_RAS_70_HASHES["TiffAssist.dll"]
    ):
        raise RuntimeError(
            "Original minimal runtime does not contain pinned TiffAssist"
        )
    build_identity = manifest.get("build", {}).get("assembly")
    if not isinstance(build_identity, dict):
        raise RuntimeError("Patch manifest is missing the built assembly identity")
    _validate_file_identity(
        build_identity,
        description="built patched TiffAssist",
        required_root=root,
    )
    patched_hash = build_identity.get("sha256")
    if not patched_hash or any(
        artifact_identities[name]["sha256"] != patched_hash
        for name in (
            "runtime_patched_tiffassist",
            "runtime_patched_minimal_tiffassist",
        )
    ):
        raise RuntimeError("Patched TiffAssist copies do not match the built assembly")
    artifacts = manifest.get("artifacts", {})
    expected_declared_files = {
        "harness_original": validated_artifacts["harness_original_exe"],
        "harness_patched": validated_artifacts["harness_patched_exe"],
    }
    for name, expected in expected_declared_files.items():
        if Path(artifacts.get(name, "")).resolve() != expected:
            raise RuntimeError(f"Declared {name} does not match its verified identity")
    for name in (
        "runtime_patched",
        "runtime_original_minimal",
        "runtime_patched_minimal",
    ):
        declared = Path(artifacts.get(name, "")).resolve()
        try:
            declared.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"Declared {name} escapes the experiment root") from exc
        if not declared.is_dir():
            raise FileNotFoundError(f"Declared runtime is missing: {declared}")
    return manifest


def synthetic_matrix(
    args: argparse.Namespace, manifest: dict[str, Any]
) -> dict[str, Any]:
    output_root = Path(os.path.abspath(args.output_root))
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    original_harness = Path(manifest["artifacts"]["harness_original"])
    patched_harness = Path(manifest["artifacts"]["harness_patched"])
    configurations: list[tuple[str, Path, dict[str, str]]] = [
        ("original", original_harness, {}),
        ("patched_inert", patched_harness, {}),
    ]
    for statistics_mode in args.statistics_modes:
        for batch_bytes in args.batch_bytes:
            for pipeline_workers in args.pipeline_workers:
                if statistics_mode == "native" and pipeline_workers > 0:
                    continue
                queue_depths = args.pipeline_queue_depths if pipeline_workers else [0]
                for queue_depth in queue_depths:
                    settings = {
                        "RASCOMMANDER_TIFF_EXPERIMENT": "1",
                        "RASCOMMANDER_TIFF_BATCH_BYTES": str(batch_bytes),
                        "RASCOMMANDER_TIFF_REUSE_BUFFER": "true",
                        "RASCOMMANDER_TIFF_STATS_MODE": statistics_mode,
                        "RASCOMMANDER_TIFF_WRITE_PROFILE": "true",
                        "RASCOMMANDER_TIFF_PIPELINE_WORKERS": str(pipeline_workers),
                    }
                    queue_label = "auto"
                    if pipeline_workers and queue_depth:
                        settings["RASCOMMANDER_TIFF_PIPELINE_QUEUE_DEPTH"] = str(
                            queue_depth
                        )
                        queue_label = str(queue_depth)
                    configurations.append(
                        (
                            f"patched_{statistics_mode}_{batch_bytes}_w{pipeline_workers}_q{queue_label}",
                            patched_harness,
                            settings,
                        )
                    )

    runs = []
    reference_signature = None
    for identifier, harness, settings in configurations:
        run_dir = output_root / identifier
        run_dir.mkdir()
        output = run_dir / "fixture.tif"
        environment = dict(os.environ)
        for name in EXPERIMENT_ENVIRONMENT:
            environment.pop(name, None)
        environment.update(settings)
        command = [
            str(harness),
            str(output),
            str(args.width),
            str(args.height),
            str(args.repeats),
            str(args.nodata_tile_interval),
            str(args.template_tile_count),
        ]
        execution = run_monitored(command, environment)
        signature = raster_signature(output)
        if reference_signature is None:
            reference_signature = signature
        io_sidecar = output.with_name(output.name + ".rascommander-tiff-profile.json")
        record = {
            "id": identifier,
            "settings": settings,
            "command": command,
            "execution": execution,
            "raster": signature,
            "equivalence": semantic_equivalence(reference_signature, signature),
            "tiff_io": (
                json.loads(io_sidecar.read_text(encoding="utf-8-sig"))
                if io_sidecar.is_file()
                else None
            ),
        }
        runs.append(record)
        (run_dir / "report.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )

    report = {
        "schema": "ras-commander.native-tiff-synthetic-benchmark/2",
        "patch_manifest": str(args.manifest),
        "configuration": {
            "width": args.width,
            "height": args.height,
            "repeats": args.repeats,
            "nodata_tile_interval": args.nodata_tile_interval,
            "template_tile_count": args.template_tile_count,
            "batch_bytes": args.batch_bytes,
            "statistics_modes": args.statistics_modes,
            "pipeline_workers": args.pipeline_workers,
            "pipeline_queue_depths": args.pipeline_queue_depths,
        },
        "runs": runs,
        "all_semantically_equivalent": all(
            run["equivalence"]["equivalent"] for run in runs
        ),
    }
    write_summary(output_root, report)
    return report


def locate_single_tiff(folder: Path) -> Path:
    candidates = sorted(folder.glob("*.tif")) + sorted(folder.glob("*.tiff"))
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one TIFF in {folder}, found {len(candidates)}")
    return candidates[0]


def run_store_map_case(
    identifier: str,
    runtime: Path,
    result_hdf: Path,
    project_folder: Path,
    output_root: Path,
    map_type: str,
    profile: str,
    timeout: int,
    settings: dict[str, str],
) -> dict[str, Any]:
    case_dir = output_root / identifier
    case_dir.mkdir()
    output_base = case_dir / f"{map_type} ({profile})"
    before_hdf = {"bytes": result_hdf.stat().st_size, "sha256": sha256(result_hdf)}
    started = time.perf_counter()
    profiler = ProcessTreeProfiler(
        sample_interval_seconds=0.1,
        watch_paths=(case_dir,),
    )
    profiler.start()
    try:
        with experiment_environment(settings):
            result = run_store_map_helper(
                hecras_dir=runtime,
                render_mode="horizontal",
                map_type=map_type,
                result_hdf_path=result_hdf,
                profile_name=profile,
                output_base_path=output_base,
                timeout=timeout,
                working_dir=project_folder,
                gdal_num_threads=1,
                gdal_cachemax_mb=64,
            )
    finally:
        profiler.stop()
    elapsed = time.perf_counter() - started
    if result.returncode:
        raise RuntimeError(
            f"StoreMap {identifier} exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    after_hdf = {"bytes": result_hdf.stat().st_size, "sha256": sha256(result_hdf)}
    output = locate_single_tiff(case_dir)
    output_sidecar = output.with_name(output.name + ".rascommander-tiff-profile.json")
    resource_profile = profiler.performance_summary()
    execution = {
        "wall_seconds": elapsed,
        "cpu_seconds": resource_profile["cpu_seconds"],
        "effective_logical_cpus": (
            resource_profile["average_tree_cpu_percent"] / 100.0
        ),
        "peak_private_bytes": (
            int(profiler.peak_tree_private_mb * 1024 * 1024)
            if profiler.peak_tree_private_mb is not None
            else 0
        ),
        "peak_rss_bytes": int(profiler.peak_tree_rss_mb * 1024 * 1024),
        "process_io": {
            "read_bytes": None,
            "write_bytes": None,
            "read_operations": None,
            "write_operations": None,
            "mean_write_bytes": resource_profile["mean_write_size_bytes"],
            "write_iops": resource_profile["average_write_iops"],
            "write_mib_per_second": resource_profile["average_write_mib_per_second"],
            "read_iops": resource_profile["average_read_iops"],
            "read_mib_per_second": resource_profile["average_read_mib_per_second"],
        },
    }
    return {
        "id": identifier,
        "runtime": str(runtime),
        "runtime_tiffassist_sha256": sha256(runtime / "TiffAssist.dll"),
        "settings": settings,
        "elapsed_seconds": elapsed,
        "execution": execution,
        "resource_profile": resource_profile,
        "phase_profile": profiler.phase_summary(),
        "resource_samples": [sample.to_dict() for sample in profiler.samples],
        "stdout": result.stdout,
        "stderr": result.stderr,
        "result_hdf_preserved": before_hdf == after_hdf,
        "raster": raster_signature(output),
        "tiff_io": (
            json.loads(output_sidecar.read_text(encoding="utf-8-sig"))
            if output_sidecar.is_file()
            else None
        ),
    }


def store_map_runs_equivalent(runs: list[dict[str, Any]]) -> bool:
    """Require raster equivalence and source-HDF preservation for every run."""

    return all(
        run.get("result_hdf_preserved") is True
        and run.get("equivalence", {}).get("equivalent", True)
        for run in runs
    )


def store_map_pair(
    args: argparse.Namespace, manifest: dict[str, Any]
) -> dict[str, Any]:
    if str(args.ras_version) != "7.0":
        raise ValueError(
            "The copied TiffAssist experiment is pinned to HEC-RAS 7.0; "
            f"received --ras-version {args.ras_version!r}"
        )
    if "none" in args.store_map_statistics_modes:
        raise ValueError(
            "statistics mode 'none' is synthetic-only because normal StoreMap "
            "histogram/statistics metadata is part of the product contract"
        )
    output_root = Path(os.path.abspath(args.output_root))
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    project_folder = Path(os.path.abspath(args.project_folder))
    ras = init_ras_project(project_folder, args.ras_version)
    plan_number = str(args.plan_number).zfill(2)
    rows = ras.plan_df.loc[ras.plan_df["plan_number"] == plan_number]
    if len(rows) != 1:
        raise ValueError(f"Plan {plan_number} did not resolve uniquely")
    result_hdf = Path(rows.iloc[0]["HDF_Results_Path"])
    install_runtime = Path(manifest["source_inventory"]["install_dir"])
    patched_runtime = Path(manifest["artifacts"]["runtime_patched"])

    original = run_store_map_case(
        "original",
        install_runtime,
        result_hdf,
        project_folder,
        output_root,
        args.map_type,
        args.profile,
        args.timeout,
        {},
    )
    runs = [original]
    for statistics_mode in args.store_map_statistics_modes:
        for pipeline_workers in args.store_map_pipeline_workers:
            if statistics_mode == "native" and pipeline_workers > 0:
                continue
            settings = {
                "RASCOMMANDER_TIFF_EXPERIMENT": "1",
                "RASCOMMANDER_TIFF_BATCH_BYTES": str(args.store_map_batch_bytes),
                "RASCOMMANDER_TIFF_REUSE_BUFFER": "true",
                "RASCOMMANDER_TIFF_STATS_MODE": statistics_mode,
                "RASCOMMANDER_TIFF_WRITE_PROFILE": "true",
                "RASCOMMANDER_TIFF_PIPELINE_WORKERS": str(pipeline_workers),
            }
            if pipeline_workers and args.store_map_pipeline_queue_depth:
                settings["RASCOMMANDER_TIFF_PIPELINE_QUEUE_DEPTH"] = str(
                    args.store_map_pipeline_queue_depth
                )
            patched = run_store_map_case(
                f"patched_{statistics_mode}_{args.store_map_batch_bytes}_w{pipeline_workers}",
                patched_runtime,
                result_hdf,
                project_folder,
                output_root,
                args.map_type,
                args.profile,
                args.timeout,
                settings,
            )
            patched["equivalence"] = semantic_equivalence(
                original["raster"], patched["raster"]
            )
            runs.append(patched)
    report = {
        "schema": "ras-commander.native-tiff-store-map-benchmark/2",
        "patch_manifest": str(args.manifest),
        "project_folder": str(project_folder),
        "plan_number": plan_number,
        "result_hdf": str(result_hdf),
        "map_type": args.map_type,
        "profile": args.profile,
        "runs": runs,
        "all_semantically_equivalent": store_map_runs_equivalent(runs),
    }
    write_summary(output_root, report)
    return report


def write_summary(output_root: Path, report: dict[str, Any]) -> None:
    report_path = output_root / "summary.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    rows = []
    for run in report["runs"]:
        execution = run.get("execution", {})
        io = execution.get("process_io") or {}
        tiff_io = run.get("tiff_io") or {}
        raster_equivalent = run.get("equivalence", {}).get("equivalent", True)
        hdf_preserved = run.get("result_hdf_preserved")
        rows.append(
            {
                "id": run["id"],
                "seconds": execution.get("wall_seconds", run.get("elapsed_seconds")),
                "process_write_operations": io.get("write_operations"),
                "process_mean_write_bytes": io.get("mean_write_bytes"),
                "process_write_iops": io.get("write_iops"),
                "process_write_mib_per_second": io.get("write_mib_per_second"),
                "effective_logical_cpus": execution.get("effective_logical_cpus"),
                "peak_private_mib": (
                    execution.get("peak_private_bytes", 0) / (1024 * 1024)
                    if execution
                    else None
                ),
                "tiff_logical_write_calls": tiff_io.get("logical_write_calls"),
                "tiff_underlying_write_calls": tiff_io.get("underlying_write_calls"),
                "tiff_mean_underlying_write_bytes": tiff_io.get(
                    "mean_underlying_write_bytes"
                ),
                "pipeline_workers": tiff_io.get("pipeline_workers"),
                "pipeline_queue_depth": tiff_io.get("pipeline_queue_depth"),
                "pipeline_wall_seconds": tiff_io.get("pipeline_wall_seconds"),
                "prepare_seconds": tiff_io.get("prepare_seconds"),
                "deflate_seconds": tiff_io.get("deflate_seconds"),
                "raw_commit_seconds": tiff_io.get("raw_commit_seconds"),
                "maximum_owned_tiles": tiff_io.get("maximum_owned_tiles"),
                "pixel_sha256": run["raster"]["pixel_sha256"],
                "equivalent": raster_equivalent,
                "result_hdf_preserved": hdf_preserved,
                "accepted": raster_equivalent
                and (hdf_preserved is None or hdf_preserved is True),
            }
        )
    with (output_root / "summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    markdown = [
        "# Copied TiffAssist benchmark",
        "",
        "| Run | Seconds | Effective CPUs | Peak private MiB | Workers | Pipeline s | Prepare s | Deflate s | Commit s | Process writes | TIFF writes | Equivalent |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for row in rows:
        markdown.append(
            "| {id} | {seconds:.3f} | {effective_logical_cpus} | {peak_private_mib} | "
            "{pipeline_workers} | {pipeline_wall_seconds} | {prepare_seconds} | "
            "{deflate_seconds} | {raw_commit_seconds} | {process_write_operations} | "
            "{tiff_underlying_write_calls} | "
            "{equivalent} |".format(**row)
        )
    markdown.extend(
        [
            "",
            f"All decoded pixels and selected metadata equivalent: **{report['all_semantically_equivalent']}**",
            "",
        ]
    )
    (output_root / "summary.md").write_text("\n".join(markdown), encoding="utf-8")


def parse_csv_ints(value: str) -> list[int]:
    result = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not result:
        raise argparse.ArgumentTypeError("At least one integer is required")
    if any(item < MINIMUM_BATCH_BYTES or item > MAXIMUM_BATCH_BYTES for item in result):
        raise argparse.ArgumentTypeError(
            f"Batch sizes must be {MINIMUM_BATCH_BYTES} through {MAXIMUM_BATCH_BYTES}"
        )
    return result


def parse_batch_bytes(value: str) -> int:
    """Parse one bounded TIFF client-I/O batch size."""
    values = parse_csv_ints(value)
    if len(values) != 1:
        raise argparse.ArgumentTypeError("Exactly one batch size is required")
    return values[0]


def parse_stats_modes(value: str) -> list[str]:
    result = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not result or any(item not in {"native", "serial", "none"} for item in result):
        raise argparse.ArgumentTypeError(
            "Statistics modes must be native, serial, and/or none"
        )
    return result


def parse_worker_counts(value: str) -> list[int]:
    result = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not result or any(item < 0 or item > 32 for item in result):
        raise argparse.ArgumentTypeError("Pipeline workers must be between 0 and 32")
    return result


def parse_queue_depths(value: str) -> list[int]:
    result = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not result or any(item < 0 or item > 128 for item in result):
        raise argparse.ArgumentTypeError(
            "Pipeline queue depths must be 0 (automatic) or 1 through 128"
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("synthetic", "store-map"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--width", type=int, default=8192)
    parser.add_argument("--height", type=int, default=8192)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--nodata-tile-interval",
        type=int,
        default=0,
        help="Write every Nth tile through the raw NoData path; 0 disables",
    )
    parser.add_argument(
        "--template-tile-count",
        type=int,
        default=0,
        help="Reuse N pre-generated tiles to isolate writer scaling; 0 generates every tile",
    )
    parser.add_argument(
        "--batch-bytes",
        type=parse_csv_ints,
        default=parse_csv_ints(
            "65536,262144,1048576,2097152,8388608,16777216,67108864"
        ),
    )
    parser.add_argument(
        "--statistics-modes",
        type=parse_stats_modes,
        default=parse_stats_modes("native,serial"),
    )
    parser.add_argument(
        "--pipeline-workers",
        type=parse_worker_counts,
        default=parse_worker_counts("0,1,2,4,8"),
    )
    parser.add_argument(
        "--pipeline-queue-depths",
        type=parse_queue_depths,
        default=parse_queue_depths("0"),
        help="0 uses the copied assembly's automatic bounded depth",
    )
    parser.add_argument("--project-folder", type=Path)
    parser.add_argument("--plan-number", default="15")
    parser.add_argument("--ras-version", default="7.0")
    parser.add_argument("--map-type", default="Depth")
    parser.add_argument("--profile", default="Max")
    parser.add_argument(
        "--store-map-batch-bytes",
        type=parse_batch_bytes,
        default=2097152,
    )
    parser.add_argument(
        "--store-map-statistics-modes",
        type=parse_stats_modes,
        default=parse_stats_modes("native,serial"),
    )
    parser.add_argument(
        "--store-map-pipeline-workers",
        type=parse_worker_counts,
        default=parse_worker_counts("0,2,4,8"),
    )
    parser.add_argument(
        "--store-map-pipeline-queue-depth",
        type=int,
        choices=range(0, 129),
        default=0,
        help="0 uses the copied assembly's automatic bounded depth",
    )
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument(
        "--allow-non-equivalent",
        action="store_true",
        help=(
            "Synthetic mode only: return success for intentionally non-equivalent "
            "controls such as statistics mode none"
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = load_manifest(args.manifest)
    if args.allow_non_equivalent and args.mode != "synthetic":
        raise ValueError("--allow-non-equivalent is available only in synthetic mode")
    if args.mode == "synthetic":
        report = synthetic_matrix(args, manifest)
    else:
        if args.project_folder is None:
            raise ValueError("--project-folder is required for store-map mode")
        report = store_map_pair(args, manifest)
    # Recheck all installed, copied-runtime, harness, and patched-assembly
    # identities after the benchmark as well as before it.
    load_manifest(args.manifest)
    print(json.dumps(report, indent=2))
    return (
        0 if report["all_semantically_equivalent"] or args.allow_non_equivalent else 3
    )


if __name__ == "__main__":
    sys.exit(main())
