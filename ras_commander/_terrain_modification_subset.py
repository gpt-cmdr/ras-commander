"""Lossless subsets of native polyline terrain modifications."""

from __future__ import annotations

import copy
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import h5py
import numpy as np

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


def _validated_group(group):
    if set(group.keys()) != TABLES:
        raise ValueError(f"Unsupported modification layout: {group.name}")
    arrays = {name: group[name][:] for name in TABLES}
    count = len(arrays["Attributes"])
    if arrays["Polyline Info"].shape != (count, 4) or arrays["Profile Info"].shape != (
        count,
        2,
    ):
        raise ValueError(f"Inconsistent modification feature indexes: {group.name}")
    if arrays["Polyline Parts"].ndim != 2 or arrays["Polyline Parts"].shape[1] != 2:
        raise ValueError(f"Invalid modification part indexes: {group.name}")
    for feature in range(count):
        start, size, part_start, part_size = map(int, arrays["Polyline Info"][feature])
        profile_start, profile_size = map(int, arrays["Profile Info"][feature])
        if (
            start < 0
            or size < 1
            or start + size > len(arrays["Polyline Points"])
            or part_start < 0
            or part_size < 1
            or part_start + part_size > len(arrays["Polyline Parts"])
            or profile_start < 0
            or profile_size < 0
            or profile_start + profile_size > len(arrays["Profile Values"])
        ):
            raise ValueError(
                f"Modification indexes leave their tables: {group.name}/{feature}"
            )
        native_parts = arrays["Polyline Parts"][part_start : part_start + part_size]
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
    return arrays


def read_features(terrain_hdf_path, crs):
    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString, Point

    if crs is None:
        raise ValueError("A modification CRS is required")
    rows = []
    with h5py.File(terrain_hdf_path, "r") as file:
        for name, group in file.get("Modifications", {}).items():
            arrays = _validated_group(group)
            for index, attributes in enumerate(arrays["Attributes"]):
                point_start, _, start, count = map(int, arrays["Polyline Info"][index])
                native_parts = arrays["Polyline Parts"][start : start + count]
                if any(int(n) == 1 for _, n in native_parts):
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
                    None,
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
    points, parts, profiles, line_info, profile_info = [], [], [], [], []
    point_offset = part_offset = profile_offset = 0
    for index in indexes:
        start, count, part_start, part_count = map(int, arrays["Polyline Info"][index])
        profile_start, profile_count = map(int, arrays["Profile Info"][index])
        points.append(arrays["Polyline Points"][start : start + count])
        new_parts = arrays["Polyline Parts"][
            part_start : part_start + part_count
        ].copy()
        parts.append(new_parts)
        profiles.append(
            arrays["Profile Values"][profile_start : profile_start + profile_count]
        )
        line_info.append([point_offset, count, part_offset, part_count])
        profile_info.append([profile_offset, profile_count])
        point_offset += count
        part_offset += part_count
        profile_offset += profile_count
    return {
        "Attributes": arrays["Attributes"][indexes],
        "Polyline Points": np.concatenate(points),
        "Polyline Parts": np.concatenate(parts),
        "Profile Values": np.concatenate(profiles),
        "Polyline Info": np.asarray(line_info, dtype=arrays["Polyline Info"].dtype),
        "Profile Info": np.asarray(profile_info, dtype=arrays["Profile Info"].dtype),
    }


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
):
    source_hdf, destination_hdf = Path(source_hdf), Path(destination_hdf)
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
    if any(
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
        if "Modifications" in destination:
            raise ValueError(
                "Destination terrain already contains terrain modifications"
            )
        groups = source.get("Modifications", {})
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
                selected[name] = _subset_arrays(arrays, indexes)
            summaries.append(
                {
                    "group_name": name,
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
            if any(child.tag == "Layer" for child in derivative):
                filename = os.path.relpath(
                    destination_hdf, destination_rasmap.parent
                ).replace("/", "\\")
                for element in derivative.iter():
                    if "Filename" in element.attrib:
                        element.set("Filename", filename)
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
                mods = destination.create_group("Modifications")
                mods.attrs.update(source["Modifications"].attrs)
                for name, arrays in selected.items():
                    group = mods.create_group(name)
                    group.attrs.update(source["Modifications"][name].attrs)
                    for table, data in arrays.items():
                        result = group.create_dataset(table, data=data)
                        result.attrs.update(source["Modifications"][name][table].attrs)
        destination_tree.write(staged_xml, encoding="utf-8", xml_declaration=True)
        old_xml = destination_rasmap.read_bytes()
        backup = Path(temporary) / "original.hdf"
        shutil.copyfile(destination_hdf, backup)
        try:
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
        os.replace(staged, output_dir)
    return summaries
