"""Explicit terrain registration removal for caller-owned Mapper clones."""

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
                dict(
                    plan_name=plan.get("Name", ""),
                    element=element.tag,
                    attribute=attribute,
                    old_terrain_name=old,
                    new_terrain_name=new,
                )
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
