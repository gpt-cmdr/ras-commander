"""
GeomHtab - Unified HTAB Parameter Management for HEC-RAS Geometry Files

This module provides a unified interface for optimizing Hydraulic Table (HTAB)
parameters for both cross sections and hydraulic structures (bridges, culverts,
inline weirs) in HEC-RAS geometry files.

HTAB parameters control how HEC-RAS pre-computes hydraulic property tables:
- Cross sections: Starting elevation, increment, and number of points
- Structures: Maximum headwater, tailwater, flow, and curve point counts

The optimize_all_htab_from_results() method provides one-call optimization of
ALL HTAB parameters in a geometry file based on existing HDF results.

All methods are static and designed to be used without instantiation.

List of Functions:
- optimize_all_htab_from_results() - One-call optimization of ALL HTAB in geometry file
- optimize_xs_htab_from_results() - Optimize all cross section HTAB from HDF results
- optimize_structures_htab_from_results() - Optimize all structure HTAB from HDF results

Example Usage:
    >>> from ras_commander.geom import GeomHtab
    >>>
    >>> # One-call optimization of all HTAB
    >>> result = GeomHtab.optimize_all_htab_from_results(
    ...     geom_file="model.g01",
    ...     hdf_results_path="model.p01.hdf",
    ...     xs_safety_factor=1.3,
    ...     structure_hw_safety=2.0
    ... )
    >>> print(f"Modified {result['xs_modified']} XS, {result['structures_modified']} structures")
    >>> print(f"Backup at: {result['backup']}")

Technical Notes:
    - Safety factors prevent extrapolation errors during simulation
    - XS HTAB: 30% safety factor (1.3x) on depth is recommended
    - Structure HTAB: 100% safety factor (2.0x) on HW/TW/flow is recommended
    - Creates single backup before any modifications
    - If any step fails, backup can be used for manual recovery

References:
    - HEC-RAS User's Manual: Geometric Preprocessor
    - HEC-RAS User's Manual: HTAB Internal Boundaries Table
    - Paige Brue, Kleinschmidt: HTAB optimization best practices
    - feature_dev_notes/HTAB_Parameter_Modification/
"""

from pathlib import Path
from typing import Dict, List, Optional, Union, Any
import shutil
from datetime import datetime

import h5py
import pandas as pd
import numpy as np

from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


class GeomHtab:
    """
    Unified HTAB parameter management for HEC-RAS geometry files.

    This class provides a single entry point for optimizing all HTAB parameters
    (cross sections and structures) in a geometry file based on existing HDF
    results.

    All methods are static and designed to be used without instantiation.

    Key Features:
        - One-call optimization of ALL HTAB parameters
        - Automatic safety factor application
        - Single backup creation for all modifications
        - Comprehensive summary of changes made

    Example:
        >>> from ras_commander.geom import GeomHtab
        >>>
        >>> # Optimize all HTAB from results
        >>> result = GeomHtab.optimize_all_htab_from_results(
        ...     "model.g01", "model.p01.hdf"
        ... )
        >>> print(f"Backup: {result['backup']}")
        >>> print(f"XS modified: {result['xs_modified']}")
        >>> print(f"Structures modified: {result['structures_modified']}")
    """

    @staticmethod
    @log_call
    def optimize_all_htab_from_results(
        geom_file: Union[str, Path],
        hdf_results_path: Union[str, Path],
        xs_safety_factor: float = 1.3,
        structure_hw_safety: float = 2.0,
        structure_flow_safety: float = 2.0,
        xs_target_increment: float = 0.1,
        xs_max_points: int = 500,
        structure_free_flow_points: int = 20,
        structure_submerged_curves: int = 30,
        structure_points_per_curve: int = 20,
        create_backup: bool = True
    ) -> Dict[str, Any]:
        """
        One-call optimization of ALL HTAB parameters in geometry file.

        This method optimizes HTAB parameters for both cross sections and
        hydraulic structures (bridges, culverts, inline weirs) based on
        observed maximum water surface elevations and flows from HDF results.

        The optimization process:
            1. Creates a single backup of the geometry file
            2. Extracts maximum WSE values for all cross sections from HDF
            3. Calculates and applies optimal XS HTAB parameters
            4. Extracts maximum HW/flow values for structures from HDF
            5. Calculates and applies optimal structure HTAB parameters
            6. Returns comprehensive summary of all changes

        Parameters:
            geom_file: Path to geometry file (.g##)
            hdf_results_path: Path to plan HDF file with results (.p##.hdf)
            xs_safety_factor: Safety factor for XS max depth (default 1.3 = 30%)
                Higher values provide more buffer against extrapolation.
                Recommended: 1.2-1.5 for typical floods, 2.0 for dam break.
            structure_hw_safety: Safety factor for structure headwater (default 2.0 = 100%)
            structure_flow_safety: Safety factor for structure flow (default 2.0 = 100%)
            xs_target_increment: Target elevation increment for XS HTAB (default 0.1 ft)
            xs_max_points: Maximum points in XS HTAB (HEC-RAS limit is 500)
            structure_free_flow_points: Points on free flow rating curve (max 20)
            structure_submerged_curves: Number of submerged rating curves (max 30)
            structure_points_per_curve: Points per submerged curve (max 20)
            create_backup: Whether to create .bak backup file (default True)

        Returns:
            dict: Summary of optimization with keys:
                - 'xs_modified' (int): Number of cross sections modified
                - 'structures_modified' (int): Number of structures modified
                - 'backup' (Path or None): Path to backup file
                - 'xs_summary' (dict): Cross section optimization summary
                - 'structure_summary' (dict): Structure optimization summary
                - 'total_changes' (int): Total HTAB modifications made
                - 'success' (bool): Whether optimization completed without errors
                - 'errors' (list): List of any errors encountered
                - 'warnings' (list): List of any warnings generated

        Raises:
            FileNotFoundError: If geometry file or HDF file doesn't exist
            ValueError: If HDF file doesn't contain required results data
            IOError: If file write fails

        Example:
            >>> # Standard optimization with defaults
            >>> result = GeomHtab.optimize_all_htab_from_results(
            ...     "model.g01", "model.p01.hdf"
            ... )
            >>> print(f"Optimized {result['xs_modified']} XS, "
            ...       f"{result['structures_modified']} structures")

            >>> # Dam break scenario with higher safety factors
            >>> result = GeomHtab.optimize_all_htab_from_results(
            ...     "model.g01", "model.p01.hdf",
            ...     xs_safety_factor=2.0,
            ...     structure_hw_safety=3.0,
            ...     structure_flow_safety=3.0
            ... )

        Notes:
            - A single backup is created before any modifications
            - If structures optimization fails, XS changes are retained
            - Re-run geometric preprocessor (clear_geompre=True) after optimization
            - Verify HEC-RAS can open modified file before discarding backup

        See Also:
            - optimize_xs_htab_from_results(): XS-only optimization
            - optimize_structures_htab_from_results(): Structures-only optimization
            - GeomHtabUtils: Utility functions for HTAB calculations
        """
        from .GeomParser import GeomParser
        from .GeomCrossSection import GeomCrossSection
        from .GeomBridge import GeomBridge
        from .GeomHtabUtils import GeomHtabUtils

        geom_file = Path(geom_file)
        hdf_results_path = Path(hdf_results_path)

        # Validate inputs
        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not hdf_results_path.exists():
            raise FileNotFoundError(f"HDF results file not found: {hdf_results_path}")

        # Initialize result summary
        result = {
            'xs_modified': 0,
            'structures_modified': 0,
            'backup': None,
            'xs_summary': {},
            'structure_summary': {},
            'total_changes': 0,
            'success': False,
            'errors': [],
            'warnings': []
        }

        # Create single backup before any modifications
        if create_backup:
            try:
                backup_path = GeomParser.create_backup(geom_file)
                result['backup'] = backup_path
                logger.info(f"Created unified backup: {backup_path}")
            except Exception as e:
                error_msg = f"Failed to create backup: {str(e)}"
                logger.error(error_msg)
                result['errors'].append(error_msg)
                raise IOError(error_msg)

        # Step 1: Optimize Cross Section HTAB
        logger.info("Starting cross section HTAB optimization...")
        try:
            xs_result = GeomHtab.optimize_xs_htab_from_results(
                geom_file=geom_file,
                hdf_results_path=hdf_results_path,
                safety_factor=xs_safety_factor,
                target_increment=xs_target_increment,
                max_points=xs_max_points,
                create_backup=False  # Already created unified backup
            )
            result['xs_modified'] = xs_result.get('modified', 0)
            result['xs_summary'] = xs_result
            logger.info(f"Optimized {result['xs_modified']} cross sections")
        except Exception as e:
            error_msg = f"XS HTAB optimization failed: {str(e)}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
            # Continue to try structure optimization even if XS fails

        # Step 2: Optimize Structure HTAB
        logger.info("Starting structure HTAB optimization...")
        try:
            struct_result = GeomHtab.optimize_structures_htab_from_results(
                geom_file=geom_file,
                hdf_results_path=hdf_results_path,
                hw_safety_factor=structure_hw_safety,
                flow_safety_factor=structure_flow_safety,
                free_flow_points=structure_free_flow_points,
                submerged_curves=structure_submerged_curves,
                points_per_curve=structure_points_per_curve,
                create_backup=False  # Already created unified backup
            )
            result['structures_modified'] = struct_result.get('modified', 0)
            result['structure_summary'] = struct_result
            logger.info(f"Optimized {result['structures_modified']} structures")
        except Exception as e:
            error_msg = f"Structure HTAB optimization failed: {str(e)}"
            logger.error(error_msg)
            result['errors'].append(error_msg)

        # Calculate totals and set success
        result['total_changes'] = result['xs_modified'] + result['structures_modified']
        result['success'] = len(result['errors']) == 0

        # Log summary
        if result['success']:
            logger.info(
                f"HTAB optimization complete: {result['xs_modified']} XS, "
                f"{result['structures_modified']} structures modified"
            )
        else:
            logger.warning(
                f"HTAB optimization completed with errors: {result['xs_modified']} XS, "
                f"{result['structures_modified']} structures modified. "
                f"Errors: {result['errors']}"
            )

        return result

    @staticmethod
    @log_call
    def optimize_xs_htab_from_results(
        geom_file: Union[str, Path],
        hdf_results_path: Union[str, Path],
        safety_factor: float = 1.3,
        target_increment: float = 0.1,
        max_points: int = 500,
        create_backup: bool = True
    ) -> Dict[str, Any]:
        """
        Optimize HTAB parameters for ALL cross sections from HDF results.

        Reads maximum water surface elevation for each cross section from HDF
        results, calculates optimal HTAB parameters with safety factor, and
        updates the geometry file.

        Parameters:
            geom_file: Path to geometry file (.g##)
            hdf_results_path: Path to plan HDF file with results
            safety_factor: Multiplier for max depth (default 1.3 = 30% safety)
            target_increment: Desired elevation increment (default 0.1 ft)
            max_points: Maximum number of points (default 500, HEC-RAS max)
            create_backup: Whether to create .bak backup (default True)

        Returns:
            dict: Summary with keys:
                - 'modified' (int): Number of XS modified
                - 'skipped' (int): Number of XS skipped (no results)
                - 'errors' (list): List of XS that failed
                - 'params_summary' (dict): Statistics of parameters applied
                - 'backup' (Path or None): Path to backup file

        Notes:
            - For 1D cross sections, extracts max WSE from HDF 1D results
            - For 2D-connected XS, attempts to use mesh max WSE
            - XS without results data are skipped with warning
        """
        from .GeomParser import GeomParser
        from .GeomCrossSection import GeomCrossSection
        from .GeomHtabUtils import GeomHtabUtils
        from ..hdf.HdfResultsXsec import HdfResultsXsec

        geom_file = Path(geom_file)
        hdf_results_path = Path(hdf_results_path)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not hdf_results_path.exists():
            raise FileNotFoundError(f"HDF results file not found: {hdf_results_path}")

        result = {
            'modified': 0,
            'skipped': 0,
            'errors': [],
            'params_summary': {},
            'backup': None
        }

        # Create backup if requested
        if create_backup:
            result['backup'] = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {result['backup']}")

        # Extract max WSE data from HDF
        try:
            xs_timeseries = HdfResultsXsec.get_xsec_timeseries(hdf_results_path)

            # Get max WSE for each cross section
            max_wse_data = {}

            # Extract max water surface from xarray Dataset
            cross_sections = xs_timeseries.coords['cross_section'].values
            rivers = xs_timeseries.coords['River'].values
            reaches = xs_timeseries.coords['Reach'].values
            stations = xs_timeseries.coords['Station'].values
            max_wse_values = xs_timeseries.coords['Maximum_Water_Surface'].values

            for i, xs_name in enumerate(cross_sections):
                max_wse_data[xs_name] = {
                    'river': rivers[i],
                    'reach': reaches[i],
                    'station': stations[i],
                    'max_wse': float(max_wse_values[i])
                }

            logger.info(f"Extracted max WSE for {len(max_wse_data)} cross sections")

        except Exception as e:
            logger.warning(f"Could not extract 1D XS timeseries: {str(e)}")
            logger.warning("Attempting alternative max WSE extraction...")
            max_wse_data = {}

        if not max_wse_data:
            result['errors'].append("No cross section max WSE data available in HDF")
            logger.error("No cross section results data found in HDF file")
            return result

        # Track parameters for summary
        increments_used = []
        depths_covered = []

        # Process each cross section
        for xs_name, xs_data in max_wse_data.items():
            try:
                river = xs_data['river']
                reach = xs_data['reach']
                rs = xs_data['station']
                max_wse = xs_data['max_wse']

                # Skip if max_wse is invalid (NaN or very small)
                if np.isnan(max_wse) or max_wse < -9998:
                    logger.debug(f"Skipping {xs_name}: no valid max WSE")
                    result['skipped'] += 1
                    continue

                # Get current HTAB params to get invert
                current_params = GeomCrossSection.get_xs_htab_params(
                    geom_file, river, reach, rs
                )

                if current_params['invert'] is None:
                    logger.warning(f"Skipping {xs_name}: no invert elevation available")
                    result['skipped'] += 1
                    continue

                invert = current_params['invert']

                # Calculate optimal parameters
                optimal = GeomHtabUtils.calculate_optimal_xs_htab(
                    invert=invert,
                    max_wse=max_wse,
                    safety_factor=safety_factor,
                    target_increment=target_increment,
                    max_points=max_points
                )

                # Apply optimal parameters
                GeomCrossSection.set_xs_htab_params(
                    geom_file=geom_file,
                    river=river,
                    reach=reach,
                    rs=rs,
                    starting_el=optimal['starting_el'],
                    increment=optimal['increment'],
                    num_points=optimal['num_points']
                )

                result['modified'] += 1
                increments_used.append(optimal['increment'])
                depths_covered.append(optimal['target_depth'])

                logger.debug(
                    f"Optimized {xs_name}: starting_el={optimal['starting_el']:.2f}, "
                    f"increment={optimal['increment']:.4f}, num_points={optimal['num_points']}"
                )

            except Exception as e:
                error_msg = f"Failed to optimize {xs_name}: {str(e)}"
                logger.error(error_msg)
                result['errors'].append(error_msg)

        # Build summary statistics
        if increments_used:
            result['params_summary'] = {
                'min_increment': min(increments_used),
                'max_increment': max(increments_used),
                'avg_increment': sum(increments_used) / len(increments_used),
                'min_depth': min(depths_covered),
                'max_depth': max(depths_covered),
                'avg_depth': sum(depths_covered) / len(depths_covered)
            }

        logger.info(
            f"XS HTAB optimization complete: {result['modified']} modified, "
            f"{result['skipped']} skipped, {len(result['errors'])} errors"
        )

        return result

    @staticmethod
    @log_call
    def optimize_structures_htab_from_results(
        geom_file: Union[str, Path],
        hdf_results_path: Union[str, Path],
        hw_safety_factor: float = 2.0,
        flow_safety_factor: float = 2.0,
        tw_safety_factor: float = 2.0,
        free_flow_points: int = 20,
        submerged_curves: int = 30,
        points_per_curve: int = 20,
        create_backup: bool = True
    ) -> Dict[str, Any]:
        """
        Optimize HTAB parameters for ALL structures from HDF results.

        Reads maximum headwater, tailwater, and flow for each structure from
        HDF results, calculates optimal HTAB parameters with safety factors,
        and updates the geometry file.

        Parameters:
            geom_file: Path to geometry file (.g##)
            hdf_results_path: Path to plan HDF file with results
            hw_safety_factor: Safety factor for headwater (default 2.0 = 100%)
            flow_safety_factor: Safety factor for flow (default 2.0 = 100%)
            tw_safety_factor: Safety factor for tailwater (default 2.0 = 100%)
            free_flow_points: Points on free flow curve (default 20, max 20)
            submerged_curves: Number of submerged curves (default 30, max 30)
            points_per_curve: Points per submerged curve (default 20, max 20)
            create_backup: Whether to create .bak backup (default True)

        Returns:
            dict: Summary with keys:
                - 'modified' (int): Number of structures modified
                - 'skipped' (int): Number of structures skipped (no results)
                - 'errors' (list): List of structures that failed
                - 'structures_processed' (list): List of structure identifiers
                - 'backup' (Path or None): Path to backup file

        Notes:
            - Processes bridges, culverts, and inline weirs
            - Structures without results data are skipped with warning
            - Safety is applied to range above invert, not absolute elevation
        """
        from .GeomParser import GeomParser
        from .GeomBridge import GeomBridge
        from .GeomHtabUtils import GeomHtabUtils

        geom_file = Path(geom_file)
        hdf_results_path = Path(hdf_results_path)

        if not geom_file.exists():
            raise FileNotFoundError(f"Geometry file not found: {geom_file}")

        if not hdf_results_path.exists():
            raise FileNotFoundError(f"HDF results file not found: {hdf_results_path}")

        result = {
            'modified': 0,
            'skipped': 0,
            'errors': [],
            'structures_processed': [],
            'backup': None
        }

        # Create backup if requested
        if create_backup:
            result['backup'] = GeomParser.create_backup(geom_file)
            logger.info(f"Created backup: {result['backup']}")

        # Extract structure max values from HDF
        try:
            structure_max_data = GeomHtab._extract_structure_max_values(hdf_results_path)
            logger.info(f"Extracted max values for {len(structure_max_data)} structures")
        except Exception as e:
            logger.warning(f"Could not extract structure results: {str(e)}")
            structure_max_data = {}

        if not structure_max_data:
            # No structure data found - this may be OK if model has no structures
            logger.info("No structure results data found in HDF file (model may have no structures)")
            return result

        # Process each structure
        for struct_id, struct_data in structure_max_data.items():
            try:
                river = struct_data['river']
                reach = struct_data['reach']
                rs = struct_data['station']
                max_hw = struct_data.get('max_hw')
                max_tw = struct_data.get('max_tw')
                max_flow = struct_data.get('max_flow')

                # Skip if no useful data
                if max_hw is None and max_flow is None:
                    logger.debug(f"Skipping structure {struct_id}: no max HW or flow data")
                    result['skipped'] += 1
                    continue

                # Get current HTAB to get invert
                current_htab = GeomBridge.get_htab_dict(geom_file, river, reach, rs)

                if current_htab.get('invert') is None:
                    logger.warning(f"Skipping structure {struct_id}: no invert available")
                    result['skipped'] += 1
                    continue

                struct_invert = current_htab['invert']

                # Calculate optimal parameters
                # Use current values as defaults if results are missing
                effective_max_hw = max_hw if max_hw is not None else (current_htab.get('hw_max') or struct_invert + 10)
                effective_max_tw = max_tw if max_tw is not None else (current_htab.get('tw_max') or struct_invert + 5)
                effective_max_flow = max_flow if max_flow is not None else (current_htab.get('max_flow') or 10000)

                optimal = GeomHtabUtils.calculate_optimal_structure_htab(
                    struct_invert=struct_invert,
                    max_hw=effective_max_hw,
                    max_tw=effective_max_tw,
                    max_flow=effective_max_flow,
                    hw_safety=hw_safety_factor,
                    flow_safety=flow_safety_factor,
                    tw_safety=tw_safety_factor,
                    free_flow_points=free_flow_points,
                    submerged_curves=submerged_curves,
                    points_per_curve=points_per_curve
                )

                # Apply optimal parameters
                GeomBridge.set_htab(
                    geom_file=geom_file,
                    river=river,
                    reach=reach,
                    rs=rs,
                    hw_max=optimal['hw_max'],
                    tw_max=optimal['tw_max'],
                    max_flow=optimal['max_flow'],
                    use_user_curves=optimal['use_user_curves'],
                    free_flow_points=optimal['free_flow_points'],
                    submerged_curves=optimal['submerged_curves'],
                    points_per_curve=optimal['points_per_curve'],
                    validate=False  # Already calculated optimal values
                )

                result['modified'] += 1
                result['structures_processed'].append(struct_id)

                logger.debug(
                    f"Optimized structure {struct_id}: hw_max={optimal['hw_max']:.2f}, "
                    f"max_flow={optimal['max_flow']:.2f}"
                )

            except Exception as e:
                error_msg = f"Failed to optimize structure {struct_id}: {str(e)}"
                logger.error(error_msg)
                result['errors'].append(error_msg)

        logger.info(
            f"Structure HTAB optimization complete: {result['modified']} modified, "
            f"{result['skipped']} skipped, {len(result['errors'])} errors"
        )

        return result

    @staticmethod
    def _extract_structure_max_values(hdf_path: Path) -> Dict[str, Dict[str, Any]]:
        """
        Extract maximum headwater, tailwater, and flow for structures from HDF.

        This internal method reads the HDF file to find maximum hydraulic values
        for all structures (bridges, culverts, inline weirs).

        Parameters:
            hdf_path: Path to HDF results file

        Returns:
            dict: Mapping of structure ID to max values:
                {
                    'structure_id': {
                        'river': str,
                        'reach': str,
                        'station': str,
                        'max_hw': float,
                        'max_tw': float,
                        'max_flow': float
                    },
                    ...
                }
        """
        structure_data = {}

        try:
            with h5py.File(hdf_path, 'r') as hdf:
                # Try multiple possible paths for structure results
                possible_paths = [
                    "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections",
                    "Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/Unsteady Time Series/Cross Sections",
                ]

                # Try to find structures in the HDF
                # Structures are typically stored with their XS data or in separate datasets
                structures_base = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/SA/2D Area Connections"
                inline_base = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/SA/2D Area Inline"

                # Check for SA/2D Area Connections (bridges, culverts over 2D areas)
                if structures_base in hdf:
                    try:
                        conn_path = structures_base
                        # Look for structure-specific datasets
                        if "Connection Attributes" in hdf[conn_path]:
                            attrs = hdf[f"{conn_path}/Connection Attributes"][:]

                            # Get flow data if available
                            flow_data = None
                            if "Flow" in hdf[conn_path]:
                                flow_data = hdf[f"{conn_path}/Flow"][:]
                                max_flows = np.max(np.abs(flow_data), axis=0)

                            for i, attr in enumerate(attrs):
                                struct_id = f"SA_Conn_{i}"
                                try:
                                    name = attr['Name'].decode('utf-8').strip() if hasattr(attr['Name'], 'decode') else str(attr['Name'])
                                except:
                                    name = f"Connection_{i}"

                                structure_data[name] = {
                                    'river': 'SA_Connection',
                                    'reach': 'SA_Connection',
                                    'station': name,
                                    'max_hw': None,  # SA connections may not have explicit HW
                                    'max_tw': None,
                                    'max_flow': float(max_flows[i]) if flow_data is not None else None
                                }
                    except Exception as e:
                        logger.debug(f"Could not process SA connections: {e}")

                # Check for 1D inline structures
                inline_1d_base = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Lateral Structures"
                if inline_1d_base in hdf:
                    try:
                        # Similar processing for lateral/inline structures
                        pass  # Implement if needed
                    except Exception as e:
                        logger.debug(f"Could not process inline structures: {e}")

                # If no structure data found, try reading from geometry attributes
                # that might be stored in results
                if not structure_data:
                    logger.debug("No structure results found in standard HDF paths")

        except Exception as e:
            logger.warning(f"Error extracting structure max values: {str(e)}")

        return structure_data

    @staticmethod
    def get_optimization_report(
        geom_file: Union[str, Path],
        hdf_results_path: Union[str, Path],
        xs_safety_factor: float = 1.3,
        structure_hw_safety: float = 2.0
    ) -> str:
        """
        Generate markdown report showing current vs recommended HTAB parameters.

        This method analyzes the geometry file and HDF results to produce a
        report showing what HTAB optimizations would be made, without actually
        modifying the file.

        Parameters:
            geom_file: Path to geometry file (.g##)
            hdf_results_path: Path to plan HDF file with results
            xs_safety_factor: Safety factor for XS depth analysis
            structure_hw_safety: Safety factor for structure HW analysis

        Returns:
            str: Markdown-formatted report

        Example:
            >>> report = GeomHtab.get_optimization_report(
            ...     "model.g01", "model.p01.hdf"
            ... )
            >>> print(report)
            >>> # Or write to file:
            >>> Path("htab_report.md").write_text(report)
        """
        from .GeomCrossSection import GeomCrossSection
        from .GeomHtabUtils import GeomHtabUtils
        from ..hdf.HdfResultsXsec import HdfResultsXsec

        geom_file = Path(geom_file)
        hdf_results_path = Path(hdf_results_path)

        report_lines = [
            "# HTAB Optimization Report",
            "",
            f"**Geometry File**: {geom_file.name}",
            f"**HDF Results**: {hdf_results_path.name}",
            f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Analysis Parameters",
            "",
            f"- XS Safety Factor: {xs_safety_factor} ({(xs_safety_factor - 1) * 100:.0f}% safety)",
            f"- Structure HW Safety Factor: {structure_hw_safety} ({(structure_hw_safety - 1) * 100:.0f}% safety)",
            "",
            "---",
            ""
        ]

        # Analyze cross sections
        report_lines.append("## Cross Section HTAB Analysis")
        report_lines.append("")

        try:
            xs_timeseries = HdfResultsXsec.get_xsec_timeseries(hdf_results_path)
            cross_sections = xs_timeseries.coords['cross_section'].values
            rivers = xs_timeseries.coords['River'].values
            reaches = xs_timeseries.coords['Reach'].values
            stations = xs_timeseries.coords['Station'].values
            max_wse_values = xs_timeseries.coords['Maximum_Water_Surface'].values

            report_lines.append(f"Found {len(cross_sections)} cross sections with results.")
            report_lines.append("")
            report_lines.append("| Cross Section | Current Start El | Recommended | Current Inc | Recommended | Change |")
            report_lines.append("|---------------|------------------|-------------|-------------|-------------|--------|")

            changes_needed = 0
            for i, xs_name in enumerate(cross_sections[:20]):  # Limit to first 20 for readability
                try:
                    river = rivers[i]
                    reach = reaches[i]
                    rs = stations[i]
                    max_wse = float(max_wse_values[i])

                    if np.isnan(max_wse) or max_wse < -9998:
                        continue

                    current = GeomCrossSection.get_xs_htab_params(geom_file, river, reach, rs)

                    if current['invert'] is None:
                        continue

                    optimal = GeomHtabUtils.calculate_optimal_xs_htab(
                        invert=current['invert'],
                        max_wse=max_wse,
                        safety_factor=xs_safety_factor
                    )

                    curr_start = current['starting_el'] or 'N/A'
                    curr_inc = current['increment'] or 'N/A'

                    needs_change = (
                        curr_start != optimal['starting_el'] or
                        (isinstance(curr_inc, float) and abs(curr_inc - optimal['increment']) > 0.001)
                    )

                    change_flag = "YES" if needs_change else "no"
                    if needs_change:
                        changes_needed += 1

                    if isinstance(curr_start, float):
                        curr_start = f"{curr_start:.2f}"
                    if isinstance(curr_inc, float):
                        curr_inc = f"{curr_inc:.4f}"

                    report_lines.append(
                        f"| {xs_name[:30]} | {curr_start} | {optimal['starting_el']:.2f} | "
                        f"{curr_inc} | {optimal['increment']:.4f} | {change_flag} |"
                    )

                except Exception as e:
                    logger.debug(f"Could not analyze {xs_name}: {e}")

            if len(cross_sections) > 20:
                report_lines.append(f"| ... | | | | | |")
                report_lines.append(f"| ({len(cross_sections) - 20} more) | | | | | |")

            report_lines.append("")
            report_lines.append(f"**Cross sections needing optimization**: {changes_needed}")
            report_lines.append("")

        except Exception as e:
            report_lines.append(f"Error analyzing cross sections: {str(e)}")
            report_lines.append("")

        # Add recommendations section
        report_lines.extend([
            "---",
            "",
            "## Recommendations",
            "",
            "1. Run `GeomHtab.optimize_all_htab_from_results()` to apply optimizations",
            "2. After optimization, run geometric preprocessor (`clear_geompre=True`)",
            "3. Verify model opens correctly in HEC-RAS GUI",
            "4. Compare before/after results for stability",
            "",
            "---",
            "",
            "*Report generated by ras-commander GeomHtab*"
        ])

        return "\n".join(report_lines)
