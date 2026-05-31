# ras_commander/hdf/HdfChannelCapacity.py
"""
1D Channel Capacity Analysis for HEC-RAS models.

Determines the capacity level of each 1D cross section by comparing maximum
water surface elevations from multiple AEP storm simulations against bank
elevations. Results are aggregated into 0.25-mile segments and summarized as a
system-wide capacity distribution.

This analysis uses an AEP (annual-exceedance-probability) storm-sweep
methodology, testing storms from smallest to largest and recording the largest
storm each cross section can contain without overtopping.

Capacity Levels:
    1: Contains 50% AEP (2-year) or less
    2: Contains 20% AEP (5-year)
    3: Contains 10% AEP (10-year)
    4: Contains 4% AEP (25-year)
    5: Contains 2% AEP (50-year)
    6: Contains 1% AEP (100-year)
    7: Contains 0.2% AEP (500-year)

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
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from ..LoggingConfig import log_call, get_logger

logger = get_logger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Storm order from most frequent (smallest) to least frequent (largest)
STORM_ORDER = ['50P', '20P', '10P', '4P', '2P', '1P', '0.2P']

# Capacity category labels by level.
LEVEL_TO_CATEGORY = {
    1: '<=2-yr',
    2: '5-yr',
    3: '10-yr',
    4: '25-yr',
    5: '50-yr',
    6: '100-yr',
    7: '>=500-yr',
}

CATEGORY_TO_LEVEL = {category: level for level, category in LEVEL_TO_CATEGORY.items()}
CATEGORY_TO_LEVEL.update({
    '<= 2-yr': 1,
    '2-yr': 1,
    '5-year': 2,
    '10-year': 3,
    '25-year': 4,
    '50-year': 5,
    '100-year': 6,
    '500-year': 7,
    'X <= 10%': 1,
    '10% < X <= 4%': 2,
    '4% < X <= 2%': 3,
    '2% < X <= 1%': 4,
    '1% < X <= 0.2%': 5,
    'X > 0.2%': 6,
    'X > 0.2% (500-yr)': 7,
    'Unknown': 0,
})

# Maps last-contained storm to capacity category
CAPACITY_MAP = {
    None: LEVEL_TO_CATEGORY[1],
    '50P': LEVEL_TO_CATEGORY[1],
    '20P': LEVEL_TO_CATEGORY[2],
    '10P': LEVEL_TO_CATEGORY[3],
    '4P': LEVEL_TO_CATEGORY[4],
    '2P': LEVEL_TO_CATEGORY[5],
    '1P': LEVEL_TO_CATEGORY[6],
    '0.2P': LEVEL_TO_CATEGORY[7],
}

STORM_TO_LEVEL = {storm: CATEGORY_TO_LEVEL[category] for storm, category in CAPACITY_MAP.items()}

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

        input_str = str(hdf_input)

        # Case 1: Full path (contains directory separators)
        if '/' in input_str or '\\' in input_str:
            return Path(hdf_input)

        # Case 2: HDF filename (ends with .hdf)
        if input_str.endswith('.hdf'):
            if ras_object is None or not hasattr(ras_object, 'folder'):
                raise ValueError(
                    f"Cannot resolve HDF filename '{input_str}' without initialized project."
                )
            return Path(ras_object.folder) / input_str

        # Case 3: Plan/geometry number
        plan_number = input_str.lstrip('pgPG')

        if ras_object is None:
            raise ValueError(
                f"Cannot resolve number '{plan_number}' without initialized project."
            )

        try:
            project_folder = ras_object.folder
            hdfs = HdfUtils.resolve_hdf_paths(
                project_folder, plan_number, ras_object=ras_object
            )
            # Try plan HDF first, fall back to geometry HDF
            hdf_path = hdfs.get('plan') or hdfs.get('geom')
            if hdf_path is not None:
                return Path(hdf_path)
            return Path(project_folder) / f"unknown.p{plan_number}.hdf"
        except Exception as e:
            logger.warning(f"Could not resolve {label} '{input_str}': {e}")
            if hasattr(ras_object, 'folder') and ras_object.folder:
                return Path(ras_object.folder) / f"unknown.p{plan_number}.hdf"
            raise ValueError(f"Failed to resolve {label} '{input_str}': {e}")

    @staticmethod
    def _decode_hdf_value(value: Any) -> str:
        """Decode bytes, numpy bytes, or scalar HDF values to stripped strings."""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore").strip()
        if hasattr(value, "decode"):
            try:
                return value.decode("utf-8", errors="ignore").strip()
            except TypeError:
                pass
        return str(value).strip()

    @staticmethod
    def _decode_hdf_strings(values: Sequence[Any]) -> List[str]:
        """Decode an HDF string vector to Python strings."""
        return [HdfChannelCapacity._decode_hdf_value(value) for value in values]

    @staticmethod
    def _structured_field_names(array: np.ndarray) -> Dict[str, str]:
        """Map normalized structured-array field names to their original names."""
        dtype_names = array.dtype.names or ()
        return {name.lower().replace(" ", "").replace("_", ""): name for name in dtype_names}

    @staticmethod
    def _get_structured_value(record: Any, field_map: Dict[str, str], candidates: Sequence[str]) -> str:
        """Read the first matching field from a structured HDF attribute record."""
        for candidate in candidates:
            key = candidate.lower().replace(" ", "").replace("_", "")
            field_name = field_map.get(key)
            if field_name is not None:
                return HdfChannelCapacity._decode_hdf_value(record[field_name])
        return ""

    @staticmethod
    def _read_cross_section_attributes(hdf: Any, n_xs: int) -> Tuple[List[str], List[str], List[str]]:
        """
        Read River, Reach, and RS values from known HEC-RAS HDF result paths.

        RAS plan HDF files vary by version and result type. This helper searches
        summary output, unsteady time series, steady profiles, and embedded
        geometry metadata before falling back to positional station labels.
        """
        attr_paths = [
            "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/Cross Sections/Cross Section Attributes",
            "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Cross Sections/Cross Section Attributes",
            "Results/Unsteady/Output/Geometry Info/Cross Section Attributes",
            "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Cross Section Attributes",
            "Results/Steady/Output/Geometry Info/Cross Section Attributes",
            "Geometry/Cross Sections/Attributes",
        ]

        for attr_path in attr_paths:
            if attr_path not in hdf:
                continue

            attrs = hdf[attr_path][:]
            if len(attrs) == 0 or attrs.dtype.names is None:
                continue

            field_map = HdfChannelCapacity._structured_field_names(attrs)
            rivers = [
                HdfChannelCapacity._get_structured_value(row, field_map, ("River", "River Name"))
                for row in attrs
            ]
            reaches = [
                HdfChannelCapacity._get_structured_value(row, field_map, ("Reach", "Reach Name"))
                for row in attrs
            ]
            stations = [
                HdfChannelCapacity._get_structured_value(row, field_map, ("Station", "RS", "River Station"))
                for row in attrs
            ]

            if len(stations) >= n_xs and any(stations):
                return rivers[:n_xs], reaches[:n_xs], stations[:n_xs]

        logger.warning(
            "Could not find cross-section attributes in HDF; using positional station labels."
        )
        return (
            [""] * n_xs,
            [""] * n_xs,
            [str(i + 1) for i in range(n_xs)],
        )

    @staticmethod
    def _as_1d_wse(values: np.ndarray, reducer: str) -> np.ndarray:
        """Normalize HDF WSE arrays to one value per cross section."""
        array = np.asarray(values, dtype=float)
        if array.ndim == 0:
            return array.reshape(1)
        if array.ndim == 1:
            return array
        if reducer == "first":
            return array[0, :]
        return np.nanmax(array, axis=0)

    @staticmethod
    def _select_profile_index(profile_names: List[str], profile_name: Optional[str]) -> Optional[int]:
        """Find a steady-profile index using exact or case-insensitive matching."""
        if profile_name is None:
            return None

        normalized_target = profile_name.strip().lower()
        for idx, name in enumerate(profile_names):
            if name.strip().lower() == normalized_target:
                return idx
        return None

    @staticmethod
    def _extract_single_plan_wse(
        hdf_path: Path,
        profile_name: Optional[str] = None
    ) -> Tuple[np.ndarray, Tuple[List[str], List[str], List[str]], str]:
        """
        Extract one WSE vector from a plan HDF using production fallback order.

        Detection order:
        1. RAS 6.x unsteady summary Maximum Water Surface
        2. RAS 5.x/6.x unsteady Water Surface time series max
        3. Steady Water Surface profile selection or profile-wise max
        """
        import h5py

        summary_path = (
            "Results/Unsteady/Output/Output Blocks/Base Output/"
            "Summary Output/Cross Sections/Maximum Water Surface"
        )
        unsteady_path = (
            "Results/Unsteady/Output/Output Blocks/Base Output/"
            "Unsteady Time Series/Cross Sections/Water Surface"
        )
        steady_base = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
        steady_wse_path = f"{steady_base}/Cross Sections/Water Surface"
        steady_names_path = f"{steady_base}/Profile Names"

        with h5py.File(hdf_path, "r") as hdf:
            if summary_path in hdf:
                wse = HdfChannelCapacity._as_1d_wse(hdf[summary_path][:], reducer="first")
                attrs = HdfChannelCapacity._read_cross_section_attributes(hdf, len(wse))
                return wse, attrs, "unsteady_summary"

            if unsteady_path in hdf:
                wse = HdfChannelCapacity._as_1d_wse(hdf[unsteady_path][:], reducer="max")
                attrs = HdfChannelCapacity._read_cross_section_attributes(hdf, len(wse))
                return wse, attrs, "unsteady_timeseries"

            if steady_wse_path in hdf:
                wse_data = np.asarray(hdf[steady_wse_path][:], dtype=float)
                if wse_data.ndim == 1:
                    wse = wse_data
                    profile_source = "steady_single_profile"
                else:
                    profile_names = []
                    if steady_names_path in hdf:
                        profile_names = HdfChannelCapacity._decode_hdf_strings(hdf[steady_names_path][:])

                    profile_idx = HdfChannelCapacity._select_profile_index(profile_names, profile_name)
                    if profile_idx is not None:
                        wse = wse_data[profile_idx, :]
                        profile_source = f"steady_profile:{profile_names[profile_idx]}"
                    elif profile_name is not None:
                        available = ", ".join(profile_names) if profile_names else "no profile names found"
                        raise ValueError(
                            f"Steady profile '{profile_name}' not found in {hdf_path.name}; "
                            f"available profiles: {available}"
                        )
                    else:
                        wse = np.nanmax(wse_data, axis=0)
                        profile_source = "steady_profile_max"

                attrs = HdfChannelCapacity._read_cross_section_attributes(hdf, len(wse))
                return wse, attrs, profile_source

        raise ValueError(
            f"No supported 1D WSE dataset found in {hdf_path.name}. "
            "Expected unsteady summary, unsteady time series, or steady profiles."
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
                thalweg_elev, channel_depth, Len Channel
        """
        from ras_commander.hdf import HdfXsec
        from ras_commander import ras as global_ras

        _ras = ras_object if ras_object is not None else global_ras

        # Resolve geometry HDF path
        geom_path = HdfChannelCapacity._standardize_hdf_input(
            geom_hdf, "geometry", _ras
        )

        # If the input looks like a plan number, try to find the geometry HDF
        input_str = str(geom_hdf)
        if not input_str.endswith('.hdf') and '/' not in input_str and '\\' not in input_str:
            # May be a geometry number — try resolving via geom_df
            geom_num = input_str.lstrip('gG')
            if hasattr(_ras, 'geom_df') and _ras.geom_df is not None and len(_ras.geom_df) > 0:
                matches = _ras.geom_df[_ras.geom_df['geom_number'] == geom_num]
                if len(matches) > 0:
                    geom_file = Path(matches.iloc[0]['full_path'])
                    geom_path = geom_file.with_suffix(geom_file.suffix + '.hdf')

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
            thalweg = float(np.nanmin(elevations))

            rows.append({
                'River': row['River'],
                'Reach': row['Reach'],
                'RS': row['RS'],
                'Left Bank': left_bank_sta,
                'Right Bank': right_bank_sta,
                'left_bank_elev': left_elev,
                'right_bank_elev': right_elev,
                'controlling_bank_elev': controlling,
                'thalweg_elev': thalweg,
                'channel_depth': controlling - thalweg,
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

            ws_data = np.asarray(hdf[ws_path][:], dtype=float)
            if ws_data.ndim == 1:
                ws_data = ws_data.reshape(1, -1)
            n_profiles, n_xs = ws_data.shape

            # Read profile names from HDF if not provided
            names_path = f"{base_steady}/Profile Names"
            if profile_names is None:
                if names_path in hdf:
                    profile_names = HdfChannelCapacity._decode_hdf_strings(hdf[names_path][:])
                else:
                    profile_names = [f"Profile_{i+1:02d}" for i in range(n_profiles)]

            if len(profile_names) != n_profiles:
                raise ValueError(
                    f"profile_names has {len(profile_names)} entries but HDF "
                    f"contains {n_profiles} profiles"
                )

            xs_rivers, xs_reaches, xs_stations = HdfChannelCapacity._read_cross_section_attributes(
                hdf, n_xs
            )

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
        plan_inputs: Union[
            str,
            Path,
            Dict[str, Union[str, Path, Tuple[Union[str, Path], str]]],
            List[Union[str, Path]]
        ],
        profile_names: Optional[List[str]] = None,
        steady_profile_names: Optional[Union[str, List[Optional[str]], Dict[str, str]]] = None,
        ras_object: Optional[Any] = None
    ) -> pd.DataFrame:
        """
        Extract maximum water surface elevation at each XS from one or more plans.

        Auto-detects format using the following fallback chain:
        1. RAS 6.x unsteady summary output (Maximum Water Surface)
        2. RAS 5.x/6.x unsteady time series (Water Surface -> max across time)
        3. Steady-state profiles (selected profile or max across profiles)

        Args:
            plan_inputs: Single plan path/number or list of plan paths/numbers.
                        A dict may be used as {output_column: plan_input}; dict
                        values may also be (plan_input, steady_profile_name).
            profile_names: Optional list of profile/storm names corresponding to
                          each plan input. If None, uses "Plan_01", "Plan_02", etc.
            steady_profile_names: Optional steady-state profile name(s) to select
                          from plan HDF files. Use a string for one input, a list
                          matching plan_inputs, or a dict keyed by output column.
            ras_object: Optional RAS project object for multi-project workflows.

        Returns:
            DataFrame with columns:
                River, Reach, RS, plus one WSE column per plan
                (named by profile_names or "Plan_XX")
        """
        from ras_commander import ras as global_ras

        _ras = ras_object if ras_object is not None else global_ras

        steady_profiles_by_name: Dict[str, Optional[str]] = {}

        if isinstance(plan_inputs, dict):
            normalized_inputs = []
            normalized_names = []
            for name, value in plan_inputs.items():
                if isinstance(value, tuple):
                    plan_value, steady_name = value
                    steady_profiles_by_name[name] = steady_name
                else:
                    plan_value = value
                normalized_names.append(name)
                normalized_inputs.append(plan_value)
            plan_inputs = normalized_inputs
            if profile_names is None:
                profile_names = normalized_names
        elif not isinstance(plan_inputs, list):
            plan_inputs = [plan_inputs]

        if profile_names is None:
            profile_names = [f"Plan_{i+1:02d}" for i in range(len(plan_inputs))]

        if len(profile_names) != len(plan_inputs):
            raise ValueError(
                f"Length mismatch: {len(plan_inputs)} plans but {len(profile_names)} profile names"
            )

        if isinstance(steady_profile_names, str):
            steady_profile_lookup = [steady_profile_names]
        elif isinstance(steady_profile_names, dict):
            steady_profile_lookup = [
                steady_profile_names.get(name, steady_profiles_by_name.get(name))
                for name in profile_names
            ]
        elif steady_profile_names is None:
            steady_profile_lookup = [
                steady_profiles_by_name.get(name)
                for name in profile_names
            ]
        else:
            steady_profile_lookup = list(steady_profile_names)

        if len(steady_profile_lookup) == 1 and len(plan_inputs) > 1:
            steady_profile_lookup = steady_profile_lookup * len(plan_inputs)

        if len(steady_profile_lookup) != len(plan_inputs):
            raise ValueError(
                "steady_profile_names must be a string, dict, or list matching plan_inputs"
            )

        result_df = None

        for plan_input, pname, steady_profile_name in zip(
            plan_inputs, profile_names, steady_profile_lookup
        ):
            hdf_path = HdfChannelCapacity._standardize_hdf_input(
                plan_input, f"plan ({pname})", _ras
            )

            if not hdf_path.exists():
                logger.warning(f"HDF not found for {pname}: {hdf_path}")
                continue

            logger.info(f"Extracting Max WSE from {hdf_path.name} as '{pname}'")

            try:
                max_wse_values, attrs, source = HdfChannelCapacity._extract_single_plan_wse(
                    hdf_path,
                    profile_name=steady_profile_name,
                )
                xs_rivers, xs_reaches, xs_stations = attrs
                logger.debug(
                    f"  Format: {source} ({len(max_wse_values)} XS)"
                )
            except Exception as exc:
                logger.warning(f"Could not extract WSE from {hdf_path.name}: {exc}")
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
        The sweep stops at the first overtopping event for each cross section,
        which is the conservative interpretation of channel capacity.

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

        # Vectorized capacity determination. Start at Level 1, then promote
        # cross sections as they contain progressively larger events.
        capacity_level = np.ones(n_xs, dtype=int)
        last_contained_storm = np.full(n_xs, 'None', dtype=object)
        still_testing = np.ones(n_xs, dtype=bool)

        for storm in storm_order:
            if storm not in merged.columns:
                logger.warning(f"Storm column '{storm}' not found in WSE data, skipping")
                continue

            wse_values = merged[storm].values
            valid = ~np.isnan(wse_values)
            contained = still_testing & valid & (wse_values <= bank_elev)
            overtops = still_testing & valid & (wse_values > bank_elev)

            # Create boolean overtop column
            merged[f'overtop_{storm}'] = overtops

            if np.any(contained):
                capacity_level[contained] = STORM_TO_LEVEL.get(storm, capacity_level[contained])
                last_contained_storm[contained] = storm

            # Stop testing after first overtopping. This preserves the
            # production behavior when bad/nonmonotonic WSE data are present.
            still_testing[overtops] = False

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
            if 'Len Channel' in group.columns:
                len_channel = pd.to_numeric(group['Len Channel'], errors='coerce').fillna(0.0).values
            else:
                len_channel = np.zeros(len(group), dtype=float)
            cumulative_length = np.zeros(len(group), dtype=float)
            if len(group) > 1:
                cumulative_length[1:] = np.cumsum(len_channel[:-1])
            group['cumulative_distance_ft'] = cumulative_length

            # Determine segment boundaries
            total_length = float(np.nansum(len_channel))
            if total_length <= 0 and len(cumulative_length) > 0:
                total_length = float(cumulative_length[-1])
            n_segments = max(1, int(np.ceil(total_length / segment_length)))

            for seg_idx in range(n_segments):
                seg_start = seg_idx * segment_length
                seg_end = min((seg_idx + 1) * segment_length, total_length)
                if total_length <= 0:
                    seg_end = segment_length

                # Find XS in this segment
                if seg_idx == n_segments - 1:
                    mask = (cumulative_length >= seg_start) & (cumulative_length <= seg_end)
                else:
                    mask = (cumulative_length >= seg_start) & (cumulative_length < seg_end)

                seg_xs = group[mask]
                if len(seg_xs) == 0:
                    continue

                # Weighted average capacity
                if 'Len Channel' in seg_xs.columns:
                    weights = pd.to_numeric(seg_xs['Len Channel'], errors='coerce').fillna(0.0).values
                else:
                    weights = np.zeros(len(seg_xs), dtype=float)
                capacities = seg_xs['capacity_level'].values
                total_weight = weights.sum()

                if total_weight > 0:
                    weighted_cap = np.average(capacities, weights=weights)
                else:
                    weighted_cap = np.mean(capacities)

                # FLOOR for conservative assessment
                floored_level = int(np.floor(weighted_cap))
                floored_level = max(1, min(7, floored_level))  # Clamp to valid range
                capacity_category = LEVEL_TO_CATEGORY.get(floored_level, 'Unknown')
                actual_segment_length = max(0.0, seg_end - seg_start)

                segments.append({
                    'River': river,
                    'Reach': reach,
                    'river': river,
                    'reach': reach,
                    'segment_id': seg_idx + 1,
                    'segment_start_rs': seg_xs['RS'].iloc[0],
                    'segment_end_rs': seg_xs['RS'].iloc[-1],
                    'start_distance': seg_start,
                    'end_distance': seg_end,
                    'segment_length_ft': actual_segment_length,
                    'segment_length_miles': actual_segment_length / 5280.0,
                    'weighted_capacity': round(weighted_cap, 2),
                    'capacity_level': floored_level,
                    'capacity_category': capacity_category,
                    'system_capacity': capacity_category,
                    'channel_length': actual_segment_length,
                    'cross_section_count': len(seg_xs),
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

        Groups cross sections or channel segments by capacity level and computes
        the total channel length and percentage at each level.

        Args:
            capacity_df: DataFrame from segment_channel() with columns
                        capacity_level and segment_length_ft/channel_length, or
                        from determine_capacity() with capacity_level and Len Channel.

        Returns:
            DataFrame with columns:
                capacity_level, capacity_category,
                channel_length_ft, percent_of_total

            Sorted by capacity_level (1-7). Percentages sum to 100%.
        """
        if len(capacity_df) == 0:
            return pd.DataFrame()

        work_df = capacity_df.copy()
        if 'capacity_level' not in work_df.columns and 'system_capacity' in work_df.columns:
            work_df['capacity_level'] = work_df['system_capacity'].map(CATEGORY_TO_LEVEL)

        if 'segment_length_ft' in work_df.columns:
            length_col = 'segment_length_ft'
        elif 'channel_length' in work_df.columns:
            length_col = 'channel_length'
        elif 'Len Channel' in work_df.columns:
            length_col = 'Len Channel'
        elif 'segment_length_miles' in work_df.columns:
            work_df['segment_length_ft'] = work_df['segment_length_miles'] * 5280.0
            length_col = 'segment_length_ft'
        else:
            raise ValueError(
                "capacity_df must contain segment_length_ft, channel_length, "
                "segment_length_miles, or Len Channel."
            )

        count_col = 'segment_id' if 'segment_id' in work_df.columns else 'RS'
        if count_col not in work_df.columns:
            work_df['_row_count'] = 1
            count_col = '_row_count'

        summary = work_df.groupby('capacity_level').agg(
            channel_length_ft=(length_col, 'sum'),
            xs_count=(count_col, 'count')
        ).reset_index()

        total_length = summary['channel_length_ft'].sum()
        if total_length > 0:
            summary['percent_of_total'] = (
                summary['channel_length_ft'] / total_length * 100
            ).round(1)
        else:
            summary['percent_of_total'] = 0.0

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
        summary = HdfChannelCapacity.system_capacity_summary(segments)

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
        existing_results: Union[Dict[str, Any], pd.DataFrame],
        proposed_results: Union[Dict[str, Any], pd.DataFrame],
        level: str = "segments"
    ) -> pd.DataFrame:
        """
        Compare channel capacity between existing and proposed conditions.

        Produces a side-by-side segment-level comparison showing capacity level
        changes between two analysis results. A positive level change is an
        improvement because higher capacity levels contain larger events.

        Args:
            existing_results: Dict from analyze_channel_capacity() or a capacity
                DataFrame for existing conditions.
            proposed_results: Dict from analyze_channel_capacity() or a capacity
                DataFrame for proposed conditions.
            level: "segments" for default segment-level comparison, or "xs" for
                cross-section comparison.

        Returns:
            DataFrame with columns:
                River, Reach, segment_id (or RS for level="xs"),
                existing_level, existing_category,
                proposed_level, proposed_category,
                level_change, classification
        """
        def _capacity_frame(results: Union[Dict[str, Any], pd.DataFrame], comparison_level: str) -> pd.DataFrame:
            if isinstance(results, pd.DataFrame):
                return results.copy()
            if comparison_level == "xs":
                return results["xs_capacity"].copy()
            if "segments" in results and len(results["segments"]) > 0:
                return results["segments"].copy()
            return results["xs_capacity"].copy()

        if level not in {"segments", "xs"}:
            raise ValueError("level must be 'segments' or 'xs'")

        existing_frame = _capacity_frame(existing_results, level)
        proposed_frame = _capacity_frame(proposed_results, level)

        if 'capacity_level' not in existing_frame.columns and 'system_capacity' in existing_frame.columns:
            existing_frame['capacity_level'] = existing_frame['system_capacity'].map(CATEGORY_TO_LEVEL)
            existing_frame['capacity_category'] = existing_frame['system_capacity']
        if 'capacity_level' not in proposed_frame.columns and 'system_capacity' in proposed_frame.columns:
            proposed_frame['capacity_level'] = proposed_frame['system_capacity'].map(CATEGORY_TO_LEVEL)
            proposed_frame['capacity_category'] = proposed_frame['system_capacity']

        key_cols = ['River', 'Reach', 'RS'] if level == "xs" else ['River', 'Reach', 'segment_id']
        if level == "segments":
            for frame in (existing_frame, proposed_frame):
                if 'River' not in frame.columns and 'river' in frame.columns:
                    frame['River'] = frame['river']
                if 'Reach' not in frame.columns and 'reach' in frame.columns:
                    frame['Reach'] = frame['reach']

        missing_existing = [col for col in key_cols + ['capacity_level'] if col not in existing_frame.columns]
        missing_proposed = [col for col in key_cols + ['capacity_level'] if col not in proposed_frame.columns]
        if missing_existing or missing_proposed:
            raise ValueError(
                f"Missing comparison columns. existing missing={missing_existing}; "
                f"proposed missing={missing_proposed}"
            )

        keep_cols = key_cols + ['capacity_level']
        if 'capacity_category' in existing_frame.columns:
            keep_cols.append('capacity_category')
        existing_cap = existing_frame[keep_cols].rename(columns={
            'capacity_level': 'existing_level',
            'capacity_category': 'existing_category',
        })

        keep_cols = key_cols + ['capacity_level']
        if 'capacity_category' in proposed_frame.columns:
            keep_cols.append('capacity_category')
        proposed_cap = proposed_frame[keep_cols].rename(columns={
            'capacity_level': 'proposed_level',
            'capacity_category': 'proposed_category',
        })

        comparison = existing_cap.merge(proposed_cap, on=key_cols, how='outer')
        comparison['existing_category'] = comparison.get('existing_category', pd.Series(index=comparison.index)).fillna(
            comparison['existing_level'].map(LEVEL_TO_CATEGORY)
        )
        comparison['proposed_category'] = comparison.get('proposed_category', pd.Series(index=comparison.index)).fillna(
            comparison['proposed_level'].map(LEVEL_TO_CATEGORY)
        )

        comparison['level_change'] = comparison['proposed_level'] - comparison['existing_level']
        comparison['classification'] = np.select(
            [
                comparison['level_change'] > 0,
                comparison['level_change'] < 0,
                comparison['level_change'] == 0,
            ],
            ['Improved', 'Degraded', 'No Change'],
            default='Incomplete',
        )
        comparison['improved'] = comparison['classification'] == 'Improved'

        n_improved = int((comparison['classification'] == 'Improved').sum())
        n_degraded = int((comparison['classification'] == 'Degraded').sum())
        n_unchanged = int((comparison['classification'] == 'No Change').sum())

        logger.info(
            f"Capacity comparison: {n_improved} improved, "
            f"{n_degraded} degraded, {n_unchanged} unchanged"
        )

        return comparison
