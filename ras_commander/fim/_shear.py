"""Max shear-stress inputs for sloping requests (engine method ``rasmapper-face-shear-max/1``).

RAS Mapper's Max shear stress is not a per-pixel time series. Its
post-processor computes a shear vector on every face at every stored output
time, keeps each face's largest magnitude (PostProcessing ``Maximum Shear``)
and interpolates those face scalars through the facepoints. The engine
reproduces that pass, so per mesh it needs, in HDF order and read, never
derived:

- the face normals as float32 ``(x, y, polyline length)`` (as velocity);
- ``Faces Area Elevation Info`` (int32 start, count) and ``Values`` (float32
  elevation, area, wetted perimeter, Manning's n);
- every stored output time's cell ``Water Surface`` (ghost cells included) and
  ``Face Velocity``, as contiguous float32 time x element arrays.

The request's single profile is the Max profile (``Maximum Water Surface``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

METHOD_ID = "rasmapper-face-shear-max/1"
SHEAR_DEPTHS = ("rendered", "horizontal")
#: Plan ``Units System`` values the engine accepts.
UNITS = ("US Customary", "SI Units")
_SERIES = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas"


def require_engine(method: dict, shear_depth: str) -> None:
    """Check the engine advertises Max shear stress and the clipping depth."""
    from .errors import FimUnsupportedError

    if method.get("shear_stress") != METHOD_ID:
        raise FimUnsupportedError(
            f"engine sloping method lacks {METHOD_ID}; install ras-commander-fast-map "
            "with shear-stress support"
        )
    if shear_depth not in (method.get("shear_stress_depth") or ()):
        raise FimUnsupportedError(
            f"engine does not advertise shear_stress_depth={shear_depth!r}"
        )


def units(hdf: Path) -> str:
    """The plan's ``Units System`` (selects the shear unit factor)."""
    import h5py

    with h5py.File(hdf, "r") as source:
        value = source.attrs.get("Units System")
    if isinstance(value, bytes):
        value = value.decode()
    if value not in UNITS:
        from .errors import FimUnsupportedError

        raise FimUnsupportedError(f"unknown plan unit system {value!r}; shear stress needs it")
    return value


def shear_path(folder: Path, profile: str) -> Path:
    return Path(folder) / f"15_{profile}_shear_stress.tif"


def _stage_series(source, dataset_path: str, width: int, destination: Path, chunk_bytes: int) -> int:
    """Copy a (time, width) float32 dataset row-block by row-block; return the time count."""
    from ..fast_hdf import read_dataset
    from .errors import FimUnsupportedError

    if dataset_path not in source:
        raise FimUnsupportedError(f"shear stress needs {dataset_path}")
    dataset = source[dataset_path]
    if len(dataset.shape) != 2 or dataset.shape[1] != width or dataset.shape[0] < 1:
        raise FimUnsupportedError(f"unsupported dimensions {dataset.shape} for {dataset_path}")
    times = int(dataset.shape[0])
    rows = max(1, chunk_bytes // (4 * width))
    partial = destination.with_suffix(".partial")
    try:
        with partial.open("wb") as stream:
            for start in range(0, times, rows):
                stop = min(times, start + rows)
                block = np.asarray(
                    read_dataset(dataset, (slice(start, stop), slice(None)), backend="rust"),
                    dtype="<f4",
                )
                if block.shape != (stop - start, width) or not np.isfinite(block).all():
                    raise ValueError(f"invalid values in {dataset_path} rows {start}:{stop}")
                stream.write(memoryview(np.ascontiguousarray(block)).cast("B"))
                del block
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return times


def stage(hdf: Path, root: Path, meshes, *, shear_depth: str = "rendered", threads: int = 1,
          chunk_bytes: int = 32 * 1024 * 1024) -> dict:
    """Write the per-mesh shear inputs; return the request's ``shear_stress`` field."""
    import h5py

    from ..fast_hdf import read_datasets
    from ._horizontal_engine import _write_array
    from ._velocity import polyline_lengths
    from .errors import FimUnsupportedError

    if shear_depth not in SHEAR_DEPTHS:
        raise ValueError(f"shear_depth must be one of {SHEAR_DEPTHS}")
    plan_units = units(hdf)
    entries = []
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
                "Faces Area Elevation Info",
                "Faces Area Elevation Values",
            ]
            missing = [field for field in fields if prefix + field not in source]
            if missing:
                raise FimUnsupportedError(f"shear stress needs {missing} for mesh {name!r}")
            arrays = read_datasets(source, [prefix + f for f in fields], backend="rust", threads=threads)
            normals = np.asarray(arrays[prefix + fields[0]], dtype=np.float64).reshape(-1, 3)
            faces = len(normals)
            lengths = polyline_lengths(
                normals,
                arrays[prefix + "FacePoints Coordinate"],
                arrays[prefix + "Faces FacePoint Indexes"],
                arrays[prefix + "Faces Perimeter Info"],
                arrays[prefix + "Faces Perimeter Values"],
            )
            staged = np.column_stack([normals[:, :2], lengths]).astype("<f4")
            if not np.isfinite(staged).all() or (staged[:, 2] <= 0).any():
                raise FimUnsupportedError(f"mesh {name!r} has non-finite normals or non-positive face lengths")
            info = np.asarray(arrays[prefix + "Faces Area Elevation Info"])
            values = np.asarray(arrays[prefix + "Faces Area Elevation Values"])
            if info.shape != (faces, 2) or values.ndim != 2 or values.shape[1] != 4:
                raise FimUnsupportedError(f"unsupported Faces Area Elevation layout for mesh {name!r}")
            if (info[:, 1] <= 0).any():
                raise FimUnsupportedError(
                    f"mesh {name!r} has faces without a Faces Area Elevation table; "
                    "RAS Mapper cannot compute shear stress for it"
                )
            normals_file = f"shear-normals-{index}.bin"
            info_file = f"shear-tables-info-{index}.bin"
            values_file = f"shear-tables-values-{index}.bin"
            _write_array(root / normals_file, staged)
            _write_array(root / info_file, np.ascontiguousarray(info, dtype="<i4"))
            _write_array(root / values_file, np.ascontiguousarray(values, dtype="<f4"))
            ws_file = f"shear-water-surface-{index}.bin"
            fv_file = f"shear-face-velocity-{index}.bin"
            times = _stage_series(source, f"{_SERIES}/{name}/Water Surface", int(mesh["cell_count"]),
                                  root / ws_file, chunk_bytes)
            if _stage_series(source, f"{_SERIES}/{name}/Face Velocity", faces, root / fv_file,
                             chunk_bytes) != times:
                raise FimUnsupportedError(f"Water Surface and Face Velocity times differ for mesh {name!r}")
            entries.append(dict(
                normals_file=normals_file, tables_info_file=info_file,
                tables_values_file=values_file, table_rows=int(values.shape[0]),
                times=times, water_surface_file=ws_file, face_velocity_file=fv_file,
            ))
    return {"shear_stress": {"units": plan_units, "depth": shear_depth, "meshes": entries}}


def describe(shear_depth: str, render_mode: str, plan_units: str) -> dict:
    return {
        "method_id": METHOD_ID,
        "profile": "Max",
        "rule": (
            "per face, the maximum over every stored output time of RAS Mapper's face shear "
            "k*|V|*V*n^2/R^(1/3) (least-squares facepoint velocities, Faces Area Elevation "
            "hydraulic radius and first Manning's n); facepoints average their faces and are "
            "painted with the plain sloping weights"
        ),
        "units": plan_units,
        "shear_depth": shear_depth,
        "drawn": (
            "where the horizontal (cell-constant) Max depth > 0"
            if shear_depth == "horizontal"
            else f"where the rendered {render_mode} Max depth > 0"
        ),
    }
