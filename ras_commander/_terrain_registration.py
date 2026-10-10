"""Explicit terrain registration removal for caller-owned Mapper clones."""

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
