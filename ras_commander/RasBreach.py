"""
RasBreach: Dam breach parameter modification for HEC-RAS plan files.

This module provides methods for reading and writing breach parameters in plain text
plan files (.p##). For extracting breach RESULTS from HDF files, use HdfResultsBreach class.

Architectural Separation:
    - RasBreach: Breach PARAMETERS in plain text plan files (.p##)
    - HdfResultsBreach: Breach RESULTS from HDF files (.p##.hdf)
    - HdfStruc: Structure listings and metadata from HDF

The class follows ras-commander conventions with static methods and support for
plan numbers, integers, or file paths.

Classes:
    RasBreach: Static methods for breach parameter operations
    BreachLocation: Dataclass for breach location data
    BreachBlock: Dataclass for breach parameter blocks

Key Plan File Methods:
    - list_breach_structures_plan(): List breach structures in plan file
    - read_breach_block(): Parse breach parameters from plan
    - update_breach_block(): Modify breach parameters in plan (supports DLBreach Method 9)
    - create_breach_block(): Create new breach block for a structure
    - set_breach_geom(): Update individual breach geometry parameters

DLBreach (Method 9) Support:
    Physics-based erosion modeling using soil properties. Supported parameters:
    - dlb_methods: 7-value list of method flags
    - dlb_soil_type: Soil type index (0-7)
    - dlb_soil_properties: 7-value list of erosion parameters
    - dlb_core_soil_type, dlb_cover_option, dlb_cover_soil_properties
    - dlb_breach_direction: Breach direction flag

    Advanced parameters:
    - user_growth_flag: User-defined growth ratio flag (-1 or 1)
    - user_growth_ratio: Growth ratio value
    - mass_wasting_option: Mass wasting model (0-2)

BreachBlock Getter Methods:
    - get_dlb_methods(), get_dlb_soil_type(), get_dlb_soil_properties()
    - get_dlb_core_soil_type(), get_dlb_cover_option(), get_dlb_cover_soil_properties()
    - get_dlb_breach_direction(), get_breach_method()
    - get_user_growth_flag(), get_user_growth_ratio(), get_mass_wasting_option()

For HDF Results Extraction, see HdfResultsBreach:
    - HdfResultsBreach.get_breach_timeseries(): Extract time series
    - HdfResultsBreach.get_breach_summary(): Extract summary statistics
    - HdfResultsBreach.get_breaching_variables(): Breach geometry evolution
    - HdfResultsBreach.get_structure_variables(): Structure flow variables

Author: ras-commander development team
Date: 2025
"""

from typing import Dict, List, Union, Optional, Tuple
from pathlib import Path
import pandas as pd
from datetime import datetime
import re
from dataclasses import dataclass

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasPrj import ras

logger = get_logger(__name__)


class RasBreach:
    """
    Handles dam breach parameter reading and modification in plan files.

    This class provides methods for manipulating breach parameters in plain text
    plan files (.p##). For extracting breach RESULTS from HDF files, use HdfResultsBreach.

    Key Functionality:
    - List breach structures defined in plan files
    - Read breach parameters (method, geometry, timing, etc.)
    - Create new breach blocks for structures
    - Modify breach parameters (activation, progression, geometry)
    - Support DLBreach (Method 9) physics-based erosion modeling
    - Support advanced parameters (user growth ratio, mass wasting)
    - Create backups before modification
    - Validate CRLF line endings for HEC-RAS compatibility

    All methods accept plan numbers, integers, or file paths.

    Examples:
        >>> from ras_commander import RasBreach, HdfResultsBreach
        >>>
        >>> # List breach structures in plan file
        >>> structures = RasBreach.list_breach_structures_plan("02")
        >>>
        >>> # Read breach parameters
        >>> params = RasBreach.read_breach_block("02", "Dam")
        >>> print(f"Active: {params['is_active']}")
        >>>
        >>> # Create new breach block
        >>> RasBreach.create_breach_block("02", "New_Dam", river="Big River", reach="Upper")
        >>>
        >>> # Modify parameters (traditional methods)
        >>> RasBreach.update_breach_block("02", "Dam", method=1)
        >>>
        >>> # Configure DLBreach (Method 9) with soil properties
        >>> RasBreach.update_breach_block("02", "Dam",
        ...                               method=9,
        ...                               dlb_methods=[9, 0, 0, 0, 0, 0, 0],
        ...                               dlb_soil_type=3,  # Clay
        ...                               dlb_soil_properties=[0.3, 0, 0, 0, 0, 0, 0])
        >>>
        >>> # Set advanced parameters
        >>> RasBreach.update_breach_block("02", "Dam",
        ...                               user_growth_flag=-1,
        ...                               user_growth_ratio=1.0,
        ...                               mass_wasting_option=0)
        >>>
        >>> # For HDF results extraction, use HdfResultsBreach:
        >>> timeseries = HdfResultsBreach.get_breach_timeseries("02", "Dam")
        >>> summary = HdfResultsBreach.get_breach_summary("02")
    """

    # ==========================================================================
    # PLAN FILE PARAMETER METHODS
    # NOTE: For HDF results extraction, use HdfResultsBreach class:
    #   - HdfResultsBreach.get_breach_timeseries()
    #   - HdfResultsBreach.get_breach_summary()
    #   - HdfResultsBreach.get_breaching_variables()
    #   - HdfResultsBreach.get_structure_variables()
    # ==========================================================================

    # ==========================================================================
    # PLAN FILE PARAMETER METHODS
    # ==========================================================================

    @dataclass
    class BreachLocation:
        """Represents the structured data encoded in the `Breach Loc` line."""
        river: str
        reach: str
        station: str
        is_active: bool
        structure: str

        @classmethod
        def from_value(cls, value: str) -> "RasBreach.BreachLocation":
            parts = value.split(",")
            if len(parts) < 5:
                raise ValueError(f"Unexpected Breach Loc format: '{value}'")
            river = parts[0].strip()
            reach = parts[1].strip()
            station = parts[2].strip()
            flag = parts[3].strip()
            structure = ",".join(parts[4:]).strip()
            return cls(
                river=river,
                reach=reach,
                station=station,
                is_active=flag.strip().lower() in {"true", "1", "yes"},
                structure=structure,
            )

    @dataclass
    class BreachBlock:
        """Structured representation of a breach block within a plan file."""
        start_index: int
        end_index: int
        order: List[Tuple[str, str]]
        values: Dict[str, str]
        table_rows: Dict[str, List[List[float]]]
        table_row_lengths: Dict[str, List[int]]

        # Numeric table keys
        NUMERIC_TABLE_KEYS = {
            "Breach Progression",
            "Simplified Physical Breach Downcutting",
            "Simplified Physical Breach Widening",
        }
        DEFAULT_VALUES_PER_ROW = 10
        FIXED_WIDTH = 8

        @property
        def location(self) -> "RasBreach.BreachLocation":
            return RasBreach.BreachLocation.from_value(self.values["Breach Loc"])

        @property
        def structure_name(self) -> str:
            return self.location.structure.strip()

        @property
        def is_active(self) -> bool:
            return self.location.is_active

        def to_dict(self) -> Dict:
            """Convert breach block to dictionary for easy inspection."""
            return {
                'structure_name': self.structure_name,
                'is_active': self.is_active,
                'river': self.location.river,
                'reach': self.location.reach,
                'station': self.location.station,
                'values': self.values.copy(),
                'table_rows': self.table_rows.copy(),
            }

        # ======================================================================
        # DLBreach Getter Methods (Method 9)
        # ======================================================================

        def get_dlb_methods(self) -> List[str]:
            """
            Parse DLBreach Methods from plan file.

            Returns
            -------
            List[str]
                List of 7 DLBreach method values, or empty list if not set.
            """
            raw = self.values.get("DLBreach Methods", "")
            if not raw:
                return []
            return [x.strip() for x in raw.split(",")]

        def get_dlb_soil_type(self) -> str:
            """
            Get DLBreach SoilType.

            Returns
            -------
            str
                Soil type value (0-7), or empty string if not set.
            """
            return self.values.get("DLBreach SoilType", "").strip()

        def get_dlb_soil_properties(self) -> List[str]:
            """
            Parse DLBreach Soil Properties from plan file.

            Returns
            -------
            List[str]
                List of 7 soil property values, or empty list if not set.
            """
            raw = self.values.get("DLBreach Soil Properties", "")
            if not raw:
                return []
            return [x.strip() for x in raw.split(",")]

        def get_dlb_core_soil_type(self) -> str:
            """
            Get DLBreach Core SoilType.

            Returns
            -------
            str
                Core soil type value, or empty string if not set.
            """
            return self.values.get("DLBreach Core SoilType", "").strip()

        def get_dlb_cover_option(self) -> str:
            """
            Get DLBreach Cover Option.

            Returns
            -------
            str
                Cover option value, or empty string if not set.
            """
            return self.values.get("DLBreach Cover Option", "").strip()

        def get_dlb_cover_soil_properties(self) -> List[str]:
            """
            Parse DLBreach Cover Soil Properties from plan file.

            Returns
            -------
            List[str]
                List of 7 cover soil property values, or empty list if not set.
            """
            raw = self.values.get("DLBreach Cover Soil Properties", "")
            if not raw:
                return []
            return [x.strip() for x in raw.split(",")]

        def get_dlb_breach_direction(self) -> str:
            """
            Get DLBreach Breach Direction.

            Returns
            -------
            str
                Breach direction value, or empty string if not set.
            """
            return self.values.get("DLBreach Breach Direction", "").strip()

        # ======================================================================
        # Advanced Parameter Getter Methods
        # ======================================================================

        def get_user_growth_flag(self) -> Optional[int]:
            """
            Get Breach Use User Defined Growth Ratio flag.

            Returns
            -------
            Optional[int]
                Growth flag value (-1 or 1), or None if not set.
            """
            raw = self.values.get("Breach Use User Defined Growth Ratio", "").strip()
            return int(raw) if raw else None

        def get_user_growth_ratio(self) -> Optional[float]:
            """
            Get Breach User Defined Growth Ratio value.

            Returns
            -------
            Optional[float]
                Growth ratio value, or None if not set.
            """
            raw = self.values.get("Breach User Defined Growth Ratio", "").strip()
            return float(raw) if raw else None

        def get_mass_wasting_option(self) -> Optional[int]:
            """
            Get Mass Wasting Options value.

            Returns
            -------
            Optional[int]
                Mass wasting option (0-2), or None if not set.
            """
            raw = self.values.get("Mass Wasting Options", "").strip()
            return int(raw) if raw else None

        def get_breach_method(self) -> Optional[int]:
            """
            Get Breach Method value.

            Returns
            -------
            Optional[int]
                Breach method (0-9), or None if not set.
            """
            raw = self.values.get("Breach Method", "").strip()
            return int(raw) if raw else None

        def to_lines(self) -> List[str]:
            """Serialize breach block back to plan file format."""
            lines: List[str] = []
            for kind, key in self.order:
                if kind == "line":
                    lines.append(f"{key}={self.values[key]}")
                elif kind == "table":
                    rows = self.table_rows.get(key, [])
                    if rows:
                        lines.extend(RasBreach._format_numeric_rows(rows, width=self.FIXED_WIDTH))
                elif kind == "blank":
                    lines.append("")
                elif kind == "literal":
                    lines.append(key)
            return lines

    @staticmethod
    @log_call
    def list_breach_structures_plan(plan_input: Union[str, int, Path], *, ras_object=None) -> List[Dict]:
        """
        List all breach structures defined in plan file.

        Parameters
        ----------
        plan_input : Union[str, int, Path]
            Plan number (e.g., "02", 2) or path to HEC-RAS plan file
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        List[Dict]
            List of dictionaries containing breach location information:
            - structure: Structure name
            - river: River name
            - reach: Reach name
            - station: River station
            - is_active: Boolean, True if breach is active

        Examples
        --------
        >>> # Using plan number
        >>> structures = RasBreach.list_breach_structures_plan("02")
        >>> for struct in structures:
        ...     print(f"{struct['structure']}: Active={struct['is_active']}")
        >>>
        >>> # Using plan file path
        >>> plan_path = Path("MyProject.p02")
        >>> structures = RasBreach.list_breach_structures_plan(plan_path)

        Notes
        -----
        - Returns breach structures regardless of activation status
        - Use is_active field to filter for active breaches only
        - Accepts plan number (string/int) or full plan file path
        """
        from .RasUtils import RasUtils
        
        ras_obj = ras_object or ras
        
        try:
            # Handle plan number or path input
            if isinstance(plan_input, Path):
                plan_path = plan_input
            elif isinstance(plan_input, str):
                # Check if it's a file path
                test_path = Path(plan_input)
                if test_path.exists():
                    plan_path = test_path
                else:
                    # It's a plan number
                    ras_obj.check_initialized()
                    plan_number = RasUtils.normalize_ras_number(plan_input)
                    plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
            elif isinstance(plan_input, int):
                # It's a plan number
                ras_obj.check_initialized()
                plan_number = RasUtils.normalize_ras_number(plan_input)
                plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
            else:
                raise ValueError(f"Invalid plan_input type: {type(plan_input)}")
            
            if not plan_path.exists():
                raise FileNotFoundError(f"Plan file not found: {plan_path}")
            
            blocks = RasBreach._read_breach_blocks_internal(plan_path)
            locations = []
            for block in blocks:
                loc = block.location
                locations.append({
                    'structure': loc.structure,
                    'river': loc.river,
                    'reach': loc.reach,
                    'station': loc.station,
                    'is_active': loc.is_active
                })
            logger.info(f"Found {len(locations)} breach structures in {plan_path.name}")
            return locations
        except Exception as e:
            logger.error(f"Error listing breach structures: {e}")
            raise

    @staticmethod
    @log_call
    def read_breach_block(plan_input: Union[str, int, Path], structure_name: str, *, ras_object=None) -> Dict:
        """
        Read breach parameters for specified structure from plan file.

        Parameters
        ----------
        plan_input : Union[str, int, Path]
            Plan number (e.g., "02", 2) or path to HEC-RAS plan file
        structure_name : str
            Name of breach structure to read
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        Dict
            Dictionary containing all breach parameters:
            - structure_name: Structure name
            - is_active: Boolean, breach activation status
            - river, reach, station: Location information
            - values: Dict of all breach parameter values
            - table_rows: Dict of numeric tables (progression, downcutting, etc.)

        Examples
        --------
        >>> # Using plan number
        >>> breach_data = RasBreach.read_breach_block("02", "Laxton_Dam")
        >>> print(f"Active: {breach_data['is_active']}")
        >>>
        >>> # Using plan file path
        >>> plan_path = Path("MyProject.p02")
        >>> breach_data = RasBreach.read_breach_block(plan_path, "Laxton_Dam")

        Raises
        ------
        ValueError
            If specified structure not found in plan file

        Notes
        -----
        - Accepts plan number (string/int) or full plan file path
        - Uses RasUtils.normalize_ras_number() for plan number handling
        - All values returned as strings; parse as needed
        """
        from .RasUtils import RasUtils

        ras_obj = ras_object or ras

        try:
            # Handle plan number or path input
            if isinstance(plan_input, Path):
                plan_path = plan_input
            elif isinstance(plan_input, str):
                # Check if it's a file path
                test_path = Path(plan_input)
                if test_path.exists():
                    plan_path = test_path
                else:
                    # It's a plan number
                    ras_obj.check_initialized()
                    plan_number = RasUtils.normalize_ras_number(plan_input)
                    plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
            elif isinstance(plan_input, int):
                # It's a plan number
                ras_obj.check_initialized()
                plan_number = RasUtils.normalize_ras_number(plan_input)
                plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
            else:
                raise ValueError(f"Invalid plan_input type: {type(plan_input)}")

            if not plan_path.exists():
                raise FileNotFoundError(f"Plan file not found: {plan_path}")

            blocks = RasBreach._read_breach_blocks_internal(plan_path)
            block = RasBreach._find_block_by_structure(blocks, structure_name)

            if block is None:
                raise ValueError(f"Structure '{structure_name}' not found in {plan_path.name}")

            logger.info(f"Read breach block for {structure_name} from {plan_path.name}")
            return block.to_dict()

        except Exception as e:
            logger.error(f"Error reading breach block: {e}")
            raise

    @staticmethod
    @log_call
    def update_breach_block(
        plan_input: Union[str, int, Path],
        structure_name: str,
        *,
        is_active: bool = None,
        method: int = None,
        geom_values: List = None,
        start_values: List = None,
        progression_mode: int = None,
        progression_pairs: List[Tuple[float, float]] = None,
        downcutting_pairs: List[Tuple[float, float]] = None,
        widening_pairs: List[Tuple[float, float]] = None,
        calculator_data: List = None,
        # DLBreach parameters (Method 9)
        dlb_methods: Optional[List] = None,
        dlb_soil_type: Optional[Union[str, int]] = None,
        dlb_soil_properties: Optional[List] = None,
        dlb_core_soil_type: Optional[Union[str, int]] = None,
        dlb_cover_option: Optional[Union[str, int]] = None,
        dlb_cover_soil_properties: Optional[List] = None,
        dlb_breach_direction: Optional[Union[str, int]] = None,
        # Advanced parameters
        user_growth_flag: Optional[int] = None,
        user_growth_ratio: Optional[float] = None,
        mass_wasting_option: Optional[int] = None,
        create_backup: bool = True,
        ras_object=None
    ) -> Dict:
        """
        Update breach parameters for specified structure in plan file.

        **CRITICAL**: Creates backup before modification. Uses CRLF line endings for HEC-RAS compatibility.

        Parameters
        ----------
        plan_input : Union[str, int, Path]
            Plan number (e.g., "02", 2) or path to HEC-RAS plan file
        structure_name : str
            Name of breach structure to update
        is_active : bool, optional
            Set breach activation status (True/False)
        method : int, optional
            Breach calculation method (0-9, where 9 is DLBreach)
        geom_values : List, optional
            Breach geometry values: [center_station, final_width, final_elev,
            left_slope, right_slope, weir_coef, formation_time]
        start_values : List, optional
            Breach starting conditions
        progression_mode : int, optional
            Progression mode (0=Linear, 1=Non-linear)
        progression_pairs : List[Tuple[float, float]], optional
            Time/breach fraction pairs for non-linear progression
        downcutting_pairs : List[Tuple[float, float]], optional
            Time/elevation pairs for physical breach downcutting
        widening_pairs : List[Tuple[float, float]], optional
            Time/width pairs for physical breach widening
        calculator_data : List, optional
            Breach calculator heuristic inputs
        dlb_methods : List, optional
            DLBreach Methods (7 values, first is primary method 0-9)
        dlb_soil_type : Union[str, int], optional
            DLBreach SoilType (0-7)
        dlb_soil_properties : List, optional
            DLBreach Soil Properties (7 erosion parameter values)
        dlb_core_soil_type : Union[str, int], optional
            DLBreach Core SoilType
        dlb_cover_option : Union[str, int], optional
            DLBreach Cover Option
        dlb_cover_soil_properties : List, optional
            DLBreach Cover Soil Properties (7 values)
        dlb_breach_direction : Union[str, int], optional
            DLBreach Breach Direction
        user_growth_flag : int, optional
            User-defined growth flag (-1 or 1)
        user_growth_ratio : float, optional
            User-defined growth ratio (dimensionless)
        mass_wasting_option : int, optional
            Mass wasting model option (0-2)
        create_backup : bool, default True
            Create backup file before modification
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        Dict
            Updated breach block as dictionary

        Examples
        --------
        >>> # Activate breach
        >>> RasBreach.update_breach_block("02", "Laxton_Dam", is_active=True)

        >>> # Set breach geometry
        >>> geom = [150, 100, 1400, 1, 1, 2.6, 0.5]  # center, width, elev, slopes, coef, time
        >>> RasBreach.update_breach_block("02", "Laxton_Dam", geom_values=geom)

        >>> # Set non-linear progression
        >>> progression = [(0, 0), (0.5, 0.3), (1.0, 1.0)]  # time, fraction pairs
        >>> RasBreach.update_breach_block("02", "Laxton_Dam",
        ...                               progression_mode=1,
        ...                               progression_pairs=progression)

        >>> # Configure DLBreach (Method 9) with soil properties
        >>> RasBreach.update_breach_block("02", "Dam",
        ...                               method=9,
        ...                               dlb_methods=[9, 0, 0, 0, 0, 0, 0],
        ...                               dlb_soil_type=3,  # Clay
        ...                               dlb_soil_properties=[0.3, 0, 0, 0, 0, 0, 0])

        >>> # Set advanced parameters
        >>> RasBreach.update_breach_block("02", "Dam",
        ...                               user_growth_flag=-1,
        ...                               user_growth_ratio=1.0,
        ...                               mass_wasting_option=0)

        Raises
        ------
        ValueError
            If structure not found in plan file, or if dlb_methods doesn't have 7 values
        RuntimeError
            If CRLF line endings not preserved (HEC-RAS incompatibility)

        Warnings
        --------
        - Modifies plan file in-place
        - Backup created in same directory with timestamp
        - HEC-RAS must be closed before modification
        - Validates CRLF line endings after write

        Notes
        -----
        Based on TNTech Dam Breach Dashboard breach_io.py implementation.
        Adapted to ras-commander conventions with plan-number support.
        DLBreach (Method 9) provides physics-based erosion modeling using soil properties.
        """
        from .RasUtils import RasUtils

        ras_obj = ras_object or ras

        try:
            # Handle plan number or path input
            if isinstance(plan_input, Path):
                plan_path = plan_input
            elif isinstance(plan_input, str):
                # Check if it's a file path
                test_path = Path(plan_input)
                if test_path.exists():
                    plan_path = test_path
                else:
                    # It's a plan number
                    ras_obj.check_initialized()
                    plan_number = RasUtils.normalize_ras_number(plan_input)
                    plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
            elif isinstance(plan_input, int):
                # It's a plan number
                ras_obj.check_initialized()
                plan_number = RasUtils.normalize_ras_number(plan_input)
                plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
            else:
                raise ValueError(f"Invalid plan_input type: {type(plan_input)}")

            if not plan_path.exists():
                raise FileNotFoundError(f"Plan file not found: {plan_path}")

            # Read all breach blocks
            lines = plan_path.read_text().splitlines()
            blocks = RasBreach._parse_breach_blocks(lines)
            block = RasBreach._find_block_by_structure(blocks, structure_name)

            if block is None:
                raise ValueError(f"Structure '{structure_name}' not found in {plan_path.name}")

            # Apply updates
            if is_active is not None:
                RasBreach._set_activation(block, is_active)
            if method is not None:
                block.values["Breach Method"] = f" {int(method)}"
            if geom_values is not None:
                block.values["Breach Geom"] = RasBreach._format_csv(geom_values)
            if start_values is not None:
                block.values["Breach Start"] = RasBreach._format_csv(start_values)
            if progression_mode is not None or progression_pairs is not None:
                mode = progression_mode if progression_mode is not None else int(block.values["Breach Progression"].strip())
                RasBreach._set_progression(block, mode, progression_pairs)
            if downcutting_pairs is not None:
                RasBreach._set_table_pairs(block, "Simplified Physical Breach Downcutting", downcutting_pairs)
            if widening_pairs is not None:
                RasBreach._set_table_pairs(block, "Simplified Physical Breach Widening", widening_pairs)
            if calculator_data is not None:
                block.values["Breach Calculator Data"] = RasBreach._format_csv(calculator_data)

            # Apply DLBreach parameters (Method 9)
            if dlb_methods is not None:
                if len(dlb_methods) != 7:
                    raise ValueError(f"dlb_methods must have exactly 7 values, got {len(dlb_methods)}")
                RasBreach._ensure_key_in_order(block, "DLBreach Methods")
                block.values["DLBreach Methods"] = RasBreach._format_csv(dlb_methods)
            if dlb_soil_type is not None:
                RasBreach._ensure_key_in_order(block, "DLBreach SoilType")
                block.values["DLBreach SoilType"] = RasBreach._format_scalar(dlb_soil_type)
            if dlb_soil_properties is not None:
                if len(dlb_soil_properties) != 7:
                    raise ValueError(f"dlb_soil_properties must have exactly 7 values, got {len(dlb_soil_properties)}")
                RasBreach._ensure_key_in_order(block, "DLBreach Soil Properties")
                block.values["DLBreach Soil Properties"] = RasBreach._format_csv(dlb_soil_properties)
            if dlb_core_soil_type is not None:
                RasBreach._ensure_key_in_order(block, "DLBreach Core SoilType")
                block.values["DLBreach Core SoilType"] = RasBreach._format_scalar(dlb_core_soil_type)
            if dlb_cover_option is not None:
                RasBreach._ensure_key_in_order(block, "DLBreach Cover Option")
                block.values["DLBreach Cover Option"] = RasBreach._format_scalar(dlb_cover_option)
            if dlb_cover_soil_properties is not None:
                if len(dlb_cover_soil_properties) != 7:
                    raise ValueError(f"dlb_cover_soil_properties must have exactly 7 values, got {len(dlb_cover_soil_properties)}")
                RasBreach._ensure_key_in_order(block, "DLBreach Cover Soil Properties")
                block.values["DLBreach Cover Soil Properties"] = RasBreach._format_csv(dlb_cover_soil_properties)
            if dlb_breach_direction is not None:
                RasBreach._ensure_key_in_order(block, "DLBreach Breach Direction")
                block.values["DLBreach Breach Direction"] = RasBreach._format_scalar(dlb_breach_direction)

            # Apply advanced parameters
            if user_growth_flag is not None:
                RasBreach._ensure_key_in_order(block, "Breach Use User Defined Growth Ratio")
                block.values["Breach Use User Defined Growth Ratio"] = str(int(user_growth_flag))
            if user_growth_ratio is not None:
                RasBreach._ensure_key_in_order(block, "Breach User Defined Growth Ratio")
                block.values["Breach User Defined Growth Ratio"] = str(user_growth_ratio)
            if mass_wasting_option is not None:
                RasBreach._ensure_key_in_order(block, "Mass Wasting Options")
                block.values["Mass Wasting Options"] = RasBreach._format_scalar(mass_wasting_option)

            # Replace block lines in file
            new_block_lines = block.to_lines()
            lines[block.start_index:block.end_index] = new_block_lines
            block.end_index = block.start_index + len(new_block_lines)

            # Create backup
            if create_backup:
                RasBreach._create_backup(plan_path)

            # Write with CRLF line endings (CRITICAL for HEC-RAS)
            if lines and not lines[-1].endswith("\n"):
                output = "\r\n".join(lines) + "\r\n"
            else:
                output = "\r\n".join(lines)

            # Use open() with newline='' to preserve CRLF
            with open(plan_path, 'w', encoding='utf-8', newline='') as f:
                f.write(output)

            # Validate CRLF preservation
            if not RasBreach._validate_crlf(plan_path):
                raise RuntimeError(
                    f"CRITICAL: Failed to preserve CRLF line endings in {plan_path}. "
                    "HEC-RAS will not be able to open this project."
                )

            logger.info(f"Updated breach block for {structure_name} in {plan_path.name}")
            return block.to_dict()

        except Exception as e:
            logger.error(f"Error updating breach block: {e}")
            raise

    @staticmethod
    @log_call
    def set_breach_geom(
        plan_input: Union[str, int, Path],
        structure_name: str,
        *,
        centerline: Optional[float] = None,
        initial_width: Optional[float] = None,
        final_bottom_elev: Optional[float] = None,
        left_slope: Optional[float] = None,
        right_slope: Optional[float] = None,
        active: Optional[bool] = None,
        weir_coef: Optional[float] = None,
        top_elev: Optional[float] = None,
        formation_method: Optional[int] = None,
        formation_time: Optional[float] = None,
        ras_object=None
    ) -> Dict:
        """
        Update individual breach geometry parameters.

        Convenience function for modifying specific breach geometry fields without
        reconstructing the entire Breach Geom CSV. Reads current values and updates
        only the specified parameters.

        Parameters
        ----------
        plan_input : Union[str, int, Path]
            Plan number (e.g., "02", 2) or path to HEC-RAS plan file
        structure_name : str
            Name of breach structure to update
        centerline : float, optional
            Centerline/station location (ft or m)
        initial_width : float, optional
            Initial breach bottom width (ft or m)
        final_bottom_elev : float, optional
            Final breach bottom elevation (ft or m) - **Common modification**
        left_slope : float, optional
            Left side slope (H:V ratio, e.g., 0.5 = 0.5H:1V)
        right_slope : float, optional
            Right side slope (H:V ratio)
        active : bool, optional
            Breach activation flag (True/False)
        weir_coef : float, optional
            Weir discharge coefficient (dimensionless)
        top_elev : float, optional
            Top elevation (ft or m)
        formation_method : int, optional
            Formation method (1=Time-based, 2=Trigger-based)
        formation_time : float, optional
            Formation time (hrs) or trigger threshold (ft)
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        Dict
            Updated breach block dictionary

        Examples
        --------
        >>> # Update just Final Bottom Elevation
        >>> RasBreach.set_breach_geom("19", "Dam", final_bottom_elev=605)
        >>>
        >>> # Update multiple parameters
        >>> RasBreach.set_breach_geom("19", "Dam",
        ...                           initial_width=250,
        ...                           final_bottom_elev=600,
        ...                           formation_time=3.0)
        >>>
        >>> # Change breach to time-based formation
        >>> RasBreach.set_breach_geom("template_plan", "Dam",
        ...                           formation_method=1,
        ...                           formation_time=2.5)

        Notes
        -----
        - Only specified parameters are modified; others retain current values
        - Automatically reads current Breach Geom and updates selectively
        - Creates backup before modification
        - Validates CRLF line endings

        Breach Geom Field Reference:
            [0] centerline - Breach centerline/station location
            [1] initial_width - Starting breach width
            [2] final_bottom_elev - Final breach bottom elevation
            [3] left_slope - Left side slope (H:V)
            [4] right_slope - Right side slope (H:V)
            [5] active - Activation flag
            [6] weir_coef - Weir discharge coefficient
            [7] top_elev - Top elevation
            [8] formation_method - 1=Time, 2=Trigger
            [9] formation_time - Time (hrs) or threshold (ft)
        """
        try:
            # Read current breach block
            current_block = RasBreach.read_breach_block(plan_input, structure_name, ras_object=ras_object)

            # Parse current Breach Geom values
            geom_str = current_block['values'].get('Breach Geom', '')
            if not geom_str:
                raise ValueError(f"No Breach Geom found for structure '{structure_name}'")

            current_geom = [x.strip() for x in geom_str.split(',')]

            if len(current_geom) < 10:
                raise ValueError(f"Breach Geom has {len(current_geom)} fields, expected 10")

            # Update specified parameters (preserve current values for None parameters)
            new_geom = current_geom.copy()

            if centerline is not None:
                new_geom[0] = centerline
            if initial_width is not None:
                new_geom[1] = initial_width
            if final_bottom_elev is not None:
                new_geom[2] = final_bottom_elev
            if left_slope is not None:
                new_geom[3] = left_slope
            if right_slope is not None:
                new_geom[4] = right_slope
            if active is not None:
                new_geom[5] = active
            if weir_coef is not None:
                new_geom[6] = weir_coef
            if top_elev is not None:
                new_geom[7] = top_elev
            if formation_method is not None:
                new_geom[8] = formation_method
            if formation_time is not None:
                new_geom[9] = formation_time

            # Log what changed
            changes = []
            field_names = ['centerline', 'initial_width', 'final_bottom_elev', 'left_slope', 'right_slope',
                          'active', 'weir_coef', 'top_elev', 'formation_method', 'formation_time']
            for idx, (old, new, name) in enumerate(zip(current_geom, new_geom, field_names)):
                if str(old) != str(new):
                    changes.append(f"{name}: {old} → {new}")

            if changes:
                logger.info(f"Modifying breach geometry for {structure_name}: {', '.join(changes)}")
            else:
                logger.warning(f"No changes specified for {structure_name}")

            # Update using existing update_breach_block method
            return RasBreach.update_breach_block(
                plan_input,
                structure_name,
                geom_values=new_geom,
                ras_object=ras_object
            )

        except Exception as e:
            logger.error(f"Error setting breach geometry: {e}")
            raise

    @staticmethod
    @log_call
    def create_breach_block(
        plan_input: Union[str, int, Path],
        structure_name: str,
        *,
        river: str = "",
        reach: str = "",
        station: str = "",
        is_active: bool = True,
        create_backup: bool = True,
        ras_object=None
    ) -> Dict:
        """
        Create a new breach block for a structure in the plan file.

        Creates a minimal breach block with default parameters that can be
        customized using update_breach_block() after creation.

        **CRITICAL**: Creates backup before modification. Uses CRLF line endings for HEC-RAS compatibility.

        Parameters
        ----------
        plan_input : Union[str, int, Path]
            Plan number (e.g., "02", 2) or path to HEC-RAS plan file
        structure_name : str
            Name of breach structure (must match structure name in geometry file)
        river : str, optional
            River name (default: empty string)
        reach : str, optional
            Reach name (default: empty string)
        station : str, optional
            River station (default: empty string)
        is_active : bool, default True
            Initial breach activation status
        create_backup : bool, default True
            Create backup file before modification
        ras_object : RasPrj, optional
            RAS object for multi-project workflows

        Returns
        -------
        Dict
            Created breach block as dictionary with default parameters

        Examples
        --------
        >>> # Create new breach block
        >>> RasBreach.create_breach_block("02", "New_Dam")
        >>>
        >>> # Create with location info
        >>> RasBreach.create_breach_block("02", "Dam",
        ...                               river="Big River",
        ...                               reach="Upper",
        ...                               station="5000")
        >>>
        >>> # Create and then configure
        >>> RasBreach.create_breach_block("02", "Dam")
        >>> RasBreach.update_breach_block("02", "Dam",
        ...                               method=9,
        ...                               dlb_methods=[9, 0, 0, 0, 0, 0, 0],
        ...                               dlb_soil_type=3)

        Raises
        ------
        ValueError
            If structure already has a breach block in the plan file
        RuntimeError
            If CRLF line endings not preserved (HEC-RAS incompatibility)

        Warnings
        --------
        - Modifies plan file in-place
        - Backup created in same directory with timestamp
        - HEC-RAS must be closed before modification
        - Validates CRLF line endings after write

        Notes
        -----
        Creates a minimal breach block with:
        - Method 0 (user-specified breach geometry)
        - Empty geometry values (must be set via update_breach_block or set_breach_geom)
        - Empty start conditions
        - Empty breach progression

        The block is inserted after the last existing breach block in the file,
        or at the end if no breach blocks exist.
        """
        from .RasUtils import RasUtils

        ras_obj = ras_object or ras

        try:
            # Handle plan number or path input
            if isinstance(plan_input, Path):
                plan_path = plan_input
            elif isinstance(plan_input, str):
                # Check if it's a file path
                test_path = Path(plan_input)
                if test_path.exists():
                    plan_path = test_path
                else:
                    # It's a plan number
                    ras_obj.check_initialized()
                    plan_number = RasUtils.normalize_ras_number(plan_input)
                    plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
            elif isinstance(plan_input, int):
                # It's a plan number
                ras_obj.check_initialized()
                plan_number = RasUtils.normalize_ras_number(plan_input)
                plan_path = ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_number}"
            else:
                raise ValueError(f"Invalid plan_input type: {type(plan_input)}")

            if not plan_path.exists():
                raise FileNotFoundError(f"Plan file not found: {plan_path}")

            # Read all lines and parse existing breach blocks
            lines = plan_path.read_text().splitlines()
            blocks = RasBreach._parse_breach_blocks(lines)

            # Check if structure already has a breach block
            existing = RasBreach._find_block_by_structure(blocks, structure_name)
            if existing is not None:
                raise ValueError(
                    f"Structure '{structure_name}' already has a breach block in {plan_path.name}. "
                    "Use update_breach_block() to modify existing blocks."
                )

            # Build Breach Loc line
            river_padded = river.rjust(16) if river else "".rjust(16)
            reach_padded = reach.rjust(16) if reach else "".rjust(16)
            station_padded = station.rjust(8) if station else "".rjust(8)
            active_flag = "True" if is_active else "False"
            structure_padded = structure_name.ljust(16)
            breach_loc = f"{river_padded},{reach_padded},{station_padded},{active_flag},{structure_padded}"

            # Build minimal breach block lines (Method 0 default)
            new_block_lines = [
                f"Breach Loc={breach_loc}",
                "Breach Method= 0",
                "Breach Geom= 0, 0, 0, 0, 0, True, 2.6, 0, 1, 0",
                "Breach Start= 0,",
                "Breach Progression= 0",
                "Breach Calculator Data= 0, 0, 0, 0, 0, 0, 0",
                "",  # Trailing blank line
            ]

            # Find insertion point (after last existing breach block)
            if blocks:
                # Insert after the last breach block
                last_block = blocks[-1]
                insert_idx = last_block.end_index
            else:
                # No existing breach blocks - find a good location
                # Look for common plan file sections to insert before
                insert_idx = len(lines)  # Default to end of file
                for i, line in enumerate(lines):
                    # Insert before these typical end-of-file sections
                    if line.startswith("IC Time=") or line.startswith("Met Data") or line.startswith("Sim Duration"):
                        insert_idx = i
                        break

            # Insert the new block
            for i, block_line in enumerate(new_block_lines):
                lines.insert(insert_idx + i, block_line)

            # Create backup
            if create_backup:
                RasBreach._create_backup(plan_path)

            # Write with CRLF line endings (CRITICAL for HEC-RAS)
            if lines and not lines[-1].endswith("\n"):
                output = "\r\n".join(lines) + "\r\n"
            else:
                output = "\r\n".join(lines)

            # Use open() with newline='' to preserve CRLF
            with open(plan_path, 'w', encoding='utf-8', newline='') as f:
                f.write(output)

            # Validate CRLF preservation
            if not RasBreach._validate_crlf(plan_path):
                raise RuntimeError(
                    f"CRITICAL: Failed to preserve CRLF line endings in {plan_path}. "
                    "HEC-RAS will not be able to open this project."
                )

            logger.info(f"Created breach block for {structure_name} in {plan_path.name}")

            # Re-read to return the created block
            updated_blocks = RasBreach._read_breach_blocks_internal(plan_path)
            created_block = RasBreach._find_block_by_structure(updated_blocks, structure_name)
            if created_block is None:
                raise RuntimeError(f"Failed to verify created breach block for {structure_name}")

            return created_block.to_dict()

        except Exception as e:
            logger.error(f"Error creating breach block: {e}")
            raise

    # ==========================================================================
    # INTERNAL HELPER METHODS
    # ==========================================================================

    @staticmethod
    def _read_breach_blocks_internal(plan_path: Path) -> List["RasBreach.BreachBlock"]:
        """Internal method to read and parse breach blocks from plan file."""
        lines = plan_path.read_text().splitlines()
        return RasBreach._parse_breach_blocks(lines)

    @staticmethod
    def _parse_breach_blocks(lines: List[str]) -> List["RasBreach.BreachBlock"]:
        """Parse all breach blocks from plan file lines."""
        blocks: List[RasBreach.BreachBlock] = []
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            if line.startswith("Breach Loc="):
                start_idx = idx
                block_lines = [line]
                idx += 1
                while idx < len(lines):
                    candidate = lines[idx]
                    if candidate.startswith("Breach Loc=") and block_lines:
                        break
                    block_lines.append(candidate)
                    idx += 1
                end_idx = start_idx + len(block_lines)
                block = RasBreach._parse_block(block_lines, start_idx, end_idx)
                blocks.append(block)
            else:
                idx += 1
        return blocks

    @staticmethod
    def _parse_block(block_lines: List[str], start_index: int, end_index: int) -> "RasBreach.BreachBlock":
        """Parse single breach block from lines."""
        values: Dict[str, str] = {}
        table_rows: Dict[str, List[List[float]]] = {}
        order: List[Tuple[str, str]] = []
        current_table_key: Optional[str] = None

        for line in block_lines:
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.rstrip()
                values[key] = value
                order.append(("line", key))
                if key in RasBreach.BreachBlock.NUMERIC_TABLE_KEYS:
                    order.append(("table", key))
                    current_table_key = key
                    table_rows.setdefault(key, [])
                else:
                    current_table_key = None
            else:
                if current_table_key:
                    stripped = line.strip()
                    if stripped:
                        numeric_row = [float(part) for part in stripped.split()]
                        table_rows.setdefault(current_table_key, []).append(numeric_row)
                else:
                    if line.strip() == "":
                        order.append(("blank", ""))
                    else:
                        order.append(("literal", line))

        table_row_lengths = {key: [len(row) for row in rows] for key, rows in table_rows.items()}
        return RasBreach.BreachBlock(
            start_index=start_index,
            end_index=end_index,
            order=order,
            values=values,
            table_rows=table_rows,
            table_row_lengths=table_row_lengths,
        )

    @staticmethod
    def _find_block_by_structure(blocks: List["RasBreach.BreachBlock"], structure_name: str) -> Optional["RasBreach.BreachBlock"]:
        """Find breach block by structure name (case-insensitive)."""
        target = structure_name.strip().lower()
        for block in blocks:
            if block.structure_name.lower() == target:
                return block
        return None

    @staticmethod
    def _set_activation(block: "RasBreach.BreachBlock", is_active: bool) -> None:
        """Set breach activation status."""
        loc = block.location
        loc.is_active = bool(is_active)
        river = (loc.river or "").rjust(16)
        reach = (loc.reach or "").rjust(16)
        station = (loc.station or "").rjust(8)
        flag = "True" if loc.is_active else "False"
        structure = (loc.structure or "").ljust(16)
        block.values["Breach Loc"] = f"{river},{reach},{station},{flag},{structure}"

    @staticmethod
    def _set_progression(block: "RasBreach.BreachBlock", mode: int, pairs: Optional[List[Tuple[float, float]]]) -> None:
        """Set breach progression mode and pairs."""
        block.values["Breach Progression"] = f" {int(mode)}"
        if pairs is not None:
            flat_values: List[float] = []
            for pair in pairs:
                if len(pair) != 2:
                    raise ValueError("Progression pairs must contain exactly two values")
                flat_values.extend([float(pair[0]), float(pair[1])])
            RasBreach._set_table_values(block, "Breach Progression", flat_values)

    @staticmethod
    def _set_table_pairs(block: "RasBreach.BreachBlock", key: str, pairs: List[Tuple[float, float]]) -> None:
        """Set table values from time/value pairs."""
        flat_values: List[float] = []
        for pair in pairs:
            if len(pair) != 2:
                raise ValueError(f"{key} pairs must contain exactly two values")
            flat_values.extend([float(pair[0]), float(pair[1])])
        RasBreach._set_table_values(block, key, flat_values)

    @staticmethod
    def _set_table_values(block: "RasBreach.BreachBlock", key: str, values: List[float]) -> None:
        """Set numeric table values for breach block."""
        lengths = block.table_row_lengths.get(key)
        if lengths and sum(lengths) == len(values):
            rows: List[List[float]] = []
            index = 0
            for length in lengths:
                rows.append(list(values[index:index + length]))
                index += length
        else:
            rows = []
            chunk = RasBreach.BreachBlock.DEFAULT_VALUES_PER_ROW
            for index in range(0, len(values), chunk):
                rows.append(list(values[index:index + chunk]))

        block.table_rows[key] = rows
        block.table_row_lengths[key] = [len(row) for row in rows]

    @staticmethod
    def _format_numeric_rows(rows: List[List[float]], width: int) -> List[str]:
        """Format numeric table rows for plan file."""
        formatted: List[str] = []
        for row in rows:
            formatted.append("".join(RasBreach._format_numeric_value(value, width=width) for value in row))
        return formatted

    @staticmethod
    def _format_numeric_value(value: float, width: int) -> str:
        """Format single numeric value with fixed width."""
        numeric = float(value)
        if numeric == 0:
            text = "0"
        elif abs(numeric) >= 10000 or (0 < abs(numeric) < 1e-4):
            text = f"{numeric:.3e}"
        else:
            text = f"{numeric:.6g}"
        if len(text) > width:
            text = f"{numeric:.6e}"
        if len(text) > width:
            text = text[:width]
        return text.rjust(width)

    @staticmethod
    def _format_csv(values: List) -> str:
        """Format values as comma-separated string."""
        formatted: List[str] = []
        for item in values:
            if item is None:
                formatted.append("")
            elif isinstance(item, bool):
                formatted.append("True" if item else "False")
            elif isinstance(item, (int, float)):
                formatted.append(str(item))
            else:
                formatted.append(str(item))
        return ",".join(formatted)

    @staticmethod
    def _format_scalar(value: Union[str, float, int, bool, None]) -> str:
        """
        Format scalar value for plan file.

        HEC-RAS plan files typically have a leading space before scalar values
        for alignment (e.g., "DLBreach SoilType= 3").

        Parameters
        ----------
        value : Union[str, float, int, bool, None]
            Value to format

        Returns
        -------
        str
            Formatted value with leading space for alignment
        """
        if value is None:
            return ""
        if isinstance(value, bool):
            return " True" if value else " False"
        if isinstance(value, (int, float)):
            return f" {value}"
        return f" {value}"

    @staticmethod
    def _ensure_key_in_order(block: "RasBreach.BreachBlock", key: str) -> None:
        """
        Ensure a key exists in the order list for serialization.

        When adding new parameters (like DLBreach) that don't exist in the
        original file, we need to add them to the order list so they get
        serialized in to_lines().

        Parameters
        ----------
        block : RasBreach.BreachBlock
            Breach block to modify
        key : str
            Key to add to order list if not present
        """
        # Check if key already exists in order
        for kind, existing_key in block.order:
            if kind == "line" and existing_key == key:
                return  # Already exists

        # Find insertion point - before trailing blanks
        insert_idx = len(block.order)
        for i in range(len(block.order) - 1, -1, -1):
            kind, _ = block.order[i]
            if kind == "blank":
                insert_idx = i
            else:
                break

        block.order.insert(insert_idx, ("line", key))

    @staticmethod
    def _create_backup(plan_path: Path) -> None:
        """Create timestamped backup of plan file."""
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = plan_path.parent / f"{plan_path.stem}_backup_{timestamp}{plan_path.suffix}"
        backup_path.write_text(plan_path.read_text())
        logger.info(f"Created backup: {backup_path.name}")

    @staticmethod
    def _validate_crlf(plan_path: Path) -> bool:
        """Validate that file has CRLF line endings."""
        content = plan_path.read_bytes()
        # Check if file contains \r\n (CRLF)
        return b'\r\n' in content
