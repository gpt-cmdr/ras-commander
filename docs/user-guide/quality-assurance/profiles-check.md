# Profiles Check: Multiple Profile Consistency

The Profiles Check validates consistency and relationships between multiple steady flow profiles in a HEC-RAS model.

## Overview

When a model contains multiple profiles (e.g., 10-year, 50-year, 100-year, 500-year floods), certain physical relationships should hold. This check examines:

1. **WSE Ordering (WO)** - Water surface elevations should increase with discharge
2. **Discharge Ordering (DO)** - Discharges should be ordered consistently
3. **Top Width Ordering (TW)** - Top widths should generally increase with discharge
4. **Velocity Consistency (VC)** - Velocity relationships across profiles
5. **Flow Regime (FR)** - Consistent flow regime across profiles
6. **Boundary Conditions (BC)** - Appropriate boundary condition methods

## Expected Physical Relationships

For typical floodplain hydraulics, as discharge increases:

| Parameter | Expected Behavior |
|-----------|-------------------|
| Water Surface Elevation (WSE) | Increases |
| Flow Area | Increases |
| Top Width | Increases (floodplain activation) |
| Velocity | Generally increases |
| Froude Number | May vary with geometry |

!!! note "Exceptions"
    These relationships may not hold in all cases:
    - Storage areas and split flow can cause anomalies
    - Structures may cause flow regime transitions
    - Complex floodplain geometry can invert relationships

## Message Reference

### WSE Ordering Messages (MP_WO_*)

#### MP_WO_01 - WSE Order Violation

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | WSE for {profile_high} ({wse_high} ft) is lower than {profile_low} ({wse_low} ft) at RS {station} |
| **Cause** | Higher discharge profile has lower water surface |
| **Resolution** | Review profile discharges and results. May indicate model instability or data error |

#### MP_WO_02 - WSE Crossing

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | WSE profiles cross at RS {station}: {profile1} and {profile2} |
| **Cause** | Water surface profiles intersect |
| **Resolution** | Profile crossing may indicate storage effects or split flow. Review reach conditions |

#### MP_WO_03 - WSE Order Tolerance

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | WSE difference ({diff} ft) between {profile_high} and {profile_low} is within tolerance at RS {station} |
| **Cause** | Very small difference between profile WSEs |
| **Resolution** | Small differences are acceptable but may indicate model sensitivity |

### Discharge Ordering Messages (MP_DO_*)

#### MP_DO_01 - Discharge Order Violation

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Discharge for {profile_high} ({q_high} cfs) is less than {profile_low} ({q_low} cfs) at RS {station} |
| **Cause** | Expected higher recurrence interval has lower discharge |
| **Resolution** | Review flow data. Discharges should increase with decreasing AEP |

#### MP_DO_02 - Discharge Constant Across Profiles

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Discharge is constant ({q} cfs) across all profiles at RS {station} |
| **Cause** | All profiles have same discharge |
| **Resolution** | May be intentional for sensitivity analysis. Verify if expected |

### Top Width Ordering Messages (MP_TW_*)

#### MP_TW_01 - Top Width Order Violation

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Top width for {profile_high} ({tw_high} ft) is less than {profile_low} ({tw_low} ft) at RS {station} |
| **Cause** | Higher discharge has narrower top width |
| **Resolution** | May indicate confined channel or complex geometry. Review cross section |

#### MP_TW_02 - Top Width Unchanged

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Top width unchanged across profiles at RS {station} |
| **Cause** | Floodplain not activating or confined channel |
| **Resolution** | May indicate all flow within channel banks. Verify geometry |

### Velocity Consistency Messages (MP_VC_*)

#### MP_VC_01 - Velocity Decrease with Higher Discharge

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Velocity for {profile_high} ({v_high} fps) is less than {profile_low} ({v_low} fps) at RS {station} |
| **Cause** | Higher discharge has lower velocity |
| **Resolution** | Common with floodplain activation (larger area). Review if reasonable |

#### MP_VC_02 - Extreme Velocity

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Velocity ({v} fps) exceeds {limit} fps for {profile} at RS {station} |
| **Cause** | Very high velocity computed |
| **Resolution** | Velocities > 20-25 fps are unusual for natural channels. Review geometry |

#### MP_VC_03 - Very Low Velocity

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Velocity ({v} fps) is less than {limit} fps for {profile} at RS {station} |
| **Cause** | Very slow flow |
| **Resolution** | May indicate ponding or backwater. Review downstream conditions |

### Flow Regime Messages (MP_FR_*)

#### MP_FR_01 - Flow Regime Inconsistency

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Flow regime differs between profiles at RS {station}: {profile1}={regime1}, {profile2}={regime2} |
| **Cause** | Different profiles have different flow regimes (subcritical vs supercritical) |
| **Resolution** | Review flow conditions. Regime transitions may occur at different discharges |

#### MP_FR_02 - Critical Depth for All Profiles

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Critical depth computed for all profiles at RS {station} |
| **Cause** | All profiles show critical depth |
| **Resolution** | Indicates control section. Verify geometry is appropriate |

### Boundary Condition Messages (MP_BC_*)

#### MP_BC_01 - Mixed Boundary Methods

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Different boundary condition methods used across profiles |
| **Cause** | Profiles use different downstream boundary types |
| **Resolution** | Consistent boundary methods are preferred. Document reasoning for differences |

#### MP_BC_02 - Normal Depth Boundary

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Normal depth boundary condition used for {profile} |
| **Cause** | Profile uses normal depth at boundary |
| **Resolution** | Normal depth is appropriate when channel slope controls. Verify slope value |

#### MP_BC_03 - Known WSE Boundary

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Known water surface boundary ({wse} ft) used for {profile} |
| **Cause** | Fixed WSE at boundary |
| **Resolution** | Known WSE appropriate when controlled by downstream lake, confluence, etc. |

### Energy Messages (MP_EN_*)

#### MP_EN_01 - Energy Ordering

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Energy grade line for {profile_high} ({egl_high} ft) is lower than {profile_low} ({egl_low} ft) at RS {station} |
| **Cause** | Higher discharge has lower energy |
| **Resolution** | Unusual but may occur with floodplain effects. Review results |

## Running Profiles Check

```python
from ras_commander.check import RasCheck

# Define profiles in expected order (lowest to highest discharge)
profiles = ['10yr', '50yr', '100yr', '500yr']

# Run profiles check
results = RasCheck.check_profiles(
    plan_hdf,
    profiles=profiles
)

# Review ordering violations
for msg in results.messages:
    if 'order' in msg.message.lower():
        print(f"{msg.station}: {msg.message}")
```

## Customizing Profiles Thresholds

```python
from ras_commander.check import create_custom_thresholds, RasCheck

# Create thresholds with custom velocity limits
custom_thresholds = create_custom_thresholds({
    'profiles.wse_order_tolerance_ft': 0.05,  # Stricter WSE tolerance
    'profiles.velocity_max_fps': 20.0,        # Lower velocity limit
    'profiles.velocity_min_fps': 0.2,         # Higher minimum velocity
    'profiles.froude_subcritical_max': 0.95,  # Stricter Froude limit
})

# Run check with custom thresholds
results = RasCheck.check_profiles(plan_hdf, profiles, thresholds=custom_thresholds)
```

## Common Causes of Profile Inconsistencies

### WSE Order Violations

1. **Data entry errors** - Wrong discharge assigned to profile
2. **Boundary condition issues** - Inappropriate boundary methods
3. **Storage effects** - Offline storage activating at higher flows
4. **Split flow** - Flow diversion at higher stages
5. **Model instability** - Numerical issues at specific profiles

### Top Width Anomalies

1. **Confined valley** - Steep valley walls limit expansion
2. **Ineffective flow** - Trigger elevations causing jumps
3. **Levees** - Levee overtopping changes width relationships
4. **Structures** - Bridge openings constraining flow

### Velocity Anomalies

1. **Floodplain activation** - Larger area at higher flows
2. **Backwater effects** - Downstream controls
3. **Geometry transitions** - Width changes affecting velocity

## References

- HEC-RAS User's Manual
- FEMA Guidelines and Specifications for Flood Hazard Mapping Partners
- Hydraulic Engineering Circular No. 25 (HEC-25)
