"""
ether_hollow_debris_flow.py — Ether Hollow post-fire debris-flow model, from scratch.

US Customary (feet) HEC-RAS 7.0 model of a single high-hazard basin from the
2020 Ether Hollow Fire (Utah County, UT). Foundation phases:

  data     (no HEC-RAS): select target basin from the USGS DF predictions,
           reproject to feet UTM 12N, fetch + convert the 1 m DEM to feet,
           write the basin perimeter + a feet terrain GeoTIFF.
  build    (HEC-RAS, interactive session): create_project_from_template ->
           RasTerrain (associate feet terrain) -> set_2d_flow_area_perimeter ->
           generate_computation_points -> compute_plan(force_geompre) -> mesh.

Later phases (BC + bulked inflow, clear-water run, Bingham NN sensitivity,
compare + hazard maps) build on the meshed project this produces.

Inputs live under <root>/data/ether_hollow (USGS DF predictions, projection .prj,
HMS hydrograph); 3DEP lidar is downloaded on demand. build/run drive HEC-RAS on
Windows in an interactive session. See README.md.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


# Feet UTM 12N (HEC DebrisProjection_USCust.prj) — model CRS. US survey foot.
M_PER_USFT = 1200.0 / 3937.0          # exact US survey foot
M_TO_USFT = 1.0 / M_PER_USFT


def banner(m):
    print("\n" + "=" * 78 + f"\n{m}\n" + "=" * 78)


def _data_dir(root: Path) -> Path:
    return root / "data" / "ether_hollow"


def select_basin(data_dir: Path, intensity: str = "12mmh"):
    """Pick the highest combined-hazard basin from the USGS DF predictions.

    intensity "12mmh" matches the HEC tutorial's design storm
    (eth2020_Basin_DFPredictions_15min_12mmh).
    """
    import geopandas as gpd
    shp = data_dir / "burn" / f"eth2020_Basin_DFPredictions_15min_{intensity}.shp"
    gdf = gpd.read_file(shp)
    # rank by combined hazard then debris-flow volume
    gdf = gdf.sort_values(["CombHaz", "Volume"], ascending=False).reset_index(drop=True)
    row = gdf.iloc[0]
    info = {
        "basin_id": int(row.get("BASIN_ID", -1)),
        "segment_id": int(row.get("Segment_ID", -1)) if "Segment_ID" in gdf.columns else -1,
        "up_area_km2": float(row["UpArea_km2"]),
        "volume_m3": float(row["Volume"]),
        "vol_min_m3": float(row["VolMin"]),
        "vol_max_m3": float(row["VolMax"]),
        "prob": float(row["P"]),
        "comb_haz": int(row.get("CombHaz", -1)),
        "comb_haz_class": str(row.get("CombHazCl_", "")),
        "src_crs": str(gdf.crs),
    }
    return gdf.iloc[[0]], info


def runout_corridor(dem_path: Path, outlet_xy, src_crs,
                    max_dist_m: float = 1600.0, step_m: float = 10.0,
                    width_m: float = 120.0):
    """Trace a steepest-descent flow path from the basin outlet on the DEM and
    return a buffered corridor polygon (in the DEM's CRS).

    Captures the downstream runout/deposition reach (the tutorial extends the 2D
    area ~1 mile downstream onto the alluvial fan). Coarse stepping + a simple
    pit-escape keeps the trace robust on a 1 m DEM.
    """
    import numpy as np
    import rasterio
    from shapely.geometry import LineString

    with rasterio.open(dem_path) as ds:
        arr = ds.read(1).astype("float64")
        nodata = ds.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        tf = ds.transform
        H, W = arr.shape
        dem_crs = ds.crs

        def elev(x, y):
            c, r = ~tf * (x, y)
            r, c = int(round(r)), int(round(c))
            if 0 <= r < H and 0 <= c < W:
                return arr[r, c]
            return np.nan

        # outlet_xy is in src_crs; index it in the DEM grid CRS (no-op when
        # 3DEP serves the basin CRS, correct if it ever differs).
        ox, oy = float(outlet_xy[0]), float(outlet_xy[1])
        if src_crs is not None and dem_crs is not None and str(dem_crs) != str(src_crs):
            from pyproj import Transformer
            ox, oy = Transformer.from_crs(src_crs, dem_crs, always_xy=True).transform(ox, oy)
        x, y = ox, oy
        pts = [(x, y)]
        dirs = [(step_m * math.cos(a), step_m * math.sin(a))
                for a in [i * math.pi / 4 for i in range(8)]]
        last = None
        dist = 0.0
        while dist < max_dist_m:
            here = elev(x, y)
            here = here if np.isfinite(here) else np.inf
            best, bd = None, None
            # search increasing radii to step over small pits/flats
            for mult in (1.0, 2.0, 3.0):
                bz = here
                for dx, dy in dirs:
                    z = elev(x + dx * mult, y + dy * mult)
                    if np.isfinite(z) and z < bz:
                        bz, best, bd = z, (x + dx * mult, y + dy * mult), (dx, dy)
                if best is not None:
                    break
            if best is None:           # true pit -> coast in last direction, else stop
                if last is None:
                    break
                cand = (x + last[0], y + last[1])
                if not np.isfinite(elev(*cand)):
                    break
                best, bd = cand, last
            px, py = x, y
            x, y = best
            last = bd
            pts.append((x, y))
            dist += math.hypot(x - px, y - py)   # true step length (handles
            #                  pit-escape 2x/3x jumps and diagonal x sqrt(2))
        if len(pts) < 2:
            return None
        corridor = LineString(pts).buffer(width_m / 2.0, cap_style=2)
        # the trace runs in the DEM grid's CRS; return it in the caller's
        # src_crs so the downstream union stays single-CRS even if 3DEP ever
        # serves a projection other than the basin's.
        if src_crs is not None and dem_crs is not None and str(dem_crs) != str(src_crs):
            import geopandas as gpd
            corridor = gpd.GeoSeries([corridor], crs=dem_crs).to_crs(src_crs).iloc[0]
        return corridor


def fetch_3dep_mosaic(area_gdf, out_dir: Path, projects) -> Path:
    """Download USGS 3DEP 1 m tiles from one or more projects covering
    ``area_gdf`` and merge them into one GeoTIFF.

    A basin that straddles 3DEP project boundaries is not fully covered by any
    single tile/project (each has nodata gores at its project edge), so we
    mosaic MULTIPLE projects. ``projects`` is listed newest-first; merge uses
    method='first', so earlier (newer) sources win and later ones fill nodata.
    """
    import rasterio
    from rasterio.merge import merge
    from ras_commander.terrain.Usgs3depAws import Usgs3depAws

    out_dir.mkdir(parents=True, exist_ok=True)
    mosaic_path = out_dir / "dem_3dep_mosaic.tif"
    if mosaic_path.exists():
        print(f"[data] 3DEP mosaic cached: {mosaic_path}")
        return mosaic_path
    bbox = tuple(float(v) for v in area_gdf.to_crs(4326).total_bounds)
    print(f"[data] 3DEP fetch bbox(wgs84)={[round(v,4) for v in bbox]} projects={projects}")
    all_tiles = []
    for proj in projects:
        proj = str(proj).strip()
        if not proj:
            continue
        try:
            tiles = Usgs3depAws.download_tiles(bbox, 1, out_dir, project_name=proj)
        except Exception as e:  # noqa: BLE001
            print(f"[data]   project {proj}: fetch failed ({e})")
            tiles = []
        if not tiles:  # already-present tiles may be skipped by download_tiles
            tiles = sorted(out_dir.glob(f"*{proj}*.tif"))
        print(f"[data]   project {proj}: {len(tiles)} tile(s)")
        all_tiles.extend(tiles)
    if not all_tiles:
        raise RuntimeError(f"No 3DEP 1m tiles found for bbox {bbox} from {projects}")
    srcs = [rasterio.open(t) for t in all_tiles]
    try:
        arr, tf = merge(srcs, method="first")   # newest-first ordering wins
        meta = srcs[0].meta.copy()
        meta.update(driver="GTiff", height=arr.shape[1], width=arr.shape[2],
                    transform=tf, count=1, compress="deflate")
        with rasterio.open(mosaic_path, "w", **meta) as dst:
            dst.write(arr[0], 1)
    finally:
        for s in srcs:
            s.close()
    print(f"[data] 3DEP mosaic: {mosaic_path} from {len(all_tiles)} tile(s) / "
          f"{len(projects)} project(s)")
    return mosaic_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["data", "build", "run", "all"], default="data")
    ap.add_argument("--root", type=Path, default=Path("."),
                    help="root holding data/ether_hollow/ inputs and prep/ outputs")
    ap.add_argument("--workdir", type=Path, default=Path("ether_hollow_proj"),
                    help="HEC-RAS project workspace (created by the build phase)")
    ap.add_argument("--project-name", default="EtherHollow")
    ap.add_argument("--cell-size-ft", type=float, default=33.0)  # ~10 m, matches tutorial
    ap.add_argument("--breaklines", action="store_true",
                    help="refine the mesh along TauDEM channel centerlines "
                         "(reads channel_breakline_ft.json from the data dir; "
                         "produce it with delineate_channels.py)")
    ap.add_argument("--channel-width-ft", type=float, default=30.0,
                    help="approximate channel width -> width of the refined corridor")
    ap.add_argument("--channel-cell-ft", type=float, default=12.0,
                    help="breakline near=far spacing (uniform fine cells along the thalweg)")
    ap.add_argument("--breakline-simplify-ft", type=float, default=10.0,
                    help="Douglas-Peucker tolerance applied to the centerline before authoring")
    ap.add_argument("--buffer-ft", type=float, default=300.0)
    ap.add_argument("--runout-m", type=float, default=1600.0)     # ~1 mile downstream
    ap.add_argument("--corridor-width-m", type=float, default=200.0)
    ap.add_argument("--no-corridor", action="store_true",
                    help="basin-only domain — skip the runout corridor trace "
                         "(isolation run to confirm the terrain-in-mesh path)")
    ap.add_argument("--mannings-n", type=float, default=0.08,
                    help="base Manning's n for the 2D area. The template default "
                         "0.04 is a smooth-channel value; post-fire ash/rilled/"
                         "debris-strewn steep terrain is ~0.06-0.10.")
    ap.add_argument("--inflow-at", choices=["head", "outlet"], default="head",
                    help="inflow BC placement: 'head' = highest-elevation perimeter "
                         "(basin head, whole-basin routing); 'outlet' = perimeter "
                         "nearest the basin outlet/fan apex (basin = hydrology only)")
    ap.add_argument("--inflow-width-ft", type=float, default=200.0,
                    help="span of the upstream inflow BC line along the domain edge")
    ap.add_argument("--outflow-width-ft", type=float, default=300.0,
                    help="span of the downstream normal-depth BC line")
    ap.add_argument("--sim-hours", type=float, default=2.0,
                    help="unsteady run duration (h); covers the flashy peak + recession")
    ap.add_argument("--comp-interval", default="1SEC",
                    help="HEC-RAS computation interval; small to keep Courant in "
                         "check on the steep 33 ft mesh (5SEC went unstable)")
    ap.add_argument("--equation-set", choices=["SWE-ELM", "DWE"], default="SWE-ELM",
                    help="2D equation set. Full Momentum (SWE-ELM) is REQUIRED for "
                         "non-Newtonian/mobile-bed debris flow — Diffusion Wave (DWE) "
                         "drops the inertial terms and is not applicable here.")
    ap.add_argument("--yields", default="700,2500",
                    help="comma list of Bingham yield stresses (Pa) to run as NN "
                         "variants, alongside a clear-water baseline")
    ap.add_argument("--cv", type=float, default=0.70,
                    help="volumetric sediment concentration for Bulk Fluid Volume "
                         "bulking (Cv=0.70 -> bulking factor 1/(1-Cv)=3.33)")
    ap.add_argument("--viscosity-pa", type=float, default=100.0,
                    help="Bingham dynamic viscosity (Pa*s)")
    ap.add_argument("--dem-projects",
                    default="UT_Central_QL1_B2_2018,UT_Wasatch_L5_2014",
                    help="comma-list of USGS 3DEP project S3 folders to mosaic (newest first)")
    ap.add_argument("--status", type=Path, default=Path("ether_hollow_status.jsonl"),
                    help="JSONL run/status log")
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="dir with prep artifacts (feet DEM/perimeter/projection) for build phase")
    args = ap.parse_args()

    data_dir = _data_dir(args.root)
    prep = data_dir / "prep"
    prep.mkdir(parents=True, exist_ok=True)
    args.status.parent.mkdir(parents=True, exist_ok=True)

    def status(rec):
        from datetime import datetime
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), **rec}
        with open(args.status, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        print("[status]", rec)

    if args.phase in ("data", "all"):
        banner("PHASE data — select basin, reproject to feet, build feet DEM")
        import geopandas as gpd
        import numpy as np
        import rasterio
        from rasterio.warp import calculate_default_transform, reproject, Resampling
        from rasterio.mask import mask as rio_mask

        # feet CRS from HEC's projection file
        feet_wkt = (data_dir / "DebrisProjection_USCust.prj").read_text(encoding="utf-8")
        from pyproj import CRS
        feet_crs = CRS.from_wkt(feet_wkt)
        print("[data] feet CRS:", feet_crs.name)

        from shapely.ops import unary_union

        basin_gdf, info = select_basin(data_dir)
        print("[data] selected basin:", json.dumps(info, indent=2))
        src_crs_data = basin_gdf.crs  # EPSG:26912 (m)

        # fetch USGS 3DEP 1m coverage for the basin + downstream runout buffer
        # (full multi-tile mosaic — needed for the corridor trace AND the final
        # terrain; the single HEC tutorial tile only covers ~half the domain).
        cover = gpd.GeoDataFrame(
            geometry=[basin_gdf.geometry.iloc[0].buffer(args.runout_m + 500.0)],
            crs=src_crs_data)
        dem_src = fetch_3dep_mosaic(cover, data_dir / "3dep",
                                    projects=args.dem_projects.split(","))

        # outlet point for this basin (pour point), else basin representative point
        pts = gpd.read_file(data_dir / "burn" / "eth2020_basinpt_feat.shp")
        sel = pts[pts["BASIN_ID"] == info["basin_id"]] if "BASIN_ID" in pts.columns else pts.iloc[0:0]
        if len(sel):
            outlet_xy = (float(sel.geometry.iloc[0].x), float(sel.geometry.iloc[0].y))
        else:
            rp = basin_gdf.geometry.iloc[0].representative_point()
            outlet_xy = (rp.x, rp.y)
        print("[data] outlet(m):", [round(v, 1) for v in outlet_xy])

        # downstream runout corridor + union with the source basin -> 2D domain
        if args.no_corridor:
            corridor = None
            print("[data] basin-only domain (--no-corridor): runout trace skipped")
        else:
            corridor = runout_corridor(dem_src, outlet_xy, src_crs_data,
                                       max_dist_m=args.runout_m, step_m=10.0,
                                       width_m=args.corridor_width_m)
        from shapely import make_valid
        from shapely.geometry import MultiPolygon
        from shapely.geometry.polygon import orient

        geoms = [basin_gdf.geometry.iloc[0]]
        if corridor is not None and not corridor.is_empty:
            geoms.append(corridor)
        else:
            print("[data] WARNING: runout corridor trace degenerate; "
                  "domain = source basin only")
        # A buffered flow-line union has slivers / self-intersections / vertices
        # spaced below the cell size — RAS Mapper's PointGenerator then yields no
        # computation points and the mesher emits ZERO cells. Heal the union and
        # drop sub-cell vertices before it becomes the 2D-area perimeter.
        cell_m = args.cell_size_ft * M_PER_USFT
        domain_src = make_valid(unary_union(geoms)).buffer(0)
        if isinstance(domain_src, MultiPolygon):
            parts = sorted(domain_src.geoms, key=lambda g: g.area, reverse=True)
            print(f"[data] domain union split into {len(parts)} parts "
                  f"(basin/corridor disjoint?); keeping largest "
                  f"({parts[0].area/1e6:.3f} km2)")
            domain_src = parts[0]
        domain_src = domain_src.simplify(cell_m * 0.5).buffer(0)
        domain_gdf = gpd.GeoDataFrame(geometry=[domain_src], crs=src_crs_data)
        print(f"[data] domain (basin+corridor): {domain_src.area/1e6:.3f} km2, "
              f"{len(domain_src.exterior.coords)} verts")

        # reproject domain -> feet, enforce CCW exterior orientation, write perimeter
        domain_ft = domain_gdf.to_crs(feet_crs)
        poly_ft = orient(domain_ft.geometry.iloc[0], sign=1.0)
        domain_ft = gpd.GeoDataFrame(geometry=[poly_ft], crs=feet_crs)
        domain_ft.to_file(prep / "domain_ft.shp")
        ring = list(poly_ft.exterior.coords)
        (prep / "basin_perimeter_ft.json").write_text(
            json.dumps([[float(x), float(y)] for x, y in ring]), encoding="utf-8")
        minx, miny, maxx, maxy = domain_ft.total_bounds
        print(f"[data] domain perimeter: {len(ring)} verts, bounds(ft)="
              f"{[round(v,1) for v in (minx,miny,maxx,maxy)]}")

        # clip DEM to the domain BBOX (a rectangle — NOT the polygon, so the
        # terrain has full coverage with no interior NaN holes that would make
        # RAS Mapper's CreatePropertyTables fail), reproject to feet, scale m->ft.
        from shapely.geometry import box as _box
        NODATA = -9999.0   # numeric sentinel (RAS terrains dislike NaN nodata)
        dom_buf = domain_gdf.buffer(args.buffer_ft * M_PER_USFT)
        with rasterio.open(dem_src) as src:
            nd = src.nodata if src.nodata is not None else NODATA
            bbox = _box(*dom_buf.to_crs(src.crs).total_bounds)
            clip, clip_tf = rio_mask(src, [bbox.__geo_interface__], crop=True,
                                     filled=True, nodata=nd)
            src_crs = src.crs
        clip = clip[0].astype("float32")
        clip[clip == nd] = np.nan
        # reproject clip -> feet CRS
        dst_tf, w, h = calculate_default_transform(
            src_crs, feet_crs, clip.shape[1], clip.shape[0],
            *rasterio.transform.array_bounds(clip.shape[0], clip.shape[1], clip_tf))
        dst = np.full((h, w), np.nan, dtype="float32")
        reproject(source=clip, destination=dst,
                  src_transform=clip_tf, src_crs=src_crs,
                  dst_transform=dst_tf, dst_crs=feet_crs,
                  src_nodata=np.nan, dst_nodata=np.nan,
                  resampling=Resampling.bilinear)
        # vertical m -> US ft, then write with a numeric nodata sentinel
        dst = dst * M_TO_USFT
        dem_ft = prep / "EtherHollow_terrain_ft.tif"
        dst_out = np.where(np.isfinite(dst), dst, NODATA).astype("float32")
        with rasterio.open(dem_ft, "w", driver="GTiff", height=h, width=w, count=1,
                           dtype="float32", crs=feet_crs, transform=dst_tf,
                           nodata=NODATA, compress="deflate") as out:
            out.write(dst_out, 1)
        # also write the ESRI .prj sidecar
        (dem_ft.with_suffix(".prj")).write_text(feet_crs.to_wkt("WKT1_ESRI"), encoding="utf-8")
        nfin = int(np.isfinite(dst).sum())
        print(f"[data] feet terrain: {dem_ft} ({w}x{h}, finite={nfin}, "
              f"elev {np.nanmin(dst):.0f}-{np.nanmax(dst):.0f} ft, nodata={NODATA})")

        # clear-water inflow hydrograph (US Customary CFS, 1-min ordinates) from
        # the HMS export — NOT pre-bulked (bulking is the Bulk Fluid Volume option
        # in the non-Newtonian phase). Written to prep/ for staging to the runner.
        import pandas as pd
        hg = pd.read_excel(data_dir / "HMS_Hydrograph_SI.xlsx",
                           sheet_name="US Cust", header=None)
        cfs = [round(float(v), 2) for v in
               pd.to_numeric(hg.iloc[:, 2], errors="coerce").dropna().to_numpy()]
        (prep / "inflow_hydrograph.json").write_text(
            json.dumps({"interval": "1MIN", "units": "cfs", "cfs": cfs}),
            encoding="utf-8")
        print(f"[data] inflow hydrograph: {len(cfs)} ords @1MIN, "
              f"peak {max(cfs):.0f} cfs at min {cfs.index(max(cfs))+1}")

        # basin outlet / fan apex in feet CRS (for the --inflow-at outlet placement)
        from shapely.geometry import Point as _Point
        outlet_ft = gpd.GeoSeries([_Point(*outlet_xy)], crs=src_crs_data).to_crs(feet_crs).iloc[0]
        (prep / "outlet_ft.json").write_text(
            json.dumps([float(outlet_ft.x), float(outlet_ft.y)]), encoding="utf-8")
        # copy the model-CRS projection into prep so the build phase can read it
        # from the default prep dir (when --data-dir is not passed explicitly).
        import shutil as _shutil
        _shutil.copy2(data_dir / "DebrisProjection_USCust.prj",
                      prep / "DebrisProjection_USCust.prj")

        status({"phase": "data", "ok": True, "basin": info,
                "perimeter_verts": len(ring), "hydrograph_ords": len(cfs),
                "peak_cfs": max(cfs),
                "dem_ft": str(dem_ft), "dem_shape": [int(h), int(w)]})
        if args.phase == "data":
            return 0

    if args.phase in ("build", "all"):
        banner("PHASE build — instantiate, 2D area, mesh, terrain (HEC-RAS)")
        from ras_commander import init_ras_project, create_project_from_template, RasCmdr
        from ras_commander.terrain.RasTerrain import RasTerrain
        from ras_commander.RasMap import RasMap
        from ras_commander.geom.GeomStorage import GeomStorage
        from ras_commander.geom.GeomMesh import GeomMesh
        from ras_commander.geom.GeomBcLines import GeomBcLines

        ddir = args.data_dir or (prep)
        feet_wkt = (ddir / "DebrisProjection_USCust.prj").read_text(encoding="utf-8")
        ring = json.loads((ddir / "basin_perimeter_ft.json").read_text(encoding="utf-8"))
        dem_ft = ddir / "EtherHollow_terrain_ft.tif"
        cell = int(args.cell_size_ft)
        name = args.project_name
        wd = args.workdir
        wd.parent.mkdir(parents=True, exist_ok=True)

        # 1. instantiate project from template (feet UTM 12N CRS)
        prj = create_project_from_template(
            wd, project_name=name, version="7.0", target_crs=feet_wkt, overwrite=True)
        init_ras_project(str(wd), "7.0")
        geom_text = wd / f"{name}.g01"
        rasmap = wd / f"{name}.rasmap"
        proj_prj = wd / f"{name}.projection.prj"
        print(f"[build] instantiated {prj.name}")

        # 2. author the 2D flow-area perimeter + initial computation points
        GeomStorage.set_2d_flow_area_perimeter(
            geom_file=geom_text, flow_area_name="DebrisFlowArea",
            coordinates=ring, point_generation_data=[None, None, cell, cell])
        # realistic base roughness for post-fire steep terrain (template default
        # 0.04 is too smooth -> over-fast velocities). Set in geometry text; HEC-RAS
        # applies it to cells during preprocessing (not a direct cell-n HDF write).
        GeomStorage.set_2d_flow_area_settings(
            geom_file=geom_text, flow_area_name="DebrisFlowArea",
            mannings_n=args.mannings_n)
        print(f"[build] base Manning's n = {args.mannings_n}")
        gp = GeomMesh.generate_computation_points(
            str(geom_text), mesh_name="DebrisFlowArea", cell_size=float(cell))
        print(f"[build] generate_computation_points -> status={getattr(gp,'status',None)} "
              f"pts={getattr(gp,'cell_count',None)}")

        # 2b. author inflow + outflow BC lines on the domain edge. The inflow line
        #     sits on the highest-elevation perimeter segment (basin head, where the
        #     runoff hydrograph enters), the normal-depth outflow on the lowest
        #     (corridor/fan toe). Sample the feet terrain at each ring vertex to
        #     locate them; friction slope = local bed slope above the outflow.
        elevs = _sample_terrain_elev(dem_ft, ring)
        outflow_pts = _pick_bc_segment(ring, elevs, "low", args.outflow_width_ft)
        outlet_json = ddir / "outlet_ft.json"
        if args.inflow_at == "outlet" and outlet_json.exists():
            outlet_pt = json.loads(outlet_json.read_text(encoding="utf-8"))
            inflow_pts = _pick_bc_segment_near(ring, outlet_pt, args.inflow_width_ft)
            print(f"[build] inflow at OUTLET/apex near {[round(v) for v in outlet_pt]}")
        else:
            inflow_pts = _pick_bc_segment(ring, elevs, "high", args.inflow_width_ft)
            print("[build] inflow at basin HEAD (highest-elevation perimeter)")
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        fslope = _bed_slope(dem_ft, outflow_pts, (cx, cy))
        GeomBcLines.add_bc_lines(geom_text, replace_existing=True, lines=[
            {"name": "Inflow", "storage_area": "DebrisFlowArea", "coordinates": inflow_pts},
            {"name": "Outflow", "storage_area": "DebrisFlowArea", "coordinates": outflow_pts},
        ])
        (wd / "bc_meta.json").write_text(json.dumps({
            "inflow_name": "Inflow", "outflow_name": "Outflow",
            "friction_slope": round(fslope, 5), "inflow_at": args.inflow_at,
            "inflow_verts": len(inflow_pts), "outflow_verts": len(outflow_pts),
        }), encoding="utf-8")
        print(f"[build] BC lines: Inflow({len(inflow_pts)} pts) + "
              f"Outflow({len(outflow_pts)} pts), friction_slope={fslope:.4f}")

        # 3. create the RAS terrain from the feet DEM + register it in the .rasmap
        terrain_hdf = RasTerrain.create_terrain_from_rasters(
            input_rasters=[dem_ft], output_folder=wd / "Terrain",
            terrain_name="Terrain", units="Feet", hecras_version="7.0")
        print(f"[build] terrain: {terrain_hdf}")
        RasMap.add_terrain_layer(terrain_hdf, rasmap, layer_name="Terrain",
                                 projection_prj=proj_prj)

        # 4. minimal geometry-only flow + plan; register in .prj
        (wd / f"{name}.u01").write_text(
            "Flow Title=Geometry Only\nProgram Version=7.00\n"
            "BEGIN FILE DESCRIPTION:\nEND FILE DESCRIPTION:\nUse Restart= 0 \n",
            encoding="utf-8")
        # geometry-preprocessor-only bootstrap (Run UNet=0): build mesh + 2D tables
        # without running the solver, so the newly-added BC lines (which have no
        # flow data yet) don't trigger an unsteady "boundary not specified" error.
        (wd / f"{name}.p01").write_text(
            "Plan Title=Mesh Bootstrap\nProgram Version=7.00\n"
            "Geom File=g01\nFlow File=u01\nRun HTab=-1\nRun UNet= 0\nRun Sed= 0\n"
            "Run WQ= 0\nShort ID=MESHBOOT\n"
            "Simulation Date=01JAN2000,0000,01JAN2000,0100\n"
            "Computation Interval=30SEC\nOutput Interval=1HOUR\n"
            "Instantaneous Interval=15MIN\nMapping Interval=1HOUR\n", encoding="utf-8")
        txt = prj.read_text(encoding="utf-8", errors="replace")
        if "Current Plan=" not in txt:
            lines, out = txt.splitlines(keepends=True), []
            for ln in lines:
                out.append(ln)
                if ln.startswith("Proj Title="):
                    out.append("Current Plan=p01\n")
            txt = "".join(out)
        if ("Plan File=p01" not in txt or "Unsteady File=u01" not in txt) \
                and "Geom File=g01\n" not in txt:
            raise RuntimeError(
                "template .prj has no 'Geom File=g01' anchor line; cannot "
                "register plan/flow files via text insertion")
        if "Plan File=p01" not in txt:
            txt = txt.replace("Geom File=g01\n", "Geom File=g01\nPlan File=p01\n", 1)
        if "Unsteady File=u01" not in txt:
            txt = txt.replace("Geom File=g01\n", "Geom File=g01\nUnsteady File=u01\n", 1)
        prj.write_text(txt, encoding="utf-8")

        # 5. build the mesh TOPOLOGY (HEC-RAS geometry preprocessor); force_geompre
        #    rebuilds the .g01.hdf from the .g01 text + 2D points.
        geom_hdf = wd / f"{name}.g01.hdf"
        init_ras_project(str(wd), "7.0")
        cres = RasCmdr.compute_plan("01", force_geompre=True, num_cores=2)
        topo_ok, topo_detail = hdf_has_2d_mesh(geom_hdf)
        print(f"[build] mesh topology: {topo_ok} ({topo_detail})")

        # 5b. (optional) channel-centerline breaklines from the TauDEM delineation:
        #     align mesh faces to the thalweg and refine a constant-width corridor.
        #     near=far (uniform fine spacing, no coarsening within the corridor);
        #     near_repeats sized so the refined band ~= the channel width.
        bl_json = ddir / "channel_breakline_ft.json"
        if args.breaklines and bl_json.exists():
            from shapely.geometry import LineString
            bl_defs = json.loads(bl_json.read_text(encoding="utf-8"))
            near = far = float(args.channel_cell_ft)
            near_repeats = max(1, round(args.channel_width_ft / (2.0 * near)))
            GeomStorage.set_breaklines(geom_text, "DebrisFlowArea", [
                {"name": d["name"][:32],
                 "coords": list(LineString(d["coords"]).simplify(
                     args.breakline_simplify_ft, preserve_topology=True).coords),
                 "cell_size_near": near, "cell_size_far": far}
                for d in bl_defs])
            GeomMesh.set_breakline_spacing(str(geom_text), near=near, far=far,
                                           near_repeats=near_repeats, protection_radius=1,
                                           all_breaklines=True)
            print(f"[build] breaklines: {len(bl_defs)} centerline(s), near=far={near} ft, "
                  f"near_repeats={near_repeats}, protection_radius=1")
            # breakline-aware mesh regeneration (.NET EnforceBreaklines + the 8-tier
            # auto-repair of bad faces); recompile_via_rasexe rebuilds the stale HDF.
            mres = GeomMesh.generate(str(geom_text), mesh_name="DebrisFlowArea",
                                     cell_size=float(cell), bl_spacing_near=near,
                                     bl_spacing_far=far, near_repeats=near_repeats,
                                     max_iterations=8, recompile_via_rasexe=True)
            print(f"[build] breakline regen -> status={getattr(mres,'status',None)} "
                  f"pts={getattr(mres,'cell_count',None)}")
            # rebuild the mesh HDF from the new breakline-aware computation points
            cres = RasCmdr.compute_plan("01", force_geompre=True, num_cores=2)
            topo_ok, topo_detail = hdf_has_2d_mesh(geom_hdf)
            print(f"[build] mesh topology (breakline): {topo_ok} ({topo_detail})")

        # 6. associate terrain to the COMPILED geometry HDF, then compute the 2D
        #    property tables (Cells Minimum Elevation, face profiles, ...). This
        #    is what actually puts terrain elevations INTO the mesh — it must run
        #    AFTER the topology HDF exists (the prior bug deleted the HDF after a
        #    pre-compute association, so terrain never reached the mesh).
        GeomMesh.set_geometry_association("01", terrain_hdf_path=str(terrain_hdf))
        pt_ok = GeomMesh.compute_property_tables("01", mesh_name="DebrisFlowArea")
        print(f"[build] compute_property_tables -> {pt_ok}")

        # 7. verify terrain elevations are now in the mesh
        elev = _mesh_elevation_summary(geom_hdf, "DebrisFlowArea")
        ok = elev is not None
        status({"phase": "build", "ok": ok, "topology": topo_detail,
                "property_tables": bool(pt_ok), "elevation_ft": elev,
                "gen_status": getattr(gp, "status", None),
                "terrain_hdf": str(terrain_hdf), "compute_result": str(cres)[:150]})
        print(f"[build] terrain elevations in mesh: {elev}")
        if args.phase == "build":
            return 0 if ok else 1

    if args.phase in ("run", "all"):
        banner("PHASE run — clear-water + Bingham non-Newtonian variants (HEC-RAS)")
        from ras_commander import init_ras_project, RasCmdr
        import shutil

        name = args.project_name
        wd = args.workdir
        geom_hdf = wd / f"{name}.g01.hdf"
        plan_hdf = wd / f"{name}.p01.hdf"
        ddir = args.data_dir or prep
        hyd = json.loads((ddir / "inflow_hydrograph.json").read_text(encoding="utf-8"))
        bcm = json.loads((wd / "bc_meta.json").read_text(encoding="utf-8"))
        cfs, interval = hyd["cfs"], hyd["interval"]

        # clear-water baseline + one Bingham variant per yield stress. The inflow
        # hydrograph stays clear-water; HEC-RAS bulks it internally via Bulk Fluid
        # Volume at Cv (do NOT pre-bulk). BF = 1/(1-Cv); Cv=0.70 -> 3.33x.
        yields = [float(y) for y in str(args.yields).split(",") if y.strip()]
        variants = [("clear", None)] + [
            (f"bingham_ty{int(y)}", {
                "method": 1, "cv": args.cv, "user_yield": y,
                "user_viscosity": args.viscosity_pa, "bulking": 1,
                "max_cv": max(round(args.cv + 0.05, 2), 0.75)})
            for y in yields]

        hh = int(args.sim_hours)
        mm = int(round((args.sim_hours - hh) * 60))
        end = f"01JAN2000,{hh:02d}{mm:02d}"
        bf = 1.0 / (1.0 - args.cv)
        print(f"[run] inflow peak {max(cfs):.0f} cfs (clear); bulked peak "
              f"{max(cfs) * bf:.0f} cfs at Cv={args.cv} (BF={bf:.2f}); "
              f"sim {args.sim_hours} h @{args.comp_interval}; variants={[v[0] for v in variants]}")

        init_ras_project(str(wd), "7.0")
        allres = {}
        for vname, nn in variants:
            # Run HTab=-1: HEC-RAS runs its native geometry preprocessor as part of
            # the run (the unsteady engine reads its own geometry tables; HTab=0
            # fails "re-run the preprocessor"). NN rheology rides in the .u01.
            write_unsteady_2d(
                wd / f"{name}.u01", area="DebrisFlowArea",
                inflow_name=bcm["inflow_name"], hydro_cfs=cfs, interval=interval,
                outflow_name=bcm["outflow_name"], friction_slope=bcm["friction_slope"],
                title=f"Ether Hollow {vname}", nn=nn)
            (wd / f"{name}.p01").write_text(
                f"Plan Title={vname}\nProgram Version=7.00\n"
                "Geom File=g01\nFlow File=u01\nRun HTab=-1\nRun UNet=-1\nRun Sed= 0\n"
                f"Run WQ= 0\nRun PostProcess=-1\nRun RASMapper= 0\nShort ID={vname[:24]}\n"
                f"Simulation Date=01JAN2000,0000,{end}\n"
                f"Computation Interval={args.comp_interval}\nOutput Interval=1MIN\n"
                "Instantaneous Interval=1MIN\nMapping Interval=1MIN\n"
                # 2D equation set: 1 = SWE-ELM (Full Momentum), required for
                # non-Newtonian debris flow; 0 = Diffusion Wave (not applicable).
                f"UNET D2 Equation= {1 if args.equation_set == 'SWE-ELM' else 0} \n",
                encoding="utf-8")
            print(f"\n[run] === variant {vname} (nn={nn}) ===")
            cres = RasCmdr.compute_plan("01", num_cores=2)
            res = _results_summary(plan_hdf, geom_hdf, "DebrisFlowArea")
            inflow = _inflow_volume(plan_hdf, "DebrisFlowArea")
            if res is not None and inflow is not None:
                res = {**res, **inflow}
            try:                                   # persist each variant's plan HDF
                if plan_hdf.exists():
                    shutil.copy2(plan_hdf, wd / f"result_{vname}.p01.hdf")
            except Exception as e:                 # noqa: BLE001
                print(f"[run] WARNING: could not persist {vname} HDF: {e}")
            allres[vname] = res
            status({"phase": "run", "variant": vname, "nn": nn,
                    "mannings_n": args.mannings_n, "cell_size_ft": args.cell_size_ft,
                    "inflow_at": bcm.get("inflow_at", args.inflow_at),
                    "ok": bool(cres) and res is not None, "results": res,
                    "sim_hours": args.sim_hours, "comp_interval": args.comp_interval,
                    "compute_result": str(cres)[:120]})
            print(f"[run] {vname}: {res}")

        print("\n=== variant comparison (max over domain) ===")
        print(f"  {'variant':18s} {'inflowQ':>8} {'maxV(fps)':>9} {'maxD(ft)':>9} "
              f"{'meanD(ft)':>9} {'wet':>6}")
        for vname, res in allres.items():
            if res:
                print(f"  {vname:18s} {res.get('inflow_peak_cfs','-'):>8} "
                      f"{res.get('max_vel_fps','-'):>9} "
                      f"{res.get('max_depth_ft','-'):>9} {res.get('mean_depth_ft','-'):>9} "
                      f"{res.get('wet_cells','-'):>6}")
        return 0 if any(allres.values()) else 1
    return 0


def _sample_terrain_elev(dem_path, pts):
    """Sample the feet terrain (same CRS as the ring) at each (x,y); NaN off-grid."""
    import rasterio
    import numpy as np
    with rasterio.open(dem_path) as ds:
        arr = ds.read(1).astype("float64")
        nd = ds.nodata
        if nd is not None:
            arr[arr == nd] = np.nan
        tf = ds.transform
        H, W = arr.shape
        out = []
        for x, y in pts:
            c, r = ~tf * (float(x), float(y))
            r, c = int(round(r)), int(round(c))
            out.append(float(arr[r, c]) if 0 <= r < H and 0 <= c < W else float("nan"))
    return out


def _pick_bc_segment(ring, elevs, mode, span_ft):
    """Contiguous run of perimeter vertices centred on the highest ('high') or
    lowest ('low') elevation vertex, grown until it spans ~span_ft. Returns the
    ordered [x,y] polyline for a BC line that lies on the domain edge."""
    import numpy as np
    pts = ring[:-1] if ring and list(ring[0]) == list(ring[-1]) else list(ring)
    n = len(pts)
    e = np.asarray(elevs[:n], dtype=float)
    c = 0 if np.all(np.isnan(e)) else int(
        np.nanargmax(e) if mode == "high" else np.nanargmin(e))

    def seglen(idxs):
        return sum(math.hypot(pts[idxs[i + 1]][0] - pts[idxs[i]][0],
                              pts[idxs[i + 1]][1] - pts[idxs[i]][1])
                   for i in range(len(idxs) - 1))

    k = 1
    while True:
        idxs = [(c + j) % n for j in range(-k, k + 1)]
        if seglen(idxs) >= span_ft or (2 * k + 1) >= n:
            break
        k += 1
    return [[float(pts[(c + j) % n][0]), float(pts[(c + j) % n][1])]
            for j in range(-k, k + 1)]


def _pick_bc_segment_near(ring, pt, span_ft):
    """Contiguous perimeter run centred on the vertex nearest point ``pt`` (e.g.
    the basin outlet / fan apex), grown until it spans ~span_ft."""
    pts = ring[:-1] if ring and list(ring[0]) == list(ring[-1]) else list(ring)
    n = len(pts)
    c = min(range(n), key=lambda i: (pts[i][0] - pt[0]) ** 2 + (pts[i][1] - pt[1]) ** 2)

    def seglen(idxs):
        return sum(math.hypot(pts[idxs[i + 1]][0] - pts[idxs[i]][0],
                              pts[idxs[i + 1]][1] - pts[idxs[i]][1])
                   for i in range(len(idxs) - 1))

    k = 1
    while True:
        idxs = [(c + j) % n for j in range(-k, k + 1)]
        if seglen(idxs) >= span_ft or (2 * k + 1) >= n:
            break
        k += 1
    return [[float(pts[(c + j) % n][0]), float(pts[(c + j) % n][1])]
            for j in range(-k, k + 1)]


def _bed_slope(dem_path, outflow_pts, centroid_xy, probe_ft=400.0,
               lo=0.002, hi=0.5, default=0.02):
    """Local bed slope just above the outflow line (Δelev over probe_ft toward
    the domain centroid) — the EG slope for the downstream normal-depth BC."""
    mx = sum(p[0] for p in outflow_pts) / len(outflow_pts)
    my = sum(p[1] for p in outflow_pts) / len(outflow_pts)
    dx, dy = centroid_xy[0] - mx, centroid_xy[1] - my
    d = math.hypot(dx, dy) or 1.0
    up = (mx + dx / d * probe_ft, my + dy / d * probe_ft)
    e_out, e_up = _sample_terrain_elev(dem_path, [(mx, my), up])
    if not (math.isfinite(e_out) and math.isfinite(e_up)):
        return default
    return float(min(hi, max(lo, (e_up - e_out) / probe_ft)))


def _nn_block(nn):
    """Full HEC-RAS Non-Newtonian block for the .u## (templated from a real
    fixture, exact keys incl. the HEC-RAS misspelling 'User Yeild'). nn keys:
    method (1=Bingham), cv, user_yield (Pa), user_viscosity (Pa*s),
    bulking (1=Bulk Fluid Volume), max_cv."""
    # HEC-RAS stores volumetric concentration in PERCENT (70 = 70%), not a
    # fraction. nn['cv'] is kept as a fraction (0.70) for the bulking-factor math;
    # write it ×100 here. (Writing 0.70 makes HEC-RAS read 0.7% -> bulking 1.007×.)
    cv_pct = nn["cv"] * 100.0
    maxcv_pct = nn.get("max_cv", 0.75) * 100.0
    return [
        f"Non-Newtonian Method= {nn['method']} ,",
        f"Non-Newtonian Constant Vol Conc={cv_pct:g}",
        "Non-Newtonian Yield Method= 1 ,",          # User Yield
        "Non-Newtonian Yield Coef=0, 0",
        f"User Yeild=   {nn['user_yield']}",          # sic: HEC-RAS key is misspelled
        "Non-Newtonian Sed Visc= 2 ,",               # User Defined Viscosity
        "Non-Newtonian Obrian B=0",
        f"User Viscosity={nn['user_viscosity']}",
        "User Viscosity Ratio=0",
        "Herschel-Bulkley Coef=0, 0",
        "Clastic Method= 0 ,",
        "Coulomb Phi=0",
        "Non-Newtonian Hindered FV= 0",
        "Non-Newtonian FV K=0",
        "Non-Newtonian ds=0",
        f"Non-Newtonian Max Cv={maxcv_pct:g}",
        f"Non-Newtonian Bulking Method= {nn['bulking']} ,",
        "Non-Newtonian High C Transport= 0 ,",
        "Viscosity=1000,,,",
    ]


def write_unsteady_2d(path, area, inflow_name, hydro_cfs, interval,
                      outflow_name, friction_slope, title="Clear Water", nn=None):
    """Hand-author a greenfield 2D unsteady flow file (.u##): one Flow Hydrograph
    inflow BC + one Normal Depth outflow BC. ras-commander has no Boundary
    Location= block creator, so emit the HEC-RAS text directly. The 2D Boundary
    Location format is 9 comma fields: field 6 = 2D area, field 8 = BC line."""
    def loc(bcname):
        f = [f"{'':<16}", f"{'':<16}", f"{'':<8}", f"{'':<8}", f"{'':<16}",
             f"{area:<16}", f"{'':<16}", f"{bcname:<32}", f"{'':<32}"]
        return "Boundary Location=" + ",".join(f)

    L = [f"Flow Title={title}", "Program Version=7.00",
         "BEGIN FILE DESCRIPTION:", "END FILE DESCRIPTION:", "Use Restart= 0 "]
    L.append(loc(inflow_name))
    L.append(f"Interval={interval}")
    L.append(f"Flow Hydrograph= {len(hydro_cfs)} ")
    for i in range(0, len(hydro_cfs), 10):
        L.append("".join(f"{float(v):8.2f}" for v in hydro_cfs[i:i + 10]))
    L += ["Stage Hydrograph TW Check=0", "Flow Hydrograph Slope= 0 ",
          "DSS Path=", "Use DSS=False", "Use Fixed Start Time=False",
          "Fixed Start Date/Time=,", "Is Critical Boundary=False",
          "Critical Boundary Flow="]
    L.append(loc(outflow_name))
    L.append(f"Friction Slope={friction_slope:.5f},0")
    if nn:
        L += _nn_block(nn)   # global rheology block (mud/debris flow)
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def _inflow_volume(plan_hdf, area):
    """Realized inflow (peak cfs, volume m3) from the BC flow-per-face time series
    — a mass-balance QA: bulked NN runs should show ~1/(1-Cv)x the clear volume."""
    import h5py
    import numpy as np
    tsb = ("Results/Unsteady/Output/Output Blocks/Base Output/"
           f"Unsteady Time Series/2D Flow Areas/{area}/Boundary Conditions")
    try:
        with h5py.File(plan_hdf, "r") as f:
            fpf = f.get(f"{tsb}/Inflow - Flow per Face")
            if fpf is None:
                return None
            tot = np.abs(np.asarray(fpf[:], float)).sum(axis=1)
            vol = float(np.sum((tot[:-1] + tot[1:]) / 2.0) * 60.0) * 0.0283168  # 1-min->m3
            return {"inflow_peak_cfs": round(float(tot.max()), 1),
                    "inflow_vol_m3": round(vol)}
    except Exception as e:  # noqa: BLE001
        print(f"[run] WARNING: inflow-volume read failed: {e}")
        return None


def _results_summary(plan_hdf, geom_hdf, area):
    """Max WSE / depth / velocity for the 2D area from the plan HDF. Returns None
    if the run produced no 2D results (failed or went unstable)."""
    import h5py
    import numpy as np
    if not Path(plan_hdf).exists():
        print(f"[run] WARNING: plan HDF missing: {plan_hdf}")
        return None
    try:
        with h5py.File(plan_hdf, "r") as f:
            base = ("Results/Unsteady/Output/Output Blocks/Base Output/"
                    f"Summary Output/2D Flow Areas/{area}")
            grp = f.get(base)
            if grp is None:
                print(f"[run] WARNING: no 2D summary results at {base}")
                parent = f.get("Results/Unsteady/Output/Output Blocks/"
                               "Base Output/Summary Output/2D Flow Areas")
                if parent is not None:
                    print("[run] available 2D area result groups:", list(parent.keys()))
                return None

            def maxrow(ds):
                a = grp.get(ds)
                if a is None:
                    return None
                a = a[:]
                return a[0] if a.ndim == 2 else a   # (2,N) = [value, time]

            out = {}
            ws = maxrow("Maximum Water Surface")
            if ws is not None:
                wf = ws[np.isfinite(ws)]
                if wf.size:
                    out["max_ws_ft"] = round(float(wf.max()), 2)
                with h5py.File(geom_hdf, "r") as g:
                    el = g.get(f"Geometry/2D Flow Areas/{area}/Cells Minimum Elevation")
                    if el is not None:
                        el = el[:]
                        n = min(len(ws), len(el))
                        depth = ws[:n] - el[:n]
                        depth = depth[np.isfinite(depth) & (depth > 0.0)]
                        if depth.size:
                            out["max_depth_ft"] = round(float(depth.max()), 2)
                            out["mean_depth_ft"] = round(float(depth.mean()), 2)
                            out["wet_cells"] = int(depth.size)
            vel = maxrow("Maximum Face Velocity")
            if vel is None:
                vel = maxrow("Maximum Velocity")
            if vel is not None:
                vf = vel[np.isfinite(vel)]
                if vf.size:
                    out["max_vel_fps"] = round(float(vf.max()), 2)
            return out or None
    except Exception as e:
        print(f"[run] WARNING: results read failed: {e}")
        return None


def _mesh_elevation_summary(geom_hdf: Path, area: str):
    """Return {min,max,mean} of 'Cells Minimum Elevation' (ft) or None if absent."""
    import h5py
    import numpy as np
    if not geom_hdf.exists():
        return None
    try:
        with h5py.File(geom_hdf, "r") as f:
            d = f.get(f"Geometry/2D Flow Areas/{area}/Cells Minimum Elevation")
            if d is None:
                return None
            a = d[:]
            a = a[np.isfinite(a)]
            if a.size == 0:
                return None
            return {"min": round(float(a.min()), 1), "max": round(float(a.max()), 1),
                    "mean": round(float(a.mean()), 1), "n": int(a.size)}
    except Exception as e:
        # distinguish a genuine read failure from "dataset absent" (which
        # returns None above) so a locked/partial HDF isn't misread as
        # "terrain not in mesh" and silently fails the build.
        print(f"[build] WARNING: Cells Minimum Elevation read failed: {e}")
        return None


def hdf_has_2d_mesh(geom_hdf: Path):
    """Return (ok, detail): a 2D Flow Areas group with cells exists."""
    import h5py
    if not geom_hdf.exists():
        return False, f"{geom_hdf.name} missing"
    try:
        with h5py.File(geom_hdf, "r") as f:
            grp = f.get("Geometry/2D Flow Areas")
            if grp is None:
                return False, "no '2D Flow Areas' group"
            areas = [k for k in grp.keys() if isinstance(grp[k], h5py.Group)]
            if not areas:
                return False, "no area subgroups"
            tot = 0
            det = []
            for a in areas:
                cc = grp.get(f"{a}/Cells Center Coordinate")
                n = 0 if cc is None else cc.shape[0]
                tot += n
                det.append(f"{a}:{n} cells")
            return tot > 0, "; ".join(det)
    except Exception as e:
        return False, f"HDF read error: {e}"


if __name__ == "__main__":
    import sys
    try:
        sys.exit(main())
    except Exception:
        import traceback
        banner("ERROR")
        traceback.print_exc()
        sys.exit(2)
