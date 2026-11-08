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
import hashlib
from pathlib import Path

import numpy as np

from .errors import FimEngineError, FimUnsupportedError

METHOD_ID = "storage-area-level-pool/1"
_BASE = "Results/Unsteady/Output/Output Blocks/Base Output"
SUMMARY = f"{_BASE}/Summary Output/Storage Areas/Maximum Water Surface"
SERIES = f"{_BASE}/Unsteady Time Series/Storage Areas/Water Surface"
_GROUP = f"{_BASE}/Unsteady Time Series/Storage Areas"
STRICT = "strict"
NATIVE_EVEN_ODD = "native_even_odd"


@dataclass(frozen=True)
class StorageAreas:
    """Storage-area polygons of one plan HDF, in geometry order."""

    names: tuple
    polygons: np.ndarray
    geometry_policy: str = STRICT
    geometry_records: tuple = ()

    def __len__(self):
        return len(self.names)


def _text(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="strict")
    return str(value).strip()


def _native_signed_area(rings):
    """Native binary64 trapezoid accumulation; positive means clockwise."""
    min_y = min(float(point[1]) for ring in rings for point in ring)
    total = 0.0
    for ring in rings:
        part = 0.0
        for a, b in zip(ring, ring[1:]):
            dx = float(b[0]) - float(a[0])
            ya = float(a[1]) - min_y
            yb = float(b[1]) - min_y
            part += (ya + yb) * dx
        total += part * 0.5
    return total


def geometry_metadata(areas):
    """Receipt of geometry admission without changing source ring topology."""
    return {
        "policy": areas.geometry_policy,
        "fill_rule": "even-odd" if areas.geometry_policy == NATIVE_EVEN_ODD else None,
        "preserved_invalid": [dict(row) for row in areas.geometry_records if not row["valid"]],
        "polygons": [dict(row) for row in areas.geometry_records],
    }


def read(hdf_path, *, max_bytes=None, geometry_policy=STRICT):
    """Read polygons, retaining strict validation unless explicitly requested.

    ``native_even_odd`` additionally admits finite single-ring self-crossings
    with nonnegative native signed area. It preserves WKB and feature order;
    negative invalid rings and invalid multipart topology remain unsupported.
    """
    import h5py
    import shapely
    from ..fast_hdf import read_typed

    if geometry_policy not in (STRICT, NATIVE_EVEN_ODD):
        raise ValueError("unknown storage geometry policy")

    with h5py.File(Path(hdf_path), "r") as source:
        group = source.get("Geometry/Storage Areas")
        attributes = group.get("Attributes") if group is not None else None
        if group is not None and len(group) and attributes is None:
            raise FimUnsupportedError("storage areas lack geometry Attributes")
        if attributes is None or attributes.shape[0] == 0:
            return None
        if not attributes.dtype.names or "Name" not in attributes.dtype.names:
            raise FimUnsupportedError("unsupported storage-area attributes: missing Name")
        planned = sum(ds.size * ds.dtype.itemsize for ds in group.values() if isinstance(ds, h5py.Dataset))
        if max_bytes is not None and planned * 8 > max_bytes:
            raise FimUnsupportedError("storage geometry exceeds input admission")
        names = tuple(_text(row["Name"]) for row in read_typed(attributes))
        if any(not name for name in names) or len(set(names)) != len(names):
            raise FimUnsupportedError("storage-area names must be unique and non-empty")
        for name in ("Polygon Info", "Polygon Points"):
            if name not in group:
                raise FimUnsupportedError(f"storage areas lack Geometry/Storage Areas/{name}")
        info = np.asarray(read_typed(group["Polygon Info"]), dtype=np.int64)
        points = np.asarray(read_typed(group["Polygon Points"]), dtype=np.float64)
        parts = (
            np.asarray(read_typed(group["Polygon Parts"]), dtype=np.int64)
            if "Polygon Parts" in group
            else None
        )
    count = len(names)
    if info.shape != (count, 4) or points.ndim != 2 or points.shape[1] != 2:
        raise FimUnsupportedError("storage-area polygon tables do not match the area count")
    if not np.isfinite(points).all():
        raise FimUnsupportedError("storage-area polygon coordinates must be finite")
    polygons = []
    records = []
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
        closed_rings = [list(polygon.exterior.coords),
                        *[list(ring.coords) for ring in polygon.interiors]]
        area = _native_signed_area(closed_rings)
        reason = str(shapely.is_valid_reason(polygon))
        preserved_crossing = (
            geometry_policy == NATIVE_EVEN_ODD
            and not polygon.is_valid
            and len(rings) == 1
            and len(closed_rings[0]) >= 4
            and reason.startswith(("Self-intersection[", "Ring Self-intersection["))
            and area >= 0.0
        )
        if (polygon.is_empty or not np.isfinite(area)
                or (not preserved_crossing and (not polygon.is_valid or polygon.area <= 0))):
            raise FimUnsupportedError(
                f"storage area {name!r} is not a valid polygon; RAS Mapper's drawing of it is unqualified"
            )
        polygons.append(polygon)
        wkb_hash = hashlib.sha256(polygon.wkb).hexdigest()
        records.append({
            "id": len(polygons) - 1, "name": name, "valid": bool(polygon.is_valid),
            "validity_reason": reason, "native_signed_area": area,
            "winding": "clockwise" if area > 0 else "counterclockwise" if area < 0 else "zero",
            "raw_wkb_sha256": wkb_hash, "staged_wkb_sha256": wkb_hash,
            "coordinates_preserved": True, "part_count": len(rings),
        })
    array = np.empty(count, dtype=object)
    array[:] = polygons
    array.setflags(write=False)
    return StorageAreas(names, array, geometry_policy, tuple(records))


def _checked(values, names, what):
    values = np.asarray(values, dtype=np.float32).reshape(-1)
    if len(values) != len(names):
        raise FimUnsupportedError(f"{what} does not match the {len(names)} storage areas")
    if not np.isfinite(values).all():
        raise FimUnsupportedError(f"{what} contains non-finite storage-area WSE")
    return values.astype("<f4")


def _series_columns(source, areas, *, series_path=SERIES, group_path=_GROUP):
    """Water Surface series with its column order proven per storage-area name."""
    from ..fast_hdf import read_typed
    series = source.get(series_path)
    if series is None or series.ndim != 2 or series.shape[1] != len(areas):
        raise FimUnsupportedError(
            "plan HDF lacks a storage-area Water Surface series matching the storage areas"
        )
    stages = []
    for name in areas.names:
        variables = source.get(f"{group_path}/{name}/Storage Area Variables")
        if variables is None:
            raise FimUnsupportedError(f"storage area {name!r} has no Storage Area Variables")
        labels = variables.attrs.get("Variable_Unit")
        if labels is None or _text(np.asarray(labels).reshape(-1, 2)[0][0]) != "Stage":
            raise FimUnsupportedError(f"storage area {name!r}: first variable is not Stage")
        if variables.shape[0] != series.shape[0]:
            raise FimUnsupportedError(f"storage area {name!r}: series length mismatch")
        stages.append(np.asarray(read_typed(variables, (slice(None), 0)), dtype=np.float64))
    if len(areas) > 1:
        # The named Stage variable is not bit-identical to the Water Surface
        # column (HEC-RAS stores them separately; p07 differs by up to 0.0013
        # ft), so each column must be strictly closest to its own area's Stage.
        values = np.asarray(read_typed(series), dtype=np.float64)
        distance = np.array([
            [np.nanmean(np.abs(values[:, column] - stage)) for stage in stages]
            for column in range(len(areas))
        ])
        for column, name in enumerate(areas.names):
            row = distance[column]
            others = np.delete(row, column)
            # Steady named Stage may prove the value exactly even when two
            # pools have identical histories; there is no inferred permutation.
            exact_named = (group_path != _GROUP and
                           np.array_equal(values[:, column], stages[column]))
            if not exact_named and (not np.isfinite(row[column]) or not (row[column] < others).all()):
                raise FimUnsupportedError(
                    f"storage-area Water Surface column {column} is not {name!r}; column order unproven"
                )
    return series


def profile_values(hdf_path, areas, selection, *, max_bytes=None):
    """Float32 storage-area WSE per output name for ``Max`` or a stored index."""
    import h5py

    from ..fast_hdf import read_typed
    out = {}
    with h5py.File(Path(hdf_path), "r") as source:
        # The series proves the column order the summary shares.
        has_steady, has_unsteady = "Results/Steady" in source, "Results/Unsteady" in source
        if has_steady and has_unsteady:
            raise FimUnsupportedError("ambiguous steady and unsteady storage result groups")
        steady = has_steady and not has_unsteady
        base = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
        group_path = base + "/Storage Areas" if steady else _GROUP
        series_path = group_path + "/Water Surface"
        if group_path not in source:
            raise FimUnsupportedError("plan HDF lacks storage-area Water Surface series")
        datasets = [obj for obj in source[group_path].values() if isinstance(obj, h5py.Dataset)]
        for name in areas.names:
            path = f"{group_path}/{name}/Storage Area Variables"
            if path in source:
                datasets.append(source[path])
        planned = sum(ds.size * ds.dtype.itemsize for ds in datasets) * (len(areas) + 4)
        if max_bytes is not None and planned > max_bytes:
            raise FimUnsupportedError("storage result proof exceeds input admission")
        series = _series_columns(source, areas, series_path=series_path, group_path=group_path)
        names = None
        if steady:
            ds = source[base + "/Profile Names"]
            if ds.size * ds.dtype.itemsize > (max_bytes or 268435456):
                raise FimUnsupportedError("steady profile axis exceeds admission")
            names = [_text(v) for v in read_typed(ds)]
            if len(names) != series.shape[0] or len(set(names)) != len(names):
                raise FimUnsupportedError("storage steady profile axis mismatch")
        for output, selector in selection.items():
            if steady:
                if isinstance(selector, str):
                    if selector not in names:
                        raise FimUnsupportedError("select an explicit stored steady profile")
                    index = names.index(selector)
                else:
                    index = int(selector)
                if not 0 <= index < len(names):
                    raise ValueError("storage steady profile index out of bounds")
                out[output] = _checked(read_typed(series, index), areas.names, "steady storage Water Surface")
            elif selector == "Max":
                summary = source.get(SUMMARY)
                if summary is None or summary.ndim != 2 or summary.shape[1] != len(areas):
                    raise FimUnsupportedError("plan HDF lacks storage-area Maximum Water Surface")
                out[output] = _checked(read_typed(summary, 0), areas.names, "Maximum Water Surface")
            else:
                index = int(selector)
                if not 0 <= index < series.shape[0]:
                    raise ValueError(
                        f"storage-area timestep {index} outside 0..{series.shape[0] - 1}"
                    )
                out[output] = _checked(read_typed(series, index), areas.names, f"Water Surface at {index}")
    return out


def time_series(hdf_path, areas, times):
    """All stored storage-area WSE, shape ``(times, areas)`` float32."""
    import h5py

    from ..fast_hdf import read_typed
    with h5py.File(Path(hdf_path), "r") as source:
        series = _series_columns(source, areas)
        if series.shape[0] != times:
            raise FimUnsupportedError(
                f"storage-area Water Surface has {series.shape[0]} rows, not the {times} output times"
            )
        values = np.asarray(read_typed(series), dtype=np.float32)
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
