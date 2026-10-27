"""Plot exact agreement/divergence from retained boundary files, without repair.

Usage: python scripts/benchmarks/fim_boundary_figures.py case.json new_output
Case: {"terrain": "optional.tif", "comparisons": [{"label": "Davis Max",
"left_label": "Rust", "right_label": "Native", "left": "a.geojson",
"right": "b.shp"}]}. Inputs must share a projected CRS. No HEC-RAS is run.
"""

import argparse
import hashlib
import json
from pathlib import Path


def parts(geometry):
    if geometry.geom_type == "Polygon":
        yield geometry
    elif hasattr(geometry, "geoms"):
        for item in geometry.geoms:
            yield from parts(item)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            result.update(block)
    return result.hexdigest()


def main():
    import geopandas as gpd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Rectangle
    from matplotlib.ticker import ScalarFormatter
    from matplotlib.transforms import Bbox
    import numpy as np
    import rasterio
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    case = json.loads(args.case.read_text(encoding="utf-8"))
    comparisons = case["comparisons"]
    if not comparisons:
        raise ValueError("At least one comparison is required")
    args.output.mkdir(parents=True, exist_ok=False)
    watched = {args.case.resolve(), Path(__file__).resolve()}
    for comparison in comparisons:
        for key in ("left", "right"):
            path = Path(comparison[key]).resolve(strict=True)
            watched.add(path)
            if path.suffix.lower() == ".shp":
                watched.update(p for suffix in (".shx", ".dbf", ".prj", ".cpg")
                               if (p := path.with_suffix(suffix)).exists())
    if case.get("terrain"):
        watched.add(Path(case["terrain"]).resolve(strict=True))
    before = {str(path): digest(path) for path in sorted(watched)}
    receipt = {"schema": "boundary-figures/1", "sources": before, "rows": [],
               "policy": "Original geometry; no repair, resampling, snapping or difference buffering."}
    colors = {"both": "#4d9fbd", "left": "#994bc2", "right": "#e58b23"}
    figure, axes = plt.subplots(len(comparisons), 2,
        figsize=(13, 4.7 * len(comparisons)), squeeze=False)
    for index, row in enumerate(comparisons):
        frames = [gpd.read_file(row[key]) for key in ("left", "right")]
        if frames[0].crs is None or not frames[0].crs.is_projected or frames[0].crs != frames[1].crs:
            raise ValueError("References must store the same projected CRS")
        if any(len(frame) != 1 for frame in frames):
            raise ValueError("Each source must contain one complete polygon feature")
        left, right = [frame.geometry.iloc[0] for frame in frames]
        if not left.is_valid or not right.is_valid:
            raise ValueError("Invalid source geometry; automatic repair is forbidden")
        common, left_only, right_only = left.intersection(right), left.difference(right), right.difference(left)
        difference = left.symmetric_difference(right)
        components = sorted(parts(difference), key=lambda p: p.area, reverse=True)
        shells = unary_union([Polygon(p.exterior) for p in parts(left)])
        left_holes = shells.difference(left)
        inside_holes = right_only.intersection(left_holes).area
        right_holes = unary_union([Polygon(p.exterior) for p in parts(right)]).difference(right)
        reverse_inside_holes = left_only.intersection(right_holes).area
        unit = frames[0].crs.axis_info[0].unit_name
        coordinate_unit = "US survey ft" if unit == "US survey foot" else unit
        area_unit = "ft²" if unit == "US survey foot" else unit + "²"
        metrics = dict(label=row["label"], left_label=row["left_label"], right_label=row["right_label"],
            left_area=left.area, right_area=right.area, agreement_area=common.area,
            left_only_area=left_only.area, right_only_area=right_only.area,
            symmetric_difference_area=difference.area,
            intersection_over_union=common.area / left.union(right).area,
            right_only_inside_left_holes_area=inside_holes,
            right_only_hole_fraction=inside_holes / right_only.area if right_only.area else None,
            left_only_inside_right_holes_area=reverse_inside_holes,
            left_only_hole_fraction=reverse_inside_holes / left_only.area if left_only.area else None,
            left_holes=sum(len(p.interiors) for p in parts(left)),
            right_holes=sum(len(p.interiors) for p in parts(right)),
            largest_difference_components=[dict(area=p.area, bounds=list(p.bounds)) for p in components[:5]],
            crs=frames[0].crs.to_string(), units=frames[0].crs.axis_info[0].unit_name)
        receipt["rows"].append(metrics)
        all_bounds = left.union(right).bounds
        zoom_bounds = components[0].bounds if components else all_bounds
        x0, y0, x1, y1 = zoom_bounds
        span = max(x1 - x0, y1 - y0, 1.) * 1.35
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        zoom_bounds = (cx - span / 2, cy - span / 2, cx + span / 2, cy + span / 2)
        for column, bounds in enumerate((all_bounds, zoom_bounds)):
            ax = axes[index, column]
            if case.get("terrain"):
                with rasterio.open(case["terrain"]) as terrain:
                    if terrain.crs != frames[0].crs:
                        raise ValueError("Terrain CRS mismatch; no implicit reprojection")
                    window = rasterio.windows.from_bounds(*bounds, terrain.transform).round_offsets().round_lengths()
                    if window.width > 0 and window.height > 0:
                        data = terrain.read(1, window=window, masked=True)
                        extent = rasterio.windows.bounds(window, terrain.transform)
                        valid = data.compressed()
                        if valid.size:
                            lo, hi = np.percentile(valid, [2, 98])
                            ax.imshow(data, extent=(extent[0], extent[2], extent[1], extent[3]),
                                cmap="Greys", vmin=lo, vmax=max(hi, lo + .01), alpha=.22, zorder=0)
            for geometry, color in ((common, colors["both"]), (left_only, colors["left"]), (right_only, colors["right"])):
                clipped = geometry.intersection(box(*bounds))
                polygons = list(parts(clipped))
                if polygons:
                    gpd.GeoSeries(polygons).plot(ax=ax, color=color, edgecolor="none", zorder=2)
            ax.set_xlim(bounds[0], bounds[2]); ax.set_ylim(bounds[1], bounds[3])
            ax.set_aspect("equal")
            for axis in (ax.xaxis, ax.yaxis):
                formatter = ScalarFormatter(useOffset=False)
                formatter.set_scientific(False); axis.set_major_formatter(formatter)
            ax.tick_params(labelsize=7, rotation=20)
            ax.set_xlabel(f"Easting ({coordinate_unit})", fontsize=8)
            ax.set_ylabel(f"Northing ({coordinate_unit})", fontsize=8)
            ax.set_title(row["label"] + (" — overview" if column == 0 else " — largest divergence"), fontsize=12)
            ax.legend(handles=[Patch(color=colors["both"], label="Agreement"),
                Patch(color=colors["left"], label=row["left_label"] + " only"),
                Patch(color=colors["right"], label=row["right_label"] + " only")],
                fontsize=8, loc="upper right", framealpha=.95)
            if column == 0:
                ax.add_patch(Rectangle((zoom_bounds[0], zoom_bounds[1]), span, span,
                    fill=False, edgecolor="#242c34", linewidth=1.1, linestyle="--", zorder=4))
            else:
                ax.text(.02, .02, f"Whole map: IoU {metrics['intersection_over_union']:.8%}\n"
                    f"{row['left_label']} only {left_only.area:,.6f} {area_unit}\n"
                    f"{row['right_label']} only {right_only.area:,.6f} {area_unit}", transform=ax.transAxes,
                    fontsize=8, bbox=dict(facecolor="white", edgecolor="none", alpha=.93), zorder=5)
        features = [dict(type="Feature", properties={"category": category}, geometry=geometry.__geo_interface__)
            for category, geometry in (("agreement", common), ("left_only", left_only), ("right_only", right_only))]
        (args.output / f"difference-{index}.geojson").write_text(json.dumps(dict(type="FeatureCollection",
            crs=dict(type="name", properties=dict(name=frames[0].crs.to_string())), features=features)), encoding="utf-8")
    figure.suptitle(case.get("title", "Stored boundaries: actual agreement and divergence"), fontsize=16, y=.998)
    figure.tight_layout(rect=(0, 0, 1, .98), h_pad=2)
    figure.savefig(args.output / "boundary-agreement.png", dpi=180, bbox_inches="tight")
    figure.savefig(args.output / "boundary-agreement.pdf", bbox_inches="tight")
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    for index, row_axes in enumerate(axes):
        bounds = Bbox.union([ax.get_tightbbox(renderer) for ax in row_axes])
        bounds = bounds.transformed(figure.dpi_scale_trans.inverted()).expanded(1.015, 1.04)
        figure.savefig(args.output / f"comparison-{index}.png", dpi=180, bbox_inches=bounds)
    plt.close(figure)
    if {str(path): digest(path) for path in sorted(watched)} != before:
        raise RuntimeError("A source changed while drawing figures")
    (args.output / "metrics.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt["rows"], indent=2))


if __name__ == "__main__":
    main()
