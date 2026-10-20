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
}
