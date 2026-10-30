"""Lossless subsets of native polyline and constant-elevation polygon edits."""

from __future__ import annotations

import copy
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import h5py
import numpy as np

from .fast_hdf import read_typed, release_native_sessions

TABLES = frozenset(
    {
        "Attributes",
        "Polyline Info",
        "Polyline Parts",
        "Polyline Points",
        "Profile Info",
        "Profile Values",
    }
)
POLYGON_TABLES = frozenset(
    {"Attributes", "Polygon Info", "Polygon Parts", "Polygon Points"}
)


def _prefix(arrays):
    return "Polygon" if "Polygon Info" in arrays else "Polyline"


def _validated_group(group):
    if set(group.keys()) not in (TABLES, POLYGON_TABLES):
        raise ValueError(f"Unsupported modification layout: {group.name}")
    arrays = {name: read_typed(group[name], slice(None)) for name in group}
    prefix = _prefix(arrays)
    count = len(arrays["Attributes"])
    if arrays[prefix + " Info"].shape != (count, 4) or (
        prefix == "Polyline" and arrays["Profile Info"].shape != (count, 2)
    ):
        raise ValueError(f"Inconsistent modification feature indexes: {group.name}")
    if arrays[prefix + " Parts"].ndim != 2 or arrays[prefix + " Parts"].shape[1] != 2:
        raise ValueError(f"Invalid modification part indexes: {group.name}")
    points = arrays[prefix + " Points"]
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError(f"Invalid modification points: {group.name}")
    if prefix == "Polygon":
        fields = arrays["Attributes"].dtype.names or ()
        required = {
            "Elevation Type",
            "Elevation Value",
            "Generate Boundary Elevations",
            "Use ShapeFile Z Elevations",
        }
        if not required.issubset(fields):
            raise ValueError(f"Unsupported polygon parameters: {group.name}")
        for record in arrays["Attributes"]:
            kind = record["Elevation Type"]
            kind = kind.decode() if isinstance(kind, bytes) else str(kind)
            if (
                kind != "SetValue"
                or not np.isfinite(record["Elevation Value"])
                or record["Generate Boundary Elevations"]
                or record["Use ShapeFile Z Elevations"]
            ):
                raise ValueError(f"Unsupported polygon elevation method: {group.name}")
    for feature in range(count):
        start, size, part_start, part_size = map(int, arrays[prefix + " Info"][feature])
        profile_start, profile_size = (
            map(int, arrays["Profile Info"][feature])
            if prefix == "Polyline"
            else (0, 0)
        )
        if (
            start < 0
            or size < 1
            or start + size > len(points)
            or part_start < 0
            or part_size < 1
            or part_start + part_size > len(arrays[prefix + " Parts"])
            or profile_start < 0
            or profile_size < 0
            or profile_start + profile_size > len(arrays.get("Profile Values", []))
        ):
            raise ValueError(
                f"Modification indexes leave their tables: {group.name}/{feature}"
            )
        native_parts = arrays[prefix + " Parts"][part_start : part_start + part_size]
        if prefix == "Polygon" and any(int(length) < 4 for _, length in native_parts):
            raise ValueError(f"Invalid polygon ring: {group.name}/{feature}")
        if any(int(length) == 1 for _, length in native_parts) and not (
            size == 1
            and part_size == 1
            and int(native_parts[0, 0]) == 0
            and int(native_parts[0, 1]) == 1
        ):
            raise ValueError(
                f"Unsupported mixed degenerate parts: {group.name}/{feature}"
            )
        for offset, length in native_parts:
            if int(offset) < 0 or int(length) < 1 or int(offset + length) > size:
                raise ValueError(
                    f"Modification part leaves its feature: {group.name}/{feature}"
                )
        if prefix == "Polygon":
            from shapely.geometry import Polygon

            rings = [
                points[start + int(p) : start + int(p + n)] for p, n in native_parts
            ]
            if any(not np.array_equal(ring[0], ring[-1]) for ring in rings):
                raise ValueError(f"Unclosed polygon ring: {group.name}/{feature}")
            polygon = Polygon(rings[0], rings[1:])
            if polygon.is_empty or not polygon.is_valid:
                raise ValueError(f"Invalid polygon geometry: {group.name}/{feature}")
    return arrays


def read_features(terrain_hdf_path, crs):
    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString, Point, Polygon

    if crs is None:
        raise ValueError("A modification CRS is required")
    rows = []
    with h5py.File(terrain_hdf_path, "r") as file:
        for name, group in file.get("Modifications", {}).items():
            arrays = _validated_group(group)
            prefix = _prefix(arrays)
            for index, attributes in enumerate(arrays["Attributes"]):
                point_start, _, start, count = map(int, arrays[prefix + " Info"][index])
                native_parts = arrays[prefix + " Parts"][start : start + count]
                if prefix == "Polygon":
                    rings = [
                        arrays["Polygon Points"][
                            point_start + int(p) : point_start + int(p + n)
                        ]
                        for p, n in native_parts
                    ]
                    if any(not np.array_equal(ring[0], ring[-1]) for ring in rings):
                        raise ValueError(f"Unclosed polygon ring: {name}/{index}")
                    geometry = Polygon(rings[0], rings[1:])
                    if geometry.is_empty or not geometry.is_valid:
                        raise ValueError(f"Invalid polygon geometry: {name}/{index}")
                elif any(int(n) == 1 for _, n in native_parts):
                    if count != 1 or int(native_parts[0, 1]) != 1:
                        raise ValueError(
                            f"Unsupported mixed degenerate parts: {name}/{index}"
                        )
                    p = point_start + int(native_parts[0, 0])
                    geometry = Point(arrays["Polyline Points"][p, :2])
                else:
                    lines = [
                        LineString(
                            arrays["Polyline Points"][
                                point_start + int(p) : point_start + int(p + n), :2
                            ]
                        )
                        for p, n in native_parts
                    ]
                    geometry = lines[0] if len(lines) == 1 else MultiLineString(lines)
                values = {key: attributes[key] for key in attributes.dtype.names or ()}
                extent = next(
                    (
                        float(values[key])
                        for key in ("Max Reach", "Max Extent")
                        if key in values
                    ),
                    0.0 if prefix == "Polygon" else None,
                )
                if extent is None or not np.isfinite(extent) or extent < 0:
                    raise ValueError(
                        f"Modification support distance is unavailable: {name}/{index}"
                    )
                rows.append(
                    {
                        "group_name": name,
                        "feature_index": index,
                        "support_distance": extent,
                        "geometry": geometry,
                    }
                )
    frame = gpd.GeoDataFrame(
        rows,
        columns=["group_name", "feature_index", "support_distance", "geometry"],
        geometry="geometry",
        crs=crs,
    )
    return frame.astype({"feature_index": "int64", "support_distance": "float64"})


def _subset_arrays(arrays, indexes):
    prefix = _prefix(arrays)
    points, parts, profiles, line_info, profile_info = [], [], [], [], []
    point_offset = part_offset = profile_offset = 0
    for index in indexes:
        start, count, part_start, part_count = map(int, arrays[prefix + " Info"][index])
        profile_start, profile_count = (
            map(int, arrays["Profile Info"][index]) if prefix == "Polyline" else (0, 0)
        )
        points.append(arrays[prefix + " Points"][start : start + count])
        new_parts = arrays[prefix + " Parts"][
            part_start : part_start + part_count
        ].copy()
        parts.append(new_parts)
        if prefix == "Polyline":
            profiles.append(
                arrays["Profile Values"][profile_start : profile_start + profile_count]
            )
        line_info.append([point_offset, count, part_offset, part_count])
        profile_info.append([profile_offset, profile_count])
        point_offset += count
        part_offset += part_count
        profile_offset += profile_count
    result = {
        "Attributes": arrays["Attributes"][indexes],
        prefix + " Points": np.concatenate(points),
        prefix + " Parts": np.concatenate(parts),
        prefix + " Info": np.asarray(line_info, dtype=arrays[prefix + " Info"].dtype),
    }
    if prefix == "Polyline":
        result.update(
            {
                "Profile Values": np.concatenate(profiles),
                "Profile Info": np.asarray(
                    profile_info, dtype=arrays["Profile Info"].dtype
                ),
            }
        )
    return result


def _resolve_layer(root, mapper, hdf, *, source):
    terrains = root.find("Terrains")
    if terrains is None:
        raise ValueError("Mapper has no terrain registrations")
    exact, basename = [], []
    for layer in terrains.findall("Layer"):
        filename = layer.get("Filename", "").replace("\\", "/")
        if not filename:
            continue
        candidate = Path(filename)
        if not candidate.is_absolute():
            candidate = mapper.parent / candidate
        if candidate.resolve() == hdf.resolve():
            exact.append(layer)
        if Path(filename).name.casefold() == hdf.name.casefold():
            basename.append(layer)
    if len(exact) == 1:
        return exact[0], "resolved_path"
    if len(exact) > 1 or not source or len(basename) != 1:
        raise ValueError("Terrain registration is missing or ambiguous")
    return basename[0], "unique_source_basename"


def copy_features(
    source_hdf,
    destination_hdf,
    source_rasmap,
    destination_rasmap,
    feature_indexes,
    *,
    group_prefix="",
    append=False,
):
    from .terrain.RasTerrainModWriter import RasTerrainModWriter

    source_hdf, destination_hdf = Path(source_hdf), Path(destination_hdf)
    if (
        not isinstance(append, bool)
        or not isinstance(group_prefix, str)
        or any(c in group_prefix for c in ("/", "\\", "\x00"))
    ):
        raise ValueError(
            "append must be Boolean and group_prefix must be a native group-name prefix"
        )
    source_rasmap, destination_rasmap = Path(source_rasmap), Path(destination_rasmap)
    if (
        (destination_hdf.exists() and os.path.samefile(source_hdf, destination_hdf))
        or (
            destination_rasmap.exists()
            and os.path.samefile(source_rasmap, destination_rasmap)
        )
        or source_hdf.resolve() == destination_hdf.resolve()
        or source_rasmap.resolve() == destination_rasmap.resolve()
    ):
        raise ValueError("Source and destination terrain/Mapper paths must be distinct")
    source_tree, destination_tree = (
        ET.parse(source_rasmap),
        ET.parse(destination_rasmap),
    )
    source_layer, source_basis = _resolve_layer(
        source_tree.getroot(), source_rasmap, source_hdf, source=True
    )
    destination_layer, _ = _resolve_layer(
        destination_tree.getroot(), destination_rasmap, destination_hdf, source=False
    )
    existing_registration = destination_layer.findall(
        "Layer[@Type='ElevationModificationGroup']"
    )
    if not append and any(
        x.get("Type") == "ElevationModificationGroup"
        for x in destination_layer.findall("Layer")
    ):
        raise ValueError("Destination Mapper already contains terrain modifications")
    selected = {}
    summaries = []
    with (
        h5py.File(source_hdf, "r") as source,
        h5py.File(destination_hdf, "r") as destination,
    ):
        if "Modifications" in destination and not append:
            raise ValueError(
                "Destination terrain already contains terrain modifications"
            )
        groups = source.get("Modifications", {})
        existing_names = set(destination.get("Modifications", {}))
        if append:
            if existing_names and len(existing_registration) != 1:
                raise ValueError("Append requires one existing modification collection")
            existing_layers = [
                child
                for group in existing_registration
                for child in group
                if child.tag == "Layer"
            ]
            mapper_names = [child.get("Name") for child in existing_layers]
            if set(mapper_names) != existing_names or len(mapper_names) != len(
                set(mapper_names)
            ):
                raise ValueError("Existing HDF and Mapper modification names differ")
            if any(
                child.tag != "Layer"
                for group in existing_registration
                for child in group
            ):
                raise ValueError("Append of collection-level controls is unsupported")
        if set(feature_indexes) - set(groups):
            raise ValueError("A selected modification group is absent from the source")
        for name, requested in feature_indexes.items():
            arrays = _validated_group(groups[name])
            if any(
                isinstance(i, bool) or not isinstance(i, (int, np.integer))
                for i in requested
            ):
                raise ValueError("Modification feature indexes must be integers")
            indexes = sorted(set(map(int, requested)))
            if len(indexes) != len(requested) or any(
                i < 0 or i >= len(arrays["Attributes"]) for i in indexes
            ):
                raise ValueError(
                    "Modification feature indexes are duplicate or out of range"
                )
            if indexes:
                target_name = group_prefix + name
                if target_name in existing_names:
                    raise ValueError(
                        "Destination modification group name already exists"
                    )
                selected[name] = _subset_arrays(arrays, indexes)
            summaries.append(
                {
                    "group_name": name,
                    "geometry_type": _prefix(arrays),
                    "destination_group_name": group_prefix + name,
                    "source_features": len(arrays["Attributes"]),
                    "source_registration_basis": source_basis,
                    "source_registration_name": source_layer.get("Name", ""),
                    "retained_feature_indexes": indexes,
                }
            )
        registered = []
        for group in source_layer.findall("Layer"):
            if group.get("Type") != "ElevationModificationGroup":
                continue
            derivative = copy.deepcopy(group)
            for child in list(derivative):
                if child.tag == "Layer":
                    if child.get("Name") not in selected:
                        derivative.remove(child)
                    else:
                        registered.append(child.get("Name"))
                        child.set("Name", group_prefix + child.get("Name"))
            if any(child.tag == "Layer" for child in derivative):
                filename = os.path.relpath(
                    destination_hdf, destination_rasmap.parent
                ).replace("/", "\\")
                for element in derivative.iter():
                    if "Filename" in element.attrib:
                        element.set("Filename", filename)
                if append and existing_registration:
                    if len(existing_registration) != 1:
                        raise ValueError(
                            "Append requires one existing modification collection"
                        )
                    previous = existing_registration[0]
                    # Collection settings apply to all children. Preserve the
                    # source settings exactly or reject before changing either file.
                    filtered = lambda element: {
                        k: v
                        for k, v in element.attrib.items()
                        if k not in {"Name", "Filename", "Expanded"}
                    }
                    if filtered(previous) != filtered(derivative):
                        raise ValueError(
                            "Parent modification collection settings differ"
                        )
                    for item in list(derivative):
                        if item.tag != "Layer":
                            raise ValueError(
                                "Append of collection-level controls is unsupported"
                            )
                        previous.append(item)
                else:
                    destination_layer.append(derivative)
        if set(registered) != set(selected) or len(registered) != len(set(registered)):
            raise ValueError(
                "Selected modifications have no unique source Mapper registration"
            )
    with tempfile.TemporaryDirectory(
        prefix="terrain-mod-copy-", dir=destination_hdf.parent
    ) as temporary:
        staged_hdf = Path(temporary) / "terrain.hdf"
        staged_xml = destination_rasmap.with_name(
            destination_rasmap.name + ".modifications.tmp"
        )
        if staged_xml.exists():
            raise ValueError("Destination Mapper has a pending modification copy")
        shutil.copyfile(destination_hdf, staged_hdf)
        with (
            h5py.File(source_hdf, "r") as source,
            h5py.File(staged_hdf, "r+") as destination,
        ):
            if selected:
                existing_modifications = "Modifications" in destination
                mods = destination.require_group("Modifications")
                original_attrs = source["Modifications"].attrs
                if (
                    append
                    and existing_modifications
                    and (
                        set(mods.attrs) != set(original_attrs)
                        or any(
                            not np.array_equal(mods.attrs[k], original_attrs[k])
                            for k in mods.attrs
                        )
                    )
                ):
                    raise ValueError("Parent modification root attributes differ")
                mods.attrs.update(original_attrs)
                for name, arrays in selected.items():
                    group = mods.create_group(group_prefix + name)
                    group.attrs.update(source["Modifications"][name].attrs)
                    for table, data in arrays.items():
                        result = RasTerrainModWriter._create_hdf_dataset(
                            group, table, data
                        )
                        result.attrs.update(source["Modifications"][name][table].attrs)
        destination_tree.write(staged_xml, encoding="utf-8", xml_declaration=True)
        old_xml = destination_rasmap.read_bytes()
        backup = Path(temporary) / "original.hdf"
        shutil.copyfile(destination_hdf, backup)
        try:
            release_native_sessions(staged_hdf, destination_hdf)
            os.replace(staged_hdf, destination_hdf)
            os.replace(staged_xml, destination_rasmap)
        except Exception:
            shutil.copyfile(backup, destination_hdf)
            destination_rasmap.write_bytes(old_xml)
            raise
        finally:
            staged_xml.unlink(missing_ok=True)
    return summaries


def export_features(source_hdf, source_rasmap, output_dir, feature_indexes):
    """Write a modification-only native boundary bundle without terrain grids."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError("Modification bundle destination already exists")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="modification-export-", dir=output_dir.parent
    ) as tmp:
        staged = Path(tmp) / "bundle"
        staged.mkdir()
        hdf = staged / "modifications.hdf"
        mapper = staged / "modifications.rasmap"
        with h5py.File(source_hdf, "r") as source, h5py.File(hdf, "w") as destination:
            destination.attrs.update(source.attrs)
        root = ET.Element("RASMapper")
        terrains = ET.SubElement(root, "Terrains")
        ET.SubElement(
            terrains,
            "Layer",
            Name="Modifications",
            Type="TerrainLayer",
            Filename=hdf.name,
        )
        ET.ElementTree(root).write(mapper, encoding="utf-8", xml_declaration=True)
        summaries = copy_features(
            source_hdf, hdf, source_rasmap, mapper, feature_indexes
        )
        release_native_sessions(staged, output_dir)
        os.replace(staged, output_dir)
    return summaries
