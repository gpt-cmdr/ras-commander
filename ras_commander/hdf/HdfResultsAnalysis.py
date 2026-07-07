"""
Critical duration and cross-plan analysis for HEC-RAS results.

Provides methods for comparing results across multiple plan HDF files,
including identification of critical storm duration at reference locations.
"""

from numbers import Number
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
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
        variable: str = 'Water Surface',
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
        variable : str, default 'Water Surface'
            Native HDF reference output variable to compare across plans.
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
        from ras_commander.hdf.HdfResultsXsec import HdfResultsXsec
        from ras_commander import ras as global_ras

        _ras = ras_object if ras_object is not None else global_ras
        _ras.check_initialized()

        reftype = reftype.lower().strip()
        if reftype not in {"lines", "points"}:
            raise ValueError("reftype must be either 'lines' or 'points'")

        if not isinstance(variable, str) or not variable.strip():
            raise ValueError("variable must be a non-empty HDF dataset name")
        variable = variable.strip()

        if plan_labels is None:
            plan_labels = {pn: pn for pn in plan_numbers}

        # Extract peaks from each plan
        plan_peaks = {}
        for raw_plan_num in plan_numbers:
            plan_num = HdfResultsAnalysis._normalize_plan_number(raw_plan_num)
            label = plan_labels.get(plan_num, plan_labels.get(raw_plan_num, raw_plan_num))
            plan_hdf, path_source = HdfResultsAnalysis._resolve_plan_hdf_path(_ras, plan_num)

            if not plan_hdf.exists():
                logger.warning(
                    f"Skipping plan {plan_num} ({label}): plan HDF not found at "
                    f"{plan_hdf} (resolved from {path_source})"
                )
                continue

            try:
                if reftype == 'lines':
                    ds = HdfResultsXsec.get_ref_lines_timeseries(
                        plan_hdf,
                        variables=variable,
                    )
                else:
                    ds = HdfResultsXsec.get_ref_points_timeseries(
                        plan_hdf,
                        variables=variable,
                    )

                if variable not in ds.data_vars:
                    available = ", ".join(sorted(ds.data_vars)) or "none"
                    logger.warning(
                        f"Skipping plan {plan_num} ({label}): variable '{variable}' "
                        f"not found in {reftype} reference timeseries at {plan_hdf} "
                        f"(resolved from {path_source}); available variables: {available}"
                    )
                    continue

                # Extract peak for each reference location
                peaks = HdfResultsAnalysis._extract_reference_peaks(
                    ds,
                    reftype=reftype,
                    variable=variable,
                )
                if not peaks:
                    logger.warning(
                        f"Skipping plan {plan_num} ({label}): no named {reftype} "
                        f"reference features found for variable '{variable}' in {plan_hdf} "
                        f"(resolved from {path_source})"
                    )
                    continue

                plan_peaks[label] = peaks
                logger.debug(f"Plan {plan_num} ({label}): extracted peaks for {len(peaks)} locations")

            except Exception as e:
                logger.error(
                    f"Skipping plan {plan_num} ({label}): failed to extract {reftype} "
                    f"reference timeseries variable '{variable}' from {plan_hdf} "
                    f"(resolved from {path_source}): {type(e).__name__}: {e}"
                )

        if not plan_peaks:
            logger.warning(
                f"No reference timeseries data extracted from {len(plan_numbers)} plan(s) "
                f"for reftype={reftype}, variable='{variable}'; returning empty DataFrame"
            )
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
            f"Critical duration analysis (reftype={reftype}, variable='{variable}'): "
            f"{len(result)} locations, "
            f"{n_exceed} exceeding {threshold_pct}% threshold"
        )
        return result

    @staticmethod
    def _normalize_plan_number(plan_number: Any) -> str:
        """Normalize plan identifiers to the zero-padded p## number."""
        try:
            missing = pd.isna(plan_number)
            if isinstance(missing, (bool, np.bool_)) and missing:
                return ""
        except (TypeError, ValueError):
            pass

        if isinstance(plan_number, Number) and not isinstance(plan_number, bool):
            number = float(plan_number)
            if np.isfinite(number) and number.is_integer():
                return f"{int(number):02d}"

        text = str(plan_number).strip()
        if text.lower().startswith('p'):
            text = text[1:]
        if text.isdigit():
            return text.zfill(2)
        try:
            number = float(text)
            if number.is_integer():
                return f"{int(number):02d}"
        except ValueError:
            pass
        return text

    @staticmethod
    def _has_path_value(value: Any) -> bool:
        """Return True when a plan_df path-like cell is populated."""
        if value is None:
            return False

        try:
            missing = pd.isna(value)
            if isinstance(missing, (bool, np.bool_)) and missing:
                return False
        except (TypeError, ValueError):
            pass

        text = str(value).strip()
        return bool(text) and text.lower() not in {'nan', 'nat', 'none'}

    @staticmethod
    def _resolve_plan_hdf_path(_ras: Any, plan_num: str) -> Tuple[Path, str]:
        """Resolve a plan results HDF path, preferring plan_df metadata."""
        fallback = Path(_ras.project_folder) / f"{_ras.project_name}.p{plan_num}.hdf"
        plan_df = getattr(_ras, 'plan_df', None)

        if plan_df is None or plan_df.empty:
            return fallback, "fallback project path (plan_df unavailable)"

        if 'plan_number' not in plan_df.columns:
            return fallback, "fallback project path (plan_df has no plan_number column)"

        normalized_numbers = plan_df['plan_number'].map(
            HdfResultsAnalysis._normalize_plan_number
        )
        matching = plan_df[normalized_numbers == plan_num]
        if matching.empty:
            return (
                fallback,
                f"fallback project path (no plan_df row matched plan_number {plan_num})",
            )

        row = matching.iloc[0]
        if (
            'HDF_Results_Path' in row.index
            and HdfResultsAnalysis._has_path_value(row['HDF_Results_Path'])
        ):
            return Path(str(row['HDF_Results_Path'])), "plan_df HDF_Results_Path"

        if (
            'full_path' in row.index
            and HdfResultsAnalysis._has_path_value(row['full_path'])
        ):
            return Path(f"{row['full_path']}.hdf"), "plan_df full_path + .hdf"

        return (
            fallback,
            "fallback project path (matched plan_df row has no populated "
            "HDF_Results_Path or full_path)",
        )

    @staticmethod
    def _extract_reference_peaks(
        ds: Any,
        reftype: str,
        variable: str,
    ) -> Dict[str, float]:
        """Extract per-feature peak values from a native reference output dataset."""
        coord_name = 'refln_name' if reftype == 'lines' else 'refpt_name'
        feature_dim = 'refln_id' if reftype == 'lines' else 'refpt_id'
        data = ds[variable]

        if 'time' not in data.dims:
            raise ValueError(
                f"Variable '{variable}' has dimensions {data.dims}; expected a time dimension"
            )
        if feature_dim not in data.dims:
            raise ValueError(
                f"Variable '{variable}' has dimensions {data.dims}; expected {feature_dim}"
            )
        if coord_name not in data.coords:
            raise ValueError(
                f"Variable '{variable}' is missing coordinate {coord_name}"
            )

        peak_data = data.max(dim='time', skipna=True)
        extra_dims = [dim for dim in peak_data.dims if dim != feature_dim]
        if extra_dims:
            raise ValueError(
                f"Variable '{variable}' has unsupported dimensions after time max: "
                f"{peak_data.dims}"
            )

        names = peak_data.coords[coord_name].values
        values = peak_data.transpose(feature_dim).values
        peaks = {}
        for name, value in zip(names, values):
            location = str(name).strip()
            if location:
                peaks[location] = float(value)
        return peaks
