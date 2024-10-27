"""
RasToGo module provides functions to interface HEC-RAS with go-consequences.
This module helps prepare and format RAS data for use with go-consequences.
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