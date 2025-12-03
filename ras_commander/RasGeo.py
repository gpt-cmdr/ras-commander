"""
RasGeo - Operations for handling geometry files in HEC-RAS projects

DEPRECATION NOTICE:
    This class is deprecated and will be removed before v1.0.
    Please migrate to the new geometry subpackage classes:
    - GeomPreprocessor.clear_geompre_files() - replaces RasGeo.clear_geompre_files()
    - GeomLandCover.get_base_mannings_n() - replaces RasGeo.get_mannings_baseoverrides()
    - GeomLandCover.set_base_mannings_n() - replaces RasGeo.set_mannings_baseoverrides()
    - GeomLandCover.get_region_mannings_n() - replaces RasGeo.get_mannings_regionoverrides()
    - GeomLandCover.set_region_mannings_n() - replaces RasGeo.set_mannings_regionoverrides()

This module is part of the ras-commander library and uses a centralized logging configuration.

Logging Configuration:
- The logging is set up in the logging_config.py file.
- A @log_call decorator is available to automatically log function calls.
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Logs are written to both console and a rotating file handler.
- The default log file is 'ras_commander.log' in the 'logs' directory.
- The default log level is INFO.

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasGeo:
- clear_geompre_files(): Clears geometry preprocessor files for specified plan files [DEPRECATED]
- get_mannings_baseoverrides(): Reads base Manning's n table from a geometry file [DEPRECATED]
- get_mannings_regionoverrides(): Reads Manning's n region overrides from a geometry file [DEPRECATED]
- set_mannings_baseoverrides(): Writes base Manning's n values to a geometry file [DEPRECATED]
- set_mannings_regionoverrides(): Writes regional Manning's n overrides to a geometry file [DEPRECATED]
"""
import warnings
from pathlib import Path
from typing import List, Union
import pandas as pd
from .RasPrj import ras
from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)


class RasGeo:
    """
    A class for operations on HEC-RAS geometry files.

    DEPRECATED: This class is deprecated and will be removed before v1.0.
    Please migrate to the new geometry subpackage classes:
    - GeomPreprocessor for geometry preprocessor operations
    - GeomLandCover for Manning's n land cover operations
    """

    @staticmethod
    @log_call
    def clear_geompre_files(
        plan_files: Union[str, Path, List[Union[str, Path]]] = None,
        ras_object=None
    ) -> None:
        """
        Clear HEC-RAS geometry preprocessor files for specified plan files.

        DEPRECATED: Use GeomPreprocessor.clear_geompre_files() instead.
        This method will be removed before v1.0.

        Parameters:
            plan_files (Union[str, Path, List[Union[str, Path]]], optional):
                Full path(s) to the HEC-RAS plan file(s) (.p*).
                If None, clears all plan files in the project directory.
            ras_object: An optional RAS object instance.

        Returns:
            None: The function deletes files and updates the ras object's geometry dataframe
        """
        warnings.warn(
            "RasGeo.clear_geompre_files() is deprecated and will be removed before v1.0. "
            "Use GeomPreprocessor.clear_geompre_files() instead.",
            DeprecationWarning,
            stacklevel=2
        )

        from .geom import GeomPreprocessor
        return GeomPreprocessor.clear_geompre_files(plan_files, ras_object)

    @staticmethod
    @log_call
    def get_mannings_baseoverrides(geom_file_path):
        """
        Reads the base Manning's n table from a HEC-RAS geometry file.

        DEPRECATED: Use GeomLandCover.get_base_mannings_n() instead.
        This method will be removed before v1.0.

        Parameters:
        -----------
        geom_file_path : str or Path
            Path to the geometry file (.g##)

        Returns:
        --------
        pandas.DataFrame
            DataFrame with Table Number, Land Cover Name, and Base Mannings n Value
        """
        warnings.warn(
            "RasGeo.get_mannings_baseoverrides() is deprecated and will be removed before v1.0. "
            "Use GeomLandCover.get_base_mannings_n() instead.",
            DeprecationWarning,
            stacklevel=2
        )

        from .geom import GeomLandCover
        return GeomLandCover.get_base_mannings_n(geom_file_path)

    @staticmethod
    @log_call
    def get_mannings_regionoverrides(geom_file_path):
        """
        Reads the Manning's n region overrides from a HEC-RAS geometry file.

        DEPRECATED: Use GeomLandCover.get_region_mannings_n() instead.
        This method will be removed before v1.0.

        Parameters:
        -----------
        geom_file_path : str or Path
            Path to the geometry file (.g##)

        Returns:
        --------
        pandas.DataFrame
            DataFrame with Table Number, Land Cover Name, MainChannel value, and Region Name
        """
        warnings.warn(
            "RasGeo.get_mannings_regionoverrides() is deprecated and will be removed before v1.0. "
            "Use GeomLandCover.get_region_mannings_n() instead.",
            DeprecationWarning,
            stacklevel=2
        )

        from .geom import GeomLandCover
        return GeomLandCover.get_region_mannings_n(geom_file_path)

    @staticmethod
    @log_call
    def set_mannings_baseoverrides(geom_file_path, mannings_data):
        """
        Writes base Manning's n values to a HEC-RAS geometry file.

        DEPRECATED: Use GeomLandCover.set_base_mannings_n() instead.
        This method will be removed before v1.0.

        Parameters:
        -----------
        geom_file_path : str or Path
            Path to the geometry file (.g##)
        mannings_data : DataFrame
            DataFrame with columns 'Table Number', 'Land Cover Name', and 'Base Mannings n Value'

        Returns:
        --------
        bool
            True if successful
        """
        warnings.warn(
            "RasGeo.set_mannings_baseoverrides() is deprecated and will be removed before v1.0. "
            "Use GeomLandCover.set_base_mannings_n() instead.",
            DeprecationWarning,
            stacklevel=2
        )

        from .geom import GeomLandCover
        return GeomLandCover.set_base_mannings_n(geom_file_path, mannings_data)

    @staticmethod
    @log_call
    def set_mannings_regionoverrides(geom_file_path, mannings_data):
        """
        Writes regional Manning's n overrides to a HEC-RAS geometry file.

        DEPRECATED: Use GeomLandCover.set_region_mannings_n() instead.
        This method will be removed before v1.0.

        Parameters:
        -----------
        geom_file_path : str or Path
            Path to the geometry file (.g##)
        mannings_data : DataFrame
            DataFrame with columns 'Table Number', 'Land Cover Name', 'MainChannel', and 'Region Name'

        Returns:
        --------
        bool
            True if successful
        """
        warnings.warn(
            "RasGeo.set_mannings_regionoverrides() is deprecated and will be removed before v1.0. "
            "Use GeomLandCover.set_region_mannings_n() instead.",
            DeprecationWarning,
            stacklevel=2
        )

        from .geom import GeomLandCover
        return GeomLandCover.set_region_mannings_n(geom_file_path, mannings_data)
