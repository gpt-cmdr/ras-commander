"""Input and HDF checks shared by Windows Python and the test suite.

This preprocessing image requires an existing 2D geometry HDF. Model inputs
are disposable copies; terrain and projection dependencies may be read-only.
"""

import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import h5py
import numpy as np


def text_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8").rstrip("\x00")
    return str(value).rstrip("\x00")


def dependency_path(parent, value):
    path = Path(text_value(value).replace("\\", os.sep))
    return (parent / path).resolve()


def require_file(path):
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Missing or empty model input: " + str(path))
    # Check actual readability before allowing HEC-RAS to rewrite geometry.
    with path.open("rb") as stream:
        stream.read(1)
    return path


def selected_inputs(project, plan):
    project = Path(project)
    plan_path = require_file(project.with_suffix(".p" + plan))
    fields = {}
    for line in plan_path.read_bytes().decode("utf-8", errors="replace").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key.strip()] = value.strip()
    geometry = fields.get("Geom File", "")
    flow = fields.get("Flow File", "")
    if not re.fullmatch(r"g\d{2}", geometry, re.I):
        raise ValueError("Selected plan must identify a geometry such as g01")
    if not re.fullmatch(r"u\d{2}", flow, re.I):
        raise ValueError("Selected plan must identify an unsteady flow file such as u01")
    return [require_file(p) for p in (
        project, plan_path, project.with_suffix("." + geometry.lower()),
        project.with_suffix("." + flow.lower()),
    )]


def mesh_summary(path, expected=None, hydraulic=False):
    """Require the same 2D areas/cell counts; face counts may change by version."""
    summary = {}
    with h5py.File(path, "r") as hdf:
        areas = hdf.get("Geometry/2D Flow Areas")
        if areas is None:
            raise ValueError(str(path) + ": missing Geometry/2D Flow Areas")
        for name, area in areas.items():
            if not isinstance(area, h5py.Group):
                continue
            coords = area.get("Cells Center Coordinate")
            if coords is None or coords.ndim != 2 or coords.shape[1] != 2 or not len(coords):
                raise ValueError(str(path) + ": missing or empty 2D cells in " + name)
            cells = len(coords)
            record = {"cells": cells}
            if hydraulic:
                for label, rows, width in (
                    ("Cells Volume Elevation", cells, 2),
                    ("Faces Area Elevation", None, 4),
                ):
                    info = area.get(label + " Info")
                    values = area.get(label + " Values")
                    if (info is None or values is None or info.ndim != 2
                            or info.shape[1] != 2 or not len(info)
                            or values.ndim != 2 or values.shape[1] != width or not len(values)
                            or (rows is not None and len(info) != rows)):
                        raise ValueError(str(path) + ": invalid " + label + " tables in " + name)
                    indexes = info[:]
                    if (np.any(indexes < 0) or not np.any(indexes[:, 1] > 0)
                            or np.any(indexes[:, 0] + indexes[:, 1] > len(values))
                            or not np.isfinite(values[:]).all()):
                        raise ValueError(str(path) + ": invalid " + label + " table values in " + name)
                    record[label] = {"entries": len(info), "values": len(values)}
            summary[name] = record
    if not summary:
        raise ValueError(str(path) + ": no populated 2D areas")
    if expected is not None:
        if set(summary) != set(expected) or any(
                summary[name]["cells"] != expected[name]["cells"] for name in expected):
            raise ValueError(str(path) + ": 2D areas or cell counts changed during preprocessing")
    return summary


def preflight(project, plan):
    """Read every required dependency before modifying any model file."""
    inputs = selected_inputs(project, plan)
    geometry_hdf = require_file(Path(str(inputs[2]) + ".hdf"))
    baseline = mesh_summary(geometry_hdf)
    rasmap = require_file(Path(project).with_suffix(".rasmap"))
    root = ET.parse(rasmap).getroot()
    dependencies = set()
    terrain_paths = set()
    projection = root.find(".//RASProjectionFilename")
    if projection is None or not projection.get("Filename"):
        raise ValueError("RAS Mapper must declare a projection file")
    dependencies.add(dependency_path(rasmap.parent, projection.get("Filename")))
    with h5py.File(geometry_hdf, "r") as hdf:
        for group in [hdf["Geometry"], *(
                hdf["Geometry/2D Flow Areas/" + name] for name in baseline)]:
            value = group.attrs.get("Terrain Filename")
            if value is not None and text_value(value).strip():
                terrain_paths.add(dependency_path(geometry_hdf.parent, value))
    for layer in root.findall(".//Terrains//Layer"):
        if layer.get("Type") == "TerrainLayer" and layer.get("Filename"):
            terrain_paths.add(dependency_path(rasmap.parent, layer.get("Filename")))
    if not terrain_paths:
        raise ValueError("Model does not declare a terrain HDF")
    for terrain in sorted(terrain_paths):
        require_file(terrain)
        dependencies.add(terrain)
        with h5py.File(terrain, "r") as hdf:
            raster_paths = []
            def collect(_name, obj):
                value = obj.attrs.get("File")
                if value is not None and text_value(value).strip():
                    raster_paths.append(dependency_path(terrain.parent, value))
            hdf.visititems(collect)
            if not raster_paths:
                raise ValueError("Terrain HDF has no referenced raster files: " + str(terrain))
            dependencies.update(raster_paths)
    for path in sorted(dependencies):
        require_file(path)
    return inputs, geometry_hdf, baseline, sorted(str(p) for p in dependencies)


def normalize_inputs(paths):
    """Convert only HEC-RAS text inputs to CRLF, preserving every other byte."""
    changed = []
    for path in paths:
        original = path.read_bytes()
        if b"\x00" in original:
            raise ValueError("Expected a single-byte HEC-RAS text file: " + str(path))
        normalized = original.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        normalized = normalized.replace(b"\n", b"\r\n")
        if normalized != original:
            path.write_bytes(normalized)
            changed.append(path.name)
    return changed


def validate_outputs(geometry_hdf, tmp_hdf, baseline):
    return {
        "geometry": mesh_summary(geometry_hdf, baseline, hydraulic=True),
        "temporary_plan": mesh_summary(tmp_hdf, baseline, hydraulic=True),
    }
