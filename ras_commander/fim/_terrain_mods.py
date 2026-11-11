"""Terrain modifications staged for ``rasmapper-effective-terrain/2``.

Reads every layer under ``/Modifications`` of a RAS Mapper terrain HDF and
converts it to the engine's ``modification_layers`` request field. Only the
modification forms qualified against HEC-RAS 7.0.1 RAS Mapper exports are
staged; anything else raises :class:`FimUnsupportedError` with the reason, so
the caller falls back to the RAS Mapper export instead of an approximation.

Qualified (fast-map ``terrain_mods``):

* ground lines (``Type=Levee``; subtype ``Levee`` = high ground, ``Channel``)
  with ``SetIfHigher`` / ``SetIfLower``, one part, a profile of two or more
  stations, ``Max Reach`` above ``Top Width``, no control points, and not
  joined to another feature through a shared ``System Name`` (RAS Mapper
  shares one profile across a system; measured on NewOrleansMetro, not yet
  reproduced);
* polygons with a constant ``Elevation Value`` (``Generate Boundary
  Elevations`` off, ``Use ShapeFile Z Elevations`` off, no control points);
* ellipses (``Type=Circle``) without rotation.

RAS Mapper's export applies every modification stored in the terrain HDF,
whatever the layer's ``Checked`` state in the ``.rasmap`` (measured on
Prop_Topo: the export with the HDF's own unchecked layers equals the one with
every layer checked), so the rasmap is not consulted here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .errors import FimUnsupportedError

GROUND_LINE_TYPES = ("SetIfHigher", "SetIfLower")
AREA_TYPES = ("SetValue", "SetIfHigher", "SetIfLower")


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, np.ndarray) and value.shape == ():
        return _text(value[()])
    return str(value)


def _field(row, name):
    names = row.dtype.names or ()
    if name not in names:
        return None
    return row[name]


def _control_points(group) -> int:
    import h5py

    cp = group.get("Control Points")
    if not isinstance(cp, h5py.Group):
        return 0
    points = cp.get("Points")
    return int(points.shape[0]) if isinstance(points, h5py.Dataset) else 0


def _parts(info, parts, i, what):
    start, count, part_start, part_count = (int(v) for v in info[i])
    if part_count != 1:
        raise FimUnsupportedError(f"{what}: {part_count} parts (only single-part features are qualified)")
    offset, n = (int(v) for v in parts[part_start])
    return start + offset, n


def _ground_line_layer(name, group, priority) -> dict:
    subtype = _text(group.attrs.get("Subtype", b"")).strip()
    if subtype not in ("Levee", "Channel"):
        raise FimUnsupportedError(f"modification {name!r}: ground-line subtype {subtype!r} is not qualified")
    if _control_points(group):
        raise FimUnsupportedError(f"modification {name!r}: ground-line control points are not qualified")
    attrs = group["Attributes"][()]
    info = group["Polyline Info"][()]
    parts = group["Polyline Parts"][()]
    points = group["Polyline Points"][()]
    pinfo = group["Profile Info"][()] if "Profile Info" in group else None
    pvalues = group["Profile Values"][()] if "Profile Values" in group else None
    if pinfo is None or pvalues is None or len(pinfo) != len(attrs):
        raise FimUnsupportedError(f"modification {name!r}: ground lines need a stored profile per feature")
    systems = [_text(_field(row, "System Name") or b"").strip() for row in attrs]
    shared = sorted({s for s in systems if s and systems.count(s) > 1})
    if shared:
        raise FimUnsupportedError(
            f"modification {name!r}: ground lines joined in systems {shared} share one profile; "
            "system joins are not qualified"
        )
    features = []
    for i, row in enumerate(attrs):
        what = f"modification {name!r} feature {i}"
        et = _text(_field(row, "Elevation Type"))
        if et not in GROUND_LINE_TYPES:
            raise FimUnsupportedError(f"{what}: ground-line elevation type {et!r} is not qualified")
        start, n = _parts(info, parts, i, what)
        xy = np.asarray(points[start:start + n, :2], dtype=float)
        p0, pn = (int(v) for v in pinfo[i])
        profile = np.asarray(pvalues[p0:p0 + pn], dtype=float)
        if n < 2 or pn < 2:
            raise FimUnsupportedError(f"{what}: needs >= 2 vertices and >= 2 profile stations")
        if not (np.isfinite(xy).all() and np.isfinite(profile).all()):
            raise FimUnsupportedError(f"{what}: non-finite geometry or profile")
        if np.any(np.all(np.diff(xy, axis=0) == 0, axis=1)):
            raise FimUnsupportedError(f"{what}: repeated vertex")
        values = {k: _field(row, k) for k in ("Top Width", "Left Slope", "Right Slope", "Max Reach")}
        if any(v is None or not np.isfinite(float(v)) for v in values.values()):
            raise FimUnsupportedError(f"{what}: missing or non-finite template parameters")
        if float(values["Left Slope"]) <= 0 or float(values["Right Slope"]) <= 0:
            raise FimUnsupportedError(f"{what}: side slopes must be positive")
        if float(values["Max Reach"]) <= float(values["Top Width"]) or float(values["Top Width"]) < 0:
            raise FimUnsupportedError(
                f"{what}: Max Reach not above Top Width (RAS Mapper clips that template differently; not qualified)"
            )
        features.append({
            "elevation_type": et,
            "top_width": float(values["Top Width"]),
            "left_slope": float(values["Left Slope"]),
            "right_slope": float(values["Right Slope"]),
            "max_reach": float(values["Max Reach"]),
            "points": xy.tolist(),
            "profile": profile.tolist(),
        })
    return {"kind": "ground_line", "name": name, "priority": priority,
            "subtype": subtype.lower(), "features": features}


def _polygon_layer(name, group, priority) -> dict:
    if _control_points(group):
        raise FimUnsupportedError(f"modification {name!r}: polygon control points are not qualified")
    attrs = group["Attributes"][()]
    info = group["Polygon Info"][()]
    parts = group["Polygon Parts"][()]
    points = group["Polygon Points"][()]
    features = []
    for i, row in enumerate(attrs):
        what = f"modification {name!r} feature {i}"
        et = _text(_field(row, "Elevation Type"))
        if et not in AREA_TYPES:
            raise FimUnsupportedError(f"{what}: polygon elevation type {et!r} is not qualified")
        if int(_field(row, "Generate Boundary Elevations") or 0):
            raise FimUnsupportedError(f"{what}: polygons with boundary elevations are not qualified")
        if int(_field(row, "Use ShapeFile Z Elevations") or 0):
            raise FimUnsupportedError(f"{what}: polygons with shapefile Z elevations are not qualified")
        start, count, part_start, part_count = (int(v) for v in info[i])
        rings = []
        for j in range(part_count):
            offset, n = (int(v) for v in parts[part_start + j])
            ring = np.asarray(points[start + offset:start + offset + n, :2], dtype=float)
            if n < 3 or not np.isfinite(ring).all():
                raise FimUnsupportedError(f"{what}: invalid ring")
            rings.append(ring.tolist())
        elevation = float(_field(row, "Elevation Value"))
        if not np.isfinite(elevation):
            raise FimUnsupportedError(f"{what}: non-finite elevation")
        features.append({"elevation_type": et, "elevation": elevation, "rings": rings})
    return {"kind": "polygon", "name": name, "priority": priority, "features": features}


def _ellipse_layer(name, group, priority) -> dict:
    attrs = group["Attributes"][()]
    circles = np.asarray(group["Circles"][()], dtype=float)
    if circles.ndim != 2 or circles.shape[1] != 5 or len(circles) != len(attrs):
        raise FimUnsupportedError(f"modification {name!r}: unexpected Circles layout {circles.shape}")
    features = []
    for i, (row, (cx, cy, rx, ry, rot)) in enumerate(zip(attrs, circles)):
        what = f"modification {name!r} feature {i}"
        et = _text(_field(row, "Elevation Type"))
        if et not in AREA_TYPES:
            raise FimUnsupportedError(f"{what}: ellipse elevation type {et!r} is not qualified")
        if rot != 0:
            raise FimUnsupportedError(f"{what}: rotated ellipses are not qualified")
        if not (np.isfinite([cx, cy, rx, ry]).all() and rx > 0 and ry > 0):
            raise FimUnsupportedError(f"{what}: invalid ellipse")
        features.append({"elevation_type": et, "elevation": float(_field(row, "Elevation Value")),
                         "center": [cx, cy], "radius_x": rx, "radius_y": ry})
    return {"kind": "ellipse", "name": name, "priority": priority, "features": features}


def read_layers(terrain_hdf) -> list:
    """Every modification layer of ``terrain_hdf`` as engine request layers.

    Raises:
        FimUnsupportedError: a layer or feature is not a qualified form.
    """
    import h5py

    layers = []
    with h5py.File(Path(terrain_hdf), "r") as hdf:
        group = hdf.get("Modifications")
        if not isinstance(group, h5py.Group):
            return []
        for name, layer in group.items():
            if not isinstance(layer, h5py.Group):
                raise FimUnsupportedError(f"modification {name!r} is not a group")
            kind = _text(layer.attrs.get("Type", b""))
            priority = layer.attrs.get("Priority")
            if priority is None:
                raise FimUnsupportedError(f"modification {name!r} has no Priority")
            priority = int(np.asarray(priority))
            if "Attributes" not in layer or len(layer["Attributes"]) == 0:
                continue  # an empty layer changes nothing
            if kind == "Levee":
                layers.append(_ground_line_layer(name, layer, priority))
            elif kind == "Polygon":
                layers.append(_polygon_layer(name, layer, priority))
            elif kind == "Circle":
                layers.append(_ellipse_layer(name, layer, priority))
            else:
                raise FimUnsupportedError(f"modification {name!r}: type {kind!r} is not qualified")
    priorities = [layer["priority"] for layer in layers]
    if len(set(priorities)) != len(priorities):
        raise FimUnsupportedError("modification layers share a Priority; application order is unproven")
    return layers
