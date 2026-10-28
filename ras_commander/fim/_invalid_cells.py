"""Physical 2D cells whose boundary rings are not valid polygons.

HEC-RAS can compute a mesh in which a face polyline crosses another face of
the same cell (a "bowtie"). Strict polygon assembly refuses the whole mesh.
Mapping instead assembles the mesh non-strictly, rebuilds each omitted cell
from its own face polylines and applies an explicit policy:

- ``"repair"``: polygonize the noded face polylines (the regions RAS Mapper's
  polygon fill covers), remove area already owned by valid cells and keep the
  largest remaining part as the ownership polygon.
- ``"hull"``: the convex hull of the face points, with the same overlap
  removal and largest-part selection.
- ``"omit"``: the cell owns no pixels.
- ``"raise"``: refuse when an invalid cell can contribute to the requested
  output (no AOI, or an AOI intersecting the cell's face-point hull).

Hydraulic stencils, connectivity and corner reconstruction always use the
complete HDF topology; only pixel ownership changes.
"""

import numpy as np

POLICIES = ("repair", "hull", "omit", "raise")
DEFAULT_POLICY = "repair"


def validate_policy(policy):
    if policy not in POLICIES:
        raise ValueError(f"invalid_cells must be one of {', '.join(map(repr, POLICIES))}")
    return policy


def _face_lines(group, faces):
    """Face polylines of one cell, in HDF face order, from the raw arrays."""
    points = group["FacePoints Coordinate"]
    endpoints = group["Faces FacePoint Indexes"]
    perimeter_info = group["Faces Perimeter Info"]
    perimeter = group["Faces Perimeter Values"]
    lines = []
    for face in map(int, faces):
        a, b = map(int, endpoints[face, :2])
        offset, inner = map(int, perimeter_info[face, :2])
        coords = [points[a]]
        if inner > 0:
            coords.extend(perimeter[offset:offset + inner])
        coords.append(points[b])
        lines.append(np.asarray(coords, dtype=np.float64))
    return lines


def _largest_polygon(geometry):
    import shapely

    parts = [part for part in shapely.get_parts(geometry)
             if part.geom_type == "Polygon" and part.area > 0]
    return max(parts, key=lambda part: part.area) if parts else None


def _candidate(lines, policy):
    import shapely
    from shapely.geometry import LineString, MultiPoint
    from shapely.ops import polygonize

    if policy == "hull":
        return MultiPoint(np.concatenate(lines)).convex_hull
    noded = shapely.node(shapely.MultiLineString([LineString(line) for line in lines]))
    return shapely.union_all(list(polygonize(shapely.get_parts(noded))))


def _reason(record, lines):
    """Reference reason code plus the GEOS validity explanation of the face ring."""
    code = record.get("reason_code") or "no_polygon"
    if len(lines) < 1 or sum(len(line) - 1 for line in lines) < 3:
        return code
    from shapely.geometry import Polygon
    from shapely.validation import explain_validity

    chain = [lines[0]]
    for line in lines[1:]:
        # Orient each face polyline to continue from the previous end point.
        end = chain[-1][-1]
        chain.append(line if np.linalg.norm(line[0] - end) <= np.linalg.norm(line[-1] - end)
                     else line[::-1])
    ring = np.concatenate([line[:-1] for line in chain])
    explanation = explain_validity(Polygon(ring))
    if explanation == "Valid Geometry":
        # The chained ring can be simple while the HDF face order is not.
        explanation = "face polylines touch or cross out of ring order"
    return f"{code}: {explanation}"


def _invalid_records(cells):
    records = cells.attrs.get("cell_polygon_diagnostics", ())
    return [record for record in records if record.get("status") == "omitted"]


def load_cells(hdf_path, *, policy, threads, _overlap_rule="lower_id"):
    """Native cell polygons with invalid cells handled by ``policy``.

    Returns the GeoDataFrame and a list of records. Invalid cells carry
    ``mesh``, ``cell_id``, ``reason``, ``action`` (``repaired``,
    ``convex_hull`` or ``omitted``), ``original_area`` (polygonized face
    area), ``fallback_area`` (``None`` unless a polygon was substituted) and
    ``overlap_with``. A crossing face also distorts the cells on its other
    side, so valid cells touching an invalid cell's face-point hull that
    overlap another cell are trimmed (``action="overlap_trimmed"``); the
    lower cell ID keeps the shared area. ``extent`` (internal; removed by
    :func:`describe`) is the hull used for AOI scoping.
    """
    import h5py
    import shapely
    from shapely.geometry import MultiPoint

    from .. import HdfMesh
    from ..fast_hdf import backend_scope

    validate_policy(policy)
    with backend_scope("rust"):
        cells = HdfMesh.get_mesh_cell_polygons(
            hdf_path, strict=False, engine="native", threads=threads, diagnostics=True
        )
    invalid = _invalid_records(cells)
    cells.attrs.pop("cell_polygon_diagnostics", None)
    if not invalid:
        return cells, []
    records, substitutes = [], {}
    with h5py.File(hdf_path, "r") as hdf:
        for record in sorted(invalid, key=lambda r: (r["mesh_name"], int(r["cell_id"]))):
            mesh, cell_id = record["mesh_name"], int(record["cell_id"])
            lines = _face_lines(hdf[f"Geometry/2D Flow Areas/{mesh}"], record.get("face_ids", ()))
            entry = dict(mesh=mesh, cell_id=cell_id, reason=_reason(record, lines),
                         action="omitted", original_area=None, fallback_area=None,
                         overlap_with=[], extent=None)
            if lines:
                entry["extent"] = MultiPoint(np.concatenate(lines)).convex_hull
                entry["original_area"] = float(_candidate(lines, "repair").area)
                if policy in ("repair", "hull"):
                    substitutes[(mesh, cell_id)] = _candidate(lines, policy)
            records.append(entry)
    cells = cells.reset_index(drop=True)
    geometries = cells.geometry.to_numpy().copy()
    keys = list(zip(cells["mesh_name"], cells["cell_id"].astype(int)))
    index = cells.sindex
    # Valid cells touching an invalid cell's hull, and every cell overlapping them.
    trimmed = {}
    for entry in records:
        if entry["extent"] is None:
            continue
        for i in index.query(entry["extent"], predicate="intersects"):
            if keys[i][0] != entry["mesh"]:
                continue
            for j in index.query(geometries[i], predicate="intersects"):
                if i == j or keys[j][0] != keys[i][0]:
                    continue
                overlap = shapely.intersection(geometries[i], geometries[j])
                if shapely.area(overlap) <= 0:
                    continue
                lower, upper = sorted((i, j), key=lambda k: keys[k][1])
                loser = upper if _overlap_rule == "lower_id" else lower
                winner = lower if loser == upper else upper
                shape = _largest_polygon(shapely.difference(geometries[loser], geometries[winner]))
                if shape is None:
                    continue
                if loser not in trimmed:
                    trimmed[loser] = dict(
                        mesh=keys[loser][0], cell_id=keys[loser][1],
                        reason="overlaps a neighbouring cell next to an invalid cell",
                        action="overlap_trimmed", original_area=float(geometries[loser].area),
                        fallback_area=None, overlap_with=[], extent=geometries[loser],
                    )
                trimmed[loser]["overlap_with"].append(int(keys[winner][1]))
                geometries[loser] = shape
    for k, entry in trimmed.items():
        entry["fallback_area"] = float(geometries[k].area)
        entry["overlap_with"] = sorted(set(entry["overlap_with"]))
    # Invalid cells take only area no valid cell owns, in cell-ID order.
    additions = []
    for entry in records:
        shape = substitutes.get((entry["mesh"], entry["cell_id"]))
        if shape is None:
            continue
        owners = [i for i in index.query(shape, predicate="intersects")
                  if keys[i][0] == entry["mesh"]]
        occupied = [geometries[i] for i in owners]
        occupied += [g for m, g in additions if m == entry["mesh"] and g.intersects(shape)]
        if occupied:
            shape = shapely.difference(shape, shapely.union_all(occupied))
        shape = _largest_polygon(shape)
        if shape is None or not shape.is_valid:
            continue
        additions.append((entry["mesh"], shape))
        entry["action"] = "repaired" if policy == "repair" else "convex_hull"
        entry["fallback_area"] = float(shape.area)
        entry["_geometry"] = shape
    cells = cells.set_geometry(geometries, crs=cells.crs)
    rows = [dict(mesh_name=e["mesh"], cell_id=e["cell_id"], geometry=e.pop("_geometry"))
            for e in records if "_geometry" in e]
    if rows:
        import geopandas as gpd
        import pandas as pd

        extra = gpd.GeoDataFrame(rows, geometry="geometry", crs=cells.crs)
        extra["cell_id"] = extra["cell_id"].astype(cells["cell_id"].dtype)
        order = {name: i for i, name in enumerate(pd.unique(cells["mesh_name"]))}
        merged = pd.concat([cells, extra], ignore_index=True)
        merged = merged.sort_values(
            ["mesh_name", "cell_id"],
            key=lambda s: s.map(order) if s.name == "mesh_name" else s,
            kind="stable",
        ).reset_index(drop=True)
        cells = gpd.GeoDataFrame(merged, geometry="geometry", crs=cells.crs)
    return cells, records + [trimmed[k] for k in sorted(trimmed, key=lambda k: keys[k])]


def check_scope(records, policy, aoi_geometry):
    """Refuse ``"raise"`` only when an invalid cell can affect the output."""
    if policy != "raise" or not records:
        return
    from ..hdf.HdfMesh import MeshCellPolygonError

    hits = [r for r in records if aoi_geometry is None or r["extent"] is None
            or r["extent"].intersects(aoi_geometry)]
    if hits:
        listed = ", ".join(f"{r['mesh']} cell {r['cell_id']}" for r in hits[:10])
        raise MeshCellPolygonError(
            f"Invalid 2D cell polygons intersect the requested output ({listed}; {hits[0]['reason']}). "
            "Pass invalid_cells='repair', 'hull' or 'omit' to map without them, or an AOI that "
            "excludes them."
        )


def describe(records, policy, aoi_geometry):
    """The manifest ``invalid_cells`` record (``fim-invalid-cells/1``)."""
    cells = []
    for record in records:
        entry = {key: value for key, value in record.items() if key != "extent"}
        entry["intersects_aoi"] = (
            None if aoi_geometry is None or record["extent"] is None
            else bool(record["extent"].intersects(aoi_geometry))
        )
        cells.append(entry)
    return dict(schema="fim-invalid-cells/1", policy=policy, count=len(cells), cells=cells)
