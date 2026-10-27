"""Bounded, required-native staging of original terrain contour metadata."""

from pathlib import Path
import math

from .. import get_logger, log_call
from .errors import FimEngineError, FimUnsupportedError

logger = get_logger(__name__)
_SLAB_BYTES = 8 * 1024 * 1024


def _identity(path):
    stat = path.stat()
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    return str(value)


def _modifications_state(handle):
    """Refuse unsupported effective terrain edits without following HDF links."""
    import h5py

    link = handle.get("Modifications", getlink=True)
    if link is None:
        return {"path": "/Modifications", "state": "absent", "link_type": "absent"}
    if not isinstance(link, h5py.HardLink):
        raise FimUnsupportedError("Boundary terrain /Modifications must be absent or an empty hard-linked group; soft/external links are unsupported")
    try:
        modifications = handle["Modifications"]
        is_empty_group = isinstance(modifications, h5py.Group) and len(modifications) == 0
    except (KeyError, OSError, RuntimeError) as exc:
        raise FimUnsupportedError("Boundary terrain /Modifications is malformed or unreadable") from exc
    if not is_empty_group:
        raise FimUnsupportedError("Boundary terrain /Modifications must be absent or an empty group; terrain modifications are unsupported")
    return {"path": "/Modifications", "state": "empty", "link_type": "hard"}


@log_call
def stage_boundary_terrain(
    terrain_hdf, terrain_tif, root, *, threads=4,
    max_staged_bytes=512 * 1024 * 1024, selected_tiles=None,
):
    """Stage original level-zero masks/perimeters and complete stitch TIN arrays.

    Requires one original, north-up, square-cell float32 TIFF tiled at 256 pixels.
    HDF source File/CRS and tile cardinalities bind the inputs; the HDF contains
    no independent affine transform. TIFF pixels stay lazy for the Rust reader.
    Selected global row-major tile IDs are sorted, never cropped within a tile.
    The caller must include contour halo tiles when selecting an AOI. Complete
    stitch connectivity is retained regardless of tile selection.

    Numeric payloads require the Rust HDF backend, including bitfield support
    added after published fast-HDF 0.2.3. No Python payload fallback is used.
    The byte budget limits staged files, not total process memory.
    Terrain modifications are unsupported: /Modifications must be absent or
    a genuine empty group reached through a hard link. No enabled flags are
    interpreted, and soft/external links are rejected without following them.
    """
    import h5py
    import numpy as np
    import rasterio
    from ..fast_hdf import read_dataset

    for name, value in (("threads", threads), ("max_staged_bytes", max_staged_bytes)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    hdf = Path(terrain_hdf).resolve(strict=True)
    tif = Path(terrain_tif).resolve(strict=True)
    root = Path(root).resolve()
    identities = {"terrain_hdf": _identity(hdf), "terrain_tiff": _identity(tif)}

    def unchanged():
        if _identity(hdf) != identities["terrain_hdf"] or _identity(tif) != identities["terrain_tiff"]:
            raise FimEngineError("Terrain source changed during boundary staging")

    with rasterio.open(tif) as raster:
        transform = raster.transform
        if (raster.driver != "GTiff" or raster.count != 1 or raster.dtypes != ("float32",)
                or raster.block_shapes != [(256, 256)] or not raster.profile.get("tiled", False)
                or transform.b != 0 or transform.d != 0 or transform.a <= 0
                or transform.e >= 0 or transform.a != -transform.e
                or not all(math.isfinite(v) for v in transform.to_gdal())
                or raster.scales != (1.0,) or raster.offsets != (0.0,)):
            raise FimUnsupportedError("Boundary terrain requires an original north-up square float32 TIFF with 256x256 tiles")
        if raster.crs is None or not raster.crs.is_projected:
            raise FimUnsupportedError("Boundary terrain requires a stored projected CRS")
        if raster.nodata is None or not math.isfinite(raster.nodata):
            raise FimUnsupportedError("Boundary terrain requires a finite stored nodata value")
        shape = [raster.height, raster.width]
        tile_grid = [math.ceil(raster.height / 256), math.ceil(raster.width / 256)]
        crs, nodata = raster.crs, float(raster.nodata)

    tile_count = math.prod(tile_grid)
    max_tiles = max_staged_bytes // (65536 + 513 * 4)
    if selected_tiles is None:
        if tile_count > max_tiles:
            raise FimUnsupportedError("Boundary terrain tile metadata exceeds the staging budget")
        tiles = list(range(tile_count))
    else:
        try:
            tiles = []
            for tile in selected_tiles:
                if len(tiles) >= max_tiles:
                    raise FimUnsupportedError("Selected boundary tile metadata exceeds the staging budget")
                tiles.append(tile)
        except TypeError as exc:
            raise ValueError("selected_tiles must contain integer tile IDs") from exc
        if (not tiles or any(isinstance(v, bool) or not isinstance(v, int)
                             or v < 0 or v >= tile_count for v in tiles)
                or len(set(tiles)) != len(tiles)):
            raise ValueError("selected_tiles must contain unique in-range integer tile IDs")
        tiles.sort()

    created = []
    partials = []
    try:
        with h5py.File(hdf, "r") as handle:
            modifications = _modifications_state(handle)
            if "Terrain" not in handle or not isinstance(handle["Terrain"], h5py.Group):
                raise FimUnsupportedError("Terrain HDF has no Terrain group")
            terrain = handle["Terrain"]
            sources = [obj for obj in terrain.values() if isinstance(obj, h5py.Group)]
            if len(sources) != 1:
                names = [_text(obj.attrs.get("File", obj.name)) for obj in sources]
                raise FimUnsupportedError(f"Boundary staging supports exactly one original terrain source; found {len(sources)}: {names}")
            source = sources[0]
            filename = _text(source.attrs.get("File", ""))
            if not filename or Path(filename.replace("\\", "/")).name != filename:
                raise FimUnsupportedError("Terrain source File must identify its original sibling TIFF")
            if (hdf.parent / filename).resolve(strict=True) != tif:
                raise FimUnsupportedError("TIFF does not match the original terrain source File")
            projection = _text(handle.attrs.get("Projection", ""))
            try:
                stored_crs = rasterio.crs.CRS.from_wkt(projection) if projection else None
            except rasterio.errors.CRSError as exc:
                raise FimUnsupportedError("Terrain HDF Projection is invalid") from exc
            if stored_crs != crs:
                raise FimUnsupportedError("Terrain HDF and TIFF CRS differ or HDF Projection is missing")
            specs = {}

            def add(key, path, dtype, columns, rows=None):
                if path not in handle or not isinstance(handle[path], h5py.Dataset):
                    raise FimUnsupportedError(f"Missing terrain boundary dataset: {path}")
                dataset = handle[path]
                if (dataset.ndim != 2 or dataset.shape[1] != columns
                        or (rows is not None and dataset.shape[0] != rows)
                        or dataset.dtype != np.dtype(dtype)):
                    raise FimUnsupportedError(f"Unsupported terrain boundary shape or dtype: {path}")
                selected = key in ("mask", "perimeter")
                output_shape = [len(tiles) if selected else dataset.shape[0], columns]
                specs[key] = (dataset, dtype, output_shape, selected)

            add("mask", f"{source.name}/0/Mask", "|u1", 65536, tile_count)
            add("perimeter", f"{source.name}/0/Perimeter", "<f4", 513, tile_count)
            points_path, triangles_path = "Terrain/Stitch TIN Points", "Terrain/Stitch TIN Triangles"
            if (points_path in handle) != (triangles_path in handle):
                raise FimUnsupportedError("Stitch TIN points and triangles must both be present or absent")
            if points_path in handle:
                add("stitch_points", points_path, "<f8", 4)
                add("stitch_triangles", triangles_path, "<i4", 3)
            planned = sum(math.prod(s[2]) * np.dtype(s[1]).itemsize for s in specs.values())
            if planned > max_staged_bytes:
                raise FimUnsupportedError(f"Boundary terrain metadata needs {planned} staged bytes, exceeding {max_staged_bytes}")
            root.mkdir(parents=True, exist_ok=True)
            for key in specs:
                if any((root / f"boundary-{key}.bin{suffix}").exists() for suffix in ("", ".partial")):
                    raise FileExistsError(f"Boundary staged input already exists: {key}")
            descriptors = {}
            for key, (dataset, dtype, output_shape, selected) in specs.items():
                destination = root / f"boundary-{key}.bin"
                partial = destination.with_suffix(".bin.partial")
                row_bytes = dataset.shape[1] * np.dtype(dtype).itemsize
                rows_per_slab = max(1, _SLAB_BYTES // row_bytes)
                # Complete TIN arrays need one range per slab, not one Python
                # iteration/object per vertex. Tile selections remain indexed.
                if not selected:
                    runs = ((start, min(start + rows_per_slab, dataset.shape[0]))
                            for start in range(0, dataset.shape[0], rows_per_slab))
                else:
                    runs = []
                    for row in tiles:
                        if runs and row == runs[-1][1] and row - runs[-1][0] < rows_per_slab:
                            runs[-1][1] += 1
                        else:
                            runs.append([row, row + 1])
                with partial.open("xb") as stream:
                    partials.append(partial)
                    for start, stop in runs:
                        values = np.asarray(read_dataset(dataset, (slice(start, stop), slice(None)), backend="rust", threads=threads))
                        if values.dtype != np.dtype(dtype) or values.shape != (stop - start, dataset.shape[1]):
                            raise ValueError(f"Invalid native terrain payload: {dataset.name}")
                        if key == "stitch_points" and not np.isfinite(values[:, :3]).all():
                            raise ValueError("Stitch TIN XYZ coordinates must be finite")
                        if key == "stitch_triangles" and values.size and (values.min() < 0 or values.max() >= specs["stitch_points"][2][0]):
                            raise ValueError("Stitch TIN triangle index is outside the points array")
                        np.ascontiguousarray(values, dtype=dtype).tofile(stream)
                        unchanged()
                if partial.stat().st_size != math.prod(output_shape) * np.dtype(dtype).itemsize:
                    raise ValueError("Incomplete terrain metadata staging")
                partial.replace(destination)
                created.append(destination)
                descriptors[key] = {"path": destination.name, "dtype": dtype, "shape": output_shape, "dataset": dataset.name}
            unchanged()
            return {
                "schema_version": 1, **identities, "source_group": source.name.lstrip("/"),
                "modifications": modifications,
                "shape": shape, "transform": list(transform.to_gdal()), "crs_wkt": crs.to_wkt(),
                "nodata": nodata, "tile_shape": [256, 256], "tile_grid": tile_grid,
                "tile_order": "row-major", "selected_tiles": tiles,
                "mask": descriptors["mask"], "perimeter": descriptors["perimeter"],
                "stitch_points": descriptors.get("stitch_points"),
                "stitch_triangles": descriptors.get("stitch_triangles"), "staged_bytes": planned,
                "grid_evidence": "original source File binding, TIFF grid, HDF tile cardinalities; no independent HDF affine",
            }
    except BaseException:
        for path in created + partials:
            path.unlink(missing_ok=True)
        raise
