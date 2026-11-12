"""RAS Mapper's effective terrain without HEC-RAS (``rasmapper-effective-terrain/1`` and ``/2``).

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

Terrain modifications (``rasmapper-effective-terrain/2``): every layer under
``/Modifications`` is staged by :mod:`._terrain_mods`, which raises
:class:`FimUnsupportedError` for any form not qualified against HEC-RAS 7.0.1
``rasterize_modifications=True`` exports, so such terrains still go to the RAS
Mapper export. An engine that advertises only ``/1`` still refuses every
modified terrain. Source priority is the one proven by
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

from . import _engine, _terrain_mods, _terrain_scope
from .errors import FimEngineError, FimUnsupportedError

METHOD_ID = "rasmapper-effective-terrain/1"
METHOD_ID_V2 = "rasmapper-effective-terrain/2"
SCHEMA = "ras-commander-effective-terrain-request/1"
SCHEMA_V2 = "ras-commander-effective-terrain-request/2"
RECEIPT_SCHEMA = "ras-commander-effective-terrain/1"
NODATA = -9999.0
_TILE_PIXELS = 256 * 256


def _record(engine: Path):
    try:
        method = _engine.engine_method(engine)
    except FileNotFoundError:
        return None
    record = method.get("effective_terrain")
    return record if isinstance(record, dict) else None


def engine_supports(engine: Path, modifications: bool = False) -> bool:
    """Whether ``engine`` builds the effective terrain.

    ``modifications=True`` asks for ``rasmapper-effective-terrain/2`` (terrain
    modifications, request schema 2); otherwise an engine advertising ``/1``
    or ``/2`` (as its method ID or a compatible ID) will do. When the record
    lists ``request_schemas``, schema 2 must be among them.
    """
    record = _record(engine)
    if record is None:
        return False
    ids = {record.get("method_id"), *(record.get("compatible_method_ids") or [])}
    if modifications:
        schemas = record.get("request_schemas")
        return (METHOD_ID_V2 in ids and isinstance(record.get("modifications"), dict)
                and (schemas is None or SCHEMA_V2 in schemas))
    return bool(ids & {METHOD_ID, METHOD_ID_V2})


def _receipt_method(report: dict, schema: str) -> str:
    """The method the engine reports, checked against the request schema.

    Schema 2 requests must report ``/2``. Schema 1 requests report ``/1``
    from older engines and ``/2`` from engines that run the ``/2`` rule for
    both schemas. A report without ``method_id`` (older engines) is read as
    the method the schema implies.
    """
    expected = METHOD_ID_V2 if schema == SCHEMA_V2 else METHOD_ID
    reported = report.get("method_id", expected)
    allowed = {METHOD_ID_V2} if schema == SCHEMA_V2 else {METHOD_ID, METHOD_ID_V2}
    if reported not in allowed:
        raise FimEngineError(
            f"effective-terrain reported method {reported!r} for a {schema} request "
            f"(expected one of {sorted(allowed)})"
        )
    return reported


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


def _source_identities(engine: Path, sources: list, crs, identity: dict) -> None:
    """Pin each lower-priority source's own WKT hash when its CRS equals the first's.

    RAS terrain sources often store the same CRS with different WKT text; the
    engine compares WKT hashes, so each source carries its caller-verified hash.
    Sources whose CRS differs (by rasterio/PROJ equality) are refused.

    With ``crs_geokeys`` (a CRS without an EPSG code): when the first source
    carries no CRS (``untagged``), every source must carry none; otherwise a
    source whose GeoKey tags differ from the first's but whose CRS is equal
    is pinned by its own WKT hash.
    """
    import rasterio
    from pyproj import CRS

    kind = identity["crs_identity"].get("kind")
    first = CRS.from_user_input(crs)
    for source in sources[1:]:
        path = Path(source["path"])
        with rasterio.open(path) as src:
            other = CRS.from_user_input(src.crs) if src.crs else None
        if kind == "untagged":
            if other is not None:
                raise FimUnsupportedError(
                    f"terrain source {path.name} carries a CRS but the first source carries none")
            source["crs_identity"] = {"kind": "untagged"}
            continue
        if other is None or other != first:
            raise FimUnsupportedError(f"terrain source {path.name} is not in the first source's CRS")
        info = _engine._json_stdout(
            _engine.run_engine([str(engine), "terrain-info", str(path)], "terrain-info"),
            "ras2fim-batch terrain-info",
        )
        fnv = info.get("crs_wkt_fnv1a64")
        if kind == "geokeys":
            if info.get("geokeys") != identity["crs_geokeys"]:
                if not fnv:
                    raise FimUnsupportedError(f"the engine reads no CRS from terrain source {path.name}")
                source["crs_identity"] = {"kind": "caller_verified_wkt", "fnv1a64": fnv}
            continue
        if kind == "caller_verified_wkt" and fnv:
            source["crs_identity"] = {"kind": "caller_verified_wkt", "fnv1a64": fnv}


def _terrain_hdf_crs(terrain_hdf):
    """The terrain CRS stored in the terrain HDF's root ``Projection`` attribute, or None."""
    import h5py
    from pyproj import CRS

    with h5py.File(terrain_hdf, "r") as hdf:
        value = hdf.attrs.get("Projection")
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return CRS.from_wkt(value.strip())
    except Exception:
        return None


def _require_epsg(crs, tif: Path, terrain_crs_fnv1a64: Optional[str], crs_any: bool = False) -> None:
    """Refuse a terrain CRS with no EPSG code before any staging, unless the
    engine advertises ``crs_any``.

    Engines without ``crs_any`` (Fast-Map 0.18 and older) carry the CRS as an
    integer ``epsg`` and write the output GeoTIFF's CRS from that code alone.
    ``crs_identity`` (including a ``caller_verified_wkt`` pin from
    ``terrain_crs_fnv1a64``) only proves that the engine reads each source in
    that CRS; it cannot label the output. A CRS that PROJ identifies only by
    another authority, such as ``ESRI:102630`` (NAD83 / Alabama West, US
    feet), therefore has no valid request for them. Engines with ``crs_any``
    take its GeoKey tags (``crs_geokeys``) and write them verbatim.
    """
    from pyproj import CRS

    parsed = CRS.from_user_input(crs) if crs else None
    if crs_any or parsed is None or parsed.to_epsg() is not None:
        return  # no CRS at all is refused by the engine identity check
    pinned = (
        f" terrain_crs_fnv1a64={terrain_crs_fnv1a64!r} does not replace it: the hash only pins "
        "the engine's WKT reading of the sources."
        if terrain_crs_fnv1a64 else ""
    )
    raise FimUnsupportedError(
        f"terrain source {Path(tif).name} has CRS {parsed.to_string()} ({parsed.name}), which "
        "has no EPSG code. The native effective terrain needs one: the engine request carries "
        "the CRS as an EPSG code and the engine writes the output GeoTIFF's CRS from it."
        f"{pinned} Use ras-commander-fast-map 0.19+ (crs_any), the RAS Mapper export "
        "(RasTerrain.export_rasmapper_terrain) for this terrain, or rebuild the terrain from "
        "sources in a CRS with an EPSG code."
    )


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
    hecras_version: Optional[str] = None,
    ras_object=None,
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
    layers = []
    version, version_basis = None, None
    if info["modified"]:
        hdf_names = {name[4:] for name in info["modifications"] if name.startswith("hdf:")}
        rasmap_only = sorted(
            name[7:] for name in info["modifications"]
            if name.startswith("rasmap:") and name[7:] not in hdf_names
        )
        if rasmap_only:
            raise FimUnsupportedError(
                f"rasmap modification layers {rasmap_only} are not stored in {info['terrain_hdf'].name}"
            )
        if not engine_supports(engine, modifications=True):
            raise FimUnsupportedError(
                f"terrain {info['terrain_hdf'].name} has modifications {info['modifications']}; "
                f"the engine lacks {METHOD_ID_V2} (use the RAS Mapper export)"
            )
        record = _record(engine) or {}
        # The engine's advertised release table, else the Fast-Map 0.18.0
        # mapping; a release without a rule is refused (RAS Mapper export).
        rules = record.get("hecras_versions")
        if hecras_version is not None:
            version, version_basis = _terrain_mods.hecras_version_for(hecras_version, rules), "argument"
        else:
            version, version_basis = _terrain_mods.project_hecras_version(
                info["terrain_hdf"], rasmap_path, ras_object, rules)
        if version != "7.0.1" and "hecras_version" not in record.get("modifications", {}):
            raise FimUnsupportedError(
                f"the engine does not advertise hecras_version; HEC-RAS {version} modification rules "
                "need a newer ras-commander-fast-map (use the RAS Mapper export)"
            )
        # Raises FimUnsupportedError for any modification form not qualified.
        layers = _terrain_mods.read_layers(
            info["terrain_hdf"],
            length_units=_terrain_mods.project_length_units(
                info["terrain_hdf"], rasmap_path, ras_object),
            hecras_version=version,
        )
    v2 = engine_supports(engine, modifications=True)
    with rasterio.open(info["tif"]) as src:
        crs = src.crs
    # Asked of the engine only for a CRS that has no EPSG code (or no CRS at all).
    any_crs = (not crs or crs.to_epsg() is None) and _engine.crs_any(_record(engine))
    declared = None
    if not crs and any_crs:
        # RAS Mapper writes terrain sources whose CRS has no EPSG code without
        # any CRS tags; the terrain HDF's Projection is the terrain's CRS.
        declared = _terrain_hdf_crs(info["terrain_hdf"])
        if declared is None:
            raise FimUnsupportedError(
                f"terrain source {Path(info['tif']).name} has no CRS and "
                f"{Path(info['terrain_hdf']).name} has no readable Projection")
    _require_epsg(crs or declared, info["tif"], terrain_crs_fnv1a64, any_crs)
    started = time.perf_counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".effective-terrain-", dir=output_path.parent))
    try:
        staged = stage(info, work)
        if declared is not None:
            # GDAL's GeoKeys for the declared CRS, verified by a GDAL round trip;
            # the engine checks that the sources carry no CRS of their own.
            keys = _engine.geokeys_for_crs(engine, declared, work / "crs", timeout=timeout)
            identity = {"path": str(info["tif"]), "epsg": None, "crs_identity": {"kind": "untagged"},
                        "crs_geokeys": keys}
            crs_record = {"kind": "geokeys", "basis": "terrain_hdf_projection",
                          "source_identity": "untagged", "crs": declared.to_wkt()}
        else:
            identity = _engine.terrain_identity(engine, Path(info["tif"]), crs, terrain_crs_fnv1a64,
                                                **({"crs_any": True} if any_crs else {}))
            crs_record = ({"kind": "epsg", "code": int(identity["epsg"])} if identity["epsg"] is not None
                          else {"kind": "geokeys", "basis": "source_tiff_geokeys",
                                "source_identity": "geokeys"})
        if v2 or declared is not None:
            _source_identities(engine, staged["sources"], crs or declared, identity)
        request = {
            "schema": SCHEMA_V2 if v2 else SCHEMA,
            "sources": staged["sources"],
            "stitch_tin": staged["stitch_tin"],
            **_engine.request_crs(identity),
            "crs_identity": identity["crs_identity"],
            "modifications": len(layers),
            "threads": int(threads),
            "max_working_bytes": int(max_working_mib) << 20,
        }
        if v2:
            request["modification_layers"] = layers
            if layers and version != "7.0.1":
                request["hecras_version"] = version
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
        method_id = _receipt_method(report, request["schema"])
        os.replace(produced, output_path)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "method_id": method_id,
            "modification_layers": [
                {"name": layer["name"], "kind": layer["kind"], "priority": layer["priority"],
                 "features": len(layer["features"])}
                for layer in layers
            ],
            "hecras_version": version,
            "hecras_version_basis": version_basis,
            "terrain_hdf": str(info["terrain_hdf"]),
            "sources_in_priority_order": info["sources"],
            "priority_basis": info["priority_basis"],
            "stitch_tin": staged["stitch_tin"] is not None,
            "rasmap_checked": info["rasmap_checked"],
            "rasmap_warnings": info["rasmap_warnings"],
            "output": str(output_path),
            "crs": crs_record,
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
