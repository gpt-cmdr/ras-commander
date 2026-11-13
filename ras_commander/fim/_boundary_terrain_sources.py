"""Original-source staging for the unqualified native boundary route.

No flattening, pixel sampling, reprojection or terrain modifications occur here.
The global stitch TIN belongs to the terrain, rather than an individual source.
"""

import math
from pathlib import Path

from . import _boundary_inputs, _engine
from ._one_d import digest
from .errors import FimEngineError, FimUnsupportedError


def _registered_vrt_crs(hdf, model_crs, originals):
    """Bind a legacy projection-less HDF to its actual sibling VRT and TIFFs."""
    import xml.etree.ElementTree as ET
    import hashlib
    from ._source_crs import source_crs
    vrt = hdf.with_suffix(".vrt")
    if not vrt.is_file() or vrt.is_symlink() or vrt.stat().st_size > 4 * 1024 * 1024:
        raise FimUnsupportedError("Terrain HDF Projection is missing; matching bounded sibling VRT is required")
    identity = _boundary_inputs._identity(vrt)
    raw = vrt.read_bytes()
    if len(raw) > 4 * 1024 * 1024 or _boundary_inputs._identity(vrt) != identity:
        raise FimEngineError("Registered terrain VRT changed during metadata reading")
    try:
        root = ET.fromstring(raw)
        projection = root.findtext("SRS")
        if root.tag != "VRTDataset" or not projection or source_crs(projection) != model_crs:
            raise ValueError("VRT source CRS differs")
        names = []
        for node in root.findall(".//SourceFilename"):
            name = node.text or ""
            if node.get("relativeToVRT") != "1" or Path(name.replace("\\", "/")).name != name:
                raise ValueError("VRT must name the original sibling TIFFs")
            names.append(name)
        if len(names) != len(originals) or set(names) != {path.name for path in originals}:
            raise ValueError("VRT source TIFF identities differ")
        bands = root.findall("VRTRasterBand")
        if (len(bands) != 1 or bands[0].get("band") != "1" or bands[0].get("dataType") != "Float32"
                or bands[0].get("subClass") or root.findall(".//PixelFunctionType")
                or root.findall(".//LUT") or root.findall(".//MaskBand")
                or any(node.text != "1" for node in root.findall(".//SourceBand"))
                or any(float(node.text) != 0.0 for node in root.findall(".//ScaleOffset"))
                or any(float(node.text) != 1.0 for node in root.findall(".//ScaleRatio"))):
            raise ValueError("Transformed or derived VRT source evidence is unsupported")
    except (ET.ParseError, ValueError, RuntimeError) as exc:
        raise FimUnsupportedError("Terrain HDF Projection is missing and registered VRT CRS/source evidence is inconsistent") from exc
    return vrt, projection, identity, hashlib.sha256(raw).hexdigest()


def _native_sources(handle):
    """Match H5Assist name-index/native link enumeration, then native Priority."""
    import h5py
    import numpy as np

    if not isinstance(handle.get("Terrain", getlink=True), h5py.HardLink):
        raise FimUnsupportedError("Terrain must be a hard-linked group")
    group = handle["Terrain"]
    if not isinstance(group, h5py.Group):
        raise FimUnsupportedError("Terrain must be a hard-linked group")
    names = []
    group.id.links.iterate(lambda name: names.append(name),
                          idx_type=h5py.h5.INDEX_NAME, order=h5py.h5.ITER_NATIVE)
    records = []
    for raw in names:
        try:
            name = raw.decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise FimUnsupportedError("Non-ASCII native terrain group names are unqualified") from exc
        if not isinstance(group.get(name, getlink=True), h5py.HardLink):
            raise FimUnsupportedError("Soft/external terrain links are unsupported")
        source = group[name]
        if not isinstance(source, h5py.Group):
            continue
        priority = source.attrs.get("Priority", -1)
        if (isinstance(priority, (bool, np.bool_)) or not np.isscalar(priority)
                or not isinstance(priority, (int, np.integer))
                or not -(2**31) <= int(priority) < 2**31):
            raise FimUnsupportedError("Terrain source Priority must be a scalar int32")
        for key in ("Stitch TIN Points", "Stitch TIN Triangles"):
            if key in source:
                raise FimUnsupportedError("Per-source stitch TIN is unsupported; one global terrain TIN is required")
        records.append({"raw_group_name": name, "source_group": source.name.lstrip("/"),
                        "native_group_index": len(records), "raw_priority": int(priority),
                        "priority_present": "Priority" in source.attrs})
    if not records:
        raise FimUnsupportedError("Terrain has no original raster sources")
    complete = all(row["raw_priority"] != -1 for row in records)
    flags = group.id.get_create_plist().get_link_creation_order()
    # The retained 6.6 reader uses NAME/NATIVE, never high-level creation order.
    # Unique complete priorities make the final order independent of ties. Other
    # creation-indexed layouts still need a paired native enumeration gate.
    if flags and (not complete or len({r["raw_priority"] for r in records}) != len(records)):
        raise FimUnsupportedError("Creation-indexed terrain with missing/tied Priority has unqualified native source order")
    if complete:
        records.sort(key=lambda row: row["raw_priority"])
    for index, row in enumerate(records):
        row.update(effective_index=index, creation_order_flags=int(flags),
                   order_method="H5_INDEX_NAME/H5_ITER_NATIVE; stable Priority ascending" if complete
                   else "H5_INDEX_NAME/H5_ITER_NATIVE; incomplete Priority preserves enumeration")
    return records


def _source_header(tiff, model_crs, allow_untagged=False):
    import rasterio
    from pyproj import CRS
    from ._source_crs import source_crs

    with rasterio.open(tiff) as raster:
        gt = raster.transform
        crs = source_crs(raster.crs) if raster.crs else None
        if (raster.driver != "GTiff" or raster.count != 1 or raster.dtypes != ("float32",)
                or raster.block_shapes != [(256, 256)] or not raster.profile.get("tiled", False)
                or gt.b != 0 or gt.d != 0 or gt.a <= 0 or gt.e != -gt.a
                or not all(math.isfinite(x) for x in gt.to_gdal())
                or raster.scales != (1.0,) or raster.offsets != (0.0,)
                or raster.nodata is None or not math.isfinite(raster.nodata)):
            raise FimUnsupportedError("Native boundary sources require original north-up square float32 TIFFs with 256x256 tiles")
        if crs is None and allow_untagged:
            pass  # RAS Mapper source without CRS tags; the terrain HDF Projection equals the model CRS.
        elif crs != model_crs:
            raise FimUnsupportedError("Every original terrain source CRS must equal the model CRS")
        return math.ceil(raster.height / 256) * math.ceil(raster.width / 256)


def stage_native_terrain_sources(
    terrain_hdf, primary_tiff, root, *, engine_path, threads, model_crs,
    max_staged_bytes, timeout, primary_crs_pin=None, crs_any=False, primary_identity=None,
):
    """Stage all original source units in native order and one global stitch TIN.

    Metadata, CRS, file paths and the aggregate payload budget are admitted before
    numeric reads or output creation. Extra descriptors use absolute file paths.
    ``terrain_identity`` performs the normal engine/header CRS cross-check; it
    does not generate terrain or invoke HEC-RAS. This is preparation support,
    not a native vector-parity qualification.
    """
    import h5py
    import numpy as np
    from pyproj import CRS
    from pyproj.exceptions import CRSError
    from ._source_crs import source_crs

    for name, value in (("threads", threads), ("max_staged_bytes", max_staged_bytes)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    model_crs = source_crs(model_crs)
    if (not model_crs.is_projected or len(model_crs.axis_info) < 2
            or any(not math.isclose(axis.unit_conversion_factor, 1200 / 3937,
                                    rel_tol=0, abs_tol=1e-14)
                   for axis in model_crs.axis_info[:2])):
        raise FimUnsupportedError("Native boundary terrain requires projected model coordinates in US survey feet")
    hdf = Path(terrain_hdf).resolve(strict=True)
    primary = Path(primary_tiff).resolve(strict=True)
    root = Path(root).resolve()
    rows, total = [], 0
    initial = {hdf: _boundary_inputs._identity(hdf)}
    with h5py.File(hdf, "r") as handle:
        _boundary_inputs._modifications_state(handle)
        projection = _boundary_inputs._text(handle.attrs.get("Projection", ""))
        if projection:
            try:
                terrain_crs = source_crs(projection)
            except (ValueError, TypeError, CRSError) as exc:
                raise FimUnsupportedError("Terrain HDF Projection is invalid") from exc
            if terrain_crs != model_crs:
                raise FimUnsupportedError("Terrain HDF Projection must equal the model CRS")
        records = _native_sources(handle)
        seen = set()
        for index, record in enumerate(records):
            source = handle[record["source_group"]]
            filename = _boundary_inputs._text(source.attrs.get("File", ""))
            if not filename or Path(filename.replace("\\", "/")).name != filename:
                raise FimUnsupportedError("Terrain source File must identify its original sibling TIFF")
            try:
                tiff = (hdf.parent / filename).resolve(strict=True)
            except FileNotFoundError as exc:
                raise FimUnsupportedError("Original terrain source TIFF is missing") from exc
            if tiff.parent != hdf.parent:
                raise FimUnsupportedError("Original terrain source TIFF must remain an actual sibling, without external file links")
            if tiff in seen:
                raise FimUnsupportedError("Duplicate original terrain source TIFF identity")
            seen.add(tiff)
            count = _source_header(tiff, model_crs, allow_untagged=bool(crs_any and projection))
            if count > max_staged_bytes // (65536 + 513 * 4):
                raise FimUnsupportedError("Native terrain source metadata exceeds the staging budget")
            specs = _boundary_inputs._boundary_specs(handle, source, range(count), count,
                        include_stitch=index == 0, strict_links=True)
            planned = sum(math.prod(s[2]) * np.dtype(s[1]).itemsize for s in specs.values())
            total += planned
            if total > max_staged_bytes:
                raise FimUnsupportedError("All native terrain sources exceed the aggregate staging budget")
            destination = root if index == 0 else root / f"terrain-source-{index:04d}"
            for key in specs:
                for suffix in ("", ".partial"):
                    if (destination / f"boundary-{key}.bin{suffix}").exists():
                        raise FileExistsError("Native boundary staged input already exists")
            initial[tiff] = _boundary_inputs._identity(tiff)
            rows.append((record, tiff, destination, planned))
    crs_evidence = {"kind": "terrain-hdf-projection", "crs_wkt": projection}
    if not projection:
        vrt, vrt_projection, vrt_identity, vrt_sha256 = _registered_vrt_crs(hdf, model_crs, [row[1] for row in rows])
        initial[vrt] = vrt_identity
        crs_evidence = {"kind": "registered-vrt-source-identity/1", "crs_wkt": vrt_projection,
                        "source_files": [str(row[1]) for row in rows], "path": str(vrt),
                        "sha256": vrt_sha256}
    if rows[0][1] != primary:
        raise FimUnsupportedError("Primary TIFF must match the first source in native terrain order")

    def verify():
        if any(_boundary_inputs._identity(path) != identity for path, identity in initial.items()):
            raise FimEngineError("Original terrain source changed during native boundary staging")

    # Headers and aggregate numeric allocation are proven before source hashes.
    hashes = {path: digest(path) for path in initial}
    if crs_evidence.get("path") and hashes[vrt] != crs_evidence["sha256"]:
        raise FimEngineError("Registered terrain VRT content changed after CRS verification")
    verify()
    import rasterio

    if crs_any and primary_identity is not None and primary_identity.get("epsg") is None:
        # A CRS without an EPSG code: the primary's GeoKeys label every source.
        # Untagged sources are checked as such; tagged ones with other keys are
        # pinned by their own WKT hash (their CRS equals the model CRS above).
        keys = primary_identity["crs_geokeys"]
        identities = [dict(primary_identity)]
        for _, tiff, _, _ in rows[1:]:
            with rasterio.open(tiff) as src:
                tagged = bool(src.crs)
            if not tagged:
                identities.append({"crs_identity": {"kind": "untagged"}})
                continue
            info = _engine._json_stdout(_engine.run_engine([str(engine_path), "terrain-info", str(tiff)],
                                                           "terrain-info"), "ras2fim-batch terrain-info")
            if info.get("geokeys") == keys:
                identities.append({"crs_identity": {"kind": "geokeys"}})
            elif info.get("crs_wkt_fnv1a64"):
                identities.append({"crs_identity": {"kind": "caller_verified_wkt",
                                                    "fnv1a64": info["crs_wkt_fnv1a64"]}})
            else:
                raise FimUnsupportedError(f"the engine reads no CRS from terrain source {Path(tiff).name}")
    else:
        identities = [_engine.terrain_identity(Path(engine_path), tiff, model_crs,
                       primary_crs_pin if index == 0 else None, timeout=timeout, source_crs_identity=True)
                      for index, (_, tiff, _, _) in enumerate(rows)]
    verify()
    outputs, created, directories = [], [], []
    try:
        for index, (record, tiff, destination, planned) in enumerate(rows):
            if not destination.exists():
                directories.append(destination)
            metadata = _boundary_inputs.stage_boundary_terrain(hdf, tiff, destination,
                threads=threads, max_staged_bytes=planned, selected_tiles=None,
                allow_multiple_sources=True, include_stitch=index == 0,
                verified_source_crs=model_crs)
            for key in ("mask", "perimeter", "stitch_points", "stitch_triangles"):
                if metadata[key] is not None:
                    path = (destination / metadata[key]["path"]).resolve()
                    created.append(path)
                    if index:
                        metadata[key]["path"] = str(path)
            outputs.append(metadata)
        verify()
        if any(digest(path) != value for path, value in hashes.items()):
            raise FimEngineError("Original terrain source content changed during native boundary staging")
        source_identities = [dict(record, **initial[tiff], sha256=hashes[tiff])
                             for record, tiff, _, _ in rows]
        if crs_evidence.get("path"):
            crs_evidence.update(initial[vrt], sha256=hashes[vrt])
        return {"terrain_metadata": outputs[0], "crs_identity": identities[0]["crs_identity"],
                "additional_terrains": [{"terrain": str(row[1]),
                    "crs_identity": identities[index]["crs_identity"], "terrain_metadata": outputs[index]}
                    for index, row in enumerate(rows) if index],
                "source_identities": source_identities,
                "terrain_hdf_identity": dict(initial[hdf], sha256=hashes[hdf]),
                "terrain_crs_evidence": crs_evidence,
                "staged_bytes": total}
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        for directory in reversed(directories):
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        raise
