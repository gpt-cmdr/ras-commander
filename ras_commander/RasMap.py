"""
RasMap - Parses HEC-RAS mapper configuration files (.rasmap)

This module provides functionality to extract and organize information from 
HEC-RAS mapper configuration files, including paths to terrain, soil, and land cover data.
It also includes functions to automate the post-processing of stored maps.

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
import shutil
from typing import Union, Optional, Dict, List, Any

from .RasPrj import ras
from .RasPlan import RasPlan
from .RasCmdr import RasCmdr
from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)

class RasMap:
    """
    Class for parsing and accessing information from HEC-RAS mapper configuration files (.rasmap).
    
    This class provides methods to extract paths to terrain, soil, land cover data,
    and various project settings from the .rasmap file associated with a HEC-RAS project.
    It also includes functionality to automate the post-processing of stored maps.
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

    @staticmethod
    @log_call
    def get_terrain_names(rasmap_path: Union[str, Path]) -> List[str]:
        """
        Extracts terrain layer names from a given .rasmap file.
        
        Args:
            rasmap_path (Union[str, Path]): Path to the .rasmap file.

        Returns:
            List[str]: A list of terrain names.
        
        Raises:
            FileNotFoundError: If the rasmap file does not exist.
            ValueError: If the file is not a valid XML or lacks a 'Terrains' section.
        """
        rasmap_path = Path(rasmap_path)
        if not rasmap_path.is_file():
            raise FileNotFoundError(f"The file '{rasmap_path}' does not exist.")

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            raise ValueError(f"Failed to parse the RASMAP file. Ensure it is a valid XML file. Error: {e}")

        terrains_element = root.find('Terrains')
        if terrains_element is None:
            logger.warning("The RASMAP file does not contain a 'Terrains' section.")
            return []

        terrain_names = [layer.get('Name') for layer in terrains_element.findall('Layer') if layer.get('Name')]
        logger.info(f"Extracted terrain names: {terrain_names}")
        return terrain_names


    @staticmethod
    @log_call
    def postprocess_stored_maps(
        plan_number: Union[str, List[str]],
        specify_terrain: Optional[str] = None,
        layers: Union[str, List[str]] = None,
        ras_object: Optional[Any] = None
    ) -> bool:
        """
        Automates the generation of stored floodplain map outputs (e.g., .tif files).

        This function modifies the plan and .rasmap files to generate floodplain maps
        for one or more plans, then restores the original files.

        Args:
            plan_number (Union[str, List[str]]): Plan number(s) to generate maps for.
            specify_terrain (Optional[str]): The name of a specific terrain to use.
            layers (Union[str, List[str]], optional): A list of map layers to generate.
                Defaults to ['WSEL', 'Velocity', 'Depth'].
            ras_object (Optional[Any]): The RAS project object.

        Returns:
            bool: True if the process completed successfully, False otherwise.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        if layers is None:
            layers = ['WSEL', 'Velocity', 'Depth']
        elif isinstance(layers, str):
            layers = [layers]

        # Convert plan_number to list if it's a string
        plan_number_list = [plan_number] if isinstance(plan_number, str) else plan_number

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        rasmap_backup_path = rasmap_path.with_suffix(f"{rasmap_path.suffix}.storedmap.bak")

        # Store plan paths and their backups
        plan_paths = []
        plan_backup_paths = []
        for plan_num in plan_number_list:
            plan_path = Path(RasPlan.get_plan_path(plan_num, ras_obj))
            plan_backup_path = plan_path.with_suffix(f"{plan_path.suffix}.storedmap.bak")
            plan_paths.append(plan_path)
            plan_backup_paths.append(plan_backup_path)

        def _create_map_element(name, map_type, profile_name="Max"):
            map_params = {
                "MapType": map_type,
                "OutputMode": "Stored Current Terrain",
                "ProfileIndex": "2147483647",
                "ProfileName": profile_name
            }
            if specify_terrain:
                map_params["Terrain"] = specify_terrain
            
            layer_elem = ET.Element('Layer', Name=name, Type="RASResultsMap", Checked="True")
            map_params_elem = ET.SubElement(layer_elem, 'MapParameters')
            for k, v in map_params.items():
                map_params_elem.set(k, str(v))
            return layer_elem

        try:
            # --- 1. Backup and Modify Plan Files ---
            for plan_num, plan_path, plan_backup_path in zip(plan_number_list, plan_paths, plan_backup_paths):
                logger.info(f"Backing up plan file {plan_path} to {plan_backup_path}")
                shutil.copy2(plan_path, plan_backup_path)
                
                logger.info(f"Updating plan run flags for floodplain mapping for plan {plan_num}...")
                RasPlan.update_run_flags(
                    plan_num,
                    geometry_preprocessor=False,
                    unsteady_flow_simulation=False,
                    post_processor=False,
                    floodplain_mapping=True, # Note: True maps to 0, which means "Run"
                    ras_object=ras_obj
                )

            # --- 2. Backup and Modify RASMAP File ---
            logger.info(f"Backing up rasmap file {rasmap_path} to {rasmap_backup_path}")
            shutil.copy2(rasmap_path, rasmap_backup_path)

            tree = ET.parse(rasmap_path)
            root = tree.getroot()
            
            results_section = root.find('Results')
            if results_section is None:
                raise ValueError(f"No <Results> section found in {rasmap_path}")

            # Process each plan's results layer
            for plan_num in plan_number_list:
                plan_hdf_part = f".p{plan_num}.hdf"
                results_layer = None
                for layer in results_section.findall("Layer[@Type='RASResults']"):
                    filename = layer.get("Filename")
                    if filename and plan_hdf_part.lower() in filename.lower():
                        results_layer = layer
                        break

                if results_layer is None:
                    logger.warning(f"Could not find RASResults layer for plan ending in '{plan_hdf_part}' in {rasmap_path}")
                    continue
                
                map_definitions = {"WSEL": "elevation", "Velocity": "velocity", "Depth": "depth"}
                for layer_name in layers:
                    if layer_name in map_definitions:
                        map_type = map_definitions[layer_name]
                        layername_attr = "Water Surface" if layer_name == "WSEL" else None
                        map_elem = _create_map_element(layer_name, map_type)
                        if layername_attr:
                            map_elem.find("MapParameters").set("LayerName", layername_attr)
                        results_layer.append(map_elem)
                        logger.info(f"Added '{layer_name}' stored map to results layer for plan {plan_num}.")

            if specify_terrain:
                terrains_elem = root.find('Terrains')
                if terrains_elem is not None:
                    for layer in list(terrains_elem):
                        if layer.get('Name') != specify_terrain:
                            terrains_elem.remove(layer)
                    logger.info(f"Filtered terrains, keeping only '{specify_terrain}'.")

            tree.write(rasmap_path, encoding='utf-8', xml_declaration=True)
            
            # --- 3. Execute HEC-RAS ---
            logger.info("Opening HEC-RAS...")
            ras_exe = ras_obj.ras_exe_path
            prj_path = f'"{str(ras_obj.prj_file)}"'
            command = f"{ras_exe} {prj_path}"
            
            try:
                import sys
                import subprocess
                if sys.platform == "win32":
                    hecras_process = subprocess.Popen(command)
                else:
                    hecras_process = subprocess.Popen([ras_exe, prj_path])

                logger.info(f"HEC-RAS opened with Process ID: {hecras_process.pid}")
                logger.info(f"Please run plan(s) {', '.join(plan_number_list)} using the 'Compute Multiple' window in HEC-RAS to generate floodplain mapping results.")
                
                # Wait for HEC-RAS to close
                logger.info("Waiting for HEC-RAS to close...")
                hecras_process.wait()
                logger.info("HEC-RAS has closed")
                
                success = True

            except Exception as e:
                logger.error(f"Failed to launch HEC-RAS: {e}")
                success = False

            if not success:
                logger.error("Floodplain mapping computation failed.")
                return False

            logger.info("Floodplain mapping computation successful.")
            return True
        
        except Exception as e:
            logger.error(f"Error in postprocess_stored_maps: {e}")
            return False

        finally:
            # --- 4. Restore Files ---
            for plan_path, plan_backup_path in zip(plan_paths, plan_backup_paths):
                if plan_backup_path.exists():
                    logger.info(f"Restoring original plan file from {plan_backup_path}")
                    shutil.move(plan_backup_path, plan_path)
            if rasmap_backup_path.exists():
                logger.info(f"Restoring original rasmap file from {rasmap_backup_path}")
                shutil.move(rasmap_backup_path, rasmap_path)