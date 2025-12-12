# RasCheck Validation Reference

Complete reference for all RasCheck validation types, message IDs, and standards.

## Overview

RasCheck implements quality assurance checks based on FEMA's cHECk-RAS tool, adapted for HEC-RAS 6.x HDF-based workflows. It validates 5 categories of model quality.

## Check Types

### 1. NT Check: Manning's n and Transition Coefficients

**Function**: `RasCheck.check_nt(geom_hdf, thresholds=None)`

**Purpose**: Validate roughness coefficients and energy loss coefficients.

**Checks Performed**:
- Manning's n values within acceptable ranges
- Channel vs overbank roughness consistency
- Transition coefficients (contraction/expansion)
- Subdivision method appropriateness

**Message IDs**:
- `NT_RC_01L` - Left overbank Manning's n out of range
- `NT_RC_01M` - Main channel Manning's n out of range
- `NT_RC_01R` - Right overbank Manning's n out of range
- `NT_TR_01` - Contraction coefficient out of range
- `NT_TR_02` - Expansion coefficient out of range

**Default Thresholds**:
```python
# Manning's n ranges
overbank: 0.020 - 0.200
channel:  0.015 - 0.150

# Transition coefficients (structures)
structure_contraction: 0.0 - 0.6
structure_expansion:   0.3 - 1.0

# Transition coefficients (regular XS)
normal_contraction: 0.0 - 0.3
normal_expansion:   0.3 - 0.8
```

**Standards**:
- FEMA Base Level Engineering (BLE) guidance
- USACE HEC-RAS Hydraulic Reference Manual
- Land cover-based roughness (Anderson classification)

### 2. XS Check: Cross Section Validation

**Function**: `RasCheck.check_xs(geom_hdf, thresholds=None)`

**Purpose**: Validate cross section geometry and placement.

**Checks Performed**:
- Cross section spacing (reach length limits)
- Station-elevation monotonicity (no reversals)
- Ineffective flow area placement
- Bank station placement
- Reach length ratios (left vs right vs channel)

**Message IDs**:
- `XS_DT_01` - Excessive cross section spacing (> 1000 ft warning, > 2000 ft error)
- `XS_DT_02L` - Left overbank reach length excessive
- `XS_DT_02R` - Right overbank reach length excessive
- `XS_DT_03` - Reach length ratio exceeds threshold
- `XS_GE_01` - Station elevation reversal detected
- `XS_IE_01` - Ineffective flow area elevation issue
- `XS_BS_01` - Bank station placement error

**Default Thresholds**:
```python
# Reach length limits
max_length_ft: 2000.0        # Error threshold
max_length_warn_ft: 1000.0   # Warning threshold
length_ratio_max: 1.5        # Left/right vs channel ratio

# Station spacing
min_station_spacing: 1.0     # Minimum station increment
```

**Standards**:
- FEMA Guidelines and Specifications for Flood Hazard Mapping
- HEC-RAS cross section spacing recommendations
- Typical maximum spacing: 500 ft (urban), 1000 ft (rural)

### 3. Structure Check: Bridges, Culverts, Weirs

**Function**: `RasCheck.check_structures(geom_hdf, thresholds=None)`

**Purpose**: Validate structure geometry and compatibility with channel.

**Checks Performed**:
- Bridge low chord vs channel invert elevations
- Pier spacing and alignment
- Culvert slope vs channel slope
- Deck width sufficiency
- Approach section compatibility
- Weir crest elevations

**Message IDs**:
- `BR_GE_01` - Low chord below channel invert (physical impossibility)
- `BR_GE_02` - Pier spacing less than minimum
- `BR_CF_01` - Bridge coefficient out of range
- `BR_TF_01` - Flow type classification issue
- `CU_GE_01` - Culvert slope mismatch with channel
- `CU_GE_02` - Culvert invert elevation issue
- `IW_GE_01` - Inline weir crest elevation issue

**Default Thresholds**:
```python
# Bridge coefficients
min_bridge_coeff: 0.3
max_bridge_coeff: 1.0

# Pier spacing
min_pier_spacing_ft: 10.0

# Culvert slope tolerance
slope_tolerance_percent: 20.0  # 20% difference allowed
```

**Standards**:
- HEC-RAS Hydraulic Reference Manual (bridge/culvert modeling)
- FEMA Guidelines for structure representation
- USACE EM 1110-2-1416 (River Hydraulics)

### 4. Floodway Check: Encroachment Analysis

**Function**: `RasCheck.check_floodways(geom_hdf, floodway_profile, surcharge=1.0)`

**Purpose**: Validate floodway analysis against FEMA/USACE standards.

**Checks Performed**:
- Surcharge limits (default 1.0 ft, state-specific overrides)
- Conveyance reduction method compliance
- Equal conveyance method application
- Base flood elevation consistency
- Encroachment station placement

**Message IDs**:
- `FW_SU_01` - Surcharge exceeds limit (CRITICAL)
- `FW_CV_01` - Conveyance reduction violation
- `FW_EC_01` - Equal conveyance method issue
- `FW_BF_01` - Base flood elevation inconsistency

**Default Thresholds**:
```python
# FEMA standard
max_surcharge_ft: 1.0

# State-specific (use get_state_surcharge_limit())
IL: 0.1 ft    # Illinois (very strict)
WI: 0.0 ft    # Wisconsin (no surcharge)
MN: 0.5 ft    # Minnesota
NJ: 0.2 ft    # New Jersey
MI, IN, OH: 0.5 ft
Default: 1.0 ft
```

**Standards**:
- FEMA Guidance Document 72 (Floodway Analysis and Mapping)
- NFIP Technical Bulletin 4 (Floodway Encroachment)
- State-specific floodway regulations

### 5. Profiles Check: Multiple Profile Consistency

**Function**: `RasCheck.check_profiles(plan_hdf, thresholds=None)`

**Purpose**: Validate consistency across multiple water surface profiles.

**Checks Performed**:
- WSE ordering (higher flows = higher WSE)
- Profile convergence
- Discharge consistency
- Extreme velocity detection
- Energy slope reasonableness

**Message IDs**:
- `PR_WS_01` - WSE ordering violation (lower flow has higher WSE)
- `PR_CV_01` - Profile convergence issue
- `PR_VL_01` - Extreme velocity warning (> 15 ft/s)
- `PR_VL_02` - Extreme velocity error (> 25 ft/s)
- `PR_ES_01` - Energy slope unreasonable

**Default Thresholds**:
```python
# Velocity limits
max_velocity_warn_fps: 15.0   # Warning (potential erosion)
max_velocity_error_fps: 25.0  # Error (unrealistic)
min_velocity_warn_fps: 0.5    # Low velocity (sedimentation)

# Energy slope
min_energy_slope: 0.0001      # Minimum reasonable slope
max_energy_slope: 0.1         # Maximum reasonable slope
```

**Standards**:
- HEC-RAS steady flow convergence criteria
- Typical velocity limits for natural channels
- Energy slope reasonableness checks

## Custom Thresholds

Override default thresholds for project-specific requirements:

```python
from ras_commander.check import create_custom_thresholds

custom = create_custom_thresholds({
    # Manning's n (stricter)
    'mannings_n.overbank_min': 0.035,
    'mannings_n.overbank_max': 0.150,
    'mannings_n.channel_min': 0.028,
    'mannings_n.channel_max': 0.080,

    # Cross section spacing (more conservative)
    'reach_length.max_length_ft': 1500.0,
    'reach_length.max_length_warn_ft': 800.0,

    # Floodway (state-specific)
    'floodway.max_surcharge_ft': 0.5,  # USACE standard

    # Velocity limits
    'velocity.max_velocity_warn_fps': 12.0,
    'velocity.max_velocity_error_fps': 20.0,
})

results = RasCheck.run_all("01", thresholds=custom)
```

## State-Specific Surcharge Limits

Different states have different maximum surcharge limits for floodway analysis:

```python
from ras_commander.check import get_state_surcharge_limit

# Get state-specific limit
il_limit = get_state_surcharge_limit('IL')  # Returns 0.1
wi_limit = get_state_surcharge_limit('WI')  # Returns 0.0
tx_limit = get_state_surcharge_limit('TX')  # Returns 1.0 (default)

# Use in floodway check
results = RasCheck.check_floodways(
    geom_hdf,
    floodway_profile="Floodway",
    surcharge=il_limit
)
```

**State Limits**:
- **IL** (Illinois): 0.1 ft
- **WI** (Wisconsin): 0.0 ft (no surcharge allowed)
- **MN** (Minnesota): 0.5 ft
- **NJ** (New Jersey): 0.2 ft
- **MI** (Michigan): 0.5 ft
- **IN** (Indiana): 0.5 ft
- **OH** (Ohio): 0.5 ft
- **Default** (TX, most states): 1.0 ft

## Message Severity Levels

All check messages are classified by severity:

| Severity | Description | Action Required |
|----------|-------------|-----------------|
| **ERROR** | Critical issue, must be fixed | Fix before submission |
| **WARNING** | Issue requiring review/justification | Document or fix |
| **INFO** | Informational note | Review, no action required |
| **PASS** | Check passed | None |

## Check Results Data Structure

**CheckResults** object contains:
- `messages`: List of CheckMessage objects
- `errors`: Filtered list (severity=ERROR)
- `warnings`: Filtered list (severity=WARNING)
- `info`: Filtered list (severity=INFO)
- `passed`: List of checks that passed

**CheckMessage** attributes:
- `message_id`: Unique identifier (e.g., "NT_RC_01L")
- `check_type`: Check category ("NT", "XS", "BR", "FW", "PR")
- `severity`: Severity enum (ERROR, WARNING, INFO, PASS)
- `station`: River station (e.g., "12345.67")
- `message`: Human-readable message
- `location`: Detailed location (reach, river, etc.)
- `value`: Actual value that triggered message
- `threshold`: Threshold value (if applicable)

## FEMA/USACE Standards Sources

RasCheck implements validation criteria from:

**FEMA Documents**:
- Guidance Document 72: Floodway Analysis and Mapping
- Base Level Engineering (BLE) Specifications
- Guidelines and Specifications for Flood Hazard Mapping Partners
- NFIP Technical Bulletin 4: Floodway Encroachment

**USACE Documents**:
- HEC-RAS Hydraulic Reference Manual
- EM 1110-2-1416: River Hydraulics
- EM 1110-2-1601: Hydraulic Design of Flood Control Channels

**Industry Standards**:
- Land cover-based Manning's n (Anderson classification)
- Typical cross section spacing guidelines
- Structure modeling best practices

## Performance Characteristics

**Speed**:
- Typical 1D model (100 XS): 5-15 seconds
- Large 1D model (1000 XS): 30-60 seconds
- 2D model (10,000 cells): 60-120 seconds

**Memory**:
- Low memory footprint (processes files sequentially)
- Suitable for models with 10,000+ cross sections
- Parallel checking supported for multiple plans

**Thread Safety**:
- All check functions are thread-safe
- Can validate multiple plans in parallel
- Uses @log_call decorators for execution tracking
