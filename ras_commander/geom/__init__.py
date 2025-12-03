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

Example:
    >>> from ras_commander import GeomCrossSection, GeomBridge
    >>>
    >>> # Get cross section data
    >>> xs_df = GeomCrossSection.get_cross_sections("model.g01")
    >>>
    >>> # Get bridge deck geometry
    >>> deck_df = GeomBridge.get_deck("model.g01", "River", "Reach", "1000")
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
]
