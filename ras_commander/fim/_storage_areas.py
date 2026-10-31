"""Standalone storage-area level pools for Rust FIM mapping.

RAS Mapper draws a storage area as a horizontal pool: the storage area's water
surface (Max or one stored output time) on every terrain pixel whose centre is
inside the storage-area polygon, visible where float32
``wse >= terrain + 0.001``. The engine method is ``storage-area-level-pool/1``
(Fast-Map). This module reads the polygons and water surfaces from the plan
HDF, fails closed on anything it cannot prove, and stages the request fields.

Sources (plan HDF):

- polygons: ``Geometry/Storage Areas`` (``Attributes`` names, ``Polygon Info``,
  ``Polygon Parts``, ``Polygon Points``); the first part is the exterior ring,
  later parts are holes;
- Max: ``Summary Output/Storage Areas/Maximum Water Surface`` row 0;
- stored output time ``k``: ``Unsteady Time Series/Storage Areas/Water Surface``
  row ``k``. Its column order is proven by matching each column to the closest
  of the areas' own
  ``<name>/Storage Area Variables`` ``Stage`` column; the summary uses the same
  column order.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .errors import FimEngineError, FimUnsupportedError

METHOD_ID = "storage-area-level-pool/1"
_BASE = "Results/Unsteady/Output/Output Blocks/Base Output"
SUMMARY = f"{_BASE}/Summary Output/Storage Areas/Maximum Water Surface"
SERIES = f"{_BASE}/Unsteady Time Series/Storage Areas/Water Surface"
_GROUP = f"{_BASE}/Unsteady Time Series/Storage Areas"


@dataclass(frozen=True)
class StorageAreas:
    """Storage-area polygons of one plan HDF, in geometry order."""

    names: tuple
    polygons: np.ndarray

    def __len__(self):
        return len(self.names)


def _text(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="strict")
    return str(value).strip()


def read(hdf_path):
    """Read storage-area polygons; ``None`` when the plan has none."""
    import h5py
    import shapely

    with h5py.File(Path(hdf_path), "r") as source:
        group = source.get("Geometry/Storage Areas")
        attributes = group.get("Attributes") if group is not None else None
        if attributes is None or attributes.shape[0] == 0:
            return None
        names = tuple(_text(row["Name"]) for row in attributes[()])
        if any(not name for name in names) or len(set(names)) != len(names):
            raise FimUnsupportedError("storage-area names must be unique and non-empty")
        for name in ("Polygon Info", "Polygon Points"):
            if name not in group:
                raise FimUnsupportedError(f"storage areas lack Geometry/Storage Areas/{name}")
        info = np.asarray(group["Polygon Info"][()], dtype=np.int64)
        points = np.asarray(group["Polygon Points"][()], dtype=np.float64)
        parts = (
            np.asarray(group["Polygon Parts"][()], dtype=np.int64)
            if "Polygon Parts" in group
            else None
        )
    count = len(names)
    if info.shape != (count, 4) or points.ndim != 2 or points.shape[1] != 2:
        raise FimUnsupportedError("storage-area polygon tables do not match the area count")
    if not np.isfinite(points).all():
        raise FimUnsupportedError("storage-area polygon coordinates must be finite")
    polygons = []
    for name, (start, length, part_start, part_count) in zip(names, info):
        if start < 0 or length < 3 or start + length > len(points):
            raise FimUnsupportedError(f"storage area {name!r} has an invalid point range")
        if parts is None or part_count <= 1:
            if part_count > 1:
                raise FimUnsupportedError(f"storage area {name!r} has parts but no Polygon Parts")
            rings = [points[start:start + length]]
        else:
            if part_start < 0 or part_start + part_count > len(parts):
                raise FimUnsupportedError(f"storage area {name!r} has an invalid part range")
            rings = []
            for offset, size in parts[part_start:part_start + part_count]:
                if offset < 0 or size < 3 or offset + size > length:
                    raise FimUnsupportedError(f"storage area {name!r} has an invalid ring")
                rings.append(points[start + offset:start + offset + size])
        polygon = shapely.Polygon(rings[0], rings[1:])
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise FimUnsupportedError(
                f"storage area {name!r} is not a valid polygon; RAS Mapper's drawing of it is unqualified"
            )
        polygons.append(polygon)
    array = np.empty(count, dtype=object)
    array[:] = polygons
    array.setflags(write=False)
    return StorageAreas(names, array)


def _checked(values, names, what):
    values = np.asarray(values, dtype=np.float32).reshape(-1)
    if len(values) != len(names):
        raise FimUnsupportedError(f"{what} does not match the {len(names)} storage areas")
    if not np.isfinite(values).all():
        raise FimUnsupportedError(f"{what} contains non-finite storage-area WSE")
    return values.astype("<f4")


def _series_columns(source, areas):
    """Water Surface series with its column order proven per storage-area name."""
    series = source.get(SERIES)
    if series is None or series.ndim != 2 or series.shape[1] != len(areas):
        raise FimUnsupportedError(
            "plan HDF lacks a storage-area Water Surface series matching the storage areas"
        )
    stages = []
    for name in areas.names:
        variables = source.get(f"{_GROUP}/{name}/Storage Area Variables")
        if variables is None:
            raise FimUnsupportedError(f"storage area {name!r} has no Storage Area Variables")
        labels = variables.attrs.get("Variable_Unit")
        if labels is None or _text(np.asarray(labels).reshape(-1, 2)[0][0]) != "Stage":
            raise FimUnsupportedError(f"storage area {name!r}: first variable is not Stage")
        if variables.shape[0] != series.shape[0]:
            raise FimUnsupportedError(f"storage area {name!r}: series length mismatch")
        stages.append(np.asarray(variables[:, 0], dtype=np.float64))
    if len(areas) > 1:
        # The named Stage variable is not bit-identical to the Water Surface
        # column (HEC-RAS stores them separately; p07 differs by up to 0.0013
        # ft), so each column must be strictly closest to its own area's Stage.
        values = np.asarray(series[()], dtype=np.float64)
        distance = np.array([
            [np.nanmean(np.abs(values[:, column] - stage)) for stage in stages]
            for column in range(len(areas))
        ])
        for column, name in enumerate(areas.names):
            row = distance[column]
            others = np.delete(row, column)
            if not np.isfinite(row[column]) or not (row[column] < others).all():
                raise FimUnsupportedError(
                    f"storage-area Water Surface column {column} is not {name!r}; column order unproven"
                )
    return series


def profile_values(hdf_path, areas, selection):
    """Float32 storage-area WSE per output name for ``Max`` or a stored index."""
    import h5py

    out = {}
    with h5py.File(Path(hdf_path), "r") as source:
        # The series proves the column order the summary shares.
        series = _series_columns(source, areas)
        for output, selector in selection.items():
            if selector == "Max":
                summary = source.get(SUMMARY)
                if summary is None or summary.ndim != 2 or summary.shape[1] != len(areas):
                    raise FimUnsupportedError("plan HDF lacks storage-area Maximum Water Surface")
                out[output] = _checked(summary[0, :], areas.names, "Maximum Water Surface")
            else:
                index = int(selector)
                if not 0 <= index < series.shape[0]:
                    raise ValueError(
                        f"storage-area timestep {index} outside 0..{series.shape[0] - 1}"
                    )
                out[output] = _checked(series[index, :], areas.names, f"Water Surface at {index}")
    return out


def time_series(hdf_path, areas, times):
    """All stored storage-area WSE, shape ``(times, areas)`` float32."""
    import h5py

    with h5py.File(Path(hdf_path), "r") as source:
        series = _series_columns(source, areas)
        if series.shape[0] != times:
            raise FimUnsupportedError(
                f"storage-area Water Surface has {series.shape[0]} rows, not the {times} output times"
            )
        values = np.asarray(series[()], dtype=np.float32)
    if not np.isfinite(values).all():
        raise FimUnsupportedError("storage-area Water Surface contains non-finite values")
    return values.astype("<f4")


def require_engine(method, kind):
    """Refuse unless the engine method advertises storage-area surfaces."""
    if not isinstance(method, dict) or method.get("storage_area_surfaces") != METHOD_ID:
        raise FimUnsupportedError(
            f"engine {kind} method lacks {METHOD_ID}; install ras-commander-fast-map with "
            "storage-area surfaces"
        )


def stage_polygons(areas, root):
    """Write framed WKB polygons and return the request fields."""
    from ._horizontal_engine import _write_geometry

    _write_geometry(Path(root) / "storage_areas.wkb", areas.polygons)
    return {"storage_areas_file": "storage_areas.wkb", "storage_area_count": len(areas)}


def stage_values(root, name, values):
    """Write one profile's float32 storage-area WSE; return its relative path."""
    from ._horizontal_engine import _write_array

    folder = Path(root) / "storage_area_values"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}.bin"
    _write_array(path, np.ascontiguousarray(values, dtype="<f4"))
    return f"storage_area_values/{name}.bin"


def check_report(report, areas):
    """Validate the engine's storage-area report block and return it."""
    block = report.get("storage_areas") if isinstance(report, dict) else None
    if (
        not isinstance(block, dict)
        or block.get("count") != len(areas)
        or not isinstance(block.get("method"), dict)
        or block["method"].get("method_id") != METHOD_ID
        or isinstance(block.get("pixels"), bool)
        or not isinstance(block.get("pixels"), int)
        or block["pixels"] < 0
    ):
        raise FimEngineError("engine report lacks a consistent storage-area block")
    return block


def describe(areas, selection=None):
    """Manifest record of the staged storage areas."""
    record = {
        "method_id": METHOD_ID,
        "count": len(areas),
        "names": list(areas.names),
        "surface": "level pool: storage-area WSE on pixels whose centre is inside the polygon",
        "visibility": "float32 wse >= terrain + 0.001; depth wse - terrain",
        "max_source": "Summary Output Maximum Water Surface",
        "timestep_source": "Unsteady Time Series Water Surface at the stored output time",
        "refused": "storage-area pixels also owned by a 2D cell, overlapping storage areas",
    }
    if selection is not None:
        record["profiles"] = dict(selection)
    return record
