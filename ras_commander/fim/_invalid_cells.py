"""Physical 2D cells whose boundary rings are not valid polygons.

HEC-RAS can compute a mesh in which a face polyline crosses another face of
the same cell (a "bowtie"). Strict polygon assembly refuses the whole mesh.
Mapping instead assembles the mesh non-strictly, rebuilds each omitted cell
from its own face polylines and applies an explicit policy:

- ``"repair"``: polygonize the noded face polylines, remove area already
  owned by valid cells and keep the largest remaining part as the ownership
  polygon (ties go to the lower-left part).
- ``"hull"``: the convex hull of the face points, with the same overlap
  removal and largest-part selection.
- ``"omit"``: the cell owns no pixels.
- ``"raise"``: refuse when an invalid cell can contribute to the requested
  output (no AOI, or an AOI intersecting the cell's face-point hull).

A crossing face also distorts the cells on its other side. Overlaps among the
valid cells touching an invalid cell's hull, and among every cell connected to
them through further overlaps, are resolved in ascending cell-ID order: each
cell loses the area of lower-ID cells it overlaps. A cell split by that
subtraction keeps every piece (one ownership row per piece, same address); a
cell left with no area owns no pixels.

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


def _polygon_parts(geometry):
    """Positive-area Polygon parts, by descending area, then lower-left."""
    import shapely

    parts = [part for part in shapely.get_parts(geometry)
             if part.geom_type == "Polygon" and part.area > 0]
    return sorted(parts, key=lambda part: (-part.area, part.bounds[0], part.bounds[1]))


def _largest_polygon(geometry):
    parts = _polygon_parts(geometry)
    return parts[0] if parts else None


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


def load_cells(hdf_path, *, policy, threads):
    """Native cell polygons with invalid cells handled by ``policy``.

    Returns the GeoDataFrame and a list of records. A cell split by overlap
    resolution appears as several Polygon rows with the same ``mesh_name`` and
    ``cell_id``. Records carry ``mesh``, ``cell_id``, ``reason``, ``action``,
    ``original_area``, ``fallback_area`` (mapped area; ``None`` when an invalid
    cell is omitted, ``0.0`` when a valid cell is consumed), ``pieces`` and
    ``overlap_with`` (lower-ID cells that kept shared area). ``extent``
    (internal; removed by :func:`describe`) is the area used for AOI scoping.
    """
    import geopandas as gpd
    import h5py
    import pandas as pd
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
                         pieces=0, overlap_with=[], extent=None)
            if lines:
                entry["extent"] = MultiPoint(np.concatenate(lines)).convex_hull
                entry["original_area"] = float(_candidate(lines, "repair").area)
                if policy in ("repair", "hull"):
                    substitutes[(mesh, cell_id)] = _candidate(lines, policy)
            records.append(entry)
    cells = cells.reset_index(drop=True)
    original = cells.geometry.to_numpy()
    geometries = original.copy()
    meshes = cells["mesh_name"].to_numpy()
    ids = cells["cell_id"].to_numpy().astype(np.int64)
    index = cells.sindex
    order = {name: i for i, name in enumerate(dict.fromkeys(
        list(meshes) + [record["mesh_name"] for record in invalid]))}

    def rank(i):
        return order[meshes[i]], int(ids[i])

    def overlapping(i):
        found = []
        for j in np.sort(index.query(original[i], predicate="intersects")):
            j = int(j)
            if j != i and meshes[j] == meshes[i] and shapely.area(
                    shapely.intersection(original[i], original[j])) > 0:
                found.append(j)
        return found

    # Valid cells touching an invalid cell's hull, then every cell connected
    # to them through positive-area overlaps.
    pending = sorted({int(i) for e in records if e["extent"] is not None
                      for i in index.query(e["extent"], predicate="intersects")
                      if meshes[i] == e["mesh"]}, key=rank)
    partners, seen = {}, set(pending)
    while pending:
        i = pending.pop(0)
        partners[i] = overlapping(i)
        for j in partners[i]:
            if j not in seen:
                seen.add(j)
                pending.append(j)
    trimmed = {}
    for i in sorted(partners, key=rank):
        lower = [j for j in partners[i] if rank(j) < rank(i)]
        if not lower:
            continue
        # Lower-ID geometries are already final; a consumed one owns nothing.
        winners = [geometries[j] for j in lower if geometries[j] is not None]
        remainder = (shapely.difference(original[i], shapely.union_all(winners))
                     if winners else original[i])
        parts = _polygon_parts(remainder)
        if len(parts) > 1:
            geometries[i] = shapely.MultiPolygon(parts)
        else:
            geometries[i] = parts[0] if parts else None
        trimmed[i] = dict(
            mesh=meshes[i], cell_id=int(ids[i]),
            reason="overlaps a lower-ID cell next to an invalid cell",
            action="overlap_trimmed" if parts else "overlap_consumed",
            original_area=float(original[i].area),
            fallback_area=float(sum(part.area for part in parts)),
            pieces=len(parts), overlap_with=sorted(int(ids[j]) for j in lower),
            extent=original[i],
        )
    # Invalid cells take only area no valid cell owns, in cell-ID order.
    additions = []
    for entry in records:
        shape = substitutes.get((entry["mesh"], entry["cell_id"]))
        if shape is None:
            continue
        occupied = [geometries[i] for i in np.sort(index.query(shape, predicate="intersects"))
                    if meshes[i] == entry["mesh"] and geometries[i] is not None]
        occupied += [g for m, g in additions if m == entry["mesh"] and g.intersects(shape)]
        if occupied:
            shape = shapely.difference(shape, shapely.union_all(occupied))
        shape = _largest_polygon(shape)
        if shape is None or not shape.is_valid:
            continue
        additions.append((entry["mesh"], shape))
        entry.update(action="repaired" if policy == "repair" else "convex_hull",
                     fallback_area=float(shape.area), pieces=1, _geometry=shape)
    keep = np.array([g is not None for g in geometries], dtype=bool)
    rows = gpd.GeoDataFrame(
        {"mesh_name": meshes[keep], "cell_id": cells["cell_id"].to_numpy()[keep]},
        geometry=list(geometries[keep]), crs=cells.crs,
    )
    extra = [dict(mesh_name=e["mesh"], cell_id=e["cell_id"], geometry=e.pop("_geometry"))
             for e in records if "_geometry" in e]
    if extra:
        extra = gpd.GeoDataFrame(extra, geometry="geometry", crs=cells.crs)
        extra["cell_id"] = extra["cell_id"].astype(cells["cell_id"].dtype)
        rows = pd.concat([rows, extra], ignore_index=True)
    # One Polygon row per ownership piece, in mesh/cell-ID order.
    rows = rows.explode(index_parts=False, ignore_index=True)
    stride = int(rows["cell_id"].max()) + 1 if len(rows) else 1
    position = rows["mesh_name"].map(order).to_numpy() * stride + rows["cell_id"].to_numpy()
    rows = rows.iloc[np.argsort(position, kind="stable")].reset_index(drop=True)
    cells = gpd.GeoDataFrame(rows, geometry="geometry", crs=cells.crs)
    return cells, records + [trimmed[k] for k in sorted(trimmed, key=rank)]


def require_cells(cells, records, policy):
    """Refuse an empty ownership set, naming invalid cells when they caused it."""
    if not cells.empty:
        return
    if records:
        listed = ", ".join(f"{r['mesh']} cell {r['cell_id']} ({r['action']})" for r in records[:10])
        raise ValueError(
            "sloping mapping has no physical 2D cell polygons left under "
            f"invalid_cells={policy!r}: {listed}"
        )
    raise ValueError("sloping mapping requires physical 2D cell polygons")


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
