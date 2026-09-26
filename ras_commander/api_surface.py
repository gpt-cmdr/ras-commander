"""Package-owned scope for the shared documentation API surface generator.

Only these subpackages are imported beyond root __all__; this is a deliberate
inventory, not a claim that every library module or runtime is covered.
FIELD_DOCS keys use defining-module.Class.field, not an export alias. Links
refer to canonical source field documentation; the generator invents none.
"""

API_SURFACE_VERSION = 1

PUBLIC_MODULES = [
    "ras_commander.boundaries",
    "ras_commander.check",
    "ras_commander.geom",
    "ras_commander.gui",
    "ras_commander.hdf",
    "ras_commander.precip",
    "ras_commander.terrain",
    "ras_commander.usgs",
]

REQUIRED_SYMBOLS = ["RasCmdr", "RasPrj", "ComputeResult", "ComputeParallelResult", "HdfResultView"]

# These source classes document their fields adjacent to the declarations.
# Source links are explicit because generated HTML does not give each dataclass
# field a stable anchor. Other dataclass fields remain documentation:not_declared.
FIELD_DOCS = {
    **{
        f"ras_commander.ComputeResults.{class_name}.{field}":
        "https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/ComputeResults.py"
        for class_name, fields in {
            "ComputeResult": ["success", "results_df_row", "completion_verified", "execution_details"],
            "ComputeParallelResult": ["execution_results", "results_df", "execution_details_by_plan"],
        }.items()
        for field in fields
    },
    **{
        f"ras_commander.hdf.HdfResultView.HdfResultView.{field}":
        "https://github.com/gpt-cmdr/ras-commander/blob/main/ras_commander/hdf/HdfResultView.py"
        for field in ["source_path", "dataset_path", "time_path", "mesh_name", "variable", "units",
                      "id_dim", "source_shape", "source_dtype", "source_size", "source_mtime_ns",
                      "time_selection", "spatial_selection", "truncate"]
    },
}
