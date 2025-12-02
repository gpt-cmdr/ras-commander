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
    - HdfInfiltration: Infiltration parameters

Visualization:
    - HdfPlot: General HDF plotting
    - HdfResultsPlot: Results visualization

Analysis:
    - HdfFluvialPluvial: Fluvial-pluvial boundary analysis

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

# Core classes
from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from .HdfPlan import HdfPlan

# Geometry classes
from .HdfMesh import HdfMesh
from .HdfXsec import HdfXsec
from .HdfBndry import HdfBndry
from .HdfStruc import HdfStruc
from .HdfHydraulicTables import HdfHydraulicTables

# Results classes
from .HdfResultsPlan import HdfResultsPlan
from .HdfResultsMesh import HdfResultsMesh
from .HdfResultsXsec import HdfResultsXsec
from .HdfResultsBreach import HdfResultsBreach

# Infrastructure classes
from .HdfPipe import HdfPipe
from .HdfPump import HdfPump
from .HdfInfiltration import HdfInfiltration

# Visualization classes
from .HdfPlot import HdfPlot
from .HdfResultsPlot import HdfResultsPlot

# Analysis classes
from .HdfFluvialPluvial import HdfFluvialPluvial

__all__ = [
    # Core
    'HdfBase', 'HdfUtils', 'HdfPlan',
    # Geometry
    'HdfMesh', 'HdfXsec', 'HdfBndry', 'HdfStruc', 'HdfHydraulicTables',
    # Results
    'HdfResultsPlan', 'HdfResultsMesh', 'HdfResultsXsec', 'HdfResultsBreach',
    # Infrastructure
    'HdfPipe', 'HdfPump', 'HdfInfiltration',
    # Visualization
    'HdfPlot', 'HdfResultsPlot',
    # Analysis
    'HdfFluvialPluvial',
]
