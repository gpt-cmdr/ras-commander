"""
Geometry Subpackage - HEC-RAS geometry file operations

This subpackage provides comprehensive functionality for reading and modifying
HEC-RAS plain text geometry files (.g##). It handles 1D cross sections, 2D flow
areas, storage areas, connections, inline structures, bridges, and culverts.

Classes:
    GeomParser - Utility functions for parsing geometry files
    GeomPreprocessor - Geometry preprocessor file operations
    GeomLandCover - 2D Manning's n land cover operations
    GeomCrossSection - 1D cross section operations
    GeomStorage - Storage area operations
    GeomLateral - Lateral structures and SA/2D connections
    GeomInlineWeir - Inline weir operations
    GeomBridge - Bridge operations
    GeomCulvert - Culvert operations
    GeomHtabUtils - HTAB parameter calculation utilities
    GeomHtab - Unified HTAB optimization for all geometry elements
    GeomMetadata - Efficient geometry element count extraction

Example:
    >>> from ras_commander import GeomCrossSection, GeomBridge
    >>>
    >>> # Get cross section data
    >>> xs_df = GeomCrossSection.get_cross_sections("model.g01")
    >>>
    >>> # Get bridge deck geometry
    >>> deck_df = GeomBridge.get_deck("model.g01", "River", "Reach", "1000")
    >>>
    >>> # Calculate optimal HTAB parameters
    >>> from ras_commander.geom import GeomHtabUtils
    >>> params = GeomHtabUtils.calculate_optimal_xs_htab(
    ...     invert=580.0, max_wse=605.0, safety_factor=1.3
    ... )
    >>>
    >>> # One-call optimization of ALL HTAB from results
    >>> from ras_commander.geom import GeomHtab
    >>> result = GeomHtab.optimize_all_htab_from_results(
    ...     "model.g01", "model.p01.hdf"
    ... )
    >>> print(f"Optimized {result['xs_modified']} XS, {result['structures_modified']} structures")
"""

from .GeomParser import GeomParser
from .GeomPreprocessor import GeomPreprocessor
from .GeomLandCover import GeomLandCover
from .GeomCrossSection import GeomCrossSection
from .GeomStorage import GeomStorage
from .GeomLateral import GeomLateral
from .GeomInlineWeir import GeomInlineWeir
from .GeomBridge import GeomBridge
from .GeomCulvert import GeomCulvert
from .GeomHtabUtils import GeomHtabUtils
from .GeomHtab import GeomHtab
from .GeomMetadata import GeomMetadata

__all__ = [
    'GeomParser',
    'GeomPreprocessor',
    'GeomLandCover',
    'GeomCrossSection',
    'GeomStorage',
    'GeomLateral',
    'GeomInlineWeir',
    'GeomBridge',
    'GeomCulvert',
    'GeomHtabUtils',
    'GeomHtab',
    'GeomMetadata',
]
