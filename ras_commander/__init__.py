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
    __version__ = "0.85.0"

# Set up logging
setup_logging()

# Core functionality
from .RasPrj import RasPrj, init_ras_project, get_ras_exe, ras
from .RasPlan import RasPlan
from .RasGeo import RasGeo
from .RasGeometry import RasGeometry
from .RasGeometryUtils import RasGeometryUtils
from .RasStruct import RasStruct
from .RasUnsteady import RasUnsteady
from .RasUtils import RasUtils
from .RasExamples import RasExamples
from .M3Model import M3Model
from .RasCmdr import RasCmdr
from .RasControl import RasControl
from .RasMap import RasMap
from .RasGuiAutomation import RasGuiAutomation
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
from .HdfHydraulicTables import HdfHydraulicTables
from .HdfResultsBreach import HdfResultsBreach
from .RasBreach import RasBreach

# Plotting functionality
from .HdfPlot import HdfPlot
from .HdfResultsPlot import HdfResultsPlot

# Remote execution - lazy loaded to avoid importing until needed
# This reduces import time and allows optional dependencies to be truly optional
_REMOTE_EXPORTS = {
    'RasWorker', 'PsexecWorker', 'LocalWorker', 'SshWorker', 'WinrmWorker',
    'DockerWorker', 'SlurmWorker', 'AwsEc2Worker', 'AzureFrWorker',
    'init_ras_worker', 'load_workers_from_json', 'compute_parallel_remote',
    'ExecutionResult', 'get_worker_status'
}

# DSS operations - lazy loaded to avoid importing pyjnius/Java until needed
# This keeps the Java dependency truly optional for users who don't need DSS
_DSS_EXPORTS = {'RasDss'}

def __getattr__(name):
    """Lazy load remote execution and DSS components on first access."""
    if name in _REMOTE_EXPORTS:
        from . import remote
        return getattr(remote, name)
    if name in _DSS_EXPORTS:
        from . import dss
        return getattr(dss, name)
    raise AttributeError(f"module 'ras_commander' has no attribute '{name}'")


# Define __all__ to specify what should be imported when using "from ras_commander import *"
__all__ = [
    # Core functionality
    'RasPrj', 'init_ras_project', 'get_ras_exe', 'ras',
    'RasPlan', 'RasGeo', 'RasGeometry', 'RasGeometryUtils', 'RasStruct', 'RasUnsteady', 'RasUtils',
    'RasExamples', 'M3Model', 'RasCmdr', 'RasControl', 'RasMap', 'RasGuiAutomation', 'HdfFluvialPluvial',

    # Remote execution (lazy loaded)
    'RasWorker', 'PsexecWorker', 'LocalWorker', 'SshWorker', 'WinrmWorker',
    'DockerWorker', 'SlurmWorker', 'AwsEc2Worker', 'AzureFrWorker',
    'init_ras_worker', 'load_workers_from_json', 'compute_parallel_remote',
    'ExecutionResult', 'get_worker_status',

    # DSS operations (lazy loaded)
    'RasDss',

    # HDF handling
    'HdfBase', 'HdfBndry', 'HdfMesh', 'HdfPlan',
    'HdfResultsMesh', 'HdfResultsPlan', 'HdfResultsXsec',
    'HdfStruc', 'HdfUtils', 'HdfXsec', 'HdfPump',
    'HdfPipe', 'HdfInfiltration', 'HdfHydraulicTables', 'HdfResultsBreach', 'RasBreach',

    # Plotting functionality
    'HdfPlot', 'HdfResultsPlot',

    # Utilities
    'get_logger', 'log_call', 'standardize_input',
]
