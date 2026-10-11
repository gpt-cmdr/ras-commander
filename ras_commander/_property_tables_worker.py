"""Internal native-only process for RASMapper property-table computation.

Execute this file directly, never through ``python -m ras_commander``: package
initialization imports h5py, whose same-name HDF5 DLL can capture HDF.PInvoke.
The parent validates the resulting geometry tables with h5py after this process
exits. This process must not import ras_commander or any Python GIS/HDF library.
"""

from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
from pathlib import Path


def main() -> None:
    """Compute native tables in the caller's disposable geometry HDF."""
    if importlib.util.find_spec("clr") is None:
        raise ImportError(
            "Native RASMapper requires pythonnet>=3.0.5. "
            "Install ras-commander[mesh] in this Windows Python environment."
        )
    install = Path(sys.argv[1]).absolute()
    geometry = Path(sys.argv[2]).absolute()
    runtime = install / "bin64"
    if not (runtime / "hdf5.dll").is_file():
        raise FileNotFoundError(f"HEC-RAS native HDF5 runtime not found: {runtime}")
    handles = []
    directories = (install, runtime, install / "GDAL" / "bin64")
    for directory in directories:
        if hasattr(os, "add_dll_directory"):
            handles.append(os.add_dll_directory(str(directory)))
    os.environ["PATH"] = ";".join(map(str, directories)) + ";" + os.environ["PATH"]
    os.environ["GDAL_DATA"] = str(install / "GDAL" / "common" / "data")
    os.environ["PROJ_LIB"] = os.environ["GDAL_DATA"]
    # Absolute loads happen before any managed HDF call. HDF.PInvoke then
    # resolves its same-name imports to HEC-RAS's own bundled pair.
    libraries = [
        ctypes.WinDLL(str(runtime / name)) for name in ("hdf5.dll", "hdf5_hl.dll")
    ]
    import clr

    sys.path.insert(0, str(install))
    for name in (
        "Utility.Core",
        "Geospatial.Core",
        "H5Assist",
        "RasMapperLib",
        "HDF.PInvoke",
    ):
        clr.AddReference(str(install / f"{name}.dll"))
    from HDF.PInvoke import H5

    bundled_version = [ctypes.c_uint() for _ in range(3)]
    if libraries[0].H5get_libversion(*(ctypes.byref(v) for v in bundled_version)) != 0:
        raise RuntimeError("Cannot inspect the bundled HEC-RAS HDF5 runtime.")
    managed_version = H5.get_libversion(0, 0, 0)
    if managed_version[0] != 0 or tuple(managed_version[1:]) != tuple(
        v.value for v in bundled_version
    ):
        raise RuntimeError("HDF.PInvoke did not bind the bundled HEC-RAS HDF5 runtime.")
    threadsafe = H5.is_library_threadsafe(0)
    if threadsafe[0] != 0 or threadsafe[1] != 1:
        raise RuntimeError("RASMapper requires the thread-safe HEC-RAS HDF5 runtime.")
    if len(sys.argv) == 4:
        from RasMapperLib import RASGeometry

        source = RASGeometry(str(Path(sys.argv[3]).absolute()))
        target = RASGeometry(str(geometry))
        source_regions = source.LandCoverRegions
        target_regions = target.LandCoverRegions
        if source_regions.FeatureCount() != target_regions.FeatureCount():
            raise RuntimeError("Native Manning region counts differ.")
        source_regions.LoadFeatureTable()
        target_regions.LoadFeatureTable()
        for index in range(source_regions.FeatureCount()):
            target_regions.SetLandCoverMapping(
                index, source_regions.GetLandCoverMapping(index)
            )
        if not target_regions.SaveFeatureTable():
            raise RuntimeError("Native Manning region mapping save failed.")
        return
    from RasMapperLib.Scripting import ComputePropertyTablesCommand

    ComputePropertyTablesCommand(str(geometry)).Execute(None)
    # Keep DLL handles alive through all native operations.
    del libraries, handles


if __name__ == "__main__":
    main()
