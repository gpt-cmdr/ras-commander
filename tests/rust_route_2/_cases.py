"""Public methods routed by PY-ROUTE-2 (Wave 3 families), keyed ``Class.method[variant]``.

Each entry maps to a callable taking the fixture path. Arguments that select an
element (network, conduit, node, reference feature, region, profile) are derived
from the file with h5py inside the callable, identically in every mode; the h5py
guard treats reads made from this module as harness reads.
"""
import h5py

from ras_commander.hdf import HdfPipe

PIPE_TS = "Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/Unsteady Time Series/Pipe Networks"
PIPE_VARIABLES = [
    "Cell Courant", "Cell Water Surface", "Face Flow", "Face Velocity", "Face Water Surface",
    "Pipes/Pipe Flow DS", "Pipes/Pipe Flow US", "Pipes/Vel DS", "Pipes/Vel US",
    "Nodes/Depth", "Nodes/Drop Inlet Flow", "Nodes/Water Surface",
]


def _rows(path, dataset):
    with h5py.File(path, "r") as f:
        return len(f[dataset]) if dataset in f else 0


def _pipe_profile_last(path):
    rows = _rows(path, "Geometry/Pipe Conduits/Terrain Profiles Info")
    return HdfPipe.get_pipe_profile(path, max(rows - 1, 0))


def _pipe_network_named(path):
    with h5py.File(path, "r") as f:
        key = "Geometry/Pipe Networks/Attributes"
        name = f[key][()]["Name"][0].decode() if key in f and len(f[key]) else "__absent__"
    return HdfPipe.get_pipe_network(path, pipe_network_name=name)


CASES = {
    "HdfPipe.get_pipe_conduits": lambda p: HdfPipe.get_pipe_conduits(p),
    "HdfPipe.get_pipe_nodes": lambda p: HdfPipe.get_pipe_nodes(p),
    "HdfPipe.get_pipe_inlets": lambda p: HdfPipe.get_pipe_inlets(p),
    "HdfPipe.get_pipe_network": lambda p: HdfPipe.get_pipe_network(p),
    "HdfPipe.get_pipe_network[named]": _pipe_network_named,
    "HdfPipe.get_pipe_profile[first]": lambda p: HdfPipe.get_pipe_profile(p, 0),
    "HdfPipe.get_pipe_profile[last]": _pipe_profile_last,
    "HdfPipe.get_pipe_network_summary": lambda p: HdfPipe.get_pipe_network_summary(p),
    "HdfPipe.extract_timeseries_for_node": lambda p: HdfPipe.extract_timeseries_for_node(p, 0),
    "HdfPipe.extract_timeseries_for_conduit": lambda p: HdfPipe.extract_timeseries_for_conduit(p, 0),
}
for _variable in PIPE_VARIABLES:
    CASES[f"HdfPipe.get_pipe_network_timeseries[{_variable}]"] = (
        lambda p, v=_variable: HdfPipe.get_pipe_network_timeseries(p, variable=v))
