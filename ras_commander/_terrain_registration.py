"""Explicit terrain registration removal for caller-owned Mapper clones."""

import copy
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def remove_terrain_layers(rasmap_path):
    path = Path(rasmap_path)
    tree = ET.parse(path)
    terrain = tree.getroot().find("Terrains")
    names = []
    if terrain is not None:
        for layer in list(terrain.findall("Layer")):
            names.append(layer.get("Name", ""))
            terrain.remove(layer)
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return names


def reassign_result_map_terrains(rasmap_path, terrain_names):
    path = Path(rasmap_path)
    tree = ET.parse(path)
    root = tree.getroot()
    registered = {layer.get("Name") for layer in root.findall("./Terrains/Layer")}
    if not isinstance(terrain_names, dict) or any(
        not isinstance(old, str) or not old or not isinstance(new, str) or not new
        for old, new in terrain_names.items()
    ):
        raise ValueError("Terrain names must map nonempty old names to nonempty new names")
    if set(terrain_names.values()) - registered:
        raise ValueError("Every destination terrain name must be registered in Mapper")
    changes = []
    results = root.find("Results")
    if results is None:
        return changes
    for plan in results.findall("Layer"):
        for element in plan.iter():
            attribute = (
                "Terrain"
                if element.tag == "MapParameters"
                else ("Name" if element.tag == "Terrain" else None)
            )
            old = element.get(attribute) if attribute else None
            if old not in terrain_names or old == terrain_names[old]:
                continue
            new = terrain_names[old]
            element.set(attribute, new)
            changes.append(
                {
                    "plan_name": plan.get("Name", ""),
                    "element": element.tag,
                    "attribute": attribute,
                    "old_terrain_name": old,
                    "new_terrain_name": new,
                }
            )
    if changes:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        os.close(descriptor)
        try:
            tree.write(temporary, encoding="utf-8", xml_declaration=True)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return changes


def create_terrain_sampling_map(
    source_mapper, terrain_hdf, projection_prj, output_mapper, geometry_hdf=None
):
    """Copy one native terrain registration into an isolated export-only Mapper."""
    source, terrain, projection, output = map(
        Path, (source_mapper, terrain_hdf, projection_prj, output_mapper)
    )
    root = ET.parse(source).getroot()
    matches = [
        layer
        for layer in root.findall("./Terrains/Layer")
        if Path(layer.get("Filename", "").replace("\\", "/")).name.casefold()
        == terrain.name.casefold()
    ]
    if len(matches) != 1:
        raise ValueError("Sampling terrain must match exactly one source registration by basename")
    if not terrain.is_file() or not projection.is_file() or output.exists():
        raise ValueError("Sampling inputs must exist and output Mapper must be new")
    if geometry_hdf is not None and not Path(geometry_hdf).is_file():
        raise ValueError("Sampling geometry must exist")
    new = ET.Element(root.tag, root.attrib)
    version = root.find("Version")
    if version is not None:
        new.append(copy.deepcopy(version))
    ET.SubElement(new, "RASProjectionFilename", Filename=str(projection.resolve()))
    layer = copy.deepcopy(matches[0])
    for element in layer.iter():
        if element.get("Filename"):
            element.set("Filename", str(terrain.resolve()))
    ET.SubElement(new, "Terrains").append(layer)
    if geometry_hdf is not None:
        ET.SubElement(
            ET.SubElement(new, "Geometries"),
            "Layer",
            Name="Sample",
            Type="RASGeometry",
            Filename=str(Path(geometry_hdf).resolve()),
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(new).write(output, encoding="utf-8", xml_declaration=True)
    return layer.get("Name", "")


def relocate_rasmap_assets(rasmap_path, assets):
    """Rebind uniquely named copied native assets relatively, preserving map semantics."""
    mapper = Path(rasmap_path)
    by_name = {}
    for item in assets:
        path = Path(item).resolve()
        if not path.is_file():
            raise ValueError("Relocated Mapper assets must exist")
        key = path.name.casefold()
        if key in by_name and by_name[key] != path:
            raise ValueError("Relocated Mapper asset basenames must be unique")
        by_name[key] = path
    tree = ET.parse(mapper)
    changes = []
    for element in tree.getroot().iter():
        filename = element.get("Filename")
        if not filename:
            continue
        key = Path(filename.replace("\\", "/")).name.casefold()
        if key in by_name:
            relative = os.path.relpath(by_name[key], mapper.parent).replace("/", "\\")
            element.set("Filename", relative)
            changes.append({"element": element.tag, "old_filename": filename, "filename": relative})
    tree.write(mapper, encoding="utf-8", xml_declaration=True)
    return changes


def audit_terrain_associations(rasmap_path, geometry_hdfs):
    """Read material terrain/classification/projection associations without mutation."""
    from .geom.GeomMesh import GeomMesh

    mapper = Path(rasmap_path)
    root = ET.parse(mapper).getroot()
    registrations = root.findall("./Terrains/Layer")
    names = {layer.get("Name", "") for layer in registrations}
    registered_paths = {
        (mapper.parent / Path(layer.get("Filename", "").replace("\\", os.sep))).resolve()
        for layer in registrations
    }
    paths, problems = [], []
    elements = list(root.findall("RASProjectionFilename"))
    for section in ("Terrains", "LandCover", "Infiltration", "Soils"):
        element = root.find(section)
        if element is not None:
            elements.extend(element.iter())
    for element in elements:
        filename = element.get("Filename")
        if not filename:
            continue
        path = Path(filename.replace("\\", os.sep))
        relative = not path.is_absolute()
        resolved = path if path.is_absolute() else mapper.parent / path
        row = {
            "element": element.tag,
            "filename": filename,
            "relative": relative,
            "exists": resolved.is_file(),
        }
        paths.append(row)
        if not relative or not row["exists"]:
            problems.append(row)
    stale = []
    for plan in root.findall("./Results/Layer"):
        for element in plan.iter():
            name = (
                element.get("Terrain")
                if element.tag == "MapParameters"
                else (element.get("Name") if element.tag == "Terrain" else None)
            )
            if name and name not in names:
                stale.append({"plan_name": plan.get("Name", ""), "terrain_name": name})
    geometry = []
    if not geometry_hdfs:
        problems.append({"association": "terrain_hdf_path", "message": "No geometry supplied"})
    for item in geometry_hdfs:
        hdf = Path(item)
        association = GeomMesh.get_geometry_association(hdf, resolve_paths=False)
        if not association.get("terrain_hdf_path"):
            problems.append(
                {
                    "geometry": hdf.name,
                    "association": "terrain_hdf_path",
                    "message": "Missing terrain association",
                }
            )
        for key, value in association.items():
            if not key.endswith("_hdf_path") or not value:
                continue
            path = Path(str(value).replace("\\", os.sep))
            resolved = path if path.is_absolute() else hdf.parent / path
            row = {
                "geometry": hdf.name,
                "association": key,
                "filename": str(value),
                "relative": not path.is_absolute(),
                "exists": resolved.is_file(),
            }
            geometry.append(row)
            if not row["relative"] or not row["exists"]:
                problems.append(row)
            elif key == "terrain_hdf_path" and resolved.resolve() not in registered_paths:
                problems.append({**row, "message": "Terrain is not registered in Mapper"})
    return {
        "status": "pass" if registrations and not problems and not stale else "hold",
        "terrain_names": sorted(names),
        "paths": paths,
        "geometry": geometry,
        "stale_result_terrains": stale,
        "problems": problems,
    }
