"""Map a configured real 2D case and compare raw native sloping reference pixels.

The case JSON contains hdf, terrain, engine, profiles (name -> Max/index), and
references (name -> {depth, wse}). Optional bbox/polygon/AOI fields constrain
mapping. Optional render_mode/reduce_shallow_to_horizontal/use_depth_weighted_faces
fields select enhanced sloping. References must use the same options and no
added depth cutoff.
Native generation uses the separate Commander reference harness; this runner
does not execute HEC-RAS or resample either raster.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np


def deliver_reference_grid(candidate_path, reference_path, output_path):
    """Write the exact reference grid, padding nodata without resampling values."""
    import rasterio
    from rasterio.windows import Window

    started = time.perf_counter()
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(output)
    with (
        rasterio.open(candidate_path) as source,
        rasterio.open(reference_path) as reference,
    ):
        if (
            source.crs != reference.crs
            or source.dtypes != ("float32",)
            or reference.dtypes != ("float32",)
        ):
            raise ValueError("Reference-grid delivery requires same-CRS float32 bands")
        a, b = source.transform, reference.transform
        if a.b or a.d or b.b or b.d or a.a != b.a or a.e != b.e:
            raise ValueError("Reference-grid delivery forbids rotation or resampling")
        col = (a.c - b.c) / b.a
        row = (a.f - b.f) / b.e
        if abs(col - round(col)) >= 1e-6 or abs(row - round(row)) >= 1e-6:
            raise ValueError("Reference and candidate pixel centres are not aligned")
        col, row = int(round(col)), int(round(row))
        if (
            col < 0
            or row < 0
            or col + source.width > reference.width
            or row + source.height > reference.height
        ):
            raise ValueError("Candidate does not fit inside the reference grid")
        if reference.nodata is None:
            raise ValueError("Reference grid must declare nodata")
        profile = reference.profile.copy()
        profile.update(dtype="float32", count=1)
        predictor = reference.tags(ns="IMAGE_STRUCTURE").get("PREDICTOR")
        if predictor is not None:
            profile["predictor"] = int(predictor)
        stripe_height = max(1, reference.block_shapes[0][0])
        with (
            rasterio.Env(GDAL_NUM_THREADS="1"),
            rasterio.open(output, "w", **profile) as destination,
        ):
            for top in range(0, reference.height, stripe_height):
                bottom = min(top + stripe_height, reference.height)
                values = np.full(
                    (bottom - top, reference.width), reference.nodata, dtype="float32"
                )
                first = max(top, row)
                last = min(bottom, row + source.height)
                if first < last:
                    values[first - top : last - top, col : col + source.width] = (
                        source.read(
                            1,
                            window=Window(0, first - row, source.width, last - first),
                            masked=True,
                        ).filled(reference.nodata)
                    )
                destination.write(
                    values, 1, window=Window(0, top, reference.width, bottom - top)
                )
    return time.perf_counter() - started


def compare_raw(candidate_path, reference_path, cells, aoi=None, *, full_grid=False):
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
            indices = [] if full_grid else cells.sindex.query(box(*extent))
            footprint = (
                np.ones(actual.shape, dtype=bool)
                if full_grid
                else np.zeros(actual.shape, dtype=bool)
            )
            if len(indices) and not full_grid:
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
            if aoi is not None and not full_grid:
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
    parser.add_argument(
        "--match-reference-grid",
        action="store_true",
        help="Include nodata-border delivery in timing and compare the whole reference grid",
    )
    args = parser.parse_args()
    case = json.loads(args.case.read_text(encoding="utf-8"))
    fields = {
        key: case[key]
        for key in ("bbox", "polygon", "polygon_layer", "aoi_crs")
        if key in case
    }
    if args.match_reference_grid:
        import rasterio

        first = next(iter(case["profiles"]))
        template = case["references"][first]["depth"]
        with rasterio.open(template) as source:
            expected = (
                source.crs,
                source.transform,
                source.shape,
                source.dtypes,
                source.compression,
                source.block_shapes,
            )
        for name in case["profiles"]:
            for band in ("depth", "wse"):
                with rasterio.open(case["references"][name][band]) as source:
                    actual = (
                        source.crs,
                        source.transform,
                        source.shape,
                        source.dtypes,
                        source.compression,
                        source.block_shapes,
                    )
                    if actual != expected:
                        raise ValueError(
                            "Reference products require one common grid/storage profile; compare separately"
                        )
        fields["template_raster"] = template
    started = time.perf_counter()
    manifest = RasFim.map_sloping_profiles(
        case["hdf"],
        case["terrain"],
        args.output,
        profiles=case["profiles"],
        **{
            key: case[key]
            for key in (
                "render_mode",
                "reduce_shallow_to_horizontal",
                "use_depth_weighted_faces",
            )
            if key in case
        },
        engine_path=case["engine"],
        threads=args.threads,
        max_working_mib=case.get("max_working_mib", 4096),
        write_floodplain=False,
        **fields,
    )
    delivered = {
        p.profile: {"depth": p.depth_tif, "wse": p.wse_tif}
        for p in manifest.itertuples()
    }
    matched_seconds = time.perf_counter() - started
    cells = HdfMesh.get_mesh_cell_polygons(case["hdf"], strict=True)
    from ras_commander.fim import _aoi

    constraint = RasFim.resolve_aoi(
        default_crs=cells.crs,
        **{k: v for k, v in fields.items() if k != "template_raster"},
    )
    geometry = _aoi.geometry_in_crs(constraint, cells.crs) if constraint else None
    receipt = dict(
        scope=(
            "complete matched reference grid; no added cutoff"
            if args.match_reference_grid
            else "raw physical 2D footprint; no added cutoff"
        ),
        threads=args.threads,
        extra_depth_cutoff=None,
        performance=manifest.attrs["performance"],
        direct_template=args.match_reference_grid,
        mapping_and_matching_grid_seconds=matched_seconds,
        delivered_products=delivered,
        profiles={},
    )
    for product in manifest.itertuples():
        receipt["profiles"][product.profile] = {
            band: compare_raw(
                delivered.get(product.profile, {}).get(band, path),
                case["references"][product.profile][band],
                cells,
                geometry,
                full_grid=args.match_reference_grid,
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
