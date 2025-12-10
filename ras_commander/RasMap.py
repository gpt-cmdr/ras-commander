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

-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasMap:
- parse_rasmap(): Parse a .rasmap file and extract relevant information
- get_rasmap_path(): Get the path to the .rasmap file based on the current project
- initialize_rasmap_df(): Initialize the rasmap_df as part of project initialization
- get_terrain_names(): Extracts terrain layer names from a given .rasmap file
- postprocess_stored_maps(): Automates the generation of stored floodplain map outputs (e.g., .tif files)
- get_results_folder(): Get the folder path containing raster results for a specified plan
- get_results_raster(): Get the .vrt file path for a specified plan and variable name
- set_water_surface_render_mode(): Set the water surface rendering mode (horizontal or sloped)
- get_water_surface_render_mode(): Get the current water surface rendering mode
- map_ras_results(): Generate raster maps from HDF results using programmatic interpolation
"""

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import pandas as pd
import shutil
from typing import Union, Optional, Dict, List, Any, TYPE_CHECKING

import numpy as np

from .RasPrj import ras
from .RasPlan import RasPlan
from .RasCmdr import RasCmdr
from .RasUtils import RasUtils
from .RasGuiAutomation import RasGuiAutomation
from .LoggingConfig import get_logger
from .Decorators import log_call

if TYPE_CHECKING:
    from geopandas import GeoDataFrame

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
        ras_object: Optional[Any] = None,
        auto_click_compute: bool = True
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
            auto_click_compute (bool, optional): If True, uses GUI automation to automatically
                click "Run > Unsteady Flow Analysis" and "Compute" button. If False, just
                opens HEC-RAS and waits for manual execution. Defaults to True.

        Returns:
            bool: True if the process completed successfully, False otherwise.

        Notes:
            - auto_click_compute=True: Automated GUI workflow (clicks menu and Compute button)
            - auto_click_compute=False: Manual workflow (user must click Compute)
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
        plan_results_folders = {}  # Map plan_num to results folder name

        for plan_num in plan_number_list:
            plan_path = Path(RasPlan.get_plan_path(plan_num, ras_obj))
            plan_backup_path = plan_path.with_suffix(f"{plan_path.suffix}.storedmap.bak")
            plan_paths.append(plan_path)
            plan_backup_paths.append(plan_backup_path)

            # Get the Short Identifier for this plan to determine results folder
            plan_df = ras_obj.plan_df
            plan_info = plan_df[plan_df['plan_number'] == plan_num]
            if not plan_info.empty:
                short_id = plan_info.iloc[0]['Short Identifier']
                if pd.notna(short_id) and short_id:
                    plan_results_folders[plan_num] = short_id
                else:
                    # Fallback: use plan number if no Short Identifier
                    plan_results_folders[plan_num] = f"Plan_{plan_num}"
                    logger.warning(f"Plan {plan_num} has no Short Identifier, using 'Plan_{plan_num}' as folder name")
            else:
                plan_results_folders[plan_num] = f"Plan_{plan_num}"
                logger.warning(f"Could not find plan {plan_num} in plan_df, using 'Plan_{plan_num}' as folder name")

        def _create_map_element(name, map_type, results_folder, profile_name="Max"):
            # Generate filename: "WSE (Max).vrt", "Depth (Max).vrt", etc.
            filename = f"{name} ({profile_name}).vrt"
            relative_path = f".\\{results_folder}\\{filename}"

            map_params = {
                "MapType": map_type,
                "OutputMode": "Stored Current Terrain",
                "StoredFilename": relative_path,  # Required for stored maps
                "ProfileIndex": "2147483647",
                "ProfileName": profile_name
            }

            # Create Layer element with Filename attribute
            layer_elem = ET.Element(
                'Layer',
                Name=name,
                Type="RASResultsMap",
                Checked="True",
                Filename=relative_path  # Required for stored maps
            )

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
                
                # Map user-provided layer names to HEC-RAS variable names and map types
                # Note: "WSE" is the correct HEC-RAS convention (not "WSEL")
                map_definitions = {
                    "WSE": "elevation",
                    "WSEL": "elevation",  # Accept both for backward compatibility, but use "WSE" in output
                    "Velocity": "velocity",
                    "Depth": "depth"
                }

                # Get the results folder for this plan
                results_folder = plan_results_folders.get(plan_num, f"Plan_{plan_num}")

                for layer_name in layers:
                    if layer_name in map_definitions:
                        map_type = map_definitions[layer_name]

                        # Convert WSEL to WSE for output (HEC-RAS convention)
                        output_name = "WSE" if layer_name == "WSEL" else layer_name

                        map_elem = _create_map_element(output_name, map_type, results_folder)
                        results_layer.append(map_elem)
                        logger.info(f"Added '{output_name}' stored map to results layer for plan {plan_num}.")

            if specify_terrain:
                terrains_elem = root.find('Terrains')
                if terrains_elem is not None:
                    for layer in list(terrains_elem):
                        if layer.get('Name') != specify_terrain:
                            terrains_elem.remove(layer)
                    logger.info(f"Filtered terrains, keeping only '{specify_terrain}'.")

            tree.write(rasmap_path, encoding='utf-8', xml_declaration=True)
            
            # --- 3. Execute HEC-RAS ---
            if auto_click_compute:
                # Use GUI automation to automatically click menu and Compute button
                logger.info("Using GUI automation to run floodplain mapping...")

                # Note: For multiple plans, we run the first plan's automation
                # The user can manually run additional plans if needed
                first_plan = plan_number_list[0]

                success = RasGuiAutomation.open_and_compute(
                    plan_number=first_plan,
                    ras_object=ras_obj,
                    auto_click_compute=True,
                    wait_for_user=True
                )

                if len(plan_number_list) > 1:
                    logger.info(f"Note: GUI automation ran plan {first_plan}. "
                               f"Please manually run remaining plans: {', '.join(plan_number_list[1:])}")

                if not success:
                    logger.error("Floodplain mapping computation failed.")
                    return False

            else:
                # Manual mode: Just open HEC-RAS and wait for user to execute
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

    @staticmethod
    @log_call
    def get_results_folder(plan_number: Union[str, int, float], ras_object=None) -> Path:
        """
        Get the folder path containing raster results for a specified plan.

        HEC-RAS creates output folders based on the plan's Short Identifier.
        Windows folder naming replaces special characters with underscores.

        Args:
            plan_number (Union[str, int, float]): Plan number (accepts flexible formats like 1, "01", "001").
            ras_object: Optional RAS object instance.

        Returns:
            Path: Path to the mapping output folder.

        Raises:
            ValueError: If the plan number is not found or output folder doesn't exist.

        Examples:
            >>> folder = RasMap.get_results_folder("01")
            >>> folder = RasMap.get_results_folder(1)
            >>> folder = RasMap.get_results_folder("08", ras_object=my_project)

        Notes:
            - Normalizes plan number to two-digit format ("01", "02", etc.)
            - Retrieves Short Identifier from plan_df
            - Normalizes Short ID for Windows folder naming (special chars -> underscores)
            - Searches project folder for matching output directory
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Normalize plan number to two-digit format
        plan_number = RasUtils.normalize_ras_number(plan_number)

        # Get plan metadata from plan_df
        plan_df = ras_obj.plan_df
        plan_info = plan_df[plan_df['plan_number'] == plan_number]

        if plan_info.empty:
            raise ValueError(
                f"Plan {plan_number} not found in project. "
                f"Available plans: {list(plan_df['plan_number'])}"
            )

        short_id = plan_info.iloc[0]['Short Identifier']

        if pd.isna(short_id) or not short_id:
            raise ValueError(
                f"Plan {plan_number} does not have a Short Identifier. "
                "Check the plan file for missing metadata."
            )

        # Normalize Short ID to match Windows folder naming
        # RASMapper replaces special characters for Windows compatibility
        replacements = {
            '/': '_', '\\': '_', ':': '_', '*': '_',
            '?': '_', '"': '_', '<': '_', '>': '_',
            '|': '_', '+': '_', ' ': '_'
        }

        normalized = short_id
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)

        # Remove trailing underscores
        normalized = normalized.rstrip('_')

        # Search for output folder in project directory
        project_folder = ras_obj.project_folder

        # Try exact match with Short ID
        exact_match = project_folder / short_id
        if exact_match.exists() and exact_match.is_dir():
            logger.info(f"Found output folder (exact match): {exact_match}")
            return exact_match

        # Try normalized name
        normalized_match = project_folder / normalized
        if normalized_match.exists() and normalized_match.is_dir():
            logger.info(f"Found output folder (normalized): {normalized_match}")
            return normalized_match

        # Try partial match (contains)
        for item in project_folder.iterdir():
            if not item.is_dir():
                continue
            folder_name = item.name
            # Check if short_id is contained in folder name or vice versa
            if short_id in folder_name or folder_name in short_id:
                logger.info(f"Found output folder (partial match): {item}")
                return item
            # Check normalized version
            if normalized in folder_name or folder_name in normalized:
                logger.info(f"Found output folder (normalized partial match): {item}")
                return item

        # No folder found
        raise ValueError(
            f"Output folder not found for plan {plan_number} (Short ID: '{short_id}'). "
            f"Expected folder name: '{normalized}' in {project_folder}. "
            "Ensure the plan has been run and RASMapper has exported results."
        )

    @staticmethod
    @log_call
    def get_results_raster(
        plan_number: Union[str, int, float],
        variable_name: str,
        ras_object=None
    ) -> Path:
        """
        Get the .vrt file path for a specified plan and variable name.

        This function locates VRT (Virtual Raster) files exported by RASMapper
        for a specific hydraulic variable (e.g., WSE, Depth, Velocity).

        Args:
            plan_number (Union[str, int, float]): Plan number (accepts flexible formats).
            variable_name (str): Variable name to search for in VRT filenames (e.g., "WSE", "Depth", "Velocity").
            ras_object: Optional RAS object instance.

        Returns:
            Path: Path to the matching .vrt file.

        Raises:
            ValueError: If no matching files or multiple matching files are found.

        Examples:
            >>> vrt = RasMap.get_results_raster("01", "WSE")
            >>> vrt = RasMap.get_results_raster(1, "Depth")
            >>> vrt = RasMap.get_results_raster("08", "WSE (Max)", ras_object=my_project)

        Notes:
            - Uses get_results_folder() to locate the output directory
            - Searches for .vrt files containing the variable_name (case-insensitive)
            - If multiple files match, lists all matches and raises an error
            - User should make variable_name more specific to narrow results
            - VRT files are lightweight virtual rasters that reference underlying .tif tiles
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Get the mapping folder for this plan
        mapping_folder = RasMap.get_results_folder(plan_number, ras_obj)

        # List all .vrt files in the folder
        vrt_files = list(mapping_folder.glob("*.vrt"))

        if not vrt_files:
            raise ValueError(
                f"No .vrt files found in mapping folder: {mapping_folder}. "
                "Ensure RASMapper has exported raster results for this plan."
            )

        # Filter files containing variable_name (case-insensitive)
        matching_files = [
            f for f in vrt_files
            if variable_name.lower() in f.name.lower()
        ]

        # Handle results
        if len(matching_files) == 0:
            available_files = [f.name for f in vrt_files]
            raise ValueError(
                f"No .vrt files found matching variable name '{variable_name}' in {mapping_folder}. "
                f"Available files: {available_files}. "
                "Try making variable_name more specific or check for typos."
            )
        elif len(matching_files) == 1:
            logger.info(f"Found matching VRT file: {matching_files[0]}")
            return matching_files[0]
        else:
            # Multiple matches - print list and raise error
            logger.error(f"Multiple .vrt files match '{variable_name}':")
            for i, f in enumerate(matching_files, 1):
                logger.error(f"  {i}. {f.name}")

            raise ValueError(
                f"Multiple .vrt files ({len(matching_files)}) match variable name '{variable_name}'. "
                f"Matching files: {[f.name for f in matching_files]}. "
                "Please make variable_name more specific (e.g., 'WSE (Max)' instead of 'WSE')."
            )

    @staticmethod
    @log_call
    def set_water_surface_render_mode(
        mode: str = "horizontal",
        ras_object=None
    ) -> bool:
        """
        Set the water surface rendering mode in the RASMapper configuration file.

        This modifies the .rasmap file to change how RASMapper renders water surfaces
        when generating raster outputs. The setting affects stored map exports and
        on-screen display.

        Args:
            mode (str): Rendering mode. Options:
                - "horizontal": Constant water surface elevation per mesh cell.
                  Each cell displays a single, flat water surface. Faster rendering.
                - "sloped": Sloped water surface using cell corner elevations.
                  Water surface varies within each cell for smoother visualization.
                  Uses depth-weighted faces and reduces shallow areas to horizontal.
            ras_object: Optional RAS object instance.

        Returns:
            bool: True if successful, False otherwise.

        Raises:
            ValueError: If an invalid mode is specified.
            FileNotFoundError: If the .rasmap file doesn't exist.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project(r"C:/Projects/MyModel", "6.6")
            >>>
            >>> # Set horizontal mode (for validation against map_ras_results)
            >>> RasMap.set_water_surface_render_mode("horizontal")
            >>>
            >>> # Set sloped mode for smoother visualization
            >>> RasMap.set_water_surface_render_mode("sloped")

        Notes:
            - Changes take effect the next time RASMapper generates raster outputs
            - "horizontal" mode matches the `map_ras_results()` function output
            - "sloped" mode produces smoother but computationally different results
            - The original .rasmap file is modified in place (no backup created)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Validate mode
        mode = mode.lower()
        valid_modes = {"horizontal", "sloped"}
        if mode not in valid_modes:
            raise ValueError(
                f"Invalid mode '{mode}'. Valid options: {valid_modes}"
            )

        # Get rasmap path
        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            raise FileNotFoundError(f"RASMapper file not found: {rasmap_path}")

        try:
            # Parse the XML file
            tree = ET.parse(rasmap_path)
            root = tree.getroot()

            # Find or create RenderMode element
            render_mode_elem = root.find("RenderMode")
            if render_mode_elem is None:
                # Insert after Units element or at the end
                units_elem = root.find("Units")
                if units_elem is not None:
                    idx = list(root).index(units_elem) + 1
                    render_mode_elem = ET.Element("RenderMode")
                    root.insert(idx, render_mode_elem)
                else:
                    render_mode_elem = ET.SubElement(root, "RenderMode")

            # Find existing depth-weighted and reduce-shallow elements
            depth_weighted_elem = root.find("UseDepthWeightedFaces")
            reduce_shallow_elem = root.find("ReduceShallowToHorizontal")

            if mode == "horizontal":
                # Set horizontal mode
                render_mode_elem.text = "horizontal"

                # Remove sloped-specific elements if present
                if depth_weighted_elem is not None:
                    root.remove(depth_weighted_elem)
                if reduce_shallow_elem is not None:
                    root.remove(reduce_shallow_elem)

                logger.info("Set water surface render mode to 'horizontal'")

            elif mode == "sloped":
                # Set sloped mode
                render_mode_elem.text = "slopingPretty"

                # Add/update depth-weighted faces element
                if depth_weighted_elem is None:
                    idx = list(root).index(render_mode_elem) + 1
                    depth_weighted_elem = ET.Element("UseDepthWeightedFaces")
                    root.insert(idx, depth_weighted_elem)
                depth_weighted_elem.text = "true"

                # Add/update reduce-shallow element
                if reduce_shallow_elem is None:
                    idx = list(root).index(depth_weighted_elem) + 1
                    reduce_shallow_elem = ET.Element("ReduceShallowToHorizontal")
                    root.insert(idx, reduce_shallow_elem)
                reduce_shallow_elem.text = "true"

                logger.info("Set water surface render mode to 'sloped' (slopingPretty)")

            # Write the modified XML back
            tree.write(rasmap_path, encoding='utf-8', xml_declaration=True)
            logger.info(f"Updated RASMapper configuration: {rasmap_path}")

            return True

        except Exception as e:
            logger.error(f"Error setting water surface render mode: {e}")
            return False

    @staticmethod
    @log_call
    def get_water_surface_render_mode(ras_object=None) -> Optional[str]:
        """
        Get the current water surface rendering mode from the RASMapper configuration.

        Args:
            ras_object: Optional RAS object instance.

        Returns:
            Optional[str]: Current rendering mode:
                - "horizontal": Constant WSE per cell
                - "sloped": Sloped surface using cell corners
                - None: If .rasmap file not found or mode not set

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project(r"C:/Projects/MyModel", "6.6")
            >>> mode = RasMap.get_water_surface_render_mode()
            >>> print(f"Current mode: {mode}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return None

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()

            render_mode_elem = root.find("RenderMode")
            if render_mode_elem is None or render_mode_elem.text is None:
                return None

            mode_text = render_mode_elem.text.lower()

            if mode_text == "horizontal":
                return "horizontal"
            elif mode_text in ("slopingpretty", "sloping"):
                return "sloped"
            else:
                logger.warning(f"Unknown render mode in rasmap: {mode_text}")
                return mode_text

        except Exception as e:
            logger.error(f"Error reading water surface render mode: {e}")
            return None

    @staticmethod
    @log_call
    def map_ras_results(
        plan_number: Union[str, int, float],
        variables: Union[str, List[str]] = "WSE",
        terrain_path: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        interpolation_method: str = "horizontal",
        ras_object=None
    ) -> Dict[str, Path]:
        """
        Generate raster maps from HEC-RAS 2D mesh results.

        This function extracts mesh cell results from HDF files and rasterizes them
        to GeoTIFF format, clipped to the mesh cell boundaries to match RASMapper output.

        Args:
            plan_number (Union[str, int, float]): Plan number to generate maps for.
            variables (Union[str, List[str]]): Variable(s) to map. Options:
                - "WSE" or "Water Surface Elevation": Maximum water surface elevation
                - "Depth": Water depth (requires terrain_path)
                - "Velocity": Maximum cell velocity (averaged from face velocities)
                Defaults to "WSE".
            terrain_path (Optional[Union[str, Path]]): Path to terrain raster (TIF/VRT).
                Required for Depth calculation. Also used as template for output grid
                (resolution, extent, CRS). If None, attempts to detect from project.
            output_dir (Optional[Union[str, Path]]): Directory to save output rasters.
                Defaults to project folder / plan Short Identifier.
            interpolation_method (str): Interpolation method for water surface rendering.
                - "horizontal": Constant WSE per cell (default). Matches RASMapper's
                  "Horizontal" water surface rendering mode. Validated to 99.997%
                  pixel-level match with RASMapper output.
                - "sloped": Sloped surface using cell corner elevations. Uses planar
                  regression to compute vertex WSE from face values, then interpolates
                  using scipy griddata. Note: Current implementation is approximate
                  and may differ from RASMapper's exact algorithm.
            ras_object: Optional RAS object instance.

        Returns:
            Dict[str, Path]: Dictionary mapping variable names to output file paths.
                Example: {"WSE": Path("output/wse.tif"), "Depth": Path("output/depth.tif")}

        Raises:
            ValueError: If plan not found, no mesh results available, or Depth requested
                without terrain_path.
            FileNotFoundError: If terrain file not found.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project(r"C:/Projects/MyModel", "6.6")
            >>>
            >>> # Generate WSE raster only (uses horizontal interpolation by default)
            >>> outputs = RasMap.map_ras_results("01")
            >>>
            >>> # Generate WSE and Depth rasters
            >>> outputs = RasMap.map_ras_results(
            ...     plan_number="03",
            ...     variables=["WSE", "Depth"],
            ...     terrain_path="Terrain/Terrain.tif"
            ... )
            >>> print(outputs["WSE"])  # Path to WSE raster

        Notes:
            - Horizontal interpolation uses constant WSE per cell, matching RASMapper's
              "Horizontal" water surface rendering mode.
            - Output is clipped to mesh cell boundaries for 99.997% pixel-level match
              with RASMapper output.
            - Velocity is computed as the maximum of adjacent face velocities for each cell.
            - Perimeter cells are filled using nearest-neighbor from interior cells.
            - Sloped interpolation computes face and vertex WSE using hydraulic connectivity
              and planar regression, then interpolates to the grid using scipy griddata.
              This is an approximation of RASMapper's exact algorithm.
        """
        # Lazy imports for heavy dependencies
        import geopandas as gpd
        from shapely.ops import unary_union
        from scipy.spatial import cKDTree

        try:
            import rasterio
            from rasterio.features import rasterize
            from rasterio.warp import reproject
            from rasterio.enums import Resampling
        except ImportError:
            raise ImportError(
                "rasterio is required for map_ras_results. "
                "Install with: pip install rasterio"
            )

        from .hdf.HdfMesh import HdfMesh
        from .hdf.HdfResultsMesh import HdfResultsMesh

        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Validate interpolation method
        interpolation_method = interpolation_method.lower()
        if interpolation_method not in ("horizontal", "sloped"):
            raise ValueError(
                f"Unknown interpolation_method '{interpolation_method}'. "
                "Valid options: 'horizontal', 'sloped'."
            )

        # Normalize inputs
        plan_number = RasUtils.normalize_ras_number(plan_number)
        if isinstance(variables, str):
            variables = [variables]

        # Normalize variable names
        var_mapping = {
            "WSE": "WSE",
            "WSEL": "WSE",
            "Water Surface Elevation": "WSE",
            "water surface elevation": "WSE",
            "Depth": "Depth",
            "depth": "Depth",
            "Velocity": "Velocity",
            "velocity": "Velocity",
        }
        variables = [var_mapping.get(v, v) for v in variables]

        # Validate variables
        valid_vars = {"WSE", "Depth", "Velocity"}
        for v in variables:
            if v not in valid_vars:
                raise ValueError(
                    f"Unknown variable '{v}'. Valid options: {valid_vars}"
                )

        # Get plan info
        plan_df = ras_obj.plan_df
        plan_info = plan_df[plan_df['plan_number'] == plan_number]
        if plan_info.empty:
            raise ValueError(f"Plan {plan_number} not found in project.")
        plan_row = plan_info.iloc[0]

        # Resolve HDF paths
        plan_hdf = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}.hdf"
        if not plan_hdf.exists():
            hdf_path = plan_row.get('HDF_Results_Path')
            if hdf_path and Path(hdf_path).exists():
                plan_hdf = Path(hdf_path)
            else:
                raise FileNotFoundError(f"Plan HDF not found: {plan_hdf}")

        geom_file = plan_row.get('Geom File', '')
        geom_hdf = ras_obj.project_folder / f"{ras_obj.project_name}.g{geom_file}.hdf"
        if not geom_hdf.exists():
            geom_path = plan_row.get('Geom Path', '')
            if geom_path:
                candidate = Path(geom_path)
                if candidate.suffix.lower() != '.hdf':
                    candidate = candidate.with_suffix('.hdf')
                if candidate.exists():
                    geom_hdf = candidate
        if not geom_hdf.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_hdf}")

        # Resolve terrain path
        if terrain_path is not None:
            terrain_path = Path(terrain_path)
            if not terrain_path.is_absolute():
                terrain_path = ras_obj.project_folder / terrain_path
            if not terrain_path.exists():
                raise FileNotFoundError(f"Terrain file not found: {terrain_path}")
        elif "Depth" in variables:
            # Try to detect terrain from rasmap
            terrain_path = RasMap._detect_terrain_path(ras_obj)
            if terrain_path is None:
                raise ValueError(
                    "terrain_path is required for Depth calculation. "
                    "Provide terrain_path parameter or ensure terrain is configured in .rasmap file."
                )

        # Setup output directory
        if output_dir is None:
            short_id = plan_row.get('Short Identifier', f'Plan_{plan_number}')
            if pd.isna(short_id) or not short_id:
                short_id = f'Plan_{plan_number}'
            output_dir = ras_obj.project_folder / short_id
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load mesh geometry
        logger.info(f"Loading mesh geometry from {geom_hdf}")
        cell_polygons = HdfMesh.get_mesh_cell_polygons(geom_hdf)
        if cell_polygons.empty:
            raise ValueError("No mesh cell polygons found in geometry HDF.")

        # Load mesh results
        logger.info(f"Loading mesh results from {plan_hdf}")
        max_ws_df = HdfResultsMesh.get_mesh_max_ws(plan_hdf)
        if max_ws_df.empty:
            raise ValueError("No maximum water surface results found in plan HDF.")

        # Propagate perimeter values
        RasMap._propagate_perimeter_values(max_ws_df, "maximum_water_surface")

        # Merge geometry with results
        mesh_gdf = cell_polygons.merge(
            max_ws_df[["mesh_name", "cell_id", "maximum_water_surface"]],
            on=["mesh_name", "cell_id"],
            how="left"
        )
        mesh_gdf = mesh_gdf.dropna(subset=["maximum_water_surface"])

        if mesh_gdf.empty:
            raise ValueError("No valid mesh results after merging geometry and results.")

        # Get raster grid from terrain
        if terrain_path:
            with rasterio.open(terrain_path) as src:
                grid_transform = src.transform
                grid_width = src.width
                grid_height = src.height
                grid_crs = src.crs
                grid_nodata = -9999.0
                terrain_data = src.read(1)
                terrain_nodata = src.nodata
        else:
            # Use mesh bounds to create grid
            bounds = mesh_gdf.total_bounds
            resolution = 20.0  # Default 20-foot cells
            grid_width = int((bounds[2] - bounds[0]) / resolution) + 1
            grid_height = int((bounds[3] - bounds[1]) / resolution) + 1
            grid_transform = rasterio.transform.from_bounds(
                bounds[0], bounds[1], bounds[2], bounds[3], grid_width, grid_height
            )
            grid_crs = mesh_gdf.crs
            grid_nodata = -9999.0
            terrain_data = None
            terrain_nodata = None

        # Create mesh boundary mask for clipping
        logger.info("Creating mesh boundary mask for clipping")
        mesh_union = unary_union(mesh_gdf.geometry.tolist())
        clip_mask = rasterize(
            [(mesh_union, 1)],
            out_shape=(grid_height, grid_width),
            transform=grid_transform,
            fill=0,
            dtype='uint8',
            all_touched=False
        )

        # Reproject mesh if needed
        if grid_crs and mesh_gdf.crs and mesh_gdf.crs != grid_crs:
            mesh_gdf = mesh_gdf.to_crs(grid_crs)

        # Generate output rasters
        outputs = {}

        for variable in variables:
            logger.info(f"Generating {variable} raster")

            if variable == "WSE":
                if interpolation_method == "sloped":
                    # Use sloped interpolation (cell corners)
                    from .mapping import compute_sloped_wse_arrays, rasterize_sloped_wse, NODATA as MAPPING_NODATA

                    logger.info("Using sloped (cell corners) interpolation")

                    # Get topology and compute sloped values
                    topology = HdfMesh.get_mesh_sloped_topology(plan_hdf)
                    if not topology:
                        raise ValueError("Could not extract mesh topology for sloped interpolation")

                    # Build cell_wse array indexed by cell_id (not filtered mesh_gdf indices)
                    n_cells = topology['n_cells']
                    cell_wse_full = np.full(n_cells, MAPPING_NODATA, dtype=np.float32)

                    # Fill in values from max_ws_df which has cell_id
                    for _, row in max_ws_df.iterrows():
                        cell_id = int(row['cell_id'])
                        wse_val = row['maximum_water_surface']
                        if cell_id < n_cells and not np.isnan(wse_val):
                            cell_wse_full[cell_id] = wse_val

                    # Compute face and vertex WSE
                    face_wse_a, face_wse_b, vertex_wse, face_midsides = compute_sloped_wse_arrays(
                        topology, cell_wse_full
                    )

                    # Rasterize using griddata interpolation
                    raster_data = rasterize_sloped_wse(
                        topology=topology,
                        cell_wse=cell_wse_full,
                        vertex_wse=vertex_wse,
                        transform=grid_transform,
                        shape=(grid_height, grid_width),
                        terrain=terrain_data if terrain_data is not None else None,
                    )

                    # Convert NODATA to NaN for consistency
                    raster_data = np.where(raster_data == MAPPING_NODATA, np.nan, raster_data)

                else:
                    # Use horizontal interpolation (constant WSE per cell)
                    shapes = [
                        (geom, float(val))
                        for geom, val in zip(mesh_gdf.geometry, mesh_gdf["maximum_water_surface"])
                        if geom is not None and not np.isnan(val)
                    ]
                    raster_data = rasterize(
                        shapes=shapes,
                        out_shape=(grid_height, grid_width),
                        transform=grid_transform,
                        fill=np.nan,
                        dtype='float32',
                        all_touched=False
                    )

                    # Filter to wet cells only (depth > 0) to match RASMapper output
                    if terrain_data is not None:
                        depth_check = raster_data - terrain_data.astype('float32')
                        if terrain_nodata is not None:
                            depth_check[terrain_data == terrain_nodata] = np.nan
                        # Set dry cells (depth <= 0) to nodata
                        raster_data = np.where(depth_check > 0, raster_data, np.nan)

            elif variable == "Depth":
                # First get WSE raster
                shapes = [
                    (geom, float(val))
                    for geom, val in zip(mesh_gdf.geometry, mesh_gdf["maximum_water_surface"])
                    if geom is not None and not np.isnan(val)
                ]
                wse_raster = rasterize(
                    shapes=shapes,
                    out_shape=(grid_height, grid_width),
                    transform=grid_transform,
                    fill=np.nan,
                    dtype='float32',
                    all_touched=False
                )

                # Reproject terrain if needed
                if terrain_data is not None:
                    with rasterio.open(terrain_path) as src:
                        if src.crs != grid_crs or src.transform != grid_transform:
                            terrain_reproj = np.full((grid_height, grid_width), np.nan, dtype='float32')
                            reproject(
                                source=terrain_data,
                                destination=terrain_reproj,
                                src_transform=src.transform,
                                src_crs=src.crs,
                                dst_transform=grid_transform,
                                dst_crs=grid_crs,
                                dst_nodata=np.nan,
                                resampling=Resampling.bilinear
                            )
                            terrain_data = terrain_reproj
                        else:
                            terrain_data = terrain_data.astype('float32')
                            if terrain_nodata is not None:
                                terrain_data[terrain_data == terrain_nodata] = np.nan

                # Calculate depth and filter to wet cells only (depth > 0)
                raster_data = wse_raster - terrain_data
                raster_data[np.isnan(wse_raster) | np.isnan(terrain_data)] = np.nan
                # Set dry cells (depth <= 0) to nodata to match RASMapper output
                raster_data = np.where(raster_data > 0, raster_data, np.nan)

            elif variable == "Velocity":
                # Get face velocities and aggregate to cells
                try:
                    face_v_df = HdfResultsMesh.get_mesh_max_face_v(plan_hdf)
                    if face_v_df.empty:
                        logger.warning("No face velocity data found, skipping Velocity")
                        continue

                    # Aggregate face velocities to cells (use maximum)
                    cell_velocities = RasMap._aggregate_face_velocity_to_cells(
                        geom_hdf, face_v_df, mesh_gdf
                    )

                    shapes = [
                        (geom, float(val))
                        for geom, val in zip(cell_velocities.geometry, cell_velocities["velocity"])
                        if geom is not None and not np.isnan(val)
                    ]
                    raster_data = rasterize(
                        shapes=shapes,
                        out_shape=(grid_height, grid_width),
                        transform=grid_transform,
                        fill=np.nan,
                        dtype='float32',
                        all_touched=False
                    )

                    # Filter to wet cells only (depth > 0) to match RASMapper output
                    if terrain_data is not None:
                        # Need WSE to compute depth for filtering
                        wse_shapes = [
                            (geom, float(val))
                            for geom, val in zip(mesh_gdf.geometry, mesh_gdf["maximum_water_surface"])
                            if geom is not None and not np.isnan(val)
                        ]
                        wse_for_filter = rasterize(
                            shapes=wse_shapes,
                            out_shape=(grid_height, grid_width),
                            transform=grid_transform,
                            fill=np.nan,
                            dtype='float32',
                            all_touched=False
                        )
                        depth_check = wse_for_filter - terrain_data.astype('float32')
                        if terrain_nodata is not None:
                            depth_check[terrain_data == terrain_nodata] = np.nan
                        # Set dry cells (depth <= 0) to nodata
                        raster_data = np.where(depth_check > 0, raster_data, np.nan)

                except Exception as e:
                    logger.error(f"Error generating velocity raster: {e}")
                    continue

            # Apply mesh boundary clipping
            raster_data = np.where(clip_mask == 1, raster_data, np.nan)

            # Write output
            output_path = output_dir / f"{variable.lower()}_max.tif"
            RasMap._write_geotiff(
                output_path, raster_data, grid_transform, grid_crs, grid_nodata
            )
            outputs[variable] = output_path
            logger.info(f"Wrote {variable} raster to {output_path}")

        return outputs

    @staticmethod
    @log_call
    def scan_results_folders(ras_folder: Path) -> Dict[str, Dict]:
        """
        Scan RAS project folder for results folders containing raster files.

        Args:
            ras_folder: Path to HEC-RAS project folder containing .prj file

        Returns:
            Dictionary mapping folder names to folder information:
            {folder_name: {'path': Path, 'has_vrt': bool, 'has_tif': bool}}

        Examples:
            >>> folders = RasMap.scan_results_folders(Path("/path/to/project"))
            >>> for name, info in folders.items():
            ...     print(f"{name}: {info['path']}")
        """
        results = {}
        for folder in ras_folder.iterdir():
            if folder.is_dir() and not folder.name.startswith('.'):
                # Check for raster files
                tif_files = list(folder.glob('*.tif'))
                vrt_files = list(folder.glob('*.vrt'))

                if tif_files or vrt_files:
                    results[folder.name] = {
                        'path': folder,
                        'has_vrt': len(vrt_files) > 0,
                        'has_tif': len(tif_files) > 0
                    }
                    logger.debug(f"Found results folder: {folder.name} "
                               f"(VRT: {len(vrt_files)}, TIF: {len(tif_files)})")
        return results

    @staticmethod
    @log_call
    def find_results_folder(ras_folder: Path, short_id: str) -> Optional[Path]:
        """
        Find results folder for a plan Short ID.

        Args:
            ras_folder: Path to HEC-RAS project folder
            short_id: Plan Short Identifier (from plan file)

        Returns:
            Path to results folder, or None if not found

        Examples:
            >>> folder = RasMap.find_results_folder(Path("/path/to/project"), "H100_CP")
        """
        # Normalize Short ID to match Windows folder naming
        # RASMapper replaces special characters for Windows compatibility
        replacements = {
            '/': '_', '\\': '_', ':': '_', '*': '_',
            '?': '_', '"': '_', '<': '_', '>': '_',
            '|': '_', '+': '_', ' ': '_'
        }

        normalized = short_id
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)

        # Remove trailing underscores
        normalized = normalized.rstrip('_')

        # Scan for folders
        folders = RasMap.scan_results_folders(ras_folder)

        # Try exact match
        if short_id in folders:
            return folders[short_id]['path']

        # Try normalized name
        if normalized in folders:
            return folders[normalized]['path']

        # Try partial match
        for folder_name, folder_info in folders.items():
            # Check if short_id is contained in folder name or vice versa
            if short_id in folder_name or folder_name in short_id:
                return folder_info['path']
            # Check normalized version
            if normalized in folder_name or folder_name in normalized:
                return folder_info['path']

        return None

    @staticmethod
    @log_call
    def resolve_raster_paths(results_folder: Path) -> Dict[str, Optional[Path]]:
        """
        Resolve WSE and Depth raster paths from results folder.

        Priority order:
        1. Unsteady flow VRT files (e.g., "Depth (Max).vrt")
        2. Steady flow VRT files (e.g., "Depth.vrt")
        3. Unsteady flow TIF files (e.g., "Depth (Max).tif")
        4. Steady flow TIF files (e.g., "Depth.tif")

        Args:
            results_folder: Path to RASMapper results folder

        Returns:
            Dictionary with 'wse' and 'depth' paths (or None if not found)

        Examples:
            >>> rasters = RasMap.resolve_raster_paths(Path("/path/to/project/H100_CP"))
            >>> wse_path = rasters['wse']
            >>> depth_path = rasters['depth']
        """
        result = {'wse': None, 'depth': None}

        # Priority 1: Look for unsteady flow VRT files (with "max")
        for vrt_file in results_folder.glob('*.vrt'):
            name_lower = vrt_file.name.lower()
            if 'depth' in name_lower and 'max' in name_lower:
                result['depth'] = vrt_file
                logger.debug(f"Found unsteady depth VRT: {vrt_file.name}")
            elif 'wse' in name_lower and 'max' in name_lower:
                result['wse'] = vrt_file
                logger.debug(f"Found unsteady WSE VRT: {vrt_file.name}")

        # Priority 2: Look for steady flow VRT files (without "max") - only if not already found
        if not result['depth'] or not result['wse']:
            for vrt_file in results_folder.glob('*.vrt'):
                name_lower = vrt_file.name.lower()
                name_base = vrt_file.stem.lower()

                # Match depth files - steady flow patterns
                if not result['depth'] and 'depth' in name_lower and 'max' not in name_lower:
                    if (name_base == 'depth' or
                        name_base.startswith('depth (') or
                        name_base.startswith('depth ') or
                        name_base.startswith('depth_grid')):
                        result['depth'] = vrt_file
                        logger.debug(f"Found steady depth VRT: {vrt_file.name}")

                # Match WSE files - steady flow patterns
                elif not result['wse'] and 'wse' in name_lower and 'max' not in name_lower:
                    if (name_base == 'wse' or
                        name_base.startswith('wse (') or
                        name_base.startswith('wse ') or
                        name_base.startswith('wse_grid')):
                        result['wse'] = vrt_file
                        logger.debug(f"Found steady WSE VRT: {vrt_file.name}")

        # Priority 3: Fall back to unsteady flow TIF files if no VRT found
        if not result['depth'] or not result['wse']:
            for tif_file in results_folder.glob('*.tif'):
                name_lower = tif_file.name.lower()
                if not result['depth'] and 'depth' in name_lower and 'max' in name_lower:
                    result['depth'] = tif_file
                    logger.debug(f"Found unsteady depth TIF: {tif_file.name}")
                elif not result['wse'] and 'wse' in name_lower and 'max' in name_lower:
                    result['wse'] = tif_file
                    logger.debug(f"Found unsteady WSE TIF: {tif_file.name}")

        # Priority 4: Fall back to steady flow TIF files if still not found
        if not result['depth'] or not result['wse']:
            for tif_file in results_folder.glob('*.tif'):
                name_lower = tif_file.name.lower()
                name_base = tif_file.stem.lower()

                # Match depth TIF files - steady flow patterns
                if not result['depth'] and 'depth' in name_lower and 'max' not in name_lower:
                    if (name_base == 'depth' or
                        name_base.startswith('depth (') or
                        name_base.startswith('depth ') or
                        name_base.startswith('depth_grid')):
                        result['depth'] = tif_file
                        logger.debug(f"Found steady depth TIF: {tif_file.name}")

                # Match WSE TIF files - steady flow patterns
                elif not result['wse'] and 'wse' in name_lower and 'max' not in name_lower:
                    if (name_base == 'wse' or
                        name_base.startswith('wse (') or
                        name_base.startswith('wse ') or
                        name_base.startswith('wse_grid')):
                        result['wse'] = tif_file
                        logger.debug(f"Found steady WSE TIF: {tif_file.name}")

        # Log detected model type
        if result['depth'] or result['wse']:
            depth_path = str(result.get('depth', '')).lower()
            wse_path = str(result.get('wse', '')).lower()
            if 'max' in depth_path or 'max' in wse_path:
                logger.info(f"Detected unsteady flow model in {results_folder.name}")
            else:
                logger.info(f"Detected steady flow model in {results_folder.name}")

        return result

    @staticmethod
    @log_call
    def find_steady_raster(results_folder: Path, profile_name: str, raster_type: str) -> Optional[Path]:
        """
        Find steady state raster for a specific profile.

        Args:
            results_folder: Path to RASMapper results folder
            profile_name: Profile name (e.g., "1Pct", "10Pct", "50Pct")
            raster_type: Type of raster ('WSE' or 'Depth')

        Returns:
            Path to raster file, or None if not found

        Examples:
            >>> raster = RasMap.find_steady_raster(Path("/path/to/project/H100_CP"), "10Pct", "WSE")
        """
        # Search patterns for steady state profile-specific rasters
        # Pattern 1: Standard format with parentheses "WSE (1Pct).vrt"
        pattern1 = f"{raster_type} ({profile_name}).vrt"
        vrt_path = results_folder / pattern1
        if vrt_path.exists():
            logger.debug(f"Found steady raster (pattern 1): {vrt_path.name}")
            return vrt_path

        # Pattern 2: Terrain-specific variant "WSE (1Pct).Terrain.{terrain_name}.tif"
        pattern2 = f"{raster_type} ({profile_name}).Terrain.*.tif"
        tif_files = list(results_folder.glob(pattern2))
        if tif_files:
            logger.debug(f"Found steady raster (pattern 2): {tif_files[0].name}")
            return tif_files[0]

        # Pattern 3: Underscore format "WSE_1Pct.vrt"
        pattern3 = f"{raster_type}_{profile_name}.vrt"
        alt_vrt = results_folder / pattern3
        if alt_vrt.exists():
            logger.debug(f"Found steady raster (pattern 3): {alt_vrt.name}")
            return alt_vrt

        # Pattern 4: Space instead of underscore "WSE 1Pct.vrt"
        pattern4 = f"{raster_type} {profile_name}.vrt"
        space_vrt = results_folder / pattern4
        if space_vrt.exists():
            logger.debug(f"Found steady raster (pattern 4): {space_vrt.name}")
            return space_vrt

        # Pattern 5: TIF variant without terrain suffix
        pattern5 = f"{raster_type} ({profile_name}).tif"
        tif_path = results_folder / pattern5
        if tif_path.exists():
            logger.debug(f"Found steady raster (pattern 5): {tif_path.name}")
            return tif_path

        logger.warning(
            f"Could not find steady state raster for profile '{profile_name}', type {raster_type}. "
            f"Searched in: {results_folder}"
        )
        return None

    @staticmethod
    def _detect_terrain_path(ras_obj) -> Optional[Path]:
        """Attempt to detect terrain raster path from project."""
        if hasattr(ras_obj, 'rasmap_df') and ras_obj.rasmap_df is not None:
            if not ras_obj.rasmap_df.empty:
                terrain_list = ras_obj.rasmap_df.get('terrain_hdf_path', [[]])
                if len(terrain_list) > 0:
                    terrain_paths = terrain_list.iloc[0]
                    for item in terrain_paths:
                        base = Path(item)
                        # Try VRT/TIF versions of terrain HDF
                        for ext in ['.vrt', '.tif']:
                            candidate = base.with_suffix(ext)
                            if candidate.exists():
                                return candidate

        # Try common terrain folder locations
        terrain_folder = ras_obj.project_folder / "Terrain"
        if terrain_folder.exists():
            for pattern in ['*.vrt', '*.tif']:
                matches = list(terrain_folder.glob(pattern))
                if matches:
                    return matches[0]

        return None

    @staticmethod
    def _propagate_perimeter_values(gdf: 'GeoDataFrame', value_column: str) -> None:
        """Fill perimeter cell values from nearest interior cells."""
        if "mesh_name" not in gdf.columns or value_column not in gdf.columns:
            return

        mask = gdf["mesh_name"].astype(str).str.contains("Perimeter", case=False, na=False)
        if not mask.any():
            return

        interior = gdf.loc[~mask]
        if interior.empty:
            return

        perim = gdf.loc[mask]

        # Get coordinates
        def get_coords(geom_series):
            if geom_series.empty:
                return np.empty((0, 2))
            sample = geom_series.iloc[0]
            geom_type = getattr(sample, "geom_type", "").lower()
            if geom_type == "point":
                xs = geom_series.x.to_numpy()
                ys = geom_series.y.to_numpy()
            else:
                centroids = geom_series.centroid
                xs = centroids.x.to_numpy()
                ys = centroids.y.to_numpy()
            return np.column_stack([xs, ys])

        interior_coords = get_coords(interior.geometry)
        perim_coords = get_coords(perim.geometry)

        if interior_coords.size == 0 or perim_coords.size == 0:
            return

        from scipy.spatial import cKDTree
        tree = cKDTree(interior_coords)
        _, idx = tree.query(perim_coords)
        gdf.loc[mask, value_column] = interior.iloc[idx][value_column].to_numpy()

    @staticmethod
    def _aggregate_face_velocity_to_cells(
        geom_hdf: Path,
        face_v_df: 'GeoDataFrame',
        mesh_gdf: 'GeoDataFrame'
    ) -> 'GeoDataFrame':
        """Aggregate face velocities to cell velocities using maximum."""
        import h5py
        import geopandas as gpd

        cell_velocities = []

        with h5py.File(geom_hdf, 'r') as hdf:
            for mesh_name in mesh_gdf['mesh_name'].unique():
                try:
                    # Get cell-face mapping
                    cell_face_info = hdf[f"Geometry/2D Flow Areas/{mesh_name}/Cells Face and Orientation Info"][()]
                    cell_face_values = hdf[f"Geometry/2D Flow Areas/{mesh_name}/Cells Face and Orientation Values"][()][:, 0]

                    # Get face velocities for this mesh
                    mesh_face_v = face_v_df[face_v_df['mesh_name'] == mesh_name]
                    if mesh_face_v.empty:
                        continue

                    face_v_dict = dict(zip(mesh_face_v['face_id'], mesh_face_v['maximum_face_velocity']))

                    # Get cells for this mesh
                    mesh_cells = mesh_gdf[mesh_gdf['mesh_name'] == mesh_name]

                    for _, cell_row in mesh_cells.iterrows():
                        cell_id = cell_row['cell_id']
                        if cell_id >= len(cell_face_info):
                            continue

                        start, length = cell_face_info[cell_id, :2]
                        face_ids = cell_face_values[start:start + length]

                        # Get max velocity from adjacent faces
                        face_vels = [face_v_dict.get(fid, 0) for fid in face_ids]
                        max_vel = max(face_vels) if face_vels else 0

                        cell_velocities.append({
                            'mesh_name': mesh_name,
                            'cell_id': cell_id,
                            'velocity': max_vel,
                            'geometry': cell_row['geometry']
                        })

                except Exception as e:
                    logger.warning(f"Error processing velocity for mesh {mesh_name}: {e}")
                    continue

        if not cell_velocities:
            return gpd.GeoDataFrame()

        return gpd.GeoDataFrame(cell_velocities, crs=mesh_gdf.crs)

    @staticmethod
    def _write_geotiff(
        path: Path,
        array: np.ndarray,
        transform,
        crs,
        nodata: float
    ) -> None:
        """Write array to GeoTIFF file."""
        import rasterio

        profile = {
            "driver": "GTiff",
            "height": array.shape[0],
            "width": array.shape[1],
            "count": 1,
            "dtype": rasterio.float32,
            "crs": crs,
            "transform": transform,
            "nodata": nodata,
            "compress": "lzw",
        }

        data = np.where(np.isnan(array), nodata, array).astype(np.float32)
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(data, 1)