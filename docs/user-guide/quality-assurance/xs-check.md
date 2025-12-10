# XS Check: Cross Section Validation

The XS Check validates cross section geometry, spacing, and hydraulic results throughout the HEC-RAS model.

## Overview

This check examines:

1. **Distance/Travel (DT)** - Reach lengths between cross sections
2. **Ineffective Flow (IF)** - Ineffective flow area definitions
3. **Default Flow (DF)** - Default ineffective flow usage
4. **Blocked Obstruction (BO)** - Blocked obstruction definitions
5. **Exceedance/Encroachment (EC)** - Water surface exceeding cross section limits
6. **Critical Depth (CD)** - Critical depth conditions
7. **Friction Slope (FS)** - Friction slope method appropriateness
8. **Discharge Conservation (DC)** - Discharge continuity
9. **Flow Regime (FR)** - Flow regime transitions
10. **Levee (LV)** - Levee definitions and overtopping
11. **Conveyance (CT)** - Conveyance subdivisions and coefficients
12. **Channel Width (CW)** - Channel width variations
13. **Additional checks** - Area, slope, energy, velocity distribution

## Message Reference

### Distance/Travel Messages (XS_DT_*)

#### XS_DT_01 - Overbank/Channel Length Mismatch

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Overbank reach lengths (LOB={lob}, ROB={rob}) exceed channel ({chl}) by more than 25 ft |
| **Cause** | Large differences between overbank and channel flow path lengths |
| **Resolution** | Review flow paths. Overbank lengths typically exceed channel in meandering streams but large differences warrant review |

#### XS_DT_02L - Left Overbank Length Ratio

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Left overbank reach length ({lob}) is more than 2x channel ({chl}) |
| **Cause** | Left overbank flow path is significantly longer than channel |
| **Resolution** | Verify overbank flow paths are accurately represented. Consider valley cross section or additional XS |

#### XS_DT_02R - Right Overbank Length Ratio

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Right overbank reach length ({rob}) is more than 2x channel ({chl}) |
| **Cause** | Right overbank flow path is significantly longer than channel |
| **Resolution** | Verify overbank flow paths in GIS or survey data |

### Ineffective Flow Messages (XS_IF_*)

#### XS_IF_01L - Left Ineffective Elevation Issue

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Left ineffective: WSE ({wsel}) > ground ({grelv}) but <= ineffective elev ({ineffell}) for {profile} |
| **Cause** | Water surface is above ground but at or below ineffective trigger elevation |
| **Resolution** | Review ineffective flow elevation. The area may be intended to be ineffective at this water level |

#### XS_IF_01R - Right Ineffective Elevation Issue

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Right ineffective: WSE ({wsel}) > ground ({grelv}) but <= ineffective elev ({ineffelr}) for {profile} |
| **Cause** | Water surface above ground but at or below ineffective trigger elevation |
| **Resolution** | Review right ineffective flow elevation settings |

#### XS_IF_02L / XS_IF_02R - Multiple Ineffective Areas

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Multiple ineffective flow areas on left/right overbank |
| **Cause** | Multiple ineffective areas defined on one side |
| **Resolution** | Multiple areas are allowed but may complicate analysis. Verify all are necessary |

#### XS_IF_03L / XS_IF_03R - Ineffective Extends Into Channel

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Left/Right ineffective station extends past bank station |
| **Cause** | Ineffective flow area crosses into the main channel |
| **Resolution** | Ineffective flow areas should not extend into the channel. Adjust station limits |

### Blocked Obstruction Messages (XS_BO_*)

#### XS_BO_01L / XS_BO_01R - Blocked Obstruction at Ground Edge

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Left/Right blocked obstruction starts at ground point |
| **Cause** | Blocked obstruction begins at the cross section edge |
| **Resolution** | Consider adding ineffective flow area to properly model blocked region |

#### XS_BO_02L / XS_BO_02R - Multiple Blocked Obstructions

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Multiple blocked obstructions may need ineffective flow areas |
| **Cause** | Multiple blocked obstructions defined |
| **Resolution** | Consider adding ineffective flow areas to properly model flow around blocked regions |

### Exceedance Messages (XS_EC_*)

#### XS_EC_01L / XS_EC_01R - WSE Exceeds Ground

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | WSE ({wsel}) exceeds left/right ground elevation ({grelv}) for {profile} |
| **Cause** | Computed water surface extends beyond cross section boundaries |
| **Resolution** | Extend cross section to higher ground or verify results. May indicate floodplain extends beyond surveyed area |

#### XS_EC_01BUL through XS_EC_01BDR - Bridge Section WSE Exceedance

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Bridge upstream/downstream: WSE exceeds ground for {profile} |
| **Cause** | Water surface exceeds cross section at bridge |
| **Resolution** | Extend bridge section cross sections. Verify bridge approach geometry |

### Critical Depth Messages (XS_CD_*)

#### XS_CD_01 - Critical Depth with Permanent Ineffective

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Critical depth at XS with permanent ineffective flow for {profile} |
| **Cause** | Critical depth computed where permanent ineffective areas exist |
| **Resolution** | This combination may indicate modeling issues. Review cross section setup |

#### XS_CD_02 - Critical Depth with Low n

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Critical depth with low channel Manning's n (<0.025) for {profile} |
| **Cause** | Critical depth combined with very low roughness |
| **Resolution** | Low n values may be causing flow regime issues. Review channel characteristics |

### Flow Regime Messages (XS_FR_*)

#### XS_FR_01 - Subcritical to Supercritical

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Flow regime transition: subcritical to supercritical for {profile} |
| **Cause** | Flow accelerates from subcritical to supercritical (control section) |
| **Resolution** | May indicate steep slope or constriction. Verify this is physically reasonable |

#### XS_FR_02 - Supercritical to Subcritical (Hydraulic Jump)

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Flow regime transition: supercritical to subcritical (hydraulic jump) for {profile} |
| **Cause** | Hydraulic jump detected |
| **Resolution** | Verify model stability and energy losses at this location. Additional cross sections may be needed |

#### XS_FR_03 - Extreme Froude Number

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Extreme Froude number ({froude}) for {profile} |
| **Cause** | Very high Froude number indicates unstable or supercritical flow |
| **Resolution** | Values > 3 may indicate geometry issues. Review cross section and flow data |

### Levee Messages (XS_LV_*)

#### XS_LV_01L / XS_LV_01R - Levee Station Out of Range

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Left/Right levee station is outside cross section extent |
| **Cause** | Levee defined at station not within cross section |
| **Resolution** | Correct levee station to be within cross section limits |

#### XS_LV_02L / XS_LV_02R - Levee Below Ground

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Left/Right levee elevation is below adjacent ground elevation |
| **Cause** | Levee elevation is lower than ground - physically impossible |
| **Resolution** | Correct levee elevation to be above ground surface |

#### XS_LV_03L / XS_LV_03R - Levee Not at High Point

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Left/Right levee is not at local high point |
| **Cause** | Levee elevation doesn't correspond to highest point in vicinity |
| **Resolution** | Review levee station placement. Levee should be at local topographic high |

#### XS_LV_04L / XS_LV_04R - Levee Overtopped

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Left/Right levee overtopped: WSE={wselev}, levee elev={leveel} |
| **Cause** | Water surface exceeds levee elevation |
| **Resolution** | This may be expected for larger floods or indicate levee data issues |

### Conveyance Messages (XS_CT_*)

#### XS_CT_01 - Non-Standard Conveyance Subdivisions

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Non-standard conveyance subdivisions: LOB={lob_slices}, Chan={chan_slices}, ROB={rob_slices} |
| **Cause** | Conveyance subdivision counts differ from typical values |
| **Resolution** | Standard values are 1-5 per region. Review if non-standard values are intentional |

#### XS_CT_04 - Coefficient Variation

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Contraction coefficient varies significantly between adjacent sections |
| **Cause** | Large differences in coefficients between neighboring cross sections |
| **Resolution** | Coefficients should generally be uniform along a reach unless specific conditions warrant changes |

### Channel Width Messages (XS_CW_*)

#### XS_CW_01 - Channel Width Ratio

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Channel width ratio ({ratio}) between adjacent sections exceeds threshold |
| **Cause** | Channel width changes significantly (>2x or <0.5x) |
| **Resolution** | May indicate geometry issues or need for intermediate cross sections. Gradual transitions preferred |

### Additional XS Messages

#### XS_AR_01 - Large Flow Area Change

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Large flow area change ({pct}%) between adjacent sections for {profile} |
| **Cause** | Flow area changes >50% between cross sections |
| **Resolution** | May indicate geometry issues or need for additional intermediate sections |

#### XS_SL_01 / XS_SL_02 - Water Surface Slope Anomaly

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Water surface slope anomaly / Steep water surface slope |
| **Cause** | Negative slope (WSE increases downstream) or very steep slope |
| **Resolution** | Negative slopes indicate backwater. Very steep slopes may need additional cross sections |

#### XS_EN_01 - Energy Grade Line Issue

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Energy grade line is below or near WSE |
| **Cause** | EGL should be above WSE by velocity head |
| **Resolution** | May indicate very low velocity or computational issues |

#### XS_EGL_01 - Energy Grade Line Reversal

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | Energy grade line reversal: EGL at downstream exceeds upstream |
| **Cause** | Energy is increasing in downstream direction (violates conservation) |
| **Resolution** | Review cross section geometry and results. May indicate model instability |

## Customizing XS Thresholds

```python
from ras_commander.check import create_custom_thresholds, RasCheck

# Create thresholds with stricter reach length limits
strict_thresholds = create_custom_thresholds({
    'reach_length.length_ratio_max': 1.5,  # Stricter ratio limit
    'reach_length.max_length_ft': 2000.0,  # Shorter max reach
    'profiles.velocity_max_fps': 20.0,     # Lower velocity limit
})

# Run XS check
results = RasCheck.check_xs(plan_hdf, geom_hdf, profiles, thresholds=strict_thresholds)
```

## References

- HEC-RAS Hydraulic Reference Manual, Chapter 3
- FEMA Guidelines and Specifications for Flood Hazard Mapping Partners
- HEC-RAS Applications Guide
