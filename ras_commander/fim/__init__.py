"""Prepare computed HEC-RAS results and supervise the optional Rust mapper.

``RasFim`` provides typed capability discovery, 2D horizontal/sloping and
Step05 mapping, temporal/velocity products, catalogs and boundary comparisons.
The explicit qualification-gated 1D path stages stored cross-section surfaces
with ``prepare_one_d_model`` and maps them with ``map_one_d_profiles`` or the
prepared model's ``map_profiles`` method. The 2D entry points retain their
dimensional guards. Canonical mixed preparation and coverage-first composition
use ``prepare_coupled_model``/``map_coupled_profiles`` behind the same explicit
qualification gate.

Install ``ras-commander[fim]`` for the external ``ras2fim-batch`` engine.
Numerical qualification is independent of transport availability and API
stability. Ordinary mapping never installs an engine or falls back to HEC-RAS.
"""

from .errors import (
    FimAoiError,
    FimEngineError,
    FimEngineNotFoundError,
    FimError,
    FimGeometryError,
    FimMappingError,
    FimUnsupportedError,
)
from ._aoi import FimAoi
from ._prepare import FimPreparedProfile
from ._capabilities import FimCapabilities, FimMethodSupport
from ._scope import FimModelScope
from .RasFim import RasFim
from ._sloping_context import FimPreparedSlopingModel
from ._one_d import FimPreparedOneDModel
from ._coupled import FimPreparedCoupledModel

__all__ = [
    "RasFim",
    "FimAoi",
    "FimPreparedProfile",
    "FimPreparedSlopingModel",
    "FimPreparedOneDModel",
    "FimPreparedCoupledModel",
    "FimCapabilities",
    "FimMethodSupport",
    "FimModelScope",
    "FimError",
    "FimEngineNotFoundError",
    "FimEngineError",
    "FimGeometryError",
    "FimUnsupportedError",
    "FimAoiError",
    "FimMappingError",
]
