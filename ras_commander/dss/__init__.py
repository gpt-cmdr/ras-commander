"""
ras-commander DSS subpackage: HEC-DSS file operations.

This subpackage provides DSS file reading capabilities using HEC Monolith
Java libraries via pyjnius. All dependencies are lazy-loaded to minimize
import time and keep optional dependencies truly optional.

Lazy Loading Behavior:
    - `import ras_commander` - DSS not loaded (fast startup)
    - `from ras_commander import RasDss` - DSS subpackage loaded
    - `RasDss.get_catalog(...)` - pyjnius/Java loaded on first call
    - HEC Monolith libraries downloaded automatically on first use (~20 MB)

Dependencies:
    Required at runtime (lazy loaded):
        - pyjnius: pip install pyjnius
        - Java JRE/JDK 8+: Must be installed and JAVA_HOME set

    Auto-downloaded:
        - HEC Monolith libraries (~20 MB, cached in ~/.ras-commander/dss/)

Usage:
    from ras_commander import RasDss

    # Get catalog of all paths in DSS file
    paths = RasDss.get_catalog("file.dss")

    # Read time series
    df = RasDss.read_timeseries("file.dss", paths[0])
    print(df.attrs['units'])  # Access metadata

    # Extract all DSS boundary conditions
    from ras_commander import init_ras_project
    ras = init_ras_project("project_path", "6.6")
    enhanced = RasDss.extract_boundary_timeseries(ras.boundaries_df, ras_object=ras)

See Also:
    - examples/22_dss_boundary_extraction.ipynb for complete workflow
    - CLAUDE.md for API documentation
"""

from .RasDss import RasDss

__all__ = ['RasDss']
