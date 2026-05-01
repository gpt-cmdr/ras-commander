"""
RasSteady - Read and author HEC-RAS steady flow files (.f##).

All methods are static and are designed to be used without instantiation.
"""

from __future__ import annotations

import copy
import re
from collections import OrderedDict
from numbers import Number
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from .Decorators import log_call
from .LoggingConfig import get_logger


logger = get_logger(__name__)


class RasSteady:
    """
    Static API for HEC-RAS steady flow files.

    The writer emits the common HEC-RAS text structure used by .f## files:
    header, one ``River Rch & RM=`` flow-change block per station, one
    profile-specific ``Boundary for River Rch & Prof#=`` block per reach and
    profile, and optional DSS import metadata.
    """

    NO_BOUNDARY = 0
    NONE = 0
    KNOWN_WS = 1
    CRITICAL_DEPTH = 2
    NORMAL_DEPTH = 3
    RATING_CURVE = 4

    BOUNDARY_TYPE_NAMES = {
        NO_BOUNDARY: "None",
        KNOWN_WS: "Known WS",
        CRITICAL_DEPTH: "Critical Depth",
        NORMAL_DEPTH: "Normal Depth",
        RATING_CURVE: "Rating Curve",
    }

    _TYPE_ALIASES = {
        "": NO_BOUNDARY,
        "0": NO_BOUNDARY,
        "none": NO_BOUNDARY,
        "no_boundary": NO_BOUNDARY,
        "noboundary": NO_BOUNDARY,
        "blank": NO_BOUNDARY,
        "1": KNOWN_WS,
        "known_ws": KNOWN_WS,
        "knownws": KNOWN_WS,
        "known_water_surface": KNOWN_WS,
        "knownwatersurface": KNOWN_WS,
        "starting_ws": KNOWN_WS,
        "startingws": KNOWN_WS,
        "start_ws": KNOWN_WS,
        "startws": KNOWN_WS,
        "2": CRITICAL_DEPTH,
        "critical_depth": CRITICAL_DEPTH,
        "criticaldepth": CRITICAL_DEPTH,
        "critical": CRITICAL_DEPTH,
        "3": NORMAL_DEPTH,
        "normal_depth": NORMAL_DEPTH,
        "normaldepth": NORMAL_DEPTH,
        "friction_slope": NORMAL_DEPTH,
        "frictionslope": NORMAL_DEPTH,
        "slope": NORMAL_DEPTH,
        "4": RATING_CURVE,
        "rating_curve": RATING_CURVE,
        "ratingcurve": RATING_CURVE,
        "rating": RATING_CURVE,
    }

    DEFAULT_DSS_IMPORT = OrderedDict(
        [
            ("DSS Import StartDate", ""),
            ("DSS Import StartTime", ""),
            ("DSS Import EndDate", ""),
            ("DSS Import EndTime", ""),
            ("DSS Import GetInterval", " 0"),
            ("DSS Import Interval", ""),
            ("DSS Import GetPeak", " 0"),
            ("DSS Import FillOption", " 0"),
        ]
    )

    _NUMBER_RE = re.compile(
        r"[-+]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[Ee][-+]?\d+)?"
    )
    _KEY_PREFIXES = (
        "Flow Title=",
        "Program Version=",
        "Version=",
        "Number of Profiles=",
        "Profile Names=",
        "River Rch & RM=",
        "Flow Change Location=",
        "Flow=",
        "Boundary for River Rch & Prof#=",
        "Boundary for River Rch & RM=",
        "Boundary for Up Type=",
        "Up Type=",
        "Dn Type=",
        "Up Known WS=",
        "Dn Known WS=",
        "Known WS=",
        "Up Slope=",
        "Dn Slope=",
        "Friction Slope=",
        "Up Rating Curve=",
        "Dn Rating Curve=",
        "Rating Curve=",
        "Critical Depth=",
        "DSS Import ",
        "Begin DESCRIPTION",
        "End DESCRIPTION",
    )

    @staticmethod
    @log_call
    def read_flow_file(
        flow_file: Union[str, Number, Path],
        ras_object: Optional[Any] = None,
    ) -> dict[str, Any]:
        """
        Read a HEC-RAS steady flow file (.f##) into a structured dictionary.

        Args:
            flow_file: Direct path to a .f## file or, when a project is
                initialized, a steady flow number such as ``"01"``.
            ras_object: Optional RAS project object. If omitted, direct paths
                are used as-is and flow numbers are resolved through the global
                project object.

        Returns:
            Dictionary with ``flow_title``, ``program_version``,
            ``profile_names``, ``number_of_profiles``, ``flow_changes``,
            ``boundaries``, and ``dss_import``.
        """
        flow_path = RasSteady._resolve_flow_path(flow_file, ras_object)
        if not flow_path.exists():
            raise FileNotFoundError(f"Steady flow file not found: {flow_path}")

        lines = flow_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        data: dict[str, Any] = {
            "flow_title": "",
            "program_version": "",
            "number_of_profiles": 0,
            "profile_names": [],
            "flow_changes": [],
            "boundaries": [],
            "dss_import": OrderedDict(),
        }

        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()

            if line.startswith("Flow Title="):
                data["flow_title"] = line.split("=", 1)[1].strip()
                index += 1
                continue

            if line.startswith("Program Version="):
                data["program_version"] = line.split("=", 1)[1].strip()
                index += 1
                continue

            if line.startswith("Version="):
                data["program_version"] = line.split("=", 1)[1].strip()
                data["program_version_key"] = "Version"
                index += 1
                continue

            if line.startswith("Number of Profiles="):
                data["number_of_profiles"] = int(
                    RasSteady._first_number(line.split("=", 1)[1], default=0)
                )
                index += 1
                continue

            if line.startswith("Profile Names="):
                profile_text = line.split("=", 1)[1]
                data["profile_names"] = [
                    name.strip() for name in profile_text.split(",") if name.strip()
                ]
                index += 1
                continue

            if line.startswith("River Rch & RM="):
                flow_change, index = RasSteady._parse_flow_change(
                    lines, index, data
                )
                data["flow_changes"].append(flow_change)
                continue

            if line.startswith("Boundary for River Rch & Prof#="):
                boundary, index = RasSteady._parse_profile_boundary(lines, index)
                data["boundaries"].append(boundary)
                continue

            if line.startswith("Boundary for River Rch & RM="):
                boundaries, index = RasSteady._parse_legacy_boundary(lines, index)
                data["boundaries"].extend(boundaries)
                continue

            if line.startswith("DSS Import ") and "=" in line:
                key, value = line.split("=", 1)
                data["dss_import"][key] = value
                index += 1
                continue

            if stripped:
                data.setdefault("unparsed_lines", []).append(line)
            index += 1

        if not data["number_of_profiles"]:
            data["number_of_profiles"] = len(data["profile_names"])

        RasSteady.validate_flow_file_data(data)
        logger.info("Read steady flow file %s", flow_path)
        return data

    @staticmethod
    @log_call
    def write_flow_file(
        flow_file: Union[str, Number, Path],
        data: Mapping[str, Any],
        ras_object: Optional[Any] = None,
    ) -> Path:
        """
        Write a structured steady flow dictionary to a HEC-RAS .f## file.

        The input is validated before any file is written. Flow-value counts,
        profile names, and profile-specific boundary values must match the
        declared profile count.
        """
        normalized = RasSteady._normalized_data(data)
        RasSteady.validate_flow_file_data(normalized)

        flow_path = RasSteady._resolve_flow_path(flow_file, ras_object, for_write=True)
        flow_path.parent.mkdir(parents=True, exist_ok=True)

        profile_names = normalized["profile_names"]
        number_of_profiles = len(profile_names)
        lines: list[str] = [
            f"Flow Title={normalized.get('flow_title', '')}\n",
        ]

        program_version = normalized.get("program_version")
        if program_version:
            version_key = normalized.get("program_version_key", "Program Version")
            lines.append(f"{version_key}={program_version}\n")

        lines.extend(
            [
                f"Number of Profiles= {number_of_profiles}\n",
                f"Profile Names={','.join(profile_names)}\n",
            ]
        )

        for flow_change in normalized["flow_changes"]:
            station = flow_change.get("station", flow_change.get("river_station", ""))
            lines.append(
                "River Rch & RM="
                f"{flow_change.get('river', '')},{flow_change.get('reach', '')},{station}\n"
            )
            lines.extend(RasSteady._format_numeric_lines(flow_change["flows"]))

        for boundary in RasSteady._expand_boundaries(
            normalized.get("boundaries", []), number_of_profiles
        ):
            profile = int(boundary["profile"])
            lines.append(
                "Boundary for River Rch & Prof#="
                f"{boundary.get('river', '')},{boundary.get('reach', '')},{profile:2d}\n"
            )
            lines.extend(RasSteady._format_boundary_side("Up", boundary["upstream"]))
            lines.extend(RasSteady._format_boundary_side("Dn", boundary["downstream"]))

        dss_import = normalized.get("dss_import")
        if dss_import is None:
            dss_import = RasSteady.DEFAULT_DSS_IMPORT
        for key, value in dss_import.items():
            lines.append(f"{key}={value}\n")

        flow_path.write_text("".join(lines), encoding="utf-8")
        logger.info("Wrote steady flow file %s", flow_path)
        return flow_path

    @staticmethod
    @log_call
    def create_flow_file(
        flow_file: Union[str, Number, Path],
        flow_title: Optional[str] = None,
        profile_names: Optional[Sequence[str]] = None,
        flow_changes: Optional[Sequence[Mapping[str, Any]]] = None,
        boundaries: Optional[Sequence[Mapping[str, Any]]] = None,
        program_version: str = "6.60",
        dss_import: Optional[Mapping[str, Any]] = None,
        ras_object: Optional[Any] = None,
        **kwargs: Any,
    ) -> Path:
        """
        Create a new steady flow file from profile, flow, and boundary data.

        ``title=`` is accepted as an alias for ``flow_title=`` for notebook
        ergonomics.
        """
        if flow_title is None:
            flow_title = kwargs.pop("title", None)
        if profile_names is None:
            profile_names = kwargs.pop("profiles", None)
        if flow_changes is None:
            flow_changes = kwargs.pop("flows", None)
        if boundaries is None:
            boundaries = kwargs.pop("boundary_conditions", None)
        if "version" in kwargs:
            program_version = kwargs.pop("version")
        if kwargs:
            unknown = ", ".join(sorted(kwargs))
            raise TypeError(f"Unknown create_flow_file argument(s): {unknown}")

        data = {
            "flow_title": flow_title or "",
            "program_version": program_version,
            "profile_names": list(profile_names or []),
            "number_of_profiles": len(profile_names or []),
            "flow_changes": RasSteady._as_list(flow_changes),
            "boundaries": RasSteady._as_list(boundaries),
            "dss_import": (
                OrderedDict(dss_import)
                if dss_import is not None
                else copy.copy(RasSteady.DEFAULT_DSS_IMPORT)
            ),
        }
        return RasSteady.write_flow_file(flow_file, data, ras_object=ras_object)

    @staticmethod
    @log_call
    def update_flow_file(
        flow_file: Union[str, Number, Path],
        flow_title: Optional[str] = None,
        profile_names: Optional[Sequence[str]] = None,
        flow_changes: Optional[Sequence[Mapping[str, Any]]] = None,
        boundaries: Optional[Sequence[Mapping[str, Any]]] = None,
        program_version: Optional[str] = None,
        dss_import: Optional[Mapping[str, Any]] = None,
        ras_object: Optional[Any] = None,
    ) -> Path:
        """
        Update selected sections of an existing steady flow file in place.
        """
        data = RasSteady.read_flow_file(flow_file, ras_object=ras_object)
        if flow_title is not None:
            data["flow_title"] = flow_title
        if profile_names is not None:
            data["profile_names"] = list(profile_names)
            data["number_of_profiles"] = len(profile_names)
        if flow_changes is not None:
            data["flow_changes"] = RasSteady._as_list(flow_changes)
        if boundaries is not None:
            data["boundaries"] = RasSteady._as_list(boundaries)
        if program_version is not None:
            data["program_version"] = program_version
        if dss_import is not None:
            data["dss_import"] = OrderedDict(dss_import)

        return RasSteady.write_flow_file(flow_file, data, ras_object=ras_object)

    @staticmethod
    @log_call
    def validate_flow_file_data(data: Mapping[str, Any]) -> bool:
        """
        Validate steady flow data before writing.

        Raises:
            ValueError: If profile counts, flow counts, or boundary value
                counts are inconsistent.
        """
        profile_names = list(data.get("profile_names", []))
        declared_count = int(data.get("number_of_profiles") or len(profile_names))

        if declared_count <= 0:
            raise ValueError("Steady flow data must include at least one profile")

        if len(profile_names) != declared_count:
            raise ValueError(
                "Profile name count must match Number of Profiles "
                f"({len(profile_names)} != {declared_count})"
            )

        flow_changes = RasSteady._as_list(data.get("flow_changes", []))
        if not flow_changes:
            raise ValueError("Steady flow data must include at least one flow change")

        for index, flow_change in enumerate(flow_changes, start=1):
            if not isinstance(flow_change, Mapping):
                raise ValueError(f"Flow change {index} must be a mapping")
            flows = list(flow_change.get("flows", flow_change.get("values", [])))
            if len(flows) != declared_count:
                raise ValueError(
                    f"Flow change {index} value count must match profile count "
                    f"({len(flows)} != {declared_count})"
                )
            for key in ("river", "reach"):
                if not str(flow_change.get(key, "")).strip():
                    raise ValueError(f"Flow change {index} is missing {key!r}")
            if not str(
                flow_change.get("station", flow_change.get("river_station", ""))
            ).strip():
                raise ValueError(f"Flow change {index} is missing 'station'")

        RasSteady._expand_boundaries(data.get("boundaries", []), declared_count)
        return True

    @staticmethod
    @log_call
    def known_water_surface(values: Any) -> dict[str, Any]:
        """Return a known-water-surface boundary specification."""
        return {"type": RasSteady.KNOWN_WS, "known_ws": values}

    @staticmethod
    @log_call
    def normal_depth(slopes: Any) -> dict[str, Any]:
        """Return a normal-depth boundary specification."""
        return {"type": RasSteady.NORMAL_DEPTH, "slope": slopes}

    @staticmethod
    @log_call
    def critical_depth() -> dict[str, Any]:
        """Return a critical-depth boundary specification."""
        return {"type": RasSteady.CRITICAL_DEPTH}

    @staticmethod
    @log_call
    def rating_curve(points: Any) -> dict[str, Any]:
        """Return a rating-curve boundary specification."""
        return {"type": RasSteady.RATING_CURVE, "rating_curve": points}

    @staticmethod
    @log_call
    def boundary(
        river: str,
        reach: str,
        profile: Optional[int] = None,
        upstream: Optional[Any] = None,
        downstream: Optional[Any] = None,
    ) -> dict[str, Any]:
        """
        Build a steady boundary block.

        If ``profile`` is omitted, profile-specific lists in ``upstream`` or
        ``downstream`` are expanded into one boundary block per profile during
        writing.
        """
        result: dict[str, Any] = {
            "river": river,
            "reach": reach,
            "upstream": upstream or {"type": RasSteady.NO_BOUNDARY},
            "downstream": downstream or {"type": RasSteady.NO_BOUNDARY},
        }
        if profile is not None:
            result["profile"] = int(profile)
            result["profile_number"] = int(profile)
        return result

    @staticmethod
    def _normalized_data(data: Mapping[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(dict(data))
        if "flow_title" not in normalized and "title" in normalized:
            normalized["flow_title"] = normalized["title"]
        if "profile_names" not in normalized and "profiles" in normalized:
            normalized["profile_names"] = normalized["profiles"]
        if "flow_changes" not in normalized and "flows" in normalized:
            normalized["flow_changes"] = normalized["flows"]

        normalized["profile_names"] = list(normalized.get("profile_names", []))
        normalized["number_of_profiles"] = int(
            normalized.get("number_of_profiles") or len(normalized["profile_names"])
        )
        normalized["flow_changes"] = [
            RasSteady._normalize_flow_change(flow_change)
            for flow_change in RasSteady._as_list(normalized.get("flow_changes", []))
        ]
        normalized["boundaries"] = RasSteady._as_list(normalized.get("boundaries", []))
        if "dss_import" in normalized and normalized["dss_import"] is not None:
            normalized["dss_import"] = OrderedDict(normalized["dss_import"])
        return normalized

    @staticmethod
    def _normalize_flow_change(flow_change: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(flow_change)
        if "flows" not in result and "values" in result:
            result["flows"] = result["values"]
        result["flows"] = [float(value) for value in result.get("flows", [])]
        if "station" not in result and "river_station" in result:
            result["station"] = result["river_station"]
        if "river_station" not in result and "station" in result:
            result["river_station"] = result["station"]
        return result

    @staticmethod
    def _parse_flow_change(
        lines: Sequence[str], index: int, data: Mapping[str, Any]
    ) -> tuple[dict[str, Any], int]:
        river, reach, station = RasSteady._parse_location(
            lines[index].split("=", 1)[1], field_count=3
        )
        next_index = index + 1
        flow_change_locations: list[float] = []
        expected = int(data.get("number_of_profiles") or len(data.get("profile_names", [])))

        if next_index < len(lines) and lines[next_index].startswith(
            "Flow Change Location="
        ):
            count = int(
                RasSteady._first_number(lines[next_index].split("=", 1)[1], default=0)
            )
            flow_change_locations, next_index = RasSteady._parse_numeric_block(
                lines, next_index + 1, count
            )

        if next_index < len(lines) and lines[next_index].startswith("Flow="):
            count = int(
                RasSteady._first_number(lines[next_index].split("=", 1)[1], default=expected)
            )
            flows, next_index = RasSteady._parse_numeric_block(
                lines, next_index + 1, count
            )
        else:
            flows, next_index = RasSteady._parse_numeric_block(
                lines, next_index, expected
            )

        flow_change = {
            "river": river,
            "reach": reach,
            "station": station,
            "river_station": station,
            "flows": flows,
        }
        if flow_change_locations:
            flow_change["flow_change_locations"] = flow_change_locations
        return flow_change, next_index

    @staticmethod
    def _parse_profile_boundary(
        lines: Sequence[str], index: int
    ) -> tuple[dict[str, Any], int]:
        river, reach, profile_text = RasSteady._parse_location(
            lines[index].split("=", 1)[1], field_count=3
        )
        profile = int(RasSteady._first_number(profile_text, default=0))
        boundary = {
            "river": river,
            "reach": reach,
            "profile": profile,
            "profile_number": profile,
            "upstream": {"type": RasSteady.NO_BOUNDARY, "type_name": "None"},
            "downstream": {"type": RasSteady.NO_BOUNDARY, "type_name": "None"},
        }
        next_index = index + 1
        while next_index < len(lines):
            line = lines[next_index]
            if RasSteady._starts_new_block(line):
                break

            if line.startswith("Up Type="):
                boundary["upstream"]["type"] = RasSteady._normalize_boundary_type(
                    line.split("=", 1)[1]
                )
                boundary["upstream"]["type_name"] = RasSteady.BOUNDARY_TYPE_NAMES[
                    boundary["upstream"]["type"]
                ]
                next_index += 1
                continue

            if line.startswith("Dn Type="):
                boundary["downstream"]["type"] = RasSteady._normalize_boundary_type(
                    line.split("=", 1)[1]
                )
                boundary["downstream"]["type_name"] = RasSteady.BOUNDARY_TYPE_NAMES[
                    boundary["downstream"]["type"]
                ]
                next_index += 1
                continue

            parsed_side = RasSteady._parse_boundary_value_line(lines, next_index)
            if parsed_side:
                side_name, values, next_index = parsed_side
                boundary[side_name].update(values)
                continue

            next_index += 1

        return boundary, next_index

    @staticmethod
    def _parse_legacy_boundary(
        lines: Sequence[str], index: int
    ) -> tuple[list[dict[str, Any]], int]:
        river, reach, station = RasSteady._parse_location(
            lines[index].split("=", 1)[1], field_count=3
        )
        boundaries: list[dict[str, Any]] = []
        next_index = index + 1
        compact = {
            "river": river,
            "reach": reach,
            "station": station,
            "downstream": {"type": RasSteady.NO_BOUNDARY},
            "upstream": {"type": RasSteady.NO_BOUNDARY},
        }
        while next_index < len(lines):
            line = lines[next_index]
            if RasSteady._starts_new_block(line):
                break
            if line.startswith("Known WS="):
                count = int(RasSteady._first_number(line.split("=", 1)[1], default=0))
                values, next_index = RasSteady._parse_numeric_block(
                    lines, next_index + 1, count
                )
                compact["downstream"] = RasSteady.known_water_surface(values)
                continue
            if line.startswith("Friction Slope="):
                count = int(RasSteady._first_number(line.split("=", 1)[1], default=0))
                values, next_index = RasSteady._parse_numeric_block(
                    lines, next_index + 1, count
                )
                compact["downstream"] = RasSteady.normal_depth(values)
                continue
            if line.startswith("Critical Depth="):
                compact["downstream"] = RasSteady.critical_depth()
            next_index += 1
        boundaries.append(compact)
        return boundaries, next_index

    @staticmethod
    def _parse_boundary_value_line(
        lines: Sequence[str], index: int
    ) -> Optional[tuple[str, dict[str, Any], int]]:
        line = lines[index]
        side = None
        key = None
        if line.startswith("Up "):
            side = "upstream"
            key = line[3:].split("=", 1)[0]
        elif line.startswith("Dn "):
            side = "downstream"
            key = line[3:].split("=", 1)[0]
        if side is None or key is None or "=" not in line:
            return None

        rhs = line.split("=", 1)[1]
        if key in {"Known WS", "Starting WS", "Start WS"}:
            return side, {"known_ws": RasSteady._first_number(rhs)}, index + 1

        if key == "Slope":
            return side, {"slope": RasSteady._first_number(rhs)}, index + 1

        if key == "Rating Curve":
            count = int(RasSteady._first_number(rhs, default=0))
            values, next_index = RasSteady._parse_numeric_block(
                lines, index + 1, count * 2
            )
            if len(values) < count * 2 and count % 2 == 0:
                values, next_index = RasSteady._parse_numeric_block(
                    lines, index + 1, count
                )
            pairs = RasSteady._pair_values(values)
            return side, {"rating_curve": pairs}, next_index

        return None

    @staticmethod
    def _format_boundary_side(prefix: str, side: Mapping[str, Any]) -> list[str]:
        boundary_type = RasSteady._normalize_boundary_type(side.get("type"))
        lines = [f"{prefix} Type={boundary_type:2d}\n"]

        if boundary_type == RasSteady.KNOWN_WS:
            value = RasSteady._extract_side_value(side, "known_ws")
            lines.append(f"{prefix} Known WS={RasSteady._format_scalar(value)}\n")
        elif boundary_type == RasSteady.NORMAL_DEPTH:
            value = RasSteady._extract_side_value(side, "slope")
            lines.append(f"{prefix} Slope={RasSteady._format_scalar(value)}\n")
        elif boundary_type == RasSteady.RATING_CURVE:
            curve = RasSteady._normalize_rating_curve(
                RasSteady._extract_side_value(side, "rating_curve")
            )
            flat_values = [value for pair in curve for value in pair]
            lines.append(f"{prefix} Rating Curve= {len(curve)}\n")
            lines.extend(RasSteady._format_numeric_lines(flat_values))

        return lines

    @staticmethod
    def _expand_boundaries(
        boundaries: Any, number_of_profiles: int
    ) -> list[dict[str, Any]]:
        expanded: list[dict[str, Any]] = []
        for index, boundary in enumerate(RasSteady._as_list(boundaries), start=1):
            if not isinstance(boundary, Mapping):
                raise ValueError(f"Boundary {index} must be a mapping")
            river = str(boundary.get("river", "")).strip()
            reach = str(boundary.get("reach", "")).strip()
            if not river or not reach:
                raise ValueError(f"Boundary {index} must include river and reach")

            profile = boundary.get("profile", boundary.get("profile_number"))
            upstream = boundary.get("upstream", boundary.get("up", None))
            downstream = boundary.get("downstream", boundary.get("down", None))

            if profile is not None:
                profile_number = int(profile)
                RasSteady._validate_profile_number(profile_number, number_of_profiles)
                expanded.append(
                    {
                        "river": river,
                        "reach": reach,
                        "profile": profile_number,
                        "profile_number": profile_number,
                        "upstream": RasSteady._normalize_side_for_profile(
                            upstream, 0, number_of_profiles, compact=False
                        ),
                        "downstream": RasSteady._normalize_side_for_profile(
                            downstream, 0, number_of_profiles, compact=False
                        ),
                    }
                )
                continue

            for profile_index in range(number_of_profiles):
                profile_number = profile_index + 1
                expanded.append(
                    {
                        "river": river,
                        "reach": reach,
                        "profile": profile_number,
                        "profile_number": profile_number,
                        "upstream": RasSteady._normalize_side_for_profile(
                            upstream, profile_index, number_of_profiles, compact=True
                        ),
                        "downstream": RasSteady._normalize_side_for_profile(
                            downstream, profile_index, number_of_profiles, compact=True
                        ),
                    }
                )
        return expanded

    @staticmethod
    def _normalize_side_for_profile(
        side: Any,
        profile_index: int,
        number_of_profiles: int,
        compact: bool,
    ) -> dict[str, Any]:
        if side is None:
            result: dict[str, Any] = {"type": RasSteady.NO_BOUNDARY}
        elif isinstance(side, Mapping):
            result = dict(side)
        else:
            result = {"type": side}

        boundary_type = RasSteady._normalize_boundary_type(result.get("type"))
        result["type"] = boundary_type
        result["type_name"] = RasSteady.BOUNDARY_TYPE_NAMES[boundary_type]

        if boundary_type == RasSteady.KNOWN_WS:
            value = RasSteady._extract_side_value(result, "known_ws", required=True)
            result["known_ws"] = RasSteady._profile_value(
                value, profile_index, number_of_profiles, compact, "known_ws"
            )
        elif boundary_type == RasSteady.NORMAL_DEPTH:
            value = RasSteady._extract_side_value(result, "slope", required=True)
            result["slope"] = RasSteady._profile_value(
                value, profile_index, number_of_profiles, compact, "slope"
            )
        elif boundary_type == RasSteady.RATING_CURVE:
            value = RasSteady._extract_side_value(
                result, "rating_curve", required=True
            )
            result["rating_curve"] = RasSteady._profile_rating_curve(
                value, profile_index, number_of_profiles, compact
            )
        elif boundary_type == RasSteady.CRITICAL_DEPTH:
            pass
        elif boundary_type != RasSteady.NO_BOUNDARY:
            raise ValueError(f"Unsupported boundary type: {boundary_type}")

        return result

    @staticmethod
    def _profile_value(
        value: Any,
        profile_index: int,
        number_of_profiles: int,
        compact: bool,
        value_name: str,
    ) -> float:
        if compact and RasSteady._is_sequence(value):
            values = list(value)
            if len(values) != number_of_profiles:
                raise ValueError(
                    f"Boundary {value_name} count must match profile count "
                    f"({len(values)} != {number_of_profiles})"
                )
            return float(values[profile_index])
        return float(value)

    @staticmethod
    def _profile_rating_curve(
        value: Any, profile_index: int, number_of_profiles: int, compact: bool
    ) -> list[tuple[float, float]]:
        if compact and RasSteady._is_profile_curve_sequence(value):
            curves = list(value)
            if len(curves) != number_of_profiles:
                raise ValueError(
                    "Boundary rating_curve count must match profile count "
                    f"({len(curves)} != {number_of_profiles})"
                )
            return RasSteady._normalize_rating_curve(curves[profile_index])
        return RasSteady._normalize_rating_curve(value)

    @staticmethod
    def _extract_side_value(
        side: Mapping[str, Any], value_name: str, required: bool = False
    ) -> Any:
        aliases = {
            "known_ws": ("known_ws", "water_surface", "starting_ws", "start_ws", "value"),
            "slope": ("slope", "friction_slope", "energy_slope", "value"),
            "rating_curve": ("rating_curve", "curve", "points", "value"),
        }
        for alias in aliases[value_name]:
            if alias in side and side[alias] is not None:
                return side[alias]
        if required:
            boundary_type = RasSteady.BOUNDARY_TYPE_NAMES.get(
                RasSteady._normalize_boundary_type(side.get("type")), side.get("type")
            )
            raise ValueError(f"{boundary_type} boundary requires {value_name}")
        return None

    @staticmethod
    def _normalize_rating_curve(value: Any) -> list[tuple[float, float]]:
        if not RasSteady._is_sequence(value):
            raise ValueError("Rating Curve boundary requires a sequence of pairs")

        values = list(value)
        if not values:
            raise ValueError("Rating Curve boundary requires at least one point")

        if all(RasSteady._is_numeric(item) for item in values):
            if len(values) % 2:
                raise ValueError("Rating Curve numeric values must form pairs")
            return [
                (float(values[i]), float(values[i + 1]))
                for i in range(0, len(values), 2)
            ]

        pairs: list[tuple[float, float]] = []
        for point in values:
            if isinstance(point, Mapping):
                stage = point.get("stage", point.get("elevation", point.get("wse")))
                flow = point.get("flow", point.get("discharge", point.get("q")))
                if stage is None or flow is None:
                    raise ValueError(
                        "Rating Curve mapping points require stage/elevation and flow"
                    )
                pairs.append((float(stage), float(flow)))
                continue

            if not RasSteady._is_sequence(point) or len(point) != 2:
                raise ValueError("Rating Curve points must be pairs")
            pairs.append((float(point[0]), float(point[1])))

        return pairs

    @staticmethod
    def _normalize_boundary_type(value: Any) -> int:
        if value is None:
            return RasSteady.NO_BOUNDARY
        if isinstance(value, Number):
            code = int(value)
        else:
            key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
            key = key.replace("/", "_")
            if key not in RasSteady._TYPE_ALIASES:
                raise ValueError(f"Unknown steady boundary type: {value!r}")
            code = RasSteady._TYPE_ALIASES[key]
        if code not in RasSteady.BOUNDARY_TYPE_NAMES:
            raise ValueError(f"Unsupported steady boundary type code: {code}")
        return code

    @staticmethod
    def _validate_profile_number(profile: int, number_of_profiles: int) -> None:
        if profile < 1 or profile > number_of_profiles:
            raise ValueError(
                f"Boundary profile {profile} is outside profile count "
                f"1..{number_of_profiles}"
            )

    @staticmethod
    def _parse_location(value: str, field_count: int) -> list[str]:
        fields = [field.strip() for field in value.split(",")]
        if len(fields) < field_count:
            raise ValueError(f"Expected {field_count} location fields in {value!r}")
        if len(fields) > field_count:
            fields = fields[: field_count - 1] + [
                ",".join(fields[field_count - 1 :]).strip()
            ]
        return fields

    @staticmethod
    def _parse_numeric_block(
        lines: Sequence[str], start_index: int, expected_count: int
    ) -> tuple[list[float], int]:
        values: list[float] = []
        index = start_index
        while index < len(lines) and len(values) < expected_count:
            line = lines[index]
            if RasSteady._is_keyword_line(line):
                break
            values.extend(RasSteady._parse_numeric_line(line))
            index += 1
        return values[:expected_count], index

    @staticmethod
    def _parse_numeric_line(line: str) -> list[float]:
        values: list[float] = []
        raw = line.rstrip("\r\n")
        for position in range(0, len(raw), 8):
            field = raw[position : position + 8].strip()
            if not field:
                continue
            try:
                values.append(float(field))
            except ValueError:
                values.extend(float(match) for match in RasSteady._NUMBER_RE.findall(field))

        if values:
            return values
        return [float(match) for match in RasSteady._NUMBER_RE.findall(raw)]

    @staticmethod
    def _pair_values(values: Sequence[float]) -> list[tuple[float, float]]:
        if len(values) % 2:
            raise ValueError("Expected an even number of rating-curve values")
        return [(float(values[i]), float(values[i + 1])) for i in range(0, len(values), 2)]

    @staticmethod
    def _first_number(value: str, default: Optional[float] = None) -> float:
        match = RasSteady._NUMBER_RE.search(str(value))
        if match:
            return float(match.group(0))
        if default is not None:
            return float(default)
        raise ValueError(f"No numeric value found in {value!r}")

    @staticmethod
    def _format_numeric_lines(values: Sequence[Any]) -> list[str]:
        lines = []
        numeric_values = [float(value) for value in values]
        for start in range(0, len(numeric_values), 10):
            row = numeric_values[start : start + 10]
            lines.append("".join(RasSteady._format_scalar(value) for value in row) + "\n")
        return lines

    @staticmethod
    def _format_scalar(value: Any) -> str:
        numeric = float(value)
        text = f"{numeric:8g}"
        if len(text) > 8:
            text = f"{numeric:.7g}"
        return text.rjust(8)

    @staticmethod
    def _starts_new_block(line: str) -> bool:
        return line.startswith(
            (
                "Boundary for River Rch & Prof#=",
                "Boundary for River Rch & RM=",
                "River Rch & RM=",
                "DSS Import ",
            )
        )

    @staticmethod
    def _is_keyword_line(line: str) -> bool:
        stripped = line.lstrip()
        return any(stripped.startswith(prefix) for prefix in RasSteady._KEY_PREFIXES)

    @staticmethod
    def _is_sequence(value: Any) -> bool:
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes))

    @staticmethod
    def _is_numeric(value: Any) -> bool:
        return isinstance(value, Number)

    @staticmethod
    def _is_pair(value: Any) -> bool:
        return (
            RasSteady._is_sequence(value)
            and len(value) == 2
            and all(RasSteady._is_numeric(item) for item in value)
        )

    @staticmethod
    def _is_profile_curve_sequence(value: Any) -> bool:
        if not RasSteady._is_sequence(value):
            return False
        values = list(value)
        if not values:
            return False
        first = values[0]
        if isinstance(first, Mapping):
            return False
        if RasSteady._is_pair(first):
            return False
        return RasSteady._is_sequence(first)

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, Mapping):
            return [value]
        return list(value)

    @staticmethod
    def _resolve_flow_path(
        flow_file: Union[str, Number, Path],
        ras_object: Optional[Any] = None,
        for_write: bool = False,
    ) -> Path:
        candidate = Path(str(flow_file)) if isinstance(flow_file, Number) else Path(flow_file)
        if candidate.exists() or candidate.suffix or candidate.parent != Path("."):
            return candidate

        try:
            from .RasPlan import RasPlan

            resolved = RasPlan.get_flow_path(flow_file, ras_object=ras_object)
            if resolved:
                return Path(resolved)
        except Exception as exc:
            if not for_write:
                logger.debug("Could not resolve flow number %s: %s", flow_file, exc)

        return candidate


RasSteady.read = staticmethod(RasSteady.read_flow_file)
RasSteady.parse_flow_file = staticmethod(RasSteady.read_flow_file)
RasSteady.write = staticmethod(RasSteady.write_flow_file)
RasSteady.write_file = staticmethod(RasSteady.write_flow_file)
RasSteady.create = staticmethod(RasSteady.create_flow_file)
RasSteady.update = staticmethod(RasSteady.update_flow_file)
RasSteady.validate = staticmethod(RasSteady.validate_flow_file_data)
RasSteady.known_ws = staticmethod(RasSteady.known_water_surface)
