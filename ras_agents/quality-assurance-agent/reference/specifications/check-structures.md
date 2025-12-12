# Structure Check Implementation Plan

## Overview

The Structure Check validates bridge, culvert, and inline weir data including section distances, flow types, coefficients, ineffective flow areas at structures, and deck/roadway configurations.

## Module Location

```
ras_commander/check/struct_check.py
```

## Data Sources

### From Plan HDF (`.p##.hdf`)

| HDF Path | Data | Description |
|----------|------|-------------|
| `Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Structures/` | Structure results | WSE, flow type, velocities |
| `Plan Data/Plan Parameters/Friction Slope Method` | Friction slope method | Method selection |

### From Geometry HDF (`.g##.hdf`)

| HDF Path | Data | Description |
|----------|------|-------------|
| `Geometry/Structures/Attributes` | Structure list | Type, name, river, reach, station |
| `Geometry/Structures/Bridge Data/` | Bridge geometry | Deck/roadway, piers, abutments |
| `Geometry/Structures/Culvert Data/` | Culvert geometry | Shape, dimensions, coefficients |
| `Geometry/Structures/Inline Weir Data/` | Weir geometry | Crest, gates |
| `Geometry/Cross Sections/` | XS at structures | Sections 1, 2, 3, 4 |

## Structure Section Numbering

HEC-RAS uses a 4-section model for bridges and culverts:

```
Flow Direction --->

Section 1 (Upstream XS)
    |
    | Distance from upstream
    v
Section 2 (Upstream structure face / Bridge-UP)
    |
    | Structure internal
    |
Section 3 (Downstream structure face / Bridge-DN)
    |
    | Distance to downstream
    v
Section 4 (Downstream XS)
```

## Validation Rules

### 1. Section Distance Checks - Bridges (BR SD)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| BR_SD_01 | Distance from Sec 1 to Sec 2 < calculated minimum | WARNING | Distance from upstream XS to bridge is less than recommended |
| BR_SD_02 | Deck width < (Sec 2 - Sec 3 distance) | WARNING | Deck/roadway width inconsistent with section distances |
| BR_SD_03 | Distance from Sec 3 to Sec 4 < calculated minimum | WARNING | Distance from bridge to downstream XS is less than recommended |

### 2. Section Distance Checks - Culverts (CU SD)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| CU_SD_01 | Distance from Sec 1 to culvert < minimum | WARNING | Distance from upstream XS to culvert is less than recommended |
| CU_SD_02 | Distance from culvert to Sec 4 < minimum | WARNING | Distance from culvert to downstream XS is less than recommended |

### 3. Section Distance Checks - Inline Weirs (IW SD)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| IW_SD_01 | Distance from Sec 1 to weir < minimum | WARNING | Distance from upstream XS to inline weir is less than recommended |
| IW_SD_02 | Distance from weir to Sec 4 < minimum | WARNING | Distance from inline weir to downstream XS is less than recommended |

### 4. Bridge Flow Type Checks (BR PF)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| BR_PF_01 | Pressure flow computed | WARNING | Pressure flow computed at bridge for {profile} |
| BR_PF_02 | Weir flow computed | WARNING | Weir flow computed at bridge for {profile} |
| BR_PF_03 | Low flow OR pressure OR weir for highest frequency profile | INFO | Bridge flow type = {type} for {profile} |

### 5. Bridge Pressure/Weir Checks (BR PW)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| BR_PW_01 | Pressure flow: check sluice gate coefficients | INFO | Pressure flow uses sluice gate coefficients (Cd = {cd}) |
| BR_PW_02 | High flow method != Energy (momentum) | INFO | High flow method is not Energy-based |
| BR_PW_03 | Weir coefficient outside typical range | WARNING | Weir coefficient {c} is outside typical range (2.5-3.1) |
| BR_PW_04 | Maximum submergence for weir flow | INFO | Maximum submergence for weir flow = {sub} |

### 6. Culvert Flow Checks (CU)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| CU_01 | Entrance loss coefficient outside typical range | WARNING | Entrance loss coefficient {Ke} outside typical range |
| CU_02 | Exit loss coefficient not 1.0 | INFO | Exit loss coefficient is {Kx}, typical value is 1.0 |
| CU_03 | Scale < 1.0 | WARNING | Culvert scale factor {scale} is less than 1.0 |
| CU_04 | Chart/Scale method inconsistent | INFO | Chart {chart}, Scale {scale}, Criteria {criteria} |
| CU_05 | Inlet control with submerged inlet | WARNING | Inlet control with submerged inlet for {profile} |

### 7. Inline Weir Checks (IW)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| IW_01 | Gate flow exceeds weir flow | INFO | Gate flow ({qgate}) exceeds weir flow ({qweir}) for {profile} |
| IW_02 | Gate height validation | INFO | Gate opening height = {height} for {profile} |
| IW_03 | Weir coefficient outside typical range | WARNING | Weir coefficient {c} outside typical range |

### 8. Structure Geometry Checks (ST GE)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| ST_GE_01L | Left effective station at Section 2 != roadway station | WARNING | Left effective station at Sec 2 doesn't align with road |
| ST_GE_01R | Right effective station at Section 2 != roadway station | WARNING | Right effective station at Sec 2 doesn't align with road |
| ST_GE_02L | Left effective station at Section 3 != roadway station | WARNING | Left effective station at Sec 3 doesn't align with road |
| ST_GE_02R | Right effective station at Section 3 != roadway station | WARNING | Right effective station at Sec 3 doesn't align with road |
| ST_GE_03 | Ground/roadway stations differ significantly | WARNING | Ground and roadway end stations differ by more than 10 ft |

### 9. Structure Ineffective Flow Checks (ST IF)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| ST_IF_01 | No ineffective flow at Section 2 | WARNING | No ineffective flow areas defined at Section 2 |
| ST_IF_02 | No ineffective flow at Section 3 | WARNING | No ineffective flow areas defined at Section 3 |
| ST_IF_03L | Left ineffective doesn't extend to abutment at Sec 2 | WARNING | Left ineffective flow should extend to abutment |
| ST_IF_03R | Right ineffective doesn't extend to abutment at Sec 2 | WARNING | Right ineffective flow should extend to abutment |
| ST_IF_04L | Left ineffective doesn't extend to abutment at Sec 3 | WARNING | Left ineffective flow should extend to abutment |
| ST_IF_04R | Right ineffective doesn't extend to abutment at Sec 3 | WARNING | Right ineffective flow should extend to abutment |
| ST_IF_05 | Permanent ineffective in floodway | WARNING | Permanent ineffective flow may affect floodway analysis |

### 10. Multiple Structure Checks (ST MS)

| Check ID | Condition | Severity | Message |
|----------|-----------|----------|---------|
| ST_MS_01 | Multiple structures at same river station | INFO | Multiple structures at RS {station} |
| ST_MS_02 | Different structure types at same location | INFO | Mixed structure types (bridge and culvert) at RS {station} |

## Implementation

```python
"""
Structure Check - Bridge, Culvert, and Inline Weir Validation

This module validates hydraulic structures in HEC-RAS models.
"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
import h5py

from ..RasCheck import CheckResults, CheckMessage, Severity
from .messages import get_message_template
from .thresholds import (
    WEIR_COEFF_MIN, WEIR_COEFF_MAX,
    ENTRANCE_LOSS_MIN, ENTRANCE_LOSS_MAX,
    EXIT_LOSS_TYPICAL,
    MIN_STRUCTURE_DISTANCE
)
from ..Decorators import log_call
from ..LoggingConfig import get_logger

logger = get_logger(__name__)


@dataclass
class StructureData:
    """Container for structure geometry data."""
    river: str
    reach: str
    station: float
    name: str
    structure_type: str  # Bridge, Culvert, InlineWeir, MultiOpen

    # Section stations (1-4)
    section_1_rs: float = -9999
    section_2_rs: float = -9999
    section_3_rs: float = -9999
    section_4_rs: float = -9999

    # Distances
    dist_upstream: float = -9999  # Sec 1 to Sec 2
    deck_width: float = -9999     # Sec 2 to Sec 3
    dist_downstream: float = -9999  # Sec 3 to Sec 4

    # Bridge data
    weir_coeff: float = -9999
    max_submergence: float = -9999
    min_low_chord: float = -9999
    high_flow_method: int = -9999
    low_flow_method: int = -9999
    friction_component: bool = False
    weight_component: bool = False
    pressure_flow_component: bool = False

    # Culvert data
    entrance_loss_coeff: float = -9999
    exit_loss_coeff: float = -9999
    chart: float = -9999
    scale: float = -9999
    criteria: float = -9999
    shape: str = ""
    n_value: float = -9999

    # Inline weir data
    weir_width: float = -9999


@dataclass
class StructureResults:
    """Container for structure results per profile."""
    river: str
    reach: str
    station: float
    structure: str
    profile: str

    wse_1: float = -9999  # Section 1 WSE
    wse_2: float = -9999  # Section 2 WSE
    wse_3: float = -9999  # Section 3 WSE
    wse_4: float = -9999  # Section 4 WSE
    ege_1: float = -9999  # Section 1 EGL
    ege_2: float = -9999  # Section 2 EGL
    ege_3: float = -9999  # Section 3 EGL
    ege_4: float = -9999  # Section 4 EGL

    flow_type: str = ""
    q_total: float = -9999
    q_weir: float = -9999
    q_gate: float = -9999
    q_culvert: float = -9999

    opening_area: float = -9999
    opening_velocity: float = -9999

    # Culvert specific
    inlet_control: bool = False
    culvert_wse_in: float = -9999
    culvert_wse_out: float = -9999


@log_call
def run_struct_check(
    plan_hdf: Path,
    geom_hdf: Path,
    profiles: List[str]
) -> CheckResults:
    """
    Run all structure validation checks.

    Args:
        plan_hdf: Path to plan HDF file
        geom_hdf: Path to geometry HDF file
        profiles: List of profile names to check

    Returns:
        CheckResults containing structure check messages and summary
    """
    results = CheckResults()
    messages = []

    # Extract structure geometry
    structures = extract_structure_geometry(geom_hdf)
    if not structures:
        logger.info("No structures found in geometry")
        return results

    # Extract structure results for each profile
    struct_results = extract_structure_results(plan_hdf, profiles)

    # Extract section information
    section_data = extract_section_data(geom_hdf)

    # Extract ineffective flow data at structure sections
    ineff_data = extract_structure_ineffective(geom_hdf)

    # Run validation checks
    for struct in structures:
        messages.extend(check_section_distances(struct))
        messages.extend(check_bridge_coefficients(struct))
        messages.extend(check_culvert_coefficients(struct))
        messages.extend(check_inline_weir(struct))
        messages.extend(check_structure_geometry(struct, section_data))
        messages.extend(check_structure_ineffective(struct, ineff_data))

    # Check flow types for each profile
    for profile in profiles:
        if profile in struct_results:
            for result in struct_results[profile]:
                messages.extend(check_flow_type(result, profile))

    # Check for multiple structures
    messages.extend(check_multiple_structures(structures))

    # Build summary DataFrame
    results.struct_summary = build_struct_summary(structures, struct_results, profiles)
    results.messages = messages

    return results


def extract_structure_geometry(geom_hdf: Path) -> List[StructureData]:
    """Extract structure geometry from HDF file."""
    structures = []

    try:
        with h5py.File(geom_hdf, 'r') as hdf:
            # Get structure attributes
            attrs_path = 'Geometry/Structures/Attributes'
            if attrs_path not in hdf:
                return structures

            attrs = hdf[attrs_path][:]

            for attr in attrs:
                struct = StructureData(
                    river=_decode_bytes(attr['River']),
                    reach=_decode_bytes(attr['Reach']),
                    station=float(attr['RS']),
                    name=_decode_bytes(attr.get('Name', '')),
                    structure_type=_decode_bytes(attr.get('Type', ''))
                )

                # Get structure-specific data based on type
                if 'Bridge' in struct.structure_type:
                    _extract_bridge_data(hdf, struct)
                elif 'Culvert' in struct.structure_type:
                    _extract_culvert_data(hdf, struct)
                elif 'InlineWeir' in struct.structure_type:
                    _extract_inline_weir_data(hdf, struct)

                structures.append(struct)

    except Exception as e:
        logger.error(f"Error extracting structure geometry: {e}")

    return structures


def _extract_bridge_data(hdf: h5py.File, struct: StructureData):
    """Extract bridge-specific data."""
    base_path = f'Geometry/Structures/Bridge Data'

    # Look for deck/roadway data
    deck_path = f'{base_path}/Deck Roadway'
    if deck_path in hdf:
        deck_data = hdf[deck_path][:]
        # Find data for this structure
        # Structure matching by river/reach/station
        pass

    # Get bridge coefficients
    # High flow method, low flow method, weir coefficient, etc.


def _extract_culvert_data(hdf: h5py.File, struct: StructureData):
    """Extract culvert-specific data."""
    base_path = 'Geometry/Structures/Culvert Data'

    if base_path in hdf:
        # Get culvert dimensions and coefficients
        pass


def _extract_inline_weir_data(hdf: h5py.File, struct: StructureData):
    """Extract inline weir-specific data."""
    base_path = 'Geometry/Structures/Inline Weir Data'

    if base_path in hdf:
        # Get weir dimensions and coefficients
        pass


def extract_structure_results(
    plan_hdf: Path,
    profiles: List[str]
) -> Dict[str, List[StructureResults]]:
    """Extract structure results for each profile."""
    results = {}

    try:
        with h5py.File(plan_hdf, 'r') as hdf:
            base_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles'

            for profile in profiles:
                profile_results = []

                # Get structure output
                # WSE at sections, flow type, etc.

                results[profile] = profile_results

    except Exception as e:
        logger.error(f"Error extracting structure results: {e}")

    return results


def extract_section_data(geom_hdf: Path) -> Dict:
    """Extract cross section data at structure sections (1-4)."""
    section_data = {}

    # Get XS attributes with section number information
    # Map (river, reach, station) to section number

    return section_data


def extract_structure_ineffective(geom_hdf: Path) -> Dict:
    """Extract ineffective flow areas at structure sections."""
    ineff_data = {}

    # Get ineffective flow areas for sections 2 and 3
    # Including abutment stations

    return ineff_data


def check_section_distances(struct: StructureData) -> List[CheckMessage]:
    """Check structure section distances."""
    messages = []

    if struct.structure_type == '' or struct.dist_upstream == -9999:
        return messages

    # Bridge distance checks
    if 'Bridge' in struct.structure_type:
        # Check upstream distance
        if struct.dist_upstream != -9999 and struct.dist_upstream < MIN_STRUCTURE_DISTANCE:
            messages.append(CheckMessage(
                message_id="BR_SD_01",
                severity=Severity.WARNING,
                check_type="STRUCT",
                river=struct.river,
                reach=struct.reach,
                station=str(struct.station),
                structure=struct.name,
                message=get_message_template("BR_SD_01").format(
                    dist=struct.dist_upstream
                )
            ))

        # Check downstream distance
        if struct.dist_downstream != -9999 and struct.dist_downstream < MIN_STRUCTURE_DISTANCE:
            messages.append(CheckMessage(
                message_id="BR_SD_03",
                severity=Severity.WARNING,
                check_type="STRUCT",
                river=struct.river,
                reach=struct.reach,
                station=str(struct.station),
                structure=struct.name,
                message=get_message_template("BR_SD_03").format(
                    dist=struct.dist_downstream
                )
            ))

    # Culvert distance checks
    elif 'Culvert' in struct.structure_type:
        if struct.dist_upstream != -9999 and struct.dist_upstream < MIN_STRUCTURE_DISTANCE:
            messages.append(CheckMessage(
                message_id="CU_SD_01",
                severity=Severity.WARNING,
                check_type="STRUCT",
                river=struct.river,
                reach=struct.reach,
                station=str(struct.station),
                structure=struct.name,
                message=get_message_template("CU_SD_01").format(
                    dist=struct.dist_upstream
                )
            ))

    # Inline weir distance checks
    elif 'InlineWeir' in struct.structure_type:
        if struct.dist_upstream != -9999 and struct.dist_upstream < MIN_STRUCTURE_DISTANCE:
            messages.append(CheckMessage(
                message_id="IW_SD_01",
                severity=Severity.WARNING,
                check_type="STRUCT",
                river=struct.river,
                reach=struct.reach,
                station=str(struct.station),
                structure=struct.name,
                message=get_message_template("IW_SD_01").format(
                    dist=struct.dist_upstream
                )
            ))

    return messages


def check_bridge_coefficients(struct: StructureData) -> List[CheckMessage]:
    """Check bridge coefficient values."""
    messages = []

    if 'Bridge' not in struct.structure_type:
        return messages

    # Check weir coefficient
    if struct.weir_coeff != -9999:
        if struct.weir_coeff < WEIR_COEFF_MIN or struct.weir_coeff > WEIR_COEFF_MAX:
            messages.append(CheckMessage(
                message_id="BR_PW_03",
                severity=Severity.WARNING,
                check_type="STRUCT",
                river=struct.river,
                reach=struct.reach,
                station=str(struct.station),
                structure=struct.name,
                message=get_message_template("BR_PW_03").format(
                    c=struct.weir_coeff
                )
            ))

    # Check high flow method
    if struct.high_flow_method != -9999 and struct.high_flow_method != 1:
        # 1 = Energy method
        messages.append(CheckMessage(
            message_id="BR_PW_02",
            severity=Severity.INFO,
            check_type="STRUCT",
            river=struct.river,
            reach=struct.reach,
            station=str(struct.station),
            structure=struct.name,
            message=get_message_template("BR_PW_02")
        ))

    return messages


def check_culvert_coefficients(struct: StructureData) -> List[CheckMessage]:
    """Check culvert coefficient values."""
    messages = []

    if 'Culvert' not in struct.structure_type:
        return messages

    # Check entrance loss coefficient
    if struct.entrance_loss_coeff != -9999:
        if (struct.entrance_loss_coeff < ENTRANCE_LOSS_MIN or
            struct.entrance_loss_coeff > ENTRANCE_LOSS_MAX):
            messages.append(CheckMessage(
                message_id="CU_01",
                severity=Severity.WARNING,
                check_type="STRUCT",
                river=struct.river,
                reach=struct.reach,
                station=str(struct.station),
                structure=struct.name,
                message=get_message_template("CU_01").format(
                    Ke=struct.entrance_loss_coeff
                )
            ))

    # Check exit loss coefficient
    if struct.exit_loss_coeff != -9999 and struct.exit_loss_coeff != EXIT_LOSS_TYPICAL:
        messages.append(CheckMessage(
            message_id="CU_02",
            severity=Severity.INFO,
            check_type="STRUCT",
            river=struct.river,
            reach=struct.reach,
            station=str(struct.station),
            structure=struct.name,
            message=get_message_template("CU_02").format(
                Kx=struct.exit_loss_coeff
            )
        ))

    # Check scale factor
    if struct.scale != -9999 and struct.scale < 1.0:
        messages.append(CheckMessage(
            message_id="CU_03",
            severity=Severity.WARNING,
            check_type="STRUCT",
            river=struct.river,
            reach=struct.reach,
            station=str(struct.station),
            structure=struct.name,
            message=get_message_template("CU_03").format(
                scale=struct.scale
            )
        ))

    return messages


def check_inline_weir(struct: StructureData) -> List[CheckMessage]:
    """Check inline weir configuration."""
    messages = []

    if 'InlineWeir' not in struct.structure_type:
        return messages

    # Check weir coefficient
    if struct.weir_coeff != -9999:
        if struct.weir_coeff < WEIR_COEFF_MIN or struct.weir_coeff > WEIR_COEFF_MAX:
            messages.append(CheckMessage(
                message_id="IW_03",
                severity=Severity.WARNING,
                check_type="STRUCT",
                river=struct.river,
                reach=struct.reach,
                station=str(struct.station),
                structure=struct.name,
                message=get_message_template("IW_03").format(
                    c=struct.weir_coeff
                )
            ))

    return messages


def check_flow_type(result: StructureResults, profile: str) -> List[CheckMessage]:
    """Check flow type at structure for a profile."""
    messages = []

    if result.flow_type == '':
        return messages

    # Check for pressure flow
    if 'Pressure' in result.flow_type:
        messages.append(CheckMessage(
            message_id="BR_PF_01",
            severity=Severity.WARNING,
            check_type="STRUCT",
            river=result.river,
            reach=result.reach,
            station=str(result.station),
            structure=result.structure,
            message=get_message_template("BR_PF_01").format(profile=profile)
        ))

    # Check for weir flow
    if 'Weir' in result.flow_type:
        messages.append(CheckMessage(
            message_id="BR_PF_02",
            severity=Severity.WARNING,
            check_type="STRUCT",
            river=result.river,
            reach=result.reach,
            station=str(result.station),
            structure=result.structure,
            message=get_message_template("BR_PF_02").format(profile=profile)
        ))

    return messages


def check_structure_geometry(struct: StructureData, section_data: Dict) -> List[CheckMessage]:
    """Check structure geometry alignment."""
    messages = []

    # Check effective station alignment with roadway
    # Check ground/roadway station consistency

    return messages


def check_structure_ineffective(struct: StructureData, ineff_data: Dict) -> List[CheckMessage]:
    """Check ineffective flow areas at structure sections."""
    messages = []

    # Check for missing ineffective at Section 2
    # Check for missing ineffective at Section 3
    # Check abutment alignment

    return messages


def check_multiple_structures(structures: List[StructureData]) -> List[CheckMessage]:
    """Check for multiple structures at same location."""
    messages = []

    # Group by river, reach, station
    location_groups = {}
    for struct in structures:
        key = (struct.river, struct.reach, struct.station)
        if key not in location_groups:
            location_groups[key] = []
        location_groups[key].append(struct)

    for key, group in location_groups.items():
        if len(group) > 1:
            river, reach, station = key
            messages.append(CheckMessage(
                message_id="ST_MS_01",
                severity=Severity.INFO,
                check_type="STRUCT",
                river=river,
                reach=reach,
                station=str(station),
                message=get_message_template("ST_MS_01").format(
                    station=station, count=len(group)
                )
            ))

            # Check for mixed types
            types = set(s.structure_type for s in group)
            if len(types) > 1:
                messages.append(CheckMessage(
                    message_id="ST_MS_02",
                    severity=Severity.INFO,
                    check_type="STRUCT",
                    river=river,
                    reach=reach,
                    station=str(station),
                    message=get_message_template("ST_MS_02").format(
                        station=station, types=', '.join(types)
                    )
                ))

    return messages


def build_struct_summary(
    structures: List[StructureData],
    struct_results: Dict[str, List[StructureResults]],
    profiles: List[str]
) -> pd.DataFrame:
    """Build summary table for structure check report."""
    records = []

    for struct in structures:
        record = {
            'river': struct.river,
            'reach': struct.reach,
            'station': struct.station,
            'name': struct.name,
            'type': struct.structure_type,
            'max_low_chord': struct.min_low_chord if struct.min_low_chord != -9999 else None,
            'deck_width': struct.deck_width if struct.deck_width != -9999 else None,
        }

        # Add results for first profile
        if profiles and profiles[0] in struct_results:
            for result in struct_results[profiles[0]]:
                if (result.river == struct.river and
                    result.reach == struct.reach and
                    result.station == struct.station):
                    record['wse'] = result.wse_3 if result.wse_3 != -9999 else None
                    record['ege'] = result.ege_3 if result.ege_3 != -9999 else None
                    record['flow_type'] = result.flow_type
                    break

        records.append(record)

    return pd.DataFrame(records)


def _decode_bytes(value) -> str:
    """Decode bytes to string if needed."""
    if isinstance(value, bytes):
        return value.decode('utf-8').strip()
    return str(value).strip()
```

## High Flow Method Codes

| Code | Method |
|------|--------|
| 1 | Energy |
| 2 | Momentum |
| 3 | Yarnell |
| 4 | WSPRO |
| 5 | Pressure/Weir |
| 6 | Energy with SRD |

## Low Flow Method Codes

| Code | Method |
|------|--------|
| 1 | Energy |
| 2 | Momentum |
| 3 | Yarnell |
| 4 | FHWA WSPRO |

## Testing Requirements

### Unit Tests

1. **test_extract_bridge_data**: Verify bridge geometry extraction
2. **test_extract_culvert_data**: Verify culvert geometry extraction
3. **test_extract_inline_weir**: Verify inline weir extraction
4. **test_check_section_distances**: Test distance validation rules
5. **test_check_bridge_coefficients**: Test bridge coefficient rules
6. **test_check_culvert_coefficients**: Test culvert coefficient rules
7. **test_check_flow_type**: Test flow type detection
8. **test_check_multiple_structures**: Test multiple structure detection

### Integration Tests

1. Test with project containing bridges
2. Test with project containing culverts
3. Test with project containing inline weirs
4. Test with project containing multiple structure types
5. Test with project having multiple structures at same RS

## Dependencies

- `h5py`: HDF file access
- `pandas`: DataFrame operations
- `numpy`: Numerical operations
- Parent module: `RasCheck`, `CheckResults`, `CheckMessage`, `Severity`
- Sibling modules: `messages`, `thresholds`
