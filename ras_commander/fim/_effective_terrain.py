"""RAS Mapper's effective terrain without HEC-RAS (``rasmapper-effective-terrain/1``).

The fast-map engine rebuilds the float32 grid that
``RasTerrain.export_rasmapper_terrain(downsample_factor=1,
rasterize_modifications=False)`` obtains from RasMapperLib for an
**unmodified** registered terrain, from the terrain's own source TIFFs, the
level-0 tile ``Mask`` of every source and the terrain's stitch TIN.

Qualified by the engine against native HEC-RAS 7.0.1 exports: Bald Eagle
Terrain50 (two sources, 197,179,058 valid pixels) has an identical valid mask
and 8 differing values, all in stitch-TIN corners where RAS Mapper's own
exports are not stable; four of five synthetic one-to-three-source terrains are
bit-identical and the fifth differs on 5 stitch-TIN corner pixels.

Terrain modifications are refused here, before the engine is called: the
engine does not rasterize them, so a modified terrain still needs the RAS
Mapper export. Source priority is the one proven by
:func:`._terrain_scope.top_priority_source` (``Priority`` attributes or the
terrain VRT order), never inferred.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

import numpy as np

from . import _engine, _terrain_scope
from .errors import FimEngineError, FimUnsupportedError

METHOD_ID = "rasmapper-effective-terrain/1"
SCHEMA = "ras-commander-effective-terrain-request/1"
RECEIPT_SCHEMA = "ras-commander-effective-terrain/1"
NODATA = -9999.0
_TILE_PIXELS = 256 * 256


def engine_supports(engine: Path) -> bool:
    """Whether ``engine`` advertises ``rasmapper-effective-terrain/1``."""
    try:
        method = _engine.engine_method(engine)
    except Exception:
        return False
    record = method.get("effective_terrain")
    return isinstance(record, dict) and record.get("method_id") == METHOD_ID


def _write_mask(dataset, path: Path) -> list:
    """Copy a ``[tiles, 65536]`` uint8 level-0 mask as raw bytes, in slabs."""
    shape = [int(v) for v in dataset.shape]
    if dataset.ndim != 2 or shape[0] == 0 or shape[1] != _TILE_PIXELS or dataset.dtype.itemsize != 1:
        raise FimUnsupportedError(f"terrain mask {dataset.name} is not a [tiles, 65536] byte array")
    with path.open("wb") as out:
        for start in range(0, shape[0], 256):
            block = dataset[start:start + 256]
            out.write(np.ascontiguousarray(block).view(np.uint8).tobytes())
    return shape


def stage(info: dict, root: Path) -> dict:
    """Write every source mask and the stitch TIN beside the request.

    Returns the request's ``sources`` and ``stitch_tin`` fields.
    """
    import h5py

    root = Path(root)
    sources = []
    stitch_tin = None
    with h5py.File(info["terrain_hdf"], "r") as hdf:
        for index, (group, file_name) in enumerate(zip(info["source_groups"], info["sources"])):
            mask = hdf.get(f"Terrain/{group}/0/Mask")
            if not isinstance(mask, h5py.Dataset):
                raise FimUnsupportedError(f"terrain source {group!r} has no level-0 Mask")
            name = f"mask{index}.u1"
            shape = _write_mask(mask, root / name)
            tif = (Path(info["terrain_hdf"]).parent / file_name).resolve()
            if not tif.is_file():
                raise FimUnsupportedError(f"terrain source {tif.name} is missing")
            sources.append({"path": str(tif), "mask": {"path": name, "dtype": "|u1", "shape": shape}})
        points = hdf.get("Terrain/Stitch TIN Points")
        triangles = hdf.get("Terrain/Stitch TIN Triangles")
        if isinstance(points, h5py.Dataset) and isinstance(triangles, h5py.Dataset):
            p = np.ascontiguousarray(points[()], dtype="<f8")
            t = np.ascontiguousarray(triangles[()], dtype="<i4")
            if p.size and t.size:
                if p.ndim != 2 or p.shape[1] != 4 or t.ndim != 2 or t.shape[1] != 3:
                    raise FimUnsupportedError("terrain stitch TIN arrays have unexpected shapes")
                (root / "tin_points.f8").write_bytes(p.tobytes())
                (root / "tin_triangles.i4").write_bytes(t.tobytes())
                stitch_tin = {
                    "points": {"path": "tin_points.f8", "dtype": "<f8", "shape": list(p.shape)},
                    "triangles": {"path": "tin_triangles.i4", "dtype": "<i4", "shape": list(t.shape)},
                }
    return {"sources": sources, "stitch_tin": stitch_tin}


def build(
    terrain_hdf,
    output_path,
    *,
    rasmap_path=None,
    engine_path=None,
    threads: int = 1,
    max_working_mib: int = 4096,
    timeout: Optional[float] = None,
    terrain_crs_fnv1a64: Optional[str] = None,
) -> dict:
    """Write the effective terrain GeoTIFF; return the receipt (also written as JSON)."""
    import rasterio

    output_path = Path(output_path)
    if output_path.suffix.lower() not in (".tif", ".tiff"):
        raise ValueError("output_path must be a .tif")
    if not 1 <= int(threads) <= 64:
        raise ValueError("threads must be 1..64")
    if int(max_working_mib) < 1:
        raise ValueError("max_working_mib must be positive")
    engine = _engine.find_engine(engine_path)
    if not engine_supports(engine):
        raise FimUnsupportedError(
            f"engine lacks {METHOD_ID}; install ras-commander-fast-map with effective-terrain support "
            "or export the terrain through RAS Mapper"
        )
    info = _terrain_scope.top_priority_source(terrain_hdf, rasmap_path)
    if info["modified"]:
        raise FimUnsupportedError(
            f"terrain {info['terrain_hdf'].name} has modifications {info['modifications']}; "
            "the native effective terrain does not rasterize them (use the RAS Mapper export)"
        )
    with rasterio.open(info["tif"]) as src:
        crs = src.crs
    started = time.perf_counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".effective-terrain-", dir=output_path.parent))
    try:
        staged = stage(info, work)
        identity = _engine.terrain_identity(engine, Path(info["tif"]), crs, terrain_crs_fnv1a64)
        request = {
            "schema": SCHEMA,
            "sources": staged["sources"],
            "stitch_tin": staged["stitch_tin"],
            "epsg": int(identity["epsg"]),
            "crs_identity": identity["crs_identity"],
            "modifications": 0,
            "threads": int(threads),
            "max_working_bytes": int(max_working_mib) << 20,
        }
        request_path = work / "request.json"
        request_path.write_text(json.dumps(request, indent=1), encoding="utf-8")
        out_dir = work / "out"
        proc = _engine.run_engine(
            [str(engine), "effective-terrain", str(request_path), str(out_dir)],
            "effective-terrain", timeout,
        )
        if proc.returncode != 0:
            refusal = _engine.read_refusal(out_dir, proc.stderr)
            if refusal is not None:
                raise refusal
            raise FimEngineError(
                f"effective-terrain failed with exit {proc.returncode}: {proc.stderr.strip()[-2000:]}"
            )
        try:
            report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FimEngineError(f"effective-terrain wrote no readable report: {exc}") from exc
        produced = out_dir / "effective_terrain.tif"
        if report.get("status") != "complete" or not produced.is_file():
            raise FimEngineError(f"effective-terrain did not complete: {report.get('status')!r}")
        os.replace(produced, output_path)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "method_id": METHOD_ID,
            "terrain_hdf": str(info["terrain_hdf"]),
            "sources_in_priority_order": info["sources"],
            "priority_basis": info["priority_basis"],
            "stitch_tin": staged["stitch_tin"] is not None,
            "rasmap_checked": info["rasmap_checked"],
            "output": str(output_path),
            "nodata": NODATA,
            "seconds": time.perf_counter() - started,
            "engine_report": report,
        }
        receipt["engine_report"]["output"] = str(output_path)
        output_path.with_suffix(output_path.suffix + ".json").write_text(
            json.dumps(receipt, indent=2, default=str), encoding="utf-8"
        )
        return receipt
    finally:
        shutil.rmtree(work, ignore_errors=True)
