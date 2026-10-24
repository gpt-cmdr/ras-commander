"""Text-only external BC offsets and read-only native face-set verification."""

from __future__ import annotations

import hashlib
import math
import os
from numbers import Integral
from pathlib import Path
from typing import Any, Mapping, Sequence


def _mesh_fingerprints(hdf_path: Path) -> dict[str, dict[str, Any]]:
    import h5py

    fingerprints = {}
    with h5py.File(hdf_path, "r") as handle:

        def visit(name, obj):
            if not isinstance(obj, h5py.Dataset) or not name.startswith(
                "Geometry/2D Flow Areas/"
            ):
                return
            values = obj[()]
            if not values.dtype.hasobject:
                fingerprints[name] = {
                    "shape": list(values.shape),
                    "dtype": str(values.dtype),
                    "sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                }

        handle.visititems(visit)
    return fingerprints


def _native_faces(
    hdf_path: Path,
) -> tuple[dict[str, list[int]], dict[str, str], dict[str, str]]:
    from ..hdf import HdfBndry

    faces = HdfBndry.get_bc_external_faces(hdf_path, include_geometry=False)
    sets, areas, types = {}, {}, {}
    for name, rows in faces.groupby("bc_line_name", dropna=False):
        if (
            not isinstance(name, str)
            or rows.bc_line_id.nunique(dropna=False) != 1
            or rows.mesh_name.nunique(dropna=False) != 1
            or rows.bc_line_type.nunique(dropna=False) != 1
        ):
            raise ValueError(
                "Native BC face ownership has ambiguous names, IDs, areas or types"
            )
        area, kind = rows.mesh_name.iloc[0], rows.bc_line_type.iloc[0]
        if not isinstance(area, str) or not isinstance(kind, str):
            raise ValueError("Native BC face ownership lacks its area or type")
        sets[name] = sorted(int(value) for value in rows.face_id)
        areas[name], types[name] = area, kind
    return sets, areas, types


def _forward_arc(ring, start, end):
    from shapely.geometry import LineString
    from shapely.ops import substring

    if end >= start:
        return substring(ring, start, end)
    return LineString(
        list(substring(ring, start, ring.length).coords)
        + list(substring(ring, 0, end).coords)[1:]
    )


def _outward_arc(polygon, coordinates, distance):
    from shapely.geometry import LineString, Point

    if polygon.geom_type != "Polygon" or not polygon.is_valid or polygon.is_empty:
        raise ValueError("External BC requires a valid, nonempty area polygon")
    line = LineString(coordinates)
    if not line.is_simple or line.is_empty or not line.is_valid or line.length == 0:
        raise ValueError(
            "External BC requires a finite simple line with distinct endpoints"
        )
    ring = LineString(polygon.exterior.coords)
    start, end = (ring.project(Point(x)) for x in (line.coords[0], line.coords[-1]))
    if start == end:
        raise ValueError("External BC endpoints project to the same perimeter station")
    candidates = [
        _forward_arc(ring, start, end),
        _forward_arc(ring, end, start).reverse(),
    ]
    arc = min(candidates, key=lambda x: x.hausdorff_distance(line))
    # Selecting an External name must not silently convert a genuine interior line.
    if arc.hausdorff_distance(line) > distance * 2:
        raise ValueError(
            "External BC is not a perimeter arc within twice the offset distance"
        )
    buffered = polygon.buffer(distance, join_style="mitre", mitre_limit=5)
    if buffered.geom_type != "Polygon" or not buffered.is_valid:
        raise ValueError("Outward area buffer is not one valid polygon")
    outer = LineString(buffered.exterior.coords)
    start, end = (outer.project(Point(x)) for x in (arc.coords[0], arc.coords[-1]))
    if start == end:
        raise ValueError("External BC endpoints collapse on the outward perimeter")
    candidates = [
        _forward_arc(outer, start, end),
        _forward_arc(outer, end, start).reverse(),
    ]
    result = min(candidates, key=lambda x: x.hausdorff_distance(arc))
    if not result.is_simple or result.intersection(polygon).length > 0:
        raise ValueError("Buffered External BC is not a simple line outside its area")
    return result


def offset_external_bc_lines(
    geom_file: Path,
    bc_line_names: Sequence[str],
    offset_distance: float,
    *,
    dry_run: bool,
    expected_geometry_sha256: str | None,
    text_only: bool,
) -> dict[str, Any]:
    import numpy as np
    from shapely.geometry import LineString
    from .GeomBcLines import GeomBcLines
    from .GeomStorage import GeomStorage

    if not isinstance(dry_run, bool) or not isinstance(text_only, bool):
        raise ValueError("dry_run and text_only must be booleans")
    distance = float(offset_distance)
    if (
        isinstance(offset_distance, bool)
        or not math.isfinite(distance)
        or distance <= 0
    ):
        raise ValueError(
            "offset_distance must be a finite positive native-CRS distance"
        )
    if (
        isinstance(bc_line_names, str)
        or not bc_line_names
        or len(set(bc_line_names)) != len(bc_line_names)
    ):
        raise ValueError("bc_line_names must be a nonempty sequence of unique names")
    before = geom_file.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    if expected_geometry_sha256 is not None and digest != expected_geometry_sha256:
        raise ValueError("Geometry text changed since the offset was planned")
    original = GeomBcLines.get_bc_lines(geom_file).to_dict("records")
    by_name = {row["name"]: row for row in original}
    if len(by_name) != len(original) or set(bc_line_names) - by_name.keys():
        raise ValueError("External BC names are absent or ambiguous in geometry text")
    areas = GeomStorage.get_storage_area_polygons(geom_file, exclude_2d=False)
    if areas.Name.duplicated().any():
        raise ValueError("Storage area names are ambiguous")
    polygons = dict(zip(areas.Name, areas.geometry))
    edits, records = [], []
    for name in bc_line_names:
        row = by_name[name]
        polygon = polygons.get(row["storage_area"])
        if polygon is None:
            raise ValueError(f"BC {name!r} has no matching area perimeter")
        coordinates = np.asarray(row["coordinates"], dtype=float)
        if not np.isfinite(coordinates).all():
            raise ValueError(f"BC {name!r} has nonfinite coordinates")
        outward = _outward_arc(polygon, coordinates, distance)
        old = LineString(coordinates)
        # Keep a serialized, already-offset line stable on a second staging pass.
        already_outside = (
            old.intersection(polygon).is_empty
            and old.distance(polygon.exterior) >= distance * 0.98
            and old.hausdorff_distance(outward) <= distance * 0.02
        )
        chosen = old if already_outside else outward
        edits.append(
            {
                "name": name,
                "storage_area": row["storage_area"],
                "coordinates": list(chosen.coords),
            }
        )
        records.append(
            {
                "name": name,
                "storage_area": row["storage_area"],
                "before_coordinates": coordinates.tolist(),
                "coordinates": list(chosen.coords),
                "changed": not already_outside,
                "displacement_hausdorff": old.hausdorff_distance(chosen),
            }
        )
    hdf = geom_file.with_suffix(geom_file.suffix + ".hdf")
    native = {}
    if hdf.is_file():
        sets, native_areas, native_types = _native_faces(hdf)
        if not text_only and any(
            name not in sets
            or native_types[name] != "External"
            or native_areas[name] != by_name[name]["storage_area"]
            or not sets[name]
            for name in bc_line_names
        ):
            raise ValueError(
                "Selected External BCs require complete matching native area/type/face evidence; use explicit text_only for first import"
            )
        native = {
            "expected_face_sets": {}
            if text_only
            else {name: sets[name] for name in bc_line_names},
            "bc_areas": {name: by_name[name]["storage_area"] for name in bc_line_names},
            "mesh_fingerprints": _mesh_fingerprints(hdf),
            "text_only": text_only,
        }
    elif not text_only:
        raise ValueError("Compiled geometry HDF is required unless text_only=True")
    else:
        native = {
            "expected_face_sets": {},
            "bc_areas": {name: by_name[name]["storage_area"] for name in bc_line_names},
            "text_only": True,
        }
    report = {
        "geometry_sha256_before": digest,
        "offset_distance": distance,
        "distance_units": "native projected CRS units",
        "dry_run": dry_run,
        "lines": records,
        "native_guard": native,
    }
    if dry_run or not any(row["changed"] for row in records):
        return report
    stat = geom_file.stat()
    try:
        report["authoring"] = GeomBcLines.add_bc_lines(
            geom_file, edits, replace_existing=True
        )
        actual = {
            row["name"]: row
            for row in GeomBcLines.get_bc_lines(geom_file).to_dict("records")
        }
        for row in records:
            line = LineString(actual[row["name"]]["coordinates"])
            polygon = polygons[row["storage_area"]]
            if (
                line.intersection(polygon).length > 0
                or line.distance(polygon.exterior) < distance * 0.98
            ):
                raise ValueError(
                    f"Serialized BC {row['name']!r} loses its outward clearance"
                )
            row["coordinates"] = actual[row["name"]]["coordinates"]
            row["minimum_outward_clearance"] = line.distance(polygon.exterior)
        if {
            name: row for name, row in by_name.items() if name not in bc_line_names
        } != {name: row for name, row in actual.items() if name not in bc_line_names}:
            raise ValueError("Offset authoring changed an unselected BC line")
    except BaseException:
        geom_file.write_bytes(before)
        os.utime(geom_file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        raise
    report["geometry_sha256_after"] = hashlib.sha256(geom_file.read_bytes()).hexdigest()
    return report


def validate_external_bc_face_sets(
    hdf_path: Path,
    expected_face_sets: Mapping[str, Sequence[int]],
    expected_mesh_fingerprints: Mapping[str, Any] | None,
    expected_bc_areas: Mapping[str, str],
) -> dict[str, Any]:
    if expected_mesh_fingerprints is not None and not expected_mesh_fingerprints:
        raise ValueError("Expected mesh fingerprints must not be empty")
    if not expected_face_sets or any(
        not values for values in expected_face_sets.values()
    ):
        raise ValueError(
            "Exact intended External face sets must be nonempty for every line"
        )
    if set(expected_bc_areas) != set(expected_face_sets) or any(
        not isinstance(value, str) or not value for value in expected_bc_areas.values()
    ):
        raise ValueError("Exact intended BC areas must cover every expected face set")
    actual, actual_areas, actual_types = _native_faces(hdf_path)
    differences = {}
    for name, values in expected_face_sets.items():
        if any(
            isinstance(value, bool) or not isinstance(value, Integral)
            for value in values
        ):
            raise ValueError(f"Intended BC face set {name!r} requires integer IDs")
        expected = [int(value) for value in values]
        if len(set(expected)) != len(expected) or any(value < 0 for value in expected):
            raise ValueError(
                f"Intended BC face set {name!r} has invalid or duplicate IDs"
            )
        differences[name] = {
            "missing": sorted(set(expected) - set(actual.get(name, []))),
            "extra": sorted(set(actual.get(name, [])) - set(expected)),
        }
        if (
            actual_areas.get(name) != expected_bc_areas[name]
            or actual_types.get(name) != "External"
        ):
            raise ValueError(
                f"BC_EXTERNAL_FACE_SET_MISMATCH: BC {name!r} has wrong native area or type"
            )
    changed_mesh = expected_mesh_fingerprints is not None and dict(
        expected_mesh_fingerprints
    ) != _mesh_fingerprints(hdf_path)
    if changed_mesh or any(
        row["missing"] or row["extra"] for row in differences.values()
    ):
        raise ValueError(
            f"BC_EXTERNAL_FACE_SET_MISMATCH: mesh_changed={changed_mesh}; faces={differences}"
        )
    return {
        "valid": True,
        "face_sets": {name: actual[name] for name in expected_face_sets},
        "mesh_arrays_byte_identical": None
        if expected_mesh_fingerprints is None
        else True,
    }
