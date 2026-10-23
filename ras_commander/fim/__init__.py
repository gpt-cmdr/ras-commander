"""Optional ras2fim-2D flood inundation mapping (FIM) for HEC-RAS 2D results.

Main class:
    RasFim: static namespace for the ras2fim-2D Step 05 method run by the
        external ``ras2fim-batch`` engine.

        - find_engine(), get_engine_info(): explicit engine resolution
        - get_cells_from_results_gpkg(): ras2fim-2D catalog cell layer
        - get_cells_from_plan_hdf(): cell maximum WSE from a plan HDF
        - get_cell_centers(): computational cell centres through HdfMesh
        - resolve_aoi(): bounding box or polygon area of interest
        - prepare_profile(): global sample preparation for one profile
        - map_profiles(), map_ras2fim_results(): batch mapping with a
          product manifest

Requires ``pip install "ras-commander[fim]"`` and an engine executable.
This method differs from RAS Mapper stored maps.
"""

from .errors import (
    FimAoiError,
    FimEngineError,
    FimEngineNotFoundError,
    FimError,
    FimMappingError,
    FimUnsupportedError,
)
from ._aoi import FimAoi
from ._prepare import FimPreparedProfile
from .RasFim import RasFim

__all__ = [
    "RasFim",
    "FimAoi",
    "FimPreparedProfile",
    "FimError",
    "FimEngineNotFoundError",
    "FimEngineError",
    "FimUnsupportedError",
    "FimAoiError",
    "FimMappingError",
]
