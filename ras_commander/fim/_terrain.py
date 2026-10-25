"""Explicit, lossless terrain CRS encoding for native-reader interoperability."""

import hashlib
import json
import os
from pathlib import Path
import uuid

from .errors import FimUnsupportedError


def canonicalize(source_path, output_path):
    import rasterio
    from pyproj import CRS
    from rasterio.enums import MaskFlags
    from rasterio.windows import Window

    source = Path(source_path).resolve(strict=True)
    target = Path(output_path).resolve()
    receipt = target.with_suffix(target.suffix + ".json")
    if source == target or target.exists() or receipt.exists():
        raise FileExistsError("canonical terrain and receipt must be new files")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tif")
    identity = (source.stat().st_size, source.stat().st_mtime_ns)
    digest = hashlib.sha256()
    try:
        with rasterio.open(source) as src:
            if src.count != 1 or src.dtypes != ("float32",) or src.crs is None or src.nodata is None:
                raise FimUnsupportedError("canonicalization requires one float32 band with CRS and nodata")
            if any(flag in src.mask_flag_enums[0] for flag in (MaskFlags.alpha, MaskFlags.per_dataset)):
                raise FimUnsupportedError("canonicalization does not support dataset/alpha masks")
            original = CRS.from_user_input(src.crs)
            epsg = original.to_epsg()
            if epsg is None or not original.equals(CRS.from_epsg(epsg)):
                raise FimUnsupportedError("terrain CRS has no equivalent canonical EPSG definition")
            profile = src.profile.copy()
            profile.update(driver="GTiff", crs=rasterio.crs.CRS.from_epsg(epsg),
                           compress="lzw", GEOTIFF_KEYS_FLAVOR="STANDARD")
            with rasterio.Env(GDAL_NUM_THREADS="1"), rasterio.open(partial, "w", **profile) as dst:
                for row in range(0, src.height, 128):
                    window = Window(0, row, src.width, min(128, src.height - row))
                    data = src.read(1, window=window)
                    digest.update(data.tobytes())
                    dst.write(data, 1, window=window)
            verified = hashlib.sha256()
            with rasterio.open(partial) as dst:
                if dst.shape != src.shape or dst.transform != src.transform or dst.crs != src.crs:
                    raise RuntimeError("canonical terrain grid/CRS verification failed")
                for row in range(0, dst.height, 128):
                    window = Window(0, row, dst.width, min(128, dst.height - row))
                    verified.update(dst.read(1, window=window).tobytes())
            if verified.digest() != digest.digest():
                raise RuntimeError("canonical terrain pixel-bit verification failed")
            state = {"schema": "ras-commander-fim-canonical-terrain/1",
                     "source": str(source), "output": str(target), "epsg": epsg,
                     "source_crs_wkt": original.to_wkt(),
                     "width": src.width, "height": src.height,
                     "transform": list(src.transform), "pixel_sha256": digest.hexdigest(),
                     "pixel_bits_and_grid_preserved": True, "reprojected": False}
        if identity != (source.stat().st_size, source.stat().st_mtime_ns):
            raise RuntimeError("source terrain changed during canonicalization")
        if target.exists() or receipt.exists():
            raise FileExistsError(target)
        os.replace(partial, target)
        receipt.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return target
    finally:
        partial.unlink(missing_ok=True)
