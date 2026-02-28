"""
Critical duration and cross-plan analysis for HEC-RAS results.

Provides methods for comparing results across multiple plan HDF files,
including identification of critical storm duration at reference locations.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import logging

import pandas as pd
import numpy as np

from ras_commander.LoggingConfig import log_call

logger = logging.getLogger(__name__)


class HdfResultsAnalysis:
    """
    Cross-plan comparison and critical duration analysis for HEC-RAS results.

    This class follows the HdfBenefitAreas pattern — a standalone analysis class
    in the hdf/ subpackage that compares results across multiple plan HDF files.

    All methods are static — no instantiation required.

    Example:
        >>> from ras_commander import HdfResultsAnalysis
        >>> # Compare peaks across storm duration plans
        >>> result = HdfResultsAnalysis.analyze_critical_duration(
        ...     plan_numbers=['01', '02', '03'],
        ...     plan_labels={'01': '6hr', '02': '12hr', '03': '24hr'},
        ...     threshold_pct=5.0
        ... )
        >>> print(result[['location', 'critical_plan', 'max_peak']])
    """

    @staticmethod
    @log_call
    def analyze_critical_duration(
        plan_numbers: List[str],
        locations: Optional[List[str]] = None,
        threshold_pct: float = 5.0,
        plan_labels: Optional[Dict[str, str]] = None,
        reftype: str = 'lines',
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Identify critical storm duration by comparing peaks across multiple plans.

        For each reference location, extracts peak values from each plan's HDF
        file and identifies which plan produces the highest peak. Computes
        percentage differences and flags locations exceeding the threshold.

        Parameters
        ----------
        plan_numbers : list of str
            Plan numbers to compare (e.g., ['01', '02', '03'])
        locations : list of str, optional
            Subset of reference locations to analyze. If None, uses all
            locations found in the HDF files.
        threshold_pct : float, default 5.0
            Percentage difference threshold for flagging (e.g., R7's 5% rule).
            Locations where the difference between max and second-max peak
            exceeds this threshold are flagged.
        plan_labels : dict, optional
            Mapping of plan_number → descriptive label (e.g., {'01': '6hr'}).
            Used for column naming in output. If None, plan numbers are used.
        reftype : str, default 'lines'
            Reference type for HDF extraction ('lines' or 'points')
        ras_object : optional
            Custom RAS object to use instead of the global one

        Returns
        -------
        pd.DataFrame
            One row per location with columns:
            - location: Reference name
            - peak_{label}: Peak value for each plan
            - critical_plan: Plan label with highest peak
            - max_peak: Highest peak value across plans
            - second_peak: Second highest peak value
            - pct_diff: Percentage difference between max and second peak
            - exceeds_threshold: Boolean flag if pct_diff > threshold_pct

        Example
        -------
        >>> from ras_commander import HdfResultsAnalysis
        >>> result = HdfResultsAnalysis.analyze_critical_duration(
        ...     plan_numbers=['01', '02', '03'],
        ...     plan_labels={'01': '6hr', '02': '12hr', '03': '24hr'}
        ... )
        >>> critical = result[result['exceeds_threshold']]
        >>> print(f"{len(critical)} locations exceed {5.0}% threshold")
        """
        from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan
        from ras_commander import ras as global_ras

        _ras = ras_object if ras_object is not None else global_ras
        _ras.check_initialized()

        if plan_labels is None:
            plan_labels = {pn: pn for pn in plan_numbers}

        # Extract peaks from each plan
        plan_peaks = {}
        for plan_num in plan_numbers:
            label = plan_labels.get(plan_num, plan_num)
            plan_hdf = _ras.project_folder / f"{_ras.project_name}.p{plan_num}.hdf"

            if not plan_hdf.exists():
                logger.warning(f"Plan HDF not found: {plan_hdf}")
                continue

            try:
                ts_df = HdfResultsPlan.get_reference_timeseries(plan_hdf, reftype=reftype)
                if ts_df.empty:
                    logger.warning(f"No reference timeseries in plan {plan_num}")
                    continue

                # Extract peak for each reference location
                peaks = {}
                for col in ts_df.columns:
                    if col == 'Time':
                        continue
                    peaks[col] = float(ts_df[col].max())

                plan_peaks[label] = peaks
                logger.info(f"Plan {plan_num} ({label}): extracted peaks for {len(peaks)} locations")

            except Exception as e:
                logger.error(f"Error processing plan {plan_num}: {e}")

        if not plan_peaks:
            logger.warning("No plan data could be extracted")
            return pd.DataFrame()

        # Collect all locations across plans
        all_locations = set()
        for peaks in plan_peaks.values():
            all_locations.update(peaks.keys())

        if locations is not None:
            all_locations = {loc for loc in all_locations if loc in locations}

        # Build comparison table
        rows = []
        labels = list(plan_peaks.keys())
        for loc in sorted(all_locations):
            row = {'location': loc}

            peak_values = []
            for label in labels:
                peak = plan_peaks.get(label, {}).get(loc, np.nan)
                row[f'peak_{label}'] = peak
                if not np.isnan(peak):
                    peak_values.append((label, peak))

            if len(peak_values) >= 2:
                # Sort by peak value descending
                peak_values.sort(key=lambda x: x[1], reverse=True)
                row['critical_plan'] = peak_values[0][0]
                row['max_peak'] = peak_values[0][1]
                row['second_peak'] = peak_values[1][1]

                if peak_values[1][1] > 0:
                    pct_diff = 100.0 * (peak_values[0][1] - peak_values[1][1]) / peak_values[1][1]
                else:
                    pct_diff = np.nan
                row['pct_diff'] = pct_diff
                row['exceeds_threshold'] = pct_diff > threshold_pct if not np.isnan(pct_diff) else False

            elif len(peak_values) == 1:
                row['critical_plan'] = peak_values[0][0]
                row['max_peak'] = peak_values[0][1]
                row['second_peak'] = np.nan
                row['pct_diff'] = np.nan
                row['exceeds_threshold'] = False
            else:
                row['critical_plan'] = None
                row['max_peak'] = np.nan
                row['second_peak'] = np.nan
                row['pct_diff'] = np.nan
                row['exceeds_threshold'] = False

            rows.append(row)

        result = pd.DataFrame(rows)
        n_exceed = result['exceeds_threshold'].sum() if not result.empty else 0
        logger.info(
            f"Critical duration analysis: {len(result)} locations, "
            f"{n_exceed} exceeding {threshold_pct}% threshold"
        )
        return result
