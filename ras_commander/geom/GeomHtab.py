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
    - XS HTAB: 30% safety factor (1.3x) on depth is recommended; 500 points always
      (does not affect computation time, provides additional stability and internal resolution)
    - Structure HTAB: 100% safety factor (2.0x) on HW/TW/flow is recommended
    - Optimal structure HTAB: 100 free flow points, 60 submerged curves, 50 points per curve
    - Creates single backup before any modifications
    - If any step fails, backup can be used for manual recovery

References:
    - HEC-RAS User's Manual: Geometric Preprocessor
    - HEC-RAS User's Manual: HTAB Internal Boundaries Table
    - Paige Brue, Kleinschmidt: HTAB optimization best practices
    - feature_dev_notes/HTAB_Parameter_Modification/
"""

from pathlib import Path
from typing import Dict, Union, Any
from datetime import datetime

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
        structure_free_flow_points: int = 100,
        structure_submerged_curves: int = 60,
        structure_points_per_curve: int = 50,
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
            structure_free_flow_points: Points on free flow rating curve (optimal 100)
            structure_submerged_curves: Number of submerged rating curves (optimal 60)
            structure_points_per_curve: Points per submerged curve (optimal 50)
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
                logger.debug(f"Created unified backup: {backup_path}")
            except Exception as e:
                error_msg = f"Failed to create backup: {str(e)}"
                logger.error(error_msg)
                result['errors'].append(error_msg)
                raise IOError(error_msg)

        # Step 1: Optimize Cross Section HTAB
        logger.debug("Starting cross section HTAB optimization")
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
            logger.debug(f"Optimized {result['xs_modified']} cross sections")
        except Exception as e:
            error_msg = f"XS HTAB optimization failed: {str(e)}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
            # Continue to try structure optimization even if XS fails

        # Step 2: Optimize Structure HTAB
        logger.debug("Starting structure HTAB optimization")
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
            logger.debug(f"Optimized {result['structures_modified']} structures")
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

        Delegates to GeomCrossSection.optimize_xs_htab_from_results() which uses
        batch I/O (single read/write cycle) for optimal performance.

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

        See Also:
            - GeomCrossSection.optimize_xs_htab_from_results(): Batch implementation
        """
        from .GeomCrossSection import GeomCrossSection

        # Delegate to GeomCrossSection's batch implementation (125x faster)
        xs_result = GeomCrossSection.optimize_xs_htab_from_results(
            geom_file=geom_file,
            hdf_results_path=hdf_results_path,
            safety_factor=safety_factor,
            increment=target_increment,
            num_points=max_points,
            create_backup=create_backup
        )

        # Adapt return schema from GeomCrossSection format to GeomHtab format
        return {
            'modified': xs_result.get('modified_count', 0),
            'skipped': xs_result.get('skipped_count', 0),
            'errors': [
                f"Failed to optimize XS: {mod.get('error', 'unknown')}"
                for mod in xs_result.get('modifications', [])
                if mod.get('status') == 'failed'
            ] if xs_result.get('modifications') else [],
            'params_summary': {
                'min_increment': xs_result.get('min_increment'),
                'max_increment': xs_result.get('max_increment'),
                'avg_increment': xs_result.get('avg_increment'),
            },
            'backup': xs_result.get('backup_path')
        }

    @staticmethod
    @log_call
    def optimize_structures_htab_from_results(
        geom_file: Union[str, Path],
        hdf_results_path: Union[str, Path],
        hw_safety_factor: float = 2.0,
        flow_safety_factor: float = 2.0,
        tw_safety_factor: float = 2.0,
        free_flow_points: int = 100,
        submerged_curves: int = 60,
        points_per_curve: int = 50,
        create_backup: bool = True
    ) -> Dict[str, Any]:
        """
        Optimize HTAB parameters for ALL structures from HDF results.

        Delegates to GeomBridge.optimize_all_structures_from_results() which uses
        HdfStruc1D for robust HDF extraction and processes all structure types.

        Parameters:
            geom_file: Path to geometry file (.g##)
            hdf_results_path: Path to plan HDF file with results
            hw_safety_factor: Safety factor for headwater (default 2.0 = 100%)
            flow_safety_factor: Safety factor for flow (default 2.0 = 100%)
            tw_safety_factor: Safety factor for tailwater (default 2.0 = 100%)
            free_flow_points: Points on free flow curve (default 100, optimal 100)
            submerged_curves: Number of submerged curves (default 60, optimal 60)
            points_per_curve: Points per submerged curve (default 50, optimal 50)
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

        See Also:
            - GeomBridge.optimize_all_structures_from_results(): Full implementation
        """
        from .GeomBridge import GeomBridge

        # Delegate to GeomBridge's implementation (uses HdfStruc1D for robust extraction)
        bridge_result = GeomBridge.optimize_all_structures_from_results(
            geom_file=geom_file,
            hdf_results_path=hdf_results_path,
            hw_safety_factor=hw_safety_factor,
            flow_safety_factor=flow_safety_factor,
            tw_safety_factor=tw_safety_factor,
            free_flow_points=free_flow_points,
            submerged_curves=submerged_curves,
            points_per_curve=points_per_curve,
            create_backup=create_backup
        )

        # Adapt return schema from GeomBridge format to GeomHtab format
        # Build structures_processed list from successful detail entries
        structures_processed = [
            f"{d.get('struct_type', 'Structure')} {d.get('river', '')}/{d.get('reach', '')}/RS {d.get('rs', '')}"
            for d in bridge_result.get('details', [])
            if d.get('status') == 'optimized'
        ]

        return {
            'modified': bridge_result.get('optimized', 0),
            'skipped': bridge_result.get('total', 0) - bridge_result.get('optimized', 0) - bridge_result.get('failed', 0),
            'errors': bridge_result.get('errors', []),
            'structures_processed': structures_processed,
            'backup': bridge_result.get('backup_path')
        }

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
