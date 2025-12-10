# NT Check: Manning's n and Transition Coefficients

The NT Check validates Manning's roughness coefficients and transition loss coefficients throughout the HEC-RAS model.

## Overview

This check examines:

1. **Roughness Coefficients (RC)** - Manning's n values for left overbank, channel, and right overbank
2. **Transition Losses (TL)** - Contraction and expansion coefficients at structures and regular cross sections
3. **Roughness at Structures (RS)** - Manning's n values at bridge section faces
4. **N-Value Variation (VR)** - Large changes in n-values between adjacent cross sections

## Default Thresholds

### Manning's n Ranges

| Location | Minimum | Maximum | Source |
|----------|---------|---------|--------|
| Left Overbank | 0.030 | 0.200 | Chow (1959), HEC-RAS Manual |
| Right Overbank | 0.030 | 0.200 | Chow (1959), HEC-RAS Manual |
| Channel | 0.025 | 0.100 | Chow (1959), HEC-RAS Manual |

!!! note "Typical Values"
    - **0.030**: Smooth pasture, lawns
    - **0.050**: Light brush, scattered trees
    - **0.100**: Heavy brush, dense vegetation
    - **0.150**: Dense willows, heavy timber with debris
    - **0.200**: Dense brush, heavy timber, debris jams

### Transition Coefficients

| Location | Contraction | Expansion | Source |
|----------|-------------|-----------|--------|
| Regular Cross Sections | 0.1 | 0.3 | HEC-RAS Manual Table 3-1 |
| Structure Sections (2, 3, 4) | 0.3 | 0.5 | HEC-RAS Manual |

## Message Reference

### Roughness Coefficient Messages (NT_RC_*)

#### NT_RC_01L - Left Overbank n Too Low

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Left overbank Manning's n value ({n}) is less than 0.030 |
| **Cause** | The left overbank roughness is below the typical minimum for natural floodplains |
| **Resolution** | Review land cover data. Very low n values are unusual except for smooth concrete or maintained lawns |

#### NT_RC_02L - Left Overbank n Too High

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Left overbank Manning's n value ({n}) exceeds 0.200 |
| **Cause** | The left overbank roughness exceeds typical maximum |
| **Resolution** | Verify land cover classification. Values above 0.200 are rare except for extreme conditions |

#### NT_RC_01R - Right Overbank n Too Low

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Right overbank Manning's n value ({n}) is less than 0.030 |
| **Cause** | The right overbank roughness is below the typical minimum |
| **Resolution** | Review land cover data for right overbank area |

#### NT_RC_02R - Right Overbank n Too High

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Right overbank Manning's n value ({n}) exceeds 0.200 |
| **Cause** | The right overbank roughness exceeds typical maximum |
| **Resolution** | Verify land cover classification |

#### NT_RC_03C - Channel n Too Low

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Channel Manning's n value ({n}) is less than 0.025 |
| **Cause** | Channel roughness is below minimum typical value |
| **Resolution** | Values below 0.025 typically indicate smooth concrete channels or engineered sections. Verify this is intentional |

#### NT_RC_04C - Channel n Too High

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Channel Manning's n value ({n}) exceeds 0.100 |
| **Cause** | Channel roughness exceeds typical maximum |
| **Resolution** | High channel n values may indicate heavy vegetation, debris, or irregular channel. Verify conditions |

#### NT_RC_05 - Overbank n Less Than Channel n

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Overbank n values (LOB={n_lob}, ROB={n_rob}) are not greater than channel n ({n_chl}) |
| **Cause** | Typically, overbank roughness exceeds channel roughness |
| **Resolution** | This may be valid for engineered channels with vegetated overbanks. Review to confirm |

### Transition Loss Messages (NT_TL_*)

#### NT_TL_01S1 through NT_TL_01S4 - Structure Section Transitions

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Section {N}: Transition coefficients ({cc}/{ce}) should be 0.3/0.5 |
| **Cause** | Bridge/culvert sections should use higher transition coefficients (0.3/0.5) |
| **Resolution** | Update contraction to 0.3 and expansion to 0.5 for sections 1-4 around structures |

Bridge 4-section model locations:

- **Section 1** - Upstream approach cross section
- **Section 2** - Upstream face of bridge (between abutments)
- **Section 3** - Downstream face of bridge (between abutments)
- **Section 4** - Downstream approach cross section

#### NT_TL_02 - Non-Standard Transition Coefficients

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Transition coefficients at RS {station} are {cc}/{ce}, typical values are 0.1/0.3 |
| **Cause** | Coefficients differ from standard gradual transition values |
| **Resolution** | Non-standard values may be intentional for specific hydraulic conditions. Review and document reasoning |

### Roughness at Structures Messages (NT_RS_*)

#### NT_RS_01S2C - Bridge Upstream n Comparison

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Channel n at Section 2 ({n_s2}) should be less than Section 1 ({n_s1}) |
| **Cause** | Manning's n typically decreases approaching a bridge due to contraction effects |
| **Resolution** | Review bridge approach conditions. The n-value gradient helps model approach velocity changes |

#### NT_RS_01S3C - Bridge Downstream n Comparison

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Channel n at Section 3 ({n_s3}) should be less than Section 4 ({n_s4}) |
| **Cause** | Manning's n typically increases leaving a bridge due to expansion effects |
| **Resolution** | Review bridge exit conditions |

#### NT_RS_02BUC - Bridge Internal Section n Mismatch (Upstream)

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Bridge upstream internal section (Section 2) has different Manning's n values than upstream XS (Section 1) |
| **Cause** | The n-values within the bridge opening differ from the approach section |
| **Resolution** | This may be intentional (e.g., concrete channel lining under bridge). Verify bridge opening conditions |

#### NT_RS_02BDC - Bridge Internal Section n Mismatch (Downstream)

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Bridge downstream internal section (Section 3) has different Manning's n values than downstream XS (Section 4) |
| **Cause** | The n-values within the bridge opening differ from the exit section |
| **Resolution** | Verify bridge opening conditions are accurately represented |

### N-Value Variation Messages (NT_VR_*)

#### NT_VR_01L - Large LOB n-Value Change

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Large LOB n-value change ({pct}%) between RS {station_us} ({n_us}) and RS {station_ds} ({n_ds}) |
| **Cause** | Significant n-value change between adjacent cross sections |
| **Resolution** | Large changes may indicate data entry error or need for intermediate cross sections. Review land cover transitions |

#### NT_VR_01C - Large Channel n-Value Change

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Large channel n-value change ({pct}%) between RS {station_us} ({n_us}) and RS {station_ds} ({n_ds}) |
| **Cause** | Significant channel n-value change |
| **Resolution** | Verify channel conditions. Abrupt changes are unusual except at structures or channel transitions |

#### NT_VR_01R - Large ROB n-Value Change

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Large ROB n-value change ({pct}%) between RS {station_us} ({n_us}) and RS {station_ds} ({n_ds}) |
| **Cause** | Significant right overbank n-value change |
| **Resolution** | Review land cover transitions and consider intermediate sections |

## Customizing NT Thresholds

```python
from ras_commander.check import create_custom_thresholds, RasCheck

# Create stricter thresholds for urban areas
urban_thresholds = create_custom_thresholds({
    'mannings_n.overbank_min': 0.035,
    'mannings_n.overbank_max': 0.150,
    'mannings_n.channel_min': 0.020,
    'mannings_n.channel_max': 0.060,
})

# Run NT check with custom thresholds
results = RasCheck.check_nt(geom_hdf, thresholds=urban_thresholds)
```

## References

- Chow, V.T. (1959). *Open-Channel Hydraulics*. McGraw-Hill.
- HEC-RAS Hydraulic Reference Manual, Chapter 3: Theoretical Basis for One-Dimensional Flow Calculations
- FEMA Guidelines and Specifications for Flood Hazard Mapping Partners
