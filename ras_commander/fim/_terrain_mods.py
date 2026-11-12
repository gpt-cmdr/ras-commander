"""Terrain modifications staged for ``rasmapper-effective-terrain/2``.

Reads every layer under ``/Modifications`` of a RAS Mapper terrain HDF and
converts it to the engine's ``modification_layers`` request field. The reader
returns what RAS Mapper applies, not what the file happens to contain: it
follows RasMapperLib's own load rules (HEC-RAS 6.6, 7.0 and 7.0.1 load
modifications identically). The engine (ras-commander-fast-map) is the source
of truth for which forms it reproduces; it refuses the rest, and so does this
reader where the refusal is cheap to decide here. A refusal raises
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
  export leaves the terrain unchanged for them. A layer without an
  ``Attributes`` table loads empty in RAS Mapper and is skipped.
* Ground-line profiles come from ``Profile Info`` + ``Profile Values``
  (float32). A dataset named ``Profile`` is never read by RAS Mapper. Without
  control points, a feature needs a stored profile of two or more stations:
  RAS Mapper samples the terrain at the line ends otherwise, which is refused.
* Ground-line features carry ``System Name`` (named features take RAS
  Mapper's system path, which the engine reproduces), ``Transition Percent``
  and ``Elev Pt Tolerance``. Template values (``Top Width``, slopes, ``Max
  Reach``) are passed as stored; NaN becomes ``null`` and the engine applies
  RAS Mapper's rules (a NaN slope reads as 3, a NaN Max Reach draws nothing).
* A layer's ``Control Points`` (``Points`` X, Y and ``Attributes``
  ``Elevation``; NaN becomes ``null``) are passed for ground lines and
  polygons.
* Polygons carry ``Generate Boundary Elevations``, ``Use ShapeFile Z
  Elevations``, ``Elev Pt Tolerance`` and the stored perimeter profile
  (``Profile Info`` + ``Profile Values``, HEC-RAS 7.x). Vertex Z is passed
  when ``Polygon Points`` names a ``Z`` column.
* Features whose ``Elevation Value`` is NaN are skipped by RAS Mapper
  (polygons and ellipses); they are dropped here.
* ``Priority``: lower wins (RAS Mapper applies layers in reverse priority
  order). A missing or shared priority leaves the order to HDF enumeration
  order, which is not qualified: refused.
* The ``.rasmap`` ``Checked`` state and per-layer entries are not consulted
  by the export, so the rasmap is not read here. The export does need the
  terrain layer's ``ElevationModificationGroup`` element named exactly
  ``Modifications`` (any content): without it, or with the group under
  another name, HEC-RAS 6.6 and 7.0.1 apply none of the HDF modifications.
  That gate is checked by ``_terrain_scope`` when a rasmap is given, which
  reports a misnamed group in ``rasmap_warnings``.

Refused here, before the engine runs (each one the engine also refuses):
polygon features with more than one ring (holes in any winding, separate or
overlapping parts; reason code ``multi_ring_polygon`` on the error's
``reason``), because RAS Mapper joins and triangulates such rings in a way
that cannot be reproduced as a rule; shape-Z polygons without boundary
elevations (vertex Z storage is not export-measured), boundary elevations sampled from the terrain when the
layer has no control points and the polygon no stored profile, named ground
lines in a layer with control points or with a NaN template, a NaN Top Width
with a finite Max Reach, and, for ``hecras_version="6.6"``, named ground lines
and boundary elevations without control points.

``hecras_version`` selects the HEC-RAS version whose export is reproduced:
``"7.0.1"`` or ``"6.6"`` (the engine skips ground lines whose Max Reach is not
wider than one cell under 6.6). :func:`hecras_version_for` maps a project's
version to one of these; versions other than 6.6 follow 7.0.1.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import numpy as np

from .errors import FimUnsupportedError

logger = logging.getLogger(__name__)

GROUND_LINE_TYPES = ("SetValue", "SetIfHigher", "SetIfLower", "Add")
AREA_TYPES = ("SetValue", "SetIfHigher", "SetIfLower", "Add")
ELLIPSE_TYPES = ("SetValue", "SetIfHigher", "SetIfLower")
#: Layer types RAS Mapper applies that the engine does not reproduce.
RAS_APPLIED_UNSTAGED_TYPES = (
    "Rectangle", "Triangle", "Encroachment Polygon", "Levee1", "Pier", "Tree",
)
LENGTH_UNITS = ("feet", "meters")
#: Refusal reason code for a polygon feature with more than one ring.
MULTI_RING_POLYGON = "multi_ring_polygon"
#: HEC-RAS versions whose terrain export the engine reproduces.
HECRAS_VERSIONS = ("7.0.1", "6.6")


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


def _nullable(value, what: str) -> Optional[float]:
    """A stored float as JSON: NaN becomes ``None``; infinities are refused."""
    value = float(value)
    if np.isnan(value):
        return None
    if not np.isfinite(value):
        raise FimUnsupportedError(f"{what} is {value!r}")
    return value


def _flag(row, name) -> bool:
    value = _field(row, name)
    return bool(int(value)) if value is not None else False


def _control_points(group, name) -> list:
    """The layer's ``Control Points`` as ``{x, y, elevation}`` (NaN = ``None``)."""
    import h5py

    cp = group.get("Control Points")
    if not isinstance(cp, h5py.Group):
        return []
    points = cp.get("Points")
    if not isinstance(points, h5py.Dataset) or points.shape[0] == 0:
        return []
    xy = np.asarray(points[()], dtype=float)
    if xy.ndim != 2 or xy.shape[1] < 2:
        raise FimUnsupportedError(f"modification {name!r}: unexpected Control Points layout {xy.shape}")
    attrs = cp.get("Attributes")
    if not isinstance(attrs, h5py.Dataset) or "Elevation" not in (attrs.dtype.names or ()):
        raise FimUnsupportedError(f"modification {name!r}: control points without an Elevation attribute")
    elevations = np.asarray(attrs["Elevation"], dtype=np.float32)
    if len(elevations) != len(xy):
        raise FimUnsupportedError(
            f"modification {name!r}: {len(xy)} control points but {len(elevations)} elevations"
        )
    if not np.isfinite(xy[:, :2]).all() or np.isinf(elevations).any():
        raise FimUnsupportedError(f"modification {name!r}: non-finite control point")
    return [
        {"x": float(x), "y": float(y), "elevation": None if np.isnan(e) else float(e)}
        for (x, y), e in zip(xy[:, :2], elevations)
    ]


def _parts(info, parts, i, what):
    start, _count, part_start, part_count = (int(v) for v in info[i])
    if part_count != 1:
        raise FimUnsupportedError(f"{what}: {part_count} parts (only single-part features are qualified)")
    offset, n = (int(v) for v in parts[part_start])
    return start + offset, n


def _profiles(group, count, name) -> list:
    """Per-feature ``[station, elevation]`` lists from ``Profile Info/Values``.

    RAS Mapper needs both datasets; without either every profile is empty.
    """
    if "Profile Info" not in group or "Profile Values" not in group:
        return [[] for _ in range(count)]
    pinfo = np.asarray(group["Profile Info"][()])
    pvalues = np.asarray(group["Profile Values"][()], dtype=np.float32)
    if pinfo.ndim != 2 or pinfo.shape[1] < 2 or len(pinfo) != count:
        raise FimUnsupportedError(
            f"modification {name!r}: Profile Info has {len(pinfo)} rows for {count} features"
        )
    profiles = []
    for row in pinfo:
        p0, pn = int(row[0]), int(row[1])
        values = np.asarray(pvalues[p0:p0 + pn, :2], dtype=float)
        if len(values) != pn or not np.isfinite(values).all():
            raise FimUnsupportedError(f"modification {name!r}: invalid or non-finite stored profile")
        profiles.append(values.tolist())
    return profiles


def _ground_line_layer(name, group, priority, length_units, hecras_version) -> dict:
    subtype = _text(group.attrs.get("Subtype", b"")).strip()
    if subtype not in ("Levee", "Channel"):
        raise FimUnsupportedError(
            f"modification {name!r}: ground-line subtype {subtype!r} (RAS Mapper reclassifies "
            "unknown subtypes from slope signs; not qualified)"
        )
    control_points = _control_points(group, name)
    attrs = group["Attributes"][()]
    info = group["Polyline Info"][()]
    parts = group["Polyline Parts"][()]
    points = group["Polyline Points"][()]
    profiles = _profiles(group, len(attrs), name)
    features = []
    for i, row in enumerate(attrs):
        what = f"modification {name!r} feature {i}"
        system_name = _text(_field(row, "System Name")).strip()
        et = _text(_field(row, "Elevation Type"))
        if et not in GROUND_LINE_TYPES:
            raise FimUnsupportedError(f"{what}: ground-line elevation type {et!r} is not qualified")
        start, n = _parts(info, parts, i, what)
        xy = np.asarray(points[start:start + n, :2], dtype=float)
        profile = profiles[i]
        if n < 2:
            raise FimUnsupportedError(f"{what}: needs >= 2 vertices")
        if not control_points and len(profile) < 2:
            raise FimUnsupportedError(
                f"{what}: no stored profile and no control points (RAS Mapper samples the terrain "
                "at the line ends; not qualified)"
            )
        if not np.isfinite(xy).all():
            raise FimUnsupportedError(f"{what}: non-finite geometry")
        if np.any(np.all(np.diff(xy, axis=0) == 0, axis=1)):
            raise FimUnsupportedError(f"{what}: repeated vertex")
        template = {
            key: _nullable(_float(row, column), f"{what}: {column}")
            for key, column in (("top_width", "Top Width"), ("left_slope", "Left Slope"),
                                ("right_slope", "Right Slope"), ("max_reach", "Max Reach"))
        }
        if template["top_width"] is None and template["max_reach"] is not None:
            raise FimUnsupportedError(
                f"{what}: a NaN Top Width with a finite Max Reach makes the RAS Mapper export fail"
            )
        if system_name:
            reason = None
            if control_points:
                reason = "in a layer with control points"
            elif any(value is None for value in template.values()):
                reason = "with a NaN template value"
            elif hecras_version == "6.6":
                reason = "under HEC-RAS 6.6 (its system path differs)"
            if reason:
                raise FimUnsupportedError(
                    f"{what}: named ground line (System Name {system_name!r}) {reason} is not qualified"
                )
        transition = _field(row, "Transition Percent")
        features.append({
            "elevation_type": et,
            **template,
            "points": xy.tolist(),
            "profile": profile,
            "system_name": system_name,
            "transition_percent": 0.0 if transition is None
            else _nullable(transition, f"{what}: Transition Percent"),
            "elev_pt_tolerance": _nullable(_float(row, "Elev Pt Tolerance"), f"{what}: Elev Pt Tolerance"),
        })
    layer = {"kind": "ground_line", "name": name, "priority": priority,
             "subtype": subtype.lower(), "length_units": length_units, "features": features}
    if control_points:
        layer["control_points"] = control_points
    return layer


def _z_column(dataset) -> Optional[int]:
    """Index of the ``Z`` column of a feature points dataset, if any."""
    width = dataset.shape[1] if dataset.ndim == 2 else 0
    if width == 4:
        return 2  # X, Y, Z, M
    if width == 3:
        names = [_text(c).strip().upper() for c in np.atleast_1d(dataset.attrs.get("Column", []))]
        if len(names) == 3 and names[2] == "Z":
            return 2
    return None


def _polygon_layer(name, group, priority, length_units, hecras_version) -> dict:
    control_points = _control_points(group, name)
    attrs = group["Attributes"][()]
    info = group["Polygon Info"][()]
    parts = group["Polygon Parts"][()]
    points_ds = group["Polygon Points"]
    points = points_ds[()]
    z_column = _z_column(points_ds)
    profiles = _profiles(group, len(attrs), name)
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
        if not np.isfinite(elevation):
            raise FimUnsupportedError(f"{what}: non-finite elevation")
        generate = _flag(row, "Generate Boundary Elevations")
        shape_z = _flag(row, "Use ShapeFile Z Elevations")
        if shape_z and not generate:
            raise FimUnsupportedError(f"{what}: polygons with shapefile Z elevations are not qualified")
        start, _count, part_start, part_count = (int(v) for v in info[i])
        if part_count > 1:
            # RAS Mapper joins a polygon's rings (holes in any winding, separate
            # or overlapping parts) and triangulates them in a way that is not
            # reproducible as a rule; the engine refuses them (Fast-Map #42).
            raise FimUnsupportedError(
                f"{what}: multi-ring polygon ({part_count} rings: a hole or separate/overlapping "
                f"parts) is not qualified [reason: {MULTI_RING_POLYGON}]; use the RAS Mapper export",
                reason=MULTI_RING_POLYGON,
            )
        rings, vertex_z = [], []
        for j in range(part_count):
            offset, n = (int(v) for v in parts[part_start + j])
            block = np.asarray(points[start + offset:start + offset + n], dtype=float)
            ring = block[:, :2]
            if n < 3 or not np.isfinite(ring).all():
                raise FimUnsupportedError(f"{what}: invalid ring")
            rings.append(ring.tolist())
            if z_column is not None:
                vertex_z.extend(block[:, z_column].tolist())
        if generate and not control_points:
            if hecras_version == "6.6":
                raise FimUnsupportedError(
                    f"{what}: HEC-RAS 6.6 samples boundary elevations from the terrain (not qualified)"
                )
            if not profiles[i]:
                raise FimUnsupportedError(
                    f"{what}: boundary elevations sampled from the terrain (no stored profile, "
                    "no control points) are not qualified"
                )
        feature = {
            "elevation_type": et,
            "elevation": elevation,
            "rings": rings,
            "generate_boundary": generate,
            "use_shape_z": shape_z,
            "profile": profiles[i],
            "elev_pt_tolerance": _nullable(_float(row, "Elev Pt Tolerance"), f"{what}: Elev Pt Tolerance"),
        }
        if shape_z:
            # RAS Mapper ignores vertex Z with boundary elevations on, but the
            # engine expects one value per vertex of a shape-Z ring.
            if part_count != 1 or len(vertex_z) != len(rings[0]) or not np.isfinite(vertex_z).all():
                raise FimUnsupportedError(f"{what}: shapefile Z flag without one finite Z per vertex")
            feature["vertex_z"] = vertex_z
        features.append(feature)
    layer = {"kind": "polygon", "name": name, "priority": priority,
             "length_units": length_units, "features": features}
    if control_points:
        layer["control_points"] = control_points
    return layer


def _ellipse_layer(name, group, priority) -> dict:
    attrs = group["Attributes"][()]
    circles = np.asarray(group["Circles"][()], dtype=float)
    if circles.ndim != 2 or circles.shape[1] != 5 or len(circles) != len(attrs):
        raise FimUnsupportedError(f"modification {name!r}: unexpected Circles layout {circles.shape}")
    features = []
    for i, (row, (cx, cy, rx, ry, rot)) in enumerate(zip(attrs, circles)):
        what = f"modification {name!r} feature {i}"
        et = _text(_field(row, "Elevation Type"))
        if et not in ELLIPSE_TYPES:
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


def project_length_units(terrain_hdf, rasmap_path=None, ras_object=None) -> str:
    """RAS Mapper's unit system for a terrain: ``"feet"`` or ``"meters"``.

    RAS Mapper densifies ground-line profiles every 100 ft, or 100/3.281 m in
    SI projects, by the project unit system (not by the terrain CRS). The
    project is ``ras_object``'s project file, else the ``.prj`` named like
    ``rasmap_path``, else the RAS project files beside the rasmap (or in the
    terrain's parent project folder). Units come from
    :meth:`RasPrj.get_project_units` (``SI Units``, ``English Units`` or
    ``SI Units=<bool>``). Defaults to feet when no project states its units.

    Raises:
        FimUnsupportedError: Several candidate project files state different
            units and none is selected by ``ras_object`` or the rasmap name.
    """
    from ..RasPrj import RasPrj

    def units_of(prj) -> Optional[str]:
        prj = Path(prj)
        try:
            with prj.open("r", encoding="utf-8", errors="replace") as handle:
                if not handle.readline().startswith("Proj Title="):
                    return None  # ESRI projection files share the .prj suffix
        except OSError:
            return None
        units = RasPrj.get_project_units(prj)
        return None if units is None else ("meters" if units == "m" else "feet")

    selected = []
    prj_file = getattr(ras_object, "prj_file", None) if ras_object is not None else None
    if prj_file:
        selected.append(Path(prj_file))
    if rasmap_path is not None:
        selected.append(Path(rasmap_path).with_suffix(".prj"))
    for prj in selected:
        units = units_of(prj)
        if units is not None:
            return units
    folder = Path(rasmap_path).parent if rasmap_path is not None else Path(terrain_hdf).parent.parent
    found = {}
    for prj in sorted(folder.glob("*.prj")):
        units = units_of(prj)
        if units is not None:
            found[prj.name] = units
    if len(set(found.values())) > 1:
        raise FimUnsupportedError(
            f"project files in {folder.name} state different units {found}; pass ras_object "
            "or a rasmap named like its project"
        )
    return next(iter(found.values()), "feet")


def hecras_version_for(version) -> str:
    """The engine ``hecras_version`` that reproduces a HEC-RAS version's export.

    ``6.6`` (any 6.6 patch) maps to ``"6.6"``. Every other version maps to
    ``"7.0.1"``: the engine is qualified against HEC-RAS 7.0.1 and 6.6 exports
    only, and RasMapperLib 7.0 loads and applies modifications as 7.0.1 does.
    Earlier 6.x releases are not measured and follow 7.0.1.

    Args:
        version: A version label such as ``"6.6"``, ``"6.60"``, ``"7.0.1"``,
            ``"7.00"`` or a tuple ``(6, 6, 0)``; ``None`` gives ``"7.0.1"``.
    """
    if version is None:
        return "7.0.1"
    if isinstance(version, (tuple, list)):
        major, minor = (int(v) for v in tuple(version)[:2])
    else:
        match = re.search(r"(\d+)\.(\d)", str(version))
        if match is None:
            return "7.0.1"
        major, minor = int(match.group(1)), int(match.group(2))
    return "6.6" if (major, minor) == (6, 6) else "7.0.1"


def _program_versions(folder: Path) -> list:
    """``Program Version=`` values of the RAS plan and geometry files in ``folder``."""
    found = []
    for path in sorted(folder.glob("*.[pg][0-9][0-9]")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for _, line in zip(range(400), handle):
                    if line.startswith("Program Version="):
                        found.append(line.split("=", 1)[1].strip())
                        break
        except OSError:
            continue
    return found


def project_hecras_version(terrain_hdf, rasmap_path=None, ras_object=None) -> tuple:
    """The HEC-RAS version whose export a terrain's modifications follow.

    Resolution: the initialized ``ras_object``'s HEC-RAS version (or its
    ``Ras.exe`` folder), else the newest ``Program Version`` of the plan and
    geometry files beside ``rasmap_path`` (or in the terrain's parent project
    folder), else 7.0.1.

    Returns:
        tuple: ``(hecras_version, basis)``, ``hecras_version`` one of
        :data:`HECRAS_VERSIONS` and ``basis`` a short description.
    """
    if ras_object is not None:
        for attr in ("ras_version", "ras_exe_path"):
            value = getattr(ras_object, attr, None)
            if value:
                label = Path(str(value)).parent.name if attr == "ras_exe_path" else str(value)
                if re.search(r"\d+\.\d", label):
                    return hecras_version_for(label), f"ras_object.{attr} {label}"
    folders = []
    if rasmap_path is not None:
        folders.append(Path(rasmap_path).parent)
    folders.append(Path(terrain_hdf).parent.parent)
    for folder in folders:
        versions = _program_versions(folder)
        parsed = []
        for label in versions:
            match = re.search(r"(\d+)\.(\d)", label)
            if match:
                parsed.append(((int(match.group(1)), int(match.group(2))), label))
        if parsed:
            label = max(parsed)[1]
            return hecras_version_for(label), f"Program Version {label} in {folder.name}"
    return "7.0.1", "default"


def read_layers(terrain_hdf, length_units: Optional[str] = "feet",
                hecras_version: str = "7.0.1") -> list:
    """Every modification layer of ``terrain_hdf`` as engine request layers.

    Args:
        terrain_hdf: RAS Mapper terrain HDF.
        length_units: RAS Mapper project unit system, ``"feet"`` or
            ``"meters"`` (see :func:`project_length_units`); set on every
            ground-line and polygon layer.
        hecras_version: ``"7.0.1"`` or ``"6.6"`` (see
            :func:`hecras_version_for`); forms the engine refuses for that
            version are refused here.

    Raises:
        FimUnsupportedError: a layer or feature is not a qualified form.
    """
    import h5py

    if length_units not in LENGTH_UNITS:
        raise ValueError(f"length_units must be one of {LENGTH_UNITS}")
    if hecras_version not in HECRAS_VERSIONS:
        raise ValueError(f"hecras_version must be one of {HECRAS_VERSIONS}")
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
            if "Attributes" not in layer or len(layer["Attributes"]) == 0:
                continue  # RAS Mapper loads a layer without Attributes as empty
            priority = layer.attrs.get("Priority")
            if priority is None:
                raise FimUnsupportedError(f"modification {name!r} has no Priority")
            priority = int(np.asarray(priority))
            if kind == "Levee":
                staged = _ground_line_layer(name, layer, priority, length_units, hecras_version)
            elif kind == "Polygon":
                staged = _polygon_layer(name, layer, priority, length_units, hecras_version)
            else:
                staged = _ellipse_layer(name, layer, priority)
            if staged["features"]:
                layers.append(staged)
    priorities = [layer["priority"] for layer in layers]
    if len(set(priorities)) != len(priorities):
        raise FimUnsupportedError("modification layers share a Priority; application order is unproven")
    return layers
