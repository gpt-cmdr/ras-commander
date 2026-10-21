"""Public methods routed by PY-ROUTE-2 (Wave 3 families), keyed ``Class.method[variant]``.

Each entry maps to a callable taking the fixture path. Arguments that select an
element (network, conduit, node, reference feature, region, profile) are derived
from the file with h5py inside the callable, identically in every mode; the h5py
guard treats reads made from this module as harness reads.
"""
import h5py

from ras_commander.hdf import HdfBndry, HdfPipe, HdfResultsPlan, HdfResultsXsec

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


# ---------------------------------------------------------------- reference features
class _PlanProject:
    """Minimal initialized project whose plan_df points two plans at one fixture."""

    def __init__(self, path):
        import pandas as pd
        self.project_folder = str(path.parent) if hasattr(path, "parent") else "."
        self.project_name = "fixture"
        self.plan_df = pd.DataFrame({"plan_number": ["01", "02"],
                                     "HDF_Results_Path": [str(path), str(path)]})

    def check_initialized(self):
        return True


def _critical_duration(path, reftype):
    from pathlib import Path
    from ras_commander.hdf.HdfResultsAnalysis import HdfResultsAnalysis
    return HdfResultsAnalysis.analyze_critical_duration(
        ["01", "02"], plan_labels={"01": "a", "02": "b"}, reftype=reftype,
        ras_object=_PlanProject(Path(path)))


CASES.update({
    "HdfBndry.get_reference_points": lambda p: HdfBndry.get_reference_points(p),
    "HdfResultsXsec.get_ref_lines_timeseries": lambda p: HdfResultsXsec.get_ref_lines_timeseries(p),
    "HdfResultsXsec.get_ref_points_timeseries": lambda p: HdfResultsXsec.get_ref_points_timeseries(p),
    "HdfResultsPlan.get_reference_timeseries[lines]": lambda p: HdfResultsPlan.get_reference_timeseries(p, "lines"),
    "HdfResultsPlan.get_reference_timeseries[points]": lambda p: HdfResultsPlan.get_reference_timeseries(p, "points"),
    "HdfResultsPlan.get_reference_summary[lines]": lambda p: HdfResultsPlan.get_reference_summary(p, "lines"),
    "HdfResultsPlan.get_reference_summary[points]": lambda p: HdfResultsPlan.get_reference_summary(p, "points"),
    "HdfResultsAnalysis.analyze_critical_duration[lines]": lambda p: _critical_duration(p, "lines"),
    "HdfResultsAnalysis.analyze_critical_duration[points]": lambda p: _critical_duration(p, "points"),
})
