"""
Message Catalog - Validation Message Templates for RasCheck.

This module provides message templates for all validation checks.
Each message has a unique ID, severity level, and parameterized text template.

Message ID Format:
    {CHECK_TYPE}_{CATEGORY}_{NUMBER}{SUFFIX}

Where:
- CHECK_TYPE: NT, XS, STRUCT (BR/CU/IW/ST), FW, MP
- CATEGORY: Two-letter category code
- NUMBER: Two-digit number (01-99)
- SUFFIX: Optional position indicator (L, R, S2, S3, etc.)
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
    "NT_TL_01S1": {
        "message": "Section 1: Transition coefficients ({cc}/{ce}) should be 0.3/0.5",
        "help_text": "Standard transition coefficients at structure sections are "
                     "0.3 contraction and 0.5 expansion.",
        "type": MessageType.NTCHECK
    },
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

    # Bridge Internal Manning's n Comparison
    "NT_RS_02BUC": {
        "message": "Bridge upstream internal section (Section 2) has different Manning's n values than upstream XS (Section 1)",
        "help_text": "The Manning's n values within the bridge opening at the upstream face (Section 2) differ from "
                     "those at the upstream approach cross section (Section 1). In the bridge 4-section model, "
                     "Section 2 represents the bridge upstream face between the abutments. Different n-values here "
                     "may be intentional (e.g., concrete channel lining under bridge) or may indicate data entry "
                     "issues. Review to ensure the Manning's n values accurately represent the bridge opening conditions.",
        "type": MessageType.NTCHECK
    },
    "NT_RS_02BDC": {
        "message": "Bridge downstream internal section (Section 3) has different Manning's n values than downstream XS (Section 4)",
        "help_text": "The Manning's n values within the bridge opening at the downstream face (Section 3) differ from "
                     "those at the downstream approach cross section (Section 4). In the bridge 4-section model, "
                     "Section 3 represents the bridge downstream face between the abutments. Different n-values here "
                     "may be intentional (e.g., concrete channel lining under bridge) or may indicate data entry "
                     "issues. Review to ensure the Manning's n values accurately represent the bridge opening conditions.",
        "type": MessageType.NTCHECK
    },

    # N-Value Variation
    "NT_VR_01L": {
        "message": "Large LOB n-value change ({pct:.0f}%) between RS {station_us} ({n_us:.3f}) and RS {station_ds} ({n_ds:.3f})",
        "help_text": "Large changes in Manning's n between adjacent cross sections may indicate "
                     "data entry error or need for additional intermediate cross sections.",
        "type": MessageType.NTCHECK
    },
    "NT_VR_01C": {
        "message": "Large channel n-value change ({pct:.0f}%) between RS {station_us} ({n_us:.3f}) and RS {station_ds} ({n_ds:.3f})",
        "help_text": "Large changes in Manning's n between adjacent cross sections may indicate "
                     "data entry error or need for additional intermediate cross sections.",
        "type": MessageType.NTCHECK
    },
    "NT_VR_01R": {
        "message": "Large ROB n-value change ({pct:.0f}%) between RS {station_us} ({n_us:.3f}) and RS {station_ds} ({n_ds:.3f})",
        "help_text": "Large changes in Manning's n between adjacent cross sections may indicate "
                     "data entry error or need for additional intermediate cross sections.",
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

    # Discharge Conservation
    "XS_DC_01": {
        "message": "Discharge change within reach for {profile}",
        "help_text": "Unexpected discharge change within reach. Verify no unmodeled inflows or diversions.",
        "type": MessageType.XSCHECK
    },

    # Flow Regime
    "XS_FR_01": {
        "message": "Flow regime transition: subcritical to supercritical for {profile}",
        "help_text": "Subcritical to supercritical flow transition detected. "
                     "This may indicate a control section or steep slope.",
        "type": MessageType.XSCHECK
    },
    "XS_FR_02": {
        "message": "Flow regime transition: supercritical to subcritical (hydraulic jump) for {profile}",
        "help_text": "Supercritical to subcritical flow transition (hydraulic jump) detected. "
                     "Verify model stability and energy losses at this location.",
        "type": MessageType.XSCHECK
    },
    "XS_FR_03": {
        "message": "Extreme Froude number ({froude}) for {profile}",
        "help_text": "Very high Froude number may indicate unstable flow conditions or geometry issues.",
        "type": MessageType.XSCHECK
    },

    # Levee
    "XS_LV_01L": {
        "message": "Left levee station ({levee_sta:.1f}) is outside cross section extent ({xs_min_sta:.1f} to {xs_max_sta:.1f})",
        "help_text": "The left levee station is outside the cross section limits. "
                     "Verify the levee station is correctly defined within the cross section.",
        "type": MessageType.XSCHECK
    },
    "XS_LV_01R": {
        "message": "Right levee station ({levee_sta:.1f}) is outside cross section extent ({xs_min_sta:.1f} to {xs_max_sta:.1f})",
        "help_text": "The right levee station is outside the cross section limits. "
                     "Verify the levee station is correctly defined within the cross section.",
        "type": MessageType.XSCHECK
    },
    "XS_LV_02L": {
        "message": "Left levee elevation ({levee_elev:.2f}) is below adjacent ground elevation ({ground_elev:.2f})",
        "help_text": "The left levee elevation should be higher than the adjacent ground. "
                     "A levee below ground indicates possible data entry error.",
        "type": MessageType.XSCHECK
    },
    "XS_LV_02R": {
        "message": "Right levee elevation ({levee_elev:.2f}) is below adjacent ground elevation ({ground_elev:.2f})",
        "help_text": "The right levee elevation should be higher than the adjacent ground. "
                     "A levee below ground indicates possible data entry error.",
        "type": MessageType.XSCHECK
    },
    "XS_LV_03L": {
        "message": "Left levee ({levee_elev:.2f}) is not at local high point (max nearby ground: {max_ground:.2f})",
        "help_text": "The left levee elevation should be at the highest point in its vicinity. "
                     "A levee not at a high point may not function as intended to contain flow.",
        "type": MessageType.XSCHECK
    },
    "XS_LV_03R": {
        "message": "Right levee ({levee_elev:.2f}) is not at local high point (max nearby ground: {max_ground:.2f})",
        "help_text": "The right levee elevation should be at the highest point in its vicinity. "
                     "A levee not at a high point may not function as intended to contain flow.",
        "type": MessageType.XSCHECK
    },
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

    # Conveyance Tube and Contraction Coefficient
    "XS_CT_01": {
        "message": "Non-standard conveyance subdivisions: LOB={lob_slices}, Chan={chan_slices}, ROB={rob_slices}",
        "help_text": "HEC-RAS uses conveyance subdivisions to compute flow distribution. "
                     "Standard values are 1-5 per region. Very high or very low values may affect accuracy.",
        "type": MessageType.XSCHECK
    },
    "XS_CT_02": {
        "message": "Zero conveyance subdivisions in {region} region",
        "help_text": "Zero subdivisions may indicate a modeling issue.",
        "type": MessageType.XSCHECK
    },
    "XS_CT_03": {
        "message": "Contraction coefficient ({cc:.2f}) at junction RS {station} differs from adjacent sections",
        "help_text": "At river junctions, contraction coefficients should transition smoothly between "
                     "connecting reaches. Large differences in coefficients at junction cross sections "
                     "may cause energy balance inconsistencies. Review transition losses at junctions.",
        "type": MessageType.XSCHECK
    },
    "XS_CT_04": {
        "message": "Contraction coefficient varies significantly ({cc_us:.2f} to {cc_ds:.2f}) between RS {station_us} and RS {station_ds}",
        "help_text": "Large variations in contraction coefficients between adjacent cross sections "
                     "may indicate inconsistent model setup. Coefficients should generally be uniform "
                     "along a reach unless specific hydraulic conditions warrant changes (e.g., near structures).",
        "type": MessageType.XSCHECK
    },

    # Channel Width
    "XS_CW_01": {
        "message": "Channel width ratio ({ratio:.2f}) between RS {station_us} ({width_us:.1f} ft) and RS {station_ds} ({width_ds:.1f} ft) exceeds threshold",
        "help_text": "Large changes in channel width between adjacent cross sections (>2x or <0.5x) "
                     "may indicate geometry data issues, need for intermediate cross sections, or "
                     "significant channel transitions that should be reviewed. Gradual transitions "
                     "are generally preferred for stable HEC-RAS computations.",
        "type": MessageType.XSCHECK
    },

    # Split Flow
    "XS_SW_01": {
        "message": "Split flow detected at {location}",
        "help_text": "Split flow occurs when water divides into multiple paths. "
                     "Verify flow distribution is properly modeled.",
        "type": MessageType.XSCHECK
    },

    # Junction
    "XS_JT_01": {
        "message": "Junction at {junction_name}: energy balance check needed",
        "help_text": "Junctions should maintain energy balance between connecting reaches.",
        "type": MessageType.XSCHECK
    },
    "XS_JT_02": {
        "message": "Multiple reaches connect at {junction_name}",
        "help_text": "Multiple reach connections may require careful energy balance review.",
        "type": MessageType.XSCHECK
    },

    # GIS Data
    "XS_GD_01": {
        "message": "GIS cut line data may need review at RS {station}",
        "help_text": "Cross section uses non-default centerline which may indicate GIS import.",
        "type": MessageType.XSCHECK
    },
    "XS_GD_02": {
        "message": "Default centerline used at RS {station}",
        "help_text": "Cross section using default centerline instead of GIS cut line.",
        "type": MessageType.XSCHECK
    },

    # Cross Section Area Change
    "XS_AR_01": {
        "message": "Large flow area change ({pct:.0f}%) between RS {station_us} ({area_us:.0f} sq ft) and RS {station_ds} ({area_ds:.0f} sq ft) for {profile}",
        "help_text": "Flow area changes significantly between adjacent cross sections. "
                     "Large changes (>50%) may indicate geometry issues or need for additional intermediate sections.",
        "type": MessageType.XSCHECK
    },

    # Wetted Perimeter Anomaly
    "XS_WP_01": {
        "message": "Wetted perimeter anomaly: {wp:.0f} ft is {relation} than expected for area {area:.0f} sq ft at RS {station} for {profile}",
        "help_text": "Wetted perimeter is unusually large or small relative to flow area. "
                     "This may indicate an irregular cross section shape or data entry error.",
        "type": MessageType.XSCHECK
    },

    # Hydraulic Radius Anomaly
    "XS_HK_01": {
        "message": "Hydraulic radius ({hr:.2f} ft) out of expected range at RS {station} for {profile}",
        "help_text": "Hydraulic radius (Area/Wetted Perimeter) is unusually high or low. "
                     "Very high values may indicate wide shallow flow; very low values may indicate geometry issues.",
        "type": MessageType.XSCHECK
    },

    # Energy Grade Line Below WSE
    "XS_EN_01": {
        "message": "Energy grade line ({egl:.2f} ft) is below or near WSE ({wsel:.2f} ft) at RS {station} for {profile}",
        "help_text": "Energy grade line should be above water surface elevation by velocity head. "
                     "This may indicate computational issues or very low velocity.",
        "type": MessageType.XSCHECK
    },

    # Water Surface Slope Anomaly
    "XS_SL_01": {
        "message": "Water surface slope anomaly ({slope:.6f}) between RS {station_us} and RS {station_ds} for {profile}",
        "help_text": "Water surface slope is negative (WSE increases downstream) or excessively steep. "
                     "Negative slopes may indicate backwater effects or computational issues.",
        "type": MessageType.XSCHECK
    },
    "XS_SL_02": {
        "message": "Steep water surface slope ({slope:.4f} ft/ft) between RS {station_us} and RS {station_ds} for {profile}",
        "help_text": "Water surface slope exceeds typical range (>0.02 ft/ft). "
                     "Very steep slopes may indicate rapidly varied flow conditions requiring additional cross sections.",
        "type": MessageType.XSCHECK
    },

    # Velocity Distribution Coefficient (Alpha) Anomaly
    "XS_VD_01": {
        "message": "Velocity distribution coefficient (alpha={alpha:.2f}) outside typical range at RS {station} for {profile}",
        "help_text": "Alpha coefficient should typically range from 1.0 to 2.0. "
                     "Values outside this range may indicate unusual flow distribution or geometry issues.",
        "type": MessageType.XSCHECK
    },

    # Energy Grade Line Reversal
    "XS_EGL_01": {
        "message": "Energy grade line reversal: EGL at RS {station_ds} ({egl_ds:.2f} ft) exceeds RS {station_us} ({egl_us:.2f} ft) for {profile}",
        "help_text": "Energy grade line should decrease in the downstream direction for subcritical flow. "
                     "A reversal indicates energy is increasing downstream which violates energy conservation.",
        "type": MessageType.XSCHECK
    },

    # Top Width Anomaly
    "XS_TW_01": {
        "message": "Top width ({tw:.0f} ft) is {relation} at RS {station} for {profile}",
        "help_text": "Top width is unusually large or small relative to flow depth and area. "
                     "Very wide sections may indicate floodplain flow; very narrow may indicate geometry constraints.",
        "type": MessageType.XSCHECK
    },
    "XS_TW_02": {
        "message": "Large top width change ({pct:.0f}%) between RS {station_us} ({tw_us:.0f} ft) and RS {station_ds} ({tw_ds:.0f} ft) for {profile}",
        "help_text": "Top width changes significantly between adjacent cross sections. "
                     "This may indicate floodplain transitions or geometry issues.",
        "type": MessageType.XSCHECK
    },

    # Multiple Flow Paths / Split Channel
    "XS_MF_01": {
        "message": "Multiple flow paths detected at RS {station}: ineffective areas split active flow for {profile}",
        "help_text": "Cross section has ineffective flow areas that create multiple separate flow paths. "
                     "This may be intentional (islands) but should be verified.",
        "type": MessageType.XSCHECK
    },

    # Minimum Energy Loss Check
    "XS_EL_01": {
        "message": "Low energy loss ({loss:.3f} ft) between RS {station_us} and RS {station_ds} for {profile}",
        "help_text": "Energy loss between cross sections is very low (<0.01 ft). "
                     "This may indicate the sections are too close together or roughness is too low.",
        "type": MessageType.XSCHECK
    },
    "XS_EL_02": {
        "message": "High energy loss ({loss:.2f} ft) between RS {station_us} and RS {station_ds} for {profile}",
        "help_text": "Energy loss between cross sections is unusually high (>5 ft). "
                     "Verify roughness values, transition coefficients, and geometry.",
        "type": MessageType.XSCHECK
    },

    # Conveyance Anomaly
    "XS_CV_01": {
        "message": "Conveyance decrease in downstream direction at RS {station}: upstream K={k_us:.0f}, downstream K={k_ds:.0f} for {profile}",
        "help_text": "Conveyance typically increases or remains stable in downstream direction for gradually varied flow. "
                     "Significant decreases may indicate geometry constrictions or roughness changes.",
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

    # Bridge Type Flow Checks (BR_TF_*) - Low and High Flow Classifications
    "BR_TF_01": {
        "message": "Low flow Class A (free surface) computed at bridge for {profile}",
        "help_text": "Class A low flow: Water surface remains below the low chord on both "
                     "upstream and downstream faces. Free surface flow through opening.",
        "type": MessageType.STRUCCHECK
    },
    "BR_TF_02": {
        "message": "Low flow Class B (free surface with hydraulic jump DS) computed at bridge for {profile}",
        "help_text": "Class B low flow: Water surface rises above low chord on upstream face but "
                     "drops below low chord on downstream face, creating a hydraulic jump. "
                     "This transitional flow condition may indicate capacity limitations.",
        "type": MessageType.STRUCCHECK
    },
    "BR_TF_03": {
        "message": "Low flow Class C (supercritical) computed at bridge for {profile}",
        "help_text": "Class C low flow: Supercritical flow through bridge opening. This is relatively "
                     "rare and typically occurs with steep slopes or significant constrictions. "
                     "Verify geometry and flow conditions.",
        "type": MessageType.STRUCCHECK
    },
    "BR_TF_04": {
        "message": "High flow (pressure only) computed at bridge for {profile}",
        "help_text": "Pressure flow: Water surface is above the high chord (deck) on upstream "
                     "and/or downstream faces. Bridge opening is fully submerged. Verify deck "
                     "elevations and consider scour potential.",
        "type": MessageType.STRUCCHECK
    },
    "BR_TF_05": {
        "message": "High flow (weir only) computed at bridge for {profile}",
        "help_text": "Weir flow: Water is overtopping the bridge deck/roadway but the opening "
                     "is not flowing under pressure. Flow passes both through opening and over road.",
        "type": MessageType.STRUCCHECK
    },
    "BR_TF_06": {
        "message": "High flow (pressure and weir combined) computed at bridge for {profile}",
        "help_text": "Combined pressure and weir flow: Bridge opening is flowing under pressure "
                     "while water also overtops the deck. This severe flow condition indicates "
                     "the structure is significantly undersized for the event.",
        "type": MessageType.STRUCCHECK
    },

    # Bridge Pressure Flow Checks (BR_PF_*) - Results-based Flow Detection
    "BR_PF_01": {
        "message": "Pressure flow detected at bridge for {profile}",
        "help_text": "Verify bridge deck elevation and low chord are correct. Pressure flow "
                     "indicates the bridge opening is submerged.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PF_02": {
        "message": "Weir flow detected over bridge deck for {profile}",
        "help_text": "Water is flowing over the roadway. Verify roadway profile elevations.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PF_03": {
        "message": "Flow type ({flow_type}) for highest frequency profile differs from lower frequency profiles",
        "help_text": "The flow regime for the most frequent event (typically smaller flow) differs "
                     "from less frequent events. This may indicate a flow regime transition. "
                     "Review results to ensure this is physically reasonable.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PF_04": {
        "message": "Pressure flow occurring with Class B low flow at bridge for {profile}",
        "help_text": "Pressure flow combined with Class B low flow (hydraulic jump downstream) indicates "
                     "transitional conditions. The upstream water surface is above the low chord while "
                     "downstream is below, and pressure flow is occurring through the opening. This complex "
                     "flow condition requires careful review of the bridge hydraulics.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PF_05": {
        "message": "Submergence ratio ({submergence:.2f}) indicates orifice flow at bridge for {profile}",
        "help_text": "When the submergence ratio (tailwater depth / headwater depth above deck) exceeds "
                     "approximately 0.8, flow transitions from pressure (sluice gate) to orifice conditions. "
                     "This affects the discharge coefficient and head-discharge relationship. Verify that "
                     "the model is correctly computing orifice flow conditions.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PF_06": {
        "message": "Tailwater controls pressure flow at bridge for {profile}: TW elev ({tw_elev:.2f}) near deck ({deck_elev:.2f})",
        "help_text": "When tailwater elevation approaches or exceeds the bridge deck elevation, tailwater "
                     "controls the pressure flow computation rather than headwater. This submerged condition "
                     "reduces capacity significantly. Verify tailwater boundary conditions and downstream "
                     "channel geometry.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PF_07": {
        "message": "Energy-based pressure flow method mismatch: high flow method is {method} for {profile}",
        "help_text": "For pressure flow conditions, the Energy method is typically recommended for high flow "
                     "computations to properly account for energy losses through the submerged bridge opening. "
                     "Using Momentum or other methods may not correctly compute the head-discharge relationship "
                     "under pressure conditions. Consider changing to Energy method.",
        "type": MessageType.STRUCCHECK
    },
    "BR_PF_08": {
        "message": "Pressure flow coefficient ({coef:.2f}) outside typical range (0.8-1.0) at bridge for {profile}",
        "help_text": "Typical pressure flow (sluice gate) coefficients range from 0.8 to 1.0. "
                     "Coefficients below 0.8 indicate significant entrance losses or blockage. "
                     "Coefficients above 1.0 are physically unrealistic. Verify the coefficient "
                     "setting in the bridge data.",
        "type": MessageType.STRUCCHECK
    },

    # Bridge Loss Coefficients
    "BR_LF_01": {
        "message": "Bridge contraction coefficient ({coef}) outside typical range (0.1-0.6)",
        "help_text": "Typical bridge contraction coefficients range from 0.1 to 0.6 depending on abutment type.",
        "type": MessageType.STRUCCHECK
    },
    "BR_LF_02": {
        "message": "Bridge expansion coefficient ({coef}) outside typical range (0.3-0.8)",
        "help_text": "Typical bridge expansion coefficients range from 0.3 to 0.8 depending on abutment type.",
        "type": MessageType.STRUCCHECK
    },
    "BR_LF_03": {
        "message": "Bridge low flow coefficient ({coef:.2f}) outside typical range ({min:.2f}-{max:.2f})",
        "help_text": "Low flow loss coefficients depend on the flow class (A, B, or C) and bridge geometry. "
                     "Class A: Energy method uses Yarnell, standard contraction/expansion. "
                     "Class B/C: Momentum or empirical methods may use different coefficients. "
                     "Verify coefficients match the expected flow regime and methodology.",
        "type": MessageType.STRUCCHECK
    },

    # Bridge Lateral Weir Checks
    "BR_LW_01": {
        "message": "Bridge lateral weir length ({length:.1f} ft) differs significantly from roadway width ({roadway:.1f} ft)",
        "help_text": "The lateral weir overflow length should reasonably correspond to the roadway width. "
                     "Large discrepancies may indicate geometry data entry errors. The weir length affects "
                     "the weir flow computation: Q = C * L * H^1.5",
        "type": MessageType.STRUCCHECK
    },
    "BR_LW_02": {
        "message": "Bridge weir coefficient ({coef:.2f}) outside typical range (2.5-3.1) at {name}",
        "help_text": "Weir coefficients for bridge deck overflow typically range from 2.5 (broad-crested) "
                     "to 3.1 (sharp-crested). A value of 2.6 is commonly used for roadway overtopping. "
                     "Coefficients outside this range may indicate data entry error or unusual geometry.",
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

    # =========================================================================
    # CULVERT FLOW TYPE CHECKS (CV_TF_*)
    # =========================================================================
    "CV_TF_01": {
        "message": "Type 1 flow (outlet control, unsubmerged) at culvert '{culvert}' for {profile}",
        "help_text": "Outlet control with unsubmerged inlet and outlet. Flow is controlled by "
                     "tailwater conditions. This is a normal operating condition.",
        "type": MessageType.STRUCCHECK
    },
    "CV_TF_02": {
        "message": "Type 2 flow (outlet control, submerged outlet) at culvert '{culvert}' for {profile}",
        "help_text": "Outlet control with submerged outlet. Flow is controlled by tailwater "
                     "conditions with outlet below tailwater.",
        "type": MessageType.STRUCCHECK
    },
    "CV_TF_03": {
        "message": "Type 3 flow (inlet control, unsubmerged) at culvert '{culvert}' for {profile}",
        "help_text": "Inlet control with unsubmerged inlet. Flow is controlled by inlet geometry. "
                     "Culvert capacity is limited by inlet conditions.",
        "type": MessageType.STRUCCHECK
    },
    "CV_TF_04": {
        "message": "Type 4 flow (inlet control, submerged) at culvert '{culvert}' for {profile}",
        "help_text": "Inlet control with submerged inlet. Flow acts like orifice flow. "
                     "Headwater is ponded above the culvert inlet.",
        "type": MessageType.STRUCCHECK
    },
    "CV_TF_05": {
        "message": "Type 5 flow (full flow) at culvert '{culvert}' for {profile}",
        "help_text": "Full barrel flow throughout culvert length. Culvert is flowing full "
                     "under pressure. Review if this is expected for design conditions.",
        "type": MessageType.STRUCCHECK
    },
    "CV_TF_06": {
        "message": "Type 6 flow (pressure flow) at culvert '{culvert}' for {profile}",
        "help_text": "Pressure flow detected in culvert. Flow is pressurized through "
                     "the entire barrel. May indicate undersized culvert.",
        "type": MessageType.STRUCCHECK
    },
    "CV_TF_07": {
        "message": "Type 7 flow (overtopping) at culvert '{culvert}' for {profile}",
        "help_text": "Culvert overtopping detected. Water flows both through culvert and "
                     "over roadway. Verify roadway data and design capacity.",
        "type": MessageType.STRUCCHECK
    },

    # =========================================================================
    # CULVERT LOSS COEFFICIENT CHECKS (CV_LF_*)
    # =========================================================================
    "CV_LF_01": {
        "message": "Entrance loss coefficient ({Ke:.2f}) outside typical range (0.2-0.9) at culvert '{culvert}'",
        "help_text": "Typical entrance loss coefficients: 0.2 (well-rounded inlet), "
                     "0.5 (square-edged inlet), 0.9 (projecting inlet). Values outside "
                     "this range may indicate data entry error.",
        "type": MessageType.STRUCCHECK
    },
    "CV_LF_02": {
        "message": "Exit loss coefficient ({Kx:.2f}) outside typical range (0.5-1.0) at culvert '{culvert}'",
        "help_text": "Standard exit loss coefficient is 1.0 for sudden expansion into "
                     "tailwater pool. Values less than 1.0 may be used for gradual "
                     "transitions. Verify exit conditions.",
        "type": MessageType.STRUCCHECK
    },
    "CV_LF_03": {
        "message": "Bend loss coefficient ({Kb:.2f}) applied at culvert '{culvert}'",
        "help_text": "Bend losses are applied for non-straight culverts. Typical values "
                     "range from 0.1-0.5 depending on bend angle and radius.",
        "type": MessageType.STRUCCHECK
    },

    # =========================================================================
    # CULVERT PRESSURE FLOW CHECKS (CV_PF_*)
    # =========================================================================
    "CV_PF_01": {
        "message": "Pressure flow detected at culvert '{culvert}' for {profile}",
        "help_text": "Culvert is operating under pressure flow conditions. Both inlet "
                     "and outlet may be submerged. Review culvert sizing.",
        "type": MessageType.STRUCCHECK
    },
    "CV_PF_02": {
        "message": "Inlet submerged by more than 1.2D (HW/D = {hw_ratio:.2f}) at culvert '{culvert}' for {profile}",
        "help_text": "Headwater depth exceeds 1.2 times culvert diameter/rise. Deep "
                     "submergence may indicate undersized culvert. Consider increasing "
                     "culvert size or adding additional barrels.",
        "type": MessageType.STRUCCHECK
    },

    # =========================================================================
    # CULVERT PRESSURE/WEIR COMBINED CHECKS (CV_PW_*)
    # =========================================================================
    "CV_PW_01": {
        "message": "Combined pressure and weir flow at culvert '{culvert}' for {profile}",
        "help_text": "Flow occurs both through culvert (pressure/orifice) and over "
                     "roadway (weir). This combined flow condition is typical when "
                     "headwater exceeds roadway crest elevation.",
        "type": MessageType.STRUCCHECK
    },

    # =========================================================================
    # CULVERT CHART/SCALE CHECKS (CV_CF_*)
    # =========================================================================
    "CV_CF_01": {
        "message": "Chart {chart} with scale {scale} at culvert '{culvert}'",
        "help_text": "Culvert uses FHWA inlet control charts. Chart number and scale "
                     "determine inlet control capacity. Verify chart selection matches "
                     "inlet type and material.",
        "type": MessageType.STRUCCHECK
    },
    "CV_CF_02": {
        "message": "Scale factor ({scale:.2f}) less than 1.0 at culvert '{culvert}'",
        "help_text": "Scale factor reduces culvert capacity below standard chart values. "
                     "Values less than 1.0 may be used for deteriorated or partially "
                     "blocked inlets. Verify this is intentional.",
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

    # Inline Weir Type Flow Checks (IW_TF_*)
    "IW_TF_01": {
        "message": "Inline weir '{name}' has weir flow only (no gate flow) for {profile}",
        "help_text": "Water is flowing over the weir crest but gates are not contributing flow. "
                     "This is normal when headwater is above weir crest and gates are closed or absent.",
        "type": MessageType.STRUCCHECK
    },
    "IW_TF_02": {
        "message": "Inline weir '{name}' has gate flow only (no weir flow) for {profile}",
        "help_text": "Flow is passing through gates but not over the weir crest. "
                     "This indicates headwater is below weir crest elevation.",
        "type": MessageType.STRUCCHECK
    },
    "IW_TF_03": {
        "message": "Inline weir '{name}' has combined weir and gate flow for {profile}",
        "help_text": "Both weir overflow and gate flow are occurring simultaneously. "
                     "Verify gate operations and weir coefficient are appropriate.",
        "type": MessageType.STRUCCHECK
    },
    "IW_TF_04": {
        "message": "Inline weir '{name}' is submerged: tailwater ({tw_elev:.2f} ft) approaches crest ({crest:.2f} ft) for {profile}",
        "help_text": "When tailwater elevation approaches or exceeds the weir crest elevation, "
                     "submergence correction factors are applied that reduce weir discharge capacity. "
                     "Submergence ratio (H_tw/H_hw) > 0.7 significantly affects flow. Verify downstream "
                     "boundary conditions and channel geometry are correctly modeled.",
        "type": MessageType.STRUCCHECK
    },

    # Structure Distance and Data Checks (ST_DT_*)
    "ST_DT_01": {
        "message": "Upstream distance ({dist} ft) too short for flow expansion at {name}",
        "help_text": "The upstream cross section should be located far enough from the structure "
                     "to allow for flow expansion and approach velocity stabilization. "
                     "Typical minimum is 1-2 times the structure opening width.",
        "type": MessageType.STRUCCHECK
    },
    "ST_DT_02": {
        "message": "Downstream distance ({dist} ft) too short for contraction recovery at {name}",
        "help_text": "The downstream cross section should be located far enough from the structure "
                     "to capture flow contraction and re-expansion. "
                     "Typical minimum is 1-2 times the structure opening width.",
        "type": MessageType.STRUCCHECK
    },
    "ST_DT_03": {
        "message": "Structure data table entry missing or incomplete at {name}: {missing_field}",
        "help_text": "The structure definition is missing required data. Common issues include: "
                     "missing deck/roadway data for bridges, missing barrel data for culverts, "
                     "or incomplete gate definitions for inline weirs. Complete all required "
                     "structure data for proper hydraulic computation.",
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

    # Structure Ground Data Checks (ST_GD_*)
    "ST_GD_01": {
        "message": "Ground data missing at structure '{name}'",
        "help_text": "No ground/terrain data found at the structure location. Ground data is required "
                     "for proper hydraulic modeling of structures. Verify terrain data covers the structure extent.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_02": {
        "message": "Ground elevation discontinuity ({diff:.2f} ft) at structure '{name}'",
        "help_text": "Significant ground elevation difference between upstream and downstream faces of the structure. "
                     "This may indicate a terrain data problem or incorrectly defined approach sections. "
                     "Verify ground data consistency across the structure.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_02BU": {
        "message": "Bridge upstream deck elevation ({deck_elev:.2f} ft) mismatch at '{name}': XS ground at deck station is {ground_elev:.2f} ft",
        "help_text": "The bridge deck elevation at the upstream face (Section 2) does not properly match the ground "
                     "elevation from the upstream approach cross section (Section 1). In the bridge 4-section model, "
                     "the deck/roadway profile should be consistent with the approach embankment topography. "
                     "This check verifies that the high chord (deck top) elevation aligns with the cross section "
                     "terrain at the corresponding station. Differences may indicate: (1) incorrect deck data entry, "
                     "(2) terrain data issues at the approach, or (3) intentional grade changes that should be verified.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_02BD": {
        "message": "Bridge downstream deck elevation ({deck_elev:.2f} ft) mismatch at '{name}': XS ground at deck station is {ground_elev:.2f} ft",
        "help_text": "The bridge deck elevation at the downstream face (Section 3) does not properly match the ground "
                     "elevation from the downstream approach cross section (Section 4). In the bridge 4-section model, "
                     "the deck/roadway profile should be consistent with the approach embankment topography. "
                     "This check verifies that the high chord (deck top) elevation aligns with the cross section "
                     "terrain at the corresponding station. Differences may indicate: (1) incorrect deck data entry, "
                     "(2) terrain data issues at the approach, or (3) intentional grade changes that should be verified.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_03L": {
        "message": "Left ground ({ground_elev:.2f} ft) below structure invert ({invert_elev:.2f} ft) at '{name}'",
        "help_text": "The left side ground elevation is below the structure invert (lowest opening elevation). "
                     "This is physically unreasonable - ground should be at or above the structure floor. "
                     "Check terrain data or structure geometry definition.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_03R": {
        "message": "Right ground ({ground_elev:.2f} ft) below structure invert ({invert_elev:.2f} ft) at '{name}'",
        "help_text": "The right side ground elevation is below the structure invert (lowest opening elevation). "
                     "This is physically unreasonable - ground should be at or above the structure floor. "
                     "Check terrain data or structure geometry definition.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_04L": {
        "message": "Left ground ({ground_elev:.2f} ft) above structure deck ({deck_elev:.2f} ft) at '{name}'",
        "help_text": "The left side ground elevation exceeds the structure deck elevation. "
                     "This may indicate terrain extending above the roadway surface, which could be "
                     "intentional (approach embankment) or a data error. Verify structure geometry.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_04R": {
        "message": "Right ground ({ground_elev:.2f} ft) above structure deck ({deck_elev:.2f} ft) at '{name}'",
        "help_text": "The right side ground elevation exceeds the structure deck elevation. "
                     "This may indicate terrain extending above the roadway surface, which could be "
                     "intentional (approach embankment) or a data error. Verify structure geometry.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_05": {
        "message": "Ground slope ({slope:.4f} ft/ft) exceeds threshold at structure '{name}'",
        "help_text": "The ground slope at or near the structure exceeds typical values. "
                     "Very steep slopes (>0.1 ft/ft or 10%) near structures may indicate "
                     "data errors or require special modeling considerations.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_06": {
        "message": "Ground data inconsistent between approach sections at '{name}': US={us_elev:.2f} ft, DS={ds_elev:.2f} ft",
        "help_text": "The ground elevations at the upstream and downstream approach cross sections "
                     "show unexpected differences. Approach sections should have consistent ground data "
                     "that transitions smoothly to the structure.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_07": {
        "message": "Approach section ground ({xs_elev:.2f} ft) doesn't match structure ground ({struct_elev:.2f} ft) at '{name}'",
        "help_text": "The ground elevation at the approach cross section differs significantly from "
                     "the structure ground data. This discontinuity may cause hydraulic modeling issues. "
                     "Verify that approach sections and structure data are consistent.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_08": {
        "message": "Pier ground elevation ({pier_elev:.2f} ft) issue at '{name}': {issue}",
        "help_text": "A problem was detected with the ground elevation at a bridge pier location. "
                     "Pier foundations should be at or below the channel ground elevation. "
                     "Verify pier data and terrain alignment.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_09": {
        "message": "Abutment ground elevation ({abut_elev:.2f} ft) issue at '{name}': {issue}",
        "help_text": "A problem was detected with the ground elevation at an abutment location. "
                     "Abutments should be properly tied to the approach embankment and ground surface. "
                     "Verify abutment stations and terrain data.",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_10": {
        "message": "Embankment slope ({slope:.2f}:1) too steep at '{name}' on {side} side",
        "help_text": "The approach embankment slope exceeds typical stable slopes (steeper than 2:1). "
                     "Very steep embankments (>1.5:1) are unusual and may indicate data issues. "
                     "Typical embankment slopes range from 2:1 to 3:1 (horizontal:vertical).",
        "type": MessageType.STRUCCHECK
    },
    "ST_GD_11": {
        "message": "Fill depth ({fill_depth:.2f} ft) exceeds reasonable limit at '{name}'",
        "help_text": "The fill depth (difference between roadway and natural ground) exceeds typical values. "
                     "Very deep fills (>30 ft) are unusual and should be verified. This may indicate "
                     "a data error in either the roadway profile or terrain data.",
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
    "FW_EM_05": {
        "message": "Encroachment Method 5 (target surcharge) used at RS {station} with target {target} ft",
        "help_text": "Method 5 iterates to achieve a target surcharge. Verify the target value "
                     "matches regulatory requirements (typically 1.0 ft for FEMA). Iteration "
                     "tolerance and convergence should be reviewed.",
        "type": MessageType.FWCHECK
    },
    "FW_EM_06": {
        "message": "Encroachment at structure RS {station} may require special handling",
        "help_text": "Encroachment methods at structures require careful review. Encroachments "
                     "should not extend into bridge openings or culvert barrels. Manual adjustment "
                     "(Method 1) may be appropriate at structure locations.",
        "type": MessageType.FWCHECK
    },
    "FW_EM_07": {
        "message": "Encroachment optimization warning at RS {station}: {warning}",
        "help_text": "HEC-RAS encroachment optimization may not converge or may produce unexpected "
                     "results. Review encroachment stations and consider manual adjustment if the "
                     "automatic method produces irregular floodway boundaries.",
        "type": MessageType.FWCHECK
    },
    "FW_EM_08": {
        "message": "Encroachment iteration limit ({iterations}) may be insufficient at RS {station}",
        "help_text": "Methods 4 and 5 use iterative optimization. If the iteration limit is too low, "
                     "the solution may not converge to optimal encroachment stations. Consider "
                     "increasing the iteration limit if convergence issues are observed.",
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
    "FW_ST_02L": {
        "message": "Left encroachment ({encr_sta:.1f} ft) inside bridge/culvert opening at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "Left floodway encroachment is located inside the structure opening (right of left abutment). "
                     "Floodway cannot encroach on the hydraulic opening. Move encroachment to match or exceed abutment station.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_02R": {
        "message": "Right encroachment ({encr_sta:.1f} ft) inside bridge/culvert opening at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "Right floodway encroachment is located inside the structure opening (left of right abutment). "
                     "Floodway cannot encroach on the hydraulic opening. Move encroachment to match or exceed abutment station.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03": {
        "message": "No encroachment specified at structure RS {station}",
        "help_text": "Structure locations may not have encroachments.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03L": {
        "message": "Left encroachment ({encr_sta:.1f} ft) starts inside abutment zone at RS {station} (abutment ends at {abut_sta:.1f} ft)",
        "help_text": "Left encroachment station begins within the abutment fill zone. This may reduce effective "
                     "flow area below design. Consider moving encroachment outward to clear the abutment.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03R": {
        "message": "Right encroachment ({encr_sta:.1f} ft) starts inside abutment zone at RS {station} (abutment starts at {abut_sta:.1f} ft)",
        "help_text": "Right encroachment station begins within the abutment fill zone. This may reduce effective "
                     "flow area below design. Consider moving encroachment outward to clear the abutment.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_04L": {
        "message": "Left encroachment ({encr_sta:.1f} ft) ends inside abutment at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "Left floodway boundary terminates within the abutment structure. The floodway boundary "
                     "should extend to or past the abutment face for proper delineation.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_04R": {
        "message": "Right encroachment ({encr_sta:.1f} ft) ends inside abutment at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "Right floodway boundary terminates within the abutment structure. The floodway boundary "
                     "should extend to or past the abutment face for proper delineation.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_05L": {
        "message": "Left encroachment blocks flow area at RS {station}: encroachment ({encr_sta:.1f} ft) beyond opening ({opening_sta:.1f} ft)",
        "help_text": "Left floodway encroachment extends into active flow area, reducing hydraulic capacity. "
                     "Verify this is intentional or adjust encroachment station.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_05R": {
        "message": "Right encroachment blocks flow area at RS {station}: encroachment ({encr_sta:.1f} ft) beyond opening ({opening_sta:.1f} ft)",
        "help_text": "Right floodway encroachment extends into active flow area, reducing hydraulic capacity. "
                     "Verify this is intentional or adjust encroachment station.",
        "type": MessageType.FWCHECK
    },

    # Section-Specific Structure Floodway Checks (Bridge 4-Section Model)
    # Section 2 = Bridge Upstream face (BU), Section 3 = Bridge Downstream face (BD)
    # Section 1 = Upstream XS (S1), Section 4 = Downstream XS (S4)

    # FW_ST_02 Section-Specific: Encroachment inside bridge opening
    "FW_ST_02S2L": {
        "message": "Section 2 (Bridge US): Left encroachment ({encr_sta:.1f} ft) inside opening at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face (Section 2), left encroachment is inside the structure opening. "
                     "Floodway cannot encroach on the hydraulic opening at this section.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_02S2R": {
        "message": "Section 2 (Bridge US): Right encroachment ({encr_sta:.1f} ft) inside opening at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face (Section 2), right encroachment is inside the structure opening. "
                     "Floodway cannot encroach on the hydraulic opening at this section.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_02S3L": {
        "message": "Section 3 (Bridge DS): Left encroachment ({encr_sta:.1f} ft) inside opening at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face (Section 3), left encroachment is inside the structure opening. "
                     "Floodway cannot encroach on the hydraulic opening at this section.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_02S3R": {
        "message": "Section 3 (Bridge DS): Right encroachment ({encr_sta:.1f} ft) inside opening at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face (Section 3), right encroachment is inside the structure opening. "
                     "Floodway cannot encroach on the hydraulic opening at this section.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_02BUL": {
        "message": "Bridge upstream: Left encroachment ({encr_sta:.1f} ft) inside opening at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face, left encroachment is inside the structure opening. "
                     "Floodway cannot encroach on the hydraulic opening.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_02BUR": {
        "message": "Bridge upstream: Right encroachment ({encr_sta:.1f} ft) inside opening at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face, right encroachment is inside the structure opening. "
                     "Floodway cannot encroach on the hydraulic opening.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_02BDL": {
        "message": "Bridge downstream: Left encroachment ({encr_sta:.1f} ft) inside opening at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face, left encroachment is inside the structure opening. "
                     "Floodway cannot encroach on the hydraulic opening.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_02BDR": {
        "message": "Bridge downstream: Right encroachment ({encr_sta:.1f} ft) inside opening at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face, right encroachment is inside the structure opening. "
                     "Floodway cannot encroach on the hydraulic opening.",
        "type": MessageType.FWCHECK
    },

    # FW_ST_03 Section-Specific: Encroachment in abutment zone
    "FW_ST_03S2L": {
        "message": "Section 2 (Bridge US): Left encroachment ({encr_sta:.1f} ft) in abutment zone at RS {station} (abutment ends at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face (Section 2), left encroachment begins within the abutment fill zone. "
                     "This may reduce effective flow area below design.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03S2R": {
        "message": "Section 2 (Bridge US): Right encroachment ({encr_sta:.1f} ft) in abutment zone at RS {station} (abutment starts at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face (Section 2), right encroachment begins within the abutment fill zone. "
                     "This may reduce effective flow area below design.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03S3L": {
        "message": "Section 3 (Bridge DS): Left encroachment ({encr_sta:.1f} ft) in abutment zone at RS {station} (abutment ends at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face (Section 3), left encroachment begins within the abutment fill zone. "
                     "This may reduce effective flow area below design.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03S3R": {
        "message": "Section 3 (Bridge DS): Right encroachment ({encr_sta:.1f} ft) in abutment zone at RS {station} (abutment starts at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face (Section 3), right encroachment begins within the abutment fill zone. "
                     "This may reduce effective flow area below design.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03BUL": {
        "message": "Bridge upstream: Left encroachment ({encr_sta:.1f} ft) in abutment zone at RS {station} (abutment ends at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face, left encroachment begins within the abutment fill zone. "
                     "This may reduce effective flow area below design.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03BUR": {
        "message": "Bridge upstream: Right encroachment ({encr_sta:.1f} ft) in abutment zone at RS {station} (abutment starts at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face, right encroachment begins within the abutment fill zone. "
                     "This may reduce effective flow area below design.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03BDL": {
        "message": "Bridge downstream: Left encroachment ({encr_sta:.1f} ft) in abutment zone at RS {station} (abutment ends at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face, left encroachment begins within the abutment fill zone. "
                     "This may reduce effective flow area below design.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_03BDR": {
        "message": "Bridge downstream: Right encroachment ({encr_sta:.1f} ft) in abutment zone at RS {station} (abutment starts at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face, right encroachment begins within the abutment fill zone. "
                     "This may reduce effective flow area below design.",
        "type": MessageType.FWCHECK
    },

    # FW_ST_04 Section-Specific: Encroachment ends inside abutment
    "FW_ST_04S2L": {
        "message": "Section 2 (Bridge US): Left encroachment ({encr_sta:.1f} ft) ends inside abutment at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face (Section 2), left floodway boundary terminates within the abutment structure.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_04S2R": {
        "message": "Section 2 (Bridge US): Right encroachment ({encr_sta:.1f} ft) ends inside abutment at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face (Section 2), right floodway boundary terminates within the abutment structure.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_04S3L": {
        "message": "Section 3 (Bridge DS): Left encroachment ({encr_sta:.1f} ft) ends inside abutment at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face (Section 3), left floodway boundary terminates within the abutment structure.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_04S3R": {
        "message": "Section 3 (Bridge DS): Right encroachment ({encr_sta:.1f} ft) ends inside abutment at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face (Section 3), right floodway boundary terminates within the abutment structure.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_04BUL": {
        "message": "Bridge upstream: Left encroachment ({encr_sta:.1f} ft) ends inside abutment at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face, left floodway boundary terminates within the abutment structure.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_04BUR": {
        "message": "Bridge upstream: Right encroachment ({encr_sta:.1f} ft) ends inside abutment at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge upstream face, right floodway boundary terminates within the abutment structure.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_04BDL": {
        "message": "Bridge downstream: Left encroachment ({encr_sta:.1f} ft) ends inside abutment at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face, left floodway boundary terminates within the abutment structure.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_04BDR": {
        "message": "Bridge downstream: Right encroachment ({encr_sta:.1f} ft) ends inside abutment at RS {station} (abutment at {abut_sta:.1f} ft)",
        "help_text": "At bridge downstream face, right floodway boundary terminates within the abutment structure.",
        "type": MessageType.FWCHECK
    },

    # FW_ST_05 Section-Specific: Encroachment blocks flow area
    "FW_ST_05S2L": {
        "message": "Section 2 (Bridge US): Left encroachment ({encr_sta:.1f} ft) blocks flow at RS {station} (opening at {opening_sta:.1f} ft)",
        "help_text": "At bridge upstream face (Section 2), left encroachment extends into active flow area.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_05S2R": {
        "message": "Section 2 (Bridge US): Right encroachment ({encr_sta:.1f} ft) blocks flow at RS {station} (opening at {opening_sta:.1f} ft)",
        "help_text": "At bridge upstream face (Section 2), right encroachment extends into active flow area.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_05S3L": {
        "message": "Section 3 (Bridge DS): Left encroachment ({encr_sta:.1f} ft) blocks flow at RS {station} (opening at {opening_sta:.1f} ft)",
        "help_text": "At bridge downstream face (Section 3), left encroachment extends into active flow area.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_05S3R": {
        "message": "Section 3 (Bridge DS): Right encroachment ({encr_sta:.1f} ft) blocks flow at RS {station} (opening at {opening_sta:.1f} ft)",
        "help_text": "At bridge downstream face (Section 3), right encroachment extends into active flow area.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_05BUL": {
        "message": "Bridge upstream: Left encroachment ({encr_sta:.1f} ft) blocks flow at RS {station} (opening at {opening_sta:.1f} ft)",
        "help_text": "At bridge upstream face, left encroachment extends into active flow area.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_05BUR": {
        "message": "Bridge upstream: Right encroachment ({encr_sta:.1f} ft) blocks flow at RS {station} (opening at {opening_sta:.1f} ft)",
        "help_text": "At bridge upstream face, right encroachment extends into active flow area.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_05BDL": {
        "message": "Bridge downstream: Left encroachment ({encr_sta:.1f} ft) blocks flow at RS {station} (opening at {opening_sta:.1f} ft)",
        "help_text": "At bridge downstream face, left encroachment extends into active flow area.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_05BDR": {
        "message": "Bridge downstream: Right encroachment ({encr_sta:.1f} ft) blocks flow at RS {station} (opening at {opening_sta:.1f} ft)",
        "help_text": "At bridge downstream face, right encroachment extends into active flow area.",
        "type": MessageType.FWCHECK
    },

    "FW_ST_06": {
        "message": "Floodway width ({fw_width:.1f} ft) exceeds structure opening width ({opening_width:.1f} ft) at RS {station}",
        "help_text": "The floodway width is wider than the structure opening. While not necessarily an error, "
                     "this indicates flow must contract to pass through the structure. Verify surcharge is acceptable.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_07": {
        "message": "Floodway bottom elevation ({fw_elev:.2f} ft) above structure invert ({invert:.2f} ft) at RS {station}",
        "help_text": "The effective floodway bottom is higher than the structure invert elevation. "
                     "This may indicate the encroachment has reduced flow depth below the structure opening.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_08": {
        "message": "Floodway top width ({fw_tw:.1f} ft) less than structure width ({struct_width:.1f} ft) at RS {station}",
        "help_text": "Top width of the floodway at WSE is narrower than the structure width. "
                     "Verify encroachments do not restrict flow capacity at the structure.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_09": {
        "message": "Encroachment in deck/roadway area at RS {station}: encroachment elevation ({encr_elev:.2f} ft) above deck ({deck_elev:.2f} ft)",
        "help_text": "Floodway encroachment elevation is above the bridge deck or roadway grade. "
                     "This indicates overtopping conditions with encroachment in the weir flow zone. "
                     "Verify this is consistent with floodway delineation criteria.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_10": {
        "message": "Pier {pier_num} within floodway encroachment limits at RS {station} (pier at {pier_sta:.1f} ft)",
        "help_text": "A bridge pier is located within the designated floodway limits. Piers reduce conveyance "
                     "and may increase surcharge. Verify pier effects are accounted for in floodway analysis.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_11": {
        "message": "Abutment within floodway limits at RS {station}: {side} abutment at {abut_sta:.1f} ft",
        "help_text": "Structure abutment is within the floodway boundary. The floodway should typically "
                     "not encroach on the structure opening. Review encroachment stations.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_12": {
        "message": "Structure opening blocked by encroachment at RS {station}: {pct_blocked:.1f}% of opening area blocked",
        "help_text": "Floodway encroachments significantly reduce the effective opening area. "
                     "More than 25% blockage may indicate improper encroachment placement.",
        "type": MessageType.FWCHECK
    },
    "FW_ST_13": {
        "message": "Flow area reduced by {pct_reduction:.1f}% at structure RS {station} (base: {base_area:.0f} sq ft, floodway: {fw_area:.0f} sq ft)",
        "help_text": "Encroachments cause significant flow area reduction at the structure. Large reductions "
                     "(>30%) may result in excessive surcharge or capacity problems.",
        "type": MessageType.FWCHECK
    },

    # Starting WSE
    "FW_SW_01": {
        "message": "Starting WSE ({wse} ft) at downstream boundary for {profile}",
        "help_text": "Informational: starting water surface elevation for floodway analysis.",
        "type": MessageType.FWCHECK
    },
    "FW_SW_02": {
        "message": "Starting WSE difference ({diff} ft) between base ({base_wse}) and floodway ({fw_wse}) profiles exceeds threshold",
        "help_text": "Large starting WSE difference may affect floodway analysis results. "
                     "Starting conditions should be consistent between base flood and floodway profiles.",
        "type": MessageType.FWCHECK
    },
    "FW_SW_03": {
        "message": "Starting WSE ({wse} ft) is below channel invert ({invert} ft) at RS {station}",
        "help_text": "Starting water surface elevation is below the channel bottom. "
                     "This is physically impossible and indicates a boundary condition error.",
        "type": MessageType.FWCHECK
    },
    "FW_SW_04": {
        "message": "Starting WSE ({wse} ft) is above top of bank ({bank_elev} ft) at RS {station}",
        "help_text": "Starting WSE exceeds bank elevation at the downstream boundary. "
                     "Verify this is consistent with expected floodway conditions.",
        "type": MessageType.FWCHECK
    },
    "FW_SW_05": {
        "message": "Starting WSE inconsistent between profiles at RS {station}: {profile1}={wse1} ft, {profile2}={wse2} ft",
        "help_text": "Starting WSE varies between profiles at the same location. "
                     "For floodway analysis, boundary conditions should be coordinated.",
        "type": MessageType.FWCHECK
    },
    "FW_SW_06": {
        "message": "Starting WSE produces supercritical flow (Froude={froude:.2f}) at RS {station} for {profile}",
        "help_text": "The starting WSE results in supercritical flow conditions (Froude > 1). "
                     "For floodway analysis, subcritical flow at the boundary is typically expected. "
                     "Review boundary conditions and channel slope.",
        "type": MessageType.FWCHECK
    },
    "FW_SW_07": {
        "message": "Starting WSE ({wse} ft) results in negative depth ({depth} ft) at RS {station}",
        "help_text": "The computed depth at the starting section is negative, which is physically impossible. "
                     "This indicates the starting WSE is below the channel invert.",
        "type": MessageType.FWCHECK
    },
    "FW_SW_08": {
        "message": "Starting WSE ({start_wse} ft) differs from computed WSE ({computed_wse} ft) by {diff} ft at RS {station}",
        "help_text": "The specified starting WSE differs significantly from the computed WSE at the downstream boundary. "
                     "Large differences may indicate boundary condition issues or hydraulic control effects.",
        "type": MessageType.FWCHECK
    },

    # -------------------------------------------------------------------------
    # Method-Specific Starting WSE Checks
    # HEC-RAS Encroachment Methods:
    #   Method 1: Fixed encroachment stations
    #   Method 2: Fixed top widths
    #   Method 3: Fixed percentage of conveyance reduction
    #   Method 4: Target surcharge (most common for FEMA)
    #   Method 5: Target width reduction
    # -------------------------------------------------------------------------

    # FW_SW_02M1 - Starting WSE Method 1 (fixed stations) specific check
    "FW_SW_02M1": {
        "message": "Method 1 (fixed stations): Starting WSE diff ({diff} ft) at RS {station} - fixed stations may not properly account for starting WSE variation",
        "help_text": "Method 1 uses fixed encroachment stations which do not automatically adjust "
                     "based on hydraulic conditions. When the starting WSE differs between base flood "
                     "and floodway profiles, the fixed stations may produce inappropriate surcharge. "
                     "Consider using Method 4 or 5 for better hydraulic balance, or manually verify "
                     "that the fixed stations produce acceptable surcharge with the given starting WSE.",
        "type": MessageType.FWCHECK
    },

    # FW_SW_02M4 - Starting WSE Method 4 (target surcharge) specific check
    "FW_SW_02M4": {
        "message": "Method 4 (target surcharge): Starting WSE diff ({diff} ft) at RS {station} may affect target surcharge ({target} ft) iteration",
        "help_text": "Method 4 iterates to achieve a target surcharge (typically 1.0 ft for FEMA). "
                     "When the starting WSE differs significantly from the base flood, the iteration "
                     "must account for this difference when computing encroachment positions. Large "
                     "starting WSE differences may cause convergence issues or unexpected encroachment "
                     "patterns. Verify the floodway boundary is physically reasonable.",
        "type": MessageType.FWCHECK
    },

    # FW_SW_02M5 - Starting WSE Method 5 (target width reduction) specific check
    "FW_SW_02M5": {
        "message": "Method 5 (target width reduction): Starting WSE diff ({diff} ft) at RS {station} may affect width reduction target ({target_pct}%)",
        "help_text": "Method 5 iterates to achieve a target top width reduction. When starting WSE "
                     "differs between profiles, the effective floodplain width changes, potentially "
                     "affecting the iteration convergence. Large starting WSE differences may cause "
                     "the width reduction target to be difficult to achieve or produce irregular "
                     "floodway boundaries.",
        "type": MessageType.FWCHECK
    },

    # FW_SW_03M1 - Starting WSE comparison for Method 1
    "FW_SW_03M1": {
        "message": "Method 1 (fixed stations): Starting WSE ({wse} ft) below invert ({invert} ft) at RS {station} - fixed stations invalid",
        "help_text": "With Method 1 (fixed encroachment stations), a starting WSE below the channel "
                     "invert makes the floodway analysis invalid. The fixed encroachment stations "
                     "were likely set based on a different water surface profile. The encroachment "
                     "stations must be repositioned or a different starting WSE must be used.",
        "type": MessageType.FWCHECK
    },

    # FW_SW_03M4 - Starting WSE comparison for Method 4
    "FW_SW_03M4": {
        "message": "Method 4 (target surcharge): Starting WSE ({wse} ft) below invert ({invert} ft) at RS {station} - cannot compute surcharge",
        "help_text": "With Method 4 (target surcharge), a starting WSE below the channel invert "
                     "prevents proper surcharge computation. The surcharge is the difference between "
                     "floodway and base flood water surfaces - this cannot be computed with an invalid "
                     "starting condition. Correct the downstream boundary condition.",
        "type": MessageType.FWCHECK
    },

    # FW_SW_04M1 - Starting WSE validation Method 1 variant
    "FW_SW_04M1": {
        "message": "Method 1 (fixed stations): Starting WSE ({wse} ft) exceeds bank ({bank_elev} ft) at RS {station} - fixed stations may be in overbank",
        "help_text": "With Method 1 (fixed stations), when the starting WSE exceeds bank elevation, "
                     "the encroachment stations should be positioned in the overbank areas. Verify "
                     "that the fixed stations are appropriate for overbank flow conditions. Fixed "
                     "stations set for lower water surfaces may not properly constrain the floodway "
                     "at higher stages.",
        "type": MessageType.FWCHECK
    },

    # FW_SW_04M4 - Starting WSE validation Method 4 variant
    "FW_SW_04M4": {
        "message": "Method 4 (target surcharge): Starting WSE ({wse} ft) exceeds bank ({bank_elev} ft) at RS {station} - surcharge affects overbank areas",
        "help_text": "With Method 4 (target surcharge), when starting WSE exceeds bank elevation, "
                     "the target surcharge affects water levels in the overbank areas. This may "
                     "result in encroachments that extend significantly into the floodplain. Verify "
                     "that the resulting floodway boundary is appropriate for the flood conditions.",
        "type": MessageType.FWCHECK
    },

    # FW_SW_05M1 - Starting WSE consistency Method 1
    "FW_SW_05M1": {
        "message": "Method 1 (fixed stations): Starting WSE varies between {profile1} ({wse1} ft) and {profile2} ({wse2} ft) at RS {station} - fixed stations may be inappropriate",
        "help_text": "Method 1 uses fixed encroachment stations that do not adjust for different "
                     "water surface elevations. When starting WSE varies significantly between "
                     "profiles, the same fixed stations may produce very different hydraulic effects. "
                     "Consider whether the fixed stations are appropriate for all profiles or if "
                     "an automated method (4 or 5) would be more suitable.",
        "type": MessageType.FWCHECK
    },

    # FW_SW_05M4 - Starting WSE consistency Method 4
    "FW_SW_05M4": {
        "message": "Method 4 (target surcharge): Starting WSE varies between {profile1} ({wse1} ft) and {profile2} ({wse2} ft) at RS {station} - iteration adjusted",
        "help_text": "Method 4 (target surcharge) will iterate to achieve the target surcharge "
                     "regardless of the starting WSE. However, when starting WSE varies significantly "
                     "between profiles at the boundary, the resulting encroachment stations will "
                     "differ. This is expected behavior but should be verified for consistency.",
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
    "PF_TW_01": {
        "message": "Top width decreases {pct:.1f}% from {profile_low} ({tw_low:.1f} ft) to {profile_high} ({tw_high:.1f} ft) at RS {station}",
        "help_text": "Top width decreases significantly (>20%) from lower to higher frequency profile. "
                     "This is unusual unless the cross section has constrained overbank areas or levees.",
        "type": MessageType.PROFILESCHECK
    },

    # Velocity
    "PF_VEL_01": {
        "message": "Velocity for {profile_low} ({vel_low:.2f} ft/s) is less than {profile_high} ({vel_high:.2f} ft/s) at RS {station}",
        "help_text": "With higher discharge, velocity should typically be higher. Lower velocity in a more severe "
                     "event may indicate wide overbank flow areas or significant flow area expansion.",
        "type": MessageType.PROFILESCHECK
    },

    # Energy Grade
    "PF_EG_01": {
        "message": "Energy grade for {profile_low} ({eg_low:.2f} ft) is below {profile_high} ({eg_high:.2f} ft) at RS {station}",
        "help_text": "The energy grade elevation should be higher for more severe (lower frequency) events. "
                     "This condition indicates potential model issues or unusual hydraulic behavior.",
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


def format_message(message_id: str, **kwargs) -> str:
    """
    Format a message template with provided values.

    Args:
        message_id: The message ID
        **kwargs: Values to substitute into the template

    Returns:
        Formatted message string

    Example:
        >>> format_message("NT_RC_01L", n=0.025)
        "Left overbank Manning's n value (0.025) is less than 0.030"
    """
    template = get_message_template(message_id)
    try:
        return template.format(**kwargs)
    except KeyError as e:
        return f"{template} (missing: {e})"
