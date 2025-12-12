# Floodway Check Implementation Plan

## Overview

The Floodway Check validates floodway encroachment analysis including encroachment methods, surcharge values, floodway widths, starting water surface elevations, and discharge matching between base flood and floodway profiles.

## Module Location

```
ras_commander/check/floodway_check.py
```

## Background

A regulatory floodway is the channel and adjacent floodplain that must be kept free from encroachment so that the 1% annual chance (100-year) flood can be carried without increasing the base flood elevation more than a specified amount (typically 1.0 foot, though some states use 0.5 or 0.0 feet).

## Data Sources

### From Plan HDF (`.p##.hdf`)

| HDF Path | Data | Description |
|----------|------|-------------|
| `Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/` | Profile results | WSE per profile |
| `Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names` | Profile names | Base and floodway profiles |
| `Plan Data/Encroachment Data/` | Encroachment settings | Method, values |

### From Geometry HDF (`.g##.hdf`)

| HDF Path | Data | Description |
|----------|------|-------------|
| `Geometry/Cross Sections/Attributes` | XS identifiers | River, Reach, RS |
| `Geometry/Cross Sections/Encroachment Stations/` | Encroachment data | Left/right stations |

## Encroachment Methods

HEC-RAS supports 5 encroachment methods:

| Method | Description | Use |
|--------|-------------|-----|
| 1 | Fixed encroachment stations | Manual specification |
| 2 | Fixed top width | Specified top width reduction |
| 3 | Percent conveyance reduction | Equal % reduction left/right |
| 4 | Percent conveyance reduction with optimization | Optimized left/right |
| 5 | Target surcharge with optimization | Target WSE increase |

**Note**: Methods 2-5 are acceptable for FEMA submittals. Method 1 (fixed stations) requires justification.

## Validation Rules

### 1. Encroachment Method Checks (FW EM)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| FW_EM_01 | Method = 1 (Fixed stations) | WARNING | Fixed encroachment stations (Method 1) used at RS {station} |
| FW_EM_02 | Method not specified | ERROR | No encroachment method specified for floodway profile |
| FW_EM_03 | Method varies within reach | INFO | Encroachment method varies within reach (multiple methods used) |
| FW_EM_04 | Method = 0 (None) at non-structure XS | WARNING | No encroachment at non-structure XS {station} |

### 2. Surcharge Checks (FW SC)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| FW_SC_01 | Surcharge > allowable surcharge | ERROR | Surcharge {sc} exceeds allowable surcharge {max} at RS {station} |
| FW_SC_02 | Surcharge < 0 (WSE decreased) | WARNING | Negative surcharge {sc} at RS {station} - WSE decreased |
| FW_SC_03 | Surcharge = 0 (exact match) | INFO | Zero surcharge at RS {station} |
| FW_SC_04 | Surcharge within 0.01 ft of limit | INFO | Surcharge {sc} is within 0.01 ft of limit at RS {station} |

### 3. Floodway Width Checks (FW WD)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| FW_WD_01 | Floodway width = 0 | WARNING | Zero floodway width at RS {station} |
| FW_WD_02 | Left encroachment > left bank | WARNING | Left encroachment extends beyond left bank at RS {station} |
| FW_WD_03 | Right encroachment > right bank | WARNING | Right encroachment extends beyond right bank at RS {station} |
| FW_WD_04 | Floodway width < channel width | INFO | Floodway narrower than channel at RS {station} |
| FW_WD_05 | Large lateral slope change (>1:1) | WARNING | Steep floodway boundary slope at RS {station} |

### 4. Discharge Checks (FW Q)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| FW_Q_01 | Q_floodway != Q_base_flood | WARNING | Floodway discharge {qfw} differs from base flood {qbf} at RS {station} |
| FW_Q_02 | Q_floodway > Q_base_flood * 1.01 | ERROR | Floodway discharge exceeds base flood by >1% at RS {station} |
| FW_Q_03 | Discharge changes along reach | INFO | Discharge changes within floodway reach |

### 5. Boundary Condition Checks (FW BC)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| FW_BC_01 | Different starting WSE for floodway | WARNING | Floodway starting WSE differs from base flood |
| FW_BC_02 | Same slope boundary for floodway | INFO | Same slope used as boundary for floodway profile |
| FW_BC_03 | Known WSE at downstream | INFO | Known WSE boundary used for floodway analysis |

### 6. Structure Floodway Checks (FW ST)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| FW_ST_01 | Structure sections don't match encroachments | WARNING | Encroachment at structure sections 2/3 should match openings |
| FW_ST_02 | Bridge: encroachments inside abutments | ERROR | Encroachments inside bridge abutments at RS {station} |
| FW_ST_03 | No encroachment at structure | INFO | No encroachment specified at structure RS {station} |

### 7. Equal Conveyance Reduction Check (FW EC)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| FW_EC_01 | Equal conveyance reduction not set when Method 4/5 | WARNING | Equal conveyance reduction option not enabled |

### 8. Lateral Weir Checks in Floodway (FW LW)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| FW_LW_01 | Lateral weir active in floodway | INFO | Lateral weir at station {sta} is active in floodway |
| FW_LW_02 | Lateral weir flow > 5% of main channel | WARNING | Lateral weir flow >5% of main channel at station {sta} |

## Implementation

```python
"""
Floodway Check - Encroachment Analysis Validation

This module validates floodway encroachment analysis in HEC-RAS models.
"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import pandas as pd
import numpy as np
import h5py

from ..RasCheck import CheckResults, CheckMessage, Severity
from .messages import get_message_template
from .thresholds import DEFAULT_SURCHARGE_LIMIT
from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


@dataclass
class FloodwayData:
    """Container for floodway data at each cross section."""
    river: str
    reach: str
    station: float
    structure: str = ""
    section_num: int = -99

    # Encroachment method
    method: int = -9999
    value_1: float = -9999  # Method-specific value 1
    value_2: float = -9999  # Method-specific value 2

    # Encroachment stations
    encr_sta_l: float = -9999  # Left encroachment station
    encr_sta_r: float = -9999  # Right encroachment station

    # Effective stations (for base flood)
    eff_sta_l: float = -9999
    eff_sta_r: float = -9999

    # Bank stations
    bank_sta_l: float = -9999
    bank_sta_r: float = -9999
    center_sta: float = -9999

    # Top widths
    top_width_base: float = -9999
    top_width_floodway: float = -9999

    # Surcharge
    surcharge: float = -9999

    # WSE values
    wse_base: float = -9999
    wse_floodway: float = -9999

    # Discharge
    q_base: float = -9999
    q_floodway: float = -9999

    # Reach lengths
    reach_len_chl: float = -9999


@log_call
def run_floodway_check(
    plan_hdf: Path,
    geom_hdf: Path,
    base_profile: str,
    floodway_profile: str,
    max_surcharge: float = 1.0
) -> CheckResults:
    """
    Run all floodway validation checks.

    Args:
        plan_hdf: Path to plan HDF file
        geom_hdf: Path to geometry HDF file
        base_profile: Name of base flood profile (typically 1% annual chance)
        floodway_profile: Name of floodway profile
        max_surcharge: Maximum allowable surcharge in feet (default 1.0)

    Returns:
        CheckResults containing floodway check messages and summary
    """
    results = CheckResults()
    messages = []

    # Extract floodway data
    fw_data = extract_floodway_data(plan_hdf, geom_hdf, base_profile, floodway_profile)
    if not fw_data:
        logger.warning("No floodway data found")
        return results

    # Extract boundary condition data
    bc_data = extract_boundary_conditions(plan_hdf, base_profile, floodway_profile)

    # Extract lateral weir data
    lat_weir_data = extract_lateral_weirs(geom_hdf)

    # Get equal conveyance reduction setting
    equal_conv_reduction = get_equal_conveyance_setting(plan_hdf)

    # Run validation checks
    messages.extend(check_encroachment_methods(fw_data))
    messages.extend(check_surcharge_values(fw_data, max_surcharge))
    messages.extend(check_floodway_widths(fw_data))
    messages.extend(check_discharge_match(fw_data))
    messages.extend(check_boundary_conditions(bc_data, base_profile, floodway_profile))
    messages.extend(check_structure_floodways(fw_data))
    messages.extend(check_equal_conveyance(fw_data, equal_conv_reduction))
    messages.extend(check_lateral_weirs_floodway(fw_data, lat_weir_data, floodway_profile))

    # Build summary DataFrame
    results.floodway_summary = build_floodway_summary(fw_data, max_surcharge)
    results.messages = messages

    return results


def extract_floodway_data(
    plan_hdf: Path,
    geom_hdf: Path,
    base_profile: str,
    floodway_profile: str
) -> List[FloodwayData]:
    """Extract floodway analysis data from HDF files."""
    fw_list = []

    try:
        with h5py.File(plan_hdf, 'r') as plan, h5py.File(geom_hdf, 'r') as geom:
            # Get cross section attributes
            xs_attrs_path = 'Geometry/Cross Sections/Attributes'
            if xs_attrs_path not in geom:
                return fw_list

            xs_attrs = geom[xs_attrs_path][:]

            # Get profile index
            profile_names_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names'
            if profile_names_path not in plan:
                return fw_list

            profile_names = [_decode_bytes(n) for n in plan[profile_names_path][:]]
            base_idx = profile_names.index(base_profile) if base_profile in profile_names else -1
            fw_idx = profile_names.index(floodway_profile) if floodway_profile in profile_names else -1

            if base_idx < 0 or fw_idx < 0:
                logger.warning(f"Profile not found: base={base_profile}, floodway={floodway_profile}")
                return fw_list

            # Get WSE data
            wse_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Water Surface'
            wse_data = plan[wse_path][:] if wse_path in plan else None

            # Get discharge data
            q_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Cross Sections/Flow'
            q_data = plan[q_path][:] if q_path in plan else None

            # Get encroachment data
            encr_path = 'Plan Data/Encroachment Data'
            # Implementation depends on HDF structure

            # Get bank stations
            bank_path = 'Geometry/Cross Sections/Bank Stations'
            bank_data = geom[bank_path][:] if bank_path in geom else None

            # Build floodway data list
            for i, attr in enumerate(xs_attrs):
                fw = FloodwayData(
                    river=_decode_bytes(attr['River']),
                    reach=_decode_bytes(attr['Reach']),
                    station=float(attr['RS'])
                )

                # Add WSE data
                if wse_data is not None and base_idx >= 0:
                    fw.wse_base = float(wse_data[base_idx, i])
                if wse_data is not None and fw_idx >= 0:
                    fw.wse_floodway = float(wse_data[fw_idx, i])

                # Calculate surcharge
                if fw.wse_base != -9999 and fw.wse_floodway != -9999:
                    fw.surcharge = fw.wse_floodway - fw.wse_base

                # Add discharge data
                if q_data is not None and base_idx >= 0:
                    fw.q_base = float(q_data[base_idx, i])
                if q_data is not None and fw_idx >= 0:
                    fw.q_floodway = float(q_data[fw_idx, i])

                # Add bank stations
                if bank_data is not None:
                    fw.bank_sta_l = float(bank_data[i, 0])
                    fw.bank_sta_r = float(bank_data[i, 1])
                    fw.center_sta = (fw.bank_sta_l + fw.bank_sta_r) / 2

                fw_list.append(fw)

    except Exception as e:
        logger.error(f"Error extracting floodway data: {e}")

    return fw_list


def extract_boundary_conditions(
    plan_hdf: Path,
    base_profile: str,
    floodway_profile: str
) -> Dict:
    """Extract boundary condition settings."""
    bc_data = {
        'base': {},
        'floodway': {}
    }

    try:
        with h5py.File(plan_hdf, 'r') as hdf:
            # Get boundary condition paths
            # Implementation depends on HDF structure
            pass

    except Exception as e:
        logger.error(f"Error extracting boundary conditions: {e}")

    return bc_data


def extract_lateral_weirs(geom_hdf: Path) -> List[Dict]:
    """Extract lateral weir data."""
    weirs = []

    try:
        with h5py.File(geom_hdf, 'r') as hdf:
            # Get lateral weir data
            # Implementation depends on HDF structure
            pass

    except Exception as e:
        logger.error(f"Error extracting lateral weirs: {e}")

    return weirs


def get_equal_conveyance_setting(plan_hdf: Path) -> bool:
    """Get equal conveyance reduction setting from plan."""
    try:
        with h5py.File(plan_hdf, 'r') as hdf:
            path = 'Plan Data/Plan Parameters/Equal Conveyance Reduction'
            if path in hdf:
                return bool(hdf[path][()])
    except Exception:
        pass

    return False


def check_encroachment_methods(fw_data: List[FloodwayData]) -> List[CheckMessage]:
    """Check encroachment method consistency."""
    messages = []

    methods_used = set()

    for fw in fw_data:
        if fw.method == -9999:
            continue

        methods_used.add(fw.method)

        # Check for Method 1 (fixed stations)
        if fw.method == 1 and fw.section_num == -99:  # Not at structure
            messages.append(CheckMessage(
                message_id="FW_EM_01",
                severity=Severity.WARNING,
                check_type="FW",
                river=fw.river,
                reach=fw.reach,
                station=str(fw.station),
                structure=fw.structure,
                message=get_message_template("FW_EM_01").format(station=fw.station)
            ))

        # Check for Method 0 (none) at non-structure XS
        if fw.method == 0 and fw.section_num == -99:
            messages.append(CheckMessage(
                message_id="FW_EM_04",
                severity=Severity.WARNING,
                check_type="FW",
                river=fw.river,
                reach=fw.reach,
                station=str(fw.station),
                structure=fw.structure,
                message=get_message_template("FW_EM_04").format(station=fw.station)
            ))

    # Check for multiple methods
    if len(methods_used) > 1:
        messages.append(CheckMessage(
            message_id="FW_EM_03",
            severity=Severity.INFO,
            check_type="FW",
            message=get_message_template("FW_EM_03").format(
                methods=', '.join(str(m) for m in sorted(methods_used))
            )
        ))

    return messages


def check_surcharge_values(
    fw_data: List[FloodwayData],
    max_surcharge: float
) -> List[CheckMessage]:
    """Check surcharge values against limit."""
    messages = []

    for fw in fw_data:
        if fw.surcharge == -9999:
            continue

        # Round surcharge for comparison
        surcharge_rounded = round(fw.surcharge, 2)

        # Check if exceeds maximum
        if surcharge_rounded > max_surcharge:
            messages.append(CheckMessage(
                message_id="FW_SC_01",
                severity=Severity.ERROR,
                check_type="FW",
                river=fw.river,
                reach=fw.reach,
                station=str(fw.station),
                structure=fw.structure,
                message=get_message_template("FW_SC_01").format(
                    sc=surcharge_rounded, max=max_surcharge, station=fw.station
                )
            ))

        # Check for negative surcharge
        elif surcharge_rounded < 0:
            messages.append(CheckMessage(
                message_id="FW_SC_02",
                severity=Severity.WARNING,
                check_type="FW",
                river=fw.river,
                reach=fw.reach,
                station=str(fw.station),
                structure=fw.structure,
                message=get_message_template("FW_SC_02").format(
                    sc=surcharge_rounded, station=fw.station
                )
            ))

        # Check for zero surcharge
        elif surcharge_rounded == 0:
            messages.append(CheckMessage(
                message_id="FW_SC_03",
                severity=Severity.INFO,
                check_type="FW",
                river=fw.river,
                reach=fw.reach,
                station=str(fw.station),
                structure=fw.structure,
                message=get_message_template("FW_SC_03").format(station=fw.station)
            ))

        # Check if within 0.01 ft of limit
        elif abs(max_surcharge - surcharge_rounded) <= 0.01:
            messages.append(CheckMessage(
                message_id="FW_SC_04",
                severity=Severity.INFO,
                check_type="FW",
                river=fw.river,
                reach=fw.reach,
                station=str(fw.station),
                structure=fw.structure,
                message=get_message_template("FW_SC_04").format(
                    sc=surcharge_rounded, station=fw.station
                )
            ))

    return messages


def check_floodway_widths(fw_data: List[FloodwayData]) -> List[CheckMessage]:
    """Check floodway width consistency."""
    messages = []

    prev_fw = None

    for fw in fw_data:
        # Check zero floodway width
        if fw.encr_sta_l != -9999 and fw.encr_sta_r != -9999:
            floodway_width = fw.encr_sta_r - fw.encr_sta_l
            if floodway_width <= 0:
                messages.append(CheckMessage(
                    message_id="FW_WD_01",
                    severity=Severity.WARNING,
                    check_type="FW",
                    river=fw.river,
                    reach=fw.reach,
                    station=str(fw.station),
                    structure=fw.structure,
                    message=get_message_template("FW_WD_01").format(station=fw.station)
                ))

        # Check encroachment beyond bank
        if fw.encr_sta_l != -9999 and fw.bank_sta_l != -9999:
            if fw.encr_sta_l < fw.bank_sta_l:
                messages.append(CheckMessage(
                    message_id="FW_WD_02",
                    severity=Severity.WARNING,
                    check_type="FW",
                    river=fw.river,
                    reach=fw.reach,
                    station=str(fw.station),
                    structure=fw.structure,
                    message=get_message_template("FW_WD_02").format(station=fw.station)
                ))

        if fw.encr_sta_r != -9999 and fw.bank_sta_r != -9999:
            if fw.encr_sta_r > fw.bank_sta_r:
                messages.append(CheckMessage(
                    message_id="FW_WD_03",
                    severity=Severity.WARNING,
                    check_type="FW",
                    river=fw.river,
                    reach=fw.reach,
                    station=str(fw.station),
                    structure=fw.structure,
                    message=get_message_template("FW_WD_03").format(station=fw.station)
                ))

        # Check lateral slope (change in encroachment position)
        if prev_fw is not None and fw.reach_len_chl > 0:
            if (prev_fw.encr_sta_l != -9999 and fw.encr_sta_l != -9999 and
                prev_fw.center_sta != -9999 and fw.center_sta != -9999):

                left_change = (prev_fw.center_sta - prev_fw.encr_sta_l) - (fw.center_sta - fw.encr_sta_l)
                left_slope = abs(left_change / fw.reach_len_chl)

                if left_slope > 1.0:  # Steeper than 1:1
                    messages.append(CheckMessage(
                        message_id="FW_WD_05",
                        severity=Severity.WARNING,
                        check_type="FW",
                        river=fw.river,
                        reach=fw.reach,
                        station=str(fw.station),
                        structure=fw.structure,
                        message=get_message_template("FW_WD_05").format(
                            station=fw.station, slope=round(left_slope, 2)
                        )
                    ))

        prev_fw = fw

    return messages


def check_discharge_match(fw_data: List[FloodwayData]) -> List[CheckMessage]:
    """Check discharge matching between base flood and floodway."""
    messages = []

    for fw in fw_data:
        if fw.q_base == -9999 or fw.q_floodway == -9999:
            continue

        # Check for discharge mismatch
        if fw.q_base != 0:
            ratio = fw.q_floodway / fw.q_base

            if ratio > 1.01:  # More than 1% higher
                messages.append(CheckMessage(
                    message_id="FW_Q_02",
                    severity=Severity.ERROR,
                    check_type="FW",
                    river=fw.river,
                    reach=fw.reach,
                    station=str(fw.station),
                    structure=fw.structure,
                    message=get_message_template("FW_Q_02").format(
                        station=fw.station,
                        qfw=fw.q_floodway,
                        qbf=fw.q_base
                    )
                ))
            elif abs(ratio - 1.0) > 0.001:  # Any difference
                messages.append(CheckMessage(
                    message_id="FW_Q_01",
                    severity=Severity.WARNING,
                    check_type="FW",
                    river=fw.river,
                    reach=fw.reach,
                    station=str(fw.station),
                    structure=fw.structure,
                    message=get_message_template("FW_Q_01").format(
                        station=fw.station,
                        qfw=fw.q_floodway,
                        qbf=fw.q_base
                    )
                ))

    return messages


def check_boundary_conditions(
    bc_data: Dict,
    base_profile: str,
    floodway_profile: str
) -> List[CheckMessage]:
    """Check boundary condition consistency."""
    messages = []

    # Compare starting WSE between profiles
    # Compare downstream boundary conditions

    return messages


def check_structure_floodways(fw_data: List[FloodwayData]) -> List[CheckMessage]:
    """Check floodway at structure sections."""
    messages = []

    for fw in fw_data:
        if fw.structure == '':
            continue

        # Check for no encroachment at structure
        if fw.method == 0 or fw.method == -9999:
            messages.append(CheckMessage(
                message_id="FW_ST_03",
                severity=Severity.INFO,
                check_type="FW",
                river=fw.river,
                reach=fw.reach,
                station=str(fw.station),
                structure=fw.structure,
                message=get_message_template("FW_ST_03").format(station=fw.station)
            ))

    return messages


def check_equal_conveyance(
    fw_data: List[FloodwayData],
    equal_conv_reduction: bool
) -> List[CheckMessage]:
    """Check equal conveyance reduction setting."""
    messages = []

    # Check if Methods 4 or 5 used without equal conveyance
    methods_4_5 = any(fw.method in [4, 5] for fw in fw_data if fw.method != -9999)

    if methods_4_5 and not equal_conv_reduction:
        messages.append(CheckMessage(
            message_id="FW_EC_01",
            severity=Severity.WARNING,
            check_type="FW",
            message=get_message_template("FW_EC_01")
        ))

    return messages


def check_lateral_weirs_floodway(
    fw_data: List[FloodwayData],
    lat_weir_data: List[Dict],
    floodway_profile: str
) -> List[CheckMessage]:
    """Check lateral weirs in floodway analysis."""
    messages = []

    # Check for active lateral weirs in floodway

    return messages


def build_floodway_summary(
    fw_data: List[FloodwayData],
    max_surcharge: float
) -> pd.DataFrame:
    """Build summary table for floodway check report."""
    records = []

    for fw in fw_data:
        record = {
            'river': fw.river,
            'reach': fw.reach,
            'station': fw.station,
            'structure': fw.structure if fw.structure else None,
            'method': fw.method if fw.method != -9999 else None,
            'surcharge': round(fw.surcharge, 2) if fw.surcharge != -9999 else None,
            'encr_sta_l': fw.encr_sta_l if fw.encr_sta_l != -9999 else None,
            'encr_sta_r': fw.encr_sta_r if fw.encr_sta_r != -9999 else None,
            'eff_sta_l': fw.eff_sta_l if fw.eff_sta_l != -9999 else None,
            'eff_sta_r': fw.eff_sta_r if fw.eff_sta_r != -9999 else None,
        }

        # Add lateral slope if previous XS available
        # (calculated in check function)

        records.append(record)

    return pd.DataFrame(records)


def _decode_bytes(value) -> str:
    """Decode bytes to string if needed."""
    if isinstance(value, bytes):
        return value.decode('utf-8').strip()
    return str(value).strip()
```

## Encroachment Method Details

### Method 1 - Fixed Encroachment Stations
- User specifies exact left and right encroachment stations
- No optimization
- Use only when geometric constraints require specific locations

### Method 2 - Fixed Top Width
- User specifies target top width
- Program calculates encroachment stations

### Method 3 - Percent Conveyance Reduction
- User specifies % conveyance reduction (left and right equal)
- Program calculates encroachment stations

### Method 4 - Optimized Percent Conveyance Reduction
- User specifies target surcharge
- Program optimizes left/right encroachments independently
- Uses equal conveyance reduction option

### Method 5 - Target Surcharge with Optimization
- User specifies target surcharge and conveyance reduction limits
- Program optimizes to achieve target surcharge

## Testing Requirements

### Unit Tests

1. **test_extract_floodway_data**: Verify floodway data extraction
2. **test_check_encroachment_methods**: Test method validation rules
3. **test_check_surcharge_values**: Test surcharge limit validation
4. **test_check_floodway_widths**: Test width validation
5. **test_check_discharge_match**: Test Q matching validation
6. **test_check_lateral_slopes**: Test slope calculation

### Integration Tests

1. Test with project using Method 4 (typical FEMA submission)
2. Test with project exceeding surcharge limit
3. Test with project having structures in floodway
4. Test with project having lateral weirs

## Dependencies

- `h5py`: HDF file access
- `pandas`: DataFrame operations
- `numpy`: Numerical operations
- Parent module: `RasCheck`, `CheckResults`, `CheckMessage`, `Severity`
- Sibling modules: `messages`, `thresholds`
