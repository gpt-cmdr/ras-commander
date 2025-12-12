# Message Catalog Specification

## Overview

The message catalog provides standardized message templates for all validation checks. Each message has a unique ID, severity level, and parameterized text template.

## Module Location

```
ras_commander/check/messages.py
```

## Message ID Format

Message IDs follow a consistent pattern:
```
{CHECK_TYPE}_{CATEGORY}_{NUMBER}{SUFFIX}
```

Where:
- **CHECK_TYPE**: NT, XS, STRUCT (BR/CU/IW/ST), FW, MP
- **CATEGORY**: Two-letter category code (see below)
- **NUMBER**: Two-digit number (01-99)
- **SUFFIX**: Optional position indicator (L, R, S2, S3, etc.)

## Category Codes

### NT Check Categories
| Code | Description |
|------|-------------|
| RC | Roughness Coefficient |
| TL | Transition Losses |
| RS | Roughness at Structures |

### XS Check Categories
| Code | Description |
|------|-------------|
| DT | Distance/Travel |
| IF | Ineffective Flow |
| DF | Default Flow |
| BO | Blocked Obstruction |
| EC | Encroachment/Exceedance |
| CD | Critical Depth |
| FS | Friction Slope |
| LV | Levee |
| GD | GIS Data |

### Structure Check Categories
| Code | Description |
|------|-------------|
| SD | Section Distance |
| PF | Pressure Flow |
| PW | Pressure/Weir |
| GE | Geometry |
| IF | Ineffective Flow |
| MS | Multiple Structures |

### Floodway Check Categories
| Code | Description |
|------|-------------|
| EM | Encroachment Method |
| SC | Surcharge |
| WD | Width |
| Q | Discharge |
| BC | Boundary Condition |
| ST | Structure |
| EC | Equal Conveyance |
| LW | Lateral Weir |

### Profiles Check Categories
| Code | Description |
|------|-------------|
| WS | Water Surface |
| Q | Discharge |
| TW | Top Width |
| FR | Flow Regime |
| BC | Boundary Condition |
| DQ | Data Quality |

## Implementation

```python
"""
Message Catalog - Validation Message Templates

This module provides message templates for all validation checks.
"""

from typing import Dict, Optional
from enum import Enum


class MessageType(Enum):
    """Message type categories."""
    NTCHECK = "NTCHECK"
    XSCHECK = "XSCHECK"
    STRUCCHECK = "STRUCCHECK"
    FWCHECK = "FWCHECK"
    PROFILESCHECK = "PROFILESCHECK"


# Message catalog dictionary
# Key: message_id
# Value: dict with 'message', 'help_text', 'type'
MESSAGE_CATALOG: Dict[str, Dict] = {
    # =========================================================================
    # NT CHECK MESSAGES
    # =========================================================================

    # Roughness Coefficient - Left Overbank
    "NT_RC_01L": {
        "message": "Left overbank Manning's n value ({n}) is less than 0.030",
        "help_text": "Typical overbank n values range from 0.030 to 0.200. "
                     "Very low n values may indicate modeling error or smooth surfaces.",
        "type": MessageType.NTCHECK
    },
    "NT_RC_02L": {
        "message": "Left overbank Manning's n value ({n}) exceeds 0.200",
        "help_text": "Very high n values are unusual. Verify land cover data.",
        "type": MessageType.NTCHECK
    },

    # Roughness Coefficient - Right Overbank
    "NT_RC_01R": {
        "message": "Right overbank Manning's n value ({n}) is less than 0.030",
        "help_text": "Typical overbank n values range from 0.030 to 0.200.",
        "type": MessageType.NTCHECK
    },
    "NT_RC_02R": {
        "message": "Right overbank Manning's n value ({n}) exceeds 0.200",
        "help_text": "Very high n values are unusual. Verify land cover data.",
        "type": MessageType.NTCHECK
    },

    # Roughness Coefficient - Channel
    "NT_RC_03C": {
        "message": "Channel Manning's n value ({n}) is less than 0.025",
        "help_text": "Typical channel n values range from 0.025 to 0.100. "
                     "Very low values suggest smooth concrete or other engineered channels.",
        "type": MessageType.NTCHECK
    },
    "NT_RC_04C": {
        "message": "Channel Manning's n value ({n}) exceeds 0.100",
        "help_text": "High channel n values may indicate heavy vegetation or debris.",
        "type": MessageType.NTCHECK
    },
    "NT_RC_05": {
        "message": "Overbank n values (LOB={n_lob}, ROB={n_rob}) are not greater than channel n ({n_chl})",
        "help_text": "Typically, overbank roughness exceeds channel roughness.",
        "type": MessageType.NTCHECK
    },

    # Transition Losses - At Structures
    "NT_TL_01S2": {
        "message": "Section 2: Transition coefficients ({cc}/{ce}) should be 0.3/0.5",
        "help_text": "Standard transition coefficients at structure sections are "
                     "0.3 contraction and 0.5 expansion.",
        "type": MessageType.NTCHECK
    },
    "NT_TL_01S3": {
        "message": "Section 3: Transition coefficients ({cc}/{ce}) should be 0.3/0.5",
        "help_text": "Standard transition coefficients at structure sections are "
                     "0.3 contraction and 0.5 expansion.",
        "type": MessageType.NTCHECK
    },
    "NT_TL_01S4": {
        "message": "Section 4: Transition coefficients ({cc}/{ce}) should be 0.3/0.5",
        "help_text": "Standard transition coefficients at structure sections are "
                     "0.3 contraction and 0.5 expansion.",
        "type": MessageType.NTCHECK
    },

    # Transition Losses - Regular XS
    "NT_TL_02": {
        "message": "Transition coefficients at RS {station} are {cc}/{ce}, typical values are 0.1/0.3",
        "help_text": "Standard transition coefficients at regular cross sections are "
                     "0.1 contraction and 0.3 expansion.",
        "type": MessageType.NTCHECK
    },

    # Roughness at Structures
    "NT_RS_01S2C": {
        "message": "Channel n at Section 2 ({n_s2}) should be less than Section 1 ({n_s1})",
        "help_text": "Manning's n typically decreases approaching a bridge.",
        "type": MessageType.NTCHECK
    },
    "NT_RS_01S3C": {
        "message": "Channel n at Section 3 ({n_s3}) should be less than Section 4 ({n_s4})",
        "help_text": "Manning's n typically increases leaving a bridge.",
        "type": MessageType.NTCHECK
    },

    # =========================================================================
    # XS CHECK MESSAGES
    # =========================================================================

    # Distance/Travel
    "XS_DT_01": {
        "message": "Overbank reach lengths (LOB={lob}, ROB={rob}) exceed channel ({chl}) by more than 25 ft",
        "help_text": "Large differences between overbank and channel reach lengths "
                     "may indicate model geometry issues.",
        "type": MessageType.XSCHECK
    },
    "XS_DT_02L": {
        "message": "Left overbank reach length ({lob}) is more than 2x channel ({chl})",
        "help_text": "Verify overbank flow paths are accurately represented.",
        "type": MessageType.XSCHECK
    },
    "XS_DT_02R": {
        "message": "Right overbank reach length ({rob}) is more than 2x channel ({chl})",
        "help_text": "Verify overbank flow paths are accurately represented.",
        "type": MessageType.XSCHECK
    },

    # Ineffective Flow
    "XS_IF_01L": {
        "message": "Left ineffective: WSE ({wsel}) > ground ({grelv}) but <= ineffective elev ({ineffell}) for {assignedname}",
        "help_text": "The ineffective flow area elevation may need adjustment.",
        "type": MessageType.XSCHECK
    },
    "XS_IF_01R": {
        "message": "Right ineffective: WSE ({wsel}) > ground ({grelv}) but <= ineffective elev ({ineffelr}) for {assignedname}",
        "help_text": "The ineffective flow area elevation may need adjustment.",
        "type": MessageType.XSCHECK
    },
    "XS_IF_02L": {
        "message": "Multiple ineffective flow areas on left overbank",
        "help_text": "Multiple ineffective areas are allowed but may complicate analysis.",
        "type": MessageType.XSCHECK
    },
    "XS_IF_02R": {
        "message": "Multiple ineffective flow areas on right overbank",
        "help_text": "Multiple ineffective areas are allowed but may complicate analysis.",
        "type": MessageType.XSCHECK
    },
    "XS_IF_03L": {
        "message": "Left ineffective station ({ineffstal}) extends past left bank station ({bankstal})",
        "help_text": "Ineffective flow areas should not extend into the channel.",
        "type": MessageType.XSCHECK
    },
    "XS_IF_03R": {
        "message": "Right ineffective station ({ineffstar}) extends past right bank station ({bankstar})",
        "help_text": "Ineffective flow areas should not extend into the channel.",
        "type": MessageType.XSCHECK
    },

    # Default Flow
    "XS_DF_01L": {
        "message": "Left overbank may be using default ineffective flow for {assignedname}",
        "help_text": "Verify ineffective flow areas are intentionally set.",
        "type": MessageType.XSCHECK
    },
    "XS_DF_01R": {
        "message": "Right overbank may be using default ineffective flow for {assignedname}",
        "help_text": "Verify ineffective flow areas are intentionally set.",
        "type": MessageType.XSCHECK
    },

    # Blocked Obstruction
    "XS_BO_01L": {
        "message": "Left blocked obstruction starts at left ground point",
        "help_text": "Blocked obstructions starting at ground edge may need ineffective flow.",
        "type": MessageType.XSCHECK
    },
    "XS_BO_01R": {
        "message": "Right blocked obstruction starts at right ground point",
        "help_text": "Blocked obstructions starting at ground edge may need ineffective flow.",
        "type": MessageType.XSCHECK
    },
    "XS_BO_02L": {
        "message": "Multiple left blocked obstructions may need ineffective flow areas",
        "help_text": "Consider adding ineffective flow areas to properly model blocked areas.",
        "type": MessageType.XSCHECK
    },
    "XS_BO_02R": {
        "message": "Multiple right blocked obstructions may need ineffective flow areas",
        "help_text": "Consider adding ineffective flow areas to properly model blocked areas.",
        "type": MessageType.XSCHECK
    },

    # Exceedance/Encroachment
    "XS_EC_01L": {
        "message": "WSE ({wsel}) exceeds left ground elevation ({grelv}) for {assignedname}",
        "help_text": "Water surface exceeds the cross section boundary.",
        "type": MessageType.XSCHECK
    },
    "XS_EC_01R": {
        "message": "WSE ({wsel}) exceeds right ground elevation ({grelv}) for {assignedname}",
        "help_text": "Water surface exceeds the cross section boundary.",
        "type": MessageType.XSCHECK
    },
    "XS_EC_01BUL": {
        "message": "Bridge upstream: WSE ({wsel}) exceeds left ground ({grelv}) for {assignedname}",
        "help_text": "Water surface exceeds cross section boundary at bridge upstream face.",
        "type": MessageType.XSCHECK
    },
    "XS_EC_01BUR": {
        "message": "Bridge upstream: WSE ({wsel}) exceeds right ground ({grelv}) for {assignedname}",
        "help_text": "Water surface exceeds cross section boundary at bridge upstream face.",
        "type": MessageType.XSCHECK
    },
    "XS_EC_01BDL": {
        "message": "Bridge downstream: WSE ({wsel}) exceeds left ground ({grelv}) for {assignedname}",
        "help_text": "Water surface exceeds cross section boundary at bridge downstream face.",
        "type": MessageType.XSCHECK
    },
    "XS_EC_01BDR": {
        "message": "Bridge downstream: WSE ({wsel}) exceeds right ground ({grelv}) for {assignedname}",
        "help_text": "Water surface exceeds cross section boundary at bridge downstream face.",
        "type": MessageType.XSCHECK
    },

    # Critical Depth
    "XS_CD_01": {
        "message": "Critical depth at XS with permanent ineffective flow for {assignedname}",
        "help_text": "Critical depth occurring with permanent ineffective flow may indicate issues.",
        "type": MessageType.XSCHECK
    },
    "XS_CD_02": {
        "message": "Critical depth with low channel Manning's n (<0.025) for {assignedname}",
        "help_text": "Low n values combined with critical depth may indicate modeling issues.",
        "type": MessageType.XSCHECK
    },

    # Friction Slope
    "XS_FS_01": {
        "message": "Long reach lengths may benefit from Average Conveyance friction slope method (current: {frictionslopename})",
        "help_text": "For reach lengths > 500 ft, Average Conveyance method is recommended.",
        "type": MessageType.XSCHECK
    },

    # Levee
    "XS_LV_04L": {
        "message": "Left levee overtopped for {assignedname}: WSE={wselev}, levee elev={leveel}",
        "help_text": "Water surface exceeds levee elevation.",
        "type": MessageType.XSCHECK
    },
    "XS_LV_04R": {
        "message": "Right levee overtopped for {assignedname}: WSE={wselev}, levee elev={leveer}",
        "help_text": "Water surface exceeds levee elevation.",
        "type": MessageType.XSCHECK
    },
    "XS_LV_05L": {
        "message": "Left levee: ground ({grelv}) below WSE for {assignednameMin} but levee ({leveeelvl}) above for {assignednameMax}",
        "help_text": "Levee may be ineffective for some profiles.",
        "type": MessageType.XSCHECK
    },
    "XS_LV_05R": {
        "message": "Right levee: ground ({grelv}) below WSE for {assignednameMin} but levee ({leveeelvr}) above for {assignednameMax}",
        "help_text": "Levee may be ineffective for some profiles.",
        "type": MessageType.XSCHECK
    },

    # GIS Data
    "XS_GD_01": {
        "message": "GIS cut line data may need review",
        "help_text": "LID option set at non-structure section.",
        "type": MessageType.XSCHECK
    },

    # =========================================================================
    # STRUCTURE CHECK MESSAGES
    # =========================================================================

    # Bridge Section Distance
    "BR_SD_01": {
        "message": "Distance from upstream XS to bridge ({dist} ft) is less than recommended",
        "help_text": "Upstream XS should be far enough for approach velocity to stabilize.",
        "type": MessageType.STRUCCHECK
    },
    "BR_SD_02": {
        "message": "Deck width inconsistent with section distances",
        "help_text": "Verify deck/roadway width matches structure geometry.",
        "type": MessageType.STRUCCHECK
    },
    "BR_SD_03": {
        "message": "Distance from bridge to downstream XS ({dist} ft) is less than recommended",
        "help_text": "Downstream XS should capture flow expansion.",
        "type": MessageType.STRUCCHECK
    },

    # Culvert Section Distance
    "CU_SD_01": {
        "message": "Distance from upstream XS to culvert ({dist} ft) is less than recommended",
        "help_text": "Upstream XS should be far enough for approach conditions.",
        "type": MessageType.STRUCCHECK
    },
    "CU_SD_02": {
        "message": "Distance from culvert to downstream XS ({dist} ft) is less than recommended",
        "help_text": "Downstream XS should capture outlet conditions.",
        "type": MessageType.STRUCCHECK
    },

    # Inline Weir Section Distance
    "IW_SD_01": {
        "message": "Distance from upstream XS to inline weir ({dist} ft) is less than recommended",
        "help_text": "Upstream XS should be far enough for approach conditions.",
        "type": MessageType.STRUCCHECK
    },
    "IW_SD_02": {
        "message": "Distance from inline weir to downstream XS ({dist} ft) is less than recommended",
        "help_text": "Downstream XS should capture tailwater conditions.",
        "type": MessageType.STRUCCHECK
    },

    # Bridge Flow Type
    "BR_PF_01": {
        "message": "Pressure flow computed at bridge for {profile}",
        "help_text": "Verify bridge deck elevation and low chord are correct.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PF_02": {
        "message": "Weir flow computed at bridge for {profile}",
        "help_text": "Water is flowing over the roadway.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PF_03": {
        "message": "Bridge flow type = {type} for {profile}",
        "help_text": "Informational: bridge flow type determination.",
        "type": MessageType.STRUCCHECK
    },

    # Bridge Pressure/Weir
    "BR_PW_01": {
        "message": "Pressure flow uses sluice gate coefficients (Cd = {cd})",
        "help_text": "Verify sluice gate coefficients are appropriate.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PW_02": {
        "message": "High flow method is not Energy-based",
        "help_text": "Energy method is typically recommended for high flow computations.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PW_03": {
        "message": "Weir coefficient ({c}) is outside typical range (2.5-3.1)",
        "help_text": "Typical weir coefficients range from 2.5 to 3.1.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PW_04": {
        "message": "Maximum submergence for weir flow = {sub}",
        "help_text": "Informational: submergence limit for weir calculations.",
        "type": MessageType.STRUCCHECK
    },

    # Culvert
    "CU_01": {
        "message": "Entrance loss coefficient ({Ke}) outside typical range",
        "help_text": "Typical entrance loss coefficients range from 0.2 to 0.9 depending on inlet type.",
        "type": MessageType.STRUCCHECK
    },
    "CU_02": {
        "message": "Exit loss coefficient is {Kx}, typical value is 1.0",
        "help_text": "Standard exit loss coefficient is 1.0 for sudden expansion.",
        "type": MessageType.STRUCCHECK
    },
    "CU_03": {
        "message": "Culvert scale factor ({scale}) is less than 1.0",
        "help_text": "Scale factors less than 1.0 reduce culvert capacity.",
        "type": MessageType.STRUCCHECK
    },
    "CU_04": {
        "message": "Chart {chart}, Scale {scale}, Criteria {criteria}",
        "help_text": "Culvert chart/scale configuration.",
        "type": MessageType.STRUCCHECK
    },
    "CU_05": {
        "message": "Inlet control with submerged inlet for {profile}",
        "help_text": "Verify culvert sizing for inlet control conditions.",
        "type": MessageType.STRUCCHECK
    },

    # Inline Weir
    "IW_01": {
        "message": "Gate flow ({qgate}) exceeds weir flow ({qweir}) for {profile}",
        "help_text": "Gate is controlling flow at inline structure.",
        "type": MessageType.STRUCCHECK
    },
    "IW_02": {
        "message": "Gate opening height = {height} for {profile}",
        "help_text": "Informational: gate opening configuration.",
        "type": MessageType.STRUCCHECK
    },
    "IW_03": {
        "message": "Weir coefficient ({c}) outside typical range",
        "help_text": "Typical weir coefficients range from 2.5 to 3.1.",
        "type": MessageType.STRUCCHECK
    },

    # Structure Geometry
    "ST_GE_01L": {
        "message": "Left effective station at Section 2 doesn't align with roadway",
        "help_text": "Effective flow limits should match roadway geometry.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GE_01R": {
        "message": "Right effective station at Section 2 doesn't align with roadway",
        "help_text": "Effective flow limits should match roadway geometry.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GE_02L": {
        "message": "Left effective station at Section 3 doesn't align with roadway",
        "help_text": "Effective flow limits should match roadway geometry.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GE_02R": {
        "message": "Right effective station at Section 3 doesn't align with roadway",
        "help_text": "Effective flow limits should match roadway geometry.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GE_03": {
        "message": "Ground and roadway end stations differ by more than 10 ft",
        "help_text": "Verify roadway geometry matches cross section ground data.",
        "type": MessageType.STRUCCHECK
    },

    # Structure Ineffective Flow
    "ST_IF_01": {
        "message": "No ineffective flow areas defined at Section 2",
        "help_text": "Ineffective flow areas are typically needed at structure sections.",
        "type": MessageType.STRUCCHECK
    },
    "ST_IF_02": {
        "message": "No ineffective flow areas defined at Section 3",
        "help_text": "Ineffective flow areas are typically needed at structure sections.",
        "type": MessageType.STRUCCHECK
    },
    "ST_IF_03L": {
        "message": "Left ineffective flow should extend to abutment at Section 2",
        "help_text": "Ineffective flow should extend to the bridge abutment.",
        "type": MessageType.STRUCCHECK
    },
    "ST_IF_03R": {
        "message": "Right ineffective flow should extend to abutment at Section 2",
        "help_text": "Ineffective flow should extend to the bridge abutment.",
        "type": MessageType.STRUCCHECK
    },
    "ST_IF_04L": {
        "message": "Left ineffective flow should extend to abutment at Section 3",
        "help_text": "Ineffective flow should extend to the bridge abutment.",
        "type": MessageType.STRUCCHECK
    },
    "ST_IF_04R": {
        "message": "Right ineffective flow should extend to abutment at Section 3",
        "help_text": "Ineffective flow should extend to the bridge abutment.",
        "type": MessageType.STRUCCHECK
    },
    "ST_IF_05": {
        "message": "Permanent ineffective flow may affect floodway analysis",
        "help_text": "Review permanent ineffective areas for floodway analysis.",
        "type": MessageType.STRUCCHECK
    },

    # Multiple Structures
    "ST_MS_01": {
        "message": "{count} structures at RS {station}",
        "help_text": "Multiple structures at the same river station.",
        "type": MessageType.STRUCCHECK
    },
    "ST_MS_02": {
        "message": "Mixed structure types ({types}) at RS {station}",
        "help_text": "Different structure types at the same river station.",
        "type": MessageType.STRUCCHECK
    },

    # =========================================================================
    # FLOODWAY CHECK MESSAGES
    # =========================================================================

    # Encroachment Method
    "FW_EM_01": {
        "message": "Fixed encroachment stations (Method 1) used at RS {station}",
        "help_text": "Method 1 requires justification for FEMA submittals.",
        "type": MessageType.FWCHECK
    },
    "FW_EM_02": {
        "message": "No encroachment method specified for floodway profile",
        "help_text": "Encroachment method must be specified for floodway analysis.",
        "type": MessageType.FWCHECK
    },
    "FW_EM_03": {
        "message": "Encroachment method varies within reach (methods: {methods})",
        "help_text": "Multiple encroachment methods used. Verify this is intentional.",
        "type": MessageType.FWCHECK
    },
    "FW_EM_04": {
        "message": "No encroachment at non-structure XS {station}",
        "help_text": "Encroachment should be specified at all floodway cross sections.",
        "type": MessageType.FWCHECK
    },

    # Surcharge
    "FW_SC_01": {
        "message": "Surcharge ({sc} ft) exceeds allowable ({max} ft) at RS {station}",
        "help_text": "Surcharge exceeds the regulatory limit. Floodway must be adjusted.",
        "type": MessageType.FWCHECK
    },
    "FW_SC_02": {
        "message": "Negative surcharge ({sc} ft) at RS {station} - WSE decreased",
        "help_text": "Floodway WSE is lower than base flood. Verify encroachments.",
        "type": MessageType.FWCHECK
    },
    "FW_SC_03": {
        "message": "Zero surcharge at RS {station}",
        "help_text": "No change in WSE at this location.",
        "type": MessageType.FWCHECK
    },
    "FW_SC_04": {
        "message": "Surcharge ({sc} ft) is within 0.01 ft of limit at RS {station}",
        "help_text": "Surcharge is very close to the regulatory limit.",
        "type": MessageType.FWCHECK
    },

    # Floodway Width
    "FW_WD_01": {
        "message": "Zero floodway width at RS {station}",
        "help_text": "Encroachments may have completely closed the floodway.",
        "type": MessageType.FWCHECK
    },
    "FW_WD_02": {
        "message": "Left encroachment extends beyond left bank at RS {station}",
        "help_text": "Encroachment station is outside the channel bank.",
        "type": MessageType.FWCHECK
    },
    "FW_WD_03": {
        "message": "Right encroachment extends beyond right bank at RS {station}",
        "help_text": "Encroachment station is outside the channel bank.",
        "type": MessageType.FWCHECK
    },
    "FW_WD_04": {
        "message": "Floodway narrower than channel at RS {station}",
        "help_text": "Encroachments extend into the channel.",
        "type": MessageType.FWCHECK
    },
    "FW_WD_05": {
        "message": "Steep floodway boundary slope ({slope}) at RS {station}",
        "help_text": "Large lateral slope changes in floodway boundaries may be unrealistic.",
        "type": MessageType.FWCHECK
    },

    # Discharge
    "FW_Q_01": {
        "message": "Floodway Q ({qfw}) differs from base flood ({qbf}) at RS {station}",
        "help_text": "Floodway discharge should match base flood discharge.",
        "type": MessageType.FWCHECK
    },
    "FW_Q_02": {
        "message": "Floodway Q exceeds base flood by >1% at RS {station}",
        "help_text": "Floodway discharge should not exceed base flood.",
        "type": MessageType.FWCHECK
    },
    "FW_Q_03": {
        "message": "Discharge changes within floodway reach",
        "help_text": "Check for tributaries or losses in floodway reach.",
        "type": MessageType.FWCHECK
    },

    # Boundary Condition
    "FW_BC_01": {
        "message": "Floodway starting WSE differs from base flood",
        "help_text": "Starting WSE should typically match between profiles.",
        "type": MessageType.FWCHECK
    },
    "FW_BC_02": {
        "message": "Same slope used as boundary for floodway profile",
        "help_text": "Normal depth boundary used for floodway.",
        "type": MessageType.FWCHECK
    },
    "FW_BC_03": {
        "message": "Known WSE boundary used for floodway analysis",
        "help_text": "Fixed WSE boundary condition in use.",
        "type": MessageType.FWCHECK
    },

    # Structure Floodway
    "FW_ST_01": {
        "message": "Encroachment at structure sections should match openings",
        "help_text": "Verify encroachments align with structure opening.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_02": {
        "message": "Encroachments inside bridge abutments at RS {station}",
        "help_text": "Floodway cannot encroach on bridge opening.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03": {
        "message": "No encroachment specified at structure RS {station}",
        "help_text": "Structure locations may not have encroachments.",
        "type": MessageType.FWCHECK
    },

    # Equal Conveyance
    "FW_EC_01": {
        "message": "Equal conveyance reduction option not enabled",
        "help_text": "Equal conveyance reduction is recommended for Methods 4 and 5.",
        "type": MessageType.FWCHECK
    },

    # Lateral Weir
    "FW_LW_01": {
        "message": "Lateral weir at station {sta} is active in floodway",
        "help_text": "Lateral weir may affect floodway analysis.",
        "type": MessageType.FWCHECK
    },
    "FW_LW_02": {
        "message": "Lateral weir flow >5% of main channel at station {sta}",
        "help_text": "Significant lateral weir flow in floodway analysis.",
        "type": MessageType.FWCHECK
    },

    # =========================================================================
    # PROFILES CHECK MESSAGES
    # =========================================================================

    # Water Surface
    "MP_WS_01": {
        "message": "WSE for {profile_low} is less than {profile_high} at RS {station}",
        "help_text": "Lower frequency events should have higher WSE.",
        "type": MessageType.PROFILESCHECK
    },
    "MP_WS_02": {
        "message": "WSE for {profile_low} and {profile_high} are nearly equal at RS {station}",
        "help_text": "WSE difference is less than 0.01 ft.",
        "type": MessageType.PROFILESCHECK
    },
    "MP_WS_03": {
        "message": "Large WSE difference ({diff} ft) between {profile_low} and {profile_high} at RS {station}",
        "help_text": "Large WSE jump between profiles may indicate transition issues.",
        "type": MessageType.PROFILESCHECK
    },

    # Discharge
    "MP_Q_01": {
        "message": "Discharge for {profile_low} is less than {profile_high} at RS {station}",
        "help_text": "Lower frequency events should have higher discharge.",
        "type": MessageType.PROFILESCHECK
    },
    "MP_Q_02": {
        "message": "Discharge changes unexpectedly within reach at RS {station} for {profile}",
        "help_text": "Check for tributaries or split flow.",
        "type": MessageType.PROFILESCHECK
    },

    # Top Width
    "MP_TW_01": {
        "message": "Top width for {profile_low} is less than {profile_high} at RS {station}",
        "help_text": "Lower frequency events typically have wider top width.",
        "type": MessageType.PROFILESCHECK
    },
    "MP_TW_02": {
        "message": "Large top width difference between {profile_low} and {profile_high} at RS {station}",
        "help_text": "Significant top width change between profiles.",
        "type": MessageType.PROFILESCHECK
    },

    # Flow Regime
    "MP_FR_01": {
        "message": "Critical depth in {profile_high} but not {profile_low} at RS {station}",
        "help_text": "Flow regime differs between profiles.",
        "type": MessageType.PROFILESCHECK
    },
    "MP_FR_02": {
        "message": "Flow regime changes between profiles at RS {station}",
        "help_text": "Subcritical/supercritical transition differs between profiles.",
        "type": MessageType.PROFILESCHECK
    },

    # Boundary Condition
    "MP_BC_01": {
        "message": "Boundary condition type differs between profiles",
        "help_text": "Different boundary conditions may cause inconsistencies.",
        "type": MessageType.PROFILESCHECK
    },
    "MP_BC_02": {
        "message": "Starting WSE ordering doesn't match discharge ordering",
        "help_text": "Verify boundary conditions are set correctly.",
        "type": MessageType.PROFILESCHECK
    },

    # Data Quality
    "MP_DQ_01": {
        "message": "Missing data for {profile} at RS {station}",
        "help_text": "Computation may have failed at this location.",
        "type": MessageType.PROFILESCHECK
    },
    "MP_DQ_02": {
        "message": "Computation may not have converged for {profile} at RS {station}",
        "help_text": "Check computation messages for convergence issues.",
        "type": MessageType.PROFILESCHECK
    },
}


def get_message_template(message_id: str) -> str:
    """
    Get the message template for a given message ID.

    Args:
        message_id: The message ID (e.g., "NT_RC_01L")

    Returns:
        The message template string with placeholders
    """
    if message_id in MESSAGE_CATALOG:
        return MESSAGE_CATALOG[message_id]["message"]
    return f"Unknown message ID: {message_id}"


def get_help_text(message_id: str) -> str:
    """
    Get the help text for a given message ID.

    Args:
        message_id: The message ID

    Returns:
        The help text string
    """
    if message_id in MESSAGE_CATALOG:
        return MESSAGE_CATALOG[message_id].get("help_text", "")
    return ""


def get_message_type(message_id: str) -> Optional[MessageType]:
    """
    Get the message type for a given message ID.

    Args:
        message_id: The message ID

    Returns:
        The MessageType enum value
    """
    if message_id in MESSAGE_CATALOG:
        return MESSAGE_CATALOG[message_id].get("type")
    return None


def get_all_messages_by_type(message_type: MessageType) -> Dict[str, Dict]:
    """
    Get all messages of a specific type.

    Args:
        message_type: The MessageType to filter by

    Returns:
        Dict of message_id to message info
    """
    return {
        msg_id: msg_info
        for msg_id, msg_info in MESSAGE_CATALOG.items()
        if msg_info.get("type") == message_type
    }
```

## Testing Requirements

1. **test_get_message_template**: Verify template retrieval
2. **test_get_help_text**: Verify help text retrieval
3. **test_message_format**: Verify all templates have valid placeholders
4. **test_coverage**: Ensure all check functions have corresponding messages

## Dependencies

- No external dependencies (pure Python)
