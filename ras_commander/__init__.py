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
    __version__ = "0.88.6"

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
from .sources.federal import RasEbfeModels, RasEbfeExamples
from .sources.county import M3Model
from .RasCmdr import RasCmdr
from .RasCurrency import RasCurrency
from .RasControl import RasControl
from .RasMap import RasMap
from .RasProcess import RasProcess, ProjectionInfo
from .RasGuiAutomation import RasGuiAutomation
from .RasScreenshot import RasScreenshot
from .RasBreach import RasBreach

# Validation framework - core validation infrastructure
from .RasValidation import ValidationSeverity, ValidationResult, ValidationReport

# Real-time execution monitoring callbacks
from .ExecutionCallback import ExecutionCallback
from .callbacks import (
    ConsoleCallback,
    FileLoggerCallback,
    ProgressBarCallback,
    SynchronizedCallback,
)
from .RasBco import BcoMonitor

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
    HdfFluvialPluvial, HdfBenefitAreas,
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

# Terrain module - HEC-RAS terrain creation and manipulation
_TERRAIN_EXPORTS = {'RasTerrain'}

# Results module - Compute message parsing and execution summary
_RESULTS_EXPORTS = {'ResultsParser', 'ResultsSummary'}

def __getattr__(name):
    """Lazy load remote execution, DSS, check, fixit, terrain, and results components on first access."""
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
    if name in _TERRAIN_EXPORTS:
        from . import terrain
        return getattr(terrain, name)
    if name in _RESULTS_EXPORTS:
        from . import results
        return getattr(results, name)
    raise AttributeError(f"module 'ras_commander' has no attribute '{name}'")


# Define __all__ to specify what should be imported when using "from ras_commander import *"
__all__ = [
    # Core functionality
    'RasPrj', 'init_ras_project', 'get_ras_exe', 'ras',
    'RasPlan', 'RasUnsteady', 'RasUtils',
    'RasExamples', 'RasEbfeModels', 'RasEbfeExamples', 'M3Model', 'RasCmdr', 'RasControl', 'RasMap', 'RasProcess', 'ProjectionInfo', 'RasGuiAutomation', 'RasScreenshot', 'HdfFluvialPluvial',

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

    # Terrain module - HEC-RAS terrain creation (lazy loaded)
    'RasTerrain',

    # Results module - Compute message parsing and execution summary (lazy loaded)
    'ResultsParser', 'ResultsSummary',

    # HDF handling
    'HdfBase', 'HdfBndry', 'HdfMesh', 'HdfPlan', 'HdfProject',
    'HdfResultsMesh', 'HdfResultsPlan', 'HdfResultsXsec',
    'HdfStruc', 'HdfUtils', 'HdfXsec', 'HdfPump',
    'HdfPipe', 'HdfInfiltration', 'HdfHydraulicTables', 'HdfResultsBreach', 'RasBreach',

    # Plotting functionality
    'HdfPlot', 'HdfResultsPlot',

    # Utilities
    'get_logger', 'log_call', 'standardize_input',

    # Validation framework
    'ValidationSeverity', 'ValidationResult', 'ValidationReport',

    # Real-time execution monitoring callbacks
    'ExecutionCallback',
    'ConsoleCallback',
    'FileLoggerCallback',
    'ProgressBarCallback',
    'SynchronizedCallback',
    'BcoMonitor',
]

# =============================================================================
# BACKWARD COMPATIBILITY - DEPRECATED MODULE PATHS (DEPRECATED in v0.89.0)
# =============================================================================
# These aliases provide backward compatibility for old import paths.
# Users should migrate to new paths. Old paths will show DeprecationWarning.
#
# Migration:
#   OLD: from ras_commander.BcoMonitor import BcoMonitor
#   NEW: from ras_commander.RasBco import BcoMonitor
#
#   OLD: from ras_commander.validation_base import ValidationSeverity, ...
#   NEW: from ras_commander.RasValidation import ValidationSeverity, ...
# =============================================================================

import sys
import warnings


class _DeprecatedBcoMonitor:
    """Backward compatibility shim for old BcoMonitor import path."""

    def __getattr__(self, name):
        warnings.warn(
            "Importing from ras_commander.BcoMonitor is deprecated. "
            "Use: from ras_commander.RasBco import BcoMonitor",
            DeprecationWarning,
            stacklevel=2
        )
        from .RasBco import BcoMonitor as _BcoMonitor
        if name == 'BcoMonitor':
            return _BcoMonitor
        return getattr(_BcoMonitor, name)


class _DeprecatedValidationBase:
    """Backward compatibility shim for old validation_base import path."""

    def __getattr__(self, name):
        warnings.warn(
            "Importing from ras_commander.validation_base is deprecated. "
            "Use: from ras_commander.RasValidation import ValidationSeverity, ValidationResult, ValidationReport",
            DeprecationWarning,
            stacklevel=2
        )
        from .RasValidation import ValidationSeverity, ValidationResult, ValidationReport
        mapping = {
            'ValidationSeverity': ValidationSeverity,
            'ValidationResult': ValidationResult,
            'ValidationReport': ValidationReport,
        }
        if name in mapping:
            return mapping[name]
        raise AttributeError(f"module 'ras_commander.validation_base' has no attribute '{name}'")


# Register the deprecated module shims in sys.modules for old import paths
sys.modules['ras_commander.BcoMonitor'] = _DeprecatedBcoMonitor()
sys.modules['ras_commander.validation_base'] = _DeprecatedValidationBase()


class _DeprecatedM3Model:
    """Backward compatibility shim for old M3Model import path."""

    def __getattr__(self, name):
        warnings.warn(
            "Importing from ras_commander.M3Model is deprecated. "
            "Use: from ras_commander.sources.county import M3Model",
            DeprecationWarning,
            stacklevel=2
        )
        from .sources.county import M3Model
        if name == 'M3Model':
            return M3Model
        return getattr(M3Model, name)


class _DeprecatedEbfeModels:
    """Backward compatibility shim for old ebfe_models import path."""

    def __getattr__(self, name):
        warnings.warn(
            "Importing from ras_commander.ebfe_models is deprecated. "
            "Use: from ras_commander.sources.federal import RasEbfeModels",
            DeprecationWarning,
            stacklevel=2
        )
        from .sources.federal import RasEbfeModels
        if name == 'RasEbfeModels':
            return RasEbfeModels
        return getattr(RasEbfeModels, name)


class _DeprecatedEbfeExamples:
    """Backward compatibility shim for old ebfe_examples import path."""

    def __getattr__(self, name):
        warnings.warn(
            "Importing from ras_commander.ebfe_examples is deprecated. "
            "Use: from ras_commander.sources.federal import RasEbfeExamples",
            DeprecationWarning,
            stacklevel=2
        )
        from .sources.federal import RasEbfeExamples
        if name == 'RasEbfeExamples':
            return RasEbfeExamples
        return getattr(RasEbfeExamples, name)


# Register deprecated module paths for M3Model, ebfe_models, ebfe_examples
sys.modules['ras_commander.M3Model'] = _DeprecatedM3Model()
sys.modules['ras_commander.ebfe_models'] = _DeprecatedEbfeModels()
sys.modules['ras_commander.ebfe_examples'] = _DeprecatedEbfeExamples()
