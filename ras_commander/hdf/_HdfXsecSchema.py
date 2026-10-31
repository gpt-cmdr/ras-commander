"""
Cross-section schema helpers that need only h5py.

``GeomMetadata`` counts cross sections while building ``geom_df``. The core
``ras-commander`` install has no geopandas or shapely, so these helpers live
outside ``HdfXsec``, which imports both at module level. ``HdfXsec`` delegates
to this module, so both callers share one schema-recognition contract.
"""

from typing import FrozenSet, Tuple

import h5py


def cross_section_group(hdf: h5py.File) -> h5py.Group:
    """Return the cross-section group or fail with a schema-specific error."""
    path = "/Geometry/Cross Sections"
    if path not in hdf or not isinstance(hdf[path], h5py.Group):
        raise ValueError(f"Missing cross-section group: {path}")
    return hdf[path]


# Separated-layout datasets that independently anchor the cross-section row
# count of a HEC-RAS 5.0.x hybrid file (see ``cross_section_layout``).
HYBRID_ANCHORS = (
    "Node Names",
    "River Stations",
    "Polyline Info",
    "Station Elevation Info",
)
# Compound-layout row datasets that a hybrid file may carry stale.
COMPOUND_ROW_DATASETS = ("Attributes", "Manning's n Info", "Ineffective Info")

ROW_DATASETS = (
    "Polyline Info",
    "Station Elevation Info",
    "Manning's n Info",
    "Station Manning's n Info",
    "Ineffective Info",
    "Blocked Ineffective Info",
    "River Names",
    "Reach Names",
    "River Stations",
    "Node Names",
    "Node Descriptions",
    "Lengths",
    "Bank Stations",
    "Contr Expan Coef",
    "Hydraulic Tables Starting Elevation and Increment Size",
    "Hydraulic Tables Vertical and Horizontal Slices",
)


def _row_count(group: h5py.Group, name: str):
    """Return a dataset's leading dimension, or ``None`` if it is not a dataset."""
    if name not in group:
        return None
    dataset = group[name]
    if not isinstance(dataset, h5py.Dataset) or not dataset.shape:
        return None
    return int(dataset.shape[0])


def _decoded(values) -> list:
    return [
        (bytes(value).decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)).strip()
        for value in values
    ]


def _compound_rows_omit_separated_rows(group: h5py.Group) -> bool:
    """Return True when the compound rows are an in-order subset of the separated rows.

    Cross sections are identified by (River, Reach, RS). The compound
    ``Attributes`` table must name only cross sections that the separated
    ``River Names``, ``Reach Names`` and ``River Stations`` datasets also
    list, in the same order, and must omit at least one of them.
    """
    attributes = group["Attributes"]
    names = attributes.dtype.names or ()
    if not {"River", "Reach", "RS"} <= set(names):
        return False
    separated_names = ("River Names", "Reach Names", "River Stations")
    if not all(_row_count(group, name) is not None for name in separated_names):
        return False
    compound = list(
        zip(
            _decoded(attributes["River"]),
            _decoded(attributes["Reach"]),
            _decoded(attributes["RS"]),
        )
    )
    separated = list(
        zip(*(_decoded(group[name][()]) for name in separated_names))
    )
    if len(compound) >= len(separated):
        return False
    remaining = iter(separated)
    return all(row in remaining for row in compound)


def cross_section_layout(group: h5py.Group) -> Tuple[str, int, FrozenSet[str]]:
    """Return ``(layout, row_count, stale_datasets)`` for a cross-section group.

    ``layout`` is ``"compound"`` (compound ``Attributes`` table), ``"legacy"``
    (HEC-RAS 5.x separated datasets only), ``"hybrid"``, or ``"none"`` when the
    group holds neither layout.

    Some HEC-RAS 5.0.3 geometry files hold both layouts: a compound
    ``Attributes`` table (with its ``Manning's n Info`` and
    ``Ineffective Info``) that omits cross sections, next to separated datasets
    that agree with the plain-text geometry. A file is treated as hybrid only
    when the separated anchors ``Node Names``, ``River Stations``,
    ``Polyline Info`` and ``Station Elevation Info`` are all present and agree
    among themselves, and the compound table lists an in-order subset of the
    separated cross sections with at least one omitted. The compound
    datasets whose row count differs from the anchors are returned as stale and
    must not be read. Any other disagreement cannot identify the current
    representation, so it keeps the compound layout and fails the row check.
    """
    if "Attributes" in group:
        attributes = group["Attributes"]
        if not isinstance(attributes, h5py.Dataset) or len(attributes.shape) != 1:
            raise ValueError(
                "Cross-section Attributes must be a one-dimensional dataset; "
                f"found {getattr(attributes, 'shape', None)}"
            )
        compound_rows = int(attributes.shape[0])
        anchor_rows = {_row_count(group, name) for name in HYBRID_ANCHORS}
        if None not in anchor_rows and len(anchor_rows) == 1:
            separated_rows = anchor_rows.pop()
            if separated_rows != compound_rows and _compound_rows_omit_separated_rows(
                group
            ):
                stale = frozenset(
                    name
                    for name in COMPOUND_ROW_DATASETS
                    if _row_count(group, name) not in (None, separated_rows)
                )
                return "hybrid", separated_rows, stale
        return "compound", compound_rows, frozenset()

    legacy_anchors = ("Node Names", "River Stations", "Polyline Info")
    present = [name for name in legacy_anchors if name in group]
    if not present:
        return "none", 0, frozenset()
    if len(present) != len(legacy_anchors):
        missing = sorted(set(legacy_anchors) - set(present))
        raise ValueError(
            "Incomplete legacy cross-section schema; missing row anchors: "
            + ", ".join(missing)
        )
    return "legacy", int(group["Polyline Info"].shape[0]), frozenset()


def validated_cross_section_layout(
    group: h5py.Group,
) -> Tuple[str, int, FrozenSet[str]]:
    """Resolve the layout and require every live row dataset to agree.

    Stale compound datasets in a hybrid file are excluded from the check.
    """
    layout, row_count, stale = cross_section_layout(group)
    if layout == "none":
        return layout, 0, stale

    inconsistent = []
    for name in ROW_DATASETS:
        if name not in group or name in stale:
            continue
        dataset = group[name]
        if not isinstance(dataset, h5py.Dataset) or not dataset.shape:
            raise ValueError(f"Unreadable cross-section dataset: {group.name}/{name}")
        rows = int(dataset.shape[0])
        if rows != row_count:
            inconsistent.append(f"{name}={rows}")

    if inconsistent:
        raise ValueError(
            f"Cross-section row count mismatch (expected {row_count}): "
            + ", ".join(inconsistent)
        )
    return layout, row_count, stale


def get_cross_section_count(hdf: h5py.File) -> int:
    """Return the XS row count for compound, legacy or hybrid schemas.

    HEC-RAS 5.x geometry HDF files store cross-section identity and
    hydraulic attributes in separate datasets instead of the compound
    ``Attributes`` dataset used by newer releases. A legacy schema is
    recognized only when its three independent row anchors are present.
    A hybrid file's stale compound datasets are excluded (see
    ``cross_section_layout``). All other feature-row datasets that are
    present must agree on row count. This establishes dimensional evidence;
    full reader methods separately validate the datasets needed to extract
    hydraulic content.
    """
    path = "/Geometry/Cross Sections"
    if path not in hdf:
        return 0
    group = cross_section_group(hdf)
    return validated_cross_section_layout(group)[1]
