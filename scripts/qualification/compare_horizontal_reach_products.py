"""Compare saved horizontal reach maps against full-domain native references.

Reads inputs only; writes a JSON receipt. The comparison grid covers the entire
AOI bounding window, so native wet pixels outside a candidate's extent count
as missing. No reprojection, resampling, reference replacement or tolerance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window


def _read_aligned(path, transform, shape, crs):
    with rasterio.open(path) as source:
        if source.crs != crs or source.transform.a != transform.a or source.transform.e != transform.e:
            raise ValueError(f"CRS/pixel-size mismatch: {path}")
        if source.transform.b or source.transform.d:
            raise ValueError(f"Rotated raster: {path}")
        x = (transform.c - source.transform.c) / transform.a
        y = (transform.f - source.transform.f) / transform.e
        if abs(x - round(x)) > 1e-6 or abs(y - round(y)) > 1e-6:
            raise ValueError(f"Different pixel lattice: {path}")
        return source.read(1, window=Window(round(x), round(y), shape[1], shape[0]),
                           masked=True, boundless=True).filled(np.nan)


def compare(candidate_depth, candidate_wse, native_depth, native_wse, domain):
    """Count full-AOI wet-mask differences and report independent band errors."""
    with rasterio.open(native_depth) as reference:
        strict = gpd.read_parquet(domain).to_crs(reference.crs).union_all()
        raw = rasterio.windows.from_bounds(*strict.bounds, transform=reference.transform)
        left, top = int(np.floor(raw.col_off)), int(np.floor(raw.row_off))
        right, bottom = int(np.ceil(raw.col_off + raw.width)), int(np.ceil(raw.row_off + raw.height))
        window = Window(left, top, right - left, bottom - top)
        transform, crs = reference.window_transform(window), reference.crs
        shape = (int(window.height), int(window.width))
    inside = geometry_mask([strict], out_shape=shape, transform=transform, invert=True)
    depth = _read_aligned(candidate_depth, transform, shape, crs)
    wse = _read_aligned(candidate_wse, transform, shape, crs)
    reference_depth = _read_aligned(native_depth, transform, shape, crs)
    reference_wse = _read_aligned(native_wse, transform, shape, crs)
    row = {"domain_pixels": int(inside.sum()), "thresholds": {}}
    for cutoff in (0.0, 0.5, 2.0):
        candidate = inside & np.isfinite(depth) & (depth > cutoff)
        native = inside & np.isfinite(reference_depth) & (reference_depth > cutoff)
        common = candidate & native
        both_wse = common & np.isfinite(wse) & np.isfinite(reference_wse)
        depth_error = np.abs(depth[common].astype("float64") - reference_depth[common].astype("float64"))
        wse_error = np.abs(wse[both_wse].astype("float64") - reference_wse[both_wse].astype("float64"))
        row["thresholds"][str(cutoff)] = {
            "candidate_wet": int(candidate.sum()), "native_wet": int(native.sum()),
            "extra": int((candidate & ~native).sum()), "missing": int((~candidate & native).sum()),
            "csi": float(common.sum() / max(1, (candidate | native).sum())),
            "depth_max_abs": float(depth_error.max()) if len(depth_error) else None,
            "wse_max_abs": float(wse_error.max()) if len(wse_error) else None,
            "candidate_missing_wse": int((candidate & ~np.isfinite(wse)).sum()),
            "native_missing_wse": int((native & ~np.isfinite(reference_wse)).sum()),
        }
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", type=Path, required=True,
                        help="Root containing <reach>/<time-index>/09_wsel_t####_depth_nudge.tif and 10_*_wsel_nudge.tif")
    parser.add_argument("--domains", type=Path, required=True, help="Folder of <reach>.geoparquet files")
    parser.add_argument("--references", type=Path, required=True, help="Folder of <time-index>-Depth.tif and <time-index>-WSE.tif")
    parser.add_argument("--reaches", required=True, help="Comma-separated reach identifiers")
    parser.add_argument("--times", required=True, help="Comma-separated saved time indices")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for reach in args.reaches.split(","):
        if Path(reach).name != reach:
            raise ValueError("Reach identifiers must be filenames")
        for time in map(int, args.times.split(",")):
            directory = args.products / reach / str(time)
            row = compare(directory / f"09_wsel_t{time:04d}_depth_nudge.tif",
                          directory / f"10_wsel_t{time:04d}_wsel_nudge.tif",
                          args.references / f"{time}-Depth.tif", args.references / f"{time}-WSE.tif",
                          args.domains / f"{reach}.geoparquet")
            row.update(reach=reach, time_index=time)
            rows.append(row)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps({"comparison": "full-AOI native-lattice, no resampling", "cases": rows}, indent=2) + "\n")
    print(f"Compared {len(rows)} reach/time cases; receipt: {args.receipt}")


if __name__ == "__main__":
    main()
