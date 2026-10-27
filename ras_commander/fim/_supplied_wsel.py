"""Validate and stage caller WSEL vectors; hydraulic reconstruction stays native."""

from dataclasses import dataclass
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_integer_dtype, is_numeric_dtype, is_complex_dtype

from . import _engine
from .errors import FimUnsupportedError

DRY = np.finfo(np.float32).min
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


@dataclass
class SuppliedWsel:
    index: pd.MultiIndex
    values: dict
    declared_crs: object
    source_declared: bool
    planned_bytes: int

    def align(self, meshes):
        names = [mesh["mesh_name"] for mesh in meshes]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate source mesh names")
        unknown = set(self.index.get_level_values("mesh_name")) - set(names)
        if unknown:
            raise ValueError(f"wsel_profiles has unknown mesh names: {sorted(unknown)}")
        count = sum(mesh["cell_count"] for mesh in meshes)
        if len(self.index) != count:
            raise ValueError(
                f"wsel_profiles must cover every physical and ghost cell in every mesh: "
                f"expected {count} rows, got {len(self.index)}"
            )
        positions = []
        for mesh in meshes:
            expected = pd.MultiIndex.from_product(
                [[mesh["mesh_name"]], np.arange(mesh["cell_count"], dtype=np.int64)]
            )
            indices = self.index.get_indexer(expected)
            if (indices < 0).any():
                missing = np.flatnonzero(indices < 0)[:8].tolist()
                raise ValueError(f"Missing source cell IDs in {mesh['mesh_name']!r}: {missing}; ghosts are required")
            positions.append(indices)
        return positions

    @property
    def selection(self):
        # None explicitly means caller data, never an HDF selector.
        return dict.fromkeys(self.values)

    def check_crs(self, crs):
        if self.declared_crs is not None:
            from pyproj import CRS
            if CRS.from_user_input(self.declared_crs) != CRS.from_user_input(crs):
                raise ValueError("wsel_profiles declared CRS differs from the HDF mesh CRS")


def snapshot(frame, hdf, *, profiles=None, max_bytes=None):
    """Own immutable float32 values and keys before invoking the engine."""
    if profiles is not None:
        raise ValueError("profiles and wsel_profiles are mutually exclusive")
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("wsel_profiles must be a pandas DataFrame")
    if not frame.columns.is_unique:
        raise ValueError("wsel_profiles has duplicate column names")
    if frame.empty or not {"mesh_name", "cell_id"}.issubset(frame.columns):
        raise ValueError("wsel_profiles requires mesh_name, cell_id and named WSEL columns")
    names = [name for name in frame.columns if name not in ("mesh_name", "cell_id")]
    if (not names or any(not isinstance(name, str) or not _engine._SAFE_ID.fullmatch(name)
                         or name in (".", "..") or name.endswith(".")
                         or name.split(".")[0].casefold() in _RESERVED for name in names)
            or len({name.casefold() for name in names}) != len(names)):
        raise ValueError("wsel_profiles requires unique, safe, non-reserved profile names")
    planned = len(frame) * (16 + 4 * len(names))
    if max_bytes is not None and planned > max_bytes:
        raise FimUnsupportedError("Caller WSEL snapshot exceeds the planned input budget")
    mesh = frame["mesh_name"]
    if not mesh.map(lambda name: isinstance(name, str) and bool(name)).all():
        raise ValueError("mesh_name must contain exact nonempty HDF mesh names")
    ids = frame["cell_id"]
    if (not is_integer_dtype(ids.dtype) or is_bool_dtype(ids.dtype) or ids.isna().any()
            or (ids < 0).any() or (ids > np.iinfo(np.int64).max).any()):
        raise ValueError("cell_id must contain nonnegative int64-compatible integer IDs")
    index = pd.MultiIndex.from_arrays(
        [mesh.to_numpy(copy=True), ids.to_numpy(dtype=np.int64, copy=True)],
        names=["mesh_name", "cell_id"],
    )
    if index.has_duplicates:
        raise ValueError("wsel_profiles contains duplicate mesh_name/cell_id pairs")
    declared = frame.attrs.get("fim_source_hdf")
    if declared is not None and Path(declared).resolve() != Path(hdf).resolve():
        raise ValueError("wsel_profiles source HDF differs from hdf_path")
    values = {}
    for name in names:
        column = frame[name]
        if (not is_numeric_dtype(column.dtype) or is_bool_dtype(column.dtype)
                or is_complex_dtype(column.dtype)):
            raise ValueError(f"WSEL column {name!r} must contain real numeric elevations or NaN")
        with np.errstate(over="ignore", invalid="ignore"):
            array = column.to_numpy(dtype="<f4", na_value=np.nan, copy=True)
        if np.isinf(array).any():
            raise ValueError(f"WSEL column {name!r} contains infinity or float32 overflow")
        array[np.isnan(array)] = DRY
        array.flags.writeable = False
        values[name] = array
    return SuppliedWsel(index, values, frame.attrs.get("crs"), declared is not None, planned)


def stage(supplied, root, meshes, *, max_staged_bytes=None):
    """Align complete source cell IDs (including ghosts), then write atomic files."""
    from ._horizontal_engine import _write_array

    names = [mesh["mesh_name"] for mesh in meshes]
    positions = supplied.align(meshes)
    count = sum(mesh["cell_count"] for mesh in meshes)
    planned = count * len(supplied.values) * 4
    if max_staged_bytes is not None and planned > max_staged_bytes:
        raise FimUnsupportedError("Prepared supplied WSEL inputs exceed max_prepared_mib")
    files = [[root / f"values-{p}-{m}.bin" for m in range(len(meshes))]
             for p in range(len(supplied.values))]
    for group in files:
        for path in group:
            if path.exists() or path.with_suffix(".partial").exists():
                raise FileExistsError(f"Supplied WSEL staging destination exists: {path.name}")
    created, partials, units, hashes = [], [], [], {}
    try:
        for p, (name, values) in enumerate(supplied.values.items()):
            evidence = []
            for m, indices in enumerate(positions):
                array = np.ascontiguousarray(values[indices], dtype="<f4")
                path = files[p][m]
                partial = path.with_suffix(".partial")
                partials.append(partial)
                _write_array(partial, array)
                if partial.stat().st_size != array.nbytes:
                    raise ValueError("Incomplete supplied WSEL staging")
                partial.replace(path)
                created.append(path)
                evidence.append(dict(mesh_name=names[m], cell_count=len(indices),
                    sha256=hashlib.sha256(memoryview(array)).hexdigest(),
                    dry_marker_count=int(np.count_nonzero(array == DRY))))
            units.append(dict(id=name, values_files=[path.name for path in files[p]]))
            hashes[name] = evidence
    except BaseException:
        for path in created + partials:
            path.unlink(missing_ok=True)
        raise
    metadata = dict(kind="caller-cell-wsel/1", elevation_units="model vertical units and datum",
        dry_encoding="NaN converted to finite float32 minimum", dry_value=float(DRY),
        alignment="complete mesh_name/cell_id, including ghost cells; source HDF order",
        source_hdf_metadata_checked=supplied.source_declared, profiles=hashes,
        planned_snapshot_bytes=supplied.planned_bytes,
        qualification="Caller aggregates and changed mapping terrains are not native-parity qualified by selector equivalence.")
    return units, planned, metadata
