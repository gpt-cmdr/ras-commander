"""Private catalog actor, launched as a library-owned Python subprocess."""

from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

from ._catalog import _write_json, _check_sources


def _horizontal_cells(job, selectors, budget, threads):
    import numpy as np
    from .. import HdfMesh, HdfResultsMesh
    from ..fast_hdf import backend_scope
    import shapely

    with backend_scope("rust"):
        cells = HdfMesh.get_mesh_cell_polygons(
            Path(job["hdf_path"]), strict=True, engine="native", threads=threads
        )
        planned = (
            int(cells.memory_usage(deep=True).sum())
            + int(shapely.count_coordinates(cells.geometry.to_numpy())) * 16
            + len(cells) * (256 + 4 * len(selectors))
        )
        if planned > budget * (1 << 20):
            raise MemoryError("Horizontal prepared cell table exceeds max_prepared_mib")
        cells["cell_idx"] = np.arange(len(cells), dtype=np.int64)
        views = {}
        maximum = None
        for alias, selector in selectors.items():
            values = np.empty(len(cells), dtype=np.float32)
            if selector == "Max" and maximum is None:
                maximum = HdfResultsMesh.get_mesh_max_ws(
                    Path(job["hdf_path"]),
                    include_geometry=False,
                    include_ghost_cells=True,
                )
            for mesh, indices in cells.groupby("mesh_name", sort=False).indices.items():
                ids = cells.iloc[indices].cell_id.to_numpy(dtype=np.int64)
                if selector == "Max":
                    source = (
                        maximum[maximum.mesh_name == mesh]
                        .set_index("cell_id")
                        .maximum_water_surface.loc[ids]
                        .to_numpy(dtype=np.float32)
                    )
                else:
                    if mesh not in views:
                        views[mesh] = HdfResultsMesh.get_mesh_timeseries(
                            Path(job["hdf_path"]),
                            mesh,
                            "Water Surface",
                            truncate=False,
                            return_type="view",
                            include_ghost_cells=True,
                        )
                    source = (
                        views[mesh]
                        .select(time=selector)
                        .to_numpy(dtype=np.float32)
                        .reshape(-1)[ids]
                    )
                values[indices] = source
            cells[alias] = values
        cells.sindex
    return cells


def _run_unit(unit, config, emit):
    from contextlib import nullcontext
    from .. import RasFim
    import shapely

    segments = unit["segments"]
    jobs = [s["job"] for s in segments]
    _check_sources(jobs)
    first = jobs[0]
    controls = config["controls"]
    threads = len(config["cpus"])
    selectors = {f"s{i:06d}": selector for i, selector in enumerate(unit["selectors"])}
    aliases = {selector: name for name, selector in selectors.items()}
    tick = time.perf_counter()
    if first["interpolation"] == "sloping":
        model = RasFim.prepare_sloping_model(
            first["hdf_path"],
            first["terrain_path"],
            profiles=selectors,
            threads=threads,
            max_working_mib=controls["max_working_mib"],
            max_prepared_mib=controls["max_prepared_mib"],
            engine_path=config["engine"],
            native_session=True,
            **first["options"],
        )
        context = model
    else:
        cells = _horizontal_cells(
            first, selectors, controls["max_prepared_mib"], threads
        )
        context = nullcontext()
    prepared_seconds = time.perf_counter() - tick
    with context:
        for segment in segments:
            job, start, end = segment["job"], segment["start"], segment["end"]
            _check_sources([job])
            destination = Path(config["root"]) / job["job_id"]
            batch = destination / f".batch-{start:06d}"
            names = list(dict.fromkeys(aliases[v] for v in job["timesteps"][start:end]))
            aoi = job["aoi"]
            selection = dict(aoi_crs=aoi["crs"])
            geometry = shapely.from_wkb(bytes.fromhex(aoi["wkb"]))
            selection.update(bbox=list(geometry.bounds)) if aoi[
                "kind"
            ] == "bbox" else selection.update(polygon=geometry)
            tick = time.perf_counter()
            created = []
            try:
                if first["interpolation"] == "sloping":
                    result = model.map_profiles(
                        batch,
                        profiles=names,
                        writer_threads=controls["writer_threads"],
                        max_inflight_profiles=controls["max_inflight_profiles"],
                        timeout=config["timeout"],
                        **selection,
                    )
                else:
                    result = RasFim.map_horizontal_profiles(
                        cells,
                        first["terrain_path"],
                        batch,
                        profiles=names,
                        hdf_path=first["hdf_path"],
                        threads=threads,
                        writer_threads=controls["writer_threads"],
                        max_working_mib=controls["max_working_mib"],
                        engine_path=config["engine"],
                        timeout=config["timeout"],
                        write_floodplain=False,
                        **selection,
                    )
                indexed = result.set_index("profile").to_dict(orient="index")
                records, moved = [], {}
                for ordinal in range(start, end):
                    selector = job["timesteps"][ordinal]
                    alias = aliases[selector]
                    row = dict(indexed[alias])
                    row.update(
                        job_id=job["job_id"],
                        reach_id=job["reach_id"],
                        request_ordinal=ordinal,
                        timestep=selector,
                        profile=f"p{ordinal:06d}",
                    )
                    for key, prefix in (("depth_tif", "09"), ("wse_tif", "10")):
                        if row[key]:
                            target = (
                                destination
                                / f"{prefix}_p{ordinal:06d}_{'depth' if prefix == '09' else 'wse'}.tif"
                            )
                            source = Path(row[key])
                            if str(source) in moved:
                                shutil.copyfile(moved[str(source)], target)
                            else:
                                source.replace(target)
                                moved[str(source)] = target
                            created.append(target)
                            row[key] = str(target)
                    records.append(row)
                _check_sources([job])
                evidence = dict(
                    job_id=job["job_id"],
                    start=start,
                    end=end,
                    selectors=job["timesteps"][start:end],
                    batch_seconds=time.perf_counter() - tick,
                    prepare_seconds=prepared_seconds,
                    preparation_charged_once=segment is segments[0],
                    performance=result.attrs.get("performance"),
                    prepared_context=model.info
                    if first["interpolation"] == "sloping"
                    else None,
                )
                emit(dict(kind="segment", rows=records, evidence=evidence))
            except BaseException:
                for path in created:
                    path.unlink(missing_ok=True)
                raise
            finally:
                if batch.exists():
                    shutil.rmtree(batch)


def main(config_path):
    import psutil

    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    psutil.Process().cpu_affinity(config["cpus"])
    os.environ["OMP_NUM_THREADS"] = str(len(config["cpus"]))
    control = Path(config["control"])
    # All temporary HDF/native request files belong to this actor's control
    # tree, so cancellation can remove them after owned processes have exited.
    temporary = control / f"temporary-{config['worker']}"
    temporary.mkdir()
    tempfile.tempdir = str(temporary)
    counter = 0

    def emit(event):
        nonlocal counter
        path = control / f"event-{config['worker']}-{counter:08d}.json"
        counter += 1
        event["worker"] = config["worker"]
        _write_json(path, event)
        ack = path.with_suffix(".ack")
        while not ack.exists():
            time.sleep(0.02)
        ack.unlink()

    try:
        emit(dict(kind="ready"))
        for command in sys.stdin:
            command = json.loads(command)
            if command.get("stop"):
                return
            unit = json.loads(Path(command["unit"]).read_text(encoding="utf-8"))
            with redirect_stdout(sys.stderr):
                _run_unit(unit, config, emit)
            emit(dict(kind="ready"))
    except BaseException as exc:
        emit(dict(kind="error", error=f"{type(exc).__name__}: {exc}"))
        raise


if __name__ == "__main__":
    main(sys.argv[1])
