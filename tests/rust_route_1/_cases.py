"""Public routed methods exercised by the PY-ROUTE-1 equivalence suite.

Each entry maps ``Class.method[variant]`` to a callable taking the fixture path.
Arguments that select an element (river/reach/RS, structure, profile) are
derived from the file with h5py inside the callable, identically in every mode.
"""
from pathlib import Path

import h5py


def _xs_ids(path):
    with h5py.File(path, "r") as f:
        attrs = f["Geometry/Cross Sections/Attributes"][()]
    return [tuple(a[k].decode().strip() for k in ("River", "Reach", "RS")) for a in attrs]


def _texts(path, dataset, field):
    with h5py.File(path, "r") as f:
        if dataset not in f:
            return []
        rows = f[dataset][()]
    if field not in (rows.dtype.names or ()):
        return []
    return [r[field].decode(errors="replace").strip() for r in rows]


def _first(values, default="__absent__"):
    return next((v for v in values if v), default)


def _sa_first(path):
    return _first(_texts(path, "Geometry/Storage Areas/Attributes", "Name"))


def _structure_first(path):
    with h5py.File(path, "r") as f:
        if "Geometry/Structures/Attributes" not in f:
            return ("__absent__", "__absent__", "__absent__")
        rows = f["Geometry/Structures/Attributes"][()]
    for r in rows:
        if r["Type"].decode().strip() in {"Bridge", "Culvert", "Inline"}:
            return tuple(r[k].decode().strip() for k in ("River", "Reach", "RS"))
    return ("__absent__", "__absent__", "__absent__")


def _breach_id(path):
    for field in ("Connection", "Node Name"):
        value = _first(_texts(path, "Geometry/Structures/Attributes", field), "")
        if value:
            return value
    return "__absent__"


def _hdf():
    from ras_commander import hdf
    return hdf


def _xs_htab_first(path):
    ids = _xs_ids(path)
    return _hdf().HdfHydraulicTables.get_xs_htab(path, *ids[0])


def _xs_htab_last(path):
    ids = _xs_ids(path)
    return _hdf().HdfHydraulicTables.get_xs_htab(path, *ids[-1])


CASES = {
    "HdfXsec.get_cross_sections": lambda p: _hdf().HdfXsec.get_cross_sections(Path(p)),
    "HdfXsec.get_xs_coords": lambda p: _hdf().HdfXsec.get_xs_coords(Path(p)),
    "HdfXsec.get_river_centerlines": lambda p: _hdf().HdfXsec.get_river_centerlines(Path(p)),
    "HdfXsec.get_river_reaches": lambda p: _hdf().HdfXsec.get_river_reaches(Path(p)),
    "HdfXsec.get_river_edge_lines": lambda p: _hdf().HdfXsec.get_river_edge_lines(Path(p)),
    "HdfXsec.get_river_bank_lines": lambda p: _hdf().HdfXsec.get_river_bank_lines(Path(p)),
    "HdfXsec.get_river_flow_paths": lambda p: _hdf().HdfXsec.get_river_flow_paths(Path(p)),
    "HdfXsec.get_xs_interpolation_surface": lambda p: _hdf().HdfXsec.get_xs_interpolation_surface(Path(p)),
    "HdfXsec.generate_river_edge_lines": lambda p: _hdf().HdfXsec.generate_river_edge_lines(Path(p)),
    "HdfXsec.get_1d_footprint": lambda p: _hdf().HdfXsec.get_1d_footprint(Path(p)),
    "HdfHydraulicTables.get_xs_htab[first]": _xs_htab_first,
    "HdfHydraulicTables.get_xs_htab[last]": _xs_htab_last,
    "HdfHydraulicTables.get_all_xs_htabs": lambda p: _hdf().HdfHydraulicTables.get_all_xs_htabs(Path(p)),
    "HdfResultsXsec.get_xsec_timeseries": lambda p: _hdf().HdfResultsXsec.get_xsec_timeseries(Path(p)),
    "HdfResultsXsec.get_xsec_summary": lambda p: _hdf().HdfResultsXsec.get_xsec_summary(Path(p)),
    "HdfResultsPlan.get_steady_results": lambda p: _hdf().HdfResultsPlan.get_steady_results(Path(p)),
    "HdfResultsPlan.get_steady_wse": lambda p: _hdf().HdfResultsPlan.get_steady_wse(Path(p)),
    "HdfResultsPlan.get_steady_wse[profile0]": lambda p: _hdf().HdfResultsPlan.get_steady_wse(Path(p), profile_index=0),
    "HdfChannelCapacity.extract_steady_profile_wse": lambda p: _hdf().HdfChannelCapacity.extract_steady_profile_wse(Path(p)),
    "HdfChannelCapacity.extract_max_wse": lambda p: _hdf().HdfChannelCapacity.extract_max_wse(Path(p)),
    "HdfChannelCapacity.extract_bank_elevations": lambda p: _hdf().HdfChannelCapacity.extract_bank_elevations(Path(p)),
    "HdfChannelCapacity.analyze_channel_capacity": lambda p: _hdf().HdfChannelCapacity.analyze_channel_capacity(Path(p), Path(p)),
    "HdfStruc.get_structures": lambda p: _hdf().HdfStruc.get_structures(Path(p)),
    "HdfStruc.get_culvert_hydraulics": lambda p: _hdf().HdfStruc.get_culvert_hydraulics(Path(p)),
    "HdfStruc.get_storage_area_polygons": lambda p: _hdf().HdfStruc.get_storage_area_polygons(Path(p)),
    "HdfStruc.get_connection_attachments": lambda p: _hdf().HdfStruc.get_connection_attachments(Path(p)),
    "HdfStorageArea.get_storage_area_names": lambda p: _hdf().HdfStorageArea.get_storage_area_names(Path(p)),
    "HdfStorageArea.get_storage_area_properties": lambda p: _hdf().HdfStorageArea.get_storage_area_properties(Path(p), _sa_first(p)),
    "HdfStorageArea.get_volume_elevation_curve": lambda p: _hdf().HdfStorageArea.get_volume_elevation_curve(Path(p), _sa_first(p)),
    "HdfStorageArea.get_storage_area_for_breach_structure": lambda p: _hdf().HdfStorageArea.get_storage_area_for_breach_structure(Path(p), _breach_id(p)),
    "HdfStruc1D.get_structure_max_values": lambda p: _hdf().HdfStruc1D.get_structure_max_values(Path(p), *_structure_first(p)),
    "HdfPump.get_pump_stations": lambda p: _hdf().HdfPump.get_pump_stations(Path(p)),
    "HdfPump.get_pump_groups": lambda p: _hdf().HdfPump.get_pump_groups(Path(p)),
}
