"""Bounded source-group scheduling for native 2D FIM catalogs."""

from collections import deque
from collections.abc import Mapping
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .errors import FimMappingError, FimUnsupportedError

_MIB = 1 << 20
_JOB_FIELDS = {
    "job_id",
    "reach_id",
    "hdf_path",
    "terrain_path",
    "timesteps",
    "polygon",
    "polygon_layer",
    "bbox",
    "aoi_crs",
    "interpolation",
    "render_mode",
    "reduce_shallow_to_horizontal",
    "use_depth_weighted_faces",
    "postprocessing_hdf",
    "corner_elevation_source",
    "invalid_cells",
}


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(path, value):
    partial = path.with_suffix(".partial")
    partial.write_text(
        json.dumps(_jsonable(value), indent=2, allow_nan=False), encoding="utf-8"
    )
    partial.replace(path)


def _normalise_jobs(jobs):
    from .RasFim import RasFim, _file_identity
    from . import _sloping, _invalid_cells
    import rasterio

    if isinstance(jobs, (str, bytes, Mapping)):
        raise TypeError("jobs must be a sequence of job mappings")
    result, seen, scopes, terrain_crs = [], set(), {}, {}
    for index, raw in enumerate(jobs):
        if not isinstance(raw, Mapping):
            raise TypeError("Each catalog job must be a mapping")
        unknown = set(raw) - _JOB_FIELDS
        if unknown:
            raise ValueError(f"Unknown catalog job fields: {sorted(unknown)}")
        job_id = raw.get("job_id")
        if not isinstance(job_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", job_id
        ):
            raise ValueError("job_id must match [A-Za-z0-9_-]{1,64}")
        if job_id.casefold() in seen or job_id.upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise ValueError(
                "job_id must be unique ignoring case and cannot be a reserved file name"
            )
        seen.add(job_id.casefold())
        reach_id = raw.get("reach_id", job_id)
        if not isinstance(reach_id, str):
            raise TypeError("reach_id must be a string")
        selectors = raw.get("timesteps")
        if isinstance(selectors, (str, bytes, Mapping)) or selectors is None:
            raise TypeError(
                "timesteps must be an ordered sequence of saved indices or 'Max'"
            )
        selected = _sloping._validate_selection(
            {f"p{i:06d}": v for i, v in enumerate(selectors)}
        )
        hdf = Path(raw["hdf_path"]).resolve(strict=True)
        terrain = Path(raw["terrain_path"]).resolve(strict=True)
        interpolation = raw.get("interpolation", "sloping")
        if interpolation not in ("horizontal", "sloping"):
            raise ValueError("interpolation must be horizontal or sloping")
        options = _sloping._validate_options(
            raw.get("render_mode", "sloping"),
            raw.get("reduce_shallow_to_horizontal", False),
            raw.get("use_depth_weighted_faces", False),
        )
        if interpolation == "horizontal" and any(
            k in raw
            for k in (
                "render_mode",
                "reduce_shallow_to_horizontal",
                "use_depth_weighted_faces",
                "postprocessing_hdf",
                "corner_elevation_source",
                "invalid_cells",
            )
        ):
            raise ValueError("Horizontal catalog jobs do not accept sloping options")
        options.update(
            invalid_cells=_invalid_cells.validate_policy(
                raw.get("invalid_cells", _invalid_cells.DEFAULT_POLICY)
            ),
            corner_elevation_source=raw.get("corner_elevation_source", "auto"),
        )
        if options["corner_elevation_source"] not in (
            "auto",
            "geometry",
            "mapping_cache",
        ):
            raise ValueError("Invalid corner_elevation_source")
        options["postprocessing_hdf"] = (
            str(Path(raw["postprocessing_hdf"]).resolve(strict=True))
            if raw.get("postprocessing_hdf") is not None
            else None
        )
        if hdf not in scopes:
            scopes[hdf] = RasFim.validate_2d_model(hdf)
        scope = scopes[hdf]
        if terrain not in terrain_crs:
            with rasterio.open(terrain) as ds:
                terrain_crs[terrain] = ds.crs
        crs = terrain_crs[terrain]
        aoi = RasFim.resolve_aoi(
            bbox=raw.get("bbox"),
            polygon=raw.get("polygon"),
            polygon_layer=raw.get("polygon_layer"),
            aoi_crs=raw.get("aoi_crs"),
            default_crs=crs,
        )
        if aoi is None:
            raise ValueError("Every catalog job requires a bbox or polygon")
        sources = {"hdf": hdf, "terrain": terrain}
        if scope.get("geometry_path"):
            sources["geometry"] = Path(scope["geometry_path"])
        if options["postprocessing_hdf"]:
            sources["postprocessing_hdf"] = Path(options["postprocessing_hdf"])
        if isinstance(raw.get("polygon"), (str, Path)):
            sources["polygon"] = Path(raw["polygon"]).resolve(strict=True)
        identity = {
            key: dict(path=str(path), identity=_file_identity(path))
            for key, path in sources.items()
        }
        key = json.dumps(
            [str(hdf), str(terrain), interpolation, options], sort_keys=True
        )
        result.append(
            dict(
                index=index,
                job_id=job_id,
                reach_id=reach_id,
                hdf_path=str(hdf),
                terrain_path=str(terrain),
                timesteps=list(selected.values()),
                interpolation=interpolation,
                options=options,
                key=key,
                sources=identity,
                aoi=dict(
                    kind=aoi.kind,
                    wkb=aoi.geometry.wkb_hex,
                    crs=aoi.crs.to_wkt(),
                    source=aoi.source,
                ),
            )
        )
    if not result:
        raise ValueError("jobs cannot be empty")
    return result


def _plan_units(jobs, batch_size, strategy="reuse"):
    """Bound staged selector unions; keep equal source/options/windows together."""
    groups = {}
    for job in jobs:
        groups.setdefault(
            job["key"] if strategy == "reuse" else job["index"], []
        ).append(job)
    units = []
    for group in groups.values():
        # Stable ordering retains repeated windows in the single native cache.
        ordered = sorted(
            group, key=lambda j: (j["aoi"]["wkb"], j["aoi"]["crs"], j["index"])
        )
        segments = []
        selectors = []
        for job in ordered:
            for start in range(0, len(job["timesteps"]), batch_size):
                end = min(len(job["timesteps"]), start + batch_size)
                values = list(dict.fromkeys(job["timesteps"][start:end]))
                if segments and len(set(selectors + values)) > batch_size:
                    units.append(dict(segments=segments, selectors=selectors))
                    segments, selectors = [], []
                selectors = list(dict.fromkeys(selectors + values))
                segments.append(dict(job=job, start=start, end=end))
        if segments:
            units.append(dict(segments=segments, selectors=selectors))
    return units


def _worker_count(
    unit_count,
    available_cpus,
    threads,
    max_workers,
    memory,
    working,
    prepared,
    headroom,
    writers,
):
    count = min(
        unit_count,
        max_workers,
        min(threads, len(available_cpus)) // writers,
        memory // (working + prepared + headroom),
    )
    if count < 1:
        raise FimUnsupportedError(
            "Catalog CPU/memory admission cannot fit one worker; increase budgets or reduce per-worker limits"
        )
    cpus = available_cpus[:threads]
    partitions = [
        cpus[i * len(cpus) // count : (i + 1) * len(cpus) // count]
        for i in range(count)
    ]
    return partitions


def _terminate(process):
    """Stop owned spawning before enumerating/killing its native descendants."""
    import psutil

    try:
        root = psutil.Process(process.pid)
        root.suspend()
        children = root.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        root.kill()
        psutil.wait_procs(children + [root], timeout=10)
    except psutil.NoSuchProcess:
        pass
    process.wait(timeout=10)


def _check_sources(jobs):
    from .RasFim import _file_identity

    for job in jobs:
        for source in job["sources"].values():
            if list(_file_identity(Path(source["path"]))) != list(source["identity"]):
                raise RuntimeError(f"Catalog source changed for job {job['job_id']!r}")


def map_catalog(
    jobs,
    output_folder,
    *,
    threads=4,
    max_workers=1,
    strategy="reuse",
    max_memory_mib=8192,
    max_working_mib=2048,
    max_prepared_mib=1024,
    memory_headroom_mib=256,
    max_profiles_per_batch=64,
    writer_threads=1,
    max_inflight_profiles=1,
    engine_path=None,
    timeout=None,
    cancel_event=None,
    raise_on_failure=True,
):
    import pandas as pd
    import psutil
    from .RasFim import RasFim, _positive_int
    from ..schemas import DATAFRAME_SCHEMAS

    started = time.perf_counter()
    controls = dict(
        threads=threads,
        max_workers=max_workers,
        max_memory_mib=max_memory_mib,
        max_working_mib=max_working_mib,
        max_prepared_mib=max_prepared_mib,
        memory_headroom_mib=memory_headroom_mib,
        max_profiles_per_batch=max_profiles_per_batch,
        writer_threads=writer_threads,
        max_inflight_profiles=max_inflight_profiles,
    )
    controls = {k: _positive_int(v, k) for k, v in controls.items()}
    if strategy not in ("reuse", "parallel"):
        raise ValueError("strategy must be reuse or parallel")
    controls["strategy"] = strategy
    if controls["threads"] > 64 or controls["max_profiles_per_batch"] > 4096:
        raise ValueError("threads must be <=64 and max_profiles_per_batch <=4096")
    if timeout is not None and (
        isinstance(timeout, bool)
        or not math.isfinite(float(timeout))
        or float(timeout) <= 0
    ):
        raise ValueError("timeout must be positive and finite")
    if not isinstance(raise_on_failure, bool):
        raise TypeError("raise_on_failure must be boolean")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise TypeError("cancel_event must provide is_set()")
    try:
        available = psutil.Process().cpu_affinity()
    except (AttributeError, NotImplementedError) as exc:
        raise FimUnsupportedError(
            "Catalog scheduling requires process CPU affinity (Windows/Linux)"
        ) from exc
    normal = _normalise_jobs(jobs)
    units = _plan_units(normal, controls["max_profiles_per_batch"], strategy)
    cpus = _worker_count(
        len(units),
        available,
        threads=controls["threads"],
        max_workers=controls["max_workers"],
        memory=min(
            controls["max_memory_mib"],
            max(
                0,
                psutil.virtual_memory().available // _MIB
                - controls["memory_headroom_mib"],
            ),
        ),
        working=controls["max_working_mib"],
        prepared=controls["max_prepared_mib"],
        headroom=controls["memory_headroom_mib"],
        writers=controls["writer_threads"],
    )
    engine = RasFim.get_engine_info(engine_path)
    if not engine["method"].get("sloping", {}).get("persistent_session") and any(
        j["interpolation"] == "sloping" for j in normal
    ):
        raise FimUnsupportedError(
            "Sloping catalogs require persistent_session capability"
        )
    for job in normal:
        method = engine["method"].get(job["interpolation"], {})
        if (
            job["aoi"]["kind"] == "polygon"
            and method.get("aoi_mask") != "global-terrain-lattice/1"
        ):
            raise FimUnsupportedError(
                "Polygon catalogs require global-terrain-lattice/1"
            )
    folder = Path(output_folder).resolve()
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise ValueError("Catalog output_folder must be new or empty")
    folder.mkdir(parents=True, exist_ok=True)
    control = folder / ".catalog-control"
    control.mkdir()
    for job in normal:
        (folder / job["job_id"]).mkdir()
    columns = [x["name"] for x in DATAFRAME_SCHEMAS["fim_catalog_manifest"]["columns"]]
    rows = {}
    job_rows = {j["index"]: [] for j in normal}
    job_by_id = {j["job_id"]: j for j in normal}
    request_files = {j["index"]: [] for j in normal}
    for job in normal:
        for ordinal, selector in enumerate(job["timesteps"]):
            row = dict.fromkeys(columns)
            row.update(
                job_id=job["job_id"],
                reach_id=job["reach_id"],
                request_ordinal=ordinal,
                timestep=selector,
                profile=f"p{ordinal:06d}",
                status="not_run",
            )
            rows[job["index"], ordinal] = row
            job_rows[job["index"]].append(row)
    receipt = dict(
        schema="ras-commander-fim-catalog/1",
        status="in_progress",
        controls=controls,
        cpu_partitions=cpus,
        effective_workers=len(cpus),
        planned_worker_reservation_mib=controls["max_working_mib"]
        + controls["max_prepared_mib"]
        + controls["memory_headroom_mib"],
        max_staged_selectors=controls["max_profiles_per_batch"],
        engine=engine,
        jobs=[
            dict(
                job_id=j["job_id"],
                manifest=str(folder / j["job_id"] / "fim_manifest.json"),
            )
            for j in normal
        ],
        requests=[],
        performance=dict(
            peak_tree_rss_bytes=0,
            peak_tree_private_bytes=0,
            sample_interval_seconds=0.1,
            samples=0,
        ),
        error=None,
    )
    workers, pending, completed_units = [], deque(enumerate(units)), 0
    failure = None
    last_checkpoint = 0.0

    def persist(changed=None):
        nonlocal last_checkpoint
        receipt["performance"]["total_seconds"] = time.perf_counter() - started
        # Commit the affected job before acknowledging the worker. Avoid
        # rewriting every job and every native report for each segment.
        for job in normal if changed is None else [job_by_id[name] for name in changed]:
            _write_json(
                folder / job["job_id"] / "fim_manifest.json",
                dict(
                    schema="ras-commander-fim-catalog-job/1",
                    job_id=job["job_id"],
                    job=job,
                    requests=request_files[job["index"]],
                    profiles=job_rows[job["index"]],
                ),
            )
        if changed is None or time.monotonic() - last_checkpoint >= 1:
            final = receipt["status"] != "in_progress"
            receipt["profiles"] = list(rows.values()) if final else []
            receipt["live_profiles"] = (
                "Per-job fim_manifest.json; final rows are inlined at completion"
            )
            _write_json(folder / "catalog_manifest.json", receipt)
            last_checkpoint = time.monotonic()

    try:
        persist()
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Catalog cancelled")
        for index, partition in enumerate(cpus):
            config = dict(
                root=str(folder),
                control=str(control),
                worker=index,
                cpus=partition,
                controls=controls,
                engine=engine["engine_path"],
                timeout=timeout,
            )
            config_path = control / f"worker-{index}.json"
            _write_json(config_path, config)
            log = (folder / f"worker-{index}.log").open("wb")
            try:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "ras_commander.fim._catalog_worker",
                        str(config_path),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            finally:
                log.close()
            workers.append(dict(process=process, busy=True, unit=None, stopped=False))
        previous_sample = time.monotonic()
        while completed_units < len(units):
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Catalog cancelled")
            for event_path in sorted(control.glob("event-*.json")):
                event = json.loads(event_path.read_text(encoding="utf-8"))
                slot = workers[event["worker"]]
                if event["kind"] == "segment":
                    for row in event["rows"]:
                        index = job_by_id[row["job_id"]]["index"]
                        rows[index, row["request_ordinal"]].update(row)
                    evidence = event["evidence"]
                    request_path = (
                        folder
                        / evidence["job_id"]
                        / f"request-{evidence['start']:06d}.json"
                    )
                    _write_json(request_path, evidence)
                    request_files[job_by_id[evidence["job_id"]]["index"]].append(
                        str(request_path)
                    )
                    receipt["requests"].append(str(request_path))
                    persist({row["job_id"] for row in event["rows"]})
                elif event["kind"] == "ready":
                    if slot["unit"] is not None:
                        completed_units += 1
                    slot["busy"] = False
                    slot["unit"] = None
                elif event["kind"] == "error":
                    raise RuntimeError(event["error"])
                else:
                    raise RuntimeError("Invalid catalog worker event")
                event_path.unlink()
                event_path.with_suffix(".ack").touch()
            for slot in workers:
                process = slot["process"]
                if process.poll() is not None and not slot["stopped"]:
                    raise RuntimeError(
                        f"Catalog worker exited unexpectedly ({process.returncode}); see worker logs"
                    )
                if not slot["busy"] and pending:
                    index, unit = pending.popleft()
                    path = control / f"unit-{index}.json"
                    _write_json(path, unit)
                    process.stdin.write(
                        (json.dumps(dict(unit=str(path))) + "\n").encode()
                    )
                    process.stdin.flush()
                    slot.update(busy=True, unit=index)
            if time.monotonic() - previous_sample >= 0.1:
                now = time.monotonic()
                perf = receipt["performance"]
                perf["max_sample_gap_seconds"] = max(
                    perf.get("max_sample_gap_seconds", 0), now - previous_sample
                )
                previous_sample = now
                rss = private = 0
                for slot in workers:
                    try:
                        proc = psutil.Process(slot["process"].pid)
                        tree = [proc] + proc.children(recursive=True)
                    except psutil.NoSuchProcess:
                        continue
                    for proc in tree:
                        try:
                            mem = proc.memory_info()
                            rss += mem.rss
                            private += getattr(mem, "private", mem.rss)
                        except psutil.NoSuchProcess:
                            pass
                perf["samples"] += 1
                perf["peak_tree_rss_bytes"] = max(perf["peak_tree_rss_bytes"], rss)
                perf["peak_tree_private_bytes"] = max(
                    perf["peak_tree_private_bytes"], private
                )
                if max(rss, private) > controls["max_memory_mib"] * _MIB:
                    raise MemoryError(
                        "Observed catalog worker memory exceeds max_memory_mib"
                    )
                if (
                    psutil.virtual_memory().available
                    < controls["memory_headroom_mib"] * _MIB
                ):
                    raise MemoryError(
                        "Available host memory fell below memory_headroom_mib"
                    )
            time.sleep(0.02)
        _check_sources(normal)
        receipt["status"] = "complete"
    except BaseException as exc:
        failure = exc
        receipt.update(
            status="cancelled"
            if isinstance(exc, (KeyboardInterrupt, InterruptedError))
            else "aborted",
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        for slot in workers:
            process = slot["process"]
            if failure is not None:
                _terminate(process)
            else:
                try:
                    process.stdin.write(b'{"stop":true}\n')
                    process.stdin.flush()
                    process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    _terminate(process)
            try:
                process.stdin.close()
            except OSError:
                pass
        # Killed workers cannot safely clean their current Python staging; it
        # lives under the owned control tree, never in a source project.
        for job in normal:
            for path in (folder / job["job_id"]).glob(".batch-*"):
                shutil.rmtree(path)
        if failure is not None:
            for row in rows.values():
                if row["status"] == "not_run":
                    row.update(
                        status="cancelled"
                        if receipt["status"] == "cancelled"
                        else "failed",
                        error=receipt["error"],
                    )
            # Keep only acknowledged products. A cancellation may occur after
            # a worker renamed a TIFF but before its segment was committed.
            keep = {
                str(Path(row[key]))
                for row in rows.values()
                for key in ("depth_tif", "wse_tif")
                if row[key]
            }
            for job in normal:
                for path in (folder / job["job_id"]).glob("*.tif"):
                    if str(path) not in keep:
                        path.unlink()
        persist()
        shutil.rmtree(control)
    result = pd.DataFrame(list(rows.values()), columns=columns)
    result.attrs.update(
        performance=receipt["performance"],
        catalog_manifest=str(folder / "catalog_manifest.json"),
        catalog_status=receipt["status"],
    )
    if failure is not None and raise_on_failure:
        raise FimMappingError(
            f"Catalog {receipt['status']}: {failure}", manifest=result
        ) from failure
    return result
