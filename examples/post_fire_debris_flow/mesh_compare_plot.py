"""Mesh-refinement comparison figures: uniform vs breakline-refined.

Replaces the old "cell centers" scatter (which mixed two coordinate systems in one
axes and dropped most points). For each mesh this draws the actual **cell polygons
with no fill** (or cell **faces** with ``--faces``) over the feet terrain hillshade,
with the channel centerline overlaid in red so the channel-aligned refinement band
is visible. Each mesh is written as its OWN figure (two files, not two panels).

The uniform and breakline-refined meshes come from two separate ``build`` runs (see
README); point ``--uniform`` / ``--refined`` at each one's geometry HDF (the
``EtherHollow.g01.hdf``, or any plan HDF — both carry the mesh geometry).

Usage
-----
    python mesh_compare_plot.py \
        --uniform   ether_hollow_uniform/EtherHollow.g01.hdf \
        --refined   ether_hollow_proj/EtherHollow.g01.hdf \
        --terrain   ether_hollow_proj/EtherHollow_terrain_ft.tif \
        --breakline data/ether_hollow/channel_breakline_ft.json \
        --out-dir   .

Writes ``mesh_uniform.png`` and ``mesh_refined.png`` into ``--out-dir``.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
import geopandas as gpd
from shapely.geometry import LineString
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource

# ras-commander does the HDF mesh geometry extraction (cell polygons / faces).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ras_commander import HdfMesh  # noqa: E402


def _hillshade(terrain):
    """Return (hillshade array, [l, r, b, t] extent) for an imshow backdrop."""
    with rasterio.open(terrain) as ds:
        dem = ds.read(1).astype(float)
        if ds.nodata is not None:
            dem[dem == ds.nodata] = np.nan
        ext = [ds.bounds.left, ds.bounds.right, ds.bounds.bottom, ds.bounds.top]
        hs = LightSource(315, 45).hillshade(
            np.nan_to_num(dem, nan=np.nanmin(dem)),
            vert_exag=2, dx=ds.res[0], dy=ds.res[1])
    return hs, ext


def _draw_mesh(ax, hdf, faces=False):
    """Draw one mesh (cell polygons, no fill, or cell faces) and return cell count.

    The label uses the true cell count (``Cells Center Coordinate`` length);
    ``get_mesh_cell_polygons`` drops open boundary cells, so its length would
    undercount by a few percent.
    """
    n_cells = len(HdfMesh.get_mesh_cell_points(hdf))
    if faces:
        HdfMesh.get_mesh_cell_faces(hdf).plot(ax=ax, color="#1f4e79", linewidth=0.25)
    else:
        # no fill -> just the cell edges over the terrain
        HdfMesh.get_mesh_cell_polygons(hdf).boundary.plot(
            ax=ax, color="#1f4e79", linewidth=0.25)
    return n_cells


def _load_centerline(path):
    """Read the channel centerline as a GeoDataFrame (model feet, no reprojection).

    Accepts both `delineate_channels.py`'s native format (a JSON list of
    ``{"name", "coords": [[x, y], ...]}``) and a standard GeoJSON of LineStrings.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        data = None
    if isinstance(data, list) and data and isinstance(data[0], dict) and "coords" in data[0]:
        return gpd.GeoDataFrame(
            {"name": [d.get("name", f"line{i}") for i, d in enumerate(data)]},
            geometry=[LineString(d["coords"]) for d in data])
    return gpd.read_file(path)  # GeoJSON / any OGR-readable vector


def _corridor_window(centerline, buffer_ft):
    """Bounding box of the channel centerline padded by ``buffer_ft`` (or None)."""
    if buffer_ft is None:
        return None
    minx, miny, maxx, maxy = centerline.total_bounds
    return (minx - buffer_ft, maxx + buffer_ft, miny - buffer_ft, maxy + buffer_ft)


def _render(out_png, title, hdf, hs, ext, centerline, faces, window):
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.imshow(hs, extent=ext, cmap="gray", origin="upper")
    n_cells = _draw_mesh(ax, hdf, faces=faces)
    if centerline is not None:
        centerline.plot(ax=ax, color="red", linewidth=1.6, zorder=5)
    if window is not None:
        ax.set_xlim(window[0], window[1])
        ax.set_ylim(window[2], window[3])
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(f"{title} ({n_cells:,} cells)", fontsize=12)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_png}  ({n_cells:,} cells)")
    return n_cells


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uniform", required=True, type=Path,
                    help="geometry HDF of the uniform-mesh build")
    ap.add_argument("--refined", required=True, type=Path,
                    help="geometry HDF of the breakline-refined build")
    ap.add_argument("--terrain", required=True, type=Path,
                    help="feet terrain GeoTIFF (hillshade backdrop)")
    ap.add_argument("--breakline", type=Path, default=None,
                    help="channel centerline GeoJSON (feet); drawn in red")
    ap.add_argument("--out-dir", type=Path, default=Path("."))
    ap.add_argument("--faces", action="store_true",
                    help="draw cell faces instead of cell-polygon outlines")
    ap.add_argument("--zoom-buffer-ft", type=float, default=150.0,
                    help="crop to the channel centerline + this buffer "
                         "(0 / negative = full domain). Default 150 ft.")
    ap.add_argument("--reach-center", type=float, nargs=2, metavar=("CX", "CY"),
                    default=None, help="center a tight square window here (model feet); "
                                       "shows individual cells. Overrides --zoom-buffer-ft.")
    ap.add_argument("--reach-half-ft", type=float, default=350.0,
                    help="half-width of the --reach-center window (default 350 ft)")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    hs, ext = _hillshade(args.terrain)

    centerline = None
    window = None
    if args.breakline and args.breakline.exists():
        centerline = _load_centerline(args.breakline)
        if args.zoom_buffer_ft and args.zoom_buffer_ft > 0:
            window = _corridor_window(centerline, args.zoom_buffer_ft)
    if args.reach_center is not None:
        cx, cy = args.reach_center
        h = args.reach_half_ft
        window = (cx - h, cx + h, cy - h, cy + h)

    _render(args.out_dir / "mesh_uniform.png", "Uniform mesh",
            args.uniform, hs, ext, centerline, args.faces, window)
    _render(args.out_dir / "mesh_refined.png", "Breakline-refined",
            args.refined, hs, ext, centerline, args.faces, window)


if __name__ == "__main__":
    main()
