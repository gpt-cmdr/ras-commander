"""Mapping-only plan HDF cut to an exact subset of parent 2D cells.

Qualified for the HEC-RAS 6.6 plan HDF schema only. The child keeps the
selected physical parent cells, their faces and facepoints exactly, with the
topology built by ``geom._cell_subset._build_subset`` (the same builder used by
``GeomMesh.apply_cell_subset``), so child cell and face numbering is identical
to an exact-subset child geometry made from the same IDs.

Results, when present, are copied for the selected output rows. New perimeter
ghost cells take the value of the dropped parent neighbour across the cut.
Face results whose sign follows the face normal are negated on faces whose
orientation was reversed. The file is never an input to a simulation: event
boundary data, meteorology, 1D/storage/structure elements, other 2D areas and
solver diagnostics are not carried over.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from ..LoggingConfig import get_logger

logger = get_logger(__name__)

QUALIFIED_FILE_VERSION = "HEC-RAS 6.6"
SCHEMA = "ras-mesh-results-subset/v1"

AREAS = "Geometry/2D Flow Areas"
BASE_OUTPUT = "Results/Unsteady/Output/Output Blocks/Base Output"
TIME_SERIES = BASE_OUTPUT + "/Unsteady Time Series"
SUMMARY = BASE_OUTPUT + "/Summary Output"
TIME_DATASETS = ("Time", "Time Date Stamp", "Time Date Stamp (ms)", "Time Step")

# Face values measured along the face normal change sign when c0/c1 swap.
SIGNED_FACE_SERIES = frozenset(
    {
        "Face Velocity",
        "Face Flow",
        "Face Cumulative Volume",
        "Face Flow Period Average",
        "Face Tangential Velocity",
        "Face Friction Term",
        "Face Pressure Gradient Term",
        "Face Wind Term",
    }
)
UNSIGNED_FACE_SERIES = frozenset(
    {
        "Face Water Surface",
        "Face Courant",
        "Face Shear Stress",
        "Face Area",
        "Face Manning's n",
        "Face Eddy Viscosity",
    }
)
# Summary rows are (value, time); the extreme keeps its magnitude and sign.
SIGNED_FACE_SUMMARY = frozenset({"Maximum Face Velocity", "Minimum Face Velocity"})
UNSIGNED_FACE_SUMMARY = frozenset({"Maximum Face Courant", "Maximum Face Shear Stress"})
# Solver diagnostics tied to parent cells, faces or boundaries.
DROPPED_AREA_CHILDREN = frozenset(
    {"Boundary Conditions", "Computations", "Reference Lines"}
)
DROPPED_SUMMARY = frozenset(
    {"Starting Differences Velocity", "Starting Differences WSE"}
)


@dataclass(frozen=True)
class MeshResultsSubset:
    """Record of a written mapping-only child plan HDF.

    Index arrays map child rows to parent rows: ``cell_source`` covers every
    child cell (physical cells first, then one ghost per new perimeter face,
    whose source is the dropped parent neighbour), ``face_source`` every child
    face and ``face_reversed`` marks faces whose orientation was reversed.
    """

    parent_plan_hdf: str
    child_plan_hdf: str
    mesh_name: str
    parent_sha256: str
    child_sha256: str
    parent_cell_ids: tuple[int, ...]
    output_rows: tuple[int, ...]
    has_results: bool
    ghost_cell_count: int
    face_count: int
    reversed_face_count: int
    facepoint_count: int
    perimeter: np.ndarray = field(repr=False)
    cell_source: np.ndarray = field(repr=False)
    face_source: np.ndarray = field(repr=False)
    face_reversed: np.ndarray = field(repr=False)
    dropped: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return identities, counts and dropped content; no index arrays."""
        return {
            "schema": SCHEMA,
            "parent_plan_hdf": self.parent_plan_hdf,
            "child_plan_hdf": self.child_plan_hdf,
            "mesh_name": self.mesh_name,
            "parent_sha256": self.parent_sha256,
            "child_sha256": self.child_sha256,
            "physical_cell_count": len(self.parent_cell_ids),
            "ghost_cell_count": self.ghost_cell_count,
            "face_count": self.face_count,
            "reversed_face_count": self.reversed_face_count,
            "facepoint_count": self.facepoint_count,
            "has_results": self.has_results,
            "output_rows": list(self.output_rows),
            "dropped": list(self.dropped),
            "purpose": "mapping_only",
            "hydraulic_validity": "not_established",
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value) -> str:
    return value.decode().rstrip("\x00 ") if isinstance(value, bytes) else str(value)


def _copy_attrs(src, dst) -> None:
    for key, value in src.attrs.items():
        dst.attrs[key] = value


def _create(dst_parent: h5py.Group, name: str, data, like: h5py.Dataset | None):
    data = np.asarray(data) if like is None else np.asarray(data, dtype=like.dtype)
    options: dict[str, Any] = {}
    if data.ndim and data.size:
        options["compression"] = "gzip"
        options["compression_opts"] = 1
        if like is not None and like.chunks is not None:
            options["chunks"] = tuple(
                max(1, min(c, n)) for c, n in zip(like.chunks, data.shape)
            )
    dataset = dst_parent.create_dataset(name, data=data, **options)
    if like is not None:
        _copy_attrs(like, dataset)
    return dataset


def _validate_rows(output_rows, n_times: int) -> tuple[int, ...]:
    if output_rows is None:
        return tuple(range(n_times))
    rows = np.asarray(output_rows)
    if rows.ndim != 1 or rows.dtype.kind not in "iu":
        raise ValueError("output_rows must be a sequence of integer row indexes")
    if len(np.unique(rows)) != len(rows):
        raise ValueError("output_rows contains duplicates")
    if np.any(rows < 0) or np.any(rows >= n_times):
        raise ValueError(f"output_rows must lie in 0..{n_times - 1}")
    return tuple(int(v) for v in rows)


class _Columns:
    """Map a parent area's per-cell or per-face last axis to the child."""

    def __init__(self, subset, n_cells: int, n_real: int, n_faces: int):
        if len({n_cells, n_real, n_faces}) != 3:
            raise ValueError("Parent cell, physical cell and face counts must differ")
        self.subset = subset
        self.n_cells, self.n_real, self.n_faces = n_cells, n_real, n_faces

    def kind(self, shape) -> str | None:
        last = shape[-1] if len(shape) else None
        return {self.n_cells: "cell", self.n_real: "real", self.n_faces: "face"}.get(
            last
        )

    def index(self, kind: str) -> np.ndarray:
        if kind == "cell":
            return self.subset.cell_src
        if kind == "real":
            return self.subset.cell_src[: self.subset.n_real]
        return self.subset.face_src

    def take(self, values: np.ndarray, kind: str) -> np.ndarray:
        return values[..., self.index(kind)]


def _copy_area_results(
    src_group, dst_parent, columns, rows, time_rows, n_times, summary, dropped
):
    """Copy one area's result datasets, mapping columns and output rows."""
    swap = columns.subset.face_swap
    dst = dst_parent.create_group(src_group.name.rsplit("/", 1)[-1])
    _copy_attrs(src_group, dst)
    for name, obj in src_group.items():
        path = obj.name
        if isinstance(obj, h5py.Group) or name in (
            DROPPED_SUMMARY if summary else DROPPED_AREA_CHILDREN
        ):
            dropped.append(path)
            continue
        kind = columns.kind(obj.shape)
        if kind is None:
            dropped.append(path)
            continue
        if kind == "face":
            signed = SIGNED_FACE_SUMMARY if summary else SIGNED_FACE_SERIES
            unsigned = UNSIGNED_FACE_SUMMARY if summary else UNSIGNED_FACE_SERIES
            if name not in signed and name not in unsigned and swap.any():
                # Orientation of an unclassified face quantity is unknown.
                dropped.append(path)
                continue
            negate = name in signed and swap.any()
        else:
            negate = False
        per_time = time_rows and obj.ndim == 2 and obj.shape[0] == n_times
        if per_time:
            width = len(columns.index(kind))
            out = dst.create_dataset(
                name,
                shape=(len(rows), width),
                dtype=obj.dtype,
                chunks=(1, width) if len(rows) else None,
                compression="gzip",
                compression_opts=1,
            )
            _copy_attrs(obj, out)
            for i, row in enumerate(rows):
                values = columns.take(obj[row], kind)
                if negate:
                    values = np.where(swap, -values, values)
                out[i] = values
            continue
        values = columns.take(obj[()], kind)
        if negate:
            values = values.copy()
            if summary:
                # Row 0 is the value; later rows are times or counts.
                values[0] = np.where(swap, -values[0], values[0])
            else:
                values = np.where(swap, -values, values)
        _create(dst, name, values, obj)


def _write_geometry(src, dst, mesh_name, subset, attributes_row, dropped):
    geometry = dst.create_group("Geometry")
    _copy_attrs(src["Geometry"], geometry)
    areas = geometry.create_group("2D Flow Areas")
    _copy_attrs(src[AREAS], areas)
    old = src[AREAS + "/" + mesh_name]
    area = areas.create_group(mesh_name)
    _copy_attrs(old, area)
    for name, obj in old.items():
        if name in subset.tables and isinstance(obj, h5py.Dataset):
            _create(area, name, subset.tables[name], obj)
        else:
            # Infiltration and other classification tables keyed to parent cells.
            dropped.append(obj.name)
    for name, values in subset.tables.items():
        if name not in area:
            _create(area, name, values, None)
    n_real = subset.n_real
    for name, values in (
        ("Attributes", attributes_row),
        ("Cell Info", np.array([[0, n_real]], dtype=np.int32)),
        ("Cell Points", subset.tables["Cells Center Coordinate"][:n_real]),
        ("Polygon Info", np.array([[0, len(subset.perimeter), 0, 1]], np.int32)),
        ("Polygon Parts", np.array([[0, len(subset.perimeter)]], np.int32)),
        ("Polygon Points", subset.perimeter),
    ):
        _create(areas, name, values, src.get(AREAS + "/" + name))
    extents = np.array(
        [
            subset.perimeter[:, 0].min(),
            subset.perimeter[:, 0].max(),
            subset.perimeter[:, 1].min(),
            subset.perimeter[:, 1].max(),
        ]
    )
    area.attrs["Extents"] = extents
    geometry.attrs["Extents"] = extents
    surface = subset.tables["Cells Surface Area"][:n_real]
    if np.isfinite(surface).all() and len(surface):
        area.attrs["Cell Maximum Index"] = np.int32(np.argmax(surface))
        for key, value in (
            ("Cell Maximum Size", surface.max()),
            ("Cell Minimum Size", surface.min()),
            ("Cell Average Size", surface.mean()),
        ):
            area.attrs[key] = np.float32(value)


def _write_results(src, dst, mesh_name, subset, columns, rows, dropped):
    results = dst.create_group("Results")
    _copy_attrs(src["Results"], results)
    unsteady = results.create_group("Unsteady")
    _copy_attrs(src["Results/Unsteady"], unsteady)
    for name, obj in src["Results/Unsteady"].items():
        if name == "Summary":
            src.copy(obj, unsteady, name=name)
        elif name not in ("Geometry Info", "Output"):
            dropped.append(obj.name)
    info = unsteady.create_group("Geometry Info")
    info.create_dataset("2D Area(s)", data=np.array([mesh_name.encode()], "S64"))
    base = dst.require_group(BASE_OUTPUT)
    for path in (
        "Results/Unsteady/Output",
        "Results/Unsteady/Output/Output Blocks",
        BASE_OUTPUT,
    ):
        _copy_attrs(src[path], dst[path])
    for name, obj in src["Results/Unsteady/Output/Output Blocks"].items():
        if name != "Base Output":
            dropped.append(obj.name)
    series = src[TIME_SERIES]
    n_times = len(series["Time"])
    out_series = base.create_group("Unsteady Time Series")
    _copy_attrs(series, out_series)
    for name, obj in series.items():
        if name in TIME_DATASETS:
            _create(out_series, name, obj[()][list(rows)], obj)
        elif name != "2D Flow Areas":
            dropped.append(obj.name)
    series_areas = out_series.create_group("2D Flow Areas")
    _copy_attrs(series["2D Flow Areas"], series_areas)
    for name, group in series["2D Flow Areas"].items():
        if name == mesh_name:
            _copy_area_results(
                group, series_areas, columns, rows, True, n_times, False, dropped
            )
        else:
            dropped.append(group.name)
    if SUMMARY in src:
        summary = src[SUMMARY]
        out_summary = base.create_group("Summary Output")
        _copy_attrs(summary, out_summary)
        for name, obj in summary.items():
            if name != "2D Flow Areas":
                dropped.append(obj.name)
        summary_areas = out_summary.create_group("2D Flow Areas")
        _copy_attrs(summary["2D Flow Areas"], summary_areas)
        for name, group in summary["2D Flow Areas"].items():
            if name == mesh_name:
                _copy_area_results(
                    group, summary_areas, columns, rows, False, n_times, True, dropped
                )
            else:
                dropped.append(group.name)


def _check_parent(src, mesh_name):
    file_type = _text(src.attrs.get("File Type", b""))
    version = _text(src.attrs.get("File Version", b""))
    if file_type != "HEC-RAS Results" or "Plan Data" not in src:
        raise ValueError(
            "parent must be a plan HDF; use GeomMesh.plan_cell_subset for a "
            "geometry HDF"
        )
    if not version.startswith(QUALIFIED_FILE_VERSION + " "):
        raise ValueError(
            f"plan HDF cell subsets are qualified for {QUALIFIED_FILE_VERSION} "
            f"only, not {version or 'an unknown version'}"
        )
    if AREAS + "/Attributes" not in src:
        raise ValueError("parent plan HDF has no 2D flow areas")
    attrs = src[AREAS + "/Attributes"][:]
    names = [_text(row["Name"]) for row in attrs]
    if mesh_name not in names:
        raise ValueError(f"2D area {mesh_name!r} is not in the parent ({names})")
    return attrs[names.index(mesh_name) : names.index(mesh_name) + 1].copy()


def _verify_child(child: Path, mesh_name: str, subset, parent_centres) -> None:
    """Read the written child back and check its exact parent correspondence."""
    with h5py.File(child, "r") as hdf:
        area = hdf[AREAS + "/" + mesh_name]
        centres = area["Cells Center Coordinate"][: subset.n_real]
        if not np.array_equal(centres, parent_centres):
            raise RuntimeError("child cell centres differ from the parent cells")
        faces = area["Faces Cell Indexes"][:]
        n_cells = len(area["Cells Center Coordinate"])
        if faces.min() < 0 or faces.max() >= n_cells:
            raise RuntimeError("child face incidence refers to missing cells")
        if int(hdf[AREAS + "/Attributes"][0]["Cell Count"]) != subset.n_real:
            raise RuntimeError("child cell count attribute is inconsistent")


def _write_cell_subset_results(
    parent_plan_hdf, child_plan_hdf, parent_cell_ids, mesh_name, output_rows, overwrite
) -> MeshResultsSubset:
    from ..geom._cell_subset import _selection

    parent = Path(parent_plan_hdf).absolute()
    child = Path(child_plan_hdf).absolute()
    if not parent.is_file():
        raise FileNotFoundError(f"parent plan HDF not found: {parent}")
    if child.exists():
        if child.resolve() == parent.resolve():
            raise ValueError("child and parent plan HDF must differ")
        if not overwrite:
            raise FileExistsError(f"child plan HDF exists: {child}")
    if not child.parent.is_dir():
        raise FileNotFoundError(f"child folder does not exist: {child.parent}")
    parent_hash = _sha256(parent)
    dropped: list = []
    staging = child.with_name(child.name + ".partial")
    if staging.exists():
        staging.unlink()
    try:
        with h5py.File(parent, "r") as src, h5py.File(staging, "w") as dst:
            attributes_row = _check_parent(src, mesh_name)
            group = src[AREAS + "/" + mesh_name]
            ids, subset = _selection(group, parent_cell_ids)
            n_cells = len(group["Cells Center Coordinate"])
            n_real = int(group["Faces Cell Indexes"][:, 0].max()) + 1
            if "Cell Count" in attributes_row.dtype.names:
                if int(attributes_row[0]["Cell Count"]) != n_real:
                    raise ValueError("parent cell count attribute is inconsistent")
                attributes_row["Cell Count"] = subset.n_real
            columns = _Columns(
                subset, n_cells, n_real, len(group["Faces Cell Indexes"])
            )
            parent_centres = group["Cells Center Coordinate"][:][ids]
            _copy_attrs(src, dst)
            for name in src:
                if name == "Plan Data":
                    src.copy(src[name], dst, name=name)
                elif name == "Event Conditions":
                    events = dst.create_group(name)
                    _copy_attrs(src[name], events)
                    for child_name, obj in src[name].items():
                        if child_name == "Meteorology":
                            dropped.append(obj.name)
                        else:
                            src.copy(obj, events, name=child_name)
                elif name not in ("Geometry", "Results"):
                    dropped.append("/" + name)
            for name, obj in src["Geometry"].items():
                if name != "2D Flow Areas":
                    dropped.append(obj.name)
            for name in src[AREAS]:
                if (
                    isinstance(src[AREAS + "/" + name], h5py.Group)
                    and name != mesh_name
                ):
                    dropped.append(f"/{AREAS}/{name}")
            _write_geometry(src, dst, mesh_name, subset, attributes_row, dropped)
            has_results = TIME_SERIES + "/Time" in src
            rows: tuple[int, ...] = ()
            if has_results:
                rows = _validate_rows(output_rows, len(src[TIME_SERIES + "/Time"]))
                _write_results(src, dst, mesh_name, subset, columns, rows, dropped)
            elif output_rows is not None:
                raise ValueError("output_rows given but the parent has no results")
        _verify_child(staging, mesh_name, subset, parent_centres)
        if _sha256(parent) != parent_hash:
            raise RuntimeError("parent plan HDF changed while the child was written")
        staging.replace(child)
    except BaseException:
        if staging.exists():
            staging.unlink()
        raise
    for path in dropped:
        logger.debug(f"Not carried into the child plan HDF: {path}")
    return MeshResultsSubset(
        parent_plan_hdf=str(parent),
        child_plan_hdf=str(child),
        mesh_name=mesh_name,
        parent_sha256=parent_hash,
        child_sha256=_sha256(child),
        parent_cell_ids=tuple(int(v) for v in ids),
        output_rows=rows,
        has_results=has_results,
        ghost_cell_count=len(subset.cell_src) - subset.n_real,
        face_count=len(subset.face_src),
        reversed_face_count=int(subset.face_swap.sum()),
        facepoint_count=len(subset.fp_src),
        perimeter=subset.perimeter,
        cell_source=subset.cell_src,
        face_source=subset.face_src,
        face_reversed=subset.face_swap,
        dropped=tuple(dropped),
    )
