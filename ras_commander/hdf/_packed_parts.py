"""
Resolve packed HEC-RAS ``Info``/``Parts``/``Points`` feature offsets.

Native HEC-RAS Parts offsets are relative to the feature's own point slice
(``Info`` columns 0/1), and each part must fit inside that slice. Legacy
writers stored absolute (global) offsets; those are accepted only when the
whole feature, not an individual part, reconciles exactly with its point
slice. The offset convention is never guessed per part or from whether the
numbers happen to fit the global range.
"""
from operator import index
from typing import List, Tuple


def _nonnegative_index(value) -> int:
    """Validate a stored integer offset/count without truncating floats."""
    try:
        result = index(value)
    except TypeError as exc:
        raise ValueError("Packed feature offsets and counts must be integers") from exc
    if result < 0:
        raise ValueError("Packed feature offsets and counts must be nonnegative")
    return result


def resolve_feature_part_ranges(parts, point_start: int, point_count: int) -> List[Tuple[int, int]]:
    """Return feature-local ``(offset, count)`` ranges for one packed feature.

    Args:
        parts: The feature's ``Parts`` rows (``[start, count]`` pairs).
        point_start: The feature's ``Info`` point start in the shared Points array.
        point_count: The feature's ``Info`` point count.

    Returns:
        Feature-local ranges. Every range lies inside ``[0, point_count]``.

    Raises:
        ValueError: If a row is malformed, or the ranges are neither valid
            feature-local offsets nor a legacy global layout that exactly
            covers the feature's point slice.
    """
    point_start = _nonnegative_index(point_start)
    point_count = _nonnegative_index(point_count)
    ranges = []
    for row in parts:
        if len(row) != 2:
            raise ValueError("Packed feature parts require [start, count] rows")
        start, count = _nonnegative_index(row[0]), _nonnegative_index(row[1])
        ranges.append((start, count))

    # Native contract: offsets are local and bounded by the feature point count.
    if all(start + count <= point_count for start, count in ranges):
        return ranges

    # Legacy global offsets: the complete feature must be covered without gaps
    # or overlaps. Such a layout can never also satisfy the local bound when
    # point_start > 0, so the two conventions cannot both match.
    shifted = sorted((start - point_start, count) for start, count in ranges)
    expected = 0
    for start, count in shifted:
        if start != expected:
            break
        expected += count
    else:
        if ranges and expected == point_count:
            return [(start - point_start, count) for start, count in ranges]
    raise ValueError("Packed feature parts exceed the feature point range")
