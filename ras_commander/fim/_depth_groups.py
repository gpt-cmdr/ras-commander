"""Supervise native grouped maxima; no Python pixel reduction or HEC runtime."""

from collections import OrderedDict
from collections.abc import Mapping
from contextlib import redirect_stdout
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

from ._catalog import (
    _check_sources,
    _normalise_jobs,
    _terminate,
    _worker_count,
    _write_json,
)
from .errors import FimEngineError, FimMappingError, FimUnsupportedError


def _normalise(jobs):
    if isinstance(jobs, (str, bytes, Mapping)):
        raise TypeError("jobs must be a sequence of job mappings")
    ordinary, groups = [], []
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    for raw in jobs:
        if not isinstance(raw, Mapping):
            raise TypeError("Each grouped job must be a mapping")
        raw = dict(raw)
        if "timesteps" in raw:
            raise ValueError("Grouped jobs specify groups, not top-level timesteps")
        selected = raw.pop("groups", None)
        if not isinstance(selected, (list, tuple)) or not selected:
            raise ValueError("groups must be a nonempty ordered sequence")
        seen, selectors, normal = set(), [], []
        for group in selected:
            if not isinstance(group, Mapping) or set(group) != {
                "group_id",
                "timesteps",
            }:
                raise ValueError("Each group requires exactly group_id and timesteps")
            name, times = group["group_id"], group["timesteps"]
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)
                or name.upper() in reserved
                or name.casefold() in seen
            ):
                raise ValueError(
                    "group_id must be a unique portable identifier within its job"
                )
            if (
                not isinstance(times, (list, tuple))
                or not times
                or any(type(i) is not int or not 0 <= i < 2**64 for i in times)
                or len(set(times)) != len(times)
            ):
                raise ValueError(
                    "Group timesteps must be unique nonnegative saved indices"
                )
            seen.add(name.casefold())
            normal.append(dict(group_id=name, timesteps=list(times)))
            selectors.extend(i for i in times if i not in selectors)
        raw["timesteps"] = selectors
        ordinary.append(raw)
        groups.append(normal)
    result = _normalise_jobs(ordinary)
    for job, selected in zip(result, groups, strict=True):
        if (
            job["interpolation"] != "sloping"
            or any(
                job["options"][k]
                for k in ("reduce_shallow_to_horizontal", "use_depth_weighted_faces")
            )
            or job["options"]["render_mode"] != "sloping"
        ):
            raise FimUnsupportedError("Grouped maxima initially require plain sloping")
        job["groups"] = selected
    return result


def validate_receipt(report, jobs, plans, depth_units, compression):
    """Refuse partial, repeated, unexpected or malformed sample/output receipts."""
    from rasterio.crs import CRS

    if (
        report.get("schema") != "ras-commander-depth-groups-report/1"
        or report.get("status") != "complete"
    ):
        raise FimEngineError("Incomplete grouped native receipt")
    actual = report.get("jobs")
    if not isinstance(actual, list) or [j.get("job_id") for j in actual] != [
        j["job_id"] for j in jobs
    ]:
        raise FimEngineError("Grouped receipt jobs differ from request order")
    for job, delivered in zip(jobs, actual, strict=True):
        groups = delivered.get("groups")
        if not isinstance(groups, list) or [g.get("group_id") for g in groups] != [
            g["group_id"] for g in job["groups"]
        ]:
            raise FimEngineError("Grouped receipt groups differ from request order")
        plan = plans[job["job_id"]]
        pixels = plan.shape[0] * plan.shape[1]
        for requested, group in zip(job["groups"], groups, strict=True):
            t = plan.transform
            extent = [t.c, t.f + plan.shape[0] * t.e, t.c + plan.shape[1] * t.a, t.f]
            try:
                crs_matches = (
                    isinstance(group.get("crs_wkt"), str)
                    and CRS.from_wkt(group["crs_wkt"]) == plan.crs
                )
            except (ValueError, TypeError):
                crs_matches = False
            frames = group.get("frames")
            if (
                group.get("status") != "complete"
                or group.get("source_indices") != requested["timesteps"]
                or not isinstance(frames, list)
                or [f.get("source_index") for f in frames] != requested["timesteps"]
                or group.get("shape") != list(plan.shape)
                or group.get("affine") != list(plan.transform.to_gdal())
                or group.get("strict_extent") != extent
                or not crs_matches
                or group.get("epsg") != plan.crs.to_epsg()
                or group.get("lattice", {}).get("source_window")
                != [int(v) for v in plan.window.flatten()]
                or group.get("units") != depth_units
                or group.get("nodata") != "NaN"
                or group.get("byte_length") != pixels * 4
                or group.get("dtype") != "<f4"
                or group.get("output", {}).get("path")
                != f"{job['job_id']}/{requested['group_id']}.tif"
                or group["output"].get("compression") != compression
            ):
                raise FimEngineError(
                    "Grouped output metadata or sample list differs from request"
                )
            count = group.get("retained_count")
            if (
                type(count) is not int
                or not 0 <= count <= pixels
                or group.get("all_dry") != (count == 0)
            ):
                raise FimEngineError("Invalid grouped retained pixel count")
            for frame in frames:
                native, retained = (
                    frame.get("native_wet_count"),
                    frame.get("retained_count"),
                )
                if (
                    type(frame.get("source_index")) is not int
                    or type(native) is not int
                    or type(retained) is not int
                    or not 0 <= native <= pixels
                    or not 0 <= retained <= pixels
                    or frame.get("status")
                    != ("complete" if native else "no_flooded_pixels")
                ):
                    raise FimEngineError(
                        "Unknown/failed grouped frame status or invalid pixel count"
                    )


def _cohort(jobs, config, control, ordinal):
    """Stage bounded selector waves without rebuilding parent mesh/terrain."""
    from .. import HdfBase, RasFim
    from . import _aoi, _horizontal, _invalid_cells, _sloping
    from pyproj import CRS
    from ._horizontal_engine import _write_geometry
    from ._native_session import NativeSlopingSession
    import numpy as np
    import rasterio
    import shapely

    _check_sources(jobs)
    controls = config["controls"]
    first = jobs[0]
    units = HdfBase.get_result_unit_metadata(first["hdf_path"], strict=True)
    depth_units = {"ft": "feet", "m": "metres"}.get(units["depth_units"])
    if depth_units is None:
        raise FimUnsupportedError(
            "Grouped output needs unambiguous feet/metres depth units"
        )
    source_indices = list(dict.fromkeys(i for job in jobs for i in job["timesteps"]))
    names = {index: f"s{i:06d}" for i, index in enumerate(source_indices)}
    waves = [
        source_indices[i : i + controls["max_profiles_per_batch"]]
        for i in range(0, len(source_indices), controls["max_profiles_per_batch"])
    ]
    root = control / f"cohort-{ordinal}"
    root.mkdir()
    prepare_tick = time.perf_counter()
    with RasFim.prepare_sloping_model(
        first["hdf_path"],
        first["terrain_path"],
        profiles={names[i]: i for i in waves[0]},
        threads=len(config["cpus"]),
        max_working_mib=controls["max_working_mib"],
        max_prepared_mib=controls["max_prepared_mib"],
        engine_path=config["engine"]["engine_path"],
        native_session=True,
        window_cache_mib=controls["window_cache_mib"],
        hydraulic_cache_mib=0,
        **first["options"],
    ) as prepared:
        prepared._check_sources()
        staged = [prepared._units[names[i]] for i in waves[0]]
        staged_bytes = prepared.info["planned_prepared_bytes"]
        source_wave = [
            dict(indices=waves[0], staged_bytes=prepared.info["staged_bytes"])
        ]
        # Stage all requested selectors to local disk, reading one admitted wave at a time.
        # The existing prepared-budget contract also bounds total retained staged bytes.
        for wave_index, wave in enumerate(waves[1:], 1):
            wave_root = root / f"selectors-{wave_index}"
            wave_root.mkdir()
            required = staged_bytes + sum(
                m["cell_count"] for m in prepared._meshes
            ) * 4 * len(wave)
            allowed = controls["max_prepared_mib"] << 20
            if required > allowed:
                raise MemoryError(
                    f"Prepared selectors required {required} bytes, allowed {allowed}"
                )
            selected, views, size = _sloping._stage_profiles(
                prepared._hdf,
                wave_root,
                prepared._meshes,
                {},
                {names[i]: i for i in wave},
                deduplicate=True,
                max_staged_bytes=(controls["max_prepared_mib"] << 20) - staged_bytes,
            )
            staged.extend(
                dict(
                    id=u["id"],
                    values_files=[str(wave_root / p) for p in u["values_files"]],
                )
                for u in selected
            )
            staged_bytes += size
            source_wave.append(
                dict(indices=wave, staged_bytes=size, profile_views_prepared=views)
            )
            prepared._check_sources()
        plans, native_jobs = {}, []
        for job in jobs:
            geometry = shapely.from_wkb(bytes.fromhex(job["aoi"]["wkb"]))
            constraint = _aoi.FimAoi(
                job["aoi"]["kind"],
                geometry,
                CRS.from_user_input(job["aoi"]["crs"]),
                job["aoi"]["source"],
            )
            aoi_geometry = _aoi.geometry_in_crs(constraint, prepared._cells.crs)
            _invalid_cells.check_scope(
                prepared._invalid_records, prepared._invalid_policy, aoi_geometry
            )
            plan = _horizontal.plan_grid(
                prepared._cells,
                prepared._terrain,
                constraint,
                controls["max_working_mib"],
                native=True,
            )
            if not all(plan.shape):
                raise FimUnsupportedError(
                    "Grouped AOI must contain a nonempty native window"
                )
            prepared._validate_grid(plan)
            # Keep only delivery metadata; per-reach selected-cell arrays are transient.
            plans[job["job_id"]] = SimpleNamespace(
                shape=plan.shape,
                transform=plan.transform,
                crs=plan.crs,
                window=plan.window,
            )
            aoi = root / f"{job['job_id']}.wkb"
            _write_geometry(aoi, [aoi_geometry])
            native_jobs.append(
                dict(
                    job_id=job["job_id"],
                    reach_id=job["job_id"],
                    window=[int(v) for v in plan.window.flatten()],
                    aoi_file=str(aoi),
                    groups=job["groups"],
                )
            )
        # Ownership remains global and separate from each reach's AOI mask.
        cells = prepared._cells
        lookup = {m["mesh_name"]: i for i, m in enumerate(prepared._meshes)}
        extra_bytes = len(cells) * 256 + len(source_indices) * 256
        if staged_bytes + extra_bytes > controls["max_prepared_mib"] << 20:
            raise MemoryError(
                f"Grouped preparation required {staged_bytes + extra_bytes} bytes, allowed {controls['max_prepared_mib'] << 20}"
            )
        addresses = [
            [lookup[row.mesh_name], int(row.cell_id)] for row in cells.itertuples()
        ]
        geometry_path = root / "cells.wkb"
        _write_geometry(geometry_path, cells.geometry.to_numpy())
        identity = prepared._terrain_identity
        model = dict(
            schema="ras-commander-sloping-request/1",
            terrain=str(prepared._terrain),
            epsg=identity["epsg"],
            crs_identity=identity["crs_identity"],
            terrain_transform=prepared._terrain_transform,
            window=native_jobs[0]["window"],
            geometry_file=str(geometry_path),
            mesh_files=prepared._mesh_files,
            owner_cells=addresses,
            profiles=staged,
            threads=len(config["cpus"]),
            max_inflight_profiles=1,
            max_working_bytes=controls["max_working_mib"] << 20,
            window_cache_bytes=controls["window_cache_mib"] << 20,
        )
        request = dict(
            schema="ras-commander-depth-groups-request/1",
            model=model,
            source_indices=source_indices,
            jobs=native_jobs,
            depth_units=depth_units,
            depth_cutoff_ft=controls["depth_cutoff_ft"],
            products=["depth_max"],
            compression=controls["compression"],
            sink="grouped-geotiff",
            max_accumulator_bytes=controls["max_accumulator_mib"] << 20,
            scratch=dict(
                path=str(control),
                node_local=True,
                max_bytes=controls["max_scratch_bytes"],
            ),
        )
        request_path = root / "request.json"
        _write_json(request_path, request)
        preparation_seconds = time.perf_counter() - prepare_tick
        native_out = root / "native"
        with_errors = NativeSlopingSession(config["engine"]["engine_path"])
        try:
            from ..fast_hdf import release_native_sessions

            _check_sources(jobs)
            release_native_sessions(prepared._hdf)
            process = with_errors.submit(request_path, native_out)
            completion = process.stdout.readline(65537)
            with_errors.errors.seek(0, 2)
            length = with_errors.errors.tell()
            with_errors.errors.seek(max(0, length - 4000))
            error_tail = with_errors.errors.read().decode("utf-8", errors="replace")
            if len(completion) > 65536 or not completion.endswith(b"\n"):
                raise FimEngineError(
                    f"Missing grouped session completion: {error_tail}"
                )
            terminal = json.loads(completion)
            if terminal != {"command_status": "complete"}:
                detail = error_tail
                if (native_out / "report.json").exists():
                    detail = json.loads(
                        (native_out / "report.json").read_text(encoding="utf-8")
                    ).get("error", detail)
                raise FimEngineError(f"Grouped native command failed: {detail}")
        finally:
            with_errors.close()
        report = json.loads((native_out / "report.json").read_text(encoding="utf-8"))
        validate_receipt(report, jobs, plans, depth_units, controls["compression"])
        threshold = float(
            np.float32(
                controls["depth_cutoff_ft"]
                * (0.3048 if depth_units == "metres" else 1.0)
            )
        )
        if report.get("effective_cutoff") != threshold:
            raise FimEngineError(
                "Native grouped cutoff differs from physical feet request"
            )
        for job, delivered in zip(jobs, report["jobs"], strict=True):
            delivered["reach_id"] = job["reach_id"]
            plan = plans[job["job_id"]]
            destination = Path(config["output"]) / job["job_id"]
            destination.mkdir()
            for group in delivered["groups"]:
                source = native_out / group["output"]["path"]
                with rasterio.open(source) as image:
                    if (
                        image.shape != plan.shape
                        or image.transform != plan.transform
                        or image.crs != plan.crs
                        or image.count != 1
                        or image.dtypes != ("float32",)
                        or image.nodata is None
                        or not math.isnan(image.nodata)
                        or image.compression
                        != (
                            rasterio.enums.Compression.lzw
                            if controls["compression"] == "LZW"
                            else None
                        )
                    ):
                        raise FimEngineError(
                            "Grouped GeoTIFF metadata differs from requested lattice"
                        )
                target = destination / source.name
                # Node-local scratch and delivery may live on different volumes.
                import shutil

                partial = target.with_suffix(".tif.partial")
                shutil.move(str(source), partial)
                partial.replace(target)
                group["output"]["path"] = str(target)
            prepared._check_sources()
        _check_sources(jobs)
        report["commander_preparation"] = dict(
            waves=source_wave,
            wave_count=len(waves),
            prepared_bytes=staged_bytes,
            prepare_seconds=preparation_seconds,
            unit_metadata=units,
            invalid_cells=prepared.info["invalid_cells"],
        )
        return report


def _worker(config_path):
    import psutil

    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    psutil.Process().cpu_affinity(config["cpus"])
    os.environ["OMP_NUM_THREADS"] = str(len(config["cpus"]))
    control = Path(config["control"])
    tempfile.tempdir = str(control)
    result = dict(status="in_progress", cohorts=[])
    _write_json(control / "result.json", result)
    try:
        grouped = OrderedDict()
        for job in config["jobs"]:
            grouped.setdefault(job["key"], []).append(job)
        for ordinal, jobs in enumerate(grouped.values()):
            result["cohorts"].append(_cohort(jobs, config, control, ordinal))
            _write_json(control / "result.json", result)
        result["status"] = "complete"
    except BaseException as exc:
        result.update(status="aborted", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        _write_json(control / "result.json", result)


def map_depth_groups(
    jobs,
    output_folder,
    *,
    strategy="reuse",
    threads=4,
    max_workers=1,
    max_memory_mib=8192,
    max_working_mib=2048,
    max_prepared_mib=1024,
    memory_headroom_mib=256,
    max_inflight_profiles=1,
    max_profiles_per_batch=64,
    depth_cutoff_ft=0.5,
    products=None,
    compression="NONE",
    sink="grouped-geotiff",
    max_accumulator_mib=64,
    window_cache_mib=64,
    scratch_folder=None,
    max_scratch_bytes=64 << 30,
    engine_path=None,
    timeout=None,
    cancel_event=None,
    raise_on_failure=True,
):
    from .RasFim import RasFim, _positive_int
    import psutil

    started = time.monotonic()
    if (
        strategy != "reuse"
        or type(max_workers) is not int
        or max_workers != 1
        or type(max_inflight_profiles) is not int
        or max_inflight_profiles != 1
    ):
        raise FimUnsupportedError(
            "Grouped catalogs initially require reuse, one worker and one in-flight profile"
        )
    if sink != "grouped-geotiff":
        raise FimUnsupportedError(
            "Commander grouped catalogs initially deliver GeoTIFF; native Rust also offers grouped-buffer"
        )
    if products is not None and products != ["depth_max"]:
        raise ValueError("Grouped catalogs support products=['depth_max']")
    if compression not in ("NONE", "LZW"):
        raise ValueError("compression must be NONE or LZW")
    if (
        isinstance(depth_cutoff_ft, bool)
        or not isinstance(depth_cutoff_ft, (int, float))
        or not math.isfinite(depth_cutoff_ft)
        or depth_cutoff_ft < 0
    ):
        raise ValueError("depth_cutoff_ft must be finite and nonnegative")
    controls = dict(
        threads=threads,
        max_memory_mib=max_memory_mib,
        max_working_mib=max_working_mib,
        max_prepared_mib=max_prepared_mib,
        memory_headroom_mib=memory_headroom_mib,
        max_profiles_per_batch=max_profiles_per_batch,
    )
    controls = {k: _positive_int(v, k) for k, v in controls.items()}
    for name, value in (
        ("max_accumulator_mib", max_accumulator_mib),
        ("window_cache_mib", window_cache_mib),
        ("max_scratch_bytes", max_scratch_bytes),
    ):
        if type(value) is not int or not 0 <= value <= (2**64 - 1):
            raise ValueError(f"{name} must be a nonnegative integer")
        controls[name] = value
    if window_cache_mib > 4096 or max_accumulator_mib > (2**64 - 1) >> 20:
        raise ValueError(
            "window_cache_mib must be <=4096 and accumulator bytes must fit uint64"
        )
    if threads > 64 or max_profiles_per_batch > 4096:
        raise ValueError("threads must be <=64 and max_profiles_per_batch <=4096")
    if timeout is not None and (
        isinstance(timeout, bool)
        or not math.isfinite(float(timeout))
        or float(timeout) <= 0
    ):
        raise ValueError("timeout must be positive and finite")
    if not isinstance(raise_on_failure, bool) or (
        cancel_event is not None and not callable(getattr(cancel_event, "is_set", None))
    ):
        raise TypeError("Invalid raise_on_failure or cancel_event")
    controls.update(depth_cutoff_ft=depth_cutoff_ft, compression=compression)
    try:
        available = psutil.Process().cpu_affinity()
    except (AttributeError, NotImplementedError) as exc:
        raise FimUnsupportedError(
            "Grouped supervision requires Windows/Linux CPU affinity"
        ) from exc
    cpus = _worker_count(
        1,
        available,
        threads,
        1,
        min(
            max_memory_mib,
            max(
                0, psutil.virtual_memory().available // (1 << 20) - memory_headroom_mib
            ),
        ),
        max_working_mib,
        max_prepared_mib,
        memory_headroom_mib,
        1,
    )[0]
    normal = _normalise(jobs)
    engine = RasFim.get_engine_info(engine_path)
    capability = engine["method"].get("depth_groups", {})
    if (
        capability.get("request_schema") != "ras-commander-depth-groups-request/1"
        or sink not in capability.get("sinks", [])
        or compression not in capability.get("compression", [])
        or capability.get("aoi_mask") != "global-terrain-lattice/1"
        or not engine["method"].get("sloping", {}).get("persistent_session")
    ):
        raise FimUnsupportedError("Engine lacks required grouped depth capabilities")
    folder = Path(output_folder).resolve()
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise ValueError("Grouped output_folder must be new or empty")
    local = Path(scratch_folder or tempfile.gettempdir()).resolve(strict=True)
    if not local.is_dir() or local.anchor.startswith("\\\\"):
        raise ValueError(
            "scratch_folder must be an existing node-local directory, not UNC"
        )
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = folder / "depth_groups_receipt.json"
    receipt = dict(
        schema="ras-commander-fim-depth-groups/1",
        status="in_progress",
        engine=engine,
        controls=controls,
        cpu_partition=cpus,
        effective_workers=1,
        peak_process_tree_rss_bytes=0,
        jobs=[
            dict(
                job_id=j["job_id"],
                reach_id=j["reach_id"],
                groups=[dict(g, status="not_run") for g in j["groups"]],
            )
            for j in normal
        ],
    )
    _write_json(receipt_path, receipt)
    with tempfile.TemporaryDirectory(prefix="ras-fim-groups-", dir=local) as temporary:
        control = Path(temporary)
        config_path = control / "config.json"
        _write_json(
            config_path,
            dict(
                jobs=normal,
                controls=controls,
                cpus=cpus,
                engine=engine,
                control=control,
                output=folder,
            ),
        )
        process = None
        try:
            with (folder / "group-worker.log").open("wb") as log:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "ras_commander.fim._depth_groups",
                        str(config_path),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            root = psutil.Process(process.pid)
            peak = 0
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("Grouped catalog cancelled")
                if timeout is not None and time.monotonic() - started > timeout:
                    raise TimeoutError("Grouped catalog timeout")
                rss = psutil.Process().memory_info().rss
                try:
                    children = root.children(recursive=True)
                except psutil.NoSuchProcess:
                    children = []
                for actor in [root] + children:
                    try:
                        rss += actor.memory_info().rss
                    except psutil.NoSuchProcess:
                        pass
                peak = max(peak, rss)
                receipt["peak_process_tree_rss_bytes"] = peak
                if rss > max_memory_mib << 20:
                    raise MemoryError(
                        f"Grouped catalog sampled process tree required {rss} bytes, allowed {max_memory_mib << 20}"
                    )
                time.sleep(0.05)
            result = json.loads((control / "result.json").read_text(encoding="utf-8"))
            receipt["cohorts"] = result["cohorts"]
            if process.returncode or result.get("status") != "complete":
                raise FimEngineError(result.get("error", "Grouped worker failed"))
            delivered_jobs = [j for r in result["cohorts"] for j in r["jobs"]]
            if len(delivered_jobs) != len(normal):
                raise FimEngineError("Repeated or incomplete grouped worker jobs")
            by_id = {j["job_id"]: j for j in delivered_jobs}
            if set(by_id) != {j["job_id"] for j in normal}:
                raise FimEngineError("Incomplete grouped worker jobs")
            receipt["jobs"] = [by_id[j["job_id"]] for j in normal]
            receipt["by_job"] = {
                j["job_id"]: {g["group_id"]: g for g in j["groups"]}
                for j in receipt["jobs"]
            }
            _check_sources(normal)
            receipt["status"] = "complete"
        except BaseException as exc:
            if process is not None and process.poll() is None:
                _terminate(process)
            receipt.update(status="aborted", error=f"{type(exc).__name__}: {exc}")
            # Read partial native receipts before the private scratch is removed.
            partial = []
            for path in control.glob("cohort-*/native/report.json"):
                try:
                    partial.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    pass
            receipt["partial_native_receipts"] = partial
            for job in normal:
                for group in job["groups"]:
                    for suffix in (".tif", ".tif.partial"):
                        (
                            folder / job["job_id"] / f"{group['group_id']}{suffix}"
                        ).unlink(missing_ok=True)
            for job in receipt["jobs"]:
                for group in job["groups"]:
                    group["status"] = "failed"
                    group.pop("output", None)
            receipt.pop("by_job", None)
            if not isinstance(exc, Exception):
                _write_json(receipt_path, receipt)
                raise
        receipt["total_seconds"] = time.monotonic() - started
        try:
            _write_json(receipt_path, receipt)
        except OSError:
            for job in normal:
                for group in job["groups"]:
                    (folder / job["job_id"] / f"{group['group_id']}.tif").unlink(
                        missing_ok=True
                    )
            raise
    if receipt["status"] != "complete" and raise_on_failure:
        raise FimMappingError(
            "Grouped depth catalog failed; inspect depth_groups_receipt.json",
            manifest=receipt,
        )
    return receipt


if __name__ == "__main__":
    # Model preparation logging must never enter the native binary protocol.
    with redirect_stdout(sys.stderr):
        _worker(sys.argv[1])
