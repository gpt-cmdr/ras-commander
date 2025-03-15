"""
RasToGo module provides functions to interface HEC-RAS with go-consequences.
This module helps prepare and format RAS data for use with go-consequences.


-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasToGo:

TO BE IMPLEMENTED: 
- Adding stored maps in rasmaapper for a results file
- Editing the terrain name for stored maps, so that a reduced resolution terrain can be used for mapping
- Re-computing specific plans using the floodplain mapping option to generate stored maps
- Using the stored map output to call go-consequences and compute damages
- Comparisons of go-consequences outputs based on RAS plan number
    - include optional argument with polygons defining areas of interest

"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union
import pandas as pd
import numpy as np

from .Decorators import log_call, standardize_input
from .LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)

class RasToGo:
    """Class containing functions to interface HEC-RAS with go-consequences."""

    #@staticmethod
    #@log_call 