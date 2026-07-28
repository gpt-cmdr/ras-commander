"""Build the compact Muncie land-cover qualification raster.

The source is the native six-class Muncie land-cover TIFF.  A small Urban
window outside the existing ``Flat Area`` calibration region is changed to a
seventh class so native sidecar-table edits can be proven in final solver
arrays without removing the real geometry base and regional overrides.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window, bounds as window_bounds

DEFAULT_SOURCE = Path(
    r"G:\RasProcess Testing\wine_compare\Muncie_simple_test"
    r"\LandCover\LandCoverUserShapefile.tif"
)
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "muncie_landcover_probe.tif"
)
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "muncie_landcover_probe.json"
)

PATCH_ROW = 1044
PATCH_COLUMN = 1497
PATCH_WIDTH = 60
PATCH_HEIGHT = 60
SOURCE_CLASS = 6
PROBE_CLASS = 7


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(values: np.ndarray) -> dict[str, int]:
    return {
        str(int(value)): int(count)
        for value, count in sorted(Counter(values.reshape(-1).tolist()).items())
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    manifest_path = args.manifest.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    window = Window(PATCH_COLUMN, PATCH_ROW, PATCH_WIDTH, PATCH_HEIGHT)
    with rasterio.open(source) as src:
        values = src.read(1)
        profile = src.profile.copy()
        source_overviews = src.overviews(1)
        patch_before = src.read(1, window=window)
        patch_bounds = window_bounds(window, src.transform)
        source_crs = src.crs.to_string() if src.crs else None
        source_transform = tuple(src.transform)

    if patch_before.shape != (PATCH_HEIGHT, PATCH_WIDTH):
        raise RuntimeError(
            f"Qualification window has shape {patch_before.shape}, "
            f"expected {(PATCH_HEIGHT, PATCH_WIDTH)}."
        )
    unique_patch = {int(value) for value in np.unique(patch_before)}
    if unique_patch != {SOURCE_CLASS}:
        raise RuntimeError(
            "Qualification window no longer contains only Urban/class 6; "
            f"found {sorted(unique_patch)}."
        )

    source_counts = _counts(values)
    values[
        PATCH_ROW : PATCH_ROW + PATCH_HEIGHT,
        PATCH_COLUMN : PATCH_COLUMN + PATCH_WIDTH,
    ] = PROBE_CLASS
    output_counts = _counts(values)

    profile.update(
        driver="GTiff",
        dtype="uint8",
        nodata=None,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="deflate",
    )
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(values.astype(np.uint8), 1)
        dst.build_overviews([2, 4, 8], Resampling.nearest)
        dst.update_tags(ns="rio_overview", resampling="nearest")

    with rasterio.open(output) as check:
        actual_overviews = check.overviews(1)
        if check.nodata is not None:
            raise RuntimeError("Qualification raster unexpectedly declares GDAL NoData.")
        if not check.profile.get("tiled"):
            raise RuntimeError("Qualification raster is not tiled.")
        if str(check.profile.get("compress", "")).lower() != "deflate":
            raise RuntimeError("Qualification raster is not DEFLATE-compressed.")
        if actual_overviews != [2, 4, 8]:
            raise RuntimeError(
                f"Qualification raster overviews are {actual_overviews}, "
                "expected [2, 4, 8]."
            )

    expected_counts = dict(source_counts)
    expected_counts[str(SOURCE_CLASS)] = (
        expected_counts[str(SOURCE_CLASS)] - PATCH_WIDTH * PATCH_HEIGHT
    )
    expected_counts[str(PROBE_CLASS)] = PATCH_WIDTH * PATCH_HEIGHT
    if output_counts != expected_counts:
        raise RuntimeError(
            f"Unexpected qualification counts: {output_counts}; "
            f"expected {expected_counts}."
        )

    manifest = {
        "source": str(source),
        "output": str(output),
        "source_sha256": _sha256(source),
        "output_sha256": _sha256(output),
        "width": int(profile["width"]),
        "height": int(profile["height"]),
        "dtype": "uint8",
        "crs": source_crs,
        "transform": list(source_transform),
        "nodata": None,
        "tiled": True,
        "compression": "deflate",
        "overviews": [2, 4, 8],
        "source_class_counts": source_counts,
        "class_counts": output_counts,
        "patch": {
            "row": PATCH_ROW,
            "column": PATCH_COLUMN,
            "width": PATCH_WIDTH,
            "height": PATCH_HEIGHT,
            "bounds": list(patch_bounds),
            "source_class": SOURCE_CLASS,
            "probe_class": PROBE_CLASS,
            "probe_name": "Qualification Probe",
            "baseline_mannings_n": 0.07,
            "edited_mannings_n": 0.077,
        },
        "source_overviews": source_overviews,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
