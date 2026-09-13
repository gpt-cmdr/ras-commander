"""
Shared utility functions for RasCheck submodules.

Contains helper methods extracted from RasCheck that are used by
multiple domain check modules.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple

import pandas as pd
import numpy as np
import h5py

from ..LoggingConfig import get_logger
from .types import Severity, FlowType, CheckMessage, CheckResults

logger = get_logger(__name__)


def resolve_hdf_paths(
    plan: Union[str, Path],
    ras_obj
) -> Tuple[Path, Path]:
    """
    Resolve plan and geometry HDF paths from plan identifier.

    HEC-RAS 6.x stores geometry data in plan HDF files, so geometry HDF
    is optional. Falls back to plan HDF if geometry HDF doesn't exist.

    Returns:
        Tuple of (plan_hdf_path, geom_hdf_path)
        Note: geom_hdf_path may equal plan_hdf_path if no separate geometry HDF exists
    """
    if isinstance(plan, str) and len(plan) <= 3:
        # Plan number format (e.g., "01")
        matching = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == plan]
        if matching.empty:
            raise ValueError(f"Plan '{plan}' not found. Available: {ras_obj.plan_df['plan_number'].tolist()}")
        plan_row = matching.iloc[0]
        plan_hdf = Path(plan_row['HDF_Results_Path'])
        geom_path = plan_row['Geom Path']
        # Get geometry HDF from geometry file path
        # Pattern: Muncie.g01 -> Muncie.g01.hdf (append .hdf, don't replace suffix)
        geom_base = Path(str(geom_path))
        geom_hdf = geom_base.parent / f"{geom_base.name}.hdf"
    else:
        plan_hdf = Path(plan)
        # Derive geometry HDF from plan HDF name
        # Pattern: project.p01.hdf -> project.g01.hdf
        plan_stem = plan_hdf.stem  # e.g., "project.p01"
        if '.p' in plan_stem:
            geom_stem = plan_stem.replace('.p', '.g', 1)
        else:
            geom_stem = plan_stem
        geom_hdf = plan_hdf.parent / f"{geom_stem}.hdf"

    # Fall back to plan HDF if geometry HDF doesn't exist
    # HEC-RAS 6.x plan HDF files contain geometry data
    if not geom_hdf.exists():
        logger.debug(f"Geometry HDF not found at {geom_hdf}, using plan HDF for geometry data")
        geom_hdf = plan_hdf

    return plan_hdf, geom_hdf


def verify_steady_plan(plan_hdf: Path) -> bool:
    """Check if plan contains steady flow results."""
    try:
        with h5py.File(plan_hdf, 'r') as hdf:
            return 'Results/Steady' in hdf
    except Exception:
        return False


def detect_flow_type(plan_hdf: Path) -> FlowType:
    """
    Detect the flow type of a plan HDF file.

    Args:
        plan_hdf: Path to plan HDF file

    Returns:
        FlowType enum indicating steady, unsteady, or geometry_only

    Note:
        - Checks for 'Results/Steady' for steady flow
        - Checks for 'Results/Unsteady' for unsteady flow
        - Returns GEOMETRY_ONLY if no results found
    """
    try:
        with h5py.File(plan_hdf, 'r') as hdf:
            has_steady = 'Results/Steady' in hdf
            has_unsteady = 'Results/Unsteady' in hdf

            if has_steady and not has_unsteady:
                return FlowType.STEADY
            elif has_unsteady:
                # Unsteady takes precedence if both exist (rare edge case)
                return FlowType.UNSTEADY
            else:
                return FlowType.GEOMETRY_ONLY
    except Exception as e:
        logger.warning("Could not detect flow type; assuming geometry-only checks")
        logger.debug("Flow type detection failed for %s: %s", plan_hdf, e)
        return FlowType.GEOMETRY_ONLY


def has_2d_mesh(plan_hdf: Path) -> bool:
    """
    Check if plan contains 2D mesh results.

    Args:
        plan_hdf: Path to plan HDF file

    Returns:
        True if 2D flow areas are present in results
    """
    try:
        with h5py.File(plan_hdf, 'r') as hdf:
            # Check for 2D flow area results
            unsteady_path = 'Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas'
            return unsteady_path in hdf
    except Exception:
        return False


def get_available_profiles(plan_hdf: Path) -> List[str]:
    """Get list of available profile names from HDF."""
    try:
        with h5py.File(plan_hdf, 'r') as hdf:
            path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names'
            if path in hdf:
                names = hdf[path][:]
                return [n.decode('utf-8').strip() for n in names]
    except Exception:
        pass
    return []


def calculate_statistics(results: CheckResults) -> Dict:
    """Calculate summary statistics from check results."""
    return {
        'total_messages': len(results.messages),
        'error_count': results.get_error_count(),
        'warning_count': results.get_warning_count(),
        'info_count': len(results.filter_by_severity(Severity.INFO)),
        'nt_messages': len(results.filter_by_check_type('NT')),
        'xs_messages': len(results.filter_by_check_type('XS')),
        'struct_messages': len(results.filter_by_check_type('STRUCT')),
        'fw_messages': len(results.filter_by_check_type('FW')),
        'profiles_messages': len(results.filter_by_check_type('PROFILES'))
    }


def get_structure_locations(geom_hdf: Path) -> Optional[pd.DataFrame]:
    """
    Get structure locations with abutment stations for floodway checks.

    Args:
        geom_hdf: Path to geometry HDF file

    Returns:
        DataFrame with columns: river, reach, station, abut_left, abut_right
        or None if no structures found
    """
    try:
        with h5py.File(geom_hdf, 'r') as hdf:
            if 'Geometry/Structures/Attributes' not in hdf:
                return None

            attrs = hdf['Geometry/Structures/Attributes'][:]

            records = []
            for attr in attrs:
                river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                # Get abutment stations if available
                abut_l = float(attr['BR US Left Bank']) if 'BR US Left Bank' in attr.dtype.names else 0
                abut_r = float(attr['BR US Right Bank']) if 'BR US Right Bank' in attr.dtype.names else 0

                records.append({
                    'river': river,
                    'reach': reach,
                    'station': station,
                    'abut_left': abut_l,
                    'abut_right': abut_r
                })

            return pd.DataFrame(records)

    except Exception as e:
        logger.debug(f"Could not get structure locations: {e}")
        return None


def find_column_by_keywords(df: pd.DataFrame, keywords: list, all_required: bool = True) -> Optional[str]:
    """
    Find a DataFrame column whose name contains all (or any) of the given keywords.

    Args:
        df: DataFrame to search
        keywords: List of keyword strings to match (case-insensitive)
        all_required: If True, column must contain ALL keywords. If False, ANY keyword.

    Returns:
        Matching column name, or None if not found
    """
    keywords_lower = [k.lower() for k in keywords]
    for col in df.columns:
        col_lower = col.lower()
        if all_required:
            if all(kw in col_lower for kw in keywords_lower):
                return col
        else:
            if any(kw in col_lower for kw in keywords_lower):
                return col
    return None
