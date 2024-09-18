from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("ras-commander")
except PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"

# Import all necessary functions and classes directly
from .RasPrj import ras, init_ras_project, get_ras_exe
from .RasPrj import RasPrj
from .RasPlan import RasPlan
from .RasGeo import RasGeo
from .RasUnsteady import RasUnsteady
from .RasCmdr import RasCmdr
from .RasUtils import RasUtils
from .RasExamples import RasExamples

# Import all attributes from these modules
from .RasPrj import *
from .RasPlan import *
from .RasGeo import *
from .RasUnsteady import *
from .RasCmdr import *
from .RasUtils import *
from .RasExamples import *

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
    "RasExamples"
]
