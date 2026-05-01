"""
RasFloodway - Authoring helpers for steady-flow floodway encroachments.

This module handles the plain-text HEC-RAS plan and steady-flow records needed
to configure Method 1-5 floodway encroachment trials without GUI steps.
"""

import math
import re
from collections import OrderedDict
from numbers import Number
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasPlan import RasPlan
from .RasPrj import ras

logger = get_logger(__name__)


class RasFloodway:
    """
    Static namespace for steady-flow floodway encroachment authoring.

    Encroachment records live in plan files as an ``Encroach Param`` header
    followed by river/reach/node records. Each node data line stores triplets of
    ``method, value_1, value_2`` for profiles 2..N.
    """

    ENCROACH_COLUMNS = [
        "river",
        "reach",
        "node",
        "profile_number",
        "profile_slot",
        "method",
        "value_1",
        "value_2",
        "left_station",
        "right_station",
        "target_surcharge",
        "energy_target",
        "encroach_param_1",
        "encroach_param_2",
        "encroach_param_3",
        "profile_count",
        "plan_path",
        "line_number",
    ]

    COUNTED_FLOW_KEYS = ("Known WS", "Friction Slope", "Flow")
    SECTION_START_PREFIXES = (
        "River Rch & RM=",
        "Boundary for River Rch & Prof#=",
        "Boundary for River Rch & RM=",
        "Initial Flow Split=",
        "DSS Import",
    )

    # ------------------------------------------------------------------
    # Public encroachment parsing and writing
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def parse_encroachments(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
    ) -> pd.DataFrame:
        """
        Parse floodway encroachment records from a HEC-RAS plan file.

        Parameters
        ----------
        plan_number_or_path : str, Number, or Path
            Plan number or explicit plan file path.
        ras_object : optional
            RAS project object. Required only when resolving a plan number.

        Returns
        -------
        pandas.DataFrame
            One row per node/profile encroachment triplet.
        """
        plan_path = RasFloodway._resolve_plan_path(plan_number_or_path, ras_object)
        lines = RasFloodway._read_lines(plan_path)

        encroach_param = [None, None, None, None]
        current_river = None
        current_reach = None
        records = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("Encroach Param="):
                encroach_param = RasFloodway._parse_encroach_param(stripped)
                continue
            if stripped.startswith("Encroach River="):
                current_river = stripped.split("=", 1)[1].strip()
                continue
            if stripped.startswith("Encroach Reach="):
                current_reach = stripped.split("=", 1)[1].strip()
                continue
            if not stripped.startswith("Encroach Node="):
                continue

            node = stripped.split("=", 1)[1].strip()
            value_line = lines[i + 1] if i + 1 < len(lines) else ""
            expected_slots = RasFloodway._expected_profile_slots(encroach_param)
            slots = RasFloodway._parse_node_slots(value_line, expected_slots)

            for slot_index, slot in enumerate(slots):
                method = slot[0]
                value_1 = slot[1]
                value_2 = slot[2]
                records.append({
                    "river": current_river,
                    "reach": current_reach,
                    "node": node,
                    "profile_number": slot_index + 2,
                    "profile_slot": slot_index + 1,
                    "method": method,
                    "value_1": value_1,
                    "value_2": value_2,
                    "left_station": value_1 if method == 1 else None,
                    "right_station": value_2 if method == 1 else None,
                    "target_surcharge": value_1 if method in (4, 5) else None,
                    "energy_target": value_2 if method == 5 else None,
                    "encroach_param_1": encroach_param[0],
                    "encroach_param_2": encroach_param[1],
                    "encroach_param_3": encroach_param[2],
                    "profile_count": encroach_param[3],
                    "plan_path": str(plan_path),
                    "line_number": i + 1,
                })

        if not records:
            return pd.DataFrame(columns=RasFloodway.ENCROACH_COLUMNS)
        return pd.DataFrame(records, columns=RasFloodway.ENCROACH_COLUMNS)

    @staticmethod
    @log_call
    def get_encroach_param(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
    ) -> Dict[str, Optional[float]]:
        """
        Read the ``Encroach Param`` header from a plan file.
        """
        plan_path = RasFloodway._resolve_plan_path(plan_number_or_path, ras_object)
        for line in RasFloodway._read_lines(plan_path):
            if line.strip().startswith("Encroach Param="):
                values = RasFloodway._parse_encroach_param(line)
                return {
                    "param_1": values[0],
                    "param_2": values[1],
                    "param_3": values[2],
                    "profile_count": values[3],
                }
        return {
            "param_1": None,
            "param_2": None,
            "param_3": None,
            "profile_count": None,
        }

    @staticmethod
    @log_call
    def set_encroachments(
        plan_number_or_path: Union[str, Number, Path],
        encroachments: Union[pd.DataFrame, Sequence[Dict[str, Any]]],
        encroach_param: Optional[Sequence[Any]] = None,
        profile_count: Optional[int] = None,
        ras_object=None,
    ) -> pd.DataFrame:
        """
        Write Method 1-5 encroachment records into a HEC-RAS plan file.

        ``encroachments`` may be a DataFrame with one row per node/profile or a
        sequence of dictionaries. Dictionary records can either be flat rows with
        ``method`` plus method values, or grouped node records with a ``profiles``
        list.
        """
        plan_path = RasFloodway._resolve_plan_path(plan_number_or_path, ras_object)
        normalised = RasFloodway._normalise_encroachment_records(encroachments)

        if not normalised:
            raise ValueError("encroachments must contain at least one record")

        profile_count = RasFloodway._resolve_profile_count(normalised, profile_count)
        param_values = RasFloodway._normalise_encroach_param(encroach_param, profile_count)
        block = RasFloodway._format_encroachment_block(
            normalised,
            profile_count=profile_count,
            encroach_param=param_values,
        )

        lines = RasFloodway._read_lines(plan_path)
        start, end = RasFloodway._find_encroachment_block(lines)
        if start is None:
            insert_at = RasFloodway._find_encroachment_insert_index(lines)
            lines = lines[:insert_at] + block + lines[insert_at:]
        else:
            lines = lines[:start] + block + lines[end:]

        RasFloodway._write_lines(plan_path, lines)
        RasFloodway._refresh_ras_object(ras_object)
        return RasFloodway.parse_encroachments(plan_path)

    # ------------------------------------------------------------------
    # Public trial profile helpers
    # ------------------------------------------------------------------

    @staticmethod
    @log_call
    def create_trial_profiles(
        plan_number_or_path: Union[str, Number, Path],
        method: int,
        targets: Sequence[Union[int, float]],
        flow_number_or_path: Optional[Union[str, Number, Path]] = None,
        base_profile: Union[int, str] = 1,
        profile_names: Optional[Sequence[str]] = None,
        locations: Optional[Sequence[Dict[str, Any]]] = None,
        encroachments: Optional[Sequence[Dict[str, Any]]] = None,
        starting_wse: Optional[Sequence[Union[int, float]]] = None,
        starting_wse_deltas: Optional[Sequence[Union[int, float]]] = None,
        energy_targets: Optional[Sequence[Union[int, float]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Create steady-flow floodway trial profiles and matching encroachments.

        Parameters
        ----------
        method : int
            Encroachment method, typically 4 or 5 for iterative trial setup.
        targets : sequence of numbers
            Target surcharge values written into encroachment triplets.
        base_profile : int or str
            1-based base profile number or existing profile name to duplicate.
        starting_wse : sequence, optional
            Absolute downstream starting WSE values for the new profiles.
        starting_wse_deltas : sequence, optional
            Deltas added to the base profile downstream known WSE.
        energy_targets : sequence, optional
            Method 5 secondary values.
        """
        if method not in {1, 2, 3, 4, 5}:
            raise ValueError("method must be between 1 and 5")
        targets = RasFloodway._as_number_list(targets, "targets")
        if not targets:
            raise ValueError("targets must contain at least one value")
        if starting_wse is not None and starting_wse_deltas is not None:
            raise ValueError("Use either starting_wse or starting_wse_deltas, not both")

        plan_path = RasFloodway._resolve_plan_path(plan_number_or_path, ras_object)
        flow_path = RasFloodway._resolve_flow_path(flow_number_or_path, plan_path, ras_object)

        flow_info = RasFloodway._expand_steady_flow_profiles(
            flow_path=flow_path,
            base_profile=base_profile,
            new_profile_names=profile_names,
            targets=targets,
            starting_wse=starting_wse,
            starting_wse_deltas=starting_wse_deltas,
        )

        target_profile_numbers = flow_info["new_profile_numbers"]
        locations = locations or encroachments
        if locations is None:
            locations = RasFloodway._infer_encroachment_locations(plan_path, flow_path)

        records = RasFloodway._build_trial_encroachments(
            locations=locations,
            method=method,
            targets=targets,
            target_profile_numbers=target_profile_numbers,
            energy_targets=energy_targets,
        )

        encroach_param = (-1, 0, 0, flow_info["new_profile_count"])
        parsed = RasFloodway.set_encroachments(
            plan_path,
            records,
            encroach_param=encroach_param,
            profile_count=flow_info["new_profile_count"],
            ras_object=ras_object,
        )

        trial_metadata = RasFloodway._format_trial_metadata(
            method=method,
            targets=targets,
            flow_path=flow_path,
            base_profile=base_profile,
            metadata=metadata,
        )
        RasFloodway._write_plan_description_after_encroachments(plan_path, trial_metadata)

        return {
            "plan_path": plan_path,
            "flow_path": flow_path,
            "method": method,
            "targets": targets,
            "profile_names": flow_info["profile_names"],
            "new_profile_names": flow_info["new_profile_names"],
            "new_profile_numbers": target_profile_numbers,
            "encroachments": parsed,
        }

    @staticmethod
    @log_call
    def create_method_4_trial_profiles(
        plan_number_or_path: Union[str, Number, Path],
        targets: Sequence[Union[int, float]],
        flow_number_or_path: Optional[Union[str, Number, Path]] = None,
        base_profile: Union[int, str] = 1,
        profile_names: Optional[Sequence[str]] = None,
        locations: Optional[Sequence[Dict[str, Any]]] = None,
        encroachments: Optional[Sequence[Dict[str, Any]]] = None,
        starting_wse: Optional[Sequence[Union[int, float]]] = None,
        starting_wse_deltas: Optional[Sequence[Union[int, float]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Create Method 4 target-surcharge floodway trial profiles.
        """
        return RasFloodway.create_trial_profiles(
            plan_number_or_path=plan_number_or_path,
            method=4,
            targets=targets,
            flow_number_or_path=flow_number_or_path,
            base_profile=base_profile,
            profile_names=profile_names,
            locations=locations,
            encroachments=encroachments,
            starting_wse=starting_wse,
            starting_wse_deltas=starting_wse_deltas,
            metadata=metadata,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def create_method_5_trial_profiles(
        plan_number_or_path: Union[str, Number, Path],
        targets: Sequence[Union[int, float]],
        flow_number_or_path: Optional[Union[str, Number, Path]] = None,
        base_profile: Union[int, str] = 1,
        profile_names: Optional[Sequence[str]] = None,
        locations: Optional[Sequence[Dict[str, Any]]] = None,
        encroachments: Optional[Sequence[Dict[str, Any]]] = None,
        starting_wse: Optional[Sequence[Union[int, float]]] = None,
        starting_wse_deltas: Optional[Sequence[Union[int, float]]] = None,
        energy_targets: Optional[Sequence[Union[int, float]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Create Method 5 floodway trial profiles with optional energy targets.
        """
        return RasFloodway.create_trial_profiles(
            plan_number_or_path=plan_number_or_path,
            method=5,
            targets=targets,
            flow_number_or_path=flow_number_or_path,
            base_profile=base_profile,
            profile_names=profile_names,
            locations=locations,
            encroachments=encroachments,
            starting_wse=starting_wse,
            starting_wse_deltas=starting_wse_deltas,
            energy_targets=energy_targets,
            metadata=metadata,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def check_floodways(
        plan_hdf,
        geom_hdf,
        base_profile,
        floodway_profile,
        surcharge: float = 1.0,
        thresholds=None,
        surcharge_limit: Optional[float] = None,
    ):
        """
        Delegate post-run floodway validation to ``RasCheck.check_floodways``.
        """
        from .check import RasCheck

        limit = surcharge if surcharge_limit is None else surcharge_limit
        return RasCheck.check_floodways(
            plan_hdf,
            geom_hdf,
            base_profile,
            floodway_profile,
            limit,
            thresholds,
        )

    check_floodway = check_floodways

    # ------------------------------------------------------------------
    # Encroachment parsing and writing internals
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_plan_path(
        plan_number_or_path: Union[str, Number, Path],
        ras_object=None,
    ) -> Path:
        if isinstance(plan_number_or_path, (str, Path)):
            path = Path(plan_number_or_path)
            if path.is_file():
                return path

        ras_obj = ras_object or ras
        plan_path = RasPlan.get_plan_path(plan_number_or_path, ras_obj)
        if plan_path is None or not Path(plan_path).exists():
            raise FileNotFoundError(f"Plan file not found: {plan_number_or_path}")
        return Path(plan_path)

    @staticmethod
    def _resolve_flow_path(
        flow_number_or_path: Optional[Union[str, Number, Path]],
        plan_path: Path,
        ras_object=None,
    ) -> Path:
        if flow_number_or_path is not None:
            if isinstance(flow_number_or_path, (str, Path)):
                explicit = Path(flow_number_or_path)
                if explicit.is_file():
                    return explicit
            ras_obj = ras_object or ras
            flow_path = RasPlan.get_flow_path(flow_number_or_path, ras_obj)
            if flow_path is None or not Path(flow_path).exists():
                raise FileNotFoundError(f"Steady flow file not found: {flow_number_or_path}")
            return Path(flow_path)

        for line in RasFloodway._read_lines(plan_path):
            if line.strip().startswith("Flow File=f"):
                flow_ref = line.split("=", 1)[1].strip()
                project_name = RasFloodway._project_name_from_plan_path(plan_path)
                candidate = plan_path.parent / f"{project_name}.{flow_ref}"
                if candidate.exists():
                    return candidate

        raise FileNotFoundError(f"Could not resolve steady flow file from plan: {plan_path}")

    @staticmethod
    def _project_name_from_plan_path(plan_path: Path) -> str:
        match = re.match(r"^(?P<project>.+)\.p\d\d$", plan_path.name, flags=re.IGNORECASE)
        if match:
            return match.group("project")
        return plan_path.stem

    @staticmethod
    def _read_lines(path: Path) -> List[str]:
        with open(path, "r", encoding="utf-8", errors="replace") as file:
            return file.readlines()

    @staticmethod
    def _write_lines(path: Path, lines: List[str]) -> None:
        with open(path, "w", encoding="utf-8") as file:
            file.writelines(lines)

    @staticmethod
    def _parse_encroach_param(line: str) -> List[Optional[float]]:
        raw = line.split("=", 1)[1] if "=" in line else ""
        values = RasFloodway._parse_value_tokens(raw.replace(",", " "))
        values = values[:4] + [None] * max(0, 4 - len(values))
        return values[:4]

    @staticmethod
    def _expected_profile_slots(encroach_param: Sequence[Optional[float]]) -> int:
        if len(encroach_param) >= 4 and encroach_param[3] is not None:
            return max(0, int(encroach_param[3]) - 1)
        return 0

    @staticmethod
    def _parse_node_slots(value_line: str, expected_slots: int = 0) -> List[List[Optional[float]]]:
        values = RasFloodway._parse_value_tokens(value_line)
        inferred_slots = math.ceil(len(values) / 3) if values else 0
        slot_count = max(expected_slots, inferred_slots)
        slots = []
        for slot_index in range(slot_count):
            start = slot_index * 3
            group = values[start:start + 3]
            group = group + [None] * max(0, 3 - len(group))
            method = int(group[0]) if group[0] is not None else None
            slots.append([method, group[1], group[2]])
        return slots

    @staticmethod
    def _parse_value_tokens(text: str) -> List[float]:
        tokens = []
        for token in re.split(r"[\s,]+", text.strip()):
            if not token:
                continue
            try:
                tokens.append(float(token))
            except ValueError:
                continue
        return tokens

    @staticmethod
    def _normalise_encroachment_records(
        encroachments: Union[pd.DataFrame, Sequence[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        if isinstance(encroachments, pd.DataFrame):
            entries = encroachments.to_dict("records")
        else:
            entries = list(encroachments)

        records = []
        order = 0
        for entry in entries:
            if "profiles" in entry:
                profiles = list(entry.get("profiles") or [])
                for idx, profile in enumerate(profiles):
                    merged = {key: entry.get(key) for key in ("river", "reach", "node", "station")}
                    merged.update(profile)
                    if "profile_number" not in merged and "profile_slot" not in merged:
                        merged["profile_number"] = idx + 2
                    records.append(RasFloodway._normalise_single_record(merged, order))
                    order += 1
                continue

            if "values" in entry and "method" not in entry:
                values = entry.get("values") or []
                for idx in range(0, len(values), 3):
                    group = values[idx:idx + 3]
                    profile = {
                        "river": entry.get("river"),
                        "reach": entry.get("reach"),
                        "node": entry.get("node", entry.get("station")),
                        "profile_number": (idx // 3) + 2,
                        "method": group[0] if len(group) > 0 else None,
                        "value_1": group[1] if len(group) > 1 else None,
                        "value_2": group[2] if len(group) > 2 else None,
                    }
                    records.append(RasFloodway._normalise_single_record(profile, order))
                    order += 1
                continue

            records.append(RasFloodway._normalise_single_record(entry, order))
            order += 1

        return records

    @staticmethod
    def _normalise_single_record(entry: Dict[str, Any], order: int) -> Dict[str, Any]:
        river = entry.get("river")
        reach = entry.get("reach")
        node = entry.get("node", entry.get("station"))
        if not river or not reach or node is None:
            raise ValueError("Each encroachment record requires river, reach, and node/station")

        method = entry.get("method")
        if method is None or (isinstance(method, float) and pd.isna(method)):
            raise ValueError(f"Encroachment record at {river}/{reach}/{node} requires method")
        method = int(method)
        if method not in {0, 1, 2, 3, 4, 5}:
            raise ValueError(f"Encroachment method must be 0-5, got {method}")

        profile_number = entry.get("profile_number")
        if profile_number is None or (isinstance(profile_number, float) and pd.isna(profile_number)):
            profile_slot = entry.get("profile_slot")
            profile_number = int(profile_slot) + 1 if profile_slot is not None else 2
        profile_number = int(profile_number)
        if profile_number < 2:
            raise ValueError("Encroachment profile_number must be 2 or greater")

        value_1, value_2 = RasFloodway._method_values(entry, method, river, reach, node)
        return {
            "river": str(river).strip(),
            "reach": str(reach).strip(),
            "node": str(node).strip(),
            "profile_number": profile_number,
            "profile_slot": profile_number - 1,
            "method": method,
            "value_1": value_1,
            "value_2": value_2,
            "_order": order,
        }

    @staticmethod
    def _method_values(
        entry: Dict[str, Any],
        method: int,
        river: Any,
        reach: Any,
        node: Any,
    ) -> Tuple[float, float]:
        value_1 = RasFloodway._first_present(
            entry,
            "value_1",
            "left_station",
            "target_surcharge",
            "target",
            "target_width",
        )
        value_2 = RasFloodway._first_present(
            entry,
            "value_2",
            "right_station",
            "energy_target",
            "target_energy",
        )

        label = f"{river}/{reach}/{node}"
        if method == 1:
            if value_1 is None or value_2 is None:
                raise ValueError(f"Method 1 encroachment at {label} requires left_station and right_station")
        elif method == 4:
            if value_1 is None:
                raise ValueError(f"Method 4 encroachment at {label} requires target_surcharge")
            if value_2 is None:
                value_2 = 0
        elif method == 5:
            if value_1 is None:
                raise ValueError(f"Method 5 encroachment at {label} requires target_surcharge")
            if value_2 is None:
                value_2 = 0
        elif method in {2, 3}:
            value_1 = 0 if value_1 is None else value_1
            value_2 = 0 if value_2 is None else value_2
        else:
            value_1 = 0 if value_1 is None else value_1
            value_2 = 0 if value_2 is None else value_2

        return float(value_1), float(value_2)

    @staticmethod
    def _first_present(entry: Dict[str, Any], *keys: str) -> Optional[Any]:
        for key in keys:
            value = entry.get(key)
            if value is not None and not (isinstance(value, float) and pd.isna(value)):
                return value
        return None

    @staticmethod
    def _resolve_profile_count(records: List[Dict[str, Any]], profile_count: Optional[int]) -> int:
        max_profile = max(record["profile_number"] for record in records)
        if profile_count is None:
            return max_profile
        profile_count = int(profile_count)
        if profile_count < max_profile:
            raise ValueError(
                f"profile_count {profile_count} is less than highest encroachment profile {max_profile}"
            )
        return profile_count

    @staticmethod
    def _normalise_encroach_param(
        encroach_param: Optional[Sequence[Any]],
        profile_count: int,
    ) -> Tuple[float, float, float, int]:
        if encroach_param is None:
            return -1, 0, 0, profile_count

        values = list(encroach_param)
        if len(values) == 4:
            values[3] = profile_count
        elif len(values) == 3:
            values.append(profile_count)
        else:
            raise ValueError("encroach_param must contain 3 or 4 values")
        return float(values[0]), float(values[1]), float(values[2]), int(values[3])

    @staticmethod
    def _format_encroachment_block(
        records: List[Dict[str, Any]],
        profile_count: int,
        encroach_param: Tuple[float, float, float, int],
    ) -> List[str]:
        grouped: "OrderedDict[Tuple[str, str], OrderedDict[str, List[Dict[str, Any]]]]" = OrderedDict()
        for record in sorted(records, key=lambda item: item["_order"]):
            river_reach = (record["river"], record["reach"])
            grouped.setdefault(river_reach, OrderedDict())
            grouped[river_reach].setdefault(record["node"], [])
            grouped[river_reach][record["node"]].append(record)

        lines = [
            "Encroach Param="
            f"{RasFloodway._format_compact_value(encroach_param[0])} ,"
            f"{RasFloodway._format_compact_value(encroach_param[1])},"
            f"{RasFloodway._format_compact_value(encroach_param[2])}, "
            f"{int(encroach_param[3])} \n"
        ]

        for (river, reach), nodes in grouped.items():
            lines.append(f"Encroach River={river}\n")
            lines.append(f"Encroach Reach={reach}\n")
            for node, node_records in nodes.items():
                lines.append(f"Encroach Node={node}\n")
                triplets = [[0, 0, 0] for _ in range(profile_count - 1)]
                for record in node_records:
                    slot_index = record["profile_number"] - 2
                    if slot_index < 0 or slot_index >= len(triplets):
                        raise ValueError(
                            f"Profile {record['profile_number']} is outside Encroach Param profile count {profile_count}"
                        )
                    triplets[slot_index] = [
                        record["method"],
                        record["value_1"],
                        record["value_2"],
                    ]

                flat = [value for triplet in triplets for value in triplet]
                lines.append(RasFloodway._format_fixed_values(flat) + "\n")

        return lines

    @staticmethod
    def _find_encroachment_block(lines: List[str]) -> Tuple[Optional[int], Optional[int]]:
        start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("Encroach Param="):
                start = i
                break
        if start is None:
            return None, None

        end = start + 1
        while end < len(lines):
            stripped = lines[end].strip()
            if not stripped:
                end += 1
                continue
            if stripped.startswith(("Encroach River=", "Encroach Reach=", "Encroach Node=")):
                end += 1
                continue
            if RasFloodway._looks_like_encroachment_value_line(lines[end]):
                end += 1
                continue
            break
        return start, end

    @staticmethod
    def _looks_like_encroachment_value_line(line: str) -> bool:
        values = RasFloodway._parse_value_tokens(line)
        if not values:
            return False
        return int(values[0]) in {0, 1, 2, 3, 4, 5}

    @staticmethod
    def _find_encroachment_insert_index(lines: List[str]) -> int:
        for i, line in enumerate(lines):
            if line.strip().startswith("CheckData="):
                return i + 1
        for i, line in enumerate(lines):
            if line.strip().startswith("Global Log Level="):
                return i + 1
        for i, line in enumerate(lines):
            if line.strip().startswith("Flow File="):
                return i + 1
        return len(lines)

    # ------------------------------------------------------------------
    # Trial profile internals
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_steady_flow_profiles(
        flow_path: Path,
        base_profile: Union[int, str],
        new_profile_names: Optional[Sequence[str]],
        targets: Sequence[float],
        starting_wse: Optional[Sequence[Union[int, float]]],
        starting_wse_deltas: Optional[Sequence[Union[int, float]]],
    ) -> Dict[str, Any]:
        lines = RasFloodway._read_lines(flow_path)
        old_count, old_names = RasFloodway._read_profile_header(lines)
        base_index = RasFloodway._resolve_base_profile_index(base_profile, old_names, old_count)

        if new_profile_names is None:
            new_profile_names = [f"FW {RasFloodway._format_compact_value(target)} ft" for target in targets]
        new_profile_names = list(new_profile_names)
        if len(new_profile_names) != len(targets):
            raise ValueError("profile_names length must match targets length")

        starting_wse_values = None
        if starting_wse is not None:
            starting_wse_values = RasFloodway._as_number_list(starting_wse, "starting_wse")
            if len(starting_wse_values) != len(targets):
                raise ValueError("starting_wse length must match targets length")
        starting_wse_delta_values = None
        if starting_wse_deltas is not None:
            starting_wse_delta_values = RasFloodway._as_number_list(
                starting_wse_deltas,
                "starting_wse_deltas",
            )
            if len(starting_wse_delta_values) != len(targets):
                raise ValueError("starting_wse_deltas length must match targets length")

        new_count = old_count + len(targets)
        all_names = old_names + new_profile_names
        new_lines = []
        next_profile_vector = False

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("Number of Profiles="):
                new_lines.append(f"Number of Profiles= {new_count} \n")
                i += 1
                continue

            if stripped.startswith("Profile Names="):
                new_lines.append(f"Profile Names={', '.join(all_names)}\n")
                i += 1
                continue

            if stripped.startswith("Boundary for River Rch & Prof#="):
                block, next_index = RasFloodway._collect_boundary_profile_block(lines, i)
                profile_number = RasFloodway._parse_boundary_profile_number(block[0])
                new_lines.extend(block)
                if profile_number == base_index + 1:
                    for offset in range(len(targets)):
                        new_profile_number = old_count + offset + 1
                        new_lines.extend(
                            RasFloodway._clone_boundary_block(
                                block,
                                new_profile_number,
                                offset,
                                starting_wse_values,
                                starting_wse_delta_values,
                            )
                        )
                i = next_index
                next_profile_vector = False
                continue

            counted_key = RasFloodway._counted_flow_key(stripped)
            if counted_key:
                new_lines.append(RasFloodway._replace_count(line, new_count))
                next_profile_vector = counted_key
                i += 1
                continue

            if next_profile_vector and RasFloodway._line_has_profile_values(line, old_count):
                values = RasFloodway._parse_value_tokens(line)
                additions = RasFloodway._profile_additions(
                    values,
                    base_index,
                    len(targets),
                    next_profile_vector,
                    starting_wse_values,
                    starting_wse_delta_values,
                )
                new_lines.append(RasFloodway._format_fixed_values(values + additions) + "\n")
                next_profile_vector = False
                i += 1
                continue

            new_lines.append(line)
            next_profile_vector = stripped.startswith(("River Rch & RM=", "Initial Flow Split="))
            i += 1

        RasFloodway._write_lines(flow_path, new_lines)
        return {
            "old_profile_count": old_count,
            "new_profile_count": new_count,
            "profile_names": all_names,
            "new_profile_names": new_profile_names,
            "new_profile_numbers": list(range(old_count + 1, new_count + 1)),
            "base_profile_number": base_index + 1,
        }

    @staticmethod
    def _read_profile_header(lines: List[str]) -> Tuple[int, List[str]]:
        count = None
        names = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("Number of Profiles="):
                values = RasFloodway._parse_value_tokens(stripped)
                if values:
                    count = int(values[0])
            elif stripped.startswith("Profile Names="):
                raw_names = stripped.split("=", 1)[1]
                names = [name.strip() for name in raw_names.split(",")]

        if count is None:
            raise ValueError("Steady flow file is missing Number of Profiles")
        if names is None:
            names = [f"Profile {i}" for i in range(1, count + 1)]
        if len(names) != count:
            raise ValueError("Profile Names count does not match Number of Profiles")
        return count, names

    @staticmethod
    def _resolve_base_profile_index(
        base_profile: Union[int, str],
        profile_names: Sequence[str],
        profile_count: int,
    ) -> int:
        if isinstance(base_profile, int):
            if base_profile < 1 or base_profile > profile_count:
                raise ValueError(f"base_profile {base_profile} is outside 1..{profile_count}")
            return base_profile - 1

        if isinstance(base_profile, str) and base_profile.isdigit():
            return RasFloodway._resolve_base_profile_index(int(base_profile), profile_names, profile_count)

        try:
            return list(profile_names).index(str(base_profile))
        except ValueError as exc:
            raise ValueError(f"base_profile name not found: {base_profile}") from exc

    @staticmethod
    def _counted_flow_key(stripped_line: str) -> Optional[str]:
        for key in RasFloodway.COUNTED_FLOW_KEYS:
            if stripped_line.startswith(f"{key}="):
                return key
        return None

    @staticmethod
    def _replace_count(line: str, new_count: int) -> str:
        key = line.split("=", 1)[0]
        return f"{key}= {new_count}\n"

    @staticmethod
    def _line_has_profile_values(line: str, expected_count: int) -> bool:
        return len(RasFloodway._parse_value_tokens(line)) == expected_count

    @staticmethod
    def _profile_additions(
        values: List[float],
        base_index: int,
        target_count: int,
        vector_kind: str,
        starting_wse: Optional[List[float]],
        starting_wse_deltas: Optional[List[float]],
    ) -> List[float]:
        base_value = values[base_index]
        if vector_kind == "Known WS":
            if starting_wse is not None:
                return list(starting_wse)
            if starting_wse_deltas is not None:
                return [base_value + delta for delta in starting_wse_deltas]
        return [base_value] * target_count

    @staticmethod
    def _collect_boundary_profile_block(lines: List[str], start_index: int) -> Tuple[List[str], int]:
        block = [lines[start_index]]
        i = start_index + 1
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith(RasFloodway.SECTION_START_PREFIXES):
                break
            block.append(lines[i])
            i += 1
        return block, i

    @staticmethod
    def _parse_boundary_profile_number(header_line: str) -> Optional[int]:
        match = re.search(r",\s*(\d+)\s*$", header_line.strip())
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _clone_boundary_block(
        block: List[str],
        new_profile_number: int,
        target_index: int,
        starting_wse: Optional[List[float]],
        starting_wse_deltas: Optional[List[float]],
    ) -> List[str]:
        cloned = list(block)
        cloned[0] = re.sub(r",\s*\d+\s*$", f", {new_profile_number} \n", cloned[0].rstrip("\n"))

        for i, line in enumerate(cloned):
            stripped = line.strip()
            if not stripped.startswith("Dn Known WS="):
                continue

            base_wse_values = RasFloodway._parse_value_tokens(stripped.split("=", 1)[1])
            if not base_wse_values:
                continue
            base_wse = base_wse_values[0]
            if starting_wse is not None:
                new_wse = starting_wse[target_index]
            elif starting_wse_deltas is not None:
                new_wse = base_wse + starting_wse_deltas[target_index]
            else:
                new_wse = base_wse
            cloned[i] = f"Dn Known WS={RasFloodway._format_compact_value(new_wse)}\n"

        return cloned

    @staticmethod
    def _infer_encroachment_locations(plan_path: Path, flow_path: Path) -> List[Dict[str, str]]:
        parsed = RasFloodway.parse_encroachments(plan_path)
        if not parsed.empty:
            unique = parsed[["river", "reach", "node"]].drop_duplicates()
            return unique.to_dict("records")

        locations = []
        seen = set()
        for line in RasFloodway._read_lines(flow_path):
            if not line.strip().startswith("River Rch & RM="):
                continue
            value = line.split("=", 1)[1].rstrip("\n")
            parts = value.split(",", 2)
            if len(parts) != 3:
                continue
            river, reach, node = [part.strip() for part in parts]
            key = (river, reach, node)
            if key in seen:
                continue
            seen.add(key)
            locations.append({"river": river, "reach": reach, "node": node})

        if not locations:
            raise ValueError("No encroachment locations supplied or inferred from flow file")
        return locations

    @staticmethod
    def _build_trial_encroachments(
        locations: Sequence[Dict[str, Any]],
        method: int,
        targets: Sequence[float],
        target_profile_numbers: Sequence[int],
        energy_targets: Optional[Sequence[Union[int, float]]],
    ) -> List[Dict[str, Any]]:
        energy_values = None
        if energy_targets is not None:
            energy_values = RasFloodway._as_number_list(energy_targets, "energy_targets")
            if len(energy_values) != len(targets):
                raise ValueError("energy_targets length must match targets length")

        records = []
        for location in locations:
            for i, target in enumerate(targets):
                record = {
                    "river": location.get("river"),
                    "reach": location.get("reach"),
                    "node": location.get("node", location.get("station")),
                    "profile_number": target_profile_numbers[i],
                    "method": method,
                    "target_surcharge": target,
                }
                if method == 5 and energy_values is not None:
                    record["energy_target"] = energy_values[i]
                records.append(record)
        return records

    @staticmethod
    def _format_trial_metadata(
        method: int,
        targets: Sequence[float],
        flow_path: Path,
        base_profile: Union[int, str],
        metadata: Optional[Dict[str, Any]],
    ) -> str:
        lines = [
            "Floodway Trial Metadata",
            f"method: {method}",
            "targets: " + ", ".join(RasFloodway._format_compact_value(target) for target in targets),
            f"flow_file: {flow_path.name}",
            f"base_profile: {base_profile}",
        ]
        for key, value in (metadata or {}).items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    @staticmethod
    def _write_plan_description_after_encroachments(plan_path: Path, description: str) -> None:
        lines = RasFloodway._read_lines(plan_path)
        desc_start = None
        desc_end = None
        for i, line in enumerate(lines):
            stripped = line.strip().upper()
            if stripped.startswith("BEGIN DESCRIPTION"):
                desc_start = i
            elif stripped.startswith("END DESCRIPTION"):
                desc_end = i
                break

        block = ["BEGIN DESCRIPTION:\n", description.rstrip() + "\n", "END DESCRIPTION:\n"]
        if desc_start is not None and desc_end is not None:
            new_lines = lines[:desc_start] + block + lines[desc_end + 1:]
        else:
            _, encroach_end = RasFloodway._find_encroachment_block(lines)
            insert_at = encroach_end if encroach_end is not None else RasFloodway._find_encroachment_insert_index(lines)
            new_lines = lines[:insert_at] + block + lines[insert_at:]

        RasFloodway._write_lines(plan_path, new_lines)

    # ------------------------------------------------------------------
    # Formatting and small utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _as_number_list(values: Sequence[Union[int, float]], name: str) -> List[float]:
        if values is None:
            return []
        result = []
        for value in values:
            try:
                result.append(float(value))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must contain numeric values") from exc
        return result

    @staticmethod
    def _format_fixed_values(values: Sequence[Any]) -> str:
        return "".join(f"{RasFloodway._format_compact_value(value):>8}" for value in values)

    @staticmethod
    def _format_compact_value(value: Any) -> str:
        if value is None:
            return ""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:g}"

    @staticmethod
    def _refresh_ras_object(ras_object=None) -> None:
        ras_obj = ras_object
        if ras_obj is None:
            return
        for attr, getter in (
            ("plan_df", "get_plan_entries"),
            ("flow_df", "get_flow_entries"),
            ("geom_df", "get_geom_entries"),
            ("unsteady_df", "get_unsteady_entries"),
        ):
            if hasattr(ras_obj, getter):
                try:
                    setattr(ras_obj, attr, getattr(ras_obj, getter)())
                except Exception:
                    logger.debug("Could not refresh %s on ras_object", attr, exc_info=True)
