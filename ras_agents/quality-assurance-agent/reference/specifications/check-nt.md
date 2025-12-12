# NT Check Implementation Plan

## Overview

The NT Check validates Manning's roughness coefficients ("n" values) and transition loss coefficients throughout the HEC-RAS model. These parameters significantly affect computed water surface elevations.

## Module Location

```
ras_commander/check/nt_check.py
```

## Data Sources

### From Geometry HDF (`.g##.hdf`)

| HDF Path | Data | Python Access |
|----------|------|---------------|
| `/Geometry/Cross Sections/Attributes` | XS attributes including Manning's n | `hdf['Geometry/Cross Sections/Attributes'][:]` |
| `/Geometry/Cross Sections/Manning's n Values` | n values by station | Dataset with LOB, Channel, ROB values |
| `/Geometry/Cross Sections/Contraction Expansion` | C/E coefficients | Contraction and expansion values |
| `/Geometry/Structures/` | Structure section numbers | Identifies sections 2, 3, 4 |

### Data Structure - Manning's n

The geometry HDF stores Manning's n in the following structure:
```
/Geometry/Cross Sections/
    Attributes                    # River, Reach, Station identifiers
    Station Elevation Info/
        Station Elevation Values  # Station-elevation pairs per XS
    Manning's n Info/
        Manning's n Values        # n values (may be station-based or simple LOB/CH/ROB)
```

For horizontal variation in n:
- Multiple n values per XS (station-based)
- Each n value has a starting station

For simple n (most common):
- Three values: Left Overbank, Channel, Right Overbank

### Data Structure - Transition Coefficients

```
/Geometry/Cross Sections/
    Contraction Expansion/
        Values                    # [contraction, expansion] per XS
```

## Validation Rules

### 1. Overbank Manning's n Values

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| NT_RC_01L | n_lob < 0.030 | WARNING | Left overbank n value {n} is less than 0.030 |
| NT_RC_01R | n_rob < 0.030 | WARNING | Right overbank n value {n} is less than 0.030 |
| NT_RC_02L | n_lob > 0.200 | WARNING | Left overbank n value {n} exceeds 0.200 |
| NT_RC_02R | n_rob > 0.200 | WARNING | Right overbank n value {n} exceeds 0.200 |

### 2. Channel Manning's n Values

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| NT_RC_03C | n_chl < 0.025 | WARNING | Channel n value {n} is less than 0.025 |
| NT_RC_04C | n_chl > 0.100 | WARNING | Channel n value {n} exceeds 0.100 |
| NT_RC_05 | n_lob <= n_chl AND n_rob <= n_chl | WARNING | Overbank n values should exceed channel n |

### 3. Transition Coefficients at Structures (Sections 2, 3, 4)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| NT_TL_01S2 | Section 2: cc != 0.3 OR ce != 0.5 | WARNING | Section 2 of structure: Transition coefficients should be 0.3/0.5 |
| NT_TL_01S3 | Section 3: cc != 0.3 OR ce != 0.5 | WARNING | Section 3 of structure: Transition coefficients should be 0.3/0.5 |
| NT_TL_01S4 | Section 4: cc != 0.3 OR ce != 0.5 | WARNING | Section 4 of structure: Transition coefficients should be 0.3/0.5 |

### 4. Transition Coefficients at Regular Cross Sections

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| NT_TL_02 | cc != 0.1 OR ce != 0.3 | INFO | Transition coefficients at XS {station} are {cc}/{ce}, typical values are 0.1/0.3 |

### 5. Manning's n at Bridge Sections

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| NT_RS_01S2C | n_s1 > n_s2 by more than 0.005 | WARNING | Channel n at Section 2 ({n_s2}) should be less than Section 1 ({n_s1}) |
| NT_RS_01S3C | n_s4 > n_s3 by more than 0.005 | WARNING | Channel n at Section 3 ({n_s3}) should be less than Section 4 ({n_s4}) |
| NT_RS_02BUC | n_bridge_up >= n_s3 | WARNING | Bridge upstream internal n ({n_bu}) should be less than Section 3 n ({n_s3}) |
| NT_RS_02BDC | n_bridge_dn >= n_s2 | WARNING | Bridge downstream internal n ({n_bd}) should be less than Section 2 n ({n_s2}) |

## Implementation

```python
"""
NT Check - Manning's n and Transition Loss Coefficient Validation

This module validates Manning's roughness coefficients and transition
loss coefficients in HEC-RAS steady flow models.
"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np
import h5py

from ..RasCheck import CheckResults, CheckMessage, Severity
from .messages import get_message_template
from .thresholds import (
    N_LOB_MIN, N_LOB_MAX, N_ROB_MIN, N_ROB_MAX,
    N_CHL_MIN, N_CHL_MAX,
    CC_STRUCTURE, CE_STRUCTURE,
    CC_REGULAR, CE_REGULAR,
    N_BRIDGE_DELTA
)
from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


@log_call
def run_nt_check(plan_hdf: Path, geom_hdf: Path) -> CheckResults:
    """
    Run all NT (Manning's n and Transition) checks.

    Args:
        plan_hdf: Path to plan HDF file
        geom_hdf: Path to geometry HDF file

    Returns:
        CheckResults containing NT check messages and summary
    """
    results = CheckResults()
    messages = []

    # Extract data from geometry HDF
    nt_data = extract_nt_data(geom_hdf)

    if nt_data.empty:
        logger.warning("No NT data extracted from geometry HDF")
        return results

    # Build summary DataFrame
    results.nt_summary = build_nt_summary(nt_data)

    # Calculate statistics for summary table
    stats = calculate_nt_statistics(nt_data)
    results.statistics['nt_stats'] = stats

    # Run validation checks
    messages.extend(check_overbank_n_values(nt_data))
    messages.extend(check_channel_n_values(nt_data))
    messages.extend(check_transition_coefficients(nt_data))
    messages.extend(check_structure_n_values(nt_data, geom_hdf))

    results.messages = messages
    return results


def extract_nt_data(geom_hdf: Path) -> pd.DataFrame:
    """
    Extract Manning's n and transition coefficient data from geometry HDF.

    Returns DataFrame with columns:
        river, reach, station, structure, section_num,
        n_lob, n_chl, n_rob, cc, ce
    """
    records = []

    try:
        with h5py.File(geom_hdf, 'r') as hdf:
            # Get cross section attributes
            xs_attrs_path = 'Geometry/Cross Sections/Attributes'
            if xs_attrs_path not in hdf:
                logger.warning(f"Path not found: {xs_attrs_path}")
                return pd.DataFrame()

            xs_attrs = hdf[xs_attrs_path][:]

            # Get Manning's n values
            n_values = _extract_mannings_n(hdf)

            # Get contraction/expansion coefficients
            ce_values = _extract_contraction_expansion(hdf)

            # Get structure section information
            section_map = _build_section_map(hdf)

            # Build records
            for i, attr in enumerate(xs_attrs):
                river = _decode_bytes(attr['River'])
                reach = _decode_bytes(attr['Reach'])
                station = float(attr['RS'])

                # Get structure and section info
                key = (river, reach, station)
                structure = section_map.get(key, {}).get('structure', '')
                section_num = section_map.get(key, {}).get('section', -99)

                # Get n values for this XS
                n_lob, n_chl, n_rob = n_values.get(i, (-9999, -9999, -9999))

                # Get C/E coefficients
                cc, ce = ce_values.get(i, (-9999, -9999))

                records.append({
                    'river': river,
                    'reach': reach,
                    'station': station,
                    'structure': structure,
                    'section_num': section_num,
                    'n_lob': n_lob,
                    'n_chl': n_chl,
                    'n_rob': n_rob,
                    'cc': cc,
                    'ce': ce
                })

    except Exception as e:
        logger.error(f"Error extracting NT data: {e}")
        return pd.DataFrame()

    return pd.DataFrame(records)


def _extract_mannings_n(hdf: h5py.File) -> Dict[int, Tuple[float, float, float]]:
    """Extract Manning's n values indexed by XS index."""
    n_values = {}

    # Try different possible paths
    paths_to_try = [
        'Geometry/Cross Sections/Manning n Values',
        'Geometry/Cross Sections/Manning\'s n Values',
        'Geometry/Cross Sections/Manning n Info/Values'
    ]

    for path in paths_to_try:
        if path in hdf:
            data = hdf[path][:]
            # Data format: each row is [n_lob, n_chl, n_rob] or similar
            for i, row in enumerate(data):
                if len(row) >= 3:
                    n_values[i] = (float(row[0]), float(row[1]), float(row[2]))
                elif len(row) == 1:
                    # Single n value (composite)
                    n_values[i] = (float(row[0]), float(row[0]), float(row[0]))
            break

    return n_values


def _extract_contraction_expansion(hdf: h5py.File) -> Dict[int, Tuple[float, float]]:
    """Extract contraction/expansion coefficients indexed by XS index."""
    ce_values = {}

    paths_to_try = [
        'Geometry/Cross Sections/Contraction Expansion',
        'Geometry/Cross Sections/Contraction Expansion Values'
    ]

    for path in paths_to_try:
        if path in hdf:
            data = hdf[path][:]
            for i, row in enumerate(data):
                if len(row) >= 2:
                    ce_values[i] = (float(row[0]), float(row[1]))
            break

    return ce_values


def _build_section_map(hdf: h5py.File) -> Dict:
    """
    Build mapping of (river, reach, station) to structure/section info.

    Returns dict with keys (river, reach, station) and values
    {'structure': str, 'section': int}
    """
    section_map = {}

    # Look for structure cross sections in geometry
    struct_path = 'Geometry/Structures'
    if struct_path not in hdf:
        return section_map

    # This will need to parse the structure data to identify
    # which XS are sections 1, 2, 3, 4 of each structure
    # Implementation depends on HDF structure

    return section_map


def _decode_bytes(value) -> str:
    """Decode bytes to string if needed."""
    if isinstance(value, bytes):
        return value.decode('utf-8').strip()
    return str(value).strip()


def build_nt_summary(nt_data: pd.DataFrame) -> pd.DataFrame:
    """Build summary table for NT check report."""
    summary = nt_data[[
        'river', 'reach', 'station', 'structure',
        'n_lob', 'n_chl', 'n_rob', 'cc', 'ce'
    ]].copy()

    # Replace -9999 with NaN for display
    summary = summary.replace(-9999, np.nan)

    return summary


def calculate_nt_statistics(nt_data: pd.DataFrame) -> Dict:
    """Calculate min/max statistics for n values and coefficients."""
    valid_data = nt_data.replace(-9999, np.nan)

    return {
        'n_lob_min': valid_data['n_lob'].min(),
        'n_lob_max': valid_data['n_lob'].max(),
        'n_chl_min': valid_data['n_chl'].min(),
        'n_chl_max': valid_data['n_chl'].max(),
        'n_rob_min': valid_data['n_rob'].min(),
        'n_rob_max': valid_data['n_rob'].max(),
        'cc_min': valid_data['cc'].min(),
        'cc_max': valid_data['cc'].max(),
        'ce_min': valid_data['ce'].min(),
        'ce_max': valid_data['ce'].max()
    }


def check_overbank_n_values(nt_data: pd.DataFrame) -> List[CheckMessage]:
    """Check left and right overbank Manning's n values."""
    messages = []

    for _, row in nt_data.iterrows():
        n_lob = row['n_lob']
        n_rob = row['n_rob']

        if n_lob != -9999:
            if round(n_lob, 3) < N_LOB_MIN:
                msg = CheckMessage(
                    message_id="NT_RC_01L",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_RC_01L").format(n=n_lob)
                )
                messages.append(msg)

            if round(n_lob, 2) > N_LOB_MAX:
                msg = CheckMessage(
                    message_id="NT_RC_02L",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_RC_02L").format(n=n_lob)
                )
                messages.append(msg)

        if n_rob != -9999:
            if round(n_rob, 3) < N_ROB_MIN:
                msg = CheckMessage(
                    message_id="NT_RC_01R",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_RC_01R").format(n=n_rob)
                )
                messages.append(msg)

            if round(n_rob, 2) > N_ROB_MAX:
                msg = CheckMessage(
                    message_id="NT_RC_02R",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_RC_02R").format(n=n_rob)
                )
                messages.append(msg)

    return messages


def check_channel_n_values(nt_data: pd.DataFrame) -> List[CheckMessage]:
    """Check channel Manning's n values."""
    messages = []

    for _, row in nt_data.iterrows():
        n_chl = row['n_chl']
        n_lob = row['n_lob']
        n_rob = row['n_rob']

        if n_chl != -9999:
            if round(n_chl, 3) < N_CHL_MIN:
                msg = CheckMessage(
                    message_id="NT_RC_03C",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_RC_03C").format(n=n_chl)
                )
                messages.append(msg)

            if round(n_chl, 2) > N_CHL_MAX:
                msg = CheckMessage(
                    message_id="NT_RC_04C",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_RC_04C").format(n=n_chl)
                )
                messages.append(msg)

            # Check overbank vs channel comparison
            if (n_lob != -9999 and n_rob != -9999 and
                n_lob <= n_chl and n_rob <= n_chl):
                msg = CheckMessage(
                    message_id="NT_RC_05",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_RC_05").format(
                        n_lob=n_lob, n_rob=n_rob, n_chl=n_chl
                    )
                )
                messages.append(msg)

    return messages


def check_transition_coefficients(nt_data: pd.DataFrame) -> List[CheckMessage]:
    """Check transition loss coefficients at XS and structures."""
    messages = []

    for _, row in nt_data.iterrows():
        cc = row['cc']
        ce = row['ce']
        section_num = row['section_num']

        if cc == -9999 or ce == -9999:
            continue

        # Structure sections (2, 3, 4) should have 0.3/0.5
        if section_num == 2:
            if round(cc, 2) != CC_STRUCTURE or round(ce, 2) != CE_STRUCTURE:
                msg = CheckMessage(
                    message_id="NT_TL_01S2",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_TL_01S2").format(cc=cc, ce=ce)
                )
                messages.append(msg)

        elif section_num == 3:
            if round(cc, 2) != CC_STRUCTURE or round(ce, 2) != CE_STRUCTURE:
                msg = CheckMessage(
                    message_id="NT_TL_01S3",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_TL_01S3").format(cc=cc, ce=ce)
                )
                messages.append(msg)

        elif section_num == 4:
            if round(cc, 2) != CC_STRUCTURE or round(ce, 2) != CE_STRUCTURE:
                msg = CheckMessage(
                    message_id="NT_TL_01S4",
                    severity=Severity.WARNING,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_TL_01S4").format(cc=cc, ce=ce)
                )
                messages.append(msg)

        # Regular XS (not at structure) - typical values 0.1/0.3
        elif section_num == -99:  # Not at structure
            if round(cc, 2) != CC_REGULAR or round(ce, 2) != CE_REGULAR:
                msg = CheckMessage(
                    message_id="NT_TL_02",
                    severity=Severity.INFO,
                    check_type="NT",
                    river=row['river'],
                    reach=row['reach'],
                    station=str(row['station']),
                    structure=row['structure'],
                    message=get_message_template("NT_TL_02").format(
                        station=row['station'], cc=cc, ce=ce
                    )
                )
                messages.append(msg)

    return messages


def check_structure_n_values(nt_data: pd.DataFrame, geom_hdf: Path) -> List[CheckMessage]:
    """
    Check Manning's n relationships at bridge/culvert structures.

    Validates that:
    - Channel n at Section 2 < Section 1 (by at least 0.005)
    - Channel n at Section 3 < Section 4 (by at least 0.005)
    - Bridge internal n values < adjacent section n values
    """
    messages = []

    # Group data by structure
    structures = nt_data[nt_data['structure'] != ''].groupby(
        ['river', 'reach', 'station', 'structure']
    )

    for (river, reach, station, structure), group in structures:
        # Get section data
        sections = {}
        for _, row in group.iterrows():
            sec = row['section_num']
            if sec > 0:
                sections[sec] = row

        # Check Section 1 vs Section 2
        if 1 in sections and 2 in sections:
            n1 = sections[1]['n_chl']
            n2 = sections[2]['n_chl']
            if n1 != -9999 and n2 != -9999:
                if n1 > n2 and (n1 - n2) > N_BRIDGE_DELTA:
                    msg = CheckMessage(
                        message_id="NT_RS_01S2C",
                        severity=Severity.WARNING,
                        check_type="NT",
                        river=river,
                        reach=reach,
                        station=str(sections[2]['station']),
                        structure=structure,
                        message=get_message_template("NT_RS_01S2C").format(
                            n_s2=n2, n_s1=n1
                        )
                    )
                    messages.append(msg)

        # Check Section 3 vs Section 4
        if 3 in sections and 4 in sections:
            n3 = sections[3]['n_chl']
            n4 = sections[4]['n_chl']
            if n3 != -9999 and n4 != -9999:
                if n4 > n3 and (n4 - n3) > N_BRIDGE_DELTA:
                    msg = CheckMessage(
                        message_id="NT_RS_01S3C",
                        severity=Severity.WARNING,
                        check_type="NT",
                        river=river,
                        reach=reach,
                        station=str(sections[3]['station']),
                        structure=structure,
                        message=get_message_template("NT_RS_01S3C").format(
                            n_s3=n3, n_s4=n4
                        )
                    )
                    messages.append(msg)

    # Additional check for bridge internal sections
    # (Bridge-UP and Bridge-DN internal sections)
    # This requires parsing bridge-specific data from HDF

    return messages
```

## HDF Path Reference

Based on HEC-RAS 6.x HDF structure:

```
/Geometry/
  Cross Sections/
    Attributes                          # dtype: compound with River, Reach, RS, etc.
    Station Elevation Info/
      Counts                            # Number of points per XS
      Values                            # Flattened station-elevation pairs
    Manning n Info/
      Counts                            # Number of n values per XS
      Values                            # n values (horizontal variation or simple)
    Bank Stations                       # Left and right bank stations
    Contraction Expansion               # [contraction, expansion] per XS
    Reach Lengths                       # LOB, Channel, ROB reach lengths
  Structures/
    Centerline Info/
      Points                            # Structure geometry
    Attributes                          # Structure attributes
```

## Testing Requirements

### Unit Tests

1. **test_extract_mannings_n**: Verify n value extraction from various HDF formats
2. **test_extract_transition_coeff**: Verify C/E coefficient extraction
3. **test_check_overbank_n**: Test all overbank n validation rules
4. **test_check_channel_n**: Test all channel n validation rules
5. **test_check_transition_at_structure**: Test structure transition coefficient rules
6. **test_check_transition_at_xs**: Test regular XS transition rules
7. **test_structure_n_relationships**: Test bridge section n comparisons

### Integration Tests

1. Test with Muncie example project
2. Test with Bald Eagle Creek example (structures)
3. Test with project having horizontal variation in n
4. Test with project having no structures

## Dependencies

- `h5py`: HDF file access
- `pandas`: DataFrame operations
- `numpy`: Numerical operations
- Parent module: `RasCheck`, `CheckResults`, `CheckMessage`, `Severity`
- Sibling modules: `messages`, `thresholds`
