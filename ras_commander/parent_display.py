"""Source-geometry feature probe for parent-model display extraction.

``HdfStruc.get_structures`` and ``HdfMesh.get_mesh_areas`` return an empty
GeoDataFrame whether the feature is absent, its tables are incomplete, or an
error occurred. A display publisher cannot tell "this model has no structures"
from "structures were not extracted". This module adds the missing primitive:
a read-only probe that inspects HDF group and dataset presence and row counts
only (no geometry arrays) and returns a closed status vocabulary.

Reading, parsing and geometry building stay in ``HdfMesh``, ``HdfBndry`` and
``HdfStruc``; this module never parses features itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import h5py

from .Decorators import log_call
from .fast_hdf import read_attr, reraise_required
from .LoggingConfig import get_logger

logger = get_logger(__name__)

# Closed, stable reason codes. Meaning must not change silently.
FEATURE_PRESENT = "FEATURE_PRESENT"
NOT_IN_SOURCE = "NOT_IN_SOURCE"
EMPTY_IN_SOURCE = "EMPTY_IN_SOURCE"
SOURCE_TABLE_INCOMPLETE = "SOURCE_TABLE_INCOMPLETE"
READ_ERROR = "READ_ERROR"

PROBE_CODES = (FEATURE_PRESENT, NOT_IN_SOURCE, EMPTY_IN_SOURCE, SOURCE_TABLE_INCOMPLETE, READ_ERROR)

# feature -> (HDF group, datasets that must exist for the group to be readable,
#             dataset whose first dimension is the feature count)
FEATURE_SOURCES: Mapping[str, tuple[str, tuple[str, ...], str]] = {
    "mesh_areas": (
        "Geometry/2D Flow Areas",
        ("Attributes",),
        "Attributes",
    ),
    "breaklines": (
        "Geometry/2D Flow Area Break Lines",
        ("Attributes",),
        "Attributes",
    ),
    "refinement_regions": (
        "Geometry/2D Flow Area Refinement Regions",
        ("Attributes",),
        "Attributes",
    ),
    "structures": (
        "Geometry/Structures",
        ("Attributes", "Centerline Info", "Centerline Points"),
        "Attributes",
    ),
}


@dataclass(frozen=True)
class FeatureProbe:
    """Whether a source feature exists and how many rows its table declares.

    ``reason_code`` is one of ``PROBE_CODES``. ``confirmed_zero`` is True only
    when the source itself shows no features (group absent, or an intact table
    with zero rows). An incomplete table or a read error is never zero.
    These statements describe only the known HDF layout, not the entire model.
    ``FEATURE_PRESENT`` checks required table presence and nonempty supporting
    rows; it does not validate geometry values or table index relationships.
    """

    feature: str
    reason_code: str
    source_rows: int | None
    hdf_group: str
    missing_datasets: tuple[str, ...] = ()
    detail: str | None = None

    @property
    def confirmed_zero(self) -> bool:
        return self.reason_code in (NOT_IN_SOURCE, EMPTY_IN_SOURCE)


@log_call
def probe_geometry_features(
    geometry_hdf: str | Path, features: tuple[str, ...] | None = None
) -> dict[str, FeatureProbe]:
    """Probe parent geometry HDF features without reading any geometry arrays.

    Parameters
    ----------
    geometry_hdf : path of a HEC-RAS geometry HDF (``.g??.hdf``); opened read-only.
    features : subset of ``FEATURE_SOURCES``; default all.

    Returns
    -------
    dict mapping feature name to ``FeatureProbe``. Never mutates the file, never
    raises for an unreadable feature: that feature gets ``READ_ERROR``. A file that
    cannot be opened at all raises ``OSError`` because no feature can be judged.
    """
    names = features or tuple(FEATURE_SOURCES)
    unknown = [name for name in names if name not in FEATURE_SOURCES]
    if unknown:
        raise ValueError(f"Unknown geometry features: {unknown}")
    probes: dict[str, FeatureProbe] = {}
    with h5py.File(Path(geometry_hdf), "r") as hdf:
        for name in names:
            probes[name] = _probe_one(hdf, name)
    return probes


def _probe_one(hdf: h5py.File, name: str) -> FeatureProbe:
    group_path, required, count_dataset = FEATURE_SOURCES[name]
    try:
        if group_path not in hdf:
            return FeatureProbe(name, NOT_IN_SOURCE, 0, group_path)
        group = hdf[group_path]
        missing = tuple(item for item in required if item not in group)
        if missing:
            return FeatureProbe(
                name, SOURCE_TABLE_INCOMPLETE, None, group_path, missing_datasets=missing
            )
        rows = int(group[count_dataset].shape[0])
        for item in required:
            table = group[item]
            if not isinstance(table, h5py.Dataset) or not table.shape:
                return FeatureProbe(
                    name, SOURCE_TABLE_INCOMPLETE, rows, group_path,
                    detail=f"{item} is not a row-indexed dataset",
                )
            if rows > 0 and table.shape[0] == 0:
                return FeatureProbe(
                    name, SOURCE_TABLE_INCOMPLETE, rows, group_path,
                    detail=f"{item} is empty but {count_dataset} declares {rows} features",
                )
        code = FEATURE_PRESENT if rows > 0 else EMPTY_IN_SOURCE
        return FeatureProbe(name, code, rows, group_path)
    except Exception as exc:  # one bad feature must not hide the others
        logger.warning("Could not probe %s in %s: %s", group_path, hdf.filename, type(exc).__name__)
        return FeatureProbe(name, READ_ERROR, None, group_path, detail=type(exc).__name__)


# --- applied boundary-condition forcing (Phase 2) --------------------------------------

APPLIED_TIME_SERIES = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
APPLIED_BC_GROUP = f"{APPLIED_TIME_SERIES}/Boundary Conditions"
_PER_FACE_SUFFIXES = (" - Flow per Face", " - Stage per Face")


@dataclass(frozen=True)
class AppliedBoundary:
    """One applied boundary-condition series, described without reading its values.

    ``columns`` comes from the dataset's ``Columns`` attribute (for example
    ``("Stage", "Flow")``); ``units`` is the ``Units`` attribute when the file has one,
    else ``None``. Nothing is inferred when an attribute is absent.
    """

    name: str
    columns: tuple[str, ...]
    time_steps: int | None
    units: str | None
    flow_per_face: bool
    stage_per_face: bool


@dataclass(frozen=True)
class AppliedForcingProbe:
    """Applied (solver-used) boundary-condition series of one plan HDF.

    ``reason_code`` uses the same closed set as ``FeatureProbe``. ``boundaries`` is
    empty unless ``FEATURE_PRESENT``. Applied forcing is what the run used; it is not the
    configured input and not a measured face flux.
    """

    reason_code: str
    boundaries: tuple[AppliedBoundary, ...] = ()
    time_steps: int | None = None
    time_units: str | None = None
    detail: str | None = None

    @property
    def confirmed_zero(self) -> bool:
        return self.reason_code in (NOT_IN_SOURCE, EMPTY_IN_SOURCE)


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


@log_call
def probe_applied_forcing(plan_hdf: str | Path) -> AppliedForcingProbe:
    """Describe the applied boundary-condition series in a plan result HDF.

    Reads group membership, dataset shapes and small attributes only: no value array
    is read. ``HdfResultsMesh.get_boundary_conditions_timeseries`` returns an empty
    Dataset when the group is missing, which cannot be told from "no boundary
    conditions"; this probe separates absent, empty, incomplete and unreadable.

    ``FEATURE_PRESENT`` requires two-dimensional series whose row counts match
    the one-dimensional Time dataset, and matching column labels when supplied.
    It does not validate timestamps, values, units, or hydraulic suitability.
    Absence and zero statuses refer only to this stored output group.
    Raises ``OSError`` if the file cannot be opened. Never mutates the file.
    """
    with h5py.File(Path(plan_hdf), "r") as hdf:
        try:
            if APPLIED_BC_GROUP not in hdf:
                return AppliedForcingProbe(NOT_IN_SOURCE)
            group = hdf[APPLIED_BC_GROUP]
            names = sorted(n for n in group.keys() if not n.endswith(_PER_FACE_SUFFIXES))
            if not names:
                return AppliedForcingProbe(EMPTY_IN_SOURCE)
            time_path = f"{APPLIED_TIME_SERIES}/Time"
            if time_path not in hdf:
                return AppliedForcingProbe(
                    SOURCE_TABLE_INCOMPLETE, detail="Unsteady Time Series/Time is missing"
                )
            time = hdf[time_path]
            if not isinstance(time, h5py.Dataset) or time.ndim != 1:
                return AppliedForcingProbe(
                    SOURCE_TABLE_INCOMPLETE, detail="Time is not a one-dimensional dataset"
                )
            time_steps = int(time.shape[0])
            boundaries = []
            for name in names:
                item = group[name]
                if not isinstance(item, h5py.Dataset):
                    return AppliedForcingProbe(
                        SOURCE_TABLE_INCOMPLETE, detail=f"{name} is not a dataset"
                    )
                if item.ndim != 2 or item.shape[0] != time_steps:
                    return AppliedForcingProbe(
                        SOURCE_TABLE_INCOMPLETE,
                        detail=f"{name} shape {item.shape} does not match Time ({time_steps} rows)",
                    )
                columns = tuple(_text(c) for c in read_attr(item, "Columns", ()))
                if columns and len(columns) != item.shape[1]:
                    return AppliedForcingProbe(
                        SOURCE_TABLE_INCOMPLETE,
                        detail=f"{name} Columns count does not match its second dimension",
                    )
                boundaries.append(
                    AppliedBoundary(
                        name=name,
                        columns=columns,
                        time_steps=int(item.shape[0]) if item.shape else None,
                        units=_text(read_attr(item, "Units", None)),
                        flow_per_face=f"{name} - Flow per Face" in group,
                        stage_per_face=f"{name} - Stage per Face" in group,
                    )
                )
            return AppliedForcingProbe(
                FEATURE_PRESENT,
                tuple(boundaries),
                time_steps=time_steps,
                time_units=_text(time.attrs.get("Units")),
            )
        except Exception as exc:  # report, never guess
            reraise_required(exc)
            logger.warning("Could not probe applied forcing in %s: %s", hdf.filename, type(exc).__name__)
            return AppliedForcingProbe(READ_ERROR, detail=type(exc).__name__)


# --- configured forcing: normalized descriptors over the existing parser output ---------

CONFIGURED_TABLE_TYPES = (
    "Flow Hydrograph",
    "Stage Hydrograph",
    "Lateral Inflow Hydrograph",
    "Uniform Lateral Inflow",
    "Gate Openings",
    "Precipitation Hydrograph",
    "Rating Curve",
)
_LOCATION_COLUMNS = (
    "River Name",
    "Reach Name",
    "River Station",
    "Downstream River Station",
    "Storage Area Connection",
    "Storage Area Name",
    "Pump Station Name",
    "Blank 1",
    "Blank 2",
)


def _cell(value) -> str:
    return value.strip() if isinstance(value, str) else ""


@log_call
def normalize_configured_boundaries(boundaries) -> list[dict]:
    """Reduce ``RasUnsteady.extract_boundary_and_tables`` output to validated descriptors.

    ``boundaries`` is that method's DataFrame (columns ``DSS File``, ``Tables`` and the nine
    split location columns). It is not parsed again here. Each descriptor holds only what
    the frame states: ``location_fields`` (the non-empty location columns, verbatim and
    named by the parser's own column labels, with no claim about what a column means),
    ``table_types`` (known table headers present), ``bc_type`` (the table type when exactly
    one, else ``None``), ``has_table`` and ``dss_linked`` (a DSS file is named; its path is
    never copied). Units, time interval and BC-line geometry are not stated by the parser
    and are not invented. Returns ``[]`` for ``None`` or an empty frame.
    Raises ``ValueError`` if a non-empty frame lacks the parser's columns.
    """
    if boundaries is None or len(boundaries) == 0:
        return []
    missing = [c for c in ("DSS File", "Tables") if c not in boundaries.columns]
    if missing:
        raise ValueError(f"not extract_boundary_and_tables output; missing columns {missing}")
    descriptors = []
    for row in boundaries.to_dict("records"):
        fields = {c: _cell(row.get(c)) for c in _LOCATION_COLUMNS if _cell(row.get(c))}
        tables = row.get("Tables")
        types = [t for t in (tables if isinstance(tables, dict) else {}) if t in CONFIGURED_TABLE_TYPES]
        descriptors.append(
            {
                "location_fields": fields,
                "table_types": types,
                "bc_type": types[0] if len(types) == 1 else None,
                "has_table": bool(types),
                "dss_linked": bool(_cell(row.get("DSS File"))),
            }
        )
    return descriptors
