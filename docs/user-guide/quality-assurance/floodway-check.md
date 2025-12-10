# Floodway Check: Floodway Analysis Validation

The Floodway Check validates floodway encroachment analysis for FEMA Flood Insurance Studies.

## Overview

Floodway analysis determines the channel required to convey the base flood (typically 1% annual chance) without increasing water surface elevations above an allowable surcharge limit. This check examines:

1. **Surcharge (SC)** - Surcharge values against FEMA/state limits
2. **Encroachment Method (EM)** - Appropriate encroachment method usage
3. **Starting WSE (SW)** - Starting water surface elevation consistency
4. **Discharge (DC)** - Discharge matching between profiles
5. **Structure (ST)** - Floodway analysis at structures
6. **Width (WD)** - Floodway width validation

## FEMA Floodway Requirements

Under 44 CFR 60.3, the regulatory floodway must:

- Carry the 1% annual chance flood
- Not increase the base flood elevation (BFE) more than a specified surcharge
- Default federal surcharge limit is **1.0 foot**
- Many states have more restrictive requirements

## State-Specific Surcharge Limits

| State | Surcharge Limit | Notes |
|-------|----------------|-------|
| Default (FEMA) | 1.0 ft | Standard federal limit |
| Wisconsin | 0.01 ft | Essentially zero rise |
| Illinois | 0.1 ft | Strict urban standards |
| Indiana | 0.1 ft | |
| Michigan | 0.1 ft | |
| New Jersey | 0.2 ft | |
| Minnesota | 0.5 ft | |
| Ohio | 0.5 or 1.0 ft | Varies by jurisdiction |

```python
from ras_commander.check import get_state_surcharge_limit

# Get state-specific limit
limit = get_state_surcharge_limit('IL')  # Returns 0.1
limit = get_state_surcharge_limit('TX')  # Returns 1.0 (default)
```

## Message Reference

### Surcharge Messages (FW_SC_*)

#### FW_SC_01 - Surcharge Exceeds Limit

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Surcharge ({surcharge} ft) exceeds allowable limit ({limit} ft) at RS {station} |
| **Cause** | Computed surcharge exceeds FEMA/state maximum |
| **Resolution** | Widen floodway encroachments to reduce surcharge. May need to adjust encroachment at multiple sections |

#### FW_SC_02 - Surcharge Approaching Limit

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Surcharge ({surcharge} ft) is within 10% of limit ({limit} ft) at RS {station} |
| **Cause** | Surcharge near maximum allowable |
| **Resolution** | Consider adjusting encroachments to provide additional margin |

#### FW_SC_03 - Negative Surcharge

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Negative surcharge ({surcharge} ft) at RS {station} - floodway WSE below base flood |
| **Cause** | Floodway water surface is lower than base flood |
| **Resolution** | This is acceptable but indicates encroachments could potentially be narrower |

#### FW_SC_04 - Zero Surcharge

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Zero surcharge at RS {station} |
| **Cause** | No rise in water surface from encroachment |
| **Resolution** | Indicates conservative floodway at this location |

### Encroachment Method Messages (FW_EM_*)

HEC-RAS provides five encroachment methods:

| Method | Description | Usage |
|--------|-------------|-------|
| 1 | User-specified stations | Manual encroachment |
| 2 | Equal conveyance reduction | Symmetric encroachment |
| 3 | Target surcharge | Automatic to target rise |
| 4 | Target width | Specified width |
| 5 | Optimize | Optimize for target criteria |

#### FW_EM_01 - Method 1 Usage

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Encroachment Method 1 (manual) used at RS {station} |
| **Cause** | Manual station specification requires verification |
| **Resolution** | Method 1 should only be used where automated methods don't apply. Document reasoning |

#### FW_EM_02 - Method Inconsistency

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Encroachment method changes from {method1} to {method2} at RS {station} |
| **Cause** | Different methods used at adjacent sections |
| **Resolution** | Consistent methodology is preferred. Justify method changes |

#### FW_EM_03 - Encroachment Inside Channel

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Encroachment station ({encr_sta}) is inside channel bank ({bank_sta}) at RS {station} |
| **Cause** | Floodway encroaches into main channel |
| **Resolution** | Floodway should not encroach into the main channel. Adjust encroachment limits |

### Starting WSE Messages (FW_SW_*)

#### FW_SW_01 - Base/Floodway Starting WSE Mismatch

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Starting WSE difference ({diff} ft) between base ({base_wse}) and floodway ({fw_wse}) profiles exceeds threshold |
| **Cause** | Downstream boundary conditions don't match |
| **Resolution** | Both profiles should have the same starting WSE at the downstream boundary |

#### FW_SW_02 - Computed vs Specified Starting WSE

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Computed starting WSE ({computed}) differs from specified ({specified}) by {diff} ft |
| **Cause** | Boundary condition produces different WSE than specified |
| **Resolution** | Review boundary condition. May indicate backwater effects |

#### FW_SW_03 - Starting WSE Above Bank

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Starting WSE ({wse}) exceeds bank elevation ({bank}) at downstream boundary |
| **Cause** | Out-of-bank flow at boundary |
| **Resolution** | Verify this is expected. May affect floodway delineation |

### Discharge Messages (FW_DC_*)

#### FW_DC_01 - Discharge Mismatch

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Base flood discharge ({q_base}) doesn't match floodway discharge ({q_fw}) at RS {station} |
| **Cause** | Floodway analysis must use identical discharge to base flood |
| **Resolution** | Verify both profiles use the same flow data |

#### FW_DC_02 - Discharge Tolerance Exceeded

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Discharge difference ({pct}%) exceeds {tolerance}% tolerance at RS {station} |
| **Cause** | Small differences may indicate data issues |
| **Resolution** | Review flow data entry for both profiles |

### Structure Messages (FW_ST_*)

#### FW_ST_01 - Surcharge at Structure

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | High surcharge ({surcharge} ft) at structure {name} |
| **Cause** | Structures often control surcharge |
| **Resolution** | Structures may require the full opening for floodway. Review structure floodway requirements |

#### FW_ST_02 - Encroachment at Structure

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | No encroachment applied at structure {name} |
| **Cause** | Structure opening defines effective floodway |
| **Resolution** | Normal for structures. Opening width typically equals floodway width |

#### FW_ST_03 - Structure Controls Surcharge

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Structure {name} controls maximum surcharge for reach |
| **Cause** | Maximum surcharge in reach occurs at structure |
| **Resolution** | Structures often control floodway. Verify structure analysis is correct |

### Width Messages (FW_WD_*)

#### FW_WD_01 - Narrow Floodway

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Floodway width ({width} ft) is less than channel width ({channel} ft) at RS {station} |
| **Cause** | Floodway narrower than channel |
| **Resolution** | Floodway width should generally equal or exceed channel width |

#### FW_WD_02 - Width Discontinuity

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Large floodway width change ({pct}%) between RS {station_us} ({width_us} ft) and RS {station_ds} ({width_ds} ft) |
| **Cause** | Abrupt width change |
| **Resolution** | Gradual transitions are preferred. Review for reasonableness |

#### FW_WD_03 - Asymmetric Encroachment

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Highly asymmetric encroachment at RS {station}: left={left} ft, right={right} ft |
| **Cause** | Unequal encroachment on left and right |
| **Resolution** | May be appropriate for asymmetric floodplains. Document reasoning |

## Running Floodway Checks

```python
from ras_commander.check import RasCheck, get_state_surcharge_limit

# Get state-specific surcharge limit
surcharge_limit = get_state_surcharge_limit('TX')  # 1.0 ft

# Run floodway check
results = RasCheck.check_floodways(
    plan_hdf,
    geom_hdf,
    base_profile='100yr',        # Base flood profile name
    floodway_profile='Floodway', # Floodway profile name
    surcharge=surcharge_limit    # Maximum allowable surcharge
)

# Review results
for msg in results.messages:
    if msg.severity.value == 'ERROR':
        print(f"{msg.message_id}: {msg.message}")
```

## Customizing Floodway Thresholds

```python
from ras_commander.check import create_custom_thresholds, RasCheck

# Create thresholds for Illinois (0.1 ft surcharge)
il_thresholds = create_custom_thresholds({
    'floodway.surcharge_max_ft': 0.1,
    'floodway.discharge_tolerance_percent': 2.0,  # Stricter discharge matching
    'floodway.min_floodway_width_ft': 20.0,       # Minimum width
})

# Run checks with Illinois standards
results = RasCheck.check_floodways(
    plan_hdf, geom_hdf,
    base_profile='100yr',
    floodway_profile='Floodway',
    surcharge=0.1,
    thresholds=il_thresholds
)
```

## References

- 44 CFR 60.3 - National Flood Insurance Program Regulations
- FEMA Guidelines and Specifications for Flood Hazard Mapping Partners
- HEC-RAS User's Manual, Chapter 8: Performing a Floodway Analysis
