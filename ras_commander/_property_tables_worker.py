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


def _loaded_hdf5_modules() -> dict[int, Path]:
    """Inspect every loaded module; basename lookup alone is ambiguous."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.EnumProcessModules.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    psapi.EnumProcessModules.restype = ctypes.c_int
    kernel.GetModuleFileNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_ulong,
    ]
    kernel.GetModuleFileNameW.restype = ctypes.c_ulong
    capacity = 256
    while True:
        modules = (ctypes.c_void_p * capacity)()
        needed = ctypes.c_ulong()
        if not psapi.EnumProcessModules(
            kernel.GetCurrentProcess(),
            modules,
            ctypes.sizeof(modules),
            ctypes.byref(needed),
        ):
            raise RuntimeError("Cannot inspect loaded HDF5 DLLs; refusing native work.")
        if needed.value <= ctypes.sizeof(modules):
            break
        capacity = needed.value // ctypes.sizeof(ctypes.c_void_p) + 1
    result = {}
    for handle in modules[: needed.value // ctypes.sizeof(ctypes.c_void_p)]:
        filename = ctypes.create_unicode_buffer(32768)
        length = kernel.GetModuleFileNameW(handle, filename, len(filename))
        if not length or length >= len(filename):
            raise RuntimeError("Cannot identify a loaded DLL; refusing native work.")
        path = Path(filename.value)
        if path.name.lower() in {"hdf5.dll", "hdf5_hl.dll"}:
            result[handle] = path
    return result


def _check_hdf5_modules(runtime: Path) -> dict[int, Path]:
    """Reject foreign HDF5 instances before opening a model."""
    modules = _loaded_hdf5_modules()
    for path in modules.values():
        if not path.samefile(runtime / path.name.lower()):
            raise RuntimeError(
                f"Foreign HDF5 DLL already loaded: {path}; "
                f"expected {runtime / path.name.lower()}. Refusing native work."
            )
    return modules


def _verify_managed_hdf5_identity(library, managed) -> None:
    """Verify shared object state, including reference changes in both directions."""
    for name, args, result in (
        ("H5open", [], ctypes.c_int),
        ("H5Pcreate", [ctypes.c_longlong], ctypes.c_longlong),
        ("H5Pclose", [ctypes.c_longlong], ctypes.c_int),
        ("H5Iget_ref", [ctypes.c_longlong], ctypes.c_int),
        ("H5Iinc_ref", [ctypes.c_longlong], ctypes.c_int),
    ):
        function = getattr(library, name)
        function.argtypes, function.restype = args, result
    if library.H5open() < 0:
        raise RuntimeError("Cannot initialize the selected HEC-RAS HDF5 DLL.")
    cls = ctypes.c_longlong.in_dll(library, "H5P_CLS_FILE_ACCESS_ID_g").value
    probe = library.H5Pcreate(cls)
    if probe < 0:
        raise RuntimeError("Cannot create the HDF5 DLL identity probe.")
    try:
        if (
            managed.is_valid(probe) != 1
            or managed.get_ref(probe) != 1
            or managed.inc_ref(probe) != 2
            or library.H5Iget_ref(probe) != 2
            or library.H5Iinc_ref(probe) != 3
            or managed.get_ref(probe) != 3
        ):
            raise RuntimeError(
                "HDF.PInvoke DLL identity check failed: managed calls do not share "
                "object state with the explicitly loaded HEC-RAS bin64 hdf5.dll."
            )
    finally:
        for _ in range(max(0, library.H5Iget_ref(probe))):
            if library.H5Pclose(probe) < 0:
                raise RuntimeError("Cannot close the HDF5 DLL identity probe.")


def _verify_hdf5_metadata(library, managed) -> None:
    """Check runtime compatibility separately from the DLL identity proof."""
    bundled_version = [ctypes.c_uint() for _ in range(3)]
    if library.H5get_libversion(*(ctypes.byref(v) for v in bundled_version)) != 0:
        raise RuntimeError("Cannot inspect the bundled HEC-RAS HDF5 runtime.")
    managed_version = managed.get_libversion(0, 0, 0)
    if managed_version[0] != 0 or tuple(managed_version[1:]) != tuple(
        v.value for v in bundled_version
    ):
        raise RuntimeError("HDF.PInvoke did not bind the bundled HEC-RAS HDF5 runtime.")
    threadsafe = managed.is_library_threadsafe(0)
    if threadsafe[0] != 0 or threadsafe[1] != 1:
        raise RuntimeError("RASMapper requires the thread-safe HEC-RAS HDF5 runtime.")


def _initialize_runtime(install: Path) -> tuple[list, list]:
    """Load and verify the native-only runtime; retain DLL loader handles."""
    # pythonnet's loaded clr module has no __spec__; find_spec would raise on reentry.
    if "clr" not in sys.modules and importlib.util.find_spec("clr") is None:
        raise ImportError(
            "Native RASMapper requires pythonnet>=3.0.5. "
            "Install ras-commander[mesh] in this Windows Python environment."
        )
    runtime = install / "bin64"
    if not (runtime / "hdf5.dll").is_file():
        raise FileNotFoundError(f"HEC-RAS native HDF5 runtime not found: {runtime}")
    _check_hdf5_modules(runtime)
    handles = []
    directories = (install, runtime, install / "GDAL" / "bin64")
    for directory in directories:
        if hasattr(os, "add_dll_directory"):
            handles.append(os.add_dll_directory(str(directory)))
    os.environ["PATH"] = ";".join(map(str, directories)) + ";" + os.environ["PATH"]
    os.environ["GDAL_DATA"] = str(install / "GDAL" / "common" / "data")
    os.environ["PROJ_LIB"] = os.environ["GDAL_DATA"]
    # Retain absolute loader handles and verify the managed object's state;
    # equal version/thread-safety values cannot establish DLL identity.
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
    from HDF.PInvoke import H5, H5I

    _verify_managed_hdf5_identity(libraries[0], H5I)
    modules = _check_hdf5_modules(runtime)
    for library in libraries:
        if library._handle not in modules:
            raise RuntimeError("Selected HEC-RAS HDF5 module handle was not found.")
    _verify_hdf5_metadata(libraries[0], H5)
    print(
        f"HDF.PInvoke identity verified: {modules[libraries[0]._handle]} "
        f"(module {libraries[0]._handle:#x}; shared object/reference state)",
        flush=True,
    )
    return handles, libraries


def main() -> None:
    """Compute native tables in the caller's disposable geometry HDF."""
    if importlib.util.find_spec("clr") is None:
        raise ImportError(
            "Native RASMapper requires pythonnet>=3.0.5. "
            "Install ras-commander[mesh] in this Windows Python environment."
        )
    install = Path(sys.argv[1]).absolute()
    geometry = Path(sys.argv[2]).absolute()
    handles, libraries = _initialize_runtime(install)
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
