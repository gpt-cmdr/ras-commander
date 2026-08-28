"""Lean public surface for command-line HEC-RAS plan execution.

This module is intended for batch runners that need project inventory,
``RasCmdr.compute_plan()``, compute-message parsing, and direct HDF result
extraction. It deliberately does not export ``RasControl`` or any COM-based
result API.

The execution semantics are the normal ras-commander semantics: project and
result DataFrames are refreshed after a compute, the caller retains the normal
``verify`` control, and ``RasCmdr`` owns construction of the HEC-RAS command
line.
"""

from .ComputeResults import ComputeParallelResult, ComputeResult
from .RasCmdr import RasCmdr
from .RasPlan import RasPlan
from .RasPrj import (
    RasPrj,
    create_project_from_template,
    get_ras_exe,
    init_ras_project,
    ras,
)
from .hdf import HdfResultsPlan
from .results import ResultsParser, ResultsSummary


__all__ = [
    'RasPrj',
    'init_ras_project',
    'get_ras_exe',
    'ras',
    'create_project_from_template',
    'RasPlan',
    'RasCmdr',
    'ComputeResult',
    'ComputeParallelResult',
    'ResultsParser',
    'ResultsSummary',
    'HdfResultsPlan',
]
