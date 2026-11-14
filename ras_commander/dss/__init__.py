"""
ras-commander DSS subpackage: HEC-DSS file operations.

This subpackage reads and writes DSS6 and DSS7 files through the native
ras-commander-fast-dss engine or, where it is not available, HEC Monolith Java
libraries via pyjnius. All dependencies are lazy-loaded to minimize import time.

Lazy Loading Behavior:
    - `import ras_commander` - DSS not loaded (fast startup)
    - `from ras_commander import RasDss` - DSS subpackage loaded
    - `RasDss.get_catalog(...)` - the selected backend loads on first call
      (Java route: pyjnius, the JVM and a one-time ~20 MB HEC Monolith download)

Backends:
    RasDss.backend = "auto" (default) | "java" | "native" | "shadow"; the
    environment variable RAS_COMMANDER_DSS_BACKEND overrides it. "auto" uses
    "native" when ras-commander-fast-dss is installed and advertises the features
    the default needs, otherwise "java", and logs the choice once at INFO. Set
    "java" to keep the Java backend. See docs/user-guide/dss-native-backend.md.

Dependencies:
    Native backend:
        - ras-commander-fast-dss: a default dependency on CPython for Windows x64,
          Linux x86_64/aarch64 and macOS (where wheels are published)

    Java backend (lazy loaded):
        - pyjnius: pip install pyjnius (or the dss extra)
        - Java JRE/JDK 8+: Must be installed and JAVA_HOME set
        - HEC Monolith libraries (~20 MB, auto-downloaded to ~/.ras-commander/dss/)

Usage:
    from ras_commander import RasDss

    # Get catalog of all paths in DSS file
    paths = RasDss.get_catalog("file.dss")

    # Read time series
    df = RasDss.read_timeseries("file.dss", paths[0])
    print(df.attrs['units'])  # Access metadata

    # Write SHG gridded precipitation records
    written_paths = RasDss.write_grid_timeseries(
        "precip.dss",
        "/SHG/WATERSHED/PRECIP/01JAN2020:0000/01JAN2020:0100/SYNTHETIC/",
        data,
        times,
        {"cellsize": 2000, "origin": (1096000, 1516000), "crs": "SHG"}
    )

    # Extract all DSS boundary conditions
    from ras_commander import init_ras_project
    ras = init_ras_project("project_path", "7.0")
    enhanced = RasDss.extract_boundary_timeseries(ras.boundaries_df, ras_object=ras)

Gridded import and grid tools (ras-commander-fast-dss on every backend):
    from ras_commander import RasDssGrid

    result = RasDssGrid.import_gridded(grib_files, "storm.dss", product="mrms_qpe")
    RasDssGrid.grid_to_point("storm.dss", "basins.geojson", "NAME", "basin_average.dss")

See Also:
    - examples/310_dss_boundary_extraction.ipynb for complete workflow
    - ras_commander/dss/AGENTS.md for package-local development guidance
"""

from .RasDss import RasDss
from .RasDssGrid import RasDssGrid
from . import _errors

__all__ = ['RasDss', 'RasDssGrid', *_errors.ERROR_NAMES]


def __getattr__(name):
    """Typed DSS exceptions (``DssPathnameNotFoundError`` and others).

    Resolved on first access: they are the ras-commander-fast-dss classes when that optional
    package is installed, otherwise local classes with the same names and bases.
    """
    if name in _errors.ERROR_NAMES:
        return _errors.get(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
