"""
RasGeometry - Operations for parsing and modifying HEC-RAS geometry files

DEPRECATION NOTICE:
    This class is deprecated and will be removed before v1.0.
    Please migrate to the new geometry subpackage classes:

    Cross Section Operations:
    - GeomCrossSection.get_cross_sections() - replaces RasGeometry.get_cross_sections()
    - GeomCrossSection.get_station_elevation() - replaces RasGeometry.get_station_elevation()
    - GeomCrossSection.set_station_elevation() - replaces RasGeometry.set_station_elevation()
    - GeomCrossSection.get_bank_stations() - replaces RasGeometry.get_bank_stations()
    - GeomCrossSection.get_expansion_contraction() - replaces RasGeometry.get_expansion_contraction()
    - GeomCrossSection.get_mannings_n() - replaces RasGeometry.get_mannings_n()

    Storage Area Operations:
    - GeomStorage.get_storage_areas() - replaces RasGeometry.get_storage_areas()
    - GeomStorage.get_elevation_volume() - replaces RasGeometry.get_storage_elevation_volume()

    Lateral Structure Operations:
    - GeomLateral.get_lateral_structures() - replaces RasGeometry.get_lateral_structures()
    - GeomLateral.get_weir_profile() - replaces RasGeometry.get_lateral_weir_profile()

    SA/2D Connection Operations:
    - GeomLateral.get_connections() - replaces RasGeometry.get_connections()
    - GeomLateral.get_connection_profile() - replaces RasGeometry.get_connection_weir_profile()
    - GeomLateral.get_connection_gates() - replaces RasGeometry.get_connection_gates()

This module is part of the ras-commander library and uses a centralized logging configuration.

All methods are static and designed to be used without instantiation.

List of Functions in RasGeometry (all DEPRECATED):
- get_cross_sections() - Extract all cross section metadata [DEPRECATED]
- get_station_elevation() - Read station/elevation pairs for a cross section [DEPRECATED]
- set_station_elevation() - Write station/elevation with automatic bank interpolation [DEPRECATED]
- get_bank_stations() - Read left and right bank station locations [DEPRECATED]
- get_expansion_contraction() - Read expansion and contraction coefficients [DEPRECATED]
- get_mannings_n() - Read Manning's roughness values with LOB/Channel/ROB classification [DEPRECATED]
- get_storage_areas() - List all storage area names (excluding 2D flow areas) [DEPRECATED]
- get_storage_elevation_volume() - Read elevation-volume curve for a storage area [DEPRECATED]
- get_lateral_structures() - List all lateral weir structures with metadata [DEPRECATED]
- get_lateral_weir_profile() - Read station-elevation profile for lateral weir [DEPRECATED]
- get_connections() - List all SA/2D area connections [DEPRECATED]
- get_connection_weir_profile() - Read dam/weir crest station-elevation profile [DEPRECATED]
- get_connection_gates() - Read gate definitions (CSV format, 23+ parameters) [DEPRECATED]
"""

import warnings
from pathlib import Path
from typing import Union, Optional, List, Tuple
import pandas as pd

from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)


class RasGeometry:
    """
    Operations for parsing and modifying HEC-RAS geometry files.

    DEPRECATED: This class is deprecated and will be removed before v1.0.
    Please migrate to the new geometry subpackage classes:
    - GeomCrossSection for cross section operations
    - GeomStorage for storage area operations
    - GeomLateral for lateral structure and connection operations

    All methods are static and designed to be used without instantiation.
    """

    # ========== CROSS SECTION OPERATIONS (DEPRECATED) ==========

    @staticmethod
    @log_call
    def get_cross_sections(geom_file: Union[str, Path],
                          river: Optional[str] = None,
                          reach: Optional[str] = None) -> pd.DataFrame:
        """
        Extract cross section metadata from geometry file.

        DEPRECATED: Use GeomCrossSection.get_cross_sections() instead.
        """
        warnings.warn(
            "RasGeometry.get_cross_sections() is deprecated. "
            "Use GeomCrossSection.get_cross_sections() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomCrossSection
        return GeomCrossSection.get_cross_sections(geom_file, river, reach)

    @staticmethod
    @log_call
    def get_station_elevation(geom_file: Union[str, Path],
                             river: str,
                             reach: str,
                             rs: str) -> pd.DataFrame:
        """
        Extract station/elevation pairs for a cross section.

        DEPRECATED: Use GeomCrossSection.get_station_elevation() instead.
        """
        warnings.warn(
            "RasGeometry.get_station_elevation() is deprecated. "
            "Use GeomCrossSection.get_station_elevation() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomCrossSection
        return GeomCrossSection.get_station_elevation(geom_file, river, reach, rs)

    @staticmethod
    @log_call
    def set_station_elevation(geom_file: Union[str, Path],
                             river: str,
                             reach: str,
                             rs: str,
                             sta_elev_df: pd.DataFrame,
                             bank_left: Optional[float] = None,
                             bank_right: Optional[float] = None):
        """
        Write station/elevation pairs to a cross section with automatic bank interpolation.

        DEPRECATED: Use GeomCrossSection.set_station_elevation() instead.
        """
        warnings.warn(
            "RasGeometry.set_station_elevation() is deprecated. "
            "Use GeomCrossSection.set_station_elevation() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomCrossSection
        return GeomCrossSection.set_station_elevation(
            geom_file, river, reach, rs, sta_elev_df, bank_left, bank_right
        )

    @staticmethod
    @log_call
    def get_bank_stations(geom_file: Union[str, Path],
                         river: str,
                         reach: str,
                         rs: str) -> Optional[Tuple[float, float]]:
        """
        Extract left and right bank station locations for a cross section.

        DEPRECATED: Use GeomCrossSection.get_bank_stations() instead.
        """
        warnings.warn(
            "RasGeometry.get_bank_stations() is deprecated. "
            "Use GeomCrossSection.get_bank_stations() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomCrossSection
        return GeomCrossSection.get_bank_stations(geom_file, river, reach, rs)

    @staticmethod
    @log_call
    def get_expansion_contraction(geom_file: Union[str, Path],
                                  river: str,
                                  reach: str,
                                  rs: str) -> Tuple[float, float]:
        """
        Extract expansion and contraction coefficients for a cross section.

        DEPRECATED: Use GeomCrossSection.get_expansion_contraction() instead.
        """
        warnings.warn(
            "RasGeometry.get_expansion_contraction() is deprecated. "
            "Use GeomCrossSection.get_expansion_contraction() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomCrossSection
        return GeomCrossSection.get_expansion_contraction(geom_file, river, reach, rs)

    @staticmethod
    @log_call
    def get_mannings_n(geom_file: Union[str, Path],
                      river: str,
                      reach: str,
                      rs: str) -> pd.DataFrame:
        """
        Extract Manning's n roughness values for a cross section.

        DEPRECATED: Use GeomCrossSection.get_mannings_n() instead.
        """
        warnings.warn(
            "RasGeometry.get_mannings_n() is deprecated. "
            "Use GeomCrossSection.get_mannings_n() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomCrossSection
        return GeomCrossSection.get_mannings_n(geom_file, river, reach, rs)

    # ========== STORAGE AREA OPERATIONS (DEPRECATED) ==========

    @staticmethod
    @log_call
    def get_storage_areas(geom_file: Union[str, Path],
                         exclude_2d: bool = True) -> List[str]:
        """
        Extract list of storage area names from geometry file.

        DEPRECATED: Use GeomStorage.get_storage_areas() instead.
        Note: The new method returns a DataFrame with more information.
        This wrapper converts it to List[str] for backward compatibility.
        """
        warnings.warn(
            "RasGeometry.get_storage_areas() is deprecated. "
            "Use GeomStorage.get_storage_areas() instead. "
            "Note: New method returns DataFrame, not List[str].",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomStorage
        df = GeomStorage.get_storage_areas(geom_file, exclude_2d)
        # Convert DataFrame to List[str] for backward compatibility
        if df.empty:
            return []
        return df['Name'].tolist()

    @staticmethod
    @log_call
    def get_storage_elevation_volume(geom_file: Union[str, Path],
                                     area_name: str) -> pd.DataFrame:
        """
        Extract storage area elevation-volume curve.

        DEPRECATED: Use GeomStorage.get_elevation_volume() instead.
        """
        warnings.warn(
            "RasGeometry.get_storage_elevation_volume() is deprecated. "
            "Use GeomStorage.get_elevation_volume() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomStorage
        return GeomStorage.get_elevation_volume(geom_file, area_name)

    # ========== LATERAL STRUCTURE OPERATIONS (DEPRECATED) ==========

    @staticmethod
    @log_call
    def get_lateral_structures(geom_file: Union[str, Path],
                               river: Optional[str] = None,
                               reach: Optional[str] = None) -> pd.DataFrame:
        """
        Extract lateral structure definitions from geometry file.

        DEPRECATED: Use GeomLateral.get_lateral_structures() instead.
        """
        warnings.warn(
            "RasGeometry.get_lateral_structures() is deprecated. "
            "Use GeomLateral.get_lateral_structures() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomLateral
        return GeomLateral.get_lateral_structures(geom_file, river, reach)

    @staticmethod
    @log_call
    def get_lateral_weir_profile(geom_file: Union[str, Path],
                                  river: str,
                                  reach: str,
                                  rs: str,
                                  position: int = 0) -> pd.DataFrame:
        """
        Extract lateral weir station-elevation profile.

        DEPRECATED: Use GeomLateral.get_weir_profile() instead.
        """
        warnings.warn(
            "RasGeometry.get_lateral_weir_profile() is deprecated. "
            "Use GeomLateral.get_weir_profile() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomLateral
        return GeomLateral.get_weir_profile(geom_file, river, reach, rs, position)

    # ========== SA/2D CONNECTION OPERATIONS (DEPRECATED) ==========

    @staticmethod
    @log_call
    def get_connections(geom_file: Union[str, Path]) -> pd.DataFrame:
        """
        Extract all SA/2D area connection definitions.

        DEPRECATED: Use GeomLateral.get_connections() instead.
        """
        warnings.warn(
            "RasGeometry.get_connections() is deprecated. "
            "Use GeomLateral.get_connections() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomLateral
        return GeomLateral.get_connections(geom_file)

    @staticmethod
    @log_call
    def get_connection_weir_profile(geom_file: Union[str, Path],
                                    connection_name: str) -> pd.DataFrame:
        """
        Extract weir/dam crest station-elevation profile for a connection.

        DEPRECATED: Use GeomLateral.get_connection_profile() instead.
        """
        warnings.warn(
            "RasGeometry.get_connection_weir_profile() is deprecated. "
            "Use GeomLateral.get_connection_profile() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomLateral
        return GeomLateral.get_connection_profile(geom_file, connection_name)

    @staticmethod
    @log_call
    def get_connection_gates(geom_file: Union[str, Path],
                            connection_name: str) -> pd.DataFrame:
        """
        Extract gate definitions for a connection.

        DEPRECATED: Use GeomLateral.get_connection_gates() instead.
        """
        warnings.warn(
            "RasGeometry.get_connection_gates() is deprecated. "
            "Use GeomLateral.get_connection_gates() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from .geom import GeomLateral
        return GeomLateral.get_connection_gates(geom_file, connection_name)
