"""
ras-commander: A Python library for automating HEC-RAS operations
"""

from importlib.metadata import version, PackageNotFoundError
from .LoggingConfig import setup_logging, get_logger
from .Decorators import log_call, standardize_input

try:
    __version__ = version("ras-commander")
except PackageNotFoundError:
    # package is not installed
    __version__ = "0.54.0"

# Set up logging
setup_logging()

# Core functionality
from .RasPrj import RasPrj, init_ras_project, get_ras_exe, ras
from .RasPlan import RasPlan
from .RasGeo import RasGeo
from .RasUnsteady import RasUnsteady
from .RasUtils import RasUtils
from .RasExamples import RasExamples
from .RasCmdr import RasCmdr
from .RasGpt import RasGpt
from .RasToGo import RasToGo
from .HdfFluvialPluvial import HdfFluvialPluvial

# HDF handling
from .HdfBase import HdfBase
from .HdfBndry import HdfBndry
from .HdfMesh import HdfMesh
from .HdfPlan import HdfPlan
from .HdfResultsMesh import HdfResultsMesh
from .HdfResultsPlan import HdfResultsPlan
from .HdfResultsXsec import HdfResultsXsec
from .HdfStruc import HdfStruc
from .HdfUtils import HdfUtils
from .HdfXsec import HdfXsec
from .HdfPump import HdfPump
from .HdfPipe import HdfPipe
from .HdfInfiltration import HdfInfiltration
from .RasMapper import RasMapper

# Plotting functionality
from .HdfPlot import HdfPlot
from .HdfResultsPlot import HdfResultsPlot

# Define __all__ to specify what should be imported when using "from ras_commander import *"
__all__ = [
    # Core functionality
    'RasPrj', 'init_ras_project', 'get_ras_exe', 'ras',
    'RasPlan', 'RasGeo', 'RasUnsteady', 'RasUtils',
    'RasExamples', 'RasCmdr', 'RasGpt', 'RasToGo',
    'HdfFluvialPluvial',
    
    # HDF handling
    'HdfBase', 'HdfBndry', 'HdfMesh', 'HdfPlan',
    'HdfResultsMesh', 'HdfResultsPlan', 'HdfResultsXsec',
    'HdfStruc', 'HdfUtils', 'HdfXsec', 'HdfPump',
    'HdfPipe', 'HdfInfiltration', 'RasMapper',
    
    # Plotting functionality
    'HdfPlot', 'HdfResultsPlot',
    
    # Utilities
    'get_logger', 'log_call', 'standardize_input',
]
