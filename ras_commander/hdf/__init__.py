"""
ras-commander HDF subpackage: HEC-RAS HDF file operations.

This subpackage provides comprehensive HDF5 file operations for HEC-RAS
plan files (.p##.hdf) and geometry files (.g##.hdf).

Classes are organized by function:

Core:
    - HdfBase: Foundation class for HDF operations
    - HdfUtils: Utility functions (time parsing, data conversion)
    - HdfPlan: Plan file information extraction

Geometry:
    - HdfMesh: 2D mesh operations (cells, faces, areas)
    - HdfXsec: Cross-section geometry extraction
    - HdfBndry: Boundary features (BC lines, breaklines, reference features)
    - HdfStorageArea: Storage-area polygons, properties, terrain volume curves
    - HdfStruc: Structure geometry (2D structures)
    - HdfHydraulicTables: Hydraulic property tables (HTAB)

Results:
    - HdfResultsPlan: Plan results (steady/unsteady flow)
    - HdfResultsMesh: Mesh results (water surface, velocity, timeseries)
    - HdfResultsXsec: Cross-section results
    - HdfResultsBreach: Dam breach results

Infrastructure:
    - HdfPipe: Pipe network geometry and results
    - HdfPump: Pump station geometry and results
    - HdfInfiltration: Infiltration parameters and preprocessed per-cell values
    - HdfLandCover: Final Manning's N (base + calibration overrides, raster composition)

Visualization:
    - HdfPlot: General HDF plotting
    - HdfResultsPlot: Results visualization

Analysis:
    - HdfFluvialPluvial: Fluvial-pluvial boundary analysis
    - HdfBenefitAreas: Benefit/rise area analysis (2D plan comparison)
    - HdfChannelCapacity: 1D channel capacity analysis (multi-AEP storm comparison)
    - HdfResultsAnalysis: Critical duration and cross-plan comparison

Lazy Loading:
    Heavy dependencies (geopandas, xarray, shapely, matplotlib, scipy) are
    lazy-loaded inside methods that need them to reduce import overhead.

Usage:
    from ras_commander import HdfResultsPlan, HdfMesh

    # Check if plan has steady results
    if HdfResultsPlan.is_steady_plan("plan.hdf"):
        wse = HdfResultsPlan.get_steady_wse("plan.hdf")

    # Get mesh cell polygons
    cells = HdfMesh.get_mesh_cell_polygons("plan.hdf")
"""

from importlib import import_module
import sys
from types import ModuleType


_LAZY_EXPORTS = {
    name: (f".{name}", name)
    for name in (
        'HdfBase', 'HdfUtils', 'HdfPlan',
        'HdfMesh', 'HdfXsec', 'HdfBndry', 'HdfStruc', 'HdfStorageArea',
        'HdfStruc1D', 'HdfHydraulicTables',
        'HdfResultsPlan', 'HdfResultsMesh', 'HdfResultsQuery',
        'HdfResultsXsec', 'HdfResultsBreach', 'HdfResultsSediment',
        'HdfResultsProducts',
        'HdfPipe', 'HdfPump', 'HdfInfiltration', 'HdfLandCover',
        'HdfPlot', 'HdfResultsPlot',
        'HdfFluvialPluvial', 'HdfBenefitAreas', 'HdfChannelCapacity',
        'HdfResultsAnalysis', 'HdfProject',
    )
}


def _load_export(name):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'ras_commander.hdf' has no attribute '{name}'")
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __getattr__(name):
    """Import an HDF feature only when its public class is requested."""
    return _load_export(name)


class _LazyHdfModule(ModuleType):
    """Keep class exports stable when Python also imports same-named modules.

    Import machinery assigns ``package.HdfMesh`` to the submodule object when
    code imports ``ras_commander.hdf.HdfMesh`` directly. Historically the HDF
    package overwrote that name with the class during eager initialization.
    This accessor preserves that public behavior without eagerly loading the
    entire optional HDF stack.
    """

    def __getattribute__(self, name):
        namespace = ModuleType.__getattribute__(self, "__dict__")
        exports = namespace.get("_LAZY_EXPORTS", {})
        current = namespace.get(name)
        if name in exports and (current is None or isinstance(current, ModuleType)):
            return namespace["_load_export"](name)
        return ModuleType.__getattribute__(self, name)


sys.modules[__name__].__class__ = _LazyHdfModule

__all__ = [
    # Core
    'HdfBase', 'HdfUtils', 'HdfPlan',
    # Geometry
    'HdfMesh', 'HdfXsec', 'HdfBndry', 'HdfStruc', 'HdfStorageArea', 'HdfStruc1D', 'HdfHydraulicTables',
    # Results
    'HdfResultsPlan', 'HdfResultsMesh', 'HdfResultsQuery', 'HdfResultsXsec', 'HdfResultsBreach',
    'HdfResultsSediment', 'HdfResultsProducts',
    # Infrastructure
    'HdfPipe', 'HdfPump', 'HdfInfiltration', 'HdfLandCover',
    # Visualization
    'HdfPlot', 'HdfResultsPlot',
    # Analysis
    'HdfFluvialPluvial', 'HdfBenefitAreas', 'HdfChannelCapacity', 'HdfResultsAnalysis',
    # Project-level
    'HdfProject',
]
