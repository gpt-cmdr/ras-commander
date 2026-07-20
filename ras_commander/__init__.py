"""
ras-commander: A Python library for automating HEC-RAS operations

An open-source project of CLB Engineering Corporation (https://clbengineering.com/)
Docs: https://rascommander.info/ras
GitHub: https://github.com/gpt-cmdr/ras-commander
"""

from importlib.metadata import version, PackageNotFoundError
from .LoggingConfig import setup_logging, get_logger
from .Decorators import log_call, standardize_input

try:
    __version__ = version("ras-commander")
except PackageNotFoundError:
    # package is not installed
    __version__ = "0.99.0"

# Canonical machine-readable agent index (see docs() helper below)
__llms_txt__ = "https://rascommander.info/ras/llms.txt"
__citation_url__ = "https://rascommander.info/ras/cite/"

# Set up logging
setup_logging()


def docs(topic=None):
    """Return (and print) the rascommander.info URL for an optional topic.

    No args -> docs home; topic='llms' -> llms.txt; topic='citation' -> the
    citation and sharing guide; topic='dataframes' -> the DataFrame Reference;
    any other topic -> user-guide/<topic>/.
    Designed for LLM agents to self-locate the documentation at runtime.
    """
    base = "https://rascommander.info/ras"
    if topic is None:
        url = f"{base}/"
    else:
        slug = str(topic).strip().strip("/")
        if slug == "llms":
            url = __llms_txt__
        elif slug in {"cite", "citation"}:
            url = __citation_url__
        elif slug == "dataframes":
            url = f"{base}/reference/dataframe-reference/"
        elif not slug:
            url = f"{base}/"
        else:
            url = f"{base}/user-guide/{slug}/"
    print(url)
    return url


def agent_guide_text():
    """Return the packaged LLM_GUIDE.md content (offline agent quickstart) as a string.

    Importer-safe: works for both directory and zip/non-filesystem installs.
    Prefer this over agent_guide_path() when you just need the guide text.
    """
    from importlib.resources import files
    return files("ras_commander").joinpath("LLM_GUIDE.md").read_text(encoding="utf-8")


def agent_guide_path():
    """Return a Traversable for the packaged LLM_GUIDE.md (offline agent quickstart).

    For normal (directory) pip and source installs this behaves like a filesystem
    path (``str(agent_guide_path())`` is a real path). Under zip/non-filesystem
    importers it is a ``Traversable`` that is not a real path -- read its content
    with ``agent_guide_text()``, or materialize a real path with
    ``importlib.resources.as_file()``.
    """
    from importlib.resources import files
    return files("ras_commander").joinpath("LLM_GUIDE.md")

# Core functionality
from .RasPrj import RasPrj, init_ras_project, get_ras_exe, ras, create_project_from_template
from .RasPlan import RasPlan
from .RasGeo import RasGeo  # DEPRECATED - use geom subpackage
from .RasGeometry import RasGeometry  # DEPRECATED - use geom subpackage
from .RasGeometryUtils import RasGeometryUtils  # DEPRECATED - use geom subpackage
from .RasUnsteady import RasUnsteady
from .RasSteady import RasSteady
from .RasUtils import RasUtils
from .RasExamples import RasExamples
from .sources.federal import RasEbfeModels
from .sources.county import M3Model
from .RasCmdr import RasCmdr
from .RasCurrency import RasCurrency
from .RasControl import RasControl
from .RasTcu import RasTcu, TcuStatus
from .ComputeResults import (
    ComputeResult,
    ComputeParallelResult,
    RasControlResult,
    PreprocessResult,
    GeometryPreprocessResult,
    GeometryLayerResult,
    GeometryCompleteResult,
)
from .RasPreprocess import RasPreprocess
from .RasMap import RasMap
from .RasDialogWatchdog import DialogWatchdog, DismissedDialog
from .RasEncroachments import RasEncroachments
from .RasMapValidation import RasMapValidation
from .RasBenefits import (
    BenefitAreaConfig,
    BenefitAreaResult,
    BenefitCategory,
    RasBenefits,
)
from .RasProcess import RasProcess, ProjectionInfo
from .RasGeometryCompute import RasGeometryCompute
from .RasGuiAutomation import RasGuiAutomation
from .RasScreenshot import RasScreenshot
from .RasBreach import RasBreach
from .RasFloodway import RasFloodway
from .RasHydroCompare import RasHydroCompare
from .RasModPuls import RasModPuls
from .RasPermutation import RasPermutation, RangeSpec
from .RasMonteCarlo import RasMonteCarlo
from .RasCalibrate import (
    CalibrationPoint,
    RasCalibrate,
    compute_objective,
    extract_modeled,
    extract_steady_profile_modeled,
    extract_steady_profile_observations,
    make_composite_apply_fn,
    make_infiltration_apply_fn,
    make_mannings_apply_fn,
    make_steady_profile_calibration_points,
    make_xsec_mannings_apply_fn,
)
from .RasFlowOptimization import RasFlowOptimization

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
    GeomParser, GeomPreprocessor, GeomLandCover, ManningsFromLandCover,
    GeomCrossSection, CrossSectionBankStations, CrossSectionBuildInput,
    CrossSectionBuildResult, CrossSectionManningsN, CrossSectionReachLengths,
    GeomStorage, GeomProjection, GeomLateral,
    GeomInlineWeir, GeomBridge, GeomCulvert, GeomCulvertGIS,
    GeomReferenceFeatures, GeomBcLines, GeomMesh,
    GeomPipeNetwork,
    MeshResult, BCConflict, BCFixResult,
)

# HDF handling - imported from hdf subpackage
from .hdf import (
    HdfBase, HdfUtils, HdfPlan,
    HdfMesh, HdfXsec, HdfBndry, HdfStruc, HdfStorageArea, HdfHydraulicTables,
    HdfResultsPlan, HdfResultsMesh, HdfResultsQuery, HdfResultsXsec, HdfResultsBreach,
    HdfResultsSediment,
    HdfPipe, HdfPump, HdfInfiltration, HdfLandCover,
    HdfPlot, HdfResultsPlot,
    HdfFluvialPluvial, HdfBenefitAreas, HdfChannelCapacity, HdfResultsAnalysis,
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
_TERRAIN_EXPORTS = {'RasTerrain', 'RasTerrainModification', 'RasTerrainModWriter'}

# Results module - Compute message parsing and execution summary
_RESULTS_EXPORTS = {'ResultsParser', 'ResultsSummary'}

# GUI automation - lazy loaded to avoid importing pywin32 on non-Windows platforms
_GUI_EXPORTS = {
    'Win32Primitives', 'HecRasElements', 'RasMapperElements',
    'VB6ClassNames', 'Win32Constants',
    'WorkflowStep', 'WorkflowResult', 'WorkflowExecutor',
    'OpenAndComputeWorkflow', 'RunMultiplePlansWorkflow',
    'OpenRasMapperWorkflow', 'MeshRegenerationWorkflow',
}

def __getattr__(name):
    """Lazy load remote execution, DSS, check, fixit, terrain, results, and gui components on first access."""
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
    if name in _GUI_EXPORTS:
        from . import gui
        return getattr(gui, name)
    raise AttributeError(f"module 'ras_commander' has no attribute '{name}'")


# Define __all__ to specify what should be imported when using "from ras_commander import *"
__all__ = [
    # Core functionality
    'RasPrj', 'init_ras_project', 'get_ras_exe', 'ras', 'create_project_from_template',
    'RasPlan', 'RasUnsteady', 'RasSteady', 'RasUtils',
    'ComputeResult', 'ComputeParallelResult', 'RasControlResult',
    'PreprocessResult', 'GeometryPreprocessResult',
    'GeometryLayerResult', 'GeometryCompleteResult',
    'RasGeometryCompute',
    'RasPreprocess',
    'RasExamples', 'RasEbfeModels', 'M3Model', 'RasCmdr', 'RasCurrency', 'RasControl', 'RasTcu', 'TcuStatus', 'RasMap', 'RasEncroachments', 'RasProcess', 'ProjectionInfo', 'RasGuiAutomation', 'RasScreenshot', 'HdfFluvialPluvial',
    'RasBenefits', 'BenefitAreaConfig', 'BenefitAreaResult', 'BenefitCategory',
    'RasFloodway', 'RasFlowOptimization', 'RasModPuls', 'RasPermutation', 'RangeSpec', 'RasMonteCarlo',
    'CalibrationPoint', 'RasCalibrate',
    'compute_objective', 'extract_modeled',
    'extract_steady_profile_modeled', 'extract_steady_profile_observations',
    'make_composite_apply_fn', 'make_infiltration_apply_fn',
    'make_mannings_apply_fn', 'make_steady_profile_calibration_points',
    'make_xsec_mannings_apply_fn',

    # Geometry handling (new in v0.86.0)
    'GeomParser', 'GeomPreprocessor', 'GeomLandCover', 'ManningsFromLandCover',
    'GeomCrossSection', 'CrossSectionBankStations', 'CrossSectionBuildInput',
    'CrossSectionBuildResult', 'CrossSectionManningsN', 'CrossSectionReachLengths',
    'GeomStorage', 'GeomProjection', 'GeomLateral',
    'GeomInlineWeir', 'GeomBridge', 'GeomCulvert', 'GeomCulvertGIS',
    'GeomReferenceFeatures', 'GeomBcLines', 'GeomMesh',
    'GeomPipeNetwork',
    'MeshResult', 'BCConflict', 'BCFixResult',

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

    # Terrain module - HEC-RAS terrain creation and modification (lazy loaded)
    'RasTerrain', 'RasTerrainModification', 'RasTerrainModWriter',

    # Results module - Compute message parsing and execution summary (lazy loaded)
    'ResultsParser', 'ResultsSummary',

    # GUI automation (lazy loaded, Windows only)
    'Win32Primitives', 'HecRasElements', 'RasMapperElements',
    'VB6ClassNames', 'Win32Constants',
    'WorkflowStep', 'WorkflowResult', 'WorkflowExecutor',
    'OpenAndComputeWorkflow', 'RunMultiplePlansWorkflow',
    'OpenRasMapperWorkflow', 'MeshRegenerationWorkflow',

    # HDF handling
    'HdfBase', 'HdfBndry', 'HdfMesh', 'HdfPlan', 'HdfProject',
    'HdfResultsMesh', 'HdfResultsPlan', 'HdfResultsQuery', 'HdfResultsXsec', 'HdfResultsSediment',
    'HdfStruc', 'HdfStorageArea', 'HdfUtils', 'HdfXsec', 'HdfPump',
    'HdfPipe', 'HdfInfiltration', 'HdfLandCover', 'HdfHydraulicTables', 'HdfResultsBreach', 'RasBreach',
    'HdfBenefitAreas', 'HdfChannelCapacity', 'HdfResultsAnalysis',

    # Plotting functionality
    'HdfPlot', 'HdfResultsPlot',

    # Dialog watchdog (headless execution)
    'DialogWatchdog', 'DismissedDialog',

    # Utilities
    'get_logger', 'log_call', 'standardize_input',

    # Documentation / LLM agent helpers
    'docs', 'agent_guide_path', 'agent_guide_text',

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

# ======================================================================# BACKWARD COMPATIBILITY - DEPRECATED MODULE PATHS (DEPRECATED in v0.89.0)
# ======================================================================# These aliases provide backward compatibility for old import paths.
# Users should migrate to new paths. Old paths will show DeprecationWarning.
#
# Migration:
#   OLD: from ras_commander.BcoMonitor import BcoMonitor
#   NEW: from ras_commander.RasBco import BcoMonitor
#
#   OLD: from ras_commander.validation_base import ValidationSeverity, ...
#   NEW: from ras_commander.RasValidation import ValidationSeverity, ...
# ======================================================================
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


# Register deprecated module paths for M3Model, ebfe_models
sys.modules['ras_commander.M3Model'] = _DeprecatedM3Model()
sys.modules['ras_commander.ebfe_models'] = _DeprecatedEbfeModels()
