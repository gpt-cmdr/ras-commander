# Structure Check: Bridges, Culverts, and Inline Weirs

The Structure Check validates hydraulic structures including bridges, culverts, and inline weirs.

## Overview

This check examines:

1. **Section Distance (SD)** - Cross section spacing around structures
2. **Type Flow (TF)** - Flow classification (low flow classes, pressure, weir)
3. **Pressure Flow (PF)** - Pressure flow conditions and coefficients
4. **Loss Coefficients (LF)** - Entrance, exit, and friction losses
5. **Pressure/Weir (PW)** - Combined pressure and weir flow
6. **Lateral Weir (LW)** - Weir overflow characteristics
7. **Geometry (GE)** - Structure geometry alignment

## Bridge Checks (BR_*)

### Bridge Section Distance Messages (BR_SD_*)

#### BR_SD_01 - Upstream Distance Too Short

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Distance from upstream XS to bridge ({dist} ft) is less than recommended |
| **Cause** | Upstream cross section is too close to bridge |
| **Resolution** | Move upstream XS to allow approach velocity to stabilize. Typical minimum is 1-2x opening width |

#### BR_SD_02 - Deck Width Inconsistency

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Deck width inconsistent with section distances |
| **Cause** | Roadway/deck width doesn't match section geometry |
| **Resolution** | Verify deck/roadway width matches structure geometry data |

#### BR_SD_03 - Downstream Distance Too Short

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Distance from bridge to downstream XS ({dist} ft) is less than recommended |
| **Cause** | Downstream cross section too close to bridge |
| **Resolution** | Move downstream XS to capture flow expansion. Typical minimum is 1-2x opening width |

### Bridge Type Flow Messages (BR_TF_*)

Bridge flow is classified into low flow (Classes A, B, C) and high flow (pressure, weir, combined):

#### BR_TF_01 - Low Flow Class A

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Low flow Class A (free surface) computed at bridge for {profile} |
| **Cause** | Free surface flow through bridge opening. WSE below low chord on both faces |
| **Resolution** | Normal operating condition. No action required |

#### BR_TF_02 - Low Flow Class B

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Low flow Class B (free surface with hydraulic jump DS) computed at bridge for {profile} |
| **Cause** | WSE above low chord upstream, below downstream. Hydraulic jump occurs |
| **Resolution** | Transitional flow condition. May indicate capacity limitations |

#### BR_TF_03 - Low Flow Class C

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Low flow Class C (supercritical) computed at bridge for {profile} |
| **Cause** | Supercritical flow through opening |
| **Resolution** | Relatively rare. Verify geometry and flow conditions. Typically occurs with steep slopes |

#### BR_TF_04 - High Flow (Pressure Only)

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | High flow (pressure only) computed at bridge for {profile} |
| **Cause** | Bridge opening is fully submerged (pressure flow) |
| **Resolution** | Verify deck elevations. Consider scour potential under pressure conditions |

#### BR_TF_05 - High Flow (Weir Only)

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | High flow (weir only) computed at bridge for {profile} |
| **Cause** | Water overtops roadway but opening not pressurized |
| **Resolution** | Verify roadway profile elevations and weir coefficient |

#### BR_TF_06 - High Flow (Pressure and Weir)

| Field | Value |
|-------|-------|
| **Severity** | ERROR |
| **Message** | High flow (pressure and weir combined) computed at bridge for {profile} |
| **Cause** | Opening pressurized AND water overtops roadway |
| **Resolution** | Severe condition - structure significantly undersized. Review design adequacy |

### Bridge Pressure Flow Messages (BR_PF_*)

#### BR_PF_01 - Pressure Flow Detected

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Pressure flow detected at bridge for {profile} |
| **Cause** | Bridge opening is submerged |
| **Resolution** | Verify deck and low chord elevations are correct |

#### BR_PF_02 - Weir Flow Detected

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Weir flow detected over bridge deck for {profile} |
| **Cause** | Water flows over roadway |
| **Resolution** | Verify roadway profile elevations |

#### BR_PF_05 - Orifice Flow Submergence

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Submergence ratio ({submergence}) indicates orifice flow |
| **Cause** | High submergence ratio (TW/HW > 0.8) indicates orifice conditions |
| **Resolution** | Verify model correctly computes orifice flow conditions |

#### BR_PF_06 - Tailwater Controls

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Tailwater controls pressure flow: TW elev near deck |
| **Cause** | Tailwater elevation near or above deck controls flow |
| **Resolution** | Verify downstream boundary conditions and channel geometry |

#### BR_PF_08 - Pressure Flow Coefficient

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Pressure flow coefficient ({coef}) outside typical range (0.8-1.0) |
| **Cause** | Coefficient below 0.8 indicates high losses; above 1.0 is unrealistic |
| **Resolution** | Review coefficient setting in bridge data |

### Bridge Loss Coefficient Messages (BR_LF_*)

#### BR_LF_01 - Contraction Coefficient

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Bridge contraction coefficient ({coef}) outside typical range (0.1-0.6) |
| **Cause** | Coefficient outside typical range for abutment types |
| **Resolution** | Review coefficient based on abutment geometry (vertical wall, wing wall, spill-through) |

#### BR_LF_02 - Expansion Coefficient

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Bridge expansion coefficient ({coef}) outside typical range (0.3-0.8) |
| **Cause** | Coefficient outside typical expansion range |
| **Resolution** | Review coefficient based on downstream conditions |

### Bridge Lateral Weir Messages (BR_LW_*)

#### BR_LW_01 - Weir Length Mismatch

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Bridge lateral weir length differs significantly from roadway width |
| **Cause** | Weir length should correspond to roadway width |
| **Resolution** | Verify weir length in structure data |

#### BR_LW_02 - Weir Coefficient

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Bridge weir coefficient ({coef}) outside typical range (2.5-3.1) |
| **Cause** | Coefficient outside typical range |
| **Resolution** | Typical value is 2.6 for roadway overtopping. Sharp-crested maximum is ~3.1 |

## Culvert Checks (CU_*/CV_*)

### Culvert Section Distance Messages (CU_SD_*)

#### CU_SD_01 - Upstream Distance

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Distance from upstream XS to culvert is less than recommended |
| **Cause** | Upstream section too close to culvert inlet |
| **Resolution** | Move upstream XS to capture approach conditions |

#### CU_SD_02 - Downstream Distance

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Distance from culvert to downstream XS is less than recommended |
| **Cause** | Downstream section too close to culvert outlet |
| **Resolution** | Move downstream XS to capture outlet conditions |

### Culvert Type Flow Messages (CV_TF_*)

| Message ID | Flow Type | Description |
|------------|-----------|-------------|
| CV_TF_01 | Type 1 | Outlet control, unsubmerged |
| CV_TF_02 | Type 2 | Outlet control, submerged outlet |
| CV_TF_03 | Type 3 | Inlet control, unsubmerged |
| CV_TF_04 | Type 4 | Inlet control, submerged |
| CV_TF_05 | Type 5 | Full flow |
| CV_TF_06 | Type 6 | Pressure flow |
| CV_TF_07 | Type 7 | Overtopping |

### Culvert Loss Coefficient Messages (CV_LF_*)

#### CV_LF_01 - Entrance Loss Coefficient

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Entrance loss coefficient ({Ke}) outside typical range (0.2-0.9) |
| **Cause** | Coefficient doesn't match typical inlet types |
| **Resolution** | Typical: 0.2 (well-rounded), 0.5 (square-edged), 0.9 (projecting) |

#### CV_LF_02 - Exit Loss Coefficient

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Exit loss coefficient ({Kx}) outside typical range (0.5-1.0) |
| **Cause** | Standard exit coefficient is 1.0 for sudden expansion |
| **Resolution** | Values <1.0 may be used for gradual transitions |

### Culvert Pressure Flow Messages (CV_PF_*)

#### CV_PF_01 - Pressure Flow

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Pressure flow detected at culvert for {profile} |
| **Cause** | Culvert operating under pressure conditions |
| **Resolution** | Review culvert sizing. May indicate undersized structure |

#### CV_PF_02 - Deep Submergence

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Inlet submerged by more than 1.2D (HW/D = {hw_ratio}) |
| **Cause** | Headwater depth exceeds 1.2x culvert diameter |
| **Resolution** | Consider increasing culvert size or adding barrels |

## Inline Weir Checks (IW_*)

### Inline Weir Section Distance Messages (IW_SD_*)

#### IW_SD_01 - Upstream Distance

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Distance from upstream XS to inline weir is less than recommended |
| **Cause** | Upstream section too close to weir |
| **Resolution** | Move upstream XS for approach conditions |

#### IW_SD_02 - Downstream Distance

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Distance from inline weir to downstream XS is less than recommended |
| **Cause** | Downstream section too close to weir |
| **Resolution** | Move downstream XS for tailwater conditions |

### Inline Weir Type Flow Messages (IW_TF_*)

#### IW_TF_01 - Weir Flow Only

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Inline weir has weir flow only (no gate flow) for {profile} |
| **Cause** | Water flowing over crest, gates not contributing |
| **Resolution** | Normal when headwater above crest and gates closed/absent |

#### IW_TF_02 - Gate Flow Only

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Inline weir has gate flow only (no weir flow) for {profile} |
| **Cause** | Flow through gates, headwater below crest |
| **Resolution** | Normal condition when gates are open |

#### IW_TF_03 - Combined Weir and Gate Flow

| Field | Value |
|-------|-------|
| **Severity** | INFO |
| **Message** | Inline weir has combined weir and gate flow for {profile} |
| **Cause** | Both weir overflow and gate flow occurring |
| **Resolution** | Verify gate operations and weir coefficient |

#### IW_TF_04 - Submerged Weir

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Inline weir is submerged: tailwater approaches crest for {profile} |
| **Cause** | Tailwater elevation near or above weir crest |
| **Resolution** | Submergence reduces capacity. Verify downstream conditions |

### Inline Weir Coefficient Messages (IW_*)

#### IW_03 - Weir Coefficient

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Weir coefficient ({c}) outside typical range |
| **Cause** | Coefficient outside 2.5-3.1 range |
| **Resolution** | Typical broad-crested: 2.6-2.8. Sharp-crested: up to 3.1 |

## Structure Geometry Messages (ST_GE_*)

#### ST_GE_01L / ST_GE_01R - Section 2 Alignment

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Left/Right effective station at Section 2 doesn't align with roadway |
| **Cause** | Effective flow limits don't match roadway geometry |
| **Resolution** | Verify ineffective flow limits correspond to bridge opening |

#### ST_GE_02L / ST_GE_02R - Section 3 Alignment

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Left/Right effective station at Section 3 doesn't align with roadway |
| **Cause** | Effective flow limits don't match downstream roadway geometry |
| **Resolution** | Verify ineffective flow limits at downstream face |

## Structure Distance Messages (ST_DT_*)

#### ST_DT_01 - Upstream Distance for Expansion

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Upstream distance too short for flow expansion at {name} |
| **Cause** | Cross section too close to structure |
| **Resolution** | Typical minimum is 1-2x structure opening width |

#### ST_DT_02 - Downstream Distance for Recovery

| Field | Value |
|-------|-------|
| **Severity** | WARNING |
| **Message** | Downstream distance too short for contraction recovery at {name} |
| **Cause** | Cross section doesn't capture flow re-expansion |
| **Resolution** | Move downstream section further from structure |

## References

- HEC-RAS Hydraulic Reference Manual, Chapter 5: Modeling Bridges
- HEC-RAS Hydraulic Reference Manual, Chapter 6: Modeling Culverts
- FHWA Hydraulic Design of Highway Culverts (HDS-5)
- FHWA Hydraulics of Bridge Waterways (HDS-1)
