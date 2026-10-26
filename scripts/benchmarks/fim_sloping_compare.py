"""Map a configured real 2D case and compare raw native sloping reference pixels.

The case JSON contains hdf, terrain, engine, profiles (name -> Max/index), and
references (name -> {depth, wse}). Optional bbox/polygon/AOI fields constrain
mapping. Reference maps must use plain sloping with no added depth cutoff.
Native generation uses the separate Commander reference harness; this runner
does not execute HEC-RAS or resample either raster.
"""

import argparse
import json
from pathlib import Path

import numpy as np


def compare_raw(candidate_path, reference_path, cells, aoi=None):
    """Compare validity and float32 bits in the physical 2D cell footprint."""
    import rasterio
    from rasterio.features import rasterize
    from rasterio.windows import bounds, from_bounds, transform
    from shapely.geometry import box

    result = dict(
        common=0, extra=0, missing=0, different=0, outside_footprint=0, maximum=0.0
    )
    with (
        rasterio.open(candidate_path) as candidate,
        rasterio.open(reference_path) as reference,
    ):
        if candidate.crs != reference.crs or candidate.crs != cells.crs:
            raise ValueError("Candidate, native reference and cells must share a CRS")
        if candidate.dtypes != ("float32",) or reference.dtypes != ("float32",):
            raise ValueError("Raw sloping qualification requires float32 products")
        for _, window in candidate.block_windows(1):
            local_transform = transform(window, candidate.transform)
            extent = bounds(window, candidate.transform)
            reference_window = from_bounds(*extent, reference.transform)
            if (
                abs(reference_window.col_off - round(reference_window.col_off)) >= 1e-6
                or abs(reference_window.row_off - round(reference_window.row_off))
                >= 1e-6
            ):
                raise ValueError(
                    "Reference grid is not aligned; resampling is forbidden"
                )
            reference_window = reference_window.round_offsets().round_lengths()
            if not np.allclose(
                tuple(transform(reference_window, reference.transform)),
                tuple(local_transform),
                rtol=0,
                atol=1e-8,
            ):
                raise ValueError("Reference pixel lattice differs")
            actual = candidate.read(1, window=window, masked=True)
            expected = reference.read(
                1, window=reference_window, boundless=True, masked=True
            )
            indices = cells.sindex.query(box(*extent))
            footprint = np.zeros(actual.shape, dtype=bool)
            if len(indices):
                footprint = (
                    rasterize(
                        ((g, 1) for g in cells.geometry.iloc[indices]),
                        out_shape=actual.shape,
                        transform=local_transform,
                        fill=0,
                        dtype="uint8",
                    )
                    > 0
                )
            if aoi is not None:
                footprint &= (
                    rasterize(
                        [(aoi, 1)],
                        out_shape=actual.shape,
                        transform=local_transform,
                        fill=0,
                        dtype="uint8",
                    )
                    > 0
                )
            valid = ~np.ma.getmaskarray(actual) & np.isfinite(actual.data)
            native = ~np.ma.getmaskarray(expected) & np.isfinite(expected.data)
            common = valid & native & footprint
            result["common"] += int(common.sum())
            result["extra"] += int((valid & ~native & footprint).sum())
            result["missing"] += int((native & ~valid & footprint).sum())
            result["outside_footprint"] += int((valid & ~footprint).sum())
            result["different"] += int(
                (
                    actual.data[common].view("u4") != expected.data[common].view("u4")
                ).sum()
            )
            difference = np.abs(
                actual.data[common].astype("f8") - expected.data[common].astype("f8")
            )
            result["maximum"] = max(result["maximum"], float(difference.max(initial=0)))
    return result


def main():
    from ras_commander import HdfMesh, RasFim

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    case = json.loads(args.case.read_text(encoding="utf-8"))
    fields = {
        key: case[key]
        for key in ("bbox", "polygon", "polygon_layer", "aoi_crs")
        if key in case
    }
    manifest = RasFim.map_sloping_profiles(
        case["hdf"],
        case["terrain"],
        args.output,
        profiles=case["profiles"],
        engine_path=case["engine"],
        threads=args.threads,
        max_working_mib=case.get("max_working_mib", 4096),
        write_floodplain=False,
        **fields,
    )
    cells = HdfMesh.get_mesh_cell_polygons(case["hdf"], strict=True)
    from ras_commander.fim import _aoi

    constraint = RasFim.resolve_aoi(default_crs=cells.crs, **fields)
    geometry = _aoi.geometry_in_crs(constraint, cells.crs) if constraint else None
    receipt = dict(
        scope="raw physical 2D footprint; no added cutoff",
        threads=args.threads,
        extra_depth_cutoff=None,
        performance=manifest.attrs["performance"],
        profiles={},
    )
    for product in manifest.itertuples():
        receipt["profiles"][product.profile] = {
            band: compare_raw(
                path, case["references"][product.profile][band], cells, geometry
            )
            for band, path in (("depth", product.depth_tif), ("wse", product.wse_tif))
        }
    metrics = [m for profile in receipt["profiles"].values() for m in profile.values()]
    receipt["exact_match"] = all(
        m["common"] > 0
        and all(
            m[k] == 0 for k in ("extra", "missing", "different", "outside_footprint")
        )
        for m in metrics
    )
    (args.output / "sloping_comparison.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            dict(exact_match=receipt["exact_match"], profiles=receipt["profiles"]),
            indent=2,
        )
    )
    if not receipt["exact_match"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
