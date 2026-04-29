"""
GUI Automation Subpackage - Win32-based HEC-RAS GUI automation.

This subpackage provides layered automation of HEC-RAS and RASMapper
GUI operations for workflows that have no programmatic API.

Layers:
    Layer 1 (Win32Primitives): Generic window operations
    Layer 2 (HecRasElements, RasMapperElements): App-specific finders
    Layer 3 (Workflows): Multi-step orchestrated sequences

Workflows:
    MeshRegenerationWorkflow: Regenerate 2D mesh via RASMapper
    OpenAndComputeWorkflow: Open project, set plan, compute
    RunMultiplePlansWorkflow: Batch plan execution
    OpenRasMapperWorkflow: Open RASMapper for viewing

Requirements:
    - Windows only (uses pywin32)
    - HEC-RAS 6.6 installed
    - pywin32: pip install pywin32

Example:
    >>> from ras_commander.gui import MeshRegenerationWorkflow
    >>> result = MeshRegenerationWorkflow.regenerate_mesh(timeout=600)
    >>> print(f"Success: {result.success}")
"""

from .constants import VB6ClassNames, Win32Constants
from .win32_primitives import Win32Primitives
from .hecras_elements import HecRasElements
from .rasmapper_elements import RasMapperElements
from .workflow_base import WorkflowStep, WorkflowResult, WorkflowExecutor
from .screenshots import RasScreenshot
from .workflows import (
    OpenAndComputeWorkflow,
    RunMultiplePlansWorkflow,
    OpenRasMapperWorkflow,
    MeshRegenerationWorkflow,
    RasMapperLayerCommandWorkflow,
    RasMapperXsecUpdateWorkflow,
)

__all__ = [
    # Constants
    'VB6ClassNames',
    'Win32Constants',
    # Layer 1 - Win32 primitives
    'Win32Primitives',
    # Layer 2 - Element finders
    'HecRasElements',
    'RasMapperElements',
    # Layer 3 - Workflow infrastructure
    'WorkflowStep',
    'WorkflowResult',
    'WorkflowExecutor',
    # Layer 3 - Concrete workflows
    'OpenAndComputeWorkflow',
    'RunMultiplePlansWorkflow',
    'OpenRasMapperWorkflow',
    'MeshRegenerationWorkflow',
    'RasMapperLayerCommandWorkflow',
    'RasMapperXsecUpdateWorkflow',
    # Screenshots
    'RasScreenshot',
]
