# XS Check Implementation Plan

## Overview

The XS Check validates cross section data including reach lengths, ineffective flow areas, blocked obstructions, levees, boundary conditions, and flow regime consistency. This is the most comprehensive check module in cHECk-RAS.

## Module Location

```
ras_commander/check/xs_check.py
```

## Data Sources

### From Plan HDF (`.p##.hdf`)

| HDF Path | Data | Description |
|----------|------|-------------|
| `Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/` | Results per XS | WSE, Q, velocity, etc. |
| `Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names` | Profile names | Available profiles |
| `Results/Steady/Geometry Info/Cross Section/` | XS attributes | River, Reach, Station |

### From Geometry HDF (`.g##.hdf`)

| HDF Path | Data | Description |
|----------|------|-------------|
| `Geometry/Cross Sections/Attributes` | XS identifiers | River, Reach, RS |
| `Geometry/Cross Sections/Reach Lengths` | Reach lengths | LOB, Channel, ROB distances |
| `Geometry/Cross Sections/Bank Stations` | Bank positions | Left and right bank stations |
| `Geometry/Cross Sections/Ineffective Flow Areas/` | Ineffective areas | Stations, elevations |
| `Geometry/Cross Sections/Blocked Obstructions/` | Blocked obs | Stations, elevations |
| `Geometry/Cross Sections/Levees/` | Levee data | Stations, elevations |
| `Geometry/Cross Sections/Station Elevation Info/` | Ground profile | Station-elevation pairs |
| `Geometry/Structures/` | Structure info | Bridge/culvert sections |

## Validation Rules

### 1. Reach Length Checks (XS DT)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| XS_DT_01 | LOB - CHL > 25 AND ROB - CHL > 25 | WARNING | Overbank reach lengths significantly exceed channel reach length |
| XS_DT_02L | LOB / CHL > 2.0 | WARNING | Left overbank reach length is more than 2x channel reach length |
| XS_DT_02R | ROB / CHL > 2.0 | WARNING | Right overbank reach length is more than 2x channel reach length |

### 2. Ineffective Flow Area Checks (XS IF)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| XS_IF_01L | WSE > ground elev at ineffective AND WSE <= ineffective elev (Left) | WARNING | Left ineffective flow area is active but ground is below WSE for {profile} |
| XS_IF_01R | WSE > ground elev at ineffective AND WSE <= ineffective elev (Right) | WARNING | Right ineffective flow area is active but ground is below WSE for {profile} |
| XS_IF_02L | Multiple ineffective areas on left overbank | INFO | Multiple ineffective flow areas defined on left overbank |
| XS_IF_02R | Multiple ineffective areas on right overbank | INFO | Multiple ineffective flow areas defined on right overbank |
| XS_IF_03L | Ineffective station extends past left bank station | WARNING | Left ineffective station {ineff_sta} is beyond left bank station {bank_sta} |
| XS_IF_03R | Ineffective station extends past right bank station | WARNING | Right ineffective station {ineff_sta} is beyond right bank station {bank_sta} |

### 3. Default Flow Area Checks (XS DF)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| XS_DF_01L | Default ineffective matches WSE pattern (Left) | WARNING | Left overbank may be using default ineffective flow area for {profile} |
| XS_DF_01R | Default ineffective matches WSE pattern (Right) | WARNING | Right overbank may be using default ineffective flow area for {profile} |

### 4. Blocked Obstruction Checks (XS BO)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| XS_BO_01L | Single blocked obstruction at ground start (Left) | WARNING | Left blocked obstruction starts at left ground point |
| XS_BO_01R | Single blocked obstruction at ground start (Right) | WARNING | Right blocked obstruction starts at right ground point |
| XS_BO_02L | Multiple blocked obstructions not covered by ineffective (Left) | WARNING | Multiple left blocked obstructions may need ineffective flow areas |
| XS_BO_02R | Multiple blocked obstructions not covered by ineffective (Right) | WARNING | Multiple right blocked obstructions may need ineffective flow areas |

### 5. Encroachment/Exceedance Checks (XS EC)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| XS_EC_01L | WSE > left ground elevation AND effective = ground start | WARNING | WSE exceeds left ground elevation at effective station for {profile} |
| XS_EC_01R | WSE > right ground elevation AND effective = ground end | WARNING | WSE exceeds right ground elevation at effective station for {profile} |
| XS_EC_01BUL | Bridge upstream: WSE exceeds left ground | WARNING | Bridge upstream section: WSE exceeds left ground elevation for {profile} |
| XS_EC_01BUR | Bridge upstream: WSE exceeds right ground | WARNING | Bridge upstream section: WSE exceeds right ground elevation for {profile} |
| XS_EC_01BDL | Bridge downstream: WSE exceeds left ground | WARNING | Bridge downstream section: WSE exceeds left ground elevation for {profile} |
| XS_EC_01BDR | Bridge downstream: WSE exceeds right ground | WARNING | Bridge downstream section: WSE exceeds right ground elevation for {profile} |

### 6. Critical Depth Checks (XS CD)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| XS_CD_01 | WSE = Critical WSE AND ineffective elev >= WSE | WARNING | Critical depth at XS with permanent ineffective flow for {profile} |
| XS_CD_02 | Critical depth AND channel n < 0.025 | WARNING | Critical depth with low channel Manning's n for {profile} |

### 7. Friction Slope Method Check (XS FS)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| XS_FS_01 | Channel reach length > 500 AND friction slope method != Average Conveyance | INFO | Long reach lengths may benefit from Average Conveyance friction slope method |

### 8. Levee Checks (XS LV)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| XS_LV_04L | Left levee elevation < WSE | WARNING | Left levee overtopped for {profile}: WSE={wse}, levee elev={lev_elev} |
| XS_LV_04R | Right levee elevation < WSE | WARNING | Right levee overtopped for {profile}: WSE={wse}, levee elev={lev_elev} |
| XS_LV_05L | Left levee ground elev < WSE but levee not overtopped | INFO | Left levee may be ineffective: ground below WSE for {profile_min} but above for {profile_max} |
| XS_LV_05R | Right levee ground elev < WSE but levee not overtopped | INFO | Right levee may be ineffective: ground below WSE for {profile_min} but above for {profile_max} |

### 9. GIS Data Checks (XS GD)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| XS_GD_01 | LID option set but not at structure section | INFO | GIS cut line data may need review |

## Implementation

```python
"""
XS Check - Cross Section Validation

This module validates cross section data including reach lengths,
ineffective flow areas, blocked obstructions, levees, and boundary conditions.
"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import pandas as pd
import numpy as np
import h5py

from ..RasCheck import CheckResults, CheckMessage, Severity
from .messages import get_message_template
from .thresholds import (
    REACH_LENGTH_DIFF_THRESHOLD,
    REACH_LENGTH_RATIO_THRESHOLD,
    LONG_REACH_LENGTH
)
from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


@dataclass
class CrossSectionData:
    """Container for cross section data."""
    river: str
    reach: str
    station: float
    structure: str = ""
    section_num: int = -99  # -99 = regular XS, 1-4 = structure sections

    # Geometry
    len_lob: float = -9999
    len_chl: float = -9999
    len_rob: float = -9999
    bank_sta_l: float = -9999
    bank_sta_r: float = -9999

    # Ground data
    ground_sta_first: float = -9999
    ground_elev_first: float = -9999
    ground_sta_last: float = -9999
    ground_elev_last: float = -9999

    # Ineffective flow
    ineff_sta_l: float = -9999
    ineff_elev_l: float = -9999
    ineff_sta_r: float = -9999
    ineff_elev_r: float = -9999
    ineff_count_l: int = 0
    ineff_count_r: int = 0
    ineff_ground_l: float = -9999  # Ground elev at ineffective station
    ineff_ground_r: float = -9999

    # Levees
    levee_sta_l: float = -9999
    levee_elev_l: float = -9999
    levee_sta_r: float = -9999
    levee_elev_r: float = -9999
    levee_ground_l: float = -9999
    levee_ground_r: float = -9999


@dataclass
class CrossSectionResults:
    """Container for cross section results per profile."""
    river: str
    reach: str
    station: float
    structure: str
    profile: str

    wse: float = -9999
    crit_wse: float = -9999
    q_total: float = -9999
    q_lob: float = -9999
    q_chl: float = -9999
    q_rob: float = -9999
    vel_head: float = -9999
    top_width: float = -9999
    eff_sta_l: float = -9999
    eff_sta_r: float = -9999
    eg_slope: float = -9999
    conv_ratio: float = -9999


@log_call
def run_xs_check(
    plan_hdf: Path,
    geom_hdf: Path,
    profiles: List[str]
) -> CheckResults:
    """
    Run all cross section validation checks.

    Args:
        plan_hdf: Path to plan HDF file
        geom_hdf: Path to geometry HDF file
        profiles: List of profile names to check

    Returns:
        CheckResults containing XS check messages and summary
    """
    results = CheckResults()
    messages = []

    # Extract geometry data
    xs_geom = extract_xs_geometry(geom_hdf)
    if not xs_geom:
        logger.warning("No cross section geometry data found")
        return results

    # Extract results for each profile
    xs_results = extract_xs_results(plan_hdf, profiles)

    # Extract additional geometry data
    blocked_obs = extract_blocked_obstructions(geom_hdf)
    levee_data = extract_levee_data(geom_hdf)
    structure_sections = extract_structure_sections(geom_hdf)

    # Get lowest frequency profile for base checks
    lowest_freq_profile = profiles[0] if profiles else None

    # Run validation checks
    messages.extend(check_reach_lengths(xs_geom))
    messages.extend(check_ineffective_flow(xs_geom, xs_results, profiles))
    messages.extend(check_blocked_obstructions(xs_geom, xs_results, blocked_obs))
    messages.extend(check_ground_exceedance(xs_geom, xs_results, profiles))
    messages.extend(check_critical_depth(xs_geom, xs_results, profiles))
    messages.extend(check_levees(xs_geom, xs_results, levee_data, profiles))
    messages.extend(check_friction_slope_method(plan_hdf, xs_geom))

    # Build summary DataFrame
    results.xs_summary = build_xs_summary(xs_geom, xs_results, lowest_freq_profile)
    results.messages = messages

    return results


def extract_xs_geometry(geom_hdf: Path) -> List[CrossSectionData]:
    """Extract cross section geometry from HDF file."""
    xs_list = []

    try:
        with h5py.File(geom_hdf, 'r') as hdf:
            # Get cross section attributes
            attrs_path = 'Geometry/Cross Sections/Attributes'
            if attrs_path not in hdf:
                return xs_list

            attrs = hdf[attrs_path][:]

            # Get reach lengths
            reach_lengths = _get_reach_lengths(hdf)

            # Get bank stations
            bank_stations = _get_bank_stations(hdf)

            # Get ground data
            ground_data = _get_ground_data(hdf)

            # Get ineffective flow data
            ineff_data = _get_ineffective_data(hdf)

            # Build cross section list
            for i, attr in enumerate(attrs):
                xs = CrossSectionData(
                    river=_decode_bytes(attr['River']),
                    reach=_decode_bytes(attr['Reach']),
                    station=float(attr['RS'])
                )

                # Add reach lengths
                if i in reach_lengths:
                    xs.len_lob, xs.len_chl, xs.len_rob = reach_lengths[i]

                # Add bank stations
                if i in bank_stations:
                    xs.bank_sta_l, xs.bank_sta_r = bank_stations[i]

                # Add ground data
                if i in ground_data:
                    gd = ground_data[i]
                    xs.ground_sta_first = gd['sta_first']
                    xs.ground_elev_first = gd['elev_first']
                    xs.ground_sta_last = gd['sta_last']
                    xs.ground_elev_last = gd['elev_last']

                # Add ineffective data
                if i in ineff_data:
                    ind = ineff_data[i]
                    xs.ineff_sta_l = ind.get('sta_l', -9999)
                    xs.ineff_elev_l = ind.get('elev_l', -9999)
                    xs.ineff_sta_r = ind.get('sta_r', -9999)
                    xs.ineff_elev_r = ind.get('elev_r', -9999)
                    xs.ineff_count_l = ind.get('count_l', 0)
                    xs.ineff_count_r = ind.get('count_r', 0)
                    xs.ineff_ground_l = ind.get('ground_l', -9999)
                    xs.ineff_ground_r = ind.get('ground_r', -9999)

                xs_list.append(xs)

    except Exception as e:
        logger.error(f"Error extracting XS geometry: {e}")

    return xs_list


def _get_reach_lengths(hdf: h5py.File) -> Dict[int, Tuple[float, float, float]]:
    """Extract reach lengths indexed by XS index."""
    lengths = {}
    path = 'Geometry/Cross Sections/Reach Lengths'

    if path in hdf:
        data = hdf[path][:]
        for i, row in enumerate(data):
            if len(row) >= 3:
                lengths[i] = (float(row[0]), float(row[1]), float(row[2]))

    return lengths


def _get_bank_stations(hdf: h5py.File) -> Dict[int, Tuple[float, float]]:
    """Extract bank stations indexed by XS index."""
    banks = {}
    path = 'Geometry/Cross Sections/Bank Stations'

    if path in hdf:
        data = hdf[path][:]
        for i, row in enumerate(data):
            if len(row) >= 2:
                banks[i] = (float(row[0]), float(row[1]))

    return banks


def _get_ground_data(hdf: h5py.File) -> Dict[int, Dict]:
    """Extract first/last ground points indexed by XS index."""
    ground = {}

    # Get counts and values
    counts_path = 'Geometry/Cross Sections/Station Elevation Info/Counts'
    values_path = 'Geometry/Cross Sections/Station Elevation Info/Values'

    if counts_path in hdf and values_path in hdf:
        counts = hdf[counts_path][:]
        values = hdf[values_path][:]

        offset = 0
        for i, count in enumerate(counts):
            if count > 0:
                # Get first point
                sta_first = float(values[offset][0])
                elev_first = float(values[offset][1])

                # Get last point
                last_idx = offset + count - 1
                sta_last = float(values[last_idx][0])
                elev_last = float(values[last_idx][1])

                ground[i] = {
                    'sta_first': sta_first,
                    'elev_first': elev_first,
                    'sta_last': sta_last,
                    'elev_last': elev_last
                }

            offset += count

    return ground


def _get_ineffective_data(hdf: h5py.File) -> Dict[int, Dict]:
    """Extract ineffective flow area data indexed by XS index."""
    ineff = {}

    # Try different possible paths
    counts_path = 'Geometry/Cross Sections/Ineffective Flow Areas/Counts'
    values_path = 'Geometry/Cross Sections/Ineffective Flow Areas/Values'

    if counts_path in hdf and values_path in hdf:
        counts = hdf[counts_path][:]
        values = hdf[values_path][:]

        offset = 0
        for i, count in enumerate(counts):
            if count > 0:
                ineff_areas = values[offset:offset + count]

                # Separate left and right based on position relative to channel
                # This is simplified - actual implementation needs bank station reference
                left_areas = []
                right_areas = []

                for area in ineff_areas:
                    # area typically: [sta_start, sta_end, elevation, permanent_flag]
                    left_areas.append(area)  # Simplified

                ineff[i] = {
                    'sta_l': float(ineff_areas[0][0]) if len(ineff_areas) > 0 else -9999,
                    'elev_l': float(ineff_areas[0][2]) if len(ineff_areas) > 0 else -9999,
                    'sta_r': float(ineff_areas[-1][1]) if len(ineff_areas) > 0 else -9999,
                    'elev_r': float(ineff_areas[-1][2]) if len(ineff_areas) > 0 else -9999,
                    'count_l': len(left_areas),
                    'count_r': len(right_areas)
                }

            offset += count

    return ineff


def extract_xs_results(
    plan_hdf: Path,
    profiles: List[str]
) -> Dict[str, List[CrossSectionResults]]:
    """
    Extract cross section results for each profile.

    Returns:
        Dict mapping profile name to list of results
    """
    results = {}

    try:
        with h5py.File(plan_hdf, 'r') as hdf:
            base_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles'

            for profile in profiles:
                profile_results = []

                # Get WSE data
                wse_path = f'{base_path}/Cross Sections/Water Surface'
                if wse_path in hdf:
                    wse_data = hdf[wse_path][:]
                    # wse_data is typically [n_profiles, n_xs]
                    # Need to find the correct profile index

                profile_results.append(CrossSectionResults(
                    river="",
                    reach="",
                    station=0,
                    structure="",
                    profile=profile
                ))

                results[profile] = profile_results

    except Exception as e:
        logger.error(f"Error extracting XS results: {e}")

    return results


def extract_blocked_obstructions(geom_hdf: Path) -> Dict[int, List[Dict]]:
    """Extract blocked obstruction data."""
    blocked = {}

    try:
        with h5py.File(geom_hdf, 'r') as hdf:
            counts_path = 'Geometry/Cross Sections/Blocked Obstructions/Counts'
            values_path = 'Geometry/Cross Sections/Blocked Obstructions/Values'

            if counts_path in hdf and values_path in hdf:
                counts = hdf[counts_path][:]
                values = hdf[values_path][:]

                offset = 0
                for i, count in enumerate(counts):
                    if count > 0:
                        blocked[i] = []
                        for j in range(count):
                            bo = values[offset + j]
                            blocked[i].append({
                                'sta_l': float(bo[0]),
                                'sta_r': float(bo[1]),
                                'elev': float(bo[2]),
                                'ground_elev': float(bo[3]) if len(bo) > 3 else -9999
                            })
                    offset += count

    except Exception as e:
        logger.error(f"Error extracting blocked obstructions: {e}")

    return blocked


def extract_levee_data(geom_hdf: Path) -> Dict[int, Dict]:
    """Extract levee data."""
    levees = {}

    try:
        with h5py.File(geom_hdf, 'r') as hdf:
            path = 'Geometry/Cross Sections/Levees'

            if path in hdf:
                data = hdf[path][:]
                for i, row in enumerate(data):
                    # row: [left_sta, left_elev, right_sta, right_elev] or similar
                    if len(row) >= 4:
                        levees[i] = {
                            'sta_l': float(row[0]),
                            'elev_l': float(row[1]),
                            'sta_r': float(row[2]),
                            'elev_r': float(row[3])
                        }

    except Exception as e:
        logger.error(f"Error extracting levee data: {e}")

    return levees


def extract_structure_sections(geom_hdf: Path) -> Dict[Tuple[str, str, float], int]:
    """
    Extract structure section numbers (1-4) for XS.

    Returns:
        Dict mapping (river, reach, station) to section number
    """
    sections = {}

    # This requires parsing structure data to identify
    # which XS are sections 1, 2, 3, 4 of each structure
    # Implementation depends on HDF structure

    return sections


def check_reach_lengths(xs_geom: List[CrossSectionData]) -> List[CheckMessage]:
    """Check reach length consistency."""
    messages = []

    for xs in xs_geom:
        if xs.len_lob == -9999 or xs.len_chl == -9999 or xs.len_rob == -9999:
            continue

        # Check both overbanks exceed channel by threshold
        if (xs.len_lob - xs.len_chl > REACH_LENGTH_DIFF_THRESHOLD and
            xs.len_rob - xs.len_chl > REACH_LENGTH_DIFF_THRESHOLD and
            not xs.structure):  # Not at structure
            messages.append(CheckMessage(
                message_id="XS_DT_01",
                severity=Severity.WARNING,
                check_type="XS",
                river=xs.river,
                reach=xs.reach,
                station=str(xs.station),
                structure=xs.structure,
                message=get_message_template("XS_DT_01").format(
                    lob=xs.len_lob, chl=xs.len_chl, rob=xs.len_rob
                )
            ))

        # Check left overbank ratio
        if xs.len_chl > 0 and xs.len_lob / xs.len_chl > REACH_LENGTH_RATIO_THRESHOLD:
            messages.append(CheckMessage(
                message_id="XS_DT_02L",
                severity=Severity.WARNING,
                check_type="XS",
                river=xs.river,
                reach=xs.reach,
                station=str(xs.station),
                structure=xs.structure,
                message=get_message_template("XS_DT_02L").format(
                    lob=xs.len_lob, chl=xs.len_chl
                )
            ))

        # Check right overbank ratio
        if xs.len_chl > 0 and xs.len_rob / xs.len_chl > REACH_LENGTH_RATIO_THRESHOLD:
            messages.append(CheckMessage(
                message_id="XS_DT_02R",
                severity=Severity.WARNING,
                check_type="XS",
                river=xs.river,
                reach=xs.reach,
                station=str(xs.station),
                structure=xs.structure,
                message=get_message_template("XS_DT_02R").format(
                    rob=xs.len_rob, chl=xs.len_chl
                )
            ))

    return messages


def check_ineffective_flow(
    xs_geom: List[CrossSectionData],
    xs_results: Dict[str, List[CrossSectionResults]],
    profiles: List[str]
) -> List[CheckMessage]:
    """Check ineffective flow area consistency."""
    messages = []

    for xs in xs_geom:
        # Check multiple ineffective areas
        if xs.ineff_count_l > 1:
            messages.append(CheckMessage(
                message_id="XS_IF_02L",
                severity=Severity.INFO,
                check_type="XS",
                river=xs.river,
                reach=xs.reach,
                station=str(xs.station),
                structure=xs.structure,
                message=get_message_template("XS_IF_02L")
            ))

        if xs.ineff_count_r > 1:
            messages.append(CheckMessage(
                message_id="XS_IF_02R",
                severity=Severity.INFO,
                check_type="XS",
                river=xs.river,
                reach=xs.reach,
                station=str(xs.station),
                structure=xs.structure,
                message=get_message_template("XS_IF_02R")
            ))

        # Check ineffective station vs bank station
        if xs.ineff_sta_l != -9999 and xs.bank_sta_l != -9999:
            if xs.ineff_sta_l < xs.bank_sta_l:  # Note: left is typically lower station
                # Actually need to check if extends past bank
                # This depends on XS orientation
                pass

        if xs.ineff_sta_r != -9999 and xs.bank_sta_r != -9999:
            if xs.bank_sta_r < xs.ineff_sta_r:
                messages.append(CheckMessage(
                    message_id="XS_IF_03R",
                    severity=Severity.WARNING,
                    check_type="XS",
                    river=xs.river,
                    reach=xs.reach,
                    station=str(xs.station),
                    structure=xs.structure,
                    message=get_message_template("XS_IF_03R").format(
                        ineffstar=xs.ineff_sta_r, bankstar=xs.bank_sta_r
                    )
                ))

    return messages


def check_blocked_obstructions(
    xs_geom: List[CrossSectionData],
    xs_results: Dict[str, List[CrossSectionResults]],
    blocked_obs: Dict[int, List[Dict]]
) -> List[CheckMessage]:
    """Check blocked obstruction coverage."""
    messages = []

    for i, xs in enumerate(xs_geom):
        if i not in blocked_obs or not blocked_obs[i]:
            continue

        obs_list = blocked_obs[i]

        # Separate left and right obstructions
        center_sta = (xs.bank_sta_l + xs.bank_sta_r) / 2 if xs.bank_sta_l != -9999 else 0

        left_obs = [o for o in obs_list if o['sta_r'] <= center_sta]
        right_obs = [o for o in obs_list if o['sta_l'] >= center_sta]

        # Check single obstruction at ground start
        if len(left_obs) == 1:
            if left_obs[0]['sta_l'] == xs.ground_sta_first:
                messages.append(CheckMessage(
                    message_id="XS_BO_01L",
                    severity=Severity.WARNING,
                    check_type="XS",
                    river=xs.river,
                    reach=xs.reach,
                    station=str(xs.station),
                    structure=xs.structure,
                    message=get_message_template("XS_BO_01L")
                ))

        if len(right_obs) == 1:
            if right_obs[0]['sta_r'] == xs.ground_sta_last:
                messages.append(CheckMessage(
                    message_id="XS_BO_01R",
                    severity=Severity.WARNING,
                    check_type="XS",
                    river=xs.river,
                    reach=xs.reach,
                    station=str(xs.station),
                    structure=xs.structure,
                    message=get_message_template("XS_BO_01R")
                ))

        # Check multiple obstructions needing ineffective coverage
        if len(left_obs) > 1:
            # Check if covered by ineffective flow areas
            # Simplified check - actual implementation needs more detail
            if xs.ineff_count_l == 0:
                messages.append(CheckMessage(
                    message_id="XS_BO_02L",
                    severity=Severity.WARNING,
                    check_type="XS",
                    river=xs.river,
                    reach=xs.reach,
                    station=str(xs.station),
                    structure=xs.structure,
                    message=get_message_template("XS_BO_02L")
                ))

        if len(right_obs) > 1:
            if xs.ineff_count_r == 0:
                messages.append(CheckMessage(
                    message_id="XS_BO_02R",
                    severity=Severity.WARNING,
                    check_type="XS",
                    river=xs.river,
                    reach=xs.reach,
                    station=str(xs.station),
                    structure=xs.structure,
                    message=get_message_template("XS_BO_02R")
                ))

    return messages


def check_ground_exceedance(
    xs_geom: List[CrossSectionData],
    xs_results: Dict[str, List[CrossSectionResults]],
    profiles: List[str]
) -> List[CheckMessage]:
    """Check if WSE exceeds ground at effective limits."""
    messages = []

    # Implementation checks WSE vs ground elevation at effective stations
    # for each profile

    return messages


def check_critical_depth(
    xs_geom: List[CrossSectionData],
    xs_results: Dict[str, List[CrossSectionResults]],
    profiles: List[str]
) -> List[CheckMessage]:
    """Check critical depth conditions."""
    messages = []

    # Implementation checks if WSE = critical WSE with permanent ineffective

    return messages


def check_levees(
    xs_geom: List[CrossSectionData],
    xs_results: Dict[str, List[CrossSectionResults]],
    levee_data: Dict[int, Dict],
    profiles: List[str]
) -> List[CheckMessage]:
    """Check levee overtopping conditions."""
    messages = []

    for i, xs in enumerate(xs_geom):
        if i not in levee_data:
            continue

        levee = levee_data[i]

        for profile in profiles:
            if profile not in xs_results:
                continue

            # Find matching result
            for result in xs_results[profile]:
                if (result.river == xs.river and
                    result.reach == xs.reach and
                    result.station == xs.station):

                    wse = result.wse

                    # Check left levee overtopping
                    if levee.get('elev_l', -9999) != -9999 and wse != -9999:
                        if wse > levee['elev_l']:
                            messages.append(CheckMessage(
                                message_id="XS_LV_04L",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=xs.river,
                                reach=xs.reach,
                                station=str(xs.station),
                                structure=xs.structure,
                                message=get_message_template("XS_LV_04L").format(
                                    assignedname=profile,
                                    wselev=wse,
                                    leveel=levee['elev_l']
                                )
                            ))

                    # Check right levee overtopping
                    if levee.get('elev_r', -9999) != -9999 and wse != -9999:
                        if wse > levee['elev_r']:
                            messages.append(CheckMessage(
                                message_id="XS_LV_04R",
                                severity=Severity.WARNING,
                                check_type="XS",
                                river=xs.river,
                                reach=xs.reach,
                                station=str(xs.station),
                                structure=xs.structure,
                                message=get_message_template("XS_LV_04R").format(
                                    assignedname=profile,
                                    wselev=wse,
                                    leveer=levee['elev_r']
                                )
                            ))

                    break

    return messages


def check_friction_slope_method(plan_hdf: Path, xs_geom: List[CrossSectionData]) -> List[CheckMessage]:
    """Check if friction slope method is appropriate for reach lengths."""
    messages = []

    # Check if any channel reach length > 500 ft
    long_reaches = any(xs.len_chl > LONG_REACH_LENGTH for xs in xs_geom)

    if long_reaches:
        # Get friction slope method from plan
        try:
            with h5py.File(plan_hdf, 'r') as hdf:
                method_path = 'Plan Data/Plan Parameters/Friction Slope Method'
                if method_path in hdf:
                    method = int(hdf[method_path][()])
                    if method != 1:  # Not Average Conveyance
                        method_names = {
                            1: "Average Conveyance",
                            2: "Average Friction Slope",
                            3: "Geometric Mean Friction Slope",
                            4: "Harmonic Mean Friction Slope",
                            5: "HEC6 Slope Average Method",
                            6: "Program Selects"
                        }
                        messages.append(CheckMessage(
                            message_id="XS_FS_01",
                            severity=Severity.INFO,
                            check_type="XS",
                            message=get_message_template("XS_FS_01").format(
                                frictionslopename=method_names.get(method, "Unknown")
                            )
                        ))
        except Exception as e:
            logger.debug(f"Could not read friction slope method: {e}")

    return messages


def build_xs_summary(
    xs_geom: List[CrossSectionData],
    xs_results: Dict[str, List[CrossSectionResults]],
    profile: str
) -> pd.DataFrame:
    """Build summary table for XS check report."""
    records = []

    for xs in xs_geom:
        record = {
            'river': xs.river,
            'reach': xs.reach,
            'station': xs.station,
            'structure': xs.structure,
            'len_lob': xs.len_lob if xs.len_lob != -9999 else None,
            'len_chl': xs.len_chl if xs.len_chl != -9999 else None,
            'len_rob': xs.len_rob if xs.len_rob != -9999 else None,
        }

        # Add results data if available
        if profile and profile in xs_results:
            for result in xs_results[profile]:
                if (result.river == xs.river and
                    result.reach == xs.reach and
                    result.station == xs.station):
                    record['topwidth'] = result.top_width if result.top_width != -9999 else None
                    record['qtotal'] = result.q_total if result.q_total != -9999 else None
                    break

        records.append(record)

    return pd.DataFrame(records)


def _decode_bytes(value) -> str:
    """Decode bytes to string if needed."""
    if isinstance(value, bytes):
        return value.decode('utf-8').strip()
    return str(value).strip()
```

## HDF Path Reference

### Geometry HDF Structure

```
/Geometry/
  Cross Sections/
    Attributes                          # Compound: River, Reach, RS
    Reach Lengths                       # [LOB, CHL, ROB] per XS
    Bank Stations                       # [Left, Right] per XS
    Station Elevation Info/
      Counts                            # Number of points per XS
      Values                            # [Station, Elevation] pairs
    Ineffective Flow Areas/
      Counts                            # Number of areas per XS
      Values                            # [Sta_L, Sta_R, Elev, Permanent]
    Blocked Obstructions/
      Counts                            # Number of obstructions per XS
      Values                            # [Sta_L, Sta_R, Elev, Ground_Elev]
    Levees/
      Values                            # [Sta_L, Elev_L, Sta_R, Elev_R]
```

### Plan HDF Results Structure

```
/Results/
  Steady/
    Output/
      Output Blocks/
        Base Output/
          Steady Profiles/
            Profile Names               # Profile name strings
            Cross Sections/
              Water Surface             # [n_profiles, n_xs]
              Critical Water Surface    # [n_profiles, n_xs]
              Flow                      # [n_profiles, n_xs]
              Velocity                  # [n_profiles, n_xs]
              Top Width                 # [n_profiles, n_xs]
```

## Testing Requirements

### Unit Tests

1. **test_extract_reach_lengths**: Verify reach length extraction
2. **test_extract_ineffective**: Verify ineffective flow area extraction
3. **test_extract_blocked_obs**: Verify blocked obstruction extraction
4. **test_check_reach_length_diff**: Test XS_DT_01 rule
5. **test_check_reach_length_ratio**: Test XS_DT_02L/R rules
6. **test_check_ineffective_multiple**: Test XS_IF_02L/R rules
7. **test_check_blocked_single**: Test XS_BO_01L/R rules
8. **test_check_levee_overtopping**: Test XS_LV_04L/R rules

### Integration Tests

1. Test with Muncie example project
2. Test with project having levees
3. Test with project having blocked obstructions
4. Test with multiple profiles

## Flow Code Legend

The summary table includes a "Flow Code" column with these abbreviations:

| Code | Meaning |
|------|---------|
| DL | Default ineffective left |
| DR | Default ineffective right |
| EL | Exceeds left ground |
| ER | Exceeds right ground |
| C | Critical depth |
| BL | Blocked obstruction left |
| BR | Blocked obstruction right |
| MBL | Multiple blocked left |
| MBR | Multiple blocked right |
| IL | Ineffective left |
| IR | Ineffective right |
| MIL | Multiple ineffective left |
| MIR | Multiple ineffective right |

## Dependencies

- `h5py`: HDF file access
- `pandas`: DataFrame operations
- `numpy`: Numerical operations
- Parent module: `RasCheck`, `CheckResults`, `CheckMessage`, `Severity`
- Sibling modules: `messages`, `thresholds`
