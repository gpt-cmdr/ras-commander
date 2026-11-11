"""Terrain modifications staged for ``rasmapper-effective-terrain/2``.

Reads every layer under ``/Modifications`` of a RAS Mapper terrain HDF and
converts it to the engine's ``modification_layers`` request field. The reader
returns what RAS Mapper applies, not what the file happens to contain: it
follows RasMapperLib's own load rules (HEC-RAS 6.6, 7.0 and 7.0.1 load
modifications identically). Forms the engine does not reproduce raise
:class:`FimUnsupportedError` with the reason, so the caller falls back to the
RAS Mapper export instead of an approximation.

Load rules followed (RasMapperLib 6.6 / 7.0 / 7.0.1):

* The layer class comes only from the group attribute ``Type``. ``Levee``
  (ground line), ``Polygon`` and ``Circle`` (ellipse) are staged. RAS Mapper
  also applies ``Rectangle``, ``Triangle``, ``Encroachment Polygon``,
  ``Levee1``, ``Pier`` and ``Tree`` layers; those are refused. Any other
  ``Type`` is skipped by RAS Mapper and deleted on its next save, so it is
  skipped here too, with a warning. This covers ground lines written as
  ``Type=Channel`` by ras-commander before the #790 writer fix: RAS Mapper's
  export leaves the terrain unchanged for them.
* Ground-line profiles come from ``Profile Info`` + ``Profile Values``
  (float32). A dataset named ``Profile`` is never read by RAS Mapper.
* A non-empty ``System Name`` sends a ground line through RAS Mapper's system
  path, even a lone feature, which the engine does not reproduce: refused.
* Ground-line slopes: NaN is read as 3 and 0 as 0.001 by RAS Mapper's
  per-feature path; the reader passes NaN on as 3 and 0 as 0 (the engine
  applies the 0.001 rule).
* Features whose ``Elevation Value`` is NaN are skipped by RAS Mapper
  (polygons and ellipses); they are dropped here.
* ``Priority``: lower wins (RAS Mapper applies layers in reverse priority
  order). A missing or shared priority leaves the order to HDF enumeration
  order, which is not qualified: refused.
* The ``.rasmap`` ``Checked`` state and per-layer entries are not consulted
  by the export, so the rasmap is not read here. The export does need the
  terrain layer's ``ElevationModificationGroup`` element (any content):
  without it HEC-RAS 6.6 and 7.0.1 apply none of the HDF modifications.
  That gate is checked by ``_terrain_scope`` when a rasmap is given.

Version notes the engine does not model: HEC-RAS 6.6 skips ground lines whose
``Max Reach`` is not wider than one cell at export, while 7.0 and 7.0.1 burn
them in.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import numpy as np

from .errors import FimUnsupportedError

logger = logging.getLogger(__name__)

GROUND_LINE_TYPES = ("SetValue", "SetIfHigher", "SetIfLower")
AREA_TYPES = ("SetValue", "SetIfHigher", "SetIfLower")
#: Layer types RAS Mapper applies that the engine does not reproduce.
RAS_APPLIED_UNSTAGED_TYPES = (
    "Rectangle", "Triangle", "Encroachment Polygon", "Levee1", "Pier", "Tree",
)
LENGTH_UNITS = ("feet", "meters")


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, np.bytes_)):
        return bytes(value).decode("utf-8", "replace").rstrip("\x00")
    if isinstance(value, np.ndarray) and value.shape == ():
        return _text(value[()])
    return str(value)


def _field(row, name):
    names = row.dtype.names or ()
    if name not in names:
        return None
    return row[name]


def _float(row, name) -> float:
    value = _field(row, name)
    if value is None:
        return float("nan")
    return float(value)


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


def _ground_line_layer(name, group, priority, length_units) -> dict:
    subtype = _text(group.attrs.get("Subtype", b"")).strip()
    if subtype not in ("Levee", "Channel"):
        raise FimUnsupportedError(
            f"modification {name!r}: ground-line subtype {subtype!r} (RAS Mapper reclassifies "
            "unknown subtypes from slope signs; not qualified)"
        )
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
    features = []
    for i, row in enumerate(attrs):
        what = f"modification {name!r} feature {i}"
        system_name = _text(_field(row, "System Name")).strip()
        if system_name:
            raise FimUnsupportedError(
                f"{what}: System Name {system_name!r} sends the feature through RAS Mapper's "
                "system path (even a lone feature); not qualified"
            )
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
        top_width = _float(row, "Top Width")
        max_reach = _float(row, "Max Reach")
        if not (np.isfinite(top_width) and np.isfinite(max_reach)):
            raise FimUnsupportedError(f"{what}: missing or non-finite Top Width / Max Reach")
        slopes = []
        for key in ("Left Slope", "Right Slope"):
            slope = _float(row, key)
            if np.isnan(slope):
                slope = 3.0  # RAS Mapper's per-feature path reads NaN as 3
            if not np.isfinite(slope) or slope < 0:
                raise FimUnsupportedError(f"{what}: {key} {slope!r} is not qualified")
            slopes.append(slope)
        features.append({
            "elevation_type": et,
            "top_width": top_width,
            "left_slope": slopes[0],
            "right_slope": slopes[1],
            "max_reach": max_reach,
            "points": xy.tolist(),
            "profile": profile.tolist(),
            "system_name": system_name,
        })
    return {"kind": "ground_line", "name": name, "priority": priority,
            "subtype": subtype.lower(), "length_units": length_units, "features": features}


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
        elevation = _float(row, "Elevation Value")
        if np.isnan(elevation):
            logger.warning("%s: Elevation Value is NaN; RAS Mapper skips the feature", what)
            continue
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
        elevation = _float(row, "Elevation Value")
        if np.isnan(elevation):
            logger.warning("%s: Elevation Value is NaN; RAS Mapper skips the feature", what)
            continue
        if not (np.isfinite([cx, cy, rx, ry, rot, elevation]).all() and rx > 0 and ry > 0):
            raise FimUnsupportedError(f"{what}: invalid ellipse")
        features.append({"elevation_type": et, "elevation": elevation,
                         "center": [cx, cy], "radius_x": rx, "radius_y": ry,
                         "rotation": rot})
    return {"kind": "ellipse", "name": name, "priority": priority, "features": features}


def project_length_units(terrain_hdf, rasmap_path=None) -> str:
    """RAS Mapper's unit system for a terrain: ``"feet"`` or ``"meters"``.

    RAS Mapper densifies ground-line profiles every 100 ft, or 100/3.281 m in
    SI projects, by the project unit system (not by the terrain CRS). Reads
    ``SI Units`` / ``English Units`` from the project file beside the rasmap
    (or the terrain's parent project folder). Defaults to feet.
    """
    candidates = []
    if rasmap_path is not None:
        rasmap_path = Path(rasmap_path)
        candidates.append(rasmap_path.with_suffix(".prj"))
        candidates.extend(sorted(rasmap_path.parent.glob("*.prj")))
    terrain_hdf = Path(terrain_hdf)
    candidates.extend(sorted(terrain_hdf.parent.parent.glob("*.prj")))
    for prj in candidates:
        try:
            text = prj.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.startswith("Proj Title="):
            continue  # ESRI projection files share the .prj suffix
        if re.search(r"^SI Units\s*$", text, flags=re.MULTILINE):
            return "meters"
        if re.search(r"^English Units\s*$", text, flags=re.MULTILINE):
            return "feet"
    return "feet"


def read_layers(terrain_hdf, length_units: Optional[str] = "feet") -> list:
    """Every modification layer of ``terrain_hdf`` as engine request layers.

    Args:
        terrain_hdf: RAS Mapper terrain HDF.
        length_units: RAS Mapper project unit system, ``"feet"`` or
            ``"meters"`` (see :func:`project_length_units`); set on every
            ground-line layer.

    Raises:
        FimUnsupportedError: a layer or feature is not a qualified form.
    """
    import h5py

    if length_units not in LENGTH_UNITS:
        raise ValueError(f"length_units must be one of {LENGTH_UNITS}")
    layers = []
    with h5py.File(Path(terrain_hdf), "r") as hdf:
        group = hdf.get("Modifications")
        if not isinstance(group, h5py.Group):
            return []
        for name, layer in group.items():
            if not isinstance(layer, h5py.Group):
                raise FimUnsupportedError(f"modification {name!r} is not a group")
            kind = _text(layer.attrs.get("Type", b""))
            if kind in RAS_APPLIED_UNSTAGED_TYPES:
                raise FimUnsupportedError(f"modification {name!r}: type {kind!r} is not qualified")
            if kind not in ("Levee", "Polygon", "Circle"):
                logger.warning(
                    "modification %r: Type %r is ignored by RAS Mapper (skipped)%s", name, kind,
                    "; ground lines must be Type=Levee with Subtype Channel" if kind == "Channel" else "",
                )
                continue
            priority = layer.attrs.get("Priority")
            if priority is None:
                raise FimUnsupportedError(f"modification {name!r} has no Priority")
            priority = int(np.asarray(priority))
            if "Attributes" not in layer or len(layer["Attributes"]) == 0:
                continue  # an empty layer changes nothing
            if kind == "Levee":
                staged = _ground_line_layer(name, layer, priority, length_units)
            elif kind == "Polygon":
                staged = _polygon_layer(name, layer, priority)
            else:
                staged = _ellipse_layer(name, layer, priority)
            if staged["features"]:
                layers.append(staged)
    priorities = [layer["priority"] for layer in layers]
    if len(set(priorities)) != len(priorities):
        raise FimUnsupportedError("modification layers share a Priority; application order is unproven")
    return layers
