"""Serialize an owned cell subset in an isolated selected HEC-RAS runtime."""

import json
import runpy
import sys
from pathlib import Path


def main() -> None:
    """Load the native HDF5 module before any Python GIS/HDF dependency."""
    root = Path(__file__).absolute().parent
    runtime = runpy.run_path(
        str(root / "_property_tables_worker.py"), run_name="subset_runtime"
    )
    handles, libraries = runtime["_initialize_runtime"](Path(sys.argv[1]))
    from RasMapperLib import RASGeometry
    from System.Diagnostics import FileVersionInfo

    version = FileVersionInfo.GetVersionInfo(str(Path(sys.argv[1]) / "Ras.exe"))
    parts = (version.FileMajorPart, version.FileMinorPart, version.FileBuildPart,
             version.FilePrivatePart)
    # Qualified runtimes: 6.6, and 6.4.1 (file version 6.4.0.1; 6.4.0 is not).
    if parts[:2] != (6, 6) and parts != (6, 4, 0, 1):
        raise RuntimeError(
            f"Exact subset requires HEC-RAS 6.4.1 or 6.6, selected {version.FileVersion}"
        )
    suppress = runpy.run_path(
        str(root / "dotnet/geometry_save.py"), run_name="subset_save"
    )["suppress_feature_table_reloads"]
    geometry = RASGeometry(sys.argv[2])
    area = geometry.D2FlowArea
    if area.FeatureCount() != 1 or str(area.GetFeatureName(0)).strip() != sys.argv[3]:
        raise RuntimeError("Native subset must contain only the named child 2D area")
    mesh = area.Feature(0)
    if str(mesh.MeshCompletionState) != "Complete" or mesh.NonVirtualCellCount != int(
        sys.argv[4]
    ):
        raise RuntimeError("Native reader rejected the selected physical cell topology")
    with suppress(geometry):
        area.SetMeshHasBeenRecomputed(0, True)
        area.SetFeature(0, mesh)
        area.SetMeshUpToDate(0, True)
        geometry.Save()
    Path(sys.argv[5]).write_text(
        json.dumps(
            {
                "mesh_state": str(mesh.MeshCompletionState),
                "physical_cells": int(mesh.NonVirtualCellCount),
                "faces": int(mesh.FaceCount),
                "facepoints": int(mesh.FacePointCount),
                "executable_file_version": str(version.FileVersion),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    del handles, libraries


if __name__ == "__main__":
    main()
