"""
RasMap - Parses HEC-RAS mapper configuration files (.rasmap)

This module provides functionality to extract and organize information from 
HEC-RAS mapper configuration files, including paths to terrain, soil, and land cover data.

This module is part of the ras-commander library and uses a centralized logging configuration.

Logging Configuration:
- The logging is set up in the logging_config.py file.
- A @log_call decorator is available to automatically log function calls.
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

Classes:
    RasMap: Class for parsing and accessing HEC-RAS mapper configuration.
"""

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import pandas as pd
from typing import Union, Optional, Dict, List, Any

from .RasPrj import ras
from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

class RasMap:
    """
    Class for parsing and accessing information from HEC-RAS mapper configuration files (.rasmap).
    
    This class provides methods to extract paths to terrain, soil, land cover data,
    and various project settings from the .rasmap file associated with a HEC-RAS project.
    """
    
    @staticmethod
    @log_call
    def parse_rasmap(rasmap_path: Union[str, Path], ras_object=None) -> pd.DataFrame:
        """
        Parse a .rasmap file and extract relevant information.
        
        Args:
            rasmap_path (Union[str, Path]): Path to the .rasmap file.
            ras_object: Optional RAS object instance.
            
        Returns:
            pd.DataFrame: DataFrame containing extracted information from the .rasmap file.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        rasmap_path = Path(rasmap_path)
        if not rasmap_path.exists():
            logger.error(f"RASMapper file not found: {rasmap_path}")
            # Create a single row DataFrame with all empty values
            return pd.DataFrame({
                'projection_path': [None],
                'profile_lines_path': [[]],
                'soil_layer_path': [[]],
                'infiltration_hdf_path': [[]],
                'landcover_hdf_path': [[]],
                'terrain_hdf_path': [[]],
                'current_settings': [{}]
            })
        
        try:
            # Initialize data for the DataFrame - just one row with lists
            data = {
                'projection_path': [None],
                'profile_lines_path': [[]],
                'soil_layer_path': [[]],
                'infiltration_hdf_path': [[]],
                'landcover_hdf_path': [[]],
                'terrain_hdf_path': [[]],
                'current_settings': [{}]
            }
            
            # Read the file content
            with open(rasmap_path, 'r', encoding='utf-8') as f:
                xml_content = f.read()
            
            # Check if it's a valid XML file
            if not xml_content.strip().startswith('<'):
                logger.error(f"File does not appear to be valid XML: {rasmap_path}")
                return pd.DataFrame(data)
            
            # Parse the XML file
            try:
                tree = ET.parse(rasmap_path)
                root = tree.getroot()
            except ET.ParseError as e:
                logger.error(f"Error parsing XML in {rasmap_path}: {e}")
                return pd.DataFrame(data)
            
            # Helper function to convert relative paths to absolute paths
            def to_absolute_path(relative_path: str) -> str:
                if not relative_path:
                    return None
                # Remove any leading .\ or ./
                relative_path = relative_path.lstrip('.\\').lstrip('./')
                # Convert to absolute path relative to project folder
                return str(ras_obj.project_folder / relative_path)
            
            # Extract projection path
            try:
                projection_elem = root.find(".//RASProjectionFilename")
                if projection_elem is not None and 'Filename' in projection_elem.attrib:
                    data['projection_path'][0] = to_absolute_path(projection_elem.attrib['Filename'])
            except Exception as e:
                logger.warning(f"Error extracting projection path: {e}")
            
            # Extract profile lines path
            try:
                profile_lines_elem = root.find(".//Features/Layer[@Name='Profile Lines']")
                if profile_lines_elem is not None and 'Filename' in profile_lines_elem.attrib:
                    data['profile_lines_path'][0].append(to_absolute_path(profile_lines_elem.attrib['Filename']))
            except Exception as e:
                logger.warning(f"Error extracting profile lines path: {e}")
            
            # Extract soil layer paths
            try:
                soil_layers = root.findall(".//Layer[@Name='Hydrologic Soil Groups']")
                for layer in soil_layers:
                    if 'Filename' in layer.attrib:
                        data['soil_layer_path'][0].append(to_absolute_path(layer.attrib['Filename']))
            except Exception as e:
                logger.warning(f"Error extracting soil layer paths: {e}")
            
            # Extract infiltration HDF paths
            try:
                infiltration_layers = root.findall(".//Layer[@Name='Infiltration']")
                for layer in infiltration_layers:
                    if 'Filename' in layer.attrib:
                        data['infiltration_hdf_path'][0].append(to_absolute_path(layer.attrib['Filename']))
            except Exception as e:
                logger.warning(f"Error extracting infiltration HDF paths: {e}")
            
            # Extract landcover HDF paths
            try:
                landcover_layers = root.findall(".//Layer[@Name='LandCover']")
                for layer in landcover_layers:
                    if 'Filename' in layer.attrib:
                        data['landcover_hdf_path'][0].append(to_absolute_path(layer.attrib['Filename']))
            except Exception as e:
                logger.warning(f"Error extracting landcover HDF paths: {e}")
            
            # Extract terrain HDF paths
            try:
                terrain_layers = root.findall(".//Terrains/Layer")
                for layer in terrain_layers:
                    if 'Filename' in layer.attrib:
                        data['terrain_hdf_path'][0].append(to_absolute_path(layer.attrib['Filename']))
            except Exception as e:
                logger.warning(f"Error extracting terrain HDF paths: {e}")
            
            # Extract current settings
            current_settings = {}
            try:
                settings_elem = root.find(".//CurrentSettings")
                if settings_elem is not None:
                    # Extract ProjectSettings
                    project_settings_elem = settings_elem.find("ProjectSettings")
                    if project_settings_elem is not None:
                        for child in project_settings_elem:
                            current_settings[child.tag] = child.text
                    
                    # Extract Folders
                    folders_elem = settings_elem.find("Folders")
                    if folders_elem is not None:
                        for child in folders_elem:
                            current_settings[child.tag] = child.text
                            
                data['current_settings'][0] = current_settings
            except Exception as e:
                logger.warning(f"Error extracting current settings: {e}")
            
            # Create DataFrame
            df = pd.DataFrame(data)
            logger.info(f"Successfully parsed RASMapper file: {rasmap_path}")
            return df
            
        except Exception as e:
            logger.error(f"Unexpected error processing RASMapper file {rasmap_path}: {e}")
            # Create a single row DataFrame with all empty values
            return pd.DataFrame({
                'projection_path': [None],
                'profile_lines_path': [[]],
                'soil_layer_path': [[]],
                'infiltration_hdf_path': [[]],
                'landcover_hdf_path': [[]],
                'terrain_hdf_path': [[]],
                'current_settings': [{}]
            })
    
    @staticmethod
    @log_call
    def get_rasmap_path(ras_object=None) -> Optional[Path]:
        """
        Get the path to the .rasmap file based on the current project.
        
        Args:
            ras_object: Optional RAS object instance.
            
        Returns:
            Optional[Path]: Path to the .rasmap file if found, None otherwise.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        project_name = ras_obj.project_name
        project_folder = ras_obj.project_folder
        rasmap_path = project_folder / f"{project_name}.rasmap"
        
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return None
        
        return rasmap_path
    
    @staticmethod
    @log_call
    def initialize_rasmap_df(ras_object=None) -> pd.DataFrame:
        """
        Initialize the rasmap_df as part of project initialization.
        
        Args:
            ras_object: Optional RAS object instance.
            
        Returns:
            pd.DataFrame: DataFrame containing information from the .rasmap file.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        
        rasmap_path = RasMap.get_rasmap_path(ras_obj)
        if rasmap_path is None:
            logger.warning("No .rasmap file found for this project. Creating empty rasmap_df.")
            # Create a single row DataFrame with all empty values
            return pd.DataFrame({
                'projection_path': [None],
                'profile_lines_path': [[]],
                'soil_layer_path': [[]],
                'infiltration_hdf_path': [[]],
                'landcover_hdf_path': [[]],
                'terrain_hdf_path': [[]],
                'current_settings': [{}]
            })
        
        return RasMap.parse_rasmap(rasmap_path, ras_obj)