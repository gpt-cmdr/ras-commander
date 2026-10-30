"""Top-priority terrain source resolution for mapping without a terrain export.

RAS Mapper writes stored maps per terrain source, on that source's own grid.
Inside the footprint of the highest-priority source (bit 0 of its level-0
terrain-HDF tile ``Mask``), the effective terrain is that source's original
TIFF. The fast-map engine maps directly on that TIFF when the request carries
``terrain_scope`` (method ``top-priority-source-footprint/1``) and refuses any
pixel whose result would depend on a lower-priority source.

Source priority is read, never inferred from names:

- every source group carries an integer ``Priority`` attribute (HEC-RAS 6+
  terrains), 0 being the highest priority; or
- no source group carries one (older terrains), and the terrain's own VRT,
  written beside the HDF, lists the sources in priority order, highest first.

When both are present they must agree. Mixed, duplicate, missing or
inconsistent declarations are refused.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import numpy as np

from .errors import FimUnsupportedError

METHOD_ID = "top-priority-source-footprint/1"
TILE_PIXELS = 256 * 256
_MASK_FILE = "terrain_scope_mask.u1"


def _leaf(value, what: str) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    value = str(value)
    if not value or "/" in value or "\\" in value or ":" in value:
        raise FimUnsupportedError(f"terrain {what} {value!r} is not a leaf file name beside the terrain HDF")
    return value


def _vrt_order(vrt: Path) -> list:
    try:
        root = ET.parse(vrt).getroot()
    except (OSError, ET.ParseError) as exc:
        raise FimUnsupportedError(f"cannot read terrain VRT {vrt.name}: {exc}") from exc
    references = root.findall(".//SourceFilename")
    if not references or any(ref.get("relativeToVRT") != "1" for ref in references):
        raise FimUnsupportedError("terrain VRT sources must be relative leaf file names")
    return [_leaf(ref.text or "", "VRT source") for ref in references]


def _modifications(source, rasmap_path, terrain_hdf: Path) -> list:
    """Names of terrain modifications in the HDF and, when given, the rasmap."""
    import h5py

    found = []
    group = source.get("Modifications")
    if isinstance(group, h5py.Group):
        found.extend(f"hdf:{name}" for name in group.keys())
    if rasmap_path is not None:
        rasmap = Path(rasmap_path).resolve(strict=True)
        try:
            root = ET.parse(rasmap).getroot()
        except ET.ParseError as exc:
            raise FimUnsupportedError(f"cannot read rasmap {rasmap.name}: {exc}") from exc
        layers = [
            layer for layer in root.iter("Layer")
            if layer.get("Type") == "TerrainLayer" and layer.get("Filename")
            and (rasmap.parent / layer.get("Filename").replace("\\", "/")).resolve() == terrain_hdf
        ]
        if not layers:
            raise FimUnsupportedError(f"{rasmap.name} does not register terrain {terrain_hdf.name}")
        for layer in layers:
            for group_layer in layer.findall("Layer"):
                if group_layer.get("Type") == "ElevationModificationGroup":
                    found.extend(
                        f"rasmap:{child.get('Name')}" for child in group_layer.findall("Layer")
                    )
    return found


def top_priority_source(terrain_hdf, rasmap_path=None) -> dict:
    """Identify the priority-1 source TIFF and level-0 mask of a terrain HDF."""
    import h5py

    terrain_hdf = Path(terrain_hdf).resolve(strict=True)
    with h5py.File(terrain_hdf, "r") as source:
        terrain = source.get("Terrain")
        if not isinstance(terrain, h5py.Group):
            raise FimUnsupportedError(f"{terrain_hdf.name} has no Terrain group")
        records = {
            name: group for name, group in terrain.items()
            if isinstance(group, h5py.Group) and "File" in group.attrs
        }
        if not records:
            raise FimUnsupportedError(f"{terrain_hdf.name} registers no terrain source rasters")
        files = {name: _leaf(group.attrs["File"], "source file") for name, group in records.items()}
        if len(set(files.values())) != len(files):
            raise FimUnsupportedError("terrain sources share a raster file")
        priorities = {name: group.attrs.get("Priority") for name, group in records.items()}
        declared = [value for value in priorities.values() if value is not None]
        vrt = terrain_hdf.with_suffix(".vrt")
        vrt_order = _vrt_order(vrt) if vrt.is_file() else None
        if vrt_order is not None and sorted(vrt_order) != sorted(files.values()):
            raise FimUnsupportedError("terrain VRT sources differ from the terrain HDF sources")
        if len(declared) == len(records):
            values = []
            for value in declared:
                array = np.asarray(value)
                if array.shape != () or not np.issubdtype(array.dtype, np.integer):
                    raise FimUnsupportedError("terrain source Priority attributes must be integer scalars")
                values.append(int(array))
            if sorted(values) != list(range(len(records))):
                raise FimUnsupportedError(
                    f"terrain source priorities {sorted(values)} are not 0..{len(records) - 1}"
                )
            ordered = sorted(records, key=lambda name: int(np.asarray(priorities[name])))
            basis = "hdf_priority"
            if vrt_order is not None:
                if [files[name] for name in ordered] != vrt_order:
                    raise FimUnsupportedError("terrain HDF priorities and VRT source order disagree")
                basis = "hdf_priority+vrt_order"
        elif not declared:
            if len(records) == 1:
                ordered, basis = list(records), "single_source"
            elif vrt_order is None:
                raise FimUnsupportedError(
                    "terrain sources carry no Priority and no terrain VRT records their order"
                )
            else:
                by_file = {file: name for name, file in files.items()}
                ordered, basis = [by_file[file] for file in vrt_order], "vrt_order"
        else:
            raise FimUnsupportedError("only some terrain sources carry a Priority attribute")
        top = ordered[0]
        mask = records[top].get("0/Mask")
        if (
            not isinstance(mask, h5py.Dataset)
            or mask.dtype != np.uint8
            or mask.ndim != 2
            or mask.shape[0] == 0
            or mask.shape[1] != TILE_PIXELS
        ):
            raise FimUnsupportedError(
                f"terrain source {top!r} has no uint8 [tiles, 65536] level-0 Mask"
            )
        mask_shape = [int(v) for v in mask.shape]
        modifications = _modifications(source, rasmap_path, terrain_hdf)
    tif = (terrain_hdf.parent / files[top]).resolve()
    if not tif.is_file():
        raise FimUnsupportedError(f"priority-1 terrain source {tif.name} is missing")
    return {
        "tif": tif,
        "source_count": len(records),
        "terrain_hdf": terrain_hdf,
        "modified": bool(modifications),
        "source": top,
        "sources": [files[name] for name in ordered],
        "source_groups": list(ordered),
        "priority_basis": basis,
        "mask_dataset": f"Terrain/{top}/0/Mask",
        "mask_shape": mask_shape,
        "modifications": modifications,
        "rasmap_checked": rasmap_path is not None,
    }


def resolve(terrain_hdf, terrain_path, rasmap_path=None) -> dict:
    """Check that ``terrain_path`` is the unmodified priority-1 source TIFF."""
    info = top_priority_source(terrain_hdf, rasmap_path)
    if info["modified"]:
        raise FimUnsupportedError(
            f"terrain {info['terrain_hdf'].name} has modifications {info['modifications']}; "
            "mapping on a source TIFF is qualified only for unmodified terrains"
        )
    terrain = Path(terrain_path).resolve(strict=True)
    info["canonical_copy"] = None
    if terrain != info["tif"]:
        info["canonical_copy"] = _canonical_copy(terrain, info["tif"])
        if info["canonical_copy"] is None:
            raise FimUnsupportedError(
                f"terrain_path must be the priority-1 source TIFF {info['tif']} of "
                f"{info['terrain_hdf'].name}, or its RasFim.canonicalize_terrain_crs copy"
            )
    import rasterio

    with rasterio.open(terrain) as src:
        tiles = -(-src.width // 256) * -(-src.height // 256)
        if src.block_shapes != [(256, 256)] or tiles != info["mask_shape"][0]:
            raise FimUnsupportedError(
                "terrain_scope needs the original 256 x 256 tiled source TIFF matching its level-0 mask"
            )
    return info


def _pixel_sha256(path: Path) -> str:
    import hashlib

    import rasterio
    from rasterio.windows import Window

    digest = hashlib.sha256()
    with rasterio.open(path) as src:
        for row in range(0, src.height, 128):
            window = Window(0, row, src.width, min(128, src.height - row))
            digest.update(src.read(1, window=window).tobytes())
    return digest.hexdigest()


def _canonical_copy(terrain: Path, source: Path) -> Optional[dict]:
    """Accept a lossless CRS-canonical copy of the source, proven by its receipt.

    ``RasFim.canonicalize_terrain_crs`` re-encodes only the CRS and keeps the
    grid, tiling and every pixel bit. The receipt must name the priority-1
    source, and the source's current pixels must still hash to the receipt.
    """
    import json

    import rasterio

    receipt_path = terrain.with_suffix(terrain.suffix + ".json")
    if not receipt_path.is_file():
        return None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != "ras-commander-fim-canonical-terrain/1"
        or receipt.get("pixel_bits_and_grid_preserved") is not True
        or receipt.get("reprojected") is not False
        or Path(str(receipt.get("source", ""))).resolve() != source
        or Path(str(receipt.get("output", ""))).resolve() != terrain
    ):
        return None
    with rasterio.open(source) as a, rasterio.open(terrain) as b:
        if (
            a.shape != b.shape
            or a.transform != b.transform
            or a.block_shapes != b.block_shapes
            or a.nodata != b.nodata
            or a.dtypes != b.dtypes
        ):
            raise FimUnsupportedError("canonical terrain copy changed the source grid or tiling")
    digest = _pixel_sha256(source)
    if digest != receipt.get("pixel_sha256") or _pixel_sha256(terrain) != digest:
        raise FimUnsupportedError("canonical terrain copy no longer matches the source pixels")
    return {"path": str(terrain), "receipt": str(receipt_path), "pixel_sha256": digest}


def require_engine(method: Optional[dict], what: str) -> None:
    if not isinstance(method, dict) or method.get("terrain_scope") != METHOD_ID:
        raise FimUnsupportedError(
            f"engine {what} method lacks {METHOD_ID}; install ras-commander-fast-map with terrain_scope "
            "support or map on an exported terrain"
        )


def stage(info: dict, root: Path) -> dict:
    """Copy the level-0 mask beside the request; return the request field."""
    import h5py

    path = Path(root) / _MASK_FILE
    with h5py.File(info["terrain_hdf"], "r") as source, path.open("wb") as out:
        mask = source[info["mask_dataset"]]
        if [int(v) for v in mask.shape] != info["mask_shape"]:
            raise FimUnsupportedError("terrain mask changed after resolution")
        step = 256
        for start in range(0, mask.shape[0], step):
            out.write(np.ascontiguousarray(mask[start:start + step], dtype=np.uint8).tobytes())
    return {
        "kind": "top_priority_source",
        "source_count": info["source_count"],
        "mask": {"path": _MASK_FILE, "dtype": "|u1", "shape": info["mask_shape"]},
    }


def describe(info: dict) -> dict:
    """JSON-safe manifest record."""
    return {
        "method_id": METHOD_ID,
        "terrain_hdf": str(info["terrain_hdf"]),
        "tif": str(info["tif"]),
        "source": info["source"],
        "source_count": info["source_count"],
        "sources_in_priority_order": info["sources"],
        "priority_basis": info["priority_basis"],
        "mask_dataset": info["mask_dataset"],
        "rasmap_checked": info["rasmap_checked"],
        "canonical_copy": info.get("canonical_copy"),
    }
