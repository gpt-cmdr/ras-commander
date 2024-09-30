from importlib.metadata import version, PackageNotFoundError
from .logging_config import setup_logging, get_logger, log_call

try:
    __version__ = version("ras-commander")
except PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"

# Set up logging
setup_logging()

# Import all necessary functions and classes directly
from .RasPrj import ras, init_ras_project, get_ras_exe
from .RasPrj import RasPrj
from .RasPlan import RasPlan
from .RasGeo import RasGeo
from .RasUnsteady import RasUnsteady
from .RasCmdr import RasCmdr
from .RasUtils import RasUtils
from .RasExamples import RasExamples
from .RasHdf import RasHdf
from .RasGpt import RasGpt

# Define __all__ to specify what should be imported when using "from ras_commander import *"
__all__ = [
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
    "RasHdf",
    "RasGpt",
    "get_logger",
    "log_call"
]