"""Read-only access to a parent 2D model's plan HDF for the subdomain search.

Geometry tables come from the plan HDF's own ``Geometry`` group (the compiled
geometry the run used). Time series stream through
:meth:`HdfResultsMesh.iter_mesh_timeseries` in bounded batches, so a parent with
millions of faces is never held whole in memory. Nothing here writes a file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

import numpy as np

from ..LoggingConfig import get_logger
from ..fast_hdf import read_typed

logger = get_logger(__name__)

_TS = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas"
_FOOT_UNITS = {"us customary", "english", "us"}


def sha256_file(path: Path, chunk: int = 16 * 1024 * 1024) -> str:
    """SHA-256 of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def mesh_names(hdf_path: Path) -> list[str]:
    import h5py

    with h5py.File(hdf_path, "r") as f:
        attrs = f.get("Geometry/2D Flow Areas/Attributes")
        if attrs is None:
            return []
        return [n.decode() if isinstance(n, bytes) else str(n) for n in read_typed(attrs)["Name"]]


@dataclass(frozen=True)
class ParentGeometry:
    """Native geometry of one 2D flow area as stored in a plan HDF."""

    mesh_name: str
    cell_count: int  # physical cells; ids at or above this are ghost cells
    face_cells: Any
    face_normal: Any
    face_length: Any
    face_points: Any
    point_xy: Any
    cell_center: Any  # physical cells only
    cell_min_elevation: Any  # physical cells only
    crs_wkt: Optional[str]


def read_geometry(hdf_path: Path, mesh_name: str) -> ParentGeometry:
    """Read the face and cell tables of ``mesh_name`` from a plan or geometry HDF."""
    import h5py

    from ..hdf.HdfBase import HdfBase

    base = f"Geometry/2D Flow Areas/{mesh_name}"
    with h5py.File(hdf_path, "r") as f:
        if base not in f:
            raise ValueError(f"{hdf_path.name} has no 2D flow area {mesh_name!r}")
        attrs = read_typed(f["Geometry/2D Flow Areas/Attributes"])
        names = [n.decode() if isinstance(n, bytes) else str(n) for n in attrs["Name"]]
        cell_count = int(attrs["Cell Count"][names.index(mesh_name)])
        g = f[base]
        face_cells = np.asarray(read_typed(g["Faces Cell Indexes"]), np.int64)
        nl = np.asarray(read_typed(g["Faces NormalUnitVector and Length"]), float)
        face_points = np.asarray(read_typed(g["Faces FacePoint Indexes"]), np.int64)
        point_xy = np.asarray(read_typed(g["FacePoints Coordinate"]), float)
        centers = np.asarray(read_typed(g["Cells Center Coordinate"]), float)[:cell_count]
        # A mesh-only geometry HDF (not yet preprocessed) has no property tables.
        min_elev = (np.asarray(read_typed(g["Cells Minimum Elevation"]), float)[:cell_count]
                    if "Cells Minimum Elevation" in g else np.full(cell_count, np.nan))
    return ParentGeometry(
        mesh_name=mesh_name, cell_count=cell_count, face_cells=face_cells,
        face_normal=nl[:, :2], face_length=nl[:, 2], face_points=face_points,
        point_xy=point_xy, cell_center=centers, cell_min_elevation=min_elev,
        crs_wkt=HdfBase.get_projection(hdf_path),
    )


def same_geometry(a: ParentGeometry, b: ParentGeometry) -> bool:
    return (a.cell_count == b.cell_count and a.face_cells.shape == b.face_cells.shape
            and np.array_equal(a.face_cells, b.face_cells)
            and np.allclose(a.point_xy, b.point_xy))


def require_feet(hdf_path: Path) -> None:
    """Refuse SI results (this release scores in feet)."""
    from ..hdf.HdfBase import HdfBase

    meta = HdfBase.get_result_unit_metadata(hdf_path)
    system = str(meta.get("unit_system", "")).strip().lower()
    if system not in _FOOT_UNITS:
        raise NotImplementedError(
            f"{hdf_path.name}: unit system {meta.get('unit_system')!r}; the subdomain search "
            "supports US Customary (feet) models only in this release"
        )


def require_face_flow(hdf_path: Path, mesh_name: str) -> None:
    import h5py

    with h5py.File(hdf_path, "r") as f:
        if f"{_TS}/{mesh_name}/Face Flow" not in f:
            raise ValueError(
                f"{hdf_path.name} has no native 'Face Flow' output for {mesh_name!r}. Add it with "
                "RasPlan.add_hdf_output_variable(plan, 'Face Flow') and rerun the plan."
            )


class EventReader:
    """One parent event (plan HDF): time axis, event volumes, peaks, selected series."""

    def __init__(self, hdf_path: Path, mesh_name: str, batch_size: int = 32):
        self.path = Path(hdf_path)
        self.mesh = mesh_name
        self.batch_size = batch_size
        self._seconds: Optional[np.ndarray] = None

    def _iter(self, var: str):
        from ..hdf.HdfResultsMesh import HdfResultsMesh

        return HdfResultsMesh.iter_mesh_timeseries(self.path, self.mesh, var,
                                                   batch_size=self.batch_size)

    def seconds(self) -> np.ndarray:
        if self._seconds is None:
            from ..hdf.HdfResultsMesh import HdfResultsMesh

            da = HdfResultsMesh.get_mesh_timeseries(self.path, self.mesh, "Face Flow",
                                                    truncate=False, spatial_selection=0)
            t = np.asarray(da.coords["time"].values).astype("datetime64[ns]")
            self._seconds = (t - t[0]).astype("timedelta64[ns]").astype(np.int64) / 1e9
        return self._seconds

    def face_volumes(self, weights: np.ndarray) -> np.ndarray:
        """Event-integrated net volume per face along its stored normal, ft3."""
        volume = None
        row = 0
        for batch in self._iter("Face Flow"):
            values = np.nan_to_num(np.asarray(batch.values, float), nan=0.0)
            n = values.shape[0]
            part = weights[row: row + n] @ values
            volume = part if volume is None else volume + part
            row += n
        if row != len(weights):
            raise ValueError(f"{self.path.name}: Face Flow has {row} rows, time axis {len(weights)}")
        return volume

    def max_depth(self, geometry: ParentGeometry) -> np.ndarray:
        """Peak depth per physical cell: maximum water surface less the cell minimum elevation."""
        from ..hdf.HdfResultsMesh import HdfResultsMesh

        frame = HdfResultsMesh.get_mesh_summary_values(self.path, "Maximum Water Surface")
        frame = frame[frame["mesh_name"] == self.mesh]
        wse = np.full(geometry.cell_count, np.nan)
        ids = frame["cell_id"].to_numpy(int)
        keep = (ids >= 0) & (ids < geometry.cell_count)
        wse[ids[keep]] = frame["maximum_water_surface"].to_numpy(float)[keep]
        return np.nan_to_num(wse - geometry.cell_min_elevation, nan=0.0).clip(min=0.0)

    def series(self, var: str, ids: Iterable[int]) -> tuple[np.ndarray, np.ndarray]:
        """``(time, entity)`` series of the selected faces or cells, native units."""
        ids = np.asarray(sorted(set(int(i) for i in ids)), np.int64)
        parts = []
        for batch in self._iter(var):
            parts.append(np.asarray(batch.values[:, ids], np.float32))
        return ids, (np.concatenate(parts) if parts else np.empty((0, len(ids)), np.float32))


def face_tables(hdf_path: Path, mesh_name: str, faces: Sequence[int]) -> Dict[int, np.ndarray]:
    """Face property tables ``(elevation, area, wetted perimeter, n)`` of ``faces``.

    Reads only the requested rows of ``Faces Area Elevation Info``/``Values``;
    :meth:`HdfMesh.get_mesh_face_property_tables` would load every face of every mesh.
    """
    import h5py

    base = f"Geometry/2D Flow Areas/{mesh_name}"
    wanted = sorted(set(int(f) for f in faces))
    out: Dict[int, np.ndarray] = {}
    with h5py.File(hdf_path, "r") as f:
        if f"{base}/Faces Area Elevation Values" not in f:
            raise ValueError(f"{hdf_path.name} has no face property tables for {mesh_name!r}")
        info = np.asarray(read_typed(f[f"{base}/Faces Area Elevation Info"]))
        values = f[f"{base}/Faces Area Elevation Values"]
        for face in wanted:
            start, count = (int(v) for v in info[face][:2])
            out[face] = np.asarray(values[start: start + count, :4], float)
    return out
