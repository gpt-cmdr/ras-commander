"""
HdfUtils Class
-------------

A utility class providing static methods for working with HEC-RAS HDF files.

Attribution:
    A substantial amount of code in this file is sourced or derived from the 
    https://github.com/fema-ffrd/rashdf library, released under MIT license 
    and Copyright (c) 2024 fema-ffrd. The file has been forked and modified 
    for use in RAS Commander.

Key Features:
- HDF file data conversion and parsing
- DateTime handling for RAS-specific formats
- Spatial operations using KDTree
- HDF attribute management

Main Method Categories:

1. Data Conversion
    - convert_ras_string: Convert RAS HDF strings to Python objects
    - convert_ras_hdf_value: Convert general HDF values to Python objects
    - convert_df_datetimes_to_str: Convert DataFrame datetime columns to strings
    - convert_hdf5_attrs_to_dict: Convert HDF5 attributes to dictionary
    - convert_timesteps_to_datetimes: Convert timesteps to datetime objects

2. Spatial Operations
    - perform_kdtree_query: KDTree search between datasets
    - find_nearest_neighbors: Find nearest neighbors within dataset

3. DateTime Parsing
    - parse_ras_datetime: Parse standard RAS datetime format (ddMMMYYYY HH:MM:SS)
    - parse_ras_window_datetime: Parse simulation window datetime (ddMMMYYYY HHMM)
    - parse_duration: Parse duration strings (HH:MM:SS)
    - parse_ras_datetime_ms: Parse datetime with milliseconds
    - parse_run_time_window: Parse time window strings

4. CRS Evidence and Identity
    - resolve_ras_relative_path: Resolve RASMapper relative paths on any host
    - get_crs_identity: Describe a CRS without guessing an authority code
    - crs_equivalent: Strict CRS equivalence (WKT1/WKT2/authority spellings)
    - get_equivalent_epsg: EPSG code strictly equivalent to a CRS, if any
    - format_crs: Stable public CRS string ("EPSG:n", else source WKT)
    - read_crs_evidence: Read CRS evidence from one HDF, .prj or raster file
    - collect_hdf_crs_evidence: Ordered evidence for an HDF and its .rasmap
    - collect_rasmap_crs_evidence: Ordered evidence named by a .rasmap
    - resolve_crs_evidence: Resolve evidence to resolved/missing/conflict

Usage Notes:
- All methods are static and can be called without class instantiation
- Methods handle both raw HDF data and converted Python objects
- Includes comprehensive error handling for RAS-specific data formats
- Supports various RAS datetime formats and conversions
"""
import logging
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET
import h5py
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Union, Optional, Dict, List, Tuple, Any, Sequence
import re

from ..Decorators import standardize_input, log_call 
from ..LoggingConfig import setup_logging, get_logger

logger = get_logger(__name__)

# Exact definitions; HEC-RAS "US Customary" alone does not say which foot.
US_SURVEY_FOOT_M = 1200.0 / 3937.0
INTERNATIONAL_FOOT_M = 0.3048

CRS_EVIDENCE_FOUND = "found"
CRS_EVIDENCE_ABSENT = "absent"
CRS_EVIDENCE_MISSING_FILE = "missing_file"
CRS_EVIDENCE_INVALID = "invalid"
CRS_EVIDENCE_UNREADABLE = "unreadable"

CRS_RESOLVED = "resolved"
CRS_MISSING = "missing"
CRS_CONFLICT = "conflict"


@dataclass(frozen=True)
class CrsEvidence:
    """One CRS observation from one source file.

    ``status`` is one of ``found``, ``absent`` (file readable, no CRS stored),
    ``missing_file``, ``invalid`` (CRS text present but unparseable) or
    ``unreadable``. ``wkt`` preserves the source definition with outer
    whitespace stripped.
    """
    source: str
    path: Optional[Path]
    status: str
    wkt: Optional[str] = None
    detail: Optional[str] = None


@dataclass(frozen=True)
class CrsResolution:
    """Outcome of resolving ordered CRS evidence.

    ``crs`` is the source WKT of the highest-precedence evidence only when
    ``status == "resolved"``. Missing and conflicting evidence leave ``crs``
    as ``None``; ``candidates`` lists one WKT per non-equivalent CRS found.
    ``authority`` is an exact (confidence 100) authority code for ``crs``;
    ``epsg`` is an EPSG code strictly equivalent to the agreeing evidence.
    ``to_crs_string()`` returns the public string form.
    """
    status: str
    crs: Optional[str]
    source: Optional[str]
    path: Optional[Path]
    authority: Optional[str]
    evidence: Tuple[CrsEvidence, ...] = field(default_factory=tuple)
    candidates: Tuple[str, ...] = field(default_factory=tuple)
    epsg: Optional[int] = None

    def to_crs_string(self) -> Optional[str]:
        """Return ``"EPSG:n"`` when an equivalent EPSG code exists, the
        source WKT when only WKT exists, or ``None`` when not resolved."""
        if self.status != CRS_RESOLVED:
            return None
        if self.epsg is not None:
            return f"EPSG:{self.epsg}"
        return HdfUtils.format_crs(self.crs)


def _equivalent_epsg(crs) -> Optional[int]:
    from pyproj import CRS

    try:
        matches = crs.list_authority(auth_name="EPSG", min_confidence=20)
    except Exception:
        return None
    for match in sorted(matches, key=lambda m: -m.confidence):
        try:
            if CRS.from_epsg(int(match.code)).equals(crs, ignore_axis_order=True):
                return int(match.code)
        except Exception:
            continue
    return None


# CRS text from a project rarely changes; authority matching costs tens of
# milliseconds per call and get_projection runs once per geospatial reader.
@lru_cache(maxsize=256)
def _equivalent_epsg_for_text(text: str) -> Optional[int]:
    from pyproj import CRS

    try:
        crs = CRS.from_user_input(text)
    except Exception:
        return None
    return _equivalent_epsg(crs)


@lru_cache(maxsize=256)
def _exact_authority_for_text(text: str) -> Optional[str]:
    from pyproj import CRS

    try:
        authority = CRS.from_user_input(text).to_authority(min_confidence=100)
    except Exception:
        return None
    return f"{authority[0]}:{authority[1]}" if authority else None


@lru_cache(maxsize=1024)
def _crs_text_equivalent(text_a: str, text_b: str) -> bool:
    from pyproj import CRS

    try:
        a = CRS.from_user_input(text_a)
        b = CRS.from_user_input(text_b)
    except Exception as e:
        raise ValueError(f"Could not parse CRS: {e}") from e
    return bool(a.equals(b, ignore_axis_order=True))


class HdfUtils:
    """
    Utility class for working with HEC-RAS HDF files.

    This class provides general utility functions for HDF file operations,
    including attribute extraction, data conversion, and common HDF queries.
    It also includes spatial operations and helper methods for working with
    HEC-RAS specific data structures.

    Note:
    - Use this class for general HDF utility functions that are not specific to plan or geometry files.
    - All methods in this class are static and can be called without instantiating the class.
    """




# RENAME TO convert_ras_string and make public

    @staticmethod
    def convert_ras_string(value: Union[str, bytes]) -> Union[bool, datetime, List[datetime], timedelta, str]:
        """
        Convert a string value from an HEC-RAS HDF file into a Python object.

        Args:
            value (Union[str, bytes]): The value to convert.

        Returns:
            Union[bool, datetime, List[datetime], timedelta, str]: The converted value.
        """
        if isinstance(value, bytes):
            s = value.decode("utf-8")
        else:
            s = value

        if s == "True":
            return True
        elif s == "False":
            return False
        
        ras_datetime_format1_re = r"\d{2}\w{3}\d{4} \d{2}:\d{2}:\d{2}"
        ras_datetime_format2_re = r"\d{2}\w{3}\d{4} \d{2}\d{2}"
        ras_duration_format_re = r"\d{2}:\d{2}:\d{2}"

        if re.match(rf"^{ras_datetime_format1_re}", s):
            if re.match(rf"^{ras_datetime_format1_re} to {ras_datetime_format1_re}$", s):
                split = s.split(" to ")
                return [
                    HdfUtils.parse_ras_datetime(split[0]),
                    HdfUtils.parse_ras_datetime(split[1]),
                ]
            return HdfUtils.parse_ras_datetime(s)
        elif re.match(rf"^{ras_datetime_format2_re}", s):
            if re.match(rf"^{ras_datetime_format2_re} to {ras_datetime_format2_re}$", s):
                split = s.split(" to ")
                return [
                    HdfUtils.parse_ras_window_datetime(split[0]),
                    HdfUtils.parse_ras_window_datetime(split[1]),
                ]
            return HdfUtils.parse_ras_window_datetime(s)
        elif re.match(rf"^{ras_duration_format_re}$", s):
            return HdfUtils.parse_duration(s)
        return s





    @staticmethod
    def convert_ras_hdf_value(value: Any) -> Union[None, bool, str, List[str], int, float, List[int], List[float]]:
        """
        Convert a value from a HEC-RAS HDF file into a Python object.

        Args:
            value (Any): The value to convert.

        Returns:
            Union[None, bool, str, List[str], int, float, List[int], List[float]]: The converted value.
        """
        if isinstance(value, np.floating) and np.isnan(value):
            return None
        elif isinstance(value, (bytes, np.bytes_)):
            return value.decode('utf-8')
        elif isinstance(value, np.integer):
            return int(value)
        elif isinstance(value, np.floating):
            return float(value)
        elif isinstance(value, (int, float)):
            return value
        elif isinstance(value, (list, tuple, np.ndarray)):
            if len(value) > 1:
                return [HdfUtils.convert_ras_hdf_value(v) for v in value]
            else:
                return HdfUtils.convert_ras_hdf_value(value[0])
        else:
            return str(value)










# RENAME TO convert_df_datetimes_to_str 

    @staticmethod
    def convert_df_datetimes_to_str(df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert any datetime64 columns in a DataFrame to strings.

        Args:
            df (pd.DataFrame): The DataFrame to convert.

        Returns:
            pd.DataFrame: The DataFrame with datetime columns converted to strings.
        """
        for col in df.select_dtypes(include=['datetime64']).columns:
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        return df


# KDTree Methods: 


    @staticmethod
    def perform_kdtree_query(
        reference_points: np.ndarray,
        query_points: np.ndarray,
        max_distance: float = 2.0
    ) -> np.ndarray:
        """
        Performs a KDTree query between two datasets and returns indices with distances exceeding max_distance set to -1.

        Args:
            reference_points (np.ndarray): The reference dataset for KDTree.
            query_points (np.ndarray): The query dataset to search against KDTree of reference_points.
            max_distance (float, optional): The maximum distance threshold. Indices with distances greater than this are set to -1. Defaults to 2.0.

        Returns:
            np.ndarray: Array of indices from reference_points that are nearest to each point in query_points. 
                        Indices with distances > max_distance are set to -1.

        Example:
            >>> ref_points = np.array([[0, 0], [1, 1], [2, 2]])
            >>> query_points = np.array([[0.5, 0.5], [3, 3]])
            >>> result = HdfUtils.perform_kdtree_query(ref_points, query_points)
            >>> print(result)
            array([ 0, -1])
        """
        from scipy.spatial import KDTree

        dist, snap = KDTree(reference_points).query(query_points, distance_upper_bound=max_distance)
        snap[dist > max_distance] = -1
        return snap

    @staticmethod
    def find_nearest_neighbors(points: np.ndarray, max_distance: float = 2.0) -> np.ndarray:
        """
        Creates a self KDTree for dataset points and finds nearest neighbors excluding self, 
        with distances above max_distance set to -1.

        Args:
            points (np.ndarray): The dataset to build the KDTree from and query against itself.
            max_distance (float, optional): The maximum distance threshold. Indices with distances 
                                            greater than max_distance are set to -1. Defaults to 2.0.

        Returns:
            np.ndarray: Array of indices representing the nearest neighbor in points for each point in points. 
                        Indices with distances > max_distance or self-matches are set to -1.

        Example:
            >>> points = np.array([[0, 0], [1, 1], [2, 2], [10, 10]])
            >>> result = HdfUtils.find_nearest_neighbors(points)
            >>> print(result)
            array([1, 0, 1, -1])
        """
        from scipy.spatial import KDTree

        dist, snap = KDTree(points).query(points, k=2, distance_upper_bound=max_distance)
        snap[dist > max_distance] = -1
        
        snp = pd.DataFrame(snap, index=np.arange(len(snap)))
        snp = snp.replace(-1, np.nan)
        snp.loc[snp[0] == snp.index, 0] = np.nan
        snp.loc[snp[1] == snp.index, 1] = np.nan
        filled = snp[0].fillna(snp[1])
        snapped = filled.fillna(-1).astype(np.int64).to_numpy()
        return snapped

    @staticmethod
    @log_call
    def scan_hdf_files(ras_folder: Path) -> Dict[str, Path]:
        """
        Scan for HDF plan and geometry files in a RAS project folder.

        Args:
            ras_folder: Path to HEC-RAS project folder containing .prj file

        Returns:
            Dictionary mapping HDF types to file paths:
            {'plan_01': Path, 'geom_01': Path, ...}

        Examples:
            >>> hdf_files = HdfUtils.scan_hdf_files(Path("/path/to/project"))
            >>> plan_hdf = hdf_files.get('plan_01')
            >>> geom_hdf = hdf_files.get('geom_01')
        """
        results = {}
        # Scan for plan HDFs (p##.hdf pattern)
        for hdf_file in ras_folder.glob("*.p[0-9][0-9].hdf"):
            # Extract plan number from filename
            plan_num = hdf_file.stem[-2:]
            results[f"plan_{plan_num}"] = hdf_file
            logger.debug(f"Found plan HDF: {hdf_file.name} -> Plan {plan_num}")

        # Scan for geometry HDFs (g##.hdf pattern)
        for hdf_file in ras_folder.glob("*.g[0-9][0-9].hdf"):
            # Extract geometry number from filename
            geom_num = hdf_file.stem[-2:]
            results[f"geom_{geom_num}"] = hdf_file
            logger.debug(f"Found geometry HDF: {hdf_file.name} -> Geometry {geom_num}")

        return results

    @staticmethod
    @log_call
    def resolve_hdf_paths(ras_folder: Path, plan_number: str, ras_object=None) -> Dict[str, Optional[Path]]:
        """
        Resolve HDF plan and geometry file paths for a plan.

        Args:
            ras_folder: Path to HEC-RAS project folder
            plan_number: Plan number (e.g., "01", "08")
            ras_object (RasPrj, optional): Optional RAS object instance

        Returns:
            Dictionary with 'plan' and 'geometry' HDF paths (or None if not found)

        Examples:
            >>> hdfs = HdfUtils.resolve_hdf_paths(Path("/path/to/project"), "01")
            >>> plan_hdf = hdfs['plan']
            >>> geom_hdf = hdfs['geometry']
        """
        from ..RasPrj import ras as default_ras
        ras_obj = ras_object or default_ras
        ras_obj.check_initialized()

        plan_num = str(plan_number).zfill(2)
        result = {'plan': None, 'geometry': None}

        # Scan for HDF files
        hdf_files = HdfUtils.scan_hdf_files(ras_folder)

        # Get plan HDF
        plan_key = f"plan_{plan_num}"
        if plan_key in hdf_files:
            result['plan'] = hdf_files[plan_key]

        # Get geometry HDF if we know the geometry number
        plan_row = ras_obj.plan_df[ras_obj.plan_df['plan_number'] == plan_num]
        if not plan_row.empty:
            geom_num = plan_row.iloc[0].get('geometry_number')
            if geom_num is not None:
                geom_key = f"geom_{str(geom_num).zfill(2)}"
                if geom_key in hdf_files:
                    result['geometry'] = hdf_files[geom_key]

        return result




# Rename to convert_timesteps_to_datetimes and make public
    @staticmethod
    def convert_timesteps_to_datetimes(timesteps: np.ndarray, start_time: datetime, time_unit: str = "days", round_to: str = "100ms") -> pd.DatetimeIndex:
        """
        Convert RAS timesteps to datetime objects.

        Args:
            timesteps (np.ndarray): Array of timesteps.
            start_time (datetime): Start time of the simulation.
            time_unit (str): Unit of the timesteps. Default is "days".
            round_to (str): Frequency string to round the times to. Default is "100ms" (100 milliseconds).

        Returns:
            pd.DatetimeIndex: DatetimeIndex of converted and rounded datetimes.
        """
        if time_unit == "days":
            datetimes = start_time + pd.to_timedelta(timesteps, unit='D')
        elif time_unit == "hours":
            datetimes = start_time + pd.to_timedelta(timesteps, unit='H')
        else:
            raise ValueError(f"Unsupported time unit: {time_unit}")

        return pd.DatetimeIndex(datetimes).round(round_to)
    
# rename to convert_hdf5_attrs_to_dict and make public

    @staticmethod
    def convert_hdf5_attrs_to_dict(attrs: Union[h5py.AttributeManager, Dict], prefix: Optional[str] = None) -> Dict:
        """
        Convert HDF5 attributes to a Python dictionary.

        Args:
            attrs (Union[h5py.AttributeManager, Dict]): The attributes to convert.
            prefix (Optional[str]): A prefix to add to the attribute keys.

        Returns:
            Dict: A dictionary of converted attributes.
        """
        result = {}
        for key, value in attrs.items():
            if prefix:
                key = f"{prefix}/{key}"
            if isinstance(value, (np.ndarray, list)):
                result[key] = [HdfUtils.convert_ras_hdf_value(v) for v in value]
            else:
                result[key] = HdfUtils.convert_ras_hdf_value(value)
        return result
    
    

    @staticmethod
    def parse_run_time_window(window: str) -> Tuple[datetime, datetime]:
        """
        Parse a run time window string into a tuple of datetime objects.

        Args:
            window (str): The run time window string to be parsed.

        Returns:
            Tuple[datetime, datetime]: A tuple containing two datetime objects representing the start and end of the run
            time window.
        """
        split = window.split(" to ")
        if len(split) != 2 or not all(part.strip() for part in split):
            raise ValueError(
                "RAS run time window must use the format "
                "'DDMMMYYYY HH:MM:SS to DDMMMYYYY HH:MM:SS'."
            )
        begin = HdfUtils.parse_ras_datetime(split[0].strip())
        end = HdfUtils.parse_ras_datetime(split[1].strip())
        return begin, end

    


                
                
                
                
                
                
                
                
                
                
                
                
## MOVED FROM HdfBase to HdfUtils:
# _parse_ras_datetime   
# _parse_ras_simulation_window_datetime
# _parse_duration
# _parse_ras_datetime_ms
# _convert_ras_hdf_string

# Which were renamed and made public as: 
# parse_ras_datetime
# parse_ras_window_datetime
# parse_ras_datetime_ms
# parse_ras_duration
# parse_ras_time_window


# Rename to parse_ras_datetime and make public

    @staticmethod
    def parse_ras_datetime(datetime_str: str) -> datetime:
        """
        Parse a RAS datetime string into a datetime object.

        Args:
            datetime_str (str): The datetime string in format "ddMMMYYYY HH:MM:SS"

        Returns:
            datetime: The parsed datetime object.
        """
        return datetime.strptime(datetime_str, "%d%b%Y %H:%M:%S")

# Rename to parse_ras_window_datetime and make public

    @staticmethod
    def parse_ras_window_datetime(datetime_str: str) -> datetime:
        """
        Parse a datetime string from a RAS simulation window into a datetime object.

        HEC-RAS writes the end of a day as ``2400`` (``02JAN1900 2400``), which
        is midnight at the start of the next day.

        Args:
            datetime_str (str): The datetime string to parse.

        Returns:
            datetime: The parsed datetime object.
        """
        text = datetime_str.strip()
        if text.endswith(" 2400"):
            return datetime.strptime(text[:-5], "%d%b%Y") + timedelta(days=1)
        return datetime.strptime(text, "%d%b%Y %H%M")


# Rename to parse_duration and make public


    @staticmethod
    def parse_duration(duration_str: str) -> timedelta:
        """
        Parse a duration string into a timedelta object.

        Args:
            duration_str (str): The duration string to parse.

        Returns:
            timedelta: The parsed duration as a timedelta object.
        """
        hours, minutes, seconds = map(int, duration_str.split(':'))
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    
    
# Rename to parse_ras_datetime_ms and make public
    
    @staticmethod
    def parse_ras_datetime_ms(datetime_str: str) -> datetime:
        """
        Parse a datetime string with milliseconds from a RAS file.

        Args:
            datetime_str (str): The datetime string to parse.

        Returns:
            datetime: The parsed datetime object.
        """
        milliseconds = int(datetime_str[-3:])
        microseconds = milliseconds * 1000
        parsed_dt = HdfUtils.parse_ras_datetime(datetime_str[:-4]).replace(microsecond=microseconds)
        return parsed_dt

    # ------------------------------------------------------------------
    # CRS evidence and identity
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def resolve_ras_relative_path(base_folder: Union[str, Path], filename: str) -> Path:
        """
        Resolve a path stored by RASMapper relative to ``base_folder``.

        RASMapper writes Windows separators (``.\\GIS\\a.prj``,
        ``..\\shared\\a.prj``) even when the project is read on Linux.
        Separators are normalized and parent components are preserved;
        textual removal of ``.\\`` would corrupt ``..\\`` into ``.``.

        Args:
            base_folder: Folder the stored path is relative to (normally the
                folder containing the ``.rasmap`` file).
            filename: Path text exactly as stored by RASMapper.

        Returns:
            Path: The resolved path. Drive-letter and UNC paths are returned
            unchanged because they are not relative to ``base_folder``.
        """
        text = str(filename).strip()
        if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith(("\\\\", "//")):
            return Path(text)
        relative = Path(text.replace("\\", "/"))
        if relative.is_absolute():
            return relative
        return Path(base_folder) / relative

    @staticmethod
    def _to_crs(crs_input: Any):
        from pyproj import CRS

        if isinstance(crs_input, CRS):
            return crs_input
        if isinstance(crs_input, (bytes, np.bytes_)):
            crs_input = crs_input.decode("utf-8")
        return CRS.from_user_input(crs_input)

    @staticmethod
    def _classify_linear_unit(unit_name: Optional[str], factor: Optional[float]) -> str:
        if factor is None:
            return "unknown"
        if unit_name and unit_name.lower() in ("degree", "radian", "grad"):
            return "angular"
        for kind, exact in (
            ("metre", 1.0),
            ("us_survey_foot", US_SURVEY_FOOT_M),
            ("international_foot", INTERNATIONAL_FOOT_M),
        ):
            if math.isclose(factor, exact, rel_tol=1e-9):
                return kind
        return "other"

    @staticmethod
    def _axis_unit(crs) -> Tuple[Optional[str], Optional[float]]:
        if not crs.axis_info:
            return None, None
        axis = crs.axis_info[0]
        return axis.unit_name, axis.unit_conversion_factor

    @staticmethod
    @log_call
    def get_crs_identity(crs_input: Any, candidate_min_confidence: int = 20) -> Dict[str, Any]:
        """
        Describe a CRS without assigning a guessed authority code.

        ``authority`` is set only for an exact (confidence 100) authority match
        and may be any authority (``EPSG``, ``ESRI``, ...). ``epsg`` is set
        only when an EPSG definition is strictly equivalent (see
        ``get_equivalent_epsg``). Lower-confidence matches are reported in
        ``authority_candidates`` for diagnostics and must not be used to label
        data.

        Args:
            crs_input: WKT1/WKT2 text, ``"EPSG:n"``, an EPSG integer, or a
                ``pyproj.CRS``.
            candidate_min_confidence: Minimum confidence for listed candidates.

        Returns:
            Dict with keys ``name``, ``authority``, ``epsg``,
            ``authority_candidates`` (list of ``(code, confidence)``),
            ``is_projected``, ``is_geographic``, ``is_compound``, ``datum``,
            ``ellipsoid``, ``horizontal_unit``, ``horizontal_unit_to_meter``,
            ``horizontal_unit_kind`` (``metre``, ``us_survey_foot``,
            ``international_foot``, ``angular``, ``other`` or ``unknown``) and
            ``vertical`` (``None`` or a dict with ``name``, ``datum``,
            ``unit``, ``unit_to_meter``, ``unit_kind``).

        Raises:
            ValueError: If the input cannot be parsed as a CRS.
        """
        try:
            crs = HdfUtils._to_crs(crs_input)
        except Exception as e:
            raise ValueError(f"Could not parse CRS: {e}") from e

        horizontal, vertical = crs, None
        if crs.is_compound and crs.sub_crs_list:
            horizontal = crs.sub_crs_list[0]
            vertical = crs.sub_crs_list[1] if len(crs.sub_crs_list) > 1 else None
        elif crs.is_vertical:
            horizontal, vertical = None, crs

        authority = crs.to_authority(min_confidence=100)
        candidates = [
            (f"{match.auth_name}:{match.code}", match.confidence)
            for match in crs.list_authority(min_confidence=candidate_min_confidence)
            if match.confidence < 100
        ]

        unit_name, factor = (None, None)
        if horizontal is not None:
            unit_name, factor = HdfUtils._axis_unit(horizontal)

        vertical_info = None
        if vertical is not None:
            v_name, v_factor = HdfUtils._axis_unit(vertical)
            vertical_info = {
                "name": vertical.name,
                "datum": vertical.datum.name if vertical.datum else None,
                "unit": v_name,
                "unit_to_meter": v_factor,
                "unit_kind": HdfUtils._classify_linear_unit(v_name, v_factor),
            }

        datum = horizontal.datum if horizontal is not None else None
        return {
            "name": crs.name,
            "authority": f"{authority[0]}:{authority[1]}" if authority else None,
            "epsg": HdfUtils.get_equivalent_epsg(crs),
            "authority_candidates": candidates,
            "is_projected": bool(horizontal is not None and horizontal.is_projected),
            "is_geographic": bool(horizontal is not None and horizontal.is_geographic),
            "is_compound": bool(crs.is_compound),
            "datum": datum.name if datum else None,
            "ellipsoid": crs.ellipsoid.name if crs.ellipsoid else None,
            "horizontal_unit": unit_name,
            "horizontal_unit_to_meter": factor,
            "horizontal_unit_kind": HdfUtils._classify_linear_unit(unit_name, factor),
            "vertical": vertical_info,
        }

    @staticmethod
    @log_call
    def crs_equivalent(crs_a: Any, crs_b: Any) -> bool:
        """
        Return True when two CRS definitions are strictly equivalent.

        Equivalence ignores naming and WKT dialect (ESRI WKT1, OGC WKT2,
        authority codes) and axis order, but not datum realization,
        projection parameters or units. NAD83, NAD83(HARN) and NAD83(2011)
        State Plane zones are distinct; ftUS, international feet and metres
        are distinct.

        Raises:
            ValueError: If either input cannot be parsed as a CRS.
        """
        if isinstance(crs_a, str) and isinstance(crs_b, str):
            return _crs_text_equivalent(crs_a, crs_b)
        try:
            a = HdfUtils._to_crs(crs_a)
            b = HdfUtils._to_crs(crs_b)
        except Exception as e:
            raise ValueError(f"Could not parse CRS: {e}") from e
        return bool(a.equals(b, ignore_axis_order=True))

    @staticmethod
    @log_call
    def get_equivalent_epsg(crs_input: Any) -> Optional[int]:
        """
        Return an EPSG code whose definition is strictly equivalent to the CRS.

        Candidate EPSG codes come from PROJ's authority matching; a candidate
        is accepted only if it is equivalent under the ``crs_equivalent`` rule,
        so a low-confidence match (for example a different NAD83 realization
        or foot definition) is never used as a label.

        Args:
            crs_input: Any input accepted by ``get_crs_identity``.

        Returns:
            Optional[int]: The EPSG code, or ``None`` when no EPSG definition
            is equivalent or the input cannot be parsed.
        """
        if isinstance(crs_input, str):
            return _equivalent_epsg_for_text(crs_input.strip())
        try:
            crs = HdfUtils._to_crs(crs_input)
        except Exception:
            return None
        return _equivalent_epsg(crs)

    @staticmethod
    @log_call
    def format_crs(crs_input: Any) -> Optional[str]:
        """
        Return the stable public string form of a CRS.

        This is the single formatting rule used by ``HdfBase.get_projection``,
        ``HdfProject.get_project_crs`` and ``RasPrj.project_crs``:

        - ``"EPSG:n"`` when an EPSG definition is strictly equivalent
          (``get_equivalent_epsg``);
        - otherwise the source WKT text unchanged (never an ``"ESRI:n"`` code
          and never a guessed low-confidence EPSG code);
        - ``None`` for ``None``/empty input.

        Unparseable text is returned unchanged so callers keep the source
        definition for diagnosis.
        """
        if crs_input is None:
            return None
        if isinstance(crs_input, (bytes, np.bytes_)):
            crs_input = crs_input.decode("utf-8")
        if isinstance(crs_input, str):
            crs_input = crs_input.strip()
            if not crs_input:
                return None
        epsg = HdfUtils.get_equivalent_epsg(crs_input)
        if epsg is not None:
            return f"EPSG:{epsg}"
        if isinstance(crs_input, str):
            from pyproj import CRS

            try:
                CRS.from_wkt(crs_input)
            except Exception:
                # Authority identifiers and other recognized definitions need
                # WKT serialization; preserve actual source WKT verbatim.
                pass
            else:
                return crs_input
        try:
            return HdfUtils._to_crs(crs_input).to_wkt()
        except Exception:
            return str(crs_input)

    @staticmethod
    def _evidence_from_wkt(source: str, path: Path, wkt: Optional[str]) -> CrsEvidence:
        if wkt is None or not wkt.strip():
            return CrsEvidence(source, path, CRS_EVIDENCE_ABSENT)
        wkt = wkt.strip()
        try:
            HdfUtils._to_crs(wkt)
        except Exception as e:
            return CrsEvidence(source, path, CRS_EVIDENCE_INVALID, wkt, str(e))
        return CrsEvidence(source, path, CRS_EVIDENCE_FOUND, wkt)

    @staticmethod
    def _decode_projection_attr(value: Any) -> Tuple[Optional[str], Optional[str]]:
        """Return ``(text, error)`` for an HDF ``Projection`` attribute value."""
        if value is None:
            return None, None
        if isinstance(value, np.ndarray):
            if value.size != 1:
                return None, "Projection must contain one CRS definition"
            value = value.reshape(-1)[0]
        if isinstance(value, (bytes, np.bytes_)):
            value = value.decode("utf-8")
        return str(value), None

    @staticmethod
    @log_call
    def read_crs_evidence(path: Union[str, Path], source: Optional[str] = None) -> CrsEvidence:
        """
        Read CRS evidence from one HDF, projection (``.prj``) or raster
        (``.tif``/``.tiff``/``.vrt``) file.

        For HDF files the root ``Projection`` attribute is read; when the root
        attribute is not stored, the ``Geometry`` group ``Projection``
        attribute is used. Never raises for missing or unreadable files; the
        outcome is recorded in the returned evidence ``status``.

        Args:
            path: File to read.
            source: Label for the evidence (defaults to ``hdf``, ``prj`` or
                ``raster`` from the suffix).

        Returns:
            CrsEvidence
        """
        path = Path(path)
        suffix = path.suffix.lower()
        kind = {".hdf": "hdf", ".h5": "hdf", ".hdf5": "hdf",
                ".prj": "prj", ".tif": "raster",
                ".tiff": "raster", ".vrt": "raster"}.get(suffix)
        source = source or kind or "unknown"

        if not path.is_file():
            return CrsEvidence(source, path, CRS_EVIDENCE_MISSING_FILE)
        try:
            if kind == "hdf":
                with h5py.File(path, "r") as hdf_file:
                    value = hdf_file.attrs.get("Projection")
                    if value is None and "Geometry" in hdf_file:
                        value = hdf_file["Geometry"].attrs.get("Projection")
                text, error = HdfUtils._decode_projection_attr(value)
                if error:
                    return CrsEvidence(source, path, CRS_EVIDENCE_INVALID, detail=error)
                return HdfUtils._evidence_from_wkt(source, path, text)
            if kind == "prj":
                raw = path.read_bytes()
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")
                return HdfUtils._evidence_from_wkt(source, path, text)
            if kind == "raster":
                try:
                    import rasterio
                except ImportError:
                    return CrsEvidence(source, path, CRS_EVIDENCE_UNREADABLE,
                                       detail="rasterio not installed")
                with rasterio.open(path) as src:
                    wkt = src.crs.to_wkt() if src.crs else None
                return HdfUtils._evidence_from_wkt(source, path, wkt)
        except Exception as e:
            return CrsEvidence(source, path, CRS_EVIDENCE_UNREADABLE, detail=str(e))
        return CrsEvidence(source, path, CRS_EVIDENCE_UNREADABLE,
                           detail=f"unsupported file type '{suffix}'")

    @staticmethod
    def _select_rasmap(hdf_path: Path) -> Optional[Path]:
        rasmaps = sorted(hdf_path.parent.glob("*.rasmap"))
        if not rasmaps:
            return None
        project_stem = re.sub(r"\.[pg]\d+\.hdf$", "", hdf_path.name, flags=re.I)
        if project_stem == hdf_path.name:
            project_stem = hdf_path.stem
        matches = [p for p in rasmaps if p.stem.casefold() == project_stem.casefold()]
        if len(matches) == 1:
            return matches[0]
        if len(rasmaps) == 1:
            return rasmaps[0]
        raise ValueError("Ambiguous RASMapper files; specify rasmap_path explicitly")

    @staticmethod
    @log_call
    def collect_hdf_crs_evidence(
        hdf_path: Union[str, Path],
        rasmap_path: Optional[Union[str, Path]] = None,
    ) -> List[CrsEvidence]:
        """
        Collect ordered CRS evidence for a HEC-RAS HDF file.

        Precedence (first is strongest): the HDF ``Projection`` attribute, the
        RASMapper projection file, then each terrain layer HDF listed in the
        ``.rasmap``. Every checked location is returned, including missing and
        absent ones, so callers can report exactly what was examined.

        Args:
            hdf_path: Geometry or plan HDF file.
            rasmap_path: RASMapper file. Defaults to the ``.rasmap`` in the HDF
                folder whose stem matches the HDF project name, or the sole
                map when only one exists. Multiple unmatched maps are ambiguous
                and recorded as ``invalid`` ``rasmap`` evidence.

        Returns:
            List[CrsEvidence]: Ordered evidence, suitable for
            ``resolve_crs_evidence``.
        """
        hdf_path = Path(hdf_path)
        evidence = [HdfUtils.read_crs_evidence(hdf_path, "hdf_attribute")]

        try:
            rasmap = Path(rasmap_path) if rasmap_path else HdfUtils._select_rasmap(hdf_path)
        except ValueError as exc:
            evidence.append(CrsEvidence("rasmap", None, CRS_EVIDENCE_INVALID,
                                        detail=str(exc)))
            return evidence
        if rasmap is None or not rasmap.is_file():
            evidence.append(CrsEvidence("rasmap", rasmap, CRS_EVIDENCE_MISSING_FILE,
                                        detail="no .rasmap file"))
            return evidence

        evidence.extend(HdfUtils.collect_rasmap_crs_evidence(rasmap))
        return evidence

    @staticmethod
    @log_call
    def collect_rasmap_crs_evidence(rasmap_path: Union[str, Path]) -> List[CrsEvidence]:
        """
        Collect ordered CRS evidence named by a RASMapper (``.rasmap``) file.

        Returns the ``RASProjectionFilename`` projection file evidence followed
        by one evidence item per terrain layer HDF. This is the ``.rasmap``
        part of ``collect_hdf_crs_evidence`` for workflows without an HDF
        (for example plain-text geometry).

        Args:
            rasmap_path: RASMapper file.

        Returns:
            List[CrsEvidence]: Ordered evidence; a single ``missing_file`` or
            ``unreadable`` ``rasmap`` item when the file cannot be parsed.
        """
        rasmap = Path(rasmap_path)
        if not rasmap.is_file():
            return [CrsEvidence("rasmap", rasmap, CRS_EVIDENCE_MISSING_FILE,
                                detail="no .rasmap file")]
        try:
            root = ET.parse(rasmap).getroot()
        except Exception as e:
            return [CrsEvidence("rasmap", rasmap, CRS_EVIDENCE_UNREADABLE, detail=str(e))]

        evidence = []
        proj_elem = root.find(".//RASProjectionFilename")
        filename = proj_elem.get("Filename") if proj_elem is not None else None
        if filename:
            evidence.append(HdfUtils.read_crs_evidence(
                HdfUtils.resolve_ras_relative_path(rasmap.parent, filename),
                "rasmap_projection",
            ))
        else:
            evidence.append(CrsEvidence("rasmap_projection", rasmap, CRS_EVIDENCE_ABSENT,
                                        detail="no RASProjectionFilename"))

        for layer in root.findall("./Terrains/Layer"):
            layer_file = layer.get("Filename")
            if layer_file:
                evidence.append(HdfUtils.read_crs_evidence(
                    HdfUtils.resolve_ras_relative_path(rasmap.parent, layer_file),
                    "terrain_hdf",
                ))
        return evidence

    @staticmethod
    @log_call
    def resolve_crs_evidence(evidence: Sequence[CrsEvidence]) -> CrsResolution:
        """
        Resolve ordered CRS evidence without guessing.

        - ``resolved``: at least one source has a CRS and every found CRS is
          strictly equivalent (see ``crs_equivalent``). ``crs`` is the
          highest-precedence source WKT; ``authority`` is set only for an exact
          authority match; ``epsg`` is the first strictly equivalent EPSG code
          found across the agreeing evidence.
        - ``missing``: no source has a CRS. Unknown remains unknown.
        - ``conflict``: found CRSs are not equivalent. ``crs`` is ``None`` and
          ``candidates`` holds one WKT per distinct CRS, in precedence order.

        Evidence with status ``invalid``, ``unreadable``, ``absent`` or
        ``missing_file`` is kept for reporting but does not vote.

        Args:
            evidence: Evidence in precedence order (strongest first).

        Returns:
            CrsResolution
        """
        evidence = tuple(evidence)
        found = [e for e in evidence if e.status == CRS_EVIDENCE_FOUND]
        if not found:
            return CrsResolution(CRS_MISSING, None, None, None, None, evidence)

        candidates: List[str] = []
        for item in found:
            if not any(HdfUtils.crs_equivalent(item.wkt, c) for c in candidates):
                candidates.append(item.wkt)

        if len(candidates) > 1:
            logger.warning(
                "Conflicting CRS evidence (%d distinct definitions) from: %s",
                len(candidates),
                ", ".join(f"{e.source}={e.path}" for e in found),
            )
            return CrsResolution(CRS_CONFLICT, None, None, None, None, evidence,
                                 tuple(candidates))

        primary = found[0]
        authority = _exact_authority_for_text(primary.wkt)
        epsg = None
        for wkt in dict.fromkeys(item.wkt for item in found):
            epsg = HdfUtils.get_equivalent_epsg(wkt)
            if epsg is not None:
                break
        return CrsResolution(CRS_RESOLVED, primary.wkt, primary.source, primary.path,
                             authority, evidence, (primary.wkt,), epsg)
