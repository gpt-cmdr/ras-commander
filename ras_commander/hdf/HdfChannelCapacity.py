# ras_commander/hdf/HdfChannelCapacity.py
"""
1D Channel Capacity Analysis for HEC-RAS models.

Determines the capacity level of each 1D cross section by comparing maximum
water surface elevations from multiple AEP storm simulations against bank
elevations. Results are aggregated into segments and summarized as a
system-wide capacity distribution.

This analysis follows the HCFCD (Harris County Flood Control District) channel
capacity methodology, testing storms from smallest to largest and recording the
largest storm each cross section can contain without overtopping.

Capacity Levels:
    1: X <= 10% AEP (contained by 10-year or smaller)
    2: 10% < X <= 4% AEP
    3: 4% < X <= 2% AEP
    4: 2% < X <= 1% AEP
    5: 1% < X <= 0.2% AEP
    6: X > 0.2% AEP (contains all tested storms)
    7: All overtop (overtopped by smallest tested storm)

Example:
    >>> from ras_commander import init_ras_project, HdfChannelCapacity
    >>>
    >>> init_ras_project("/path/to/project", "7.0")
    >>>
    >>> results = HdfChannelCapacity.analyze_channel_capacity(
    ...     geom_hdf="01",
    ...     plan_inputs=["01", "02", "03", "04", "05", "06", "07"],
    ...     storm_order=['50P', '20P', '10P', '4P', '2P', '1P', '0.2P']
    ... )
    >>> print(results['summary'])
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import logging

import numpy as np
import pandas as pd

from ..LoggingConfig import log_call, get_logger

logger = get_logger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Storm order from most frequent (smallest) to least frequent (largest)
STORM_ORDER = ['50P', '20P', '10P', '4P', '2P', '1P', '0.2P']

# Capacity category labels by level
CATEGORY_TO_LEVEL = {
    'X <= 10%': 1,
    '10% < X <= 4%': 2,
    '4% < X <= 2%': 3,
    '2% < X <= 1%': 4,
    '1% < X <= 0.2%': 5,
    'X > 0.2%': 6,
    'All overtop': 7,
}
LEVEL_TO_CATEGORY = {v: k for k, v in CATEGORY_TO_LEVEL.items()}

# Maps last-contained storm to capacity category
CAPACITY_MAP = {
    '50P': 'X <= 10%',
    '20P': '10% < X <= 4%',
    '10P': '4% < X <= 2%',
    '4P': '2% < X <= 1%',
    '2P': '1% < X <= 0.2%',
    '1P': 'X > 0.2%',
}

# Default segment length: 0.25 miles = 1320 feet
DEFAULT_SEGMENT_LENGTH = 1320.0


class HdfChannelCapacity:
    """
    1D channel capacity analysis for HEC-RAS models.

    Compares maximum water surface elevations from multiple AEP storm
    simulations against bank elevations to determine channel capacity at
    each cross section. Results are aggregated into segments and summarized
    as a system-wide capacity distribution.

    All methods are static — do not instantiate this class.

    Example:
        >>> from ras_commander import HdfChannelCapacity
        >>> banks = HdfChannelCapacity.extract_bank_elevations("g01.hdf")
        >>> wse = HdfChannelCapacity.extract_max_wse(["p01.hdf", "p02.hdf"])
        >>> capacity = HdfChannelCapacity.determine_capacity(banks, wse)
    """

    # -----------------------------------------------------------------
    # Private helper
    # -----------------------------------------------------------------

    @staticmethod
    def _standardize_hdf_input(
        hdf_input: Union[str, Path],
        label: str,
        ras_object: Any
    ) -> Path:
        """
        Standardize HDF input to a Path object.

        Handles three input types:
        1. Plan/geometry number (e.g., "01") — resolves via ras_object
        2. HDF filename (e.g., "plan.p01.hdf") — resolves via ras_object folder
        3. Full path (e.g., "/path/to/plan.p01.hdf") — uses directly

        Args:
            hdf_input: Plan number, filename, or full path
            label: Label for error messages (e.g., "geometry", "plan 01")
            ras_object: RAS project object for resolving numbers/filenames

        Returns:
            Resolved HDF file path

        Raises:
            ValueError: If input cannot be resolved
        """
        from ras_commander.hdf import HdfUtils

        hdf_kind = "geometry" if label.lower().startswith("geometry") else "plan"
        return HdfUtils.resolve_hdf_input(
            hdf_input,
            label=label,
            ras_object=ras_object,
            hdf_kind=hdf_kind,
        )

    # -----------------------------------------------------------------
    # Public methods
    # -----------------------------------------------------------------

    @staticmethod
    @log_call
    def extract_bank_elevations(
        geom_hdf: Union[str, Path],
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Extract bank elevations at each 1D cross section.

        Uses np.interp() on station-elevation arrays at the Left Bank and
        Right Bank station positions from HdfXsec.get_cross_sections().
        The controlling (higher) bank elevation is also computed.

        Args:
            geom_hdf: Path to geometry HDF file, geometry number (e.g., "01"),
                     or HDF filename. Uses @_standardize_hdf_input resolution.
            ras_object: Optional RAS project object for multi-project workflows.

        Returns:
            DataFrame with columns:
                River, Reach, RS, Left Bank, Right Bank,
                left_bank_elev, right_bank_elev, controlling_bank_elev,
                Len Channel
        """
        from ras_commander.hdf import HdfXsec
        from ras_commander import ras as global_ras

        _ras = ras_object if ras_object is not None else global_ras

        # Resolve geometry HDF path
        geom_path = HdfChannelCapacity._standardize_hdf_input(
            geom_hdf, "geometry", _ras
        )

        if not geom_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_path}")

        logger.info(f"Extracting bank elevations from: {geom_path.name}")

        xs_gdf = HdfXsec.get_cross_sections(str(geom_path), ras_object=_ras)

        if xs_gdf is None or len(xs_gdf) == 0:
            raise ValueError("No cross sections found in geometry HDF.")

        rows = []
        for _, row in xs_gdf.iterrows():
            sta_elev = row['station_elevation']  # Nx2 ndarray
            if sta_elev is None or len(sta_elev) == 0:
                continue

            stations = sta_elev[:, 0]
            elevations = sta_elev[:, 1]

            left_bank_sta = row.get('Left Bank', np.nan)
            right_bank_sta = row.get('Right Bank', np.nan)

            if np.isnan(left_bank_sta) or np.isnan(right_bank_sta):
                continue

            left_elev = float(np.interp(left_bank_sta, stations, elevations))
            right_elev = float(np.interp(right_bank_sta, stations, elevations))
            controlling = max(left_elev, right_elev)

            rows.append({
                'River': row['River'],
                'Reach': row['Reach'],
                'RS': row['RS'],
                'Left Bank': left_bank_sta,
                'Right Bank': right_bank_sta,
                'left_bank_elev': left_elev,
                'right_bank_elev': right_elev,
                'controlling_bank_elev': controlling,
                'Len Channel': row.get('Len Channel', 0.0),
            })

        bank_df = pd.DataFrame(rows)
        logger.info(f"Extracted bank elevations for {len(bank_df)} cross sections")
        return bank_df

    @staticmethod
    @log_call
    def extract_steady_profile_wse(
        plan_hdf: Union[str, Path],
        profile_names: Optional[List[str]] = None,
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Extract individual steady-state profile WSE from a single plan HDF.

        Unlike extract_max_wse() which collapses all profiles to a single max,
        this method preserves each profile as a separate column — required for
        channel capacity analysis on steady-state plans with multiple AEP profiles.

        Typical use case: FEMA BLE models with 7 steady-state profiles
        (10-yr, 25-yr, 50-yr, etc.) stored in one plan.

        Args:
            plan_hdf: Path to plan HDF file, plan number, or HDF filename.
            profile_names: Optional list of names for the WSE columns. If None,
                          reads profile names from the HDF file (e.g.,
                          ['10-year', '25-year', '50-year', ...]).
                          If provided, must match the number of profiles in the HDF.
            ras_object: Optional RAS project object for multi-project workflows.

        Returns:
            DataFrame with columns:
                River, Reach, RS, plus one WSE column per steady-state profile

        Raises:
            FileNotFoundError: If the HDF file does not exist.
            ValueError: If the HDF contains no steady-state results,
                       or profile_names length doesn't match profile count.
        """
        import h5py
        from ras_commander import ras as global_ras

        _ras = ras_object if ras_object is not None else global_ras

        hdf_path = HdfChannelCapacity._standardize_hdf_input(
            plan_hdf, "plan (steady profiles)", _ras
        )

        if not hdf_path.exists():
            raise FileNotFoundError(f"HDF file not found: {hdf_path}")

        logger.info(f"Extracting steady-state profiles from: {hdf_path.name}")

        base_steady = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"

        with h5py.File(hdf_path, 'r') as hdf:
            # Read water surface data: shape (n_profiles, n_xs)
            ws_path = f"{base_steady}/Cross Sections/Water Surface"
            if ws_path not in hdf:
                raise ValueError(
                    f"No steady-state Water Surface data found in {hdf_path.name}. "
                    f"This method requires a steady-state plan HDF."
                )

            ws_data = hdf[ws_path][:]  # shape: (n_profiles, n_xs)
            n_profiles, n_xs = ws_data.shape

            # Read profile names from HDF if not provided
            names_path = f"{base_steady}/Profile Names"
            if profile_names is None:
                if names_path in hdf:
                    hdf_names = [n.decode().strip() for n in hdf[names_path][:]]
                    profile_names = hdf_names
                else:
                    profile_names = [f"Profile_{i+1:02d}" for i in range(n_profiles)]

            if len(profile_names) != n_profiles:
                raise ValueError(
                    f"profile_names has {len(profile_names)} entries but HDF "
                    f"contains {n_profiles} profiles"
                )

            # Read cross section attributes
            attrs_path = f"{base_steady}/Cross Sections/Cross Section Attributes"
            if attrs_path not in hdf:
                # Fallback: try geometry info
                attrs_path = "Results/Steady/Output/Geometry Info/Cross Section Attributes"

            attrs = hdf[attrs_path][:]
            xs_rivers = [a['River'].decode().strip() for a in attrs]
            xs_reaches = [a['Reach'].decode().strip() for a in attrs]
            xs_stations = [a['Station'].decode().strip() for a in attrs]

        # Build DataFrame with one column per profile
        result = {
            'River': xs_rivers,
            'Reach': xs_reaches,
            'RS': xs_stations,
        }
        for i, pname in enumerate(profile_names):
            result[pname] = ws_data[i, :]

        result_df = pd.DataFrame(result)

        logger.info(
            f"Extracted {n_profiles} steady profiles for {n_xs} cross sections "
            f"from {hdf_path.name}"
        )
        return result_df

    @staticmethod
    @log_call
    def extract_max_wse(
        plan_inputs: Union[str, Path, List[Union[str, Path]]],
        profile_names: Optional[List[str]] = None,
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Extract maximum water surface elevation at each XS from one or more plans.

        Auto-detects format using a 3-level detection chain:
        1. RAS 6.x unsteady (pre-calculated Maximum Water Surface)
        2. RAS 5.x unsteady (Water Surface time series → max across time)
        3. Steady-state (Water Surface profiles → max across profiles)

        Args:
            plan_inputs: Single plan path/number or list of plan paths/numbers.
                        Each entry is resolved via _standardize_hdf_input.
            profile_names: Optional list of profile/storm names corresponding to
                          each plan input. If None, uses "Plan_01", "Plan_02", etc.
            ras_object: Optional RAS project object for multi-project workflows.

        Returns:
            DataFrame with columns:
                River, Reach, RS, plus one WSE column per plan
                (named by profile_names or "Plan_XX")
        """
        import h5py
        from ras_commander import ras as global_ras

        _ras = ras_object if ras_object is not None else global_ras

        # Normalize to list
        if not isinstance(plan_inputs, list):
            plan_inputs = [plan_inputs]

        if profile_names is None:
            profile_names = [f"Plan_{i+1:02d}" for i in range(len(plan_inputs))]

        if len(profile_names) != len(plan_inputs):
            raise ValueError(
                f"Length mismatch: {len(plan_inputs)} plans but {len(profile_names)} profile names"
            )

        result_df = None

        for plan_input, pname in zip(plan_inputs, profile_names):
            hdf_path = HdfChannelCapacity._standardize_hdf_input(
                plan_input, f"plan ({pname})", _ras
            )

            if not hdf_path.exists():
                logger.warning(f"HDF not found for {pname}: {hdf_path}")
                continue

            logger.info(f"Extracting Max WSE from {hdf_path.name} as '{pname}'")

            max_wse_values = None
            xs_rivers = None
            xs_reaches = None
            xs_stations = None

            with h5py.File(hdf_path, 'r') as hdf:
                # Path constants
                base_unsteady = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections"
                base_steady = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections"

                # --- Format 1: RAS 6.x unsteady (pre-calculated max) ---
                try:
                    ws_ds = hdf[f"{base_unsteady}/Water Surface"]
                    ws_data = ws_ds[:]
                    max_wse_values = np.max(ws_data, axis=0)

                    attrs_ds = hdf[f"{base_unsteady}/Cross Section Attributes"]
                    attrs = attrs_ds[:]
                    xs_rivers = [a['River'].decode('utf-8').strip() for a in attrs]
                    xs_reaches = [a['Reach'].decode('utf-8').strip() for a in attrs]
                    xs_stations = [a['Station'].decode('utf-8').strip() for a in attrs]

                    logger.debug(f"  Format: RAS 6.x/5.x unsteady ({len(max_wse_values)} XS)")
                except KeyError:
                    pass

                # --- Format 2: Steady-state profiles ---
                if max_wse_values is None:
                    try:
                        ws_ds = hdf[f"{base_steady}/Water Surface"]
                        ws_data = ws_ds[:]  # shape: (n_profiles, n_xs)
                        max_wse_values = np.max(ws_data, axis=0)

                        attrs_ds = hdf[f"{base_steady}/Cross Section Attributes"]
                        attrs = attrs_ds[:]
                        xs_rivers = [a['River'].decode('utf-8').strip() for a in attrs]
                        xs_reaches = [a['Reach'].decode('utf-8').strip() for a in attrs]
                        xs_stations = [a['Station'].decode('utf-8').strip() for a in attrs]

                        logger.debug(f"  Format: Steady-state ({len(max_wse_values)} XS)")
                    except KeyError:
                        pass

            if max_wse_values is None:
                logger.warning(f"Could not extract WSE from {hdf_path.name}")
                continue

            plan_df = pd.DataFrame({
                'River': xs_rivers,
                'Reach': xs_reaches,
                'RS': xs_stations,
                pname: max_wse_values,
            })

            if result_df is None:
                result_df = plan_df
            else:
                result_df = result_df.merge(
                    plan_df, on=['River', 'Reach', 'RS'], how='outer'
                )

        if result_df is None:
            raise ValueError("No WSE data extracted from any plan input.")

        logger.info(
            f"Extracted Max WSE: {len(result_df)} XS, "
            f"{len([c for c in result_df.columns if c not in ('River','Reach','RS')])} plans"
        )
        return result_df

    @staticmethod
    @log_call
    def determine_capacity(
        bank_elevations: pd.DataFrame,
        max_wse: pd.DataFrame,
        storm_order: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Determine capacity level at each cross section.

        Tests storms from smallest (most frequent) to largest (least frequent).
        For each XS, the capacity level corresponds to the largest storm the
        channel can contain without the WSE exceeding the controlling bank elevation.

        Args:
            bank_elevations: DataFrame from extract_bank_elevations() with columns:
                            River, Reach, RS, controlling_bank_elev, Len Channel
            max_wse: DataFrame from extract_max_wse() with columns:
                    River, Reach, RS, plus one WSE column per storm
            storm_order: Ordered list of storm column names in max_wse, from
                        smallest to largest. If None, uses non-key columns in order.

        Returns:
            DataFrame with columns:
                River, Reach, RS, controlling_bank_elev, Len Channel,
                capacity_level, capacity_category, last_contained_storm,
                plus one boolean overtop column per storm
        """
        # Merge bank elevations with WSE data
        merged = bank_elevations.merge(max_wse, on=['River', 'Reach', 'RS'], how='inner')

        if len(merged) == 0:
            logger.warning("No matching cross sections between bank elevations and WSE data")
            return pd.DataFrame()

        # Determine storm columns
        if storm_order is None:
            key_cols = {'River', 'Reach', 'RS', 'Left Bank', 'Right Bank',
                        'left_bank_elev', 'right_bank_elev', 'controlling_bank_elev',
                        'Len Channel'}
            storm_order = [c for c in merged.columns if c not in key_cols]

        n_xs = len(merged)
        n_storms = len(storm_order)

        bank_elev = merged['controlling_bank_elev'].values

        # Vectorized capacity determination
        # Start assuming all XS are contained (level 6 = contains all storms)
        capacity_level = np.full(n_xs, 6, dtype=int)
        last_contained_storm = np.full(n_xs, '', dtype=object)
        still_contained = np.ones(n_xs, dtype=bool)

        for i, storm in enumerate(storm_order):
            if storm not in merged.columns:
                logger.warning(f"Storm column '{storm}' not found in WSE data, skipping")
                continue

            wse_values = merged[storm].values
            # Mark NaN WSE as not overtopping (no data = not overtopping)
            overtops = np.where(np.isnan(wse_values), False, wse_values > bank_elev)

            # Create boolean overtop column
            merged[f'overtop_{storm}'] = overtops

            # XS that were still contained but now overtop
            newly_overtopped = still_contained & overtops

            if i == 0:
                # Overtopped by smallest storm → level 7 (All overtop)
                capacity_level[newly_overtopped] = 7
            else:
                # Capacity = level corresponding to this storm index
                # Level 1 = overtopped at 2nd storm (was only contained by 1st)
                # etc.
                capacity_level[newly_overtopped] = i

            # Update last contained storm for XS that were contained before this storm
            if i > 0:
                # XS that are about to lose containment had their last contained = previous storm
                last_contained_storm[newly_overtopped] = storm_order[i - 1]

            still_contained = still_contained & ~overtops

        # XS still contained after all storms → level 6
        capacity_level[still_contained] = 6
        last_contained_storm[still_contained] = storm_order[-1] if storm_order else ''

        # XS overtopped by first storm have no last contained storm
        level7_mask = capacity_level == 7
        last_contained_storm[level7_mask] = 'None'

        # Map levels to categories
        capacity_category = np.array([LEVEL_TO_CATEGORY.get(lv, 'Unknown') for lv in capacity_level])

        merged['capacity_level'] = capacity_level
        merged['capacity_category'] = capacity_category
        merged['last_contained_storm'] = last_contained_storm

        # Log summary
        for level in sorted(LEVEL_TO_CATEGORY.keys()):
            count = np.sum(capacity_level == level)
            if count > 0:
                logger.info(f"  Level {level} ({LEVEL_TO_CATEGORY[level]}): {count} XS")

        return merged

    @staticmethod
    @log_call
    def segment_channel(
        capacity_df: pd.DataFrame,
        segment_length: float = DEFAULT_SEGMENT_LENGTH
    ) -> pd.DataFrame:
        """
        Aggregate cross section capacity into fixed-length channel segments.

        Groups XS by River/Reach and creates segments of the specified length.
        Each segment's capacity is the weighted average of its constituent XS
        capacities (weighted by Len Channel), rounded DOWN (FLOOR) for
        conservative assessment.

        Args:
            capacity_df: DataFrame from determine_capacity() with columns:
                        River, Reach, RS, capacity_level, Len Channel
            segment_length: Segment length in model units (default 1320 ft = 0.25 mi)

        Returns:
            DataFrame with columns:
                River, Reach, segment_id, segment_start_rs, segment_end_rs,
                weighted_capacity, capacity_level (floored), capacity_category,
                channel_length, xs_count
        """
        if len(capacity_df) == 0:
            return pd.DataFrame()

        segments = []

        for (river, reach), group in capacity_df.groupby(['River', 'Reach']):
            # Sort by RS (river station) — convert to float for sorting
            group = group.copy()
            try:
                group['RS_float'] = group['RS'].astype(float)
            except (ValueError, TypeError):
                # RS may contain non-numeric chars; try extracting leading number
                group['RS_float'] = group['RS'].apply(
                    lambda x: float(''.join(c for c in str(x) if c in '0123456789.') or '0')
                )
            group = group.sort_values('RS_float', ascending=False)  # Downstream order

            # Compute cumulative channel length
            len_channel = group['Len Channel'].values
            cumulative_length = np.cumsum(len_channel)

            # Determine segment boundaries
            total_length = cumulative_length[-1] if len(cumulative_length) > 0 else 0
            n_segments = max(1, int(np.ceil(total_length / segment_length)))

            for seg_idx in range(n_segments):
                seg_start = seg_idx * segment_length
                seg_end = min((seg_idx + 1) * segment_length, total_length)

                # Find XS in this segment
                if seg_idx == 0:
                    mask = cumulative_length <= seg_end
                else:
                    mask = (cumulative_length > seg_start) & (cumulative_length <= seg_end)

                seg_xs = group[mask]
                if len(seg_xs) == 0:
                    continue

                # Weighted average capacity
                weights = seg_xs['Len Channel'].values
                capacities = seg_xs['capacity_level'].values
                total_weight = weights.sum()

                if total_weight > 0:
                    weighted_cap = np.average(capacities, weights=weights)
                else:
                    weighted_cap = np.mean(capacities)

                # FLOOR for conservative assessment
                floored_level = int(np.floor(weighted_cap))
                floored_level = max(1, min(7, floored_level))  # Clamp to valid range

                segments.append({
                    'River': river,
                    'Reach': reach,
                    'segment_id': seg_idx + 1,
                    'segment_start_rs': seg_xs['RS'].iloc[0],
                    'segment_end_rs': seg_xs['RS'].iloc[-1],
                    'weighted_capacity': round(weighted_cap, 2),
                    'capacity_level': floored_level,
                    'capacity_category': LEVEL_TO_CATEGORY.get(floored_level, 'Unknown'),
                    'channel_length': total_weight,
                    'xs_count': len(seg_xs),
                })

        result = pd.DataFrame(segments)
        logger.info(f"Created {len(result)} segments across {capacity_df[['River','Reach']].drop_duplicates().shape[0]} reaches")
        return result

    @staticmethod
    @log_call
    def system_capacity_summary(
        capacity_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Generate system-wide capacity distribution summary (Table 2).

        Groups cross sections by capacity level and computes the total
        channel length and percentage at each level.

        Args:
            capacity_df: DataFrame from determine_capacity() with columns:
                        capacity_level, Len Channel

        Returns:
            DataFrame with columns:
                capacity_level, capacity_category,
                channel_length_ft, percent_of_total

            Sorted by capacity_level (1-7). Percentages sum to 100%.
        """
        if len(capacity_df) == 0:
            return pd.DataFrame()

        summary = capacity_df.groupby('capacity_level').agg(
            channel_length_ft=('Len Channel', 'sum'),
            xs_count=('RS', 'count')
        ).reset_index()

        total_length = summary['channel_length_ft'].sum()
        summary['percent_of_total'] = (
            summary['channel_length_ft'] / total_length * 100
        ).round(1)

        summary['capacity_category'] = summary['capacity_level'].map(LEVEL_TO_CATEGORY)

        # Ensure all levels 1-7 are present
        all_levels = pd.DataFrame({
            'capacity_level': range(1, 8),
            'capacity_category': [LEVEL_TO_CATEGORY[i] for i in range(1, 8)]
        })
        summary = all_levels.merge(summary, on=['capacity_level', 'capacity_category'], how='left')
        summary['channel_length_ft'] = summary['channel_length_ft'].fillna(0)
        summary['percent_of_total'] = summary['percent_of_total'].fillna(0)
        summary['xs_count'] = summary['xs_count'].fillna(0).astype(int)

        summary = summary.sort_values('capacity_level').reset_index(drop=True)

        logger.info("System Capacity Summary:")
        for _, row in summary.iterrows():
            if row['channel_length_ft'] > 0:
                logger.info(
                    f"  Level {row['capacity_level']} ({row['capacity_category']}): "
                    f"{row['channel_length_ft']:.0f} ft ({row['percent_of_total']:.1f}%)"
                )

        return summary[['capacity_level', 'capacity_category', 'channel_length_ft',
                        'percent_of_total', 'xs_count']]

    @staticmethod
    @log_call
    def analyze_channel_capacity(
        geom_hdf: Union[str, Path],
        plan_inputs: Union[str, Path, List[Union[str, Path]]],
        storm_order: Optional[List[str]] = None,
        profile_names: Optional[List[str]] = None,
        segment_length: float = DEFAULT_SEGMENT_LENGTH,
        ras_object: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Complete channel capacity analysis pipeline.

        Orchestrates all steps: bank elevation extraction, WSE extraction,
        capacity determination, segment aggregation, and system summary.

        Args:
            geom_hdf: Geometry HDF path, number, or filename
            plan_inputs: List of plan HDF paths/numbers (one per storm)
            storm_order: Storm names in order from smallest to largest.
                        Must match profile_names if provided.
            profile_names: Names for WSE columns. If None but storm_order
                          is provided, uses storm_order as profile_names.
            segment_length: Segment length for aggregation (default 1320 ft)
            ras_object: Optional RAS project object

        Returns:
            Dict with keys:
                xs_capacity: DataFrame — per-XS capacity levels
                segments: DataFrame — aggregated segment capacities
                summary: DataFrame — system capacity distribution (Table 2)
                bank_elevations: DataFrame — bank elevations at each XS
                max_wse: DataFrame — max WSE from each plan
        """
        # Use storm_order as profile names if profile_names not provided
        if profile_names is None and storm_order is not None:
            profile_names = storm_order

        # Step 1: Extract bank elevations
        bank_elevations = HdfChannelCapacity.extract_bank_elevations(
            geom_hdf, ras_object=ras_object
        )

        # Step 2: Extract max WSE
        max_wse = HdfChannelCapacity.extract_max_wse(
            plan_inputs, profile_names=profile_names, ras_object=ras_object
        )

        # Step 3: Determine capacity
        xs_capacity = HdfChannelCapacity.determine_capacity(
            bank_elevations, max_wse, storm_order=storm_order
        )

        # Step 4: Segment aggregation
        segments = HdfChannelCapacity.segment_channel(
            xs_capacity, segment_length=segment_length
        )

        # Step 5: System summary
        summary = HdfChannelCapacity.system_capacity_summary(xs_capacity)

        logger.info("Channel capacity analysis complete")
        return {
            'xs_capacity': xs_capacity,
            'segments': segments,
            'summary': summary,
            'bank_elevations': bank_elevations,
            'max_wse': max_wse,
        }

    @staticmethod
    @log_call
    def compare_conditions(
        existing_results: Dict[str, Any],
        proposed_results: Dict[str, Any]
    ) -> pd.DataFrame:
        """
        Compare channel capacity between existing and proposed conditions.

        Produces a side-by-side comparison at each cross section showing
        capacity level changes between two analysis results.

        Args:
            existing_results: Dict from analyze_channel_capacity() for existing conditions
            proposed_results: Dict from analyze_channel_capacity() for proposed conditions

        Returns:
            DataFrame with columns:
                River, Reach, RS,
                existing_level, existing_category,
                proposed_level, proposed_category,
                change (positive = improved),
                improved (bool)
        """
        existing_cap = existing_results['xs_capacity'][
            ['River', 'Reach', 'RS', 'capacity_level', 'capacity_category']
        ].rename(columns={
            'capacity_level': 'existing_level',
            'capacity_category': 'existing_category'
        })

        proposed_cap = proposed_results['xs_capacity'][
            ['River', 'Reach', 'RS', 'capacity_level', 'capacity_category']
        ].rename(columns={
            'capacity_level': 'proposed_level',
            'capacity_category': 'proposed_category'
        })

        comparison = existing_cap.merge(proposed_cap, on=['River', 'Reach', 'RS'], how='outer')

        # Map levels to effective ordering for comparison.
        # Level 7 (overtopped by smallest storm) is WORSE than Level 1,
        # so map it to 0 for correct change calculation.
        # Ordering: 7(worst=0) < 1 < 2 < 3 < 4 < 5 < 6(best)
        def _effective(level):
            return 0 if level == 7 else level

        eff_existing = comparison['existing_level'].apply(_effective)
        eff_proposed = comparison['proposed_level'].apply(_effective)

        # Positive change = improvement (higher effective level = more capacity)
        comparison['change'] = eff_proposed - eff_existing
        comparison['improved'] = comparison['change'] > 0

        n_improved = comparison['improved'].sum()
        n_degraded = (comparison['change'] < 0).sum()
        n_unchanged = (comparison['change'] == 0).sum()

        logger.info(f"Capacity comparison: {n_improved} improved, {n_degraded} degraded, {n_unchanged} unchanged")

        return comparison
