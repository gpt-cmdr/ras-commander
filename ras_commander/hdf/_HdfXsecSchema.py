"""
Cross-section schema helpers that need only h5py.

``GeomMetadata`` counts cross sections while building ``geom_df``. The core
``ras-commander`` install has no geopandas or shapely, so these helpers live
outside ``HdfXsec``, which imports both at module level. ``HdfXsec`` delegates
to this module, so both callers share one schema-recognition contract.
"""

import h5py


def cross_section_group(hdf: h5py.File) -> h5py.Group:
    """Return the cross-section group or fail with a schema-specific error."""
    path = "/Geometry/Cross Sections"
    if path not in hdf or not isinstance(hdf[path], h5py.Group):
        raise ValueError(f"Missing cross-section group: {path}")
    return hdf[path]


def get_cross_section_count(hdf: h5py.File) -> int:
    """Return the XS row count for compound or legacy separated schemas.

    HEC-RAS 5.x geometry HDF files store cross-section identity and
    hydraulic attributes in separate datasets instead of the compound
    ``Attributes`` dataset used by newer releases. A legacy schema is
    recognized only when its three independent row anchors are present.
    All feature-row datasets that are present must agree on row count.
    This establishes dimensional evidence; full reader methods separately
    validate the datasets needed to extract hydraulic content.
    """
    path = "/Geometry/Cross Sections"
    if path not in hdf:
        return 0
    group = cross_section_group(hdf)

    if "Attributes" in group:
        attributes = group["Attributes"]
        if not isinstance(attributes, h5py.Dataset) or len(attributes.shape) != 1:
            raise ValueError(
                "Cross-section Attributes must be a one-dimensional dataset; "
                f"found {getattr(attributes, 'shape', None)}"
            )
        row_count = int(attributes.shape[0])
    else:
        legacy_anchors = ("Node Names", "River Stations", "Polyline Info")
        present = [name for name in legacy_anchors if name in group]
        if not present:
            return 0
        if len(present) != len(legacy_anchors):
            missing = sorted(set(legacy_anchors) - set(present))
            raise ValueError(
                "Incomplete legacy cross-section schema; missing row anchors: "
                + ", ".join(missing)
            )
        row_count = int(group["Polyline Info"].shape[0])

    row_datasets = (
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
    inconsistent = []
    for name in row_datasets:
        if name not in group:
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
    return row_count
