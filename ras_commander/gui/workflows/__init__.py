"""
GUI automation workflows for HEC-RAS.

Each workflow is a multi-step orchestrated sequence of GUI actions
built on the element finders (Layer 2) and Win32 primitives (Layer 1).
"""

from .open_compute import OpenAndComputeWorkflow
from .run_multiple_plans import RunMultiplePlansWorkflow
from .open_rasmapper import OpenRasMapperWorkflow
from .mesh_regeneration import MeshRegenerationWorkflow
from .xsec_update import (
    RasMapperBankLineWorkflow,
    RasMapperLayerCommandWorkflow,
    RasMapperXsecUpdateWorkflow,
)

__all__ = [
    'OpenAndComputeWorkflow',
    'RunMultiplePlansWorkflow',
    'OpenRasMapperWorkflow',
    'MeshRegenerationWorkflow',
    'RasMapperBankLineWorkflow',
    'RasMapperLayerCommandWorkflow',
    'RasMapperXsecUpdateWorkflow',
]
