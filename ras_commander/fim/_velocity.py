"""Velocity inputs for sloping requests (engine method ``rasmapper-sloping-velocity/0``).

Per mesh the engine needs the HDF face normals as float32 ``(x, y, length)``
with ``length`` the face **polyline** length (start facepoint, perimeter
points, end facepoint), and per profile the face-normal velocities in HDF face
order. Max uses the summary ``Maximum Face Velocity`` together with the Max
WSE; a stored output time uses ``Face Velocity`` at that index. Values are read,
never derived.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

METHOD_ID = "rasmapper-sloping-velocity/0"
DERIVED_METHOD_ID = "rasmapper-depth-velocity-products/1"
#: Derived products in engine stream order.
DERIVED = ("depth_x_velocity", "depth_x_velocity_squared", "froude")
#: RAS Mapper's float32 gravity constants (``SharedData.GravityUSC``/``GravitySI``).
GRAVITY = {"US Customary": 32.174, "SI Units": 9.80665}
VELOCITY_DEPTHS = ("rendered", "horizontal")


def validate_products(derived_products, velocity_depth) -> tuple:
    """Return derived products as a tuple after checking names and the depth mode."""
    if velocity_depth not in VELOCITY_DEPTHS:
        raise ValueError(f"velocity_depth must be one of {VELOCITY_DEPTHS}")
    if isinstance(derived_products, str):
        raise ValueError("derived_products must be a sequence of product names")
    products = tuple(derived_products or ())
    if len(set(products)) != len(products) or any(p not in DERIVED for p in products):
        raise ValueError(f"derived_products must be unique names from {DERIVED}")
    return products


def gravity(hdf: Path) -> float:
    """RAS Mapper's gravity constant for the plan's unit system."""
    import h5py

    with h5py.File(hdf, "r") as source:
        units = source.attrs.get("Units System")
    if isinstance(units, bytes):
        units = units.decode()
    if units not in GRAVITY:
        from .errors import FimUnsupportedError

        raise FimUnsupportedError(f"unknown plan unit system {units!r}; Froude needs gravity")
    return GRAVITY[units]


def require_engine(method: dict, render_mode: str, velocity_depth: str, products) -> None:
    """Check the engine advertises what a velocity request needs."""
    from .errors import FimUnsupportedError

    if method.get("velocity") != METHOD_ID:
        raise FimUnsupportedError(
            f"engine sloping method lacks {METHOD_ID}; install ras-commander-fast-map "
            "with velocity support"
        )
    if render_mode != "sloping" and render_mode not in (method.get("velocity_render_modes") or ()):
        raise FimUnsupportedError(
            f"engine does not advertise velocity for render_mode={render_mode!r} "
            "(velocity_render_modes); install a newer ras-commander-fast-map"
        )
    if velocity_depth != "rendered" and velocity_depth not in (method.get("velocity_depth") or ()):
        raise FimUnsupportedError("engine does not advertise velocity_depth='horizontal'")
    if products and (
        method.get("derived_method_id") != DERIVED_METHOD_ID
        or not set(products) <= set(method.get("derived_products") or ())
    ):
        raise FimUnsupportedError(
            f"engine does not advertise {DERIVED_METHOD_ID} for {list(products)}"
        )


def derived_path(folder: Path, profile: str, product: str) -> Path:
    return Path(folder) / f"13_{profile}_{product}.tif"


def max_derived_path(folder: Path, product: str) -> Path:
    return Path(folder) / f"14_max_{product}.tif"


def polyline_lengths(normals, facepoints, face_facepoints, perimeter_info, perimeter_values):
    """Return float64 face lengths, replacing the stored length of curved faces.

    Faces with perimeter points take the sum of their segment lengths
    (facepoint -> perimeter points -> facepoint); straight faces keep the
    stored ``Faces NormalUnitVector and Length`` value.
    """
    lengths = np.asarray(normals, dtype=np.float64)[:, 2].copy()
    info = np.asarray(perimeter_info, dtype=np.int64).reshape(-1, 2)
    curved = np.flatnonzero(info[:, 1] > 0)
    if curved.size == 0:
        return lengths
    facepoints = np.asarray(facepoints, dtype=np.float64).reshape(-1, 2)
    ends = np.asarray(face_facepoints, dtype=np.int64).reshape(-1, 2)
    values = np.asarray(perimeter_values, dtype=np.float64).reshape(-1, 2)
    starts, counts = info[curved, 0], info[curved, 1]
    if (starts < 0).any() or (starts + counts > len(values)).any():
        raise ValueError("Faces Perimeter Info exceeds Faces Perimeter Values")
    sizes = counts + 2
    offsets = np.concatenate(([0], np.cumsum(sizes)[:-1]))
    points = np.empty((int(sizes.sum()), 2), dtype=np.float64)
    points[offsets] = facepoints[ends[curved, 0]]
    points[offsets + sizes - 1] = facepoints[ends[curved, 1]]
    inner = np.ones(len(points), dtype=bool)
    inner[offsets] = False
    inner[offsets + sizes - 1] = False
    points[inner] = values[np.concatenate([np.arange(s, s + k) for s, k in zip(starts, counts)])]
    segment = np.hypot(*np.diff(points, axis=0).T)
    # Segments that join one face's end to the next face's start are excluded.
    keep = np.ones(len(segment), dtype=bool)
    keep[(offsets + sizes - 1)[:-1]] = False
    segment = segment[keep]
    segment_offsets = np.concatenate(([0], np.cumsum(sizes - 1)[:-1]))
    lengths[curved] = np.add.reduceat(segment, segment_offsets)
    return lengths


def stage(hdf: Path, root: Path, meshes, selected: dict, units: list, *, threads: int = 1) -> dict:
    """Write normals and per-profile face velocities; extend ``units`` in place."""
    import h5py

    from .. import HdfResultsMesh
    from ..fast_hdf import backend_scope, read_datasets
    from ._horizontal_engine import _write_array

    normals_files = []
    face_counts = []
    max_velocity = []
    with h5py.File(hdf, "r") as source:
        for index, mesh in enumerate(meshes):
            name = mesh["mesh_name"]
            prefix = f"Geometry/2D Flow Areas/{name}/"
            fields = [
                "Faces NormalUnitVector and Length",
                "FacePoints Coordinate",
                "Faces FacePoint Indexes",
                "Faces Perimeter Info",
                "Faces Perimeter Values",
            ]
            missing = [field for field in fields if prefix + field not in source]
            if missing:
                from .errors import FimUnsupportedError

                raise FimUnsupportedError(f"velocity needs {missing} for mesh {name!r}")
            summary = None
            if "Max" in selected.values():
                try:
                    summary = HdfResultsMesh.get_mesh_summary_output_group(
                        source, name, "Maximum Face Velocity"
                    )
                except ValueError as exc:
                    from .errors import FimUnsupportedError

                    raise FimUnsupportedError(
                        f"Max velocity needs Maximum Face Velocity for mesh {name!r}"
                    ) from exc
            arrays = read_datasets(
                source,
                [prefix + field for field in fields] + ([summary.name] if summary is not None else []),
                backend="rust",
                threads=threads,
            )
            normals = np.asarray(arrays[prefix + fields[0]], dtype=np.float64).reshape(-1, 3)
            faces = len(normals)
            if len(np.asarray(arrays[prefix + "Faces FacePoint Indexes"]).reshape(-1, 2)) != faces:
                raise ValueError(f"face tables disagree for mesh {name!r}")
            lengths = polyline_lengths(
                normals,
                arrays[prefix + "FacePoints Coordinate"],
                arrays[prefix + "Faces FacePoint Indexes"],
                arrays[prefix + "Faces Perimeter Info"],
                arrays[prefix + "Faces Perimeter Values"],
            )
            staged = np.column_stack([normals[:, :2], lengths]).astype("<f4")
            if not np.isfinite(staged).all() or (staged[:, 2] <= 0).any():
                from .errors import FimUnsupportedError

                raise FimUnsupportedError(f"mesh {name!r} has non-finite normals or non-positive face lengths")
            filename = f"velocity-normals-{index}.bin"
            _write_array(root / filename, staged)
            normals_files.append(filename)
            face_counts.append(faces)
            if summary is not None:
                values = np.asarray(arrays[summary.name], dtype="<f4")
                if values.ndim != 2 or values.shape[1] != faces:
                    raise ValueError(f"Unsupported Maximum Face Velocity dimensions for {name!r}")
                max_velocity.append(np.ascontiguousarray(values[0]))
            else:
                max_velocity.append(None)
    views = {}
    for position, (unit, selector) in enumerate(zip(units, selected.values())):
        files = []
        for index, mesh in enumerate(meshes):
            if selector == "Max":
                values = max_velocity[index]
            else:
                with backend_scope("rust"):
                    if index not in views:
                        views[index] = HdfResultsMesh.get_mesh_timeseries(
                            hdf, mesh["mesh_name"], "Face Velocity",
                            truncate=False, return_type="view",
                        )
                    values = views[index].select(time=int(selector)).to_numpy(dtype=np.float32).reshape(-1)
            if len(values) != face_counts[index] or not np.isfinite(values).all():
                raise ValueError(
                    f"Invalid face velocities for profile {unit['id']!r}, mesh {mesh['mesh_name']!r}"
                )
            filename = f"velocity-{position}-{index}.bin"
            _write_array(root / filename, np.asarray(values, dtype="<f4"))
            files.append(filename)
        unit["face_velocity_files"] = files
    return {"velocity_normals_files": normals_files}


def velocity_path(folder: Path, profile: str) -> Path:
    return Path(folder) / f"12_{profile}_velocity.tif"
