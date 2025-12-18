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
    __version__ = "0.87.6"

# Set up logging
setup_logging()

# Core functionality
from .RasPrj import RasPrj, init_ras_project, get_ras_exe, ras
from .RasPlan import RasPlan
from .RasGeo import RasGeo  # DEPRECATED - use geom subpackage
from .RasGeometry import RasGeometry  # DEPRECATED - use geom subpackage
from .RasGeometryUtils import RasGeometryUtils  # DEPRECATED - use geom subpackage
from .RasUnsteady import RasUnsteady
from .RasUtils import RasUtils
from .RasExamples import RasExamples
from .M3Model import M3Model
from .RasCmdr import RasCmdr
from .RasControl import RasControl
from .rasmap import RasMap
from .RasProcess import RasProcess
from .RasGuiAutomation import RasGuiAutomation
from .RasBreach import RasBreach

# Geometry handling - imported from geom subpackage
from .geom import (
    GeomParser, GeomPreprocessor, GeomLandCover,
    GeomCrossSection, GeomStorage, GeomLateral,
    GeomInlineWeir, GeomBridge, GeomCulvert,
)

# HDF handling - imported from hdf subpackage
from .hdf import (
    HdfBase, HdfUtils, HdfPlan,
    HdfMesh, HdfXsec, HdfBndry, HdfStruc, HdfHydraulicTables,
    HdfResultsPlan, HdfResultsMesh, HdfResultsXsec, HdfResultsBreach,
    HdfPipe, HdfPump, HdfInfiltration,
    HdfPlot, HdfResultsPlot,
    HdfFluvialPluvial,
    HdfProject,
)

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

# Check module - QA validation for HEC-RAS steady flow models (unofficial cHECk-RAS clone)
_CHECK_EXPORTS = {
    'RasCheck', 'CheckResults', 'CheckMessage', 'Severity',
    'ValidationThresholds', 'get_default_thresholds', 'get_state_surcharge_limit',
    'RasCheckReport', 'ReportMetadata', 'generate_html_report', 'export_messages_csv',
}

# Fixit module - Automated geometry repair for HEC-RAS models
_FIXIT_EXPORTS = {
    'RasFixit', 'FixResults', 'FixMessage', 'FixAction', 'BlockedObstruction',
}

def __getattr__(name):
    """Lazy load remote execution, DSS, check, and fixit components on first access."""
    if name in _REMOTE_EXPORTS:
        from . import remote
        return getattr(remote, name)
    if name in _DSS_EXPORTS:
        from . import dss
        return getattr(dss, name)
    if name in _CHECK_EXPORTS:
        from . import check
        return getattr(check, name)
    if name in _FIXIT_EXPORTS:
        from . import fixit
        return getattr(fixit, name)
    raise AttributeError(f"module 'ras_commander' has no attribute '{name}'")


# Define __all__ to specify what should be imported when using "from ras_commander import *"
__all__ = [
    # Core functionality
    'RasPrj', 'init_ras_project', 'get_ras_exe', 'ras',
    'RasPlan', 'RasUnsteady', 'RasUtils',
    'RasExamples', 'M3Model', 'RasCmdr', 'RasControl', 'RasMap', 'RasProcess', 'RasGuiAutomation', 'HdfFluvialPluvial',

    # Geometry handling (new in v0.86.0)
    'GeomParser', 'GeomPreprocessor', 'GeomLandCover',
    'GeomCrossSection', 'GeomStorage', 'GeomLateral',
    'GeomInlineWeir', 'GeomBridge', 'GeomCulvert',

    # Deprecated geometry classes (will be removed before v1.0)
    'RasGeo', 'RasGeometry', 'RasGeometryUtils',

    # Remote execution (lazy loaded)
    'RasWorker', 'PsexecWorker', 'LocalWorker', 'SshWorker', 'WinrmWorker',
    'DockerWorker', 'SlurmWorker', 'AwsEc2Worker', 'AzureFrWorker',
    'init_ras_worker', 'load_workers_from_json', 'compute_parallel_remote',
    'ExecutionResult', 'get_worker_status',

    # DSS operations (lazy loaded)
    'RasDss',

    # Check module - QA validation (lazy loaded) - unofficial cHECk-RAS clone
    'RasCheck', 'CheckResults', 'CheckMessage', 'Severity',
    'ValidationThresholds', 'get_default_thresholds', 'get_state_surcharge_limit',
    'RasCheckReport', 'ReportMetadata', 'generate_html_report', 'export_messages_csv',

    # Fixit module - Automated geometry repair (lazy loaded)
    'RasFixit', 'FixResults', 'FixMessage', 'FixAction', 'BlockedObstruction',

    # HDF handling
    'HdfBase', 'HdfBndry', 'HdfMesh', 'HdfPlan', 'HdfProject',
    'HdfResultsMesh', 'HdfResultsPlan', 'HdfResultsXsec',
    'HdfStruc', 'HdfUtils', 'HdfXsec', 'HdfPump',
    'HdfPipe', 'HdfInfiltration', 'HdfHydraulicTables', 'HdfResultsBreach', 'RasBreach',

    # Plotting functionality
    'HdfPlot', 'HdfResultsPlot',

    # Utilities
    'get_logger', 'log_call', 'standardize_input',
]
