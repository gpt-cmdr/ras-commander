"""Exact selected-cell topology construction for owned geometry HDF copies.

No result groups are read, no cells are added or removed from the explicit
selection, and no parent hydraulic property table is accepted as recomputed.
Perimeter face incidence is ordered from the outgoing to incoming boundary
face so native serialization retains packed adjacency record counts.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import h5py
import numpy as np


@dataclass
class _Subset:
    cell_src: (
        np.ndarray
    )  # child cell -> source cell; ghost rows identify the source neighbour
    face_src: np.ndarray  # child face -> parent face
    face_swap: np.ndarray  # bool per child face: c0/c1 swapped relative to the parent
    fp_src: np.ndarray  # child facepoint -> parent facepoint
    n_real: int
    tables: dict  # dataset name (under the area group) -> array
    perimeter: np.ndarray  # (k, 2) CCW ring


def _ragged(info: np.ndarray, values: np.ndarray, i: int) -> np.ndarray:
    s, c = info[i]
    if s < 0 or c < 0 or s + c > len(values):
        raise ValueError("Source mesh has an invalid packed table span")
    return values[s : s + c]


def _pack(lists: list[np.ndarray], width: int, dtype) -> tuple[np.ndarray, np.ndarray]:
    counts = np.array([len(x) for x in lists], dtype=np.int32)
    starts = np.zeros(len(lists), dtype=np.int32)
    if len(lists) > 1:
        starts[1:] = np.cumsum(counts)[:-1]
    info = np.stack([starts, counts], axis=1).astype(np.int32)
    if width == 1:
        vals = np.concatenate(lists).astype(dtype) if lists else np.zeros(0, dtype)
    else:
        vals = (
            np.concatenate(lists).astype(dtype)
            if lists
            else np.zeros((0, width), dtype)
        )
    return info, vals


def _build_subset(g: h5py.Group, keep: np.ndarray) -> _Subset:
    """Rebuild the mesh tables of area group ``g`` for kept real parent cells ``keep``."""
    cc = g["Cells Center Coordinate"][:]
    n_all = len(cc)
    fci = g["Faces Cell Indexes"][:]
    ffp = g["Faces FacePoint Indexes"][:]
    # Real cells precede ghosts; ghosts are exactly the c1 cells of perimeter faces.
    n_real = n_all - int((fci[:, 1] >= fci[:, 0].max() + 1).sum())
    if not (n_real == fci[:, 0].max() + 1 and keep.shape == (n_real,)):
        raise ValueError("Source mesh topology is inconsistent")
    fp_xy = g["FacePoints Coordinate"][:]
    if not (keep.any()):
        raise ValueError("Source mesh topology is inconsistent")

    is_ghost_c1 = fci[:, 1] >= n_real
    c0k = keep[fci[:, 0]]
    c1k = np.zeros(len(fci), bool)
    c1k[~is_ghost_c1] = keep[fci[~is_ghost_c1, 1]]
    face_keep = c0k | c1k
    face_src = np.where(face_keep)[0]
    new_face = -np.ones(len(fci), np.int64)
    new_face[face_src] = np.arange(len(face_src))
    swap = (~c0k & c1k)[face_src]
    perim = ((c0k ^ c1k) | (c0k & is_ghost_c1))[face_src]

    real_src = np.where(keep)[0]
    n_child_real = len(real_src)
    new_cell = -np.ones(n_all, np.int64)
    new_cell[real_src] = np.arange(n_child_real)
    # ghosts in child face order
    perim_faces = np.where(perim)[0]  # child face ids
    ghost_id = n_child_real + np.arange(len(perim_faces))
    ghost_of_face = -np.ones(len(face_src), np.int64)
    ghost_of_face[perim_faces] = ghost_id
    # Source neighbour on the other side of each new perimeter face.
    pf = face_src[perim_faces]
    other = np.where(swap[perim_faces], fci[pf, 0], fci[pf, 1])
    cell_src = np.concatenate([real_src, other])

    # faces
    f_cells = np.empty((len(face_src), 2), np.int64)
    f_fp = ffp[face_src].copy()
    for k, pfi in enumerate(face_src):
        c0, c1 = fci[pfi]
        if swap[k]:
            c0, c1 = c1, c0
            f_fp[k] = f_fp[k][::-1]
        a = new_cell[c0]
        b = ghost_of_face[k] if perim[k] else new_cell[c1]
        f_cells[k] = (a, b)
    if not ((f_cells >= 0).all()):
        raise ValueError("Source mesh topology is inconsistent")
    fp_src = np.unique(f_fp.ravel())
    new_fp = -np.ones(len(fp_xy), np.int64)
    new_fp[fp_src] = np.arange(len(fp_src))
    f_fp = new_fp[f_fp]

    t = {}
    t["Faces Cell Indexes"] = f_cells.astype(np.int32)
    t["Faces FacePoint Indexes"] = f_fp.astype(np.int32)
    nv = g["Faces NormalUnitVector and Length"][:][face_src].copy()
    nv[swap, 0:2] *= -1
    t["Faces NormalUnitVector and Length"] = nv
    for name in ("Faces Low Elevation Centroid", "Faces Minimum Elevation"):
        t[name] = g[name][:][face_src]
    # ragged face tables
    for base, width, rev in (
        ("Faces Area Elevation", 4, False),
        ("Faces Perimeter", 2, True),
    ):
        info, vals = g[base + " Info"][:], g[base + " Values"][:]
        lists = []
        for k, pfi in enumerate(face_src):
            v = _ragged(info, vals, pfi)
            lists.append(v[::-1] if (rev and swap[k]) else v)
        t[base + " Info"], t[base + " Values"] = _pack(lists, width, vals.dtype)

    # cells: real rows keep their parent order of faces/facepoints
    cfo_i, cfo_v = (
        g["Cells Face and Orientation Info"][:],
        g["Cells Face and Orientation Values"][:],
    )
    cfp = g["Cells FacePoint Indexes"][:]
    lists, cfp_rows = [], []
    for c in real_src:
        v = _ragged(cfo_i, cfo_v, c)
        if (
            len(v) < 3
            or len(np.unique(v[:, 0])) != len(v)
            or np.any(v[:, 0] < 0)
            or np.any(v[:, 0] >= len(fci))
        ):
            raise ValueError("Selected source cell has invalid face incidence")
        if not np.all(np.any(fci[v[:, 0]] == c, axis=1)):
            raise ValueError("Selected source cell/face incidence is not reciprocal")
        nf = new_face[v[:, 0]]
        if not ((nf >= 0).all()):
            raise ValueError("Source mesh topology is inconsistent")
        orient = np.where(t["Faces Cell Indexes"][nf, 0] == new_cell[c], 1, -1)
        lists.append(np.stack([nf, orient], axis=1))
        row = cfp[c].copy()
        vertex_ids = row[row >= 0]
        if (
            len(vertex_ids) < 3
            or len(np.unique(vertex_ids)) != len(vertex_ids)
            or np.any(vertex_ids >= len(new_fp))
            or np.any(new_fp[vertex_ids] < 0)
        ):
            raise ValueError("Selected source cell has invalid facepoint incidence")
        from shapely.geometry import Polygon

        polygon = Polygon(fp_xy[vertex_ids])
        if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
            raise ValueError("Selected source cell polygon is invalid")
        row[row >= 0] = new_fp[row[row >= 0]]
        cfp_rows.append(row)
    for k in perim_faces:
        lists.append(np.array([[k, -1]]))
        row = -np.ones(cfp.shape[1], np.int64)
        row[:2] = t["Faces FacePoint Indexes"][k]
        cfp_rows.append(row)
    t["Cells Face and Orientation Info"], t["Cells Face and Orientation Values"] = (
        _pack(lists, 2, np.int32)
    )
    t["Cells FacePoint Indexes"] = np.array(cfp_rows, np.int32)

    # cell centers / scalars; ghost: midpoint of face polyline, NaN elevation, area 0
    fxy = g["FacePoints Coordinate"][:][fp_src]
    t["FacePoints Coordinate"] = fxy
    gxy = 0.5 * (
        fxy[t["Faces FacePoint Indexes"][perim_faces, 0]]
        + fxy[t["Faces FacePoint Indexes"][perim_faces, 1]]
    )
    t["Cells Center Coordinate"] = np.concatenate([cc[real_src], gxy])
    for name in (
        "Cells Minimum Elevation",
        "Cells Surface Area",
        "Cells Center Manning's n",
    ):
        if name in g:
            src = g[name][:]
            ghost_val = (
                np.nan
                if name == "Cells Minimum Elevation"
                else src[n_real:].flat[0]
                if len(src) > n_real
                else 0
            )
            t[name] = np.concatenate(
                [src[real_src], np.full(len(perim_faces), ghost_val, src.dtype)]
            )
    vi, vv = g["Cells Volume Elevation Info"][:], g["Cells Volume Elevation Values"][:]
    lists = [_ragged(vi, vv, c) for c in real_src] + [np.zeros((0, 2), vv.dtype)] * len(
        perim_faces
    )
    t["Cells Volume Elevation Info"], t["Cells Volume Elevation Values"] = _pack(
        lists, 2, vv.dtype
    )
    # ghosts in the parent point their Info start at the end of Values
    t["Cells Volume Elevation Info"][n_child_real:, 0] = len(
        t["Cells Volume Elevation Values"]
    )

    # facepoints: incident faces and cells, CCW by angle
    fp_faces = defaultdict(list)
    for k, (p0, p1) in enumerate(t["Faces FacePoint Indexes"]):
        fp_faces[p0].append((k, -1))
        fp_faces[p1].append((k, 1))
    cxy = t["Cells Center Coordinate"]
    fo_lists, ci_lists = [], []
    for p in range(len(fp_src)):
        items = fp_faces[p]
        ks = np.array([k for k, _ in items])
        other = np.where(
            np.array([o for _, o in items]) == -1,
            t["Faces FacePoint Indexes"][ks, 1],
            t["Faces FacePoint Indexes"][ks, 0],
        )
        ang = np.arctan2(fxy[other, 1] - fxy[p, 1], fxy[other, 0] - fxy[p, 0])
        order = np.argsort(ang)
        ordered = np.array(items)[order]
        boundary = [int(k) for k in ks if perim[k]]
        if boundary:
            outgoing = [k for k in boundary if t["Faces FacePoint Indexes"][k, 0] == p]
            incoming = [k for k in boundary if t["Faces FacePoint Indexes"][k, 1] == p]
            if not (len(outgoing) == len(incoming) == 1):
                raise ValueError("nonmanifold boundary point")
            first = int(np.flatnonzero(ordered[:, 0] == outgoing[0])[0])
            ordered = np.roll(ordered, -first, axis=0)
            if not (ordered[-1, 0] == incoming[0]):
                raise ValueError("boundary incident-face ordering")
        fo_lists.append(ordered)
        cells = np.unique(t["Faces Cell Indexes"][ks].ravel())
        cang = np.arctan2(cxy[cells, 1] - fxy[p, 1], cxy[cells, 0] - fxy[p, 0])
        ci_lists.append(cells[np.argsort(cang)])
    (
        t["FacePoints Face and Orientation Info"],
        t["FacePoints Face and Orientation Values"],
    ) = _pack(fo_lists, 2, np.int32)
    t["FacePoints Cell Info"], t["FacePoints Cell Index Values"] = _pack(
        ci_lists, 1, np.int32
    )
    isp = np.zeros(len(fp_src), np.int32)
    isp[np.unique(t["Faces FacePoint Indexes"][perim_faces].ravel())] = -1
    t["FacePoints Is Perimeter"] = isp

    # perimeter ring: walk perimeter faces fp0 -> fp1 (interior on the left: CCW)
    nxt = {int(t["Faces FacePoint Indexes"][k, 0]): int(k) for k in perim_faces}
    if not (len(nxt) == len(perim_faces)):
        raise ValueError("pinch point survived")
    start = int(perim_faces[0])
    ring, k, seen = [], start, 0
    pinfo, pvals = t["Faces Perimeter Info"], t["Faces Perimeter Values"]
    while True:
        p0, p1 = t["Faces FacePoint Indexes"][k]
        ring.append(fxy[p0])
        s, c = pinfo[k]
        ring.extend(pvals[s : s + c])
        if int(p1) not in nxt:
            raise ValueError("Selected perimeter is not a closed manifold ring")
        k = nxt[int(p1)]
        seen += 1
        if k == start:
            break
        if not (seen <= len(perim_faces)):
            raise ValueError("Source mesh topology is inconsistent")
    if not (seen == len(perim_faces)):
        raise ValueError(
            f"perimeter has {len(perim_faces) - seen} faces off the main ring"
        )
    perimeter = np.array(ring)
    x, y = perimeter[:, 0], perimeter[:, 1]
    if not (0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y) > 0):
        raise ValueError("Source mesh topology is inconsistent")
    t["Perimeter"] = perimeter
    return _Subset(cell_src, face_src, swap, fp_src, n_child_real, t, perimeter)


def _sha256(path):
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _selection(group, parent_cell_ids):
    ids = np.asarray(parent_cell_ids)
    if ids.ndim != 1 or not ids.size or ids.dtype.kind not in "iu":
        raise ValueError("parent_cell_ids must be a nonempty integer sequence")
    if len(np.unique(ids)) != len(ids):
        raise ValueError("parent_cell_ids contains duplicates")
    n_real = int(group["Faces Cell Indexes"][:, 0].max()) + 1
    if np.any(ids < 0) or np.any(ids >= n_real):
        raise ValueError("parent_cell_ids must identify physical source cells")
    ids = np.sort(ids.astype(np.int64))
    keep = np.zeros(n_real, dtype=bool)
    keep[ids] = True
    return ids, _build_subset(group, keep)


def _attr_text(value):
    return value.decode().rstrip("\x00") if isinstance(value, bytes) else str(value)


def _geometry_source(hdf):
    value = hdf.attrs.get("File Type", b"")
    value = value.decode() if isinstance(value, bytes) else str(value)
    if value != "HEC-RAS Geometry" or "Results" in hdf:
        raise ValueError("source must be a geometry-only HDF, without Results")


def _geometry_target(hdf):
    value = _attr_text(hdf.attrs.get("File Type", b""))
    # Native completion can stamp a .g##.hdf as Results even when it contains
    # only Geometry. This exception belongs to the owned target, never source.
    native_geometry = value == "HEC-RAS Results" and set(hdf) == {"Geometry"}
    if (
        "Geometry" not in hdf
        or "Results" in hdf
        or not (value == "HEC-RAS Geometry" or native_geometry)
    ):
        raise ValueError("target must be a geometry-only HDF, without result data")


def _plan_cell_subset(
    source_geometry_hdf, geometry_path, parent_cell_ids, mesh_name, boundary_tolerance
):
    import math
    from pathlib import Path

    from pyproj import CRS
    from shapely.geometry import Polygon

    from ..hdf.HdfBase import HdfBase
    from .GeomMeshDataclasses import MeshCellSubsetPlan
    from .GeomStorage import GeomStorage

    source = Path(source_geometry_hdf).absolute()
    geometry = Path(geometry_path).absolute()
    target = Path(str(geometry) + ".hdf")
    if source.resolve() == target.resolve():
        raise ValueError("source and owned target geometry HDF must differ")
    if (
        isinstance(boundary_tolerance, bool)
        or not math.isfinite(boundary_tolerance)
        or boundary_tolerance < 0
    ):
        raise ValueError("boundary_tolerance must be finite and nonnegative")
    source_hash = _sha256(source)
    target_hash = _sha256(target)
    text_hash = _sha256(geometry)
    source_projection = HdfBase.get_projection(source)
    target_projection = HdfBase.get_projection(target)
    if source_projection is None or target_projection is None:
        raise ValueError("Source and target require consistent resolved CRS evidence")
    source_crs = CRS.from_user_input(source_projection)
    target_crs = CRS.from_user_input(target_projection)
    if not source_crs.equals(target_crs, ignore_axis_order=False):
        raise ValueError("source and target horizontal CRS differ")
    with h5py.File(source, "r") as src, h5py.File(target, "r") as dst:
        _geometry_source(src)
        _geometry_target(dst)
        base = "Geometry/2D Flow Areas"
        attrs = dst[base + "/Attributes"][:]
        names = [row["Name"].decode().rstrip("\x00 ") for row in attrs]
        if names != [mesh_name]:
            raise ValueError("target must contain only the named child 2D area")
        ids, subset = _selection(src[base + "/" + mesh_name], parent_cell_ids)
    area = Polygon(subset.perimeter)
    if not area.is_valid or area.is_empty or len(area.interiors):
        raise ValueError("selected cells require one valid perimeter without holes")
    areas = GeomStorage.get_storage_area_polygons(geometry, exclude_2d=False)
    areas = areas[areas["is_2d"]]
    if len(areas) != 1 or areas["Name"].iloc[0] != mesh_name:
        raise ValueError("target text must contain exactly the named child 2D area")
    authored = areas.geometry.iloc[0]
    if not authored.is_valid or len(authored.interiors):
        raise ValueError("target perimeter must be a valid polygon without holes")
    if area.boundary.hausdorff_distance(authored.boundary) > boundary_tolerance:
        raise ValueError(
            "selected cell union differs from the authored target perimeter"
        )
    from .GeomMesh import _validated_computation_points

    _validated_computation_points(
        subset.tables["Cells Center Coordinate"][: subset.n_real], authored
    )
    if (
        _sha256(source) != source_hash
        or _sha256(target) != target_hash
        or _sha256(geometry) != text_hash
    ):
        raise RuntimeError("cell subset inputs changed during planning")
    return MeshCellSubsetPlan(
        str(source),
        str(geometry),
        mesh_name,
        tuple(int(v) for v in ids),
        source_hash,
        text_hash,
        target_hash,
        len(subset.face_src),
        len(subset.fp_src),
        float(boundary_tolerance),
        source_crs.to_wkt(),
    )


def _replace_dataset(hdf, path, values):
    attrs = dict(hdf[path].attrs) if path in hdf else {}
    if path in hdf:
        del hdf[path]
    options = (
        {"chunks": True, "compression": "gzip", "compression_opts": 1}
        if np.ndim(values)
        else {}
    )
    dataset = hdf.create_dataset(path, data=values, **options)
    for key, value in attrs.items():
        dataset.attrs[key] = value


def _write_subset(source, target, mesh_name, subset, crs_wkt):
    base = "Geometry/2D Flow Areas"
    area = base + "/" + mesh_name
    with h5py.File(source, "r") as src, h5py.File(target, "r+") as dst:
        old = src[area]
        from ._preprocess_contract import ASSOCIATIONS

        target_attributes = dict(dst[area].attrs) if area in dst else {}
        if "Projection" not in dst.attrs:
            dst.attrs["Projection"] = np.bytes_(crs_wkt.encode("utf-8"))
        if area in dst:
            del dst[area]
        group = dst.create_group(area)
        for key in (
            "Version",
            "Manning's n",
            "Cell Volume Tolerance",
            "Face Profile Tolerance",
            "Face Area Elevation Tolerance",
            "Face Area Conveyance Ratio",
        ):
            if key in old.attrs:
                group.attrs[key] = target_attributes.get(key, old.attrs[key])
        for key in (*ASSOCIATIONS, "Projection", "Units System"):
            if key in target_attributes:
                group.attrs[key] = target_attributes[key]
        for name, values in subset.tables.items():
            _replace_dataset(dst, area + "/" + name, values)
        for name, values in (
            ("Cell Points", subset.tables["Cells Center Coordinate"][: subset.n_real]),
            ("Cell Info", np.array([[0, subset.n_real]], dtype=np.int32)),
            ("Polygon Points", subset.perimeter),
            ("Polygon Parts", np.array([[0, len(subset.perimeter)]], dtype=np.int32)),
            (
                "Polygon Info",
                np.array([[0, len(subset.perimeter), 0, 1]], dtype=np.int32),
            ),
        ):
            _replace_dataset(dst, base + "/" + name, values)
        attrs = dst[base + "/Attributes"][:]
        attrs["Cell Count"] = subset.n_real
        _replace_dataset(dst, base + "/Attributes", attrs)
        areas = subset.tables["Cells Surface Area"][: subset.n_real]
        if not np.isfinite(areas).all() or np.any(areas <= 0):
            raise ValueError(
                "Selected source cell surface areas must be finite and positive"
            )
        group.attrs["Cell Maximum Index"] = np.int32(np.argmax(areas))
        for key, value in (
            ("Cell Maximum Size", areas.max()),
            ("Cell Minimum Size", areas.min()),
            ("Cell Average Size", areas.mean()),
        ):
            group.attrs[key] = np.float32(value)
        extents = np.array(
            [
                subset.perimeter[:, 0].min(),
                subset.perimeter[:, 0].max(),
                subset.perimeter[:, 1].min(),
                subset.perimeter[:, 1].max(),
            ]
        )
        group.attrs["Extents"] = extents
        group.attrs["Data Date"] = np.bytes_("01JAN2000 00:00:00")
        dst["Geometry"].attrs["Extents"] = extents
        dst["Geometry"].attrs["Complete Geometry"] = np.bytes_("False")
        if "Geometry/GeomPreprocess" in dst:
            del dst["Geometry/GeomPreprocess"]


def _validate_incidence(hdf, mesh_name, expected):
    group = hdf["Geometry/2D Flow Areas/" + mesh_name]
    ends = group["Faces FacePoint Indexes"][:]
    coordinates = group["FacePoints Coordinate"][:]
    info = group["FacePoints Face and Orientation Info"][:]
    values = group["FacePoints Face and Orientation Values"][:]
    pairs = group["Faces Cell Indexes"][:]
    centres = group["Cells Center Coordinate"][:]
    if len(ends) != len(expected.face_src) or len(coordinates) != len(expected.fp_src):
        raise RuntimeError("Native serialization changed selected topology counts")
    if len(centres) != len(expected.tables["Cells Center Coordinate"]):
        raise RuntimeError("Native serialization changed selected cell counts")
    if not np.array_equal(pairs, expected.tables["Faces Cell Indexes"]):
        raise RuntimeError("Native serialization changed selected face cell indexes")
    if not np.array_equal(coordinates, expected.tables["FacePoints Coordinate"]):
        raise RuntimeError("Native serialization changed source facepoint coordinates")
    if not np.array_equal(ends, expected.tables["Faces FacePoint Indexes"]):
        raise RuntimeError("Native serialization changed selected face endpoints")
    for name in ("Faces Perimeter Info", "Faces Perimeter Values"):
        if not np.array_equal(group[name][()], expected.tables[name]):
            raise RuntimeError("Native serialization changed selected face polylines")
    for name in ("Faces NormalUnitVector and Length", "FacePoints Is Perimeter"):
        actual = group[name][()]
        if actual.dtype != expected.tables[name].dtype or not np.array_equal(
            actual, expected.tables[name]
        ):
            raise RuntimeError(f"Native serialization changed selected {name}")
    if len(info) != len(coordinates):
        raise RuntimeError("Native incident-face record count is invalid")
    if int(info[:, 1].sum()) != len(values):
        raise RuntimeError("Native incident-face packed counts do not match values")
    expected_faces = [[] for _ in coordinates]
    for face, (a, b) in enumerate(ends):
        expected_faces[a].append(face)
        expected_faces[b].append(face)
    offset = 0
    for point, (start, count) in enumerate(info):
        if start != offset or count < 2:
            raise RuntimeError("Native incident-face record span is invalid")
        incident = _ragged(info, values, point)[:, 0]
        if np.any(incident < 0) or np.any(incident >= len(ends)):
            raise RuntimeError("Native incident face is outside the face table")
        if len(set(incident)) != len(incident) or set(incident) != set(
            expected_faces[point]
        ):
            raise RuntimeError("Native facepoint/face incidence is not reciprocal")
        directions = _ragged(info, values, point)[:, 1]
        if not np.array_equal(directions, np.where(ends[incident, 0] == point, -1, 1)):
            raise RuntimeError("Native facepoint/face orientation is not reciprocal")
        boundary = incident[pairs[incident, 1] >= expected.n_real]
        if len(boundary):
            outgoing = boundary[ends[boundary, 0] == point]
            incoming = boundary[ends[boundary, 1] == point]
            if (
                len(outgoing) != 1
                or len(incoming) != 1
                or incident[0] != outgoing[0]
                or incident[-1] != incoming[0]
            ):
                raise RuntimeError(
                    "Native perimeter incidence must be outgoing-first/incoming-last"
                )
        offset += int(count)
    cell_info = group["Cells Face and Orientation Info"][:]
    cell_values = group["Cells Face and Orientation Values"][:]
    if len(cell_info) != len(centres) or int(cell_info[:, 1].sum()) != len(cell_values):
        raise RuntimeError("Native cell/face packed counts do not match values")
    cell_faces = [[] for _ in centres]
    for face, (first, second) in enumerate(pairs):
        cell_faces[first].append(face)
        cell_faces[second].append(face)
    cell_points = group["Cells FacePoint Indexes"][()]
    if len(cell_points) != len(centres):
        raise RuntimeError("Native cell vertex record count is invalid")
    offset = 0
    for cell, (start, count) in enumerate(cell_info):
        if start != offset or count < 1:
            raise RuntimeError("Native cell/face record span is invalid")
        row = _ragged(cell_info, cell_values, cell)
        incident = row[:, 0]
        if len(set(incident)) != len(incident) or set(incident) != set(
            cell_faces[cell]
        ):
            raise RuntimeError("Native cell/face incidence is not reciprocal")
        if not np.array_equal(row[:, 1], np.where(pairs[incident, 0] == cell, 1, -1)):
            raise RuntimeError("Native cell/face orientation is not reciprocal")
        vertices = cell_points[cell][cell_points[cell] >= 0]
        if len(vertices) != len(set(vertices)) or set(vertices) != set(
            ends[incident].ravel()
        ):
            raise RuntimeError("Native cell vertex/face incidence is not reciprocal")
        vertex_edges = {
            tuple(sorted(edge)) for edge in zip(vertices, np.roll(vertices, -1))
        }
        face_edges = {tuple(sorted(edge)) for edge in ends[incident]}
        if vertex_edges != face_edges:
            raise RuntimeError(
                "Native cell vertex order does not follow incident faces"
            )
        offset += int(count)
    fp_cell_info = group["FacePoints Cell Info"][()]
    fp_cell_values = group["FacePoints Cell Index Values"][()]
    if len(fp_cell_info) != len(coordinates) or int(fp_cell_info[:, 1].sum()) != len(
        fp_cell_values
    ):
        raise RuntimeError("Native facepoint/cell packed counts do not match values")
    offset = 0
    for point, (start, count) in enumerate(fp_cell_info):
        if start != offset or count < 1:
            raise RuntimeError("Native facepoint/cell record span is invalid")
        cells = _ragged(fp_cell_info, fp_cell_values, point)
        expected_cells = set(pairs[expected_faces[point]].ravel())
        if len(cells) != len(set(cells)) or set(cells) != expected_cells:
            raise RuntimeError("Native facepoint/cell incidence is not reciprocal")
        offset += int(count)
    if not np.array_equal(
        centres[: expected.n_real],
        expected.tables["Cells Center Coordinate"][: expected.n_real],
    ):
        raise RuntimeError(
            "Native serialization changed source physical cell coordinates"
        )
    return group.attrs["Data Date"].decode().strip("\x00")


def _validate_cell_subset(plan):
    """Rebuild expected topology from immutable planned source IDs, then compare."""
    from pathlib import Path

    from .GeomMeshDataclasses import MeshCellSubsetPlan

    if not isinstance(plan, MeshCellSubsetPlan):
        raise TypeError("plan must be returned by GeomMesh.plan_cell_subset")
    source = Path(plan.source_geometry_hdf)
    if _sha256(source) != plan.source_sha256:
        raise RuntimeError("Cell subset source changed after planning")
    with h5py.File(source, "r") as hdf:
        _, expected = _selection(
            hdf["Geometry/2D Flow Areas/" + plan.mesh_name], plan.parent_cell_ids
        )
    target = Path(plan.geometry_path + ".hdf")
    target_hash = _sha256(target)
    if (
        len(expected.face_src) != plan.face_count
        or len(expected.fp_src) != plan.facepoint_count
    ):
        raise RuntimeError(
            "Cell subset planned topology counts do not match the source"
        )
    try:
        with h5py.File(target, "r") as hdf:
            _validate_incidence(hdf, plan.mesh_name, expected)
    except (ValueError, IndexError, KeyError, TypeError) as exc:
        raise RuntimeError("Native subset topology validation failed") from exc
    if _sha256(source) != plan.source_sha256:
        raise RuntimeError("Cell subset source changed during validation")
    if _sha256(target) != target_hash:
        raise RuntimeError("Cell subset child changed during validation")
    return {
        "schema": "ras-mesh-cell-subset-validation/v1",
        "status": "pass",
        "source_sha256": plan.source_sha256,
        "geometry_hdf_sha256": target_hash,
        "physical_cells": expected.n_real,
        "total_cells": len(expected.cell_src),
        "faces": len(expected.face_src),
        "facepoints": len(expected.fp_src),
        "topology_exact": True,
        "hydraulic_acceptance": "not_established",
    }


def _set_text_stamp(path, mesh_name, stamp):
    from .._ras_text import _split_ras_records, _write_ras_text

    lines = _split_ras_records(
        path.read_bytes().decode("utf-8", errors="surrogateescape")
    )
    current = None
    count = 0
    for index, line in enumerate(lines):
        if line.startswith("Storage Area="):
            current = line.split("=", 1)[1].split(",", 1)[0].strip()
        elif current == mesh_name and line.startswith(
            "Storage Area 2D PointsPerimeterTime="
        ):
            lines[index] = "Storage Area 2D PointsPerimeterTime=" + stamp + "\n"
            count += 1
    if count != 1:
        raise ValueError("Expected one named area computation-point timestamp")
    _write_ras_text(path, "".join(lines), encoding="utf-8", errors="surrogateescape")


def _relocate_associations(staged_hdf, original_hdf):
    """Resolve staged filename attributes against their original HDF folder."""
    from .._geometry_association import (
        decode_hdf_attr,
        encode_hdf_attr,
        resolve_association_attr_path,
    )
    from ._preprocess_contract import ASSOCIATIONS

    originals = {}
    with h5py.File(staged_hdf, "r+") as hdf:
        paths = ["/", "Geometry"]
        paths.extend(
            "Geometry/2D Flow Areas/" + name
            for name, obj in hdf["Geometry/2D Flow Areas"].items()
            if isinstance(obj, h5py.Group)
        )
        for path in paths:
            for key in ASSOCIATIONS:
                if not key.endswith(" Filename") or key not in hdf[path].attrs:
                    continue
                value = hdf[path].attrs[key]
                text = decode_hdf_attr(value)
                if not text:
                    continue
                resolved = resolve_association_attr_path(original_hdf, text)
                if not resolved.is_file():
                    raise FileNotFoundError(
                        f"Associated input does not exist: {resolved}"
                    )
                originals[path, key] = value
                hdf[path].attrs[key] = encode_hdf_attr(str(resolved))
    return originals


def _restore_associations(staged_hdf, originals):
    """Restore the owned geometry's original relative association spelling."""
    with h5py.File(staged_hdf, "r+") as hdf:
        for (path, key), value in originals.items():
            hdf[path].attrs[key] = value


def _resolve_subset_install(hecras_version, hecras_dir, ras_object):
    """Retain the exact project runtime rather than rediscovering its version."""
    from pathlib import Path

    from .._landcover_native import find_hecras_install

    selected = None
    if ras_object is None:
        from ..RasPrj import ras

        if getattr(ras, "initialized", False):
            ras_object = ras
    if ras_object is not None:
        selected_exe = Path(ras_object.ras_exe_path).resolve()
        if not selected_exe.is_file() or selected_exe.name.lower() != "ras.exe":
            raise FileNotFoundError("Project must select an existing explicit Ras.exe")
        selected = selected_exe.parent
    if hecras_dir is not None:
        explicit = Path(hecras_dir).resolve()
        if selected is not None and explicit != selected:
            raise ValueError("hecras_dir conflicts with the project's selected Ras.exe")
        selected = explicit
    install = selected if selected is not None else find_hecras_install(hecras_version)
    for filename in ("Ras.exe", "RasMapperLib.dll"):
        if not (install / filename).is_file():
            raise FileNotFoundError(
                f"Selected runtime is missing {filename}: {install}"
            )
    return install


def _apply_cell_subset(plan, hecras_version, hecras_dir, ras_object, timeout):
    import json
    import os
    import shutil
    import subprocess
    import sys
    import tempfile
    from pathlib import Path
    from uuid import uuid4

    from .._gdal_runtime import configure_rasmapper_gdal_bridge
    from .._native_worker_environment import worker_environment
    from ._preprocess_contract import CALIBRATION, _digest, invalidate_products
    from .GeomMesh import GeomMesh
    from .GeomMeshDataclasses import MeshCellSubsetPlan, MeshResult
    from .GeomStorage import GeomStorage

    if not isinstance(plan, MeshCellSubsetPlan):
        raise TypeError("plan must be returned by GeomMesh.plan_cell_subset")
    source = Path(plan.source_geometry_hdf)
    geometry = Path(plan.geometry_path)
    target = Path(str(geometry) + ".hdf")

    def unchanged():
        return (_sha256(source), _sha256(geometry), _sha256(target)) == (
            plan.source_sha256,
            plan.geometry_sha256,
            plan.geometry_hdf_sha256,
        )

    if not unchanged():
        raise RuntimeError("Cell subset inputs changed after planning")
    refreshed = _plan_cell_subset(
        source, geometry, plan.parent_cell_ids, plan.mesh_name, plan.boundary_tolerance
    )
    if refreshed != plan:
        raise RuntimeError(
            "Cell subset plan does not match the current validated inputs"
        )
    install = _resolve_subset_install(hecras_version, hecras_dir, ras_object)
    configure_rasmapper_gdal_bridge(install)
    with h5py.File(source, "r") as hdf:
        _, subset = _selection(
            hdf["Geometry/2D Flow Areas/" + plan.mesh_name], plan.parent_cell_ids
        )
    with tempfile.TemporaryDirectory(
        prefix=".ras-cell-subset-", dir=geometry.parent
    ) as folder:
        staged = Path(folder) / geometry.name
        staged_hdf = Path(str(staged) + ".hdf")
        shutil.copy2(geometry, staged)
        shutil.copy2(target, staged_hdf)
        GeomStorage.set_2d_flow_area_perimeter(
            staged,
            plan.mesh_name,
            coordinates=subset.perimeter.tolist(),
            create_backup=False,
        )
        points = GeomMesh.write_computation_points(
            staged,
            subset.tables["Cells Center Coordinate"][: subset.n_real],
            mesh_name=plan.mesh_name,
            ras_object=ras_object,
        )
        if not points.ok:
            raise ValueError(points.error_message)
        _write_subset(source, staged_hdf, plan.mesh_name, subset, plan.crs_wkt)
        with h5py.File(staged_hdf, "r") as hdf:
            calibration = _digest(hdf[CALIBRATION][()]) if CALIBRATION in hdf else None
        original_associations = _relocate_associations(staged_hdf, target)
        receipt = Path(folder) / "native.json"
        worker = Path(__file__).resolve().parents[1] / "_cell_subset_worker.py"
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(worker),
                    str(install),
                    str(staged_hdf),
                    plan.mesh_name,
                    str(subset.n_real),
                    str(receipt),
                ],
                cwd=staged_hdf.parent,
                env=worker_environment(1),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Native cell subset serialization exceeded {timeout} seconds"
            ) from exc
        if result.returncode != 0 or not receipt.is_file():
            raise RuntimeError(
                "Native cell subset serialization failed: "
                + (result.stderr or result.stdout)
            )
        _restore_associations(staged_hdf, original_associations)
        native = json.loads(receipt.read_text(encoding="utf-8"))
        native.update(
            install_directory=str(install),
            executable_sha256=_sha256(install / "Ras.exe"),
            rasmapper_dll_sha256=_sha256(install / "RasMapperLib.dll"),
        )
        with h5py.File(staged_hdf, "r") as hdf:
            if calibration is not None and (
                CALIBRATION not in hdf or _digest(hdf[CALIBRATION][()]) != calibration
            ):
                raise RuntimeError(
                    "Native subset serialization changed the authored Manning calibration table"
                )
            stamp = _validate_incidence(hdf, plan.mesh_name, subset)
        _set_text_stamp(staged, plan.mesh_name, stamp)
        invalidated = invalidate_products(staged_hdf)
        with h5py.File(staged_hdf, "r+") as hdf:
            hdf["Geometry"].attrs["Complete Geometry"] = np.bytes_("False")
        if not unchanged():
            raise RuntimeError("Cell subset inputs changed during native serialization")
        token = uuid4().hex
        text_backup = geometry.with_name(
            geometry.name + ".cell-subset-" + token + ".bak"
        )
        hdf_backup = target.with_name(target.name + ".cell-subset-" + token + ".bak")
        shutil.copy2(geometry, text_backup)
        shutil.copy2(target, hdf_backup)
        try:
            os.replace(staged_hdf, target)
            os.replace(staged, geometry)
        except BaseException:
            shutil.copy2(hdf_backup, target)
            shutil.copy2(text_backup, geometry)
            raise
    return MeshResult(
        mesh_name=plan.mesh_name,
        status="complete",
        mesh_state="topology_written",
        cell_count=subset.n_real,
        face_count=len(subset.face_src),
        operation="cell_subset",
        geom_text_path=str(geometry),
        geom_hdf_path=str(target),
        cell_subset={
            **plan.to_dict(),
            "native_serialization": native,
            "mesh_data_date": stamp,
            "invalidated_products": invalidated,
            "geometry_backup": str(text_backup),
            "geometry_hdf_backup": str(hdf_backup),
        },
    )
