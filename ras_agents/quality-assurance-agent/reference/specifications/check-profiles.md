# Profiles Check Implementation Plan

## Overview

The Profiles Check validates consistency across multiple flood profiles, verifying that water surface elevations, top widths, and discharges follow expected patterns based on flood frequency. Lower frequency events (e.g., 500-year) should generally have higher WSE than higher frequency events (e.g., 10-year).

## Module Location

```
ras_commander/check/profiles_check.py
```

## Data Sources

### From Plan HDF (`.p##.hdf`)

| HDF Path | Data | Description |
|----------|------|-------------|
| `Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names` | Profile names | All profile names |
| `Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Water Surface` | WSE data | [n_profiles, n_xs] array |
| `Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Flow` | Discharge | [n_profiles, n_xs] array |
| `Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Top Width` | Top width | [n_profiles, n_xs] array |
| `Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Critical Water Surface` | Critical WSE | [n_profiles, n_xs] array |

## Expected Profile Ordering

Profiles are typically ordered by flood frequency:
- 10-year (10% annual chance)
- 50-year (2% annual chance)
- 100-year (1% annual chance)
- 500-year (0.2% annual chance)

Or by return period designation:
- Q10
- Q50
- Q100
- Q500

Lower frequency events should have higher:
- Water surface elevations
- Discharges
- Top widths (generally)

## Validation Rules

### 1. Water Surface Elevation Ordering (MP WS)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| MP_WS_01 | WSE(lower freq) < WSE(higher freq) | WARNING | WSE for {profile_low} is less than {profile_high} at RS {station} |
| MP_WS_02 | WSE difference < 0.01 ft | INFO | WSE for {profile_low} and {profile_high} are nearly equal at RS {station} |
| MP_WS_03 | Large WSE jump (>3 ft) between profiles | INFO | Large WSE difference ({diff} ft) between {profile_low} and {profile_high} at RS {station} |

### 2. Discharge Ordering (MP Q)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| MP_Q_01 | Q(lower freq) < Q(higher freq) | WARNING | Discharge for {profile_low} is less than {profile_high} at RS {station} |
| MP_Q_02 | Q inconsistency within profile | WARNING | Discharge changes unexpectedly within reach at RS {station} for {profile} |

### 3. Top Width Consistency (MP TW)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| MP_TW_01 | TopWidth(lower freq) < TopWidth(higher freq) * 0.9 | INFO | Top width for {profile_low} is less than {profile_high} at RS {station} |
| MP_TW_02 | Large top width difference | INFO | Large top width difference between {profile_low} and {profile_high} at RS {station} |

### 4. Flow Regime Consistency (MP FR)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| MP_FR_01 | Critical depth in higher frequency, not lower | INFO | Critical depth in {profile_high} but not {profile_low} at RS {station} |
| MP_FR_02 | Flow regime changes between profiles | INFO | Flow regime changes from subcritical to supercritical between profiles at RS {station} |

### 5. Boundary Condition Consistency (MP BC)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| MP_BC_01 | Different BC types between profiles | WARNING | Boundary condition type differs between profiles |
| MP_BC_02 | Starting WSE inconsistent with Q order | WARNING | Starting WSE ordering doesn't match discharge ordering |

### 6. Cross-Profile Data Quality (MP DQ)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| MP_DQ_01 | Missing data for profile at XS | WARNING | Missing data for {profile} at RS {station} |
| MP_DQ_02 | Computation not converged | WARNING | Computation may not have converged for {profile} at RS {station} |

## Implementation

```python
"""
Profiles Check - Multiple Profile Consistency Validation

This module validates consistency across multiple flood profiles.
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
    WSE_EQUAL_THRESHOLD,
    WSE_LARGE_DIFF_THRESHOLD,
    TOPWIDTH_RATIO_THRESHOLD
)
from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


@dataclass
class ProfileData:
    """Container for profile data at each cross section."""
    river: str
    reach: str
    station: float
    structure: str = ""

    # Data per profile (dict keyed by profile name)
    wse: Dict[str, float] = None
    q_total: Dict[str, float] = None
    top_width: Dict[str, float] = None
    crit_wse: Dict[str, float] = None

    def __post_init__(self):
        if self.wse is None:
            self.wse = {}
        if self.q_total is None:
            self.q_total = {}
        if self.top_width is None:
            self.top_width = {}
        if self.crit_wse is None:
            self.crit_wse = {}


@log_call
def run_profiles_check(
    plan_hdf: Path,
    profiles: List[str]
) -> CheckResults:
    """
    Run all multiple profile validation checks.

    Args:
        plan_hdf: Path to plan HDF file
        profiles: List of profile names in order of increasing frequency
                  (e.g., ['10yr', '50yr', '100yr', '500yr'])
                  Note: Order matters - first is highest frequency (lower Q)

    Returns:
        CheckResults containing profiles check messages and summary
    """
    results = CheckResults()
    messages = []

    if len(profiles) < 2:
        logger.info("Need at least 2 profiles for comparison")
        return results

    # Extract profile data
    profile_data = extract_profile_data(plan_hdf, profiles)
    if not profile_data:
        logger.warning("No profile data found")
        return results

    # Run validation checks
    messages.extend(check_wse_ordering(profile_data, profiles))
    messages.extend(check_discharge_ordering(profile_data, profiles))
    messages.extend(check_topwidth_consistency(profile_data, profiles))
    messages.extend(check_flow_regime(profile_data, profiles))
    messages.extend(check_boundary_consistency(plan_hdf, profiles))
    messages.extend(check_data_quality(profile_data, profiles))

    # Build summary DataFrame
    results.profiles_summary = build_profiles_summary(profile_data, profiles)
    results.messages = messages

    return results


def extract_profile_data(
    plan_hdf: Path,
    profiles: List[str]
) -> List[ProfileData]:
    """Extract data for all profiles from HDF file."""
    profile_data_list = []

    try:
        with h5py.File(plan_hdf, 'r') as hdf:
            base_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles'

            # Get profile names and indices
            profile_names_path = f'{base_path}/Profile Names'
            if profile_names_path not in hdf:
                return profile_data_list

            all_profiles = [_decode_bytes(n) for n in hdf[profile_names_path][:]]

            # Build profile index map
            profile_indices = {}
            for p in profiles:
                if p in all_profiles:
                    profile_indices[p] = all_profiles.index(p)
                else:
                    logger.warning(f"Profile '{p}' not found in HDF")

            if not profile_indices:
                return profile_data_list

            # Get cross section attributes
            xs_attrs_path = 'Results/Steady/Geometry Info/Cross Section/Attributes'
            alt_path = 'Geometry/Cross Sections/Attributes'

            if xs_attrs_path in hdf:
                xs_attrs = hdf[xs_attrs_path][:]
            elif alt_path in hdf:
                # Read from geometry info
                xs_attrs = hdf[alt_path][:]
            else:
                logger.warning("No cross section attributes found")
                return profile_data_list

            # Get WSE data
            wse_path = f'{base_path}/Cross Sections/Water Surface'
            wse_data = hdf[wse_path][:] if wse_path in hdf else None

            # Get discharge data
            q_path = f'{base_path}/Cross Sections/Flow'
            q_data = hdf[q_path][:] if q_path in hdf else None

            # Get top width data
            tw_path = f'{base_path}/Cross Sections/Top Width'
            tw_data = hdf[tw_path][:] if tw_path in hdf else None

            # Get critical WSE data
            crit_path = f'{base_path}/Cross Sections/Critical Water Surface'
            crit_data = hdf[crit_path][:] if crit_path in hdf else None

            # Build profile data for each XS
            n_xs = len(xs_attrs)
            for i in range(n_xs):
                pd_item = ProfileData(
                    river=_decode_bytes(xs_attrs[i]['River']) if 'River' in xs_attrs.dtype.names else '',
                    reach=_decode_bytes(xs_attrs[i]['Reach']) if 'Reach' in xs_attrs.dtype.names else '',
                    station=float(xs_attrs[i]['RS']) if 'RS' in xs_attrs.dtype.names else i
                )

                for profile, idx in profile_indices.items():
                    if wse_data is not None:
                        pd_item.wse[profile] = float(wse_data[idx, i])
                    if q_data is not None:
                        pd_item.q_total[profile] = float(q_data[idx, i])
                    if tw_data is not None:
                        pd_item.top_width[profile] = float(tw_data[idx, i])
                    if crit_data is not None:
                        pd_item.crit_wse[profile] = float(crit_data[idx, i])

                profile_data_list.append(pd_item)

    except Exception as e:
        logger.error(f"Error extracting profile data: {e}")

    return profile_data_list


def check_wse_ordering(
    profile_data: List[ProfileData],
    profiles: List[str]
) -> List[CheckMessage]:
    """Check water surface elevation ordering across profiles."""
    messages = []

    # Compare adjacent profiles (expect WSE to increase as frequency decreases)
    for i in range(len(profiles) - 1):
        higher_freq = profiles[i]      # e.g., 10yr
        lower_freq = profiles[i + 1]   # e.g., 50yr

        for pd_item in profile_data:
            wse_high = pd_item.wse.get(higher_freq, -9999)
            wse_low = pd_item.wse.get(lower_freq, -9999)

            if wse_high == -9999 or wse_low == -9999:
                continue

            diff = wse_low - wse_high

            # Check if ordering is reversed
            if diff < -0.01:  # Lower frequency has lower WSE
                messages.append(CheckMessage(
                    message_id="MP_WS_01",
                    severity=Severity.WARNING,
                    check_type="PROFILES",
                    river=pd_item.river,
                    reach=pd_item.reach,
                    station=str(pd_item.station),
                    structure=pd_item.structure,
                    message=get_message_template("MP_WS_01").format(
                        profile_low=lower_freq,
                        profile_high=higher_freq,
                        station=pd_item.station
                    )
                ))

            # Check if nearly equal
            elif abs(diff) < WSE_EQUAL_THRESHOLD:
                messages.append(CheckMessage(
                    message_id="MP_WS_02",
                    severity=Severity.INFO,
                    check_type="PROFILES",
                    river=pd_item.river,
                    reach=pd_item.reach,
                    station=str(pd_item.station),
                    structure=pd_item.structure,
                    message=get_message_template("MP_WS_02").format(
                        profile_low=lower_freq,
                        profile_high=higher_freq,
                        station=pd_item.station
                    )
                ))

            # Check for large jump
            elif diff > WSE_LARGE_DIFF_THRESHOLD:
                messages.append(CheckMessage(
                    message_id="MP_WS_03",
                    severity=Severity.INFO,
                    check_type="PROFILES",
                    river=pd_item.river,
                    reach=pd_item.reach,
                    station=str(pd_item.station),
                    structure=pd_item.structure,
                    message=get_message_template("MP_WS_03").format(
                        diff=round(diff, 2),
                        profile_low=lower_freq,
                        profile_high=higher_freq,
                        station=pd_item.station
                    )
                ))

    return messages


def check_discharge_ordering(
    profile_data: List[ProfileData],
    profiles: List[str]
) -> List[CheckMessage]:
    """Check discharge ordering across profiles."""
    messages = []

    for i in range(len(profiles) - 1):
        higher_freq = profiles[i]
        lower_freq = profiles[i + 1]

        for pd_item in profile_data:
            q_high = pd_item.q_total.get(higher_freq, -9999)
            q_low = pd_item.q_total.get(lower_freq, -9999)

            if q_high == -9999 or q_low == -9999:
                continue

            # Check if ordering is reversed
            if q_low < q_high * 0.99:  # Allow small tolerance
                messages.append(CheckMessage(
                    message_id="MP_Q_01",
                    severity=Severity.WARNING,
                    check_type="PROFILES",
                    river=pd_item.river,
                    reach=pd_item.reach,
                    station=str(pd_item.station),
                    structure=pd_item.structure,
                    message=get_message_template("MP_Q_01").format(
                        profile_low=lower_freq,
                        profile_high=higher_freq,
                        station=pd_item.station
                    )
                ))

    return messages


def check_topwidth_consistency(
    profile_data: List[ProfileData],
    profiles: List[str]
) -> List[CheckMessage]:
    """Check top width consistency across profiles."""
    messages = []

    for i in range(len(profiles) - 1):
        higher_freq = profiles[i]
        lower_freq = profiles[i + 1]

        for pd_item in profile_data:
            tw_high = pd_item.top_width.get(higher_freq, -9999)
            tw_low = pd_item.top_width.get(lower_freq, -9999)

            if tw_high == -9999 or tw_low == -9999 or tw_high <= 0:
                continue

            # Check if lower frequency has narrower width
            ratio = tw_low / tw_high

            if ratio < TOPWIDTH_RATIO_THRESHOLD:
                messages.append(CheckMessage(
                    message_id="MP_TW_01",
                    severity=Severity.INFO,
                    check_type="PROFILES",
                    river=pd_item.river,
                    reach=pd_item.reach,
                    station=str(pd_item.station),
                    structure=pd_item.structure,
                    message=get_message_template("MP_TW_01").format(
                        profile_low=lower_freq,
                        profile_high=higher_freq,
                        station=pd_item.station
                    )
                ))

    return messages


def check_flow_regime(
    profile_data: List[ProfileData],
    profiles: List[str]
) -> List[CheckMessage]:
    """Check flow regime consistency across profiles."""
    messages = []

    for i in range(len(profiles) - 1):
        higher_freq = profiles[i]
        lower_freq = profiles[i + 1]

        for pd_item in profile_data:
            wse_high = pd_item.wse.get(higher_freq, -9999)
            wse_low = pd_item.wse.get(lower_freq, -9999)
            crit_high = pd_item.crit_wse.get(higher_freq, -9999)
            crit_low = pd_item.crit_wse.get(lower_freq, -9999)

            if wse_high == -9999 or crit_high == -9999:
                continue

            # Check if critical in higher frequency but not lower
            is_critical_high = abs(wse_high - crit_high) < 0.01
            is_critical_low = abs(wse_low - crit_low) < 0.01 if wse_low != -9999 and crit_low != -9999 else False

            if is_critical_high and not is_critical_low:
                messages.append(CheckMessage(
                    message_id="MP_FR_01",
                    severity=Severity.INFO,
                    check_type="PROFILES",
                    river=pd_item.river,
                    reach=pd_item.reach,
                    station=str(pd_item.station),
                    structure=pd_item.structure,
                    message=get_message_template("MP_FR_01").format(
                        profile_high=higher_freq,
                        profile_low=lower_freq,
                        station=pd_item.station
                    )
                ))

    return messages


def check_boundary_consistency(
    plan_hdf: Path,
    profiles: List[str]
) -> List[CheckMessage]:
    """Check boundary condition consistency across profiles."""
    messages = []

    # Compare boundary condition types across profiles

    return messages


def check_data_quality(
    profile_data: List[ProfileData],
    profiles: List[str]
) -> List[CheckMessage]:
    """Check for missing or invalid data across profiles."""
    messages = []

    for pd_item in profile_data:
        for profile in profiles:
            # Check for missing WSE
            wse = pd_item.wse.get(profile, -9999)
            if wse == -9999:
                messages.append(CheckMessage(
                    message_id="MP_DQ_01",
                    severity=Severity.WARNING,
                    check_type="PROFILES",
                    river=pd_item.river,
                    reach=pd_item.reach,
                    station=str(pd_item.station),
                    structure=pd_item.structure,
                    message=get_message_template("MP_DQ_01").format(
                        profile=profile,
                        station=pd_item.station
                    )
                ))

    return messages


def build_profiles_summary(
    profile_data: List[ProfileData],
    profiles: List[str]
) -> pd.DataFrame:
    """Build summary table for profiles check report."""
    records = []

    for pd_item in profile_data:
        record = {
            'river': pd_item.river,
            'reach': pd_item.reach,
            'station': pd_item.station,
            'structure': pd_item.structure if pd_item.structure else None
        }

        # Add WSE for each profile
        for profile in profiles:
            wse = pd_item.wse.get(profile, None)
            record[f'wse_{profile}'] = round(wse, 2) if wse and wse != -9999 else None

        # Add Q for each profile
        for profile in profiles:
            q = pd_item.q_total.get(profile, None)
            record[f'q_{profile}'] = round(q, 0) if q and q != -9999 else None

        records.append(record)

    return pd.DataFrame(records)


def _decode_bytes(value) -> str:
    """Decode bytes to string if needed."""
    if isinstance(value, bytes):
        return value.decode('utf-8').strip()
    return str(value).strip()
```

## Profile Naming Conventions

Common profile naming patterns:

| Pattern | Description |
|---------|-------------|
| 10yr, 50yr, 100yr, 500yr | Year-based |
| Q10, Q50, Q100, Q500 | Q-prefix |
| 10% AEP, 2% AEP, 1% AEP | Annual exceedance probability |
| 0.1 ACE, 0.02 ACE, 0.01 ACE | Annual chance exceedance |
| Floodway | Special floodway profile |

## Expected Relationships

For properly modeled steady flow:

```
Q_10yr < Q_50yr < Q_100yr < Q_500yr
WSE_10yr < WSE_50yr < WSE_100yr < WSE_500yr
TopWidth_10yr <= TopWidth_50yr <= TopWidth_100yr <= TopWidth_500yr
```

Exceptions may occur at:
- Structure transitions
- Critical flow locations
- Split flow points
- Ineffective flow boundaries

## Testing Requirements

### Unit Tests

1. **test_extract_profile_data**: Verify profile data extraction
2. **test_check_wse_ordering**: Test WSE comparison rules
3. **test_check_discharge_ordering**: Test Q comparison rules
4. **test_check_topwidth_consistency**: Test top width rules
5. **test_check_flow_regime**: Test flow regime consistency
6. **test_check_data_quality**: Test missing data detection

### Integration Tests

1. Test with Muncie example project (multiple profiles)
2. Test with project having WSE inversion
3. Test with project having missing profile data
4. Test with project at critical depth

## Dependencies

- `h5py`: HDF file access
- `pandas`: DataFrame operations
- `numpy`: Numerical operations
- Parent module: `RasCheck`, `CheckResults`, `CheckMessage`, `Severity`
- Sibling modules: `messages`, `thresholds`
