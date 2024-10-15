from importlib.metadata import version, PackageNotFoundError
from .LoggingConfig import setup_logging, get_logger
from .Decorators import log_call, standardize_input

try:
    __version__ = version("ras-commander")
except PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"

# Set up logging
setup_logging()

# Import all necessary functions and classes directly
from .RasPrj import RasPrj, init_ras_project, get_ras_exe, ras
from .RasPlan import RasPlan
from .RasGeo import RasGeo
from .RasUnsteady import RasUnsteady
from .RasUtils import RasUtils
from .RasExamples import RasExamples
from .RasCmdr import RasCmdr
from .RasGpt import RasGpt

# Import the Hdf* classes
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

# Define __all__ to specify what should be imported when using "from ras_commander import *"
__all__ = [
    "HdfBase",
    "HdfBndry",
    "HdfMesh",
    "HdfPlan",
    "HdfResultsMesh",
    "HdfResultsPlan",
    "HdfResultsXsec",
    "HdfStruc",
    "HdfUtils",
    "HdfXsec",
    "standardize_input",
    "ras",
    "init_ras_project",
    "get_ras_exe",
    "RasPrj",
    "RasPlan",
    "RasGeo",
    "RasUnsteady",
    "RasCmdr",
    "RasUtils",
    "RasExamples",
    "get_logger",
    "log_call",
]

__version__ = "0.1.0"
