"""
HdfStruc1D - 1D Structure Results Extraction from HEC-RAS HDF Files

This module provides functionality for extracting results data from 1D hydraulic
structures (bridges, culverts, inline weirs) in HEC-RAS HDF files.

All methods are static and designed to be used without instantiation.

List of Functions:
- get_structure_max_values() - Extract max HW, TW, Flow for a structure from results
- get_structure_timeseries() - Extract full time series for structure
- list_1d_structures() - List all 1D structures with results in HDF file

Example Usage:
    >>> from ras_commander.hdf import HdfStruc1D
    >>>
    >>> # Get max values for HTAB optimization
    >>> max_vals = HdfStruc1D.get_structure_max_values(
    ...     "plan.p01.hdf", "White River", "Muncie", "5600"
    ... )
    >>> print(f"Max HW: {max_vals['max_hw']}, Max Flow: {max_vals['max_flow']}")
    >>>
    >>> # Get full time series
    >>> ts_df = HdfStruc1D.get_structure_timeseries(
    ...     "plan.p01.hdf", "White River", "Muncie", "5600"
    ... )

Technical Notes:
    - 1D structure results are stored in cross section output at structure locations
    - BR U (bridge upstream) and BR D (bridge downstream) sections store HW/TW
    - Structure flow is typically stored in the structure's upstream cross section
    - For bridges: BR U = upstream face (headwater), BR D = downstream face (tailwater)
"""

from pathlib import Path
from typing import Union, Optional, Dict, Any, List
import h5py
import numpy as np
import pandas as pd

from .HdfBase import HdfBase
from .HdfUtils import HdfUtils
from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


class HdfStruc1D:
    """
    Extract 1D structure results from HEC-RAS HDF files.

    This class provides static methods for extracting max headwater, tailwater,
    and flow values from 1D hydraulic structures (bridges, culverts, inline weirs)
    in HEC-RAS plan HDF files.

    All methods are static and designed to be used without instantiation.

    Notes
    -----
    - 1D structure results are accessed via cross section output at structure locations
    - The structure's upstream (BR U) section provides headwater values
    - The structure's downstream (BR D) section provides tailwater values
    - Flow is typically recorded at the upstream face
    """

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def get_structure_max_values(
        hdf_path: Path,
        river: str,
        reach: str,
        rs: str,
        *,
        ras_object=None
    ) -> Dict[str, Any]:
        """
        Extract maximum headwater, tailwater, and flow values for a 1D structure.

        This method searches for structure results in the HDF file and extracts
        the maximum values needed for HTAB optimization. It looks for both the
        upstream (BR U) and downstream (BR D) cross sections associated with
        a bridge, culvert, or inline structure.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        river : str
            River name (case-sensitive)
        reach : str
            Reach name (case-sensitive)
        rs : str
            River station of the structure (as string, e.g., "5600")
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'max_hw': Maximum headwater (water surface at upstream face)
            - 'max_tw': Maximum tailwater (water surface at downstream face)
            - 'max_flow': Maximum flow through structure
            - 'hw_source': Source location for headwater data
            - 'tw_source': Source location for tailwater data
            - 'flow_source': Source location for flow data
            - 'found': True if structure results were found

        Raises
        ------
        FileNotFoundError
            If HDF file doesn't exist
        ValueError
            If structure not found in results

        Examples
        --------
        >>> max_vals = HdfStruc1D.get_structure_max_values(
        ...     "Muncie.p01.hdf", "White River", "Muncie", "5600"
        ... )
        >>> print(f"Max HW: {max_vals['max_hw']:.2f}")
        >>> print(f"Max Flow: {max_vals['max_flow']:.0f}")

        Notes
        -----
        - For bridges: BR U = headwater (upstream face), BR D = tailwater (downstream)
        - If exact structure location not found, searches for nearby BR U/BR D markers
        - For unsteady results, uses time series max values
        - For steady results, uses max across all profiles
        """
        result = {
            'max_hw': None,
            'max_tw': None,
            'max_flow': None,
            'hw_source': None,
            'tw_source': None,
            'flow_source': None,
            'found': False
        }

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Determine if unsteady or steady results
                is_unsteady = "Results/Unsteady" in hdf_file
                is_steady = "Results/Steady" in hdf_file

                if is_unsteady:
                    result = HdfStruc1D._extract_unsteady_structure_max(
                        hdf_file, river, reach, rs, result
                    )
                elif is_steady:
                    result = HdfStruc1D._extract_steady_structure_max(
                        hdf_file, river, reach, rs, result
                    )
                else:
                    logger.warning(f"No steady or unsteady results found in {hdf_path}")
                    return result

                return result

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error extracting structure max values: {str(e)}")
            return result

    @staticmethod
    def _extract_unsteady_structure_max(
        hdf_file: h5py.File,
        river: str,
        reach: str,
        rs: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract max values from unsteady results for a structure."""
        base_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections"

        if base_path not in hdf_file:
            logger.warning("No cross section results found in unsteady output")
            return result

        # Get cross section attributes to find structure location
        attrs_path = f"{base_path}/Cross Section Attributes"
        if attrs_path not in hdf_file:
            logger.warning("No cross section attributes found")
            return result

        attrs_data = hdf_file[attrs_path][()]

        # Build location lookup
        xs_locations = []
        for i, attr in enumerate(attrs_data):
            xs_river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
            xs_reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
            xs_station = attr['Station'].decode('utf-8').strip() if isinstance(attr['Station'], bytes) else str(attr['Station']).strip()
            xs_name = attr['Name'].decode('utf-8').strip() if 'Name' in attr.dtype.names else ""

            xs_locations.append({
                'index': i,
                'river': xs_river,
                'reach': xs_reach,
                'station': xs_station,
                'name': xs_name
            })

        # Find structure-related cross sections
        # Look for exact RS match or BR U/BR D patterns
        hw_idx = None
        tw_idx = None
        flow_idx = None

        # Strategy 1: Look for BR U/BR D markers at or near the RS
        for xs in xs_locations:
            if xs['river'] == river and xs['reach'] == reach:
                station = xs['station']
                name = xs['name']

                # Check for bridge upstream (headwater)
                if 'BR U' in name or f"BR U" in station:
                    # Check if this is near our target RS
                    if HdfStruc1D._station_near_rs(station, rs):
                        hw_idx = xs['index']
                        result['hw_source'] = f"{river}/{reach}/{station} ({name})"
                        logger.debug(f"Found HW source at index {hw_idx}: {result['hw_source']}")

                # Check for bridge downstream (tailwater)
                if 'BR D' in name or f"BR D" in station:
                    if HdfStruc1D._station_near_rs(station, rs):
                        tw_idx = xs['index']
                        result['tw_source'] = f"{river}/{reach}/{station} ({name})"
                        logger.debug(f"Found TW source at index {tw_idx}: {result['tw_source']}")

        # Strategy 2: If BR U/BR D not found, look for exact RS match
        if hw_idx is None:
            for xs in xs_locations:
                if xs['river'] == river and xs['reach'] == reach:
                    if xs['station'] == rs:
                        hw_idx = xs['index']
                        result['hw_source'] = f"{river}/{reach}/{rs} (exact match)"
                        logger.debug(f"Using exact RS match for HW at index {hw_idx}")
                        break

        # Strategy 3: Search for structure in Structures output path (if exists)
        struct_path = f"Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Structures"
        if struct_path in hdf_file:
            logger.debug("Found Structures output group - checking for direct structure data")
            # Try to extract from dedicated structure output if available
            struct_result = HdfStruc1D._extract_from_structure_group(
                hdf_file, struct_path, river, reach, rs
            )
            if struct_result['found']:
                return struct_result

        # Extract max values from cross section time series
        if hw_idx is not None:
            # Water Surface for headwater
            ws_path = f"{base_path}/Water Surface"
            if ws_path in hdf_file:
                ws_data = hdf_file[ws_path][:]
                if hw_idx < ws_data.shape[1]:
                    result['max_hw'] = float(np.nanmax(ws_data[:, hw_idx]))
                    result['found'] = True
                    logger.debug(f"Max HW from WS data: {result['max_hw']:.2f}")

            # Flow for headwater location
            flow_path = f"{base_path}/Flow"
            if flow_path in hdf_file:
                flow_data = hdf_file[flow_path][:]
                if hw_idx < flow_data.shape[1]:
                    result['max_flow'] = float(np.nanmax(flow_data[:, hw_idx]))
                    result['flow_source'] = result['hw_source']
                    logger.debug(f"Max Flow: {result['max_flow']:.0f}")

        if tw_idx is not None:
            # Water Surface for tailwater
            ws_path = f"{base_path}/Water Surface"
            if ws_path in hdf_file:
                ws_data = hdf_file[ws_path][:]
                if tw_idx < ws_data.shape[1]:
                    result['max_tw'] = float(np.nanmax(ws_data[:, tw_idx]))
                    result['found'] = True
                    logger.debug(f"Max TW from WS data: {result['max_tw']:.2f}")

        # If tailwater not found separately, estimate from headwater
        if result['max_tw'] is None and result['max_hw'] is not None:
            # Conservative estimate: TW slightly less than HW
            result['max_tw'] = result['max_hw']
            result['tw_source'] = f"Estimated from HW (same as {result['hw_source']})"
            logger.info("TW not found separately - using HW value as conservative estimate")

        return result

    @staticmethod
    def _extract_steady_structure_max(
        hdf_file: h5py.File,
        river: str,
        reach: str,
        rs: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract max values from steady results for a structure."""
        base_path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections"

        if base_path not in hdf_file:
            logger.warning("No cross section results found in steady output")
            return result

        # Get cross section attributes
        attrs_path = f"{base_path}/Attributes"
        if attrs_path not in hdf_file:
            # Try alternate path
            attrs_path = "Results/Steady/Output/Geometry Info/Cross Section Attributes"
            if attrs_path not in hdf_file:
                logger.warning("No cross section attributes found")
                return result

        attrs_data = hdf_file[attrs_path][()]

        # Build location lookup (similar to unsteady)
        xs_locations = []
        for i, attr in enumerate(attrs_data):
            xs_river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
            xs_reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
            xs_station = attr['Station'].decode('utf-8').strip() if isinstance(attr['Station'], bytes) else str(attr['Station']).strip()

            xs_locations.append({
                'index': i,
                'river': xs_river,
                'reach': xs_reach,
                'station': xs_station
            })

        # Find structure location
        hw_idx = None
        for xs in xs_locations:
            if xs['river'] == river and xs['reach'] == reach:
                if xs['station'] == rs:
                    hw_idx = xs['index']
                    result['hw_source'] = f"{river}/{reach}/{rs}"
                    break

        if hw_idx is not None:
            # Water Surface (steady has multiple profiles - take max across all)
            ws_path = f"{base_path}/Water Surface"
            if ws_path in hdf_file:
                ws_data = hdf_file[ws_path][:]
                if hw_idx < ws_data.shape[1]:
                    # Shape is typically (num_profiles, num_xs)
                    result['max_hw'] = float(np.nanmax(ws_data[:, hw_idx]))
                    result['max_tw'] = result['max_hw']  # Conservative
                    result['tw_source'] = result['hw_source']
                    result['found'] = True

            # Flow
            flow_path = f"{base_path}/Flow"
            if flow_path not in hdf_file:
                # Try alternate path for flow
                flow_path = f"{base_path}/Additional Variables/Flow"

            if flow_path in hdf_file:
                flow_data = hdf_file[flow_path][:]
                if hw_idx < flow_data.shape[1]:
                    result['max_flow'] = float(np.nanmax(flow_data[:, hw_idx]))
                    result['flow_source'] = result['hw_source']

        return result

    @staticmethod
    def _extract_from_structure_group(
        hdf_file: h5py.File,
        struct_path: str,
        river: str,
        reach: str,
        rs: str
    ) -> Dict[str, Any]:
        """Extract values from dedicated Structures output group if available."""
        result = {
            'max_hw': None,
            'max_tw': None,
            'max_flow': None,
            'hw_source': None,
            'tw_source': None,
            'flow_source': None,
            'found': False
        }

        try:
            struct_group = hdf_file[struct_path]

            # Look for structure attributes or name matching
            if "Structure Attributes" in struct_group:
                attrs = struct_group["Structure Attributes"][()]

                for i, attr in enumerate(attrs):
                    attr_river = attr['River'].decode('utf-8').strip() if 'River' in attr.dtype.names and isinstance(attr['River'], bytes) else ""
                    attr_reach = attr['Reach'].decode('utf-8').strip() if 'Reach' in attr.dtype.names and isinstance(attr['Reach'], bytes) else ""
                    attr_rs = attr['RS'].decode('utf-8').strip() if 'RS' in attr.dtype.names and isinstance(attr['RS'], bytes) else ""

                    if attr_river == river and attr_reach == reach and attr_rs == rs:
                        # Found the structure - extract max values
                        source = f"{river}/{reach}/{rs} (Structure output)"

                        if "Headwater" in struct_group:
                            hw_data = struct_group["Headwater"][:]
                            if i < hw_data.shape[1]:
                                result['max_hw'] = float(np.nanmax(hw_data[:, i]))
                                result['hw_source'] = source
                                result['found'] = True

                        if "Tailwater" in struct_group:
                            tw_data = struct_group["Tailwater"][:]
                            if i < tw_data.shape[1]:
                                result['max_tw'] = float(np.nanmax(tw_data[:, i]))
                                result['tw_source'] = source

                        if "Flow" in struct_group:
                            flow_data = struct_group["Flow"][:]
                            if i < flow_data.shape[1]:
                                result['max_flow'] = float(np.nanmax(flow_data[:, i]))
                                result['flow_source'] = source

                        break

        except Exception as e:
            logger.debug(f"Could not extract from Structures group: {e}")

        return result

    @staticmethod
    def _station_near_rs(station: str, rs: str, tolerance: float = 100.0) -> bool:
        """
        Check if a station string is near the target river station.

        Handles station formats like "5600 BR U", "BR U 5600", "5600*", etc.
        """
        try:
            # Extract numeric part from station
            station_num = None
            for part in station.replace('*', ' ').split():
                try:
                    station_num = float(part)
                    break
                except ValueError:
                    continue

            rs_num = float(rs.replace('*', '').strip())

            if station_num is not None:
                return abs(station_num - rs_num) <= tolerance

        except (ValueError, AttributeError):
            pass

        return False

    @staticmethod
    @log_call
    @standardize_input(file_type='plan_hdf')
    def list_1d_structures(hdf_path: Path, *, ras_object=None) -> pd.DataFrame:
        """
        List all 1D structures with results in HDF file.

        Parameters
        ----------
        hdf_path : Path
            Path to HEC-RAS plan HDF file or plan number
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        pd.DataFrame
            DataFrame with columns:
            - River: River name
            - Reach: Reach name
            - RS: River station
            - Name: Cross section name (may include BR U/BR D markers)
            - Type: Structure type indicator (Bridge, Culvert, etc.) if detectable

        Notes
        -----
        Structures are identified by BR U/BR D markers in cross section names
        or by presence in dedicated Structures output group.
        """
        structures = []

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                # Check unsteady results
                unsteady_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections/Cross Section Attributes"
                if unsteady_path in hdf_file:
                    attrs_data = hdf_file[unsteady_path][()]

                    for attr in attrs_data:
                        name = attr['Name'].decode('utf-8').strip() if 'Name' in attr.dtype.names and isinstance(attr['Name'], bytes) else ""

                        # Identify structure markers
                        is_structure = 'BR U' in name or 'BR D' in name or 'IC' in name or 'Culv' in name.lower()

                        if is_structure:
                            river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                            reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                            station = attr['Station'].decode('utf-8').strip() if isinstance(attr['Station'], bytes) else str(attr['Station']).strip()

                            struct_type = "Unknown"
                            if 'BR' in name:
                                struct_type = "Bridge"
                            elif 'IC' in name:
                                struct_type = "Inline"
                            elif 'Culv' in name.lower():
                                struct_type = "Culvert"

                            structures.append({
                                'River': river,
                                'Reach': reach,
                                'RS': station,
                                'Name': name,
                                'Type': struct_type
                            })

                # Check Structures group if exists
                struct_attrs_path = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Structures/Structure Attributes"
                if struct_attrs_path in hdf_file:
                    struct_attrs = hdf_file[struct_attrs_path][()]
                    for attr in struct_attrs:
                        river = attr['River'].decode('utf-8').strip() if 'River' in attr.dtype.names and isinstance(attr['River'], bytes) else ""
                        reach = attr['Reach'].decode('utf-8').strip() if 'Reach' in attr.dtype.names and isinstance(attr['Reach'], bytes) else ""
                        rs = attr['RS'].decode('utf-8').strip() if 'RS' in attr.dtype.names and isinstance(attr['RS'], bytes) else ""
                        name = attr['Name'].decode('utf-8').strip() if 'Name' in attr.dtype.names and isinstance(attr['Name'], bytes) else ""

                        structures.append({
                            'River': river,
                            'Reach': reach,
                            'RS': rs,
                            'Name': name,
                            'Type': 'Structure'
                        })

        except Exception as e:
            logger.error(f"Error listing 1D structures: {str(e)}")

        df = pd.DataFrame(structures)
        if not df.empty:
            df = df.drop_duplicates(subset=['River', 'Reach', 'RS']).reset_index(drop=True)
            logger.info(f"Found {len(df)} 1D structures with results")
        else:
            logger.info("No 1D structures found in HDF file")

        return df
