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


# ---------------------------------------------------------------- land cover / infiltration
from ras_commander.hdf import HdfInfiltration, HdfLandCover, HdfMesh  # noqa: E402


def _infiltration_variables(path):
    names = set()
    with h5py.File(path, "r") as f:
        areas = f.get("Geometry/2D Flow Areas")
        if areas is not None:
            for area in areas.values():
                if isinstance(area, h5py.Group) and isinstance(area.get("Infiltration"), h5py.Group):
                    names.update(k for k, v in area["Infiltration"].items() if isinstance(v, h5py.Dataset))
    return sorted(names) or ["Curve Number"]


def _preprocessed_infiltration(path, stats=False):
    method = (HdfInfiltration.get_preprocessed_infiltration_stats if stats
              else HdfInfiltration.get_preprocessed_infiltration)
    return {v: method(path, variable=v) for v in _infiltration_variables(path)}


def _calibration_region_faces(path):
    with h5py.File(path, "r") as f:
        key = "Geometry/Land Cover (Manning's n)/Attributes"
        region = (f[key][()]["Name"][0].decode() if key in f and len(f[key])
                  and "Name" in (f[key].dtype.names or ()) else "__absent__")
        mesh_key = "Geometry/2D Flow Areas/Attributes"
        mesh = f[mesh_key][()]["Name"][0].decode() if mesh_key in f and len(f[mesh_key]) else "__absent__"
    return HdfMesh.get_face_ids_in_calibration_region(path, mesh, region)


def _depth_curves(path):
    return HdfLandCover.build_landcover_depth_roughness_curves(
        path, [0.0, 1.0, 5.0], lambda depth, base_n, name: base_n * (1.0 + 0.01 * depth))


CASES.update({
    "HdfInfiltration.get_preprocessed_infiltration": _preprocessed_infiltration,
    "HdfInfiltration.get_preprocessed_infiltration_stats": lambda p: _preprocessed_infiltration(p, stats=True),
    "HdfInfiltration.get_infiltration_baseoverrides": lambda p: HdfInfiltration.get_infiltration_baseoverrides(p),
    "HdfInfiltration.get_infiltration_region_names": lambda p: HdfInfiltration.get_infiltration_region_names(p),
    "HdfInfiltration.get_infiltration_calibration_regions": lambda p: HdfInfiltration.get_infiltration_calibration_regions(p),
    "HdfInfiltration.get_infiltration_region_polygons": lambda p: HdfInfiltration.get_infiltration_region_polygons(p),
    "HdfInfiltration.get_infiltration_layer_data": lambda p: HdfInfiltration.get_infiltration_layer_data(p),
    "HdfInfiltration.get_classification_polygons": lambda p: HdfInfiltration.get_classification_polygons(p),
    "HdfInfiltration.get_infiltration_map": lambda p: HdfInfiltration.get_infiltration_map(p),
    "HdfInfiltration.get_infiltration_parameters": lambda p: HdfInfiltration.get_infiltration_parameters(p, mukey="__first__"),
    "HdfLandCover.build_landcover_depth_roughness_curves": _depth_curves,
    "HdfLandCover.get_landcover_raster_map": lambda p: HdfLandCover.get_landcover_raster_map(p),
    "HdfLandCover.get_classification_polygons": lambda p: HdfLandCover.get_classification_polygons(p),
    "HdfLandCover.compare_base_vs_calibrated": lambda p: HdfLandCover.compare_base_vs_calibrated(p),
    "HdfLandCover.get_preprocessed_mannings_stats": lambda p: HdfLandCover.get_preprocessed_mannings_stats(p),
    "HdfMesh.get_face_ids_in_calibration_region": _calibration_region_faces,
})

# Multi-file methods: called with a project entry {geom, landcover, infiltration}
# from the manifest's "projects" section (read-only project folders).
PROJECT_CASES = {
    "HdfInfiltration.get_soils_raster_stats": lambda j: HdfInfiltration.get_soils_raster_stats(
        j["geom"], soil_hdf_path=j.get("infiltration")),
    "HdfInfiltration.get_soil_raster_stats": lambda j: HdfInfiltration.get_soil_raster_stats(
        j["geom"], landcover_hdf_path=j["landcover"], soil_hdf_path=j.get("infiltration")),
    "HdfInfiltration.get_infiltration_stats": lambda j: HdfInfiltration.get_infiltration_stats(
        j["geom"], landcover_hdf_path=j["landcover"], soil_hdf_path=j.get("infiltration")),
    "HdfInfiltration.get_landcover_raster_stats": lambda j: HdfInfiltration.get_landcover_raster_stats(
        j["geom"], landcover_hdf_path=j["landcover"]),
    "HdfLandCover.estimate_final_mannings_raster": lambda j: HdfLandCover.estimate_final_mannings_raster(
        j["geom"], landcover_hdf_path=j["landcover"]),
    "HdfLandCover.compute_final_mannings_raster": lambda j: HdfLandCover.compute_final_mannings_raster(
        j["geom"], landcover_hdf_path=j["landcover"]),
}


# ---------------------------------------------------------------- terrain (storage stage-storage)
from ras_commander.hdf import HdfStorageArea  # noqa: E402


def _stage_storage(path):
    with h5py.File(path, "r") as f:
        key = "Geometry/Storage Areas/Attributes"
        name = f[key][()]["Name"][0].decode().strip() if key in f and len(f[key]) else "__absent__"
    return HdfStorageArea.compute_stage_storage_curve(path, name, elevation_interval=2.0)


CASES["HdfStorageArea.compute_stage_storage_curve"] = _stage_storage


# ---------------------------------------------------------------- sediment
from ras_commander.hdf.HdfResultsSediment import HdfResultsSediment  # noqa: E402

CASES.update({
    "HdfResultsSediment.is_sediment_plan": lambda p: HdfResultsSediment.is_sediment_plan(p),
    "HdfResultsSediment.get_sediment_mesh_areas": lambda p: HdfResultsSediment.get_sediment_mesh_areas(p),
    "HdfResultsSediment.get_cell_bed_change": lambda p: HdfResultsSediment.get_cell_bed_change(p),
    "HdfResultsSediment.get_cell_bed_change[first]": lambda p: HdfResultsSediment.get_cell_bed_change(p, time_index=0),
    "HdfResultsSediment.get_cell_bed_elevation": lambda p: HdfResultsSediment.get_cell_bed_elevation(p),
    "HdfResultsSediment.get_active_layer_grain_class": lambda p: HdfResultsSediment.get_active_layer_grain_class(p),
    "HdfResultsSediment.get_bed_change_volumes": lambda p: HdfResultsSediment.get_bed_change_volumes(p),
    "HdfResultsSediment.get_cell_bed_change_timeseries": lambda p: HdfResultsSediment.get_cell_bed_change_timeseries(p),
})
