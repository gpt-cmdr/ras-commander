"""
RasProcess - Wrapper for RasProcess.exe CLI automation

This module provides functionality to automate HEC-RAS mapping operations through
the undocumented RasProcess.exe command-line interface. It enables headless
generation of stored maps, preprocessing, and other RASMapper operations.

Key Features:
- Generate stored maps (WSE, Depth, Velocity, etc.) without GUI
- Support for Max/Min profiles and specific timesteps
- Automatic .rasmap modification for stored map configuration
- Georeferencing fix for StoreMap command bug

Classes:
    RasProcess: Static class for RasProcess.exe CLI operations

Note:
    RasProcess.exe is an undocumented CLI tool bundled with HEC-RAS that exposes
    RASMapper automation functionality. See rasmapper_docs/16_rasprocess_cli_reference.md
    for complete documentation.
"""

import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Union, Optional, List, Dict, Any
from datetime import datetime
import shutil

from .RasPrj import ras
from .RasMap import RasMap
from .RasUtils import RasUtils
from .LoggingConfig import get_logger
from .Decorators import log_call

# Optional rasterio for georeferencing fix
try:
    import rasterio
    from rasterio.crs import CRS
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

logger = get_logger(__name__)


class RasProcess:
    """
    Static class for automating HEC-RAS operations via RasProcess.exe CLI.

    This class provides methods to:
    - Find RasProcess.exe in standard installation paths
    - Generate stored maps using StoreAllMaps command
    - Configure stored maps in .rasmap files
    - Fix georeferencing issues in generated TIFs

    All methods are static and follow the ras-commander pattern of accepting
    an optional ras_object parameter for multi-project support.

    Example:
        >>> from ras_commander import init_ras_project, RasProcess
        >>> init_ras_project("path/to/project", "6.6")
        >>> results = RasProcess.store_maps(
        ...     plan_number="01",
        ...     output_folder="Maps",
        ...     wse=True,
        ...     depth=True,
        ...     velocity=True
        ... )
    """

    # Map type definitions: (xml_name, display_name, needs_profile)
    MAP_TYPES = {
        'wse': ('elevation', 'WSE', True),
        'depth': ('depth', 'Depth', True),
        'velocity': ('velocity', 'Velocity', True),
        'froude': ('froude', 'Froude', True),
        'shear_stress': ('Shear', 'Shear Stress', True),
        'depth_x_velocity': ('depth and velocity', 'D * V', True),
        'depth_x_velocity_sq': ('depth and velocity squared', 'D * V^2', True),
        'flow': ('flow', 'Flow', True),
        'arrival_time': ('arrivaltime', 'Arrival Time', False),
        'duration': ('duration', 'Duration', False),
        'recession': ('recession', 'Recession', False),
    }

    # Standard HEC-RAS installation paths
    RAS_INSTALL_PATHS = [
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.6",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.5",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.4.1",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.4",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.3.1",
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.3",
        r"C:\Program Files\HEC\HEC-RAS\6.6",
        r"C:\Program Files\HEC\HEC-RAS\6.5",
    ]

    @staticmethod
    @log_call
    def find_rasprocess(ras_version: str = None) -> Optional[Path]:
        """
        Find RasProcess.exe in standard HEC-RAS installation paths.

        Args:
            ras_version: Optional specific version to look for (e.g., "6.6").
                        If None, searches all known paths.

        Returns:
            Path to RasProcess.exe if found, None otherwise.
        """
        if ras_version:
            # Look for specific version
            paths = [
                Path(f"C:/Program Files (x86)/HEC/HEC-RAS/{ras_version}/RasProcess.exe"),
                Path(f"C:/Program Files/HEC/HEC-RAS/{ras_version}/RasProcess.exe"),
            ]
        else:
            paths = [Path(p) / "RasProcess.exe" for p in RasProcess.RAS_INSTALL_PATHS]

        for path in paths:
            if path.exists():
                logger.debug(f"Found RasProcess.exe at: {path}")
                return path

        logger.warning("RasProcess.exe not found in standard installation paths")
        return None

    @staticmethod
    @log_call
    def get_plan_timestamps(
        plan_number: str,
        ras_object=None
    ) -> List[str]:
        """
        Get available output timestamps for a plan in RASMapper format.

        Args:
            plan_number: Plan number (e.g., "01", "06")
            ras_object: Optional RAS object instance

        Returns:
            List of timestamp strings in format "DDMMMYYYY HH:MM:SS" (e.g., "10SEP2018 02:30:00")
        """
        from .hdf.HdfPlan import HdfPlan

        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Get HDF path for plan
        plan_num = RasUtils.normalize_ras_number(plan_number)
        hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_num}.hdf"

        if not hdf_path.exists():
            logger.error(f"Plan HDF not found: {hdf_path}")
            return []

        try:
            timestamps = HdfPlan.get_plan_timestamps_list(hdf_path)
            # Convert to RASMapper format: "DDMMMYYYY HH:MM:SS"
            rasmap_timestamps = []
            for ts in timestamps:
                # Format: 10SEP2018 02:30:00
                formatted = ts.strftime("%d%b%Y %H:%M:%S").upper()
                rasmap_timestamps.append(formatted)
            return rasmap_timestamps
        except Exception as e:
            logger.error(f"Failed to get timestamps from {hdf_path}: {e}")
            return []

    @staticmethod
    @log_call
    def _get_projection_info(rasmap_path: Path) -> tuple:
        """
        Extract projection file path and terrain path from .rasmap XML.

        Args:
            rasmap_path: Path to .rasmap file

        Returns:
            Tuple of (prj_path, terrain_tif_path) or (None, None) if not found
        """
        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()

            # Get projection file
            prj_path = None
            proj_elem = root.find(".//RASProjectionFilename")
            if proj_elem is not None:
                filename = proj_elem.get("Filename")
                if filename:
                    prj_path = rasmap_path.parent / filename.replace(".\\", "").replace("./", "")
                    if not prj_path.exists():
                        prj_path = None

            # Get terrain TIF
            terrain_path = None
            for layer in root.findall(".//Terrains/Layer"):
                filename = layer.get("Filename")
                if filename:
                    terrain_hdf = rasmap_path.parent / filename.replace(".\\", "").replace("./", "")
                    if terrain_hdf.exists():
                        # Look for .tif in same folder
                        terrain_dir = terrain_hdf.parent
                        for tif in terrain_dir.glob("*.tif"):
                            terrain_path = tif
                            break
                    break

            return prj_path, terrain_path

        except Exception as e:
            logger.error(f"Failed to parse rasmap for projection info: {e}")
            return None, None

    @staticmethod
    @log_call
    def _fix_georeferencing(
        tif_path: Path,
        prj_path: Path,
        terrain_path: Path
    ) -> bool:
        """
        Apply georeferencing to TIF from projection and terrain files.

        Args:
            tif_path: Path to TIF file to fix
            prj_path: Path to .prj file with CRS
            terrain_path: Path to terrain TIF with transform

        Returns:
            True if fix was applied, False otherwise
        """
        if not HAS_RASTERIO:
            logger.warning(f"Skipping georef fix for {tif_path} (rasterio not installed)")
            return False

        try:
            # Read CRS from .prj
            with open(prj_path, 'r') as f:
                wkt = f.read()
            crs = CRS.from_wkt(wkt)

            # Get transform from terrain
            with rasterio.open(terrain_path) as terrain:
                transform = terrain.transform

            # Read generated data
            with rasterio.open(tif_path) as src:
                data = src.read(1)
                nodata = src.nodata
                profile = src.profile.copy()

            # Update profile with correct georeferencing
            profile.update(crs=crs, transform=transform)

            # Write back
            with rasterio.open(tif_path, 'w', **profile) as dst:
                dst.write(data, 1)

            logger.info(f"Fixed georeferencing: {tif_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to fix georeferencing for {tif_path}: {e}")
            return False

    @staticmethod
    def _get_plan_short_id(hdf_path: Path) -> Optional[str]:
        """
        Get the Plan ShortID from an HDF file.

        RasProcess.exe uses this to determine the output folder name.

        Args:
            hdf_path: Path to plan HDF file

        Returns:
            Plan ShortID string, or None if not found
        """
        try:
            import h5py
            with h5py.File(hdf_path, 'r') as hdf:
                if 'Plan Data' in hdf and 'Plan Information' in hdf['Plan Data']:
                    info = hdf['Plan Data']['Plan Information']
                    if 'Plan ShortID' in info.attrs:
                        short_id = info.attrs['Plan ShortID']
                        if isinstance(short_id, bytes):
                            short_id = short_id.decode('utf-8')
                        return short_id.strip()
        except Exception as e:
            logger.debug(f"Could not read Plan ShortID from {hdf_path}: {e}")
        return None

    @staticmethod
    @log_call
    def _add_stored_map_to_rasmap(
        rasmap_path: Path,
        plan_hdf_filename: str,
        map_type: str,
        profile_name: str,
        output_folder: str,
        profile_index: int = 2147483647
    ) -> bool:
        """
        Add a stored map configuration to the .rasmap file.

        If the Results element or plan layer doesn't exist, they will be created.

        Args:
            rasmap_path: Path to .rasmap file
            plan_hdf_filename: HDF filename (e.g., "Project.p01.hdf")
            map_type: Map type XML name (e.g., "elevation", "depth")
            profile_name: Profile name (e.g., "Max", "10SEP2018 02:30:00")
            output_folder: Output folder name relative to project
            profile_index: Profile index (2147483647 for Max/Min)

        Returns:
            True if successful, False otherwise
        """
        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()

            # Find or create the Results element
            results_elem = root.find(".//Results")
            if results_elem is None:
                # Create Results element - insert after Geometries if present
                results_elem = ET.Element("Results")
                results_elem.set("Checked", "True")
                results_elem.set("Expanded", "True")

                # Find insertion point (after Geometries or at end)
                geom_elem = root.find(".//Geometries")
                if geom_elem is not None:
                    # Insert after Geometries
                    parent = root
                    geom_index = list(parent).index(geom_elem)
                    parent.insert(geom_index + 1, results_elem)
                else:
                    root.append(results_elem)
                logger.info("Created Results element in rasmap")

            # Find the specific plan layer - match by filename basename
            plan_layer = None
            plan_basename = Path(plan_hdf_filename).name.lower()
            for layer in results_elem.findall("Layer"):
                filename = layer.get("Filename", "")
                if Path(filename).name.lower() == plan_basename:
                    plan_layer = layer
                    break

            if plan_layer is None:
                # Create the plan layer - use output_folder as layer name
                plan_layer = ET.SubElement(results_elem, "Layer")
                plan_layer.set("Name", output_folder)
                plan_layer.set("Type", "RASResults")
                plan_layer.set("Filename", f".\\{plan_hdf_filename}")
                logger.info(f"Created plan layer '{output_folder}' in rasmap for {plan_hdf_filename}")

            # Determine display name and output filename
            type_info = None
            for key, (xml_name, display_name, _) in RasProcess.MAP_TYPES.items():
                if xml_name == map_type:
                    type_info = (xml_name, display_name)
                    break

            if type_info is None:
                display_name = map_type.title()
            else:
                display_name = type_info[1]

            # Create output filename
            # Format: .\OutputFolder\WSE (Max).vrt or .\OutputFolder\Depth (10SEP2018 02 30 00).vrt
            safe_profile = profile_name.replace(":", " ").replace("/", "_")
            output_filename = f".\\{output_folder}\\{display_name} ({safe_profile}).vrt"

            # Create the Layer element
            layer_elem = ET.SubElement(plan_layer, "Layer")
            layer_elem.set("Name", display_name)
            layer_elem.set("Type", "RASResultsMap")
            layer_elem.set("Checked", "True")
            layer_elem.set("Filename", output_filename)

            # Create MapParameters element
            map_params = ET.SubElement(layer_elem, "MapParameters")
            map_params.set("MapType", map_type)
            map_params.set("OutputMode", "Stored Current Terrain")
            map_params.set("StoredFilename", output_filename)
            map_params.set("ProfileIndex", str(profile_index))
            map_params.set("ProfileName", profile_name)

            # Write back
            tree.write(rasmap_path, encoding='utf-8', xml_declaration=True)
            logger.debug(f"Added stored map: {display_name} ({profile_name})")
            return True

        except Exception as e:
            logger.error(f"Failed to add stored map to rasmap: {e}")
            return False

    @staticmethod
    @log_call
    def _remove_stored_maps_from_rasmap(
        rasmap_path: Path,
        plan_hdf_filename: str = None
    ) -> int:
        """
        Remove all stored map configurations from .rasmap file.

        Args:
            rasmap_path: Path to .rasmap file
            plan_hdf_filename: Optional specific plan to clear. If None, clears all.

        Returns:
            Number of stored maps removed
        """
        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()

            removed_count = 0
            results_elem = root.find(".//Results")
            if results_elem is None:
                return 0

            for plan_layer in results_elem.findall("Layer"):
                if plan_hdf_filename:
                    filename = plan_layer.get("Filename", "")
                    # Match by basename to handle relative paths like .\file.hdf
                    plan_basename = Path(plan_hdf_filename).name.lower()
                    if Path(filename).name.lower() != plan_basename:
                        continue

                # Find and remove stored map layers
                to_remove = []
                for layer in plan_layer.findall("Layer"):
                    if layer.get("Type") == "RASResultsMap":
                        map_params = layer.find("MapParameters")
                        if map_params is not None:
                            output_mode = map_params.get("OutputMode", "")
                            if "Stored" in output_mode:
                                to_remove.append(layer)

                for layer in to_remove:
                    plan_layer.remove(layer)
                    removed_count += 1

            if removed_count > 0:
                tree.write(rasmap_path, encoding='utf-8', xml_declaration=True)
                logger.debug(f"Removed {removed_count} stored maps from rasmap")

            return removed_count

        except Exception as e:
            logger.error(f"Failed to remove stored maps from rasmap: {e}")
            return 0

    @staticmethod
    @log_call
    def store_maps(
        plan_number: str,
        output_folder: str = None,
        profile: str = "Max",
        wse: bool = True,
        depth: bool = True,
        velocity: bool = True,
        froude: bool = False,
        shear_stress: bool = False,
        depth_x_velocity: bool = False,
        depth_x_velocity_sq: bool = False,
        inundation_boundary: bool = False,
        clear_existing: bool = True,
        fix_georef: bool = True,
        ras_object=None,
        ras_version: str = None,
        timeout: int = 600
    ) -> Dict[str, List[Path]]:
        """
        Generate stored maps for a plan using RasProcess.exe StoreAllMaps.

        This method:
        1. Configures stored maps in the .rasmap file
        2. Runs RasProcess.exe StoreAllMaps command
        3. Optionally fixes georeferencing on output TIFs

        Args:
            plan_number: Plan number (e.g., "01", "06")
            output_folder: Output folder name (default: plan name from rasmap)
            profile: Profile to map - "Max", "Min", or specific timestamp string
            wse: Generate Water Surface Elevation map (default: True)
            depth: Generate Depth map (default: True)
            velocity: Generate Velocity map (default: True)
            froude: Generate Froude number map (default: False)
            shear_stress: Generate Shear Stress map (default: False)
            depth_x_velocity: Generate D*V hazard map (default: False)
            depth_x_velocity_sq: Generate D*V² impact map (default: False)
            inundation_boundary: Generate inundation boundary polygon (default: False)
            clear_existing: Clear existing stored maps before adding new ones (default: True)
            fix_georef: Apply georeferencing fix to output TIFs (default: True)
            ras_object: Optional RAS object instance
            ras_version: Optional specific HEC-RAS version for RasProcess.exe
            timeout: Command timeout in seconds (default: 600)

        Returns:
            Dict mapping map type names to lists of generated file paths.

        Raises:
            FileNotFoundError: If RasProcess.exe or required files not found
            RuntimeError: If RasProcess.exe command fails

        Example:
            >>> results = RasProcess.store_maps(
            ...     plan_number="01",
            ...     output_folder="MaxMaps",
            ...     profile="Max",
            ...     wse=True,
            ...     depth=True,
            ...     velocity=True,
            ...     froude=True
            ... )
            >>> print(results['wse'])
            [Path('project/MaxMaps/WSE (Max).Terrain.tif')]
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Find RasProcess.exe
        rasprocess = RasProcess.find_rasprocess(ras_version)
        if rasprocess is None:
            raise FileNotFoundError(
                "RasProcess.exe not found. Ensure HEC-RAS is installed or specify ras_version."
            )

        # Get paths
        plan_num = RasUtils.normalize_ras_number(plan_number)
        rasmap_path = RasMap.get_rasmap_path(ras_obj)
        if rasmap_path is None:
            raise FileNotFoundError(f"No .rasmap file found in project folder")

        plan_hdf = f"{ras_obj.project_name}.p{plan_num}.hdf"
        plan_hdf_path = ras_obj.project_folder / plan_hdf

        if not plan_hdf_path.exists():
            raise FileNotFoundError(f"Plan HDF not found: {plan_hdf_path}")

        # RasProcess.exe uses the Plan ShortID from HDF to determine output folder name
        # This is the authoritative source - rasmap Layer Name should match but isn't used by RasProcess
        plan_short_id = RasProcess._get_plan_short_id(plan_hdf_path)

        # Get the output folder from rasmap Layer Name (should match Plan ShortID)
        tree = ET.parse(rasmap_path)
        root = tree.getroot()
        output_folder_from_rasmap = None
        plan_basename = Path(plan_hdf).name.lower()
        for layer in root.findall(".//Results/Layer"):
            filename = layer.get("Filename", "")
            if Path(filename).name.lower() == plan_basename:
                output_folder_from_rasmap = layer.get("Name")
                break

        # Determine output folder - priority: Plan ShortID > rasmap Layer Name > user-provided > default
        if plan_short_id:
            actual_output_folder = plan_short_id
        elif output_folder_from_rasmap:
            actual_output_folder = output_folder_from_rasmap
        elif output_folder:
            actual_output_folder = output_folder
        else:
            actual_output_folder = f"Plan_{plan_num}"

        # Use actual output folder for the StoredFilename paths in rasmap
        if output_folder is None:
            output_folder = actual_output_folder

        output_dir = ras_obj.project_folder / actual_output_folder
        output_dir.mkdir(exist_ok=True)

        logger.debug(f"Plan ShortID from HDF: {plan_short_id}")
        logger.debug(f"Output folder from rasmap: {output_folder_from_rasmap}")
        logger.debug(f"Actual output directory: {output_dir}")

        # Determine profile index
        if profile.upper() in ("MAX", "MIN"):
            profile_index = 2147483647  # Special value for Max/Min
            profile_name = profile.title()  # "Max" or "Min"
        else:
            # Specific timestamp - need to find index
            timestamps = RasProcess.get_plan_timestamps(plan_num, ras_obj)
            try:
                profile_index = timestamps.index(profile)
                profile_name = profile
            except ValueError:
                logger.warning(f"Timestamp '{profile}' not found. Available: {timestamps[:5]}...")
                profile_index = 2147483647
                profile_name = "Max"

        # Backup rasmap
        rasmap_backup = rasmap_path.with_suffix('.rasmap.bak')
        shutil.copy2(rasmap_path, rasmap_backup)

        try:
            # Clear existing stored maps if requested
            if clear_existing:
                RasProcess._remove_stored_maps_from_rasmap(rasmap_path, plan_hdf)

            # Build list of maps to generate
            maps_to_add = []
            if wse:
                maps_to_add.append(('elevation', 'wse'))
            if depth:
                maps_to_add.append(('depth', 'depth'))
            if velocity:
                maps_to_add.append(('velocity', 'velocity'))
            if froude:
                maps_to_add.append(('froude', 'froude'))
            if shear_stress:
                maps_to_add.append(('Shear', 'shear_stress'))
            if depth_x_velocity:
                maps_to_add.append(('depth and velocity', 'depth_x_velocity'))
            if depth_x_velocity_sq:
                maps_to_add.append(('depth and velocity squared', 'depth_x_velocity_sq'))

            # Add stored maps to rasmap
            for map_type, _ in maps_to_add:
                RasProcess._add_stored_map_to_rasmap(
                    rasmap_path,
                    plan_hdf,
                    map_type,
                    profile_name,
                    output_folder,
                    profile_index
                )

            # Add inundation boundary if requested
            if inundation_boundary:
                # This uses a different output mode
                RasProcess._add_stored_map_to_rasmap(
                    rasmap_path,
                    plan_hdf,
                    'depth',  # Uses depth with polygon output
                    profile_name,
                    output_folder,
                    profile_index
                )

            # Run StoreAllMaps
            logger.info(f"Running StoreAllMaps for plan {plan_num}...")

            cmd = [
                str(rasprocess),
                "-Command=StoreAllMaps",
                f"-RasMapFilename={rasmap_path}",
                f"-ResultFilename={plan_hdf_path}"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            logger.debug(f"StoreAllMaps stdout: {result.stdout}")
            if result.stderr:
                logger.warning(f"StoreAllMaps stderr: {result.stderr}")

            # Find generated files
            generated_files = {}
            for map_type, map_key in maps_to_add:
                type_info = None
                for key, (xml_name, display_name, _) in RasProcess.MAP_TYPES.items():
                    if xml_name == map_type:
                        display_name_used = display_name
                        break
                else:
                    display_name_used = map_type.title()

                # Look for TIF files matching this map type
                # Pattern: "WSE (Max).Terrain50.dtm_20ft.tif" or "Depth (Max).*.tif"
                safe_profile = profile_name.replace(":", " ").replace("/", "_")
                pattern = f"{display_name_used} ({safe_profile})*.tif"
                tif_files = list(output_dir.glob(pattern))

                # Also try with underscore-replaced spaces if no files found
                if not tif_files:
                    pattern_alt = f"{display_name_used.replace(' ', '_')} ({safe_profile})*.tif"
                    tif_files = list(output_dir.glob(pattern_alt))

                if tif_files:
                    generated_files[map_key] = tif_files
                    logger.info(f"Generated {len(tif_files)} {map_key} TIF(s)")
                else:
                    logger.debug(f"No TIF files found for {map_key} with pattern: {pattern}")

            # Fix georeferencing if requested
            if fix_georef and generated_files:
                prj_path, terrain_path = RasProcess._get_projection_info(rasmap_path)
                if prj_path and terrain_path:
                    for tif_list in generated_files.values():
                        for tif_path in tif_list:
                            RasProcess._fix_georeferencing(tif_path, prj_path, terrain_path)
                else:
                    logger.warning("Could not find projection/terrain for georef fix")

            return generated_files

        finally:
            # Restore rasmap backup
            if rasmap_backup.exists():
                shutil.copy2(rasmap_backup, rasmap_path)
                rasmap_backup.unlink()

    @staticmethod
    @log_call
    def store_all_maps(
        output_folder: str = None,
        profile: str = "Max",
        wse: bool = True,
        depth: bool = True,
        velocity: bool = True,
        froude: bool = False,
        shear_stress: bool = False,
        depth_x_velocity: bool = False,
        depth_x_velocity_sq: bool = False,
        fix_georef: bool = True,
        ras_object=None,
        ras_version: str = None,
        timeout: int = 1800
    ) -> Dict[str, Dict[str, List[Path]]]:
        """
        Generate stored maps for all plans in the project.

        This is a convenience wrapper around store_maps() that processes
        all plans with HDF results.

        Args:
            output_folder: Base output folder (plan name appended). If None, uses plan titles.
            profile: Profile to map - "Max", "Min", or specific timestamp
            wse: Generate WSE maps (default: True)
            depth: Generate Depth maps (default: True)
            velocity: Generate Velocity maps (default: True)
            froude: Generate Froude maps (default: False)
            shear_stress: Generate Shear Stress maps (default: False)
            depth_x_velocity: Generate D*V maps (default: False)
            depth_x_velocity_sq: Generate D*V² maps (default: False)
            fix_georef: Apply georeferencing fix (default: True)
            ras_object: Optional RAS object instance
            ras_version: Optional specific HEC-RAS version
            timeout: Timeout per plan in seconds (default: 1800)

        Returns:
            Dict mapping plan numbers to their generated files dict.

        Example:
            >>> all_results = RasProcess.store_all_maps(profile="Max")
            >>> for plan, files in all_results.items():
            ...     print(f"Plan {plan}: {len(files.get('wse', []))} WSE files")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        all_results = {}

        # Get plans with HDF results
        for _, row in ras_obj.plan_df.iterrows():
            plan_num = row['plan_number']
            hdf_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_num}.hdf"

            if not hdf_path.exists():
                logger.debug(f"Skipping plan {plan_num} - no HDF results")
                continue

            # Determine output folder for this plan
            if output_folder:
                plan_output = f"{output_folder}_{plan_num}"
            else:
                plan_output = None  # Will use plan title

            try:
                results = RasProcess.store_maps(
                    plan_number=plan_num,
                    output_folder=plan_output,
                    profile=profile,
                    wse=wse,
                    depth=depth,
                    velocity=velocity,
                    froude=froude,
                    shear_stress=shear_stress,
                    depth_x_velocity=depth_x_velocity,
                    depth_x_velocity_sq=depth_x_velocity_sq,
                    fix_georef=fix_georef,
                    ras_object=ras_obj,
                    ras_version=ras_version,
                    timeout=timeout
                )
                all_results[plan_num] = results

            except Exception as e:
                logger.error(f"Failed to generate maps for plan {plan_num}: {e}")
                all_results[plan_num] = {'error': str(e)}

        return all_results

    @staticmethod
    @log_call
    def run_command(
        command_xml: str,
        ras_version: str = None,
        timeout: int = 600
    ) -> subprocess.CompletedProcess:
        """
        Run a raw RasProcess.exe command from XML string.

        This is a low-level method for running arbitrary RasProcess commands.
        See rasmapper_docs/16_rasprocess_cli_reference.md for available commands.

        Args:
            command_xml: XML command string
            ras_version: Optional specific HEC-RAS version
            timeout: Command timeout in seconds

        Returns:
            subprocess.CompletedProcess with stdout/stderr

        Example:
            >>> xml = '''<?xml version="1.0" encoding="utf-8"?>
            ... <Command Type="StoreMap">
            ...   <MapType>depth</MapType>
            ...   <Result>C:/project/plan.p01.hdf</Result>
            ...   <ProfileName>Max</ProfileName>
            ...   <OutputBaseFilename>C:/project/Maps/depth_max</OutputBaseFilename>
            ... </Command>'''
            >>> result = RasProcess.run_command(xml)
        """
        rasprocess = RasProcess.find_rasprocess(ras_version)
        if rasprocess is None:
            raise FileNotFoundError("RasProcess.exe not found")

        # Write XML to temp file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.xml',
            delete=False,
            encoding='utf-8'
        ) as f:
            f.write(command_xml)
            xml_path = f.name

        try:
            result = subprocess.run(
                [str(rasprocess), f"-CommandFile={xml_path}"],
                capture_output=True,
                text=True,
                timeout=timeout
            )

            logger.debug(f"Command output: {result.stdout}")
            if result.stderr:
                logger.warning(f"Command errors: {result.stderr}")

            return result

        finally:
            os.unlink(xml_path)
