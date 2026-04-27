"""
Read-only index for plain-text HEC-RAS geometry records.

GeomParser remains responsible for fixed-width parsing. This module owns record
boundaries and selector lookup so geometry modules do not each rediscover the
same blocks independently.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Union, List

from ..Decorators import log_call
from .GeomParser import GeomParser


@dataclass(frozen=True)
class GeomRecord:
    """A located record block in a HEC-RAS geometry file."""

    kind: str
    start_idx: int
    end_idx: int
    marker_idx: Optional[int]
    river: Optional[str] = None
    reach: Optional[str] = None
    rs: Optional[str] = None
    name: Optional[str] = None
    type_code: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class GeomIndexData:
    """Index over geometry file lines and their discovered records."""

    geom_file: Optional[Path]
    lines: List[str]
    line_ending: str
    records: List[GeomRecord]


class GeomIndex:
    """Static namespace for geometry record indexing and lookup."""

    @staticmethod
    @log_call
    def build(geom_file: Union[str, Path]) -> GeomIndexData:
        """Build an index from a geometry file."""
        geom_path = Path(geom_file)
        text = geom_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        line_ending = "\r\n" if "\r\n" in text else "\n"
        return GeomIndex.from_lines(lines, geom_file=geom_path, line_ending=line_ending)

    @staticmethod
    @log_call
    def from_lines(
        lines: List[str],
        geom_file: Union[str, Path, None] = None,
        line_ending: Optional[str] = None,
    ) -> GeomIndexData:
        """Build an index from existing geometry file lines."""
        records: List[GeomRecord] = []
        current_river = None
        current_reach = None
        last_type_idx = None
        last_type_code = None
        last_rs = None

        for idx, line in enumerate(lines):
            if line.startswith("River Reach="):
                values = GeomParser.extract_comma_list(line, "River Reach")
                if len(values) >= 2:
                    current_river = values[0]
                    current_reach = values[1]
                continue

            if line.startswith("Type RM Length L Ch R ="):
                values = GeomIndex._type_rm_values(line)
                if len(values) > 1:
                    last_type_idx = idx
                    last_rs = values[1]
                    last_type_code = GeomIndex._safe_int(values[0])
                    records.append(
                        GeomRecord(
                            kind="cross_section",
                            start_idx=idx,
                            end_idx=GeomIndex._section_end(lines, idx),
                            marker_idx=idx,
                            river=current_river,
                            reach=current_reach,
                            rs=last_rs,
                            type_code=last_type_code,
                        )
                    )
                continue

            if line.startswith("Bridge Culvert-"):
                records.append(
                    GeomRecord(
                        kind="bridge_culvert",
                        start_idx=last_type_idx if last_type_idx is not None else idx,
                        end_idx=GeomIndex._section_end(lines, idx),
                        marker_idx=idx,
                        river=current_river,
                        reach=current_reach,
                        rs=last_rs,
                        type_code=last_type_code,
                    )
                )
                continue

            if line.startswith("IW Pilot Flow="):
                records.append(
                    GeomRecord(
                        kind="inline_weir",
                        start_idx=last_type_idx if last_type_idx is not None else idx,
                        end_idx=GeomIndex._section_end(lines, idx),
                        marker_idx=idx,
                        river=current_river,
                        reach=current_reach,
                        rs=last_rs,
                        type_code=last_type_code,
                    )
                )
                continue

            if line.startswith("Lat Struct="):
                values = GeomParser.extract_comma_list(line, "Lat Struct")
                records.append(
                    GeomRecord(
                        kind="lateral_structure",
                        start_idx=idx,
                        end_idx=GeomIndex._section_end(
                            lines,
                            idx,
                            peer_markers=("Lat Struct=", "River Reach="),
                        ),
                        marker_idx=idx,
                        river=current_river,
                        reach=current_reach,
                        name=values[0] if values else None,
                    )
                )
                continue

            if line.startswith("SA/2D Area Conn="):
                values = GeomParser.extract_comma_list(line, "SA/2D Area Conn")
                records.append(
                    GeomRecord(
                        kind="sa_2d_connection",
                        start_idx=idx,
                        end_idx=GeomIndex._section_end(
                            lines,
                            idx,
                            peer_markers=("SA/2D Area Conn=", "Storage Area=", "River Reach="),
                        ),
                        marker_idx=idx,
                        name=values[0] if values else None,
                    )
                )
                continue

            if line.startswith("Storage Area="):
                values = GeomParser.extract_comma_list(line, "Storage Area")
                records.append(
                    GeomRecord(
                        kind="storage_area",
                        start_idx=idx,
                        end_idx=GeomIndex._section_end(
                            lines,
                            idx,
                            peer_markers=("Storage Area=", "River Reach="),
                        ),
                        marker_idx=idx,
                        name=values[0] if values else None,
                    )
                )

        if line_ending is None:
            line_ending = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"

        return GeomIndexData(
            geom_file=Path(geom_file) if geom_file is not None else None,
            lines=lines,
            line_ending=line_ending,
            records=records,
        )

    @staticmethod
    @log_call
    def find(index: GeomIndexData, kind: str, **selectors) -> Optional[GeomRecord]:
        """Return the first record matching kind and selectors."""
        matches = GeomIndex.find_all(index, kind=kind, **selectors)
        return matches[0] if matches else None

    @staticmethod
    @log_call
    def find_all(index: GeomIndexData, kind: Optional[str] = None, **selectors) -> List[GeomRecord]:
        """Return all records matching kind and selectors."""
        records = index.records
        if kind is not None:
            records = [record for record in records if record.kind == kind]

        for key, expected in selectors.items():
            records = [
                record for record in records
                if GeomIndex._selector_matches(getattr(record, key), expected)
            ]

        return records

    @staticmethod
    @log_call
    def find_keyword(index: GeomIndexData, record: GeomRecord, keyword: str) -> Optional[int]:
        """Find a keyword line inside a record block."""
        for idx in range(record.start_idx, min(record.end_idx, len(index.lines))):
            line = index.lines[idx]
            if line.startswith(keyword) or line.startswith(f"{keyword}="):
                return idx
        return None

    @staticmethod
    @log_call
    def data_section(index: GeomIndexData, keyword_idx: int) -> tuple[int, int]:
        """Return the line range after a keyword until the next keyword-like line."""
        start_idx = keyword_idx + 1
        end_idx = start_idx
        while end_idx < len(index.lines):
            stripped = index.lines[end_idx].strip()
            if "=" in stripped and not stripped.startswith("-"):
                break
            end_idx += 1
        return start_idx, end_idx

    @staticmethod
    @log_call
    def record_at(
        index: GeomIndexData,
        kind: Optional[str] = None,
        start_idx: Optional[int] = None,
        marker_idx: Optional[int] = None,
    ) -> Optional[GeomRecord]:
        """Return a record at a known start or marker index."""
        for record in index.records:
            if kind is not None and record.kind != kind:
                continue
            if start_idx is not None and record.start_idx == start_idx:
                return record
            if marker_idx is not None and record.marker_idx == marker_idx:
                return record
        return None

    @staticmethod
    def _type_rm_values(line: str) -> List[str]:
        value_str = GeomParser.extract_keyword_value(line, "Type RM Length L Ch R")
        return [value.strip() for value in value_str.split(",")]

    @staticmethod
    def _section_end(
        lines: List[str],
        start_idx: int,
        peer_markers: tuple[str, ...] = ("Type RM Length L Ch R =", "River Reach="),
    ) -> int:
        for idx in range(start_idx + 1, len(lines)):
            if any(lines[idx].startswith(marker) for marker in peer_markers):
                return idx
        return len(lines)

    @staticmethod
    def _selector_matches(actual, expected) -> bool:
        if expected is None:
            return actual is None
        return str(actual) == str(expected)

    @staticmethod
    def _safe_int(value: str) -> Optional[int]:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None
