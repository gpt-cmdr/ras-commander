"""HDF input preparation for the optional plain-sloping Rust engine.

This module reads inputs only. It never loads a native HEC-RAS assembly and
does not manufacture hydraulic values from a captured native reference.
"""

from pathlib import Path

from .. import get_logger, log_call

logger = get_logger(__name__)

_BINARY_FIELDS = {
    "cell_info": ("Cells Face and Orientation Info", "<i4"),
    "cell_faces": ("Cells Face and Orientation Values", "<i4"),
    "cell_minimum": ("Cells Minimum Elevation", "<f4"),
    "face_vertices": ("Faces FacePoint Indexes", "<i4"),
    "face_cells": ("Faces Cell Indexes", "<i4"),
    "face_info": ("Faces Perimeter Info", "<i4"),
    "face_points": ("Faces Perimeter Values", "<f8"),
    "face_minimum": ("Faces Minimum Elevation", "<f4"),
    "vertices": ("FacePoints Coordinate", "<f8"),
    "vertex_info": ("FacePoints Face and Orientation Info", "<i4"),
    "vertex_faces": ("FacePoints Face and Orientation Values", "<i4"),
}


@log_call
def write_binary_mesh_inputs(hdf_path, output_folder, *, threads=4, include_max=True):
    """Stage typed HDF arrays without constructing per-cell Python objects."""
    import json
    import h5py
    import numpy as np
    import shapely
    from .. import HdfMesh, HdfResultsMesh
    from ..fast_hdf import backend_scope, read_datasets
    from ._horizontal_engine import _write_array
    from .RasFim import RasFim

    path = Path(hdf_path).resolve(strict=True)
    root = Path(output_folder)
    RasFim.validate_2d_model(path)
    with backend_scope("rust"):
        centers = HdfMesh.get_mesh_cell_points(path, include_ghost_cells=True)
        names = HdfMesh.get_mesh_area_names(path)
    if centers.empty or not names:
        raise ValueError("Sloping mapping requires readable 2D cell centres")
    files = []
    meshes = []
    max_values = []
    with h5py.File(path, "r") as source:
        for index, name in enumerate(names):
            prefix = f"Geometry/2D Flow Areas/{name}/"
            summary = (
                HdfResultsMesh.get_mesh_summary_output_group(
                    source, name, "Maximum Water Surface"
                )
                if include_max
                else None
            )
            arrays = read_datasets(
                source,
                [prefix + field for field, _ in _BINARY_FIELDS.values()]
                + ([summary.name] if summary is not None else []),
                backend="rust",
                threads=threads,
            )
            points = centers.loc[centers.mesh_name == name].sort_values("cell_id")
            if points.cell_id.tolist() != list(range(len(points))):
                raise ValueError("Non-contiguous sloping cell ids")
            descriptors = {}

            def stage(key, values, dtype):
                array = np.ascontiguousarray(values, dtype=dtype)
                expected_columns = 1 if key.endswith("minimum") else 2
                array = array.reshape(-1, expected_columns)
                filename = f"mesh-{index}-{key}.bin"
                _write_array(root / filename, array)
                descriptors[key] = dict(path=filename, rows=len(array))

            stage("centers", shapely.get_coordinates(points.geometry), "<f8")
            for key, (field, dtype) in _BINARY_FIELDS.items():
                stage(key, arrays[prefix + field], dtype)
            if summary is not None:
                values = np.asarray(arrays[summary.name], dtype="<f4")
                if values.shape != (2, len(points)):
                    raise ValueError("Unsupported sloping Max profile dimensions")
                max_values.append(np.ascontiguousarray(values[0]))
            else:
                max_values.append(None)
            metadata = dict(schema="ras-commander-sloping-mesh/1", arrays=descriptors)
            filename = f"mesh-{index}.json"
            files.append(filename)
            (root / filename).write_text(json.dumps(metadata), encoding="utf-8")
            meshes.append(dict(mesh_name=name, cell_count=len(points)))
    return files, meshes, max_values


@log_call
def read_max_mesh_inputs(hdf_path, *, threads=4):
    """Read immutable topology and Max WSE, including virtual perimeter cells.

    The current development schema targets the qualified 7.0.1 plain-sloping
    method. Face application points are reconstructed by Rust from polylines
    and cell centres. No rendering or additional depth filter occurs here.
    """
    import h5py
    import numpy as np

    from .. import HdfMesh, HdfResultsMesh
    from ..fast_hdf import backend_scope, read_datasets
    from .RasFim import RasFim

    path = Path(hdf_path).resolve(strict=True)
    RasFim.validate_2d_model(path)
    with backend_scope("rust"):
        centers = HdfMesh.get_mesh_cell_points(path, include_ghost_cells=True)
        names = HdfMesh.get_mesh_area_names(path)
    if centers.empty or not names:
        raise ValueError("Sloping mapping requires readable 2D cell centres")
    fields = (
        "Cells Face and Orientation Info",
        "Cells Face and Orientation Values",
        "Cells Minimum Elevation",
        "Faces FacePoint Indexes",
        "Faces Cell Indexes",
        "Faces Perimeter Info",
        "Faces Perimeter Values",
        "Faces Minimum Elevation",
        "FacePoints Coordinate",
        "FacePoints Face and Orientation Info",
        "FacePoints Face and Orientation Values",
    )
    products = []
    with h5py.File(path, "r") as source:
        for name in names:
            prefix = f"Geometry/2D Flow Areas/{name}/"
            paths = [prefix + field for field in fields]
            summary = HdfResultsMesh.get_mesh_summary_output_group(
                source, name, "Maximum Water Surface"
            )
            arrays = read_datasets(
                source, paths + [summary.name], backend="rust", threads=threads
            )
            data = {field: arrays[prefix + field] for field in fields}
            points = centers.loc[centers.mesh_name == name].sort_values("cell_id")
            if points.cell_id.tolist() != list(range(len(points))):
                raise ValueError(f"Non-contiguous sloping cell ids in {name!r}")

            def incidence(info_name, values_name):
                info, values = data[info_name], data[values_name]
                if (
                    info.ndim != 2
                    or info.shape[1] != 2
                    or values.ndim != 2
                    or values.shape[1] != 2
                ):
                    raise ValueError(f"Unsupported incidence layout in {name!r}")
                result = []
                expected = 0
                for start, count in info:
                    start, count = int(start), int(count)
                    if start != expected or count < 0 or start + count > len(values):
                        raise ValueError(
                            f"Invalid ordered sloping incidence in {name!r}"
                        )
                    ids = values[start : start + count, 0]
                    if (ids < 0).any():
                        raise ValueError("Negative sloping face ids are unsupported")
                    result.append(ids.astype(int).tolist())
                    expected += count
                if expected != len(values):
                    raise ValueError("Unreferenced sloping incidence values")
                return result

            cell_faces = incidence(
                "Cells Face and Orientation Info", "Cells Face and Orientation Values"
            )
            vertex_faces = incidence(
                "FacePoints Face and Orientation Info",
                "FacePoints Face and Orientation Values",
            )
            wse = np.asarray(arrays[summary.name], dtype=np.float32)
            if (
                wse.ndim != 2
                or wse.shape != (2, len(points))
                or len(cell_faces) != len(points)
            ):
                raise ValueError(
                    f"Unsupported Max-profile dimensions for {name!r}: {wse.shape}"
                )
            minimum = np.asarray(
                data["Cells Minimum Elevation"], dtype=np.float32
            ).reshape(-1)
            if len(minimum) not in (
                len(points),
                sum(len(faces) > 1 for faces in cell_faces),
            ):
                raise ValueError("Physical cell minimum count does not match topology")
            minimum_iter = iter(minimum)
            cells = [
                dict(
                    point=[p.x, p.y],
                    minimum_elevation=float(next(minimum_iter))
                    if len(faces) > 1
                    else 0.0,
                    wse=float(value),
                    virtual=len(faces) == 1,
                    faces=faces,
                )
                for p, faces, value in zip(
                    points.geometry, cell_faces, wse[0], strict=True
                )
            ]
            vertices = [
                dict(
                    point=p.tolist(),
                    faces=faces,
                    ccw=[(i + 1) % len(faces) for i in range(len(faces))],
                    cw=[(i - 1) % len(faces) for i in range(len(faces))],
                )
                for p, faces in zip(
                    data["FacePoints Coordinate"], vertex_faces, strict=True
                )
            ]
            faces = []
            internal = data["Faces Perimeter Values"]
            for pair, ends, elevation, (start, count) in zip(
                data["Faces Cell Indexes"],
                data["Faces FacePoint Indexes"],
                data["Faces Minimum Elevation"].reshape(-1),
                data["Faces Perimeter Info"],
                strict=True,
            ):
                a, b = map(int, pair)
                first, last = map(int, ends)
                start, count = int(start), int(count)
                if (
                    min(a, b) < 0
                    or max(a, b) >= len(cells)
                    or min(first, last) < 0
                    or max(first, last) >= len(vertices)
                ):
                    raise ValueError(
                        "Unsupported sloping face endpoint or cell reference"
                    )
                if start < 0 or count < 0 or start + count > len(internal):
                    raise ValueError("Invalid sloping face polyline range")
                polyline = [
                    vertices[first]["point"],
                    *internal[start : start + count].tolist(),
                    vertices[last]["point"],
                ]
                faces.append(
                    dict(
                        cells=[a, b],
                        vertices=[first, last],
                        minimum_elevation=float(elevation),
                        perimeter=cells[b]["virtual"],
                        application=None,
                        polyline=polyline,
                    )
                )
            products.append(
                dict(
                    mesh_name=name,
                    min_ws_plot_tolerance=float(np.float32(0.001)),
                    cells=cells,
                    faces=faces,
                    vertices=vertices,
                    preparation="fast-HDF; Rust face application reconstruction",
                )
            )
    return products
