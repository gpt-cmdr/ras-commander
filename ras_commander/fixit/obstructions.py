"""
Blocked obstruction data structures and algorithms.

This module provides the core algorithm for fixing overlapping blocked obstructions
in HEC-RAS geometry files using the elevation envelope approach.

Algorithm Overview:
    1. Collect all critical stations (start/end of each obstruction)
    2. For each segment between critical stations, find max elevation
    3. Merge adjacent segments with same elevation
    4. Insert 0.02-unit gaps where different elevations meet (HEC-RAS requirement)

The algorithm is hydraulically conservative - it uses maximum elevations to preserve
flow restrictions in overlap zones.
"""

from dataclasses import dataclass
from typing import List, Tuple


# Algorithm constants
GAP_SIZE = 0.02           # HEC-RAS adjacency gap requirement (must be >= 0.02)
FIELD_WIDTH = 8           # Fixed-width column size for HEC-RAS geometry files
VALUES_PER_LINE = 9       # 3 obstructions * 3 values per line
TOLERANCE = 1e-6          # Floating point comparison tolerance


@dataclass
class BlockedObstruction:
    """
    Represents a single blocked obstruction segment in a cross section.

    HEC-RAS blocked obstructions define areas where flow is completely blocked
    up to the specified elevation (e.g., buildings, walls, solid structures).

    Attributes:
        start_sta: Start station (left/upstream edge)
        end_sta: End station (right/downstream edge)
        elevation: Elevation up to which flow is blocked

    Note:
        The __post_init__ method automatically swaps start_sta and end_sta
        if they are inverted (ensures start_sta < end_sta).
    """
    start_sta: float
    end_sta: float
    elevation: float

    def __post_init__(self):
        """Auto-swap if stations are inverted."""
        if self.start_sta > self.end_sta:
            self.start_sta, self.end_sta = self.end_sta, self.start_sta

    @property
    def length(self) -> float:
        """Length of the obstruction segment."""
        return self.end_sta - self.start_sta

    def overlaps_with(self, other: 'BlockedObstruction') -> bool:
        """
        Check if this obstruction overlaps or is adjacent to another.

        HEC-RAS considers touching stations (e.g., end=100, start=100) to be
        an error condition, so we treat adjacency as overlap.

        Args:
            other: Another BlockedObstruction to compare against.

        Returns:
            True if obstructions overlap or touch, False otherwise.
        """
        return (
            self.start_sta <= other.end_sta + TOLERANCE and
            self.end_sta >= other.start_sta - TOLERANCE
        )

    def to_tuple(self) -> Tuple[float, float, float]:
        """
        Return as (start_sta, end_sta, elevation) tuple.

        Useful for serialization and comparison.
        """
        return (self.start_sta, self.end_sta, self.elevation)


def create_elevation_envelope(obstructions: List[BlockedObstruction]) -> List[BlockedObstruction]:
    """
    Create non-overlapping obstruction envelope using max elevation dominance.

    This is the core algorithm for fixing overlapping blocked obstructions.
    It preserves hydraulic behavior by using the maximum (most restrictive)
    elevation in any overlap zone.

    Algorithm:
        1. Collect all critical stations (start/end of each obstruction)
        2. For each segment between critical stations, find max elevation
           at the midpoint from all obstructions covering that segment
        3. Merge adjacent segments with identical elevations
        4. Insert 0.02-unit gaps where different elevations meet

    Args:
        obstructions: List of potentially overlapping obstructions.

    Returns:
        List of non-overlapping obstructions with HEC-RAS compliant gaps.

    Example:
        >>> original = [
        ...     BlockedObstruction(100, 120, 5.0),
        ...     BlockedObstruction(110, 130, 3.0)  # overlaps 110-120
        ... ]
        >>> fixed = create_elevation_envelope(original)
        >>> # Result: segments with max elevation at each point
        >>> # 100-120 @ 5.0 (higher), gap, 120.02-130 @ 3.0
    """
    if not obstructions:
        return []

    # Step 1: Collect all critical stations
    critical_stations = set()
    for obs in obstructions:
        critical_stations.add(obs.start_sta)
        critical_stations.add(obs.end_sta)

    sorted_stations = sorted(list(critical_stations))

    # Step 2: For each segment, find max elevation at midpoint
    segments = []
    for i in range(len(sorted_stations) - 1):
        start, end = sorted_stations[i], sorted_stations[i + 1]

        # Skip zero-length segments
        if abs(start - end) < TOLERANCE:
            continue

        midpoint = (start + end) / 2

        # Find maximum elevation from all obstructions covering this midpoint
        max_elev = -float('inf')
        for obs in obstructions:
            if obs.start_sta <= midpoint < obs.end_sta:
                if obs.elevation > max_elev:
                    max_elev = obs.elevation

        if max_elev > -float('inf'):
            segments.append({'start': start, 'end': end, 'elev': max_elev})

    if not segments:
        return []

    # Step 3 & 4: Merge same-elevation segments, insert gaps otherwise
    merged_obstructions = []
    current_obs_dict = segments[0]

    for next_obs_dict in segments[1:]:
        # Check if we can merge: same elevation and continuous
        if (abs(next_obs_dict['elev'] - current_obs_dict['elev']) < TOLERANCE and
                abs(next_obs_dict['start'] - current_obs_dict['end']) < TOLERANCE):
            # Merge: extend current segment
            current_obs_dict['end'] = next_obs_dict['end']
        else:
            # Finalize current obstruction
            merged_obstructions.append(BlockedObstruction(
                current_obs_dict['start'],
                current_obs_dict['end'],
                current_obs_dict['elev']
            ))

            # If adjacent (touching), add gap to prevent HEC-RAS error
            if abs(next_obs_dict['start'] - current_obs_dict['end']) < TOLERANCE:
                next_obs_dict['start'] += GAP_SIZE

            current_obs_dict = next_obs_dict

    # Add the final obstruction
    merged_obstructions.append(BlockedObstruction(
        current_obs_dict['start'],
        current_obs_dict['end'],
        current_obs_dict['elev']
    ))

    return merged_obstructions


def parse_obstructions(data_lines: List[str], expected_count: int) -> List[BlockedObstruction]:
    """
    Parse obstruction data from fixed-width 8-character columns.

    Deprecated compatibility wrapper. New code should use
    ``GeomCrossSection.parse_blocked_obstructions()``.

    Args:
        data_lines: Lines containing obstruction data (after header).
        expected_count: Expected number of obstructions from header.

    Returns:
        List of BlockedObstruction objects.

    Note:
        This compatibility wrapper follows the GeomCrossSection parser and
        returns at most the header-declared number of complete triplets.
    """
    from ..geom.GeomCrossSection import GeomCrossSection
    return GeomCrossSection.parse_blocked_obstructions(data_lines, expected_count)


def format_obstructions(obstructions: List[BlockedObstruction]) -> List[str]:
    """
    Format obstructions back to HEC-RAS fixed-width format.

    Deprecated compatibility wrapper. New code should use
    ``GeomCrossSection.format_blocked_obstructions()``.

    Args:
        obstructions: List of obstructions to format.

    Returns:
        List of formatted lines for HEC-RAS geometry file.

    Note:
        Values that exceed 8 characters are replaced with asterisks ('********')
        following FORTRAN overflow convention.
    """
    from ..geom.GeomCrossSection import GeomCrossSection
    return [
        line.rstrip("\n")
        for line in GeomCrossSection.format_blocked_obstructions(obstructions)
    ]


def _format_value(value: float, width: int) -> str:
    """
    Format a float into a fixed-width string.

    Handles overflow gracefully by returning asterisks, which is the
    standard for FORTRAN-style formats.

    Args:
        value: Float value to format.
        width: Target width in characters.

    Returns:
        Right-justified string of exactly 'width' characters.
    """
    # Format the number to a string with 2 decimal places
    s = f"{value:.2f}"

    # Check for overflow
    if len(s) > width:
        # Indicate overflow with asterisks
        return "*" * width

    # Right-justify the string with leading spaces to fill the width
    return s.rjust(width)


def has_overlaps(obstructions: List[BlockedObstruction]) -> bool:
    """
    Check if any obstructions in the list overlap or are adjacent.

    Args:
        obstructions: List of obstructions to check.

    Returns:
        True if any overlap or adjacency exists, False otherwise.
    """
    if len(obstructions) < 2:
        return False

    for i in range(len(obstructions)):
        for j in range(i + 1, len(obstructions)):
            if obstructions[i].overlaps_with(obstructions[j]):
                return True

    return False
