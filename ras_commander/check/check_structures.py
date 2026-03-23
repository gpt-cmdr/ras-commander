"""
CheckStructures - Structure validation (bridges, culverts, inline weirs).

Extracted from RasCheck.py for modular organization.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd
import numpy as np
import h5py

from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger
from .types import Severity, FlowType, CheckMessage, CheckResults
from .thresholds import ValidationThresholds, get_default_thresholds
from .messages import get_message_template, get_help_text, format_message
from . import _utils

logger = get_logger(__name__)


class CheckStructures:
    """Structure validation (bridges, culverts, inline weirs)."""

    @staticmethod
    @log_call
    def check_structures(
        plan_hdf: Path,
        geom_hdf: Path,
        profiles: List[str],
        thresholds: Optional[ValidationThresholds] = None
    ) -> CheckResults:
        """
        Check bridge, culvert, and inline weir data.

        Validates:
        - Multiple structures at same location
        - Weir coefficient ranges
        - Structure type identification

        Args:
            plan_hdf: Path to plan HDF file
            geom_hdf: Path to geometry HDF file
            profiles: List of profile names to check
            thresholds: Custom ValidationThresholds (uses defaults if None)

        Returns:
            CheckResults with structure check messages and summary DataFrame
        """
        from ..hdf.HdfStruc import HdfStruc

        results = CheckResults()
        messages = []

        if thresholds is None:
            thresholds = get_default_thresholds()

        s_thresholds = thresholds.structures

        # Get structure data from geometry
        try:
            struct_gdf = HdfStruc.get_structures(geom_hdf)
        except Exception as e:
            logger.warning(f"Could not read structures: {e}")
            struct_gdf = None

        if struct_gdf is None or struct_gdf.empty:
            # No structures in model - not an error
            results.messages = []
            results.struct_summary = pd.DataFrame()
            return results

        # Build summary records
        summary_records = []

        for idx, struct in struct_gdf.iterrows():
            struct_type = struct.get('Type', '')
            river = struct.get('River', '')
            reach = struct.get('Reach', '')
            station = struct.get('RS', 0)
            name = struct.get('Node Name', struct.get('Groupname', ''))

            record = {
                'River': river,
                'Reach': reach,
                'RS': station,
                'Type': struct_type,
                'Name': name,
                'issues': []
            }

            # Check weir coefficient (for bridges and inline weirs)
            weir_coef = struct.get('Weir Coef', None)
            if weir_coef is not None and weir_coef > 0:
                record['Weir_Coef'] = weir_coef
                if weir_coef < s_thresholds.weir_coefficient_min or weir_coef > s_thresholds.weir_coefficient_max:
                    if 'Bridge' in struct_type:
                        msg_id = "BR_PW_03"
                    else:
                        msg_id = "IW_03"
                    msg = CheckMessage(
                        message_id=msg_id,
                        severity=Severity.WARNING,
                        check_type="STRUCT",
                        river=river,
                        reach=reach,
                        station=str(station),
                        message=format_message(msg_id, c=f"{weir_coef:.2f}"),
                        help_text=get_help_text(msg_id),
                        value=weir_coef,
                        threshold=f"{s_thresholds.weir_coefficient_min}-{s_thresholds.weir_coefficient_max}"
                    )
                    messages.append(msg)
                    record['issues'].append(msg_id)

            # Check upstream distance
            upstream_dist = struct.get('Upstream Distance', None)
            if upstream_dist is not None and upstream_dist > 0:
                record['US_Distance'] = upstream_dist

            summary_records.append(record)

        # Check for multiple structures at same location
        location_groups = {}
        for record in summary_records:
            key = (record['River'], record['Reach'], record['RS'])
            if key not in location_groups:
                location_groups[key] = []
            location_groups[key].append(record)

        for key, group in location_groups.items():
            if len(group) > 1:
                river, reach, station = key
                msg = CheckMessage(
                    message_id="ST_MS_01",
                    severity=Severity.INFO,
                    check_type="STRUCT",
                    river=river,
                    reach=reach,
                    station=str(station),
                    message=format_message("ST_MS_01", station=str(station)),
                    help_text=get_help_text("ST_MS_01")
                )
                messages.append(msg)

                # Mark all structures in group
                for record in group:
                    if "ST_MS_01" not in record['issues']:
                        record['issues'].append("ST_MS_01")

                # Check for mixed types
                types = set(r['Type'] for r in group if r.get('Type'))
                if len(types) > 1:
                    msg = CheckMessage(
                        message_id="ST_MS_02",
                        severity=Severity.INFO,
                        check_type="STRUCT",
                        river=river,
                        reach=reach,
                        station=str(station),
                        message=format_message("ST_MS_02", station=str(station)),
                        help_text=get_help_text("ST_MS_02")
                    )
                    messages.append(msg)
                    for record in group:
                        if "ST_MS_02" not in record['issues']:
                            record['issues'].append("ST_MS_02")

        # =====================================================================
        # Additional Structure Checks from HDF
        # =====================================================================
        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' in hdf:
                    struct_attrs = hdf['Geometry/Structures/Attributes'][:]

                    for i, attr in enumerate(struct_attrs):
                        struct_type = attr['Type'].decode().strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()
                        river = attr['River'].decode().strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                        reach = attr['Reach'].decode().strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                        station = attr['RS'].decode().strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                        # Get section distances
                        us_dist = float(attr['Upstream Distance']) if 'Upstream Distance' in attr.dtype.names else 0

                        # ST_DT_03: Check for missing structure data table entries
                        missing_fields = []
                        if 'Bridge' in struct_type:
                            # Check for required bridge fields
                            required_bridge_fields = [
                                ('BR US Left Bank', 'upstream left abutment'),
                                ('BR US Right Bank', 'upstream right abutment'),
                                ('Low Chord', 'low chord elevation'),
                                ('High Chord', 'high chord elevation'),
                            ]
                            for field_name, field_desc in required_bridge_fields:
                                if field_name not in attr.dtype.names:
                                    missing_fields.append(field_desc)

                        elif 'Culvert' in struct_type:
                            # Check for required culvert fields
                            required_culvert_fields = [
                                ('Rise', 'culvert rise/height'),
                                ('Span', 'culvert span/width'),
                                ('Length', 'culvert length'),
                            ]
                            for field_name, field_desc in required_culvert_fields:
                                if field_name not in attr.dtype.names:
                                    missing_fields.append(field_desc)

                        elif 'Inline' in struct_type or 'Weir' in struct_type:
                            # Check for required inline weir fields
                            required_weir_fields = [
                                ('Weir Coef', 'weir coefficient'),
                            ]
                            for field_name, field_desc in required_weir_fields:
                                if field_name not in attr.dtype.names:
                                    missing_fields.append(field_desc)

                        if missing_fields:
                            struct_name = attr['Node Name'].decode().strip() if 'Node Name' in attr.dtype.names and isinstance(attr['Node Name'], bytes) else f"{struct_type}_{station}"
                            msg = CheckMessage(
                                message_id="ST_DT_03",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("ST_DT_03",
                                                      name=struct_name,
                                                      missing_field=', '.join(missing_fields)),
                                help_text=get_help_text("ST_DT_03")
                            )
                            messages.append(msg)

                        # BR_SD_01/03: Bridge section distance checks
                        if 'Bridge' in struct_type:
                            # Upstream distance check - should be at least 1x expansion length (typically 100-300 ft)
                            min_us_dist = s_thresholds.bridge_upstream_distance_min if hasattr(s_thresholds, 'bridge_upstream_distance_min') else 50
                            if us_dist > 0 and us_dist < min_us_dist:
                                msg = CheckMessage(
                                    message_id="BR_SD_01",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=format_message("BR_SD_01", dist=f"{us_dist:.1f}"),
                                    help_text=get_help_text("BR_SD_01"),
                                    value=us_dist
                                )
                                messages.append(msg)

                            # Check bridge contraction/expansion coefficients
                            br_contraction = float(attr['BR Contraction']) if 'BR Contraction' in attr.dtype.names else 0
                            br_expansion = float(attr['BR Expansion']) if 'BR Expansion' in attr.dtype.names else 0

                            # BR_LF_01: Unusual contraction coefficient
                            if br_contraction > 0 and (br_contraction < 0.1 or br_contraction > 0.6):
                                msg = CheckMessage(
                                    message_id="BR_LF_01",
                                    severity=Severity.INFO,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Bridge contraction coefficient ({br_contraction:.2f}) outside typical range (0.1-0.6)",
                                    help_text="Typical bridge contraction coefficients range from 0.1 to 0.6."
                                )
                                messages.append(msg)

                            # BR_LF_02: Unusual expansion coefficient
                            if br_expansion > 0 and (br_expansion < 0.3 or br_expansion > 0.8):
                                msg = CheckMessage(
                                    message_id="BR_LF_02",
                                    severity=Severity.INFO,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=f"Bridge expansion coefficient ({br_expansion:.2f}) outside typical range (0.3-0.8)",
                                    help_text="Typical bridge expansion coefficients range from 0.3 to 0.8."
                                )
                                messages.append(msg)

                            # BR_LF_03: Bridge low flow coefficient check
                            # Check for low flow coefficient (typically used in energy-based methods)
                            br_low_flow_coef = 0.0
                            for coef_name in ['Low Flow Coef', 'LF Coef', 'Yarnell Coef', 'Pier Shape']:
                                if coef_name in attr.dtype.names:
                                    br_low_flow_coef = float(attr[coef_name])
                                    break

                            if br_low_flow_coef > 0:
                                # Typical range depends on flow class and method
                                # Class A (Energy): Yarnell K typically 0.9-1.05
                                # Pier drag: typically 1.0-2.5
                                min_coef = 0.5
                                max_coef = 2.5
                                if br_low_flow_coef < min_coef or br_low_flow_coef > max_coef:
                                    msg = CheckMessage(
                                        message_id="BR_LF_03",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=format_message("BR_LF_03",
                                                              coef=br_low_flow_coef,
                                                              min=min_coef,
                                                              max=max_coef),
                                        help_text=get_help_text("BR_LF_03"),
                                        value=br_low_flow_coef
                                    )
                                    messages.append(msg)

                        # CU_SD_01: Culvert section distance checks
                        elif 'Culvert' in struct_type:
                            min_us_dist = s_thresholds.culvert_upstream_distance_min if hasattr(s_thresholds, 'culvert_upstream_distance_min') else 30
                            if us_dist > 0 and us_dist < min_us_dist:
                                msg = CheckMessage(
                                    message_id="CU_SD_01",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=format_message("CU_SD_01", dist=f"{us_dist:.1f}"),
                                    help_text=get_help_text("CU_SD_01"),
                                    value=us_dist
                                )
                                messages.append(msg)

                        # IW_SD_01: Inline weir section distance checks
                        elif 'Inline' in struct_type or 'Weir' in struct_type:
                            min_us_dist = 20
                            if us_dist > 0 and us_dist < min_us_dist:
                                msg = CheckMessage(
                                    message_id="IW_SD_01",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=format_message("IW_SD_01", dist=f"{us_dist:.1f}"),
                                    help_text=get_help_text("IW_SD_01"),
                                    value=us_dist
                                )
                                messages.append(msg)

                        # ST_IF_01/02: Structure ineffective flow checks
                        if 'Bridge' in struct_type:
                            # Check for upstream ineffective flow
                            us_ineff_left_sta = float(attr['US Ineff Left Sta']) if 'US Ineff Left Sta' in attr.dtype.names else 0
                            us_ineff_right_sta = float(attr['US Ineff Right Sta']) if 'US Ineff Right Sta' in attr.dtype.names else 0
                            ds_ineff_left_sta = float(attr['DS Ineff Left Sta']) if 'DS Ineff Left Sta' in attr.dtype.names else 0
                            ds_ineff_right_sta = float(attr['DS Ineff Right Sta']) if 'DS Ineff Right Sta' in attr.dtype.names else 0

                            # If no ineffective defined (both zeros), warn
                            if us_ineff_left_sta == 0 and us_ineff_right_sta == 0:
                                msg = CheckMessage(
                                    message_id="ST_IF_01",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=get_message_template("ST_IF_01"),
                                    help_text=get_help_text("ST_IF_01")
                                )
                                messages.append(msg)

                            if ds_ineff_left_sta == 0 and ds_ineff_right_sta == 0:
                                msg = CheckMessage(
                                    message_id="ST_IF_02",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    message=get_message_template("ST_IF_02"),
                                    help_text=get_help_text("ST_IF_02")
                                )
                                messages.append(msg)

                            # ST_IF_03L/R: Ineffective should extend to abutment
                            br_us_left_bank = float(attr['BR US Left Bank']) if 'BR US Left Bank' in attr.dtype.names else 0
                            br_us_right_bank = float(attr['BR US Right Bank']) if 'BR US Right Bank' in attr.dtype.names else 0

                            if us_ineff_left_sta > 0 and br_us_left_bank > 0:
                                if us_ineff_right_sta < br_us_left_bank - 5:  # 5 ft tolerance
                                    msg = CheckMessage(
                                        message_id="ST_IF_03L",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=get_message_template("ST_IF_03L"),
                                        help_text=get_help_text("ST_IF_03L")
                                    )
                                    messages.append(msg)

                            if us_ineff_right_sta > 0 and br_us_right_bank > 0:
                                if us_ineff_left_sta > br_us_right_bank + 5:  # 5 ft tolerance
                                    msg = CheckMessage(
                                        message_id="ST_IF_03R",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=get_message_template("ST_IF_03R"),
                                        help_text=get_help_text("ST_IF_03R")
                                    )
                                    messages.append(msg)

                        # ST_GE_01L/R: Bank station alignment checks
                        if 'Bridge' in struct_type:
                            br_us_left_bank = float(attr['BR US Left Bank']) if 'BR US Left Bank' in attr.dtype.names else 0
                            br_us_right_bank = float(attr['BR US Right Bank']) if 'BR US Right Bank' in attr.dtype.names else 0
                            xs_us_left_bank = float(attr['XS US Left Bank']) if 'XS US Left Bank' in attr.dtype.names else 0
                            xs_us_right_bank = float(attr['XS US Right Bank']) if 'XS US Right Bank' in attr.dtype.names else 0

                            # Check if bridge bank stations are significantly different from XS bank stations
                            if br_us_left_bank > 0 and xs_us_left_bank > 0:
                                if abs(br_us_left_bank - xs_us_left_bank) > 50:  # 50 ft tolerance
                                    msg = CheckMessage(
                                        message_id="ST_GE_01L",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=get_message_template("ST_GE_01L"),
                                        help_text=get_help_text("ST_GE_01L")
                                    )
                                    messages.append(msg)

                            if br_us_right_bank > 0 and xs_us_right_bank > 0:
                                if abs(br_us_right_bank - xs_us_right_bank) > 50:
                                    msg = CheckMessage(
                                        message_id="ST_GE_01R",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        message=get_message_template("ST_GE_01R"),
                                        help_text=get_help_text("ST_GE_01R")
                                    )
                                    messages.append(msg)

                        # Weir submergence check
                        weir_max_sub = float(attr['Weir Max Submergence']) if 'Weir Max Submergence' in attr.dtype.names else 0
                        if weir_max_sub > 0 and weir_max_sub < 0.8:
                            msg = CheckMessage(
                                message_id="BR_PW_04",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=format_message("BR_PW_04", sub=f"{weir_max_sub:.2f}"),
                                help_text=get_help_text("BR_PW_04")
                            )
                            messages.append(msg)

        except Exception as e:
            logger.debug(f"Could not perform additional structure checks: {e}")

        # =====================================================================
        # Additional Structure Checks Using Helper Methods
        # =====================================================================

        # ST_DT_01/02: Structure distance checks
        distance_messages = CheckStructures._check_structure_distances(geom_hdf, thresholds)
        messages.extend(distance_messages)

        # ST_GE_02L/R, ST_GE_03: Structure geometry alignment checks
        geometry_messages = CheckStructures._check_structure_geometry_alignment(geom_hdf, thresholds)
        messages.extend(geometry_messages)

        # ST_IF_04L/R: Section 3 ineffective flow checks
        ineff_section3_messages = CheckStructures._check_structure_ineffective_section3(geom_hdf, thresholds)
        messages.extend(ineff_section3_messages)

        # IW_TF_*: Inline weir flow type checks
        inline_weir_messages = CheckStructures._check_inline_weirs(geom_hdf, plan_hdf, profiles, thresholds)
        messages.extend(inline_weir_messages)

        # CV_TF_*, CV_LF_*, CV_PF_*, CV_PW_*, CV_CF_*: Culvert flow type and coefficient checks
        culvert_messages = CheckStructures._check_culverts(geom_hdf, plan_hdf, profiles, thresholds)
        messages.extend(culvert_messages)

        # BR_TF_*, BR_PF_*, BR_PW_*: Bridge flow type and pressure/weir checks
        bridge_flow_messages = CheckStructures._check_bridge_flow_types(geom_hdf, plan_hdf, profiles, thresholds)
        messages.extend(bridge_flow_messages)

        # ST_GD_*: Structure ground data validation checks
        ground_messages = CheckStructures._check_structure_ground(geom_hdf, thresholds)
        messages.extend(ground_messages)

        # Convert issues lists to strings for DataFrame
        for record in summary_records:
            record['issues'] = ', '.join(record['issues'])

        results.messages = messages
        results.struct_summary = pd.DataFrame(summary_records)
        return results

    # =========================================================================
    # Culvert Flow Type and Coefficient Checks
    # =========================================================================

    @staticmethod
    def _check_culverts(
        geom_hdf: Path,
        plan_hdf: Optional[Path],
        profiles: List[str],
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check culvert flow types and loss coefficients (CV_* checks).

        Validates:
        - CV_TF_01-07: Flow type detection (outlet control, inlet control, pressure, overtopping)
        - CV_LF_01-03: Loss coefficient ranges (entrance, exit, bend)
        - CV_PF_01-02: Pressure flow and submergence warnings
        - CV_PW_01: Combined pressure and weir flow detection
        - CV_CF_01-02: Chart/scale configuration checks

        Args:
            geom_hdf: Path to geometry HDF file
            plan_hdf: Path to plan HDF file (may be None for geometry-only checks)
            profiles: List of profile names to check
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for culvert validation
        """
        messages = []
        s_thresholds = thresholds.structures

        try:
            with h5py.File(geom_hdf, 'r') as geom_h:
                # Check for structures in geometry
                if 'Geometry/Structures/Attributes' not in geom_h:
                    return messages

                struct_attrs = geom_h['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                # Find culverts
                culverts = []
                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    # Check for culvert type
                    if 'Culvert' in struct_type:
                        river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                        reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                        station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()
                        name = attr['Node Name'].decode('utf-8').strip() if 'Node Name' in attr_names and isinstance(attr['Node Name'], bytes) else f'Culvert_{station}'

                        culvert_info = {
                            'index': i,
                            'river': river,
                            'reach': reach,
                            'station': station,
                            'name': name,
                            'type': struct_type
                        }

                        culverts.append(culvert_info)

                if not culverts:
                    return messages

                # Try to read culvert-specific data from geometry if available
                # Check for Culvert Groups dataset
                culvert_groups_path = 'Geometry/Structures/Culvert Groups'
                if culvert_groups_path in geom_h:
                    culvert_groups = geom_h[culvert_groups_path][:]
                    cg_names = culvert_groups.dtype.names if culvert_groups.dtype.names else []

                    # Match culvert groups to structures
                    for culvert in culverts:
                        # Find matching culvert group by structure index or name
                        for cg in culvert_groups:
                            # Extract relevant attributes if available
                            if 'Entrance Loss' in cg_names:
                                ke = float(cg['Entrance Loss'])
                                culvert['entrance_loss'] = ke

                                # CV_LF_01: Check entrance loss coefficient range (0.2-0.9)
                                if ke < s_thresholds.culvert_entrance_coef_min or ke > s_thresholds.culvert_entrance_coef_max:
                                    msg = CheckMessage(
                                        message_id="CV_LF_01",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=culvert['river'],
                                        reach=culvert['reach'],
                                        station=culvert['station'],
                                        structure=culvert['name'],
                                        message=f"Entrance loss coefficient ({ke:.2f}) outside typical range (0.2-0.9) at culvert '{culvert['name']}'",
                                        help_text=get_help_text("CV_LF_01"),
                                        value=ke,
                                        threshold=f"{s_thresholds.culvert_entrance_coef_min}-{s_thresholds.culvert_entrance_coef_max}"
                                    )
                                    messages.append(msg)

                            if 'Exit Loss' in cg_names:
                                kx = float(cg['Exit Loss'])
                                culvert['exit_loss'] = kx

                                # CV_LF_02: Check exit loss coefficient range (0.5-1.0)
                                if kx < 0.5 or kx > 1.0:
                                    msg = CheckMessage(
                                        message_id="CV_LF_02",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=culvert['river'],
                                        reach=culvert['reach'],
                                        station=culvert['station'],
                                        structure=culvert['name'],
                                        message=f"Exit loss coefficient ({kx:.2f}) outside typical range (0.5-1.0) at culvert '{culvert['name']}'",
                                        help_text=get_help_text("CV_LF_02"),
                                        value=kx
                                    )
                                    messages.append(msg)

                            if 'Chart' in cg_names and 'Scale' in cg_names:
                                chart = int(cg['Chart']) if cg['Chart'] else 0
                                scale = float(cg['Scale']) if cg['Scale'] else 1.0

                                # CV_CF_01: Chart/scale configuration (INFO)
                                if chart > 0:
                                    msg = CheckMessage(
                                        message_id="CV_CF_01",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=culvert['river'],
                                        reach=culvert['reach'],
                                        station=culvert['station'],
                                        structure=culvert['name'],
                                        message=f"Chart {chart} with scale {scale:.2f} at culvert '{culvert['name']}'",
                                        help_text=get_help_text("CV_CF_01")
                                    )
                                    messages.append(msg)

                                # CV_CF_02: Scale factor less than 1.0
                                if scale < 1.0:
                                    msg = CheckMessage(
                                        message_id="CV_CF_02",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=culvert['river'],
                                        reach=culvert['reach'],
                                        station=culvert['station'],
                                        structure=culvert['name'],
                                        message=f"Scale factor ({scale:.2f}) less than 1.0 at culvert '{culvert['name']}'",
                                        help_text=get_help_text("CV_CF_02"),
                                        value=scale
                                    )
                                    messages.append(msg)

                            # Only process first matching group per culvert
                            break

        except Exception as e:
            logger.debug(f"Could not read culvert geometry data: {e}")

        # Check results if plan HDF is available
        if plan_hdf is None or not Path(plan_hdf).exists():
            return messages

        try:
            with h5py.File(plan_hdf, 'r') as plan_h:
                # Look for steady results with structure data
                # Check multiple possible paths
                struct_results_base = None
                for base_path in ['Results/Steady/Structures', 'Results/Steady/Structure']:
                    if base_path in plan_h:
                        struct_results_base = base_path
                        break

                if struct_results_base is None:
                    return messages

                # Try to find culvert-specific results
                # Path may vary: Results/Steady/Structures/Culvert or similar
                for profile in profiles:
                    profile_path = f"{struct_results_base}/{profile}"
                    if profile_path not in plan_h:
                        continue

                    profile_grp = plan_h[profile_path]

                    # Check for culvert results
                    for culvert in culverts:
                        culvert_name = culvert['name']
                        river = culvert['river']
                        reach = culvert['reach']
                        station = culvert['station']

                        # Try different culvert result paths
                        culvert_result = None
                        for path_variant in [culvert_name, f"Culvert {station}", station]:
                            if path_variant in profile_grp:
                                culvert_result = profile_grp[path_variant]
                                break

                        if culvert_result is None:
                            continue

                        # Check for flow type indicators
                        # HEC-RAS stores: Culvert Q, HW Elev, TW Elev, Flow Type, etc.
                        result_attrs = dict(culvert_result.attrs) if hasattr(culvert_result, 'attrs') else {}

                        flow_type = result_attrs.get('Flow Type', None)
                        if flow_type is not None:
                            if isinstance(flow_type, bytes):
                                flow_type = flow_type.decode('utf-8').strip()
                            flow_type = str(flow_type).strip()

                            # Map flow types to CV_TF_* messages
                            flow_type_map = {
                                '1': ('CV_TF_01', Severity.INFO, "Type 1 flow (outlet control, unsubmerged)"),
                                '2': ('CV_TF_02', Severity.INFO, "Type 2 flow (outlet control, submerged outlet)"),
                                '3': ('CV_TF_03', Severity.INFO, "Type 3 flow (inlet control, unsubmerged)"),
                                '4': ('CV_TF_04', Severity.INFO, "Type 4 flow (inlet control, submerged)"),
                                '5': ('CV_TF_05', Severity.WARNING, "Type 5 flow (full flow)"),
                                '6': ('CV_TF_06', Severity.WARNING, "Type 6 flow (pressure flow)"),
                                '7': ('CV_TF_07', Severity.WARNING, "Type 7 flow (overtopping)"),
                                'Outlet': ('CV_TF_01', Severity.INFO, "Outlet control flow"),
                                'Inlet': ('CV_TF_03', Severity.INFO, "Inlet control flow"),
                                'Full': ('CV_TF_05', Severity.WARNING, "Full flow"),
                                'Pressure': ('CV_TF_06', Severity.WARNING, "Pressure flow"),
                                'Overtop': ('CV_TF_07', Severity.WARNING, "Overtopping"),
                            }

                            # Check for matching flow type
                            for key, (msg_id, severity, desc) in flow_type_map.items():
                                if key.lower() in flow_type.lower():
                                    msg = CheckMessage(
                                        message_id=msg_id,
                                        severity=severity,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        structure=culvert_name,
                                        message=f"{desc} at culvert '{culvert_name}' for {profile}",
                                        help_text=get_help_text(msg_id)
                                    )
                                    messages.append(msg)
                                    break

                        # Check headwater/tailwater for pressure flow indicators
                        hw_elev = result_attrs.get('HW Elev', None)
                        tw_elev = result_attrs.get('TW Elev', None)
                        inlet_elev = result_attrs.get('Inlet Elev', result_attrs.get('US Invert', None))
                        culvert_rise = result_attrs.get('Rise', result_attrs.get('Diameter', None))

                        if hw_elev is not None and inlet_elev is not None and culvert_rise is not None:
                            try:
                                hw = float(hw_elev)
                                inlet = float(inlet_elev)
                                rise = float(culvert_rise)

                                if rise > 0:
                                    hw_ratio = (hw - inlet) / rise

                                    # CV_PF_02: Deep submergence (HW/D > 1.2)
                                    if hw_ratio > 1.2:
                                        msg = CheckMessage(
                                            message_id="CV_PF_02",
                                            severity=Severity.WARNING,
                                            check_type="STRUCT",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            structure=culvert_name,
                                            message=f"Inlet submerged by more than 1.2D (HW/D = {hw_ratio:.2f}) at culvert '{culvert_name}' for {profile}",
                                            help_text=get_help_text("CV_PF_02"),
                                            value=hw_ratio
                                        )
                                        messages.append(msg)

                                    # CV_PF_01: General pressure flow
                                    if hw_ratio > 1.0:
                                        msg = CheckMessage(
                                            message_id="CV_PF_01",
                                            severity=Severity.WARNING,
                                            check_type="STRUCT",
                                            river=river,
                                            reach=reach,
                                            station=station,
                                            structure=culvert_name,
                                            message=f"Pressure flow detected at culvert '{culvert_name}' for {profile}",
                                            help_text=get_help_text("CV_PF_01")
                                        )
                                        messages.append(msg)
                            except (ValueError, TypeError):
                                pass

                        # Check for combined pressure/weir flow
                        weir_q = result_attrs.get('Weir Q', result_attrs.get('Weir Flow', None))
                        culvert_q = result_attrs.get('Culvert Q', result_attrs.get('Culvert Flow', None))

                        if weir_q is not None and culvert_q is not None:
                            try:
                                weir_flow = float(weir_q)
                                culv_flow = float(culvert_q)

                                # CV_PW_01: Combined pressure and weir flow
                                if weir_flow > 0 and culv_flow > 0:
                                    msg = CheckMessage(
                                        message_id="CV_PW_01",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        structure=culvert_name,
                                        message=f"Combined pressure and weir flow at culvert '{culvert_name}' for {profile}",
                                        help_text=get_help_text("CV_PW_01")
                                    )
                                    messages.append(msg)
                            except (ValueError, TypeError):
                                pass

        except Exception as e:
            logger.debug(f"Could not read culvert results: {e}")

        return messages

    # =========================================================================
    # Inline Weir Flow Type Checks
    # =========================================================================

    @staticmethod
    def _check_inline_weirs(
        geom_hdf: Path,
        plan_hdf: Optional[Path],
        profiles: List[str],
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check inline weir flow types (IW_TF_* checks).

        Determines flow type for each inline weir:
        - IW_TF_01: Weir flow only (no gate flow)
        - IW_TF_02: Gate flow only (no weir flow)
        - IW_TF_03: Combined weir and gate flow

        Args:
            geom_hdf: Path to geometry HDF file
            plan_hdf: Path to plan HDF file (may be None for geometry-only checks)
            profiles: List of profile names to check
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for inline weir flow type observations
        """
        messages = []

        if plan_hdf is None or not plan_hdf.exists():
            return messages

        try:
            with h5py.File(geom_hdf, 'r') as geom_h, h5py.File(plan_hdf, 'r') as plan_h:
                # Check for inline weirs in geometry
                if 'Geometry/Structures/Attributes' not in geom_h:
                    return messages

                struct_attrs = geom_h['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                # Find inline weirs
                inline_weirs = []
                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    # Check for inline weir types
                    if 'Inline' in struct_type or 'Weir' in struct_type:
                        river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                        reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                        station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()
                        name = attr['Node Name'].decode('utf-8').strip() if 'Node Name' in attr_names and isinstance(attr['Node Name'], bytes) else str(attr.get('Node Name', f'IW_{station}'))

                        # Get weir attributes
                        weir_coef = float(attr['Weir Coef']) if 'Weir Coef' in attr_names else 0
                        has_gates = False

                        # Check for gate groups
                        if 'Gate Groups' in attr_names:
                            gate_groups = attr['Gate Groups']
                            if isinstance(gate_groups, bytes):
                                gate_groups = gate_groups.decode('utf-8').strip()
                            has_gates = len(str(gate_groups).strip()) > 0

                        inline_weirs.append({
                            'index': i,
                            'river': river,
                            'reach': reach,
                            'station': station,
                            'name': name,
                            'type': struct_type,
                            'weir_coef': weir_coef,
                            'has_gates': has_gates
                        })

                if not inline_weirs:
                    return messages

                # Check for steady results with structure flow data
                # Path varies: Results/Steady/Structures/ or Results/Steady/Structure/
                struct_results_base = None
                for base_path in ['Results/Steady/Structures', 'Results/Steady/Structure']:
                    if base_path in plan_h:
                        struct_results_base = base_path
                        break

                if struct_results_base is None:
                    # No structure results, just report weir presence
                    for weir in inline_weirs:
                        msg = CheckMessage(
                            message_id="IW_TF_01",
                            severity=Severity.INFO,
                            check_type="STRUCT",
                            river=weir['river'],
                            reach=weir['reach'],
                            station=weir['station'],
                            structure=weir['name'],
                            message=format_message("IW_TF_01", name=weir['name'], profile="all profiles"),
                            help_text=get_help_text("IW_TF_01")
                        )
                        messages.append(msg)
                    return messages

                # Process each inline weir
                for weir in inline_weirs:
                    for profile in profiles:
                        weir_flow = 0.0
                        gate_flow = 0.0

                        # Try to get flow data for this weir
                        # Structure results path: {base}/Node Name/Flow
                        weir_path = f"{struct_results_base}/{weir['name']}"

                        if weir_path in plan_h:
                            struct_group = plan_h[weir_path]

                            # Look for weir flow data
                            if 'Weir Flow' in struct_group:
                                weir_flow_data = struct_group['Weir Flow'][:]
                                # Find profile index
                                if 'Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names' in plan_h:
                                    profile_names = plan_h['Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names'][:]
                                    profile_names = [p.decode('utf-8').strip() if isinstance(p, bytes) else str(p).strip()
                                                   for p in profile_names]
                                    if profile in profile_names:
                                        prof_idx = profile_names.index(profile)
                                        if prof_idx < len(weir_flow_data):
                                            weir_flow = float(weir_flow_data[prof_idx])

                            # Look for gate flow data
                            if 'Gate Flow' in struct_group:
                                gate_flow_data = struct_group['Gate Flow'][:]
                                if 'Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names' in plan_h:
                                    profile_names = plan_h['Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names'][:]
                                    profile_names = [p.decode('utf-8').strip() if isinstance(p, bytes) else str(p).strip()
                                                   for p in profile_names]
                                    if profile in profile_names:
                                        prof_idx = profile_names.index(profile)
                                        if prof_idx < len(gate_flow_data):
                                            gate_flow = float(gate_flow_data[prof_idx])

                        # Determine flow type and generate message
                        flow_tolerance = 0.1  # cfs tolerance

                        has_weir_flow = abs(weir_flow) > flow_tolerance
                        has_gate_flow = abs(gate_flow) > flow_tolerance

                        if has_weir_flow and has_gate_flow:
                            # IW_TF_03: Combined flow
                            msg = CheckMessage(
                                message_id="IW_TF_03",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=weir['river'],
                                reach=weir['reach'],
                                station=weir['station'],
                                structure=weir['name'],
                                message=format_message("IW_TF_03", name=weir['name'], profile=profile),
                                help_text=get_help_text("IW_TF_03"),
                                value=weir_flow + gate_flow
                            )
                            messages.append(msg)
                        elif has_gate_flow and not has_weir_flow:
                            # IW_TF_02: Gate flow only
                            msg = CheckMessage(
                                message_id="IW_TF_02",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=weir['river'],
                                reach=weir['reach'],
                                station=weir['station'],
                                structure=weir['name'],
                                message=format_message("IW_TF_02", name=weir['name'], profile=profile),
                                help_text=get_help_text("IW_TF_02"),
                                value=gate_flow
                            )
                            messages.append(msg)
                        elif has_weir_flow and not has_gate_flow:
                            # IW_TF_01: Weir flow only
                            msg = CheckMessage(
                                message_id="IW_TF_01",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=weir['river'],
                                reach=weir['reach'],
                                station=weir['station'],
                                structure=weir['name'],
                                message=format_message("IW_TF_01", name=weir['name'], profile=profile),
                                help_text=get_help_text("IW_TF_01"),
                                value=weir_flow
                            )
                            messages.append(msg)
                        # If no flow at all, don't generate a message

                        # IW_TF_04: Check for tailwater submergence
                        if has_weir_flow and weir_path in plan_h:
                            struct_group = plan_h[weir_path]

                            # Get WSE data to check submergence
                            headwater_elev = None
                            tailwater_elev = None
                            crest_elev = None

                            # Try to get headwater/tailwater elevations
                            if 'HW Elev' in struct_group:
                                hw_data = struct_group['HW Elev'][:]
                                # Get profile-specific value
                                profile_names_path = 'Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names'
                                alt_profile_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names'
                                for ppath in [profile_names_path, alt_profile_path]:
                                    if ppath in plan_h:
                                        profile_names = plan_h[ppath][:]
                                        profile_names = [p.decode('utf-8').strip() if isinstance(p, bytes) else str(p).strip()
                                                       for p in profile_names]
                                        if profile in profile_names:
                                            prof_idx = profile_names.index(profile)
                                            if prof_idx < len(hw_data):
                                                headwater_elev = float(hw_data[prof_idx])
                                        break

                            if 'TW Elev' in struct_group:
                                tw_data = struct_group['TW Elev'][:]
                                for ppath in [profile_names_path, alt_profile_path]:
                                    if ppath in plan_h:
                                        profile_names = plan_h[ppath][:]
                                        profile_names = [p.decode('utf-8').strip() if isinstance(p, bytes) else str(p).strip()
                                                       for p in profile_names]
                                        if profile in profile_names:
                                            prof_idx = profile_names.index(profile)
                                            if prof_idx < len(tw_data):
                                                tailwater_elev = float(tw_data[prof_idx])
                                        break

                            # Try to get crest elevation from geometry
                            if 'Crest Elev' in struct_group.attrs:
                                crest_elev = float(struct_group.attrs['Crest Elev'])
                            elif 'Weir Crest' in attr_names:
                                crest_elev = float(attr['Weir Crest']) if 'Weir Crest' in attr_names else None

                            # Check for submergence condition
                            if tailwater_elev is not None and crest_elev is not None:
                                # Submergence occurs when TW approaches or exceeds crest
                                if tailwater_elev > crest_elev - 0.5:  # Within 0.5 ft of crest
                                    msg = CheckMessage(
                                        message_id="IW_TF_04",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=weir['river'],
                                        reach=weir['reach'],
                                        station=weir['station'],
                                        structure=weir['name'],
                                        message=format_message("IW_TF_04",
                                                              name=weir['name'],
                                                              tw_elev=tailwater_elev,
                                                              crest=crest_elev,
                                                              profile=profile),
                                        help_text=get_help_text("IW_TF_04"),
                                        value=tailwater_elev,
                                        threshold=crest_elev
                                    )
                                    messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check inline weir flow types: {e}")

        return messages

    @staticmethod
    def _check_bridge_flow_types(
        geom_hdf: Path,
        plan_hdf: Optional[Path],
        profiles: List[str],
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check bridge flow types and classifications (BR_TF_*, BR_PF_*, BR_PW_*).

        Determines flow type for each bridge based on results:
        - BR_TF_01: Low flow Class A (free surface through bridge)
        - BR_TF_02: Low flow Class B (free surface with hydraulic jump DS)
        - BR_TF_03: Low flow Class C (supercritical through bridge)
        - BR_TF_04: High flow (pressure only)
        - BR_TF_05: High flow (weir only)
        - BR_TF_06: High flow (pressure and weir combined)
        - BR_PF_01: Pressure flow detected at bridge
        - BR_PF_02: Weir flow detected over bridge deck
        - BR_PF_03: Flow type for highest frequency profile differs from others
        - BR_PF_04: Pressure flow with Class B low flow (transitional conditions)
        - BR_PF_05: Submergence ratio indicates orifice flow (TW/HW ratio >= 0.8)
        - BR_PF_06: Tailwater controls pressure flow (TW near deck elevation)
        - BR_PF_07: Energy-based pressure flow method mismatch (non-Energy method with pressure)
        - BR_PF_08: Pressure flow coefficient outside typical range (0.8-1.0)
        - BR_PW_01: Sluice gate coefficients used for pressure flow
        - BR_PW_02: High flow method is not Energy (recommend Energy method)

        Bridge flow classification logic:
        - Class A: WSE below low chord both US and DS
        - Class B: WSE above low chord US, below DS (hydraulic jump downstream)
        - Class C: Supercritical flow through (rare)
        - Pressure: WSE above high chord (deck)
        - Weir: Roadway overtopping
        - Combined: Both pressure and weir flow

        Pressure flow checks (BR_PF_04-08):
        - BR_PF_04 detects transitional Class B + pressure flow conditions
        - BR_PF_05 checks submergence ratio for orifice vs sluice gate flow
        - BR_PF_06 warns when tailwater controls the pressure flow
        - BR_PF_07 recommends Energy method for pressure flow computations
        - BR_PF_08 validates pressure flow coefficient against typical range

        Args:
            geom_hdf: Path to geometry HDF file
            plan_hdf: Path to plan HDF file (may be None for geometry-only checks)
            profiles: List of profile names to check
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for bridge flow type observations
        """
        messages = []

        # First, do geometry-only checks (BR_PW_01, BR_PW_02)
        try:
            with h5py.File(geom_hdf, 'r') as geom_h:
                if 'Geometry/Structures/Attributes' not in geom_h:
                    return messages

                struct_attrs = geom_h['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                # Collect bridge information
                bridges = []
                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    if 'Bridge' not in struct_type:
                        continue

                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()
                    name = attr['Node Name'].decode('utf-8').strip() if 'Node Name' in attr_names and isinstance(attr['Node Name'], bytes) else str(attr.get('Node Name', f'BR_{station}'))

                    # Get bridge-specific attributes
                    low_chord = float(attr['Low Chord']) if 'Low Chord' in attr_names else 0
                    high_chord = float(attr['High Chord']) if 'High Chord' in attr_names else 0
                    deck_elev = float(attr['Deck/Roadway']) if 'Deck/Roadway' in attr_names else high_chord
                    weir_coef = float(attr['Weir Coef']) if 'Weir Coef' in attr_names else 0

                    # Check for sluice gate coefficient (BR_PW_01)
                    sluice_coef = float(attr['Sluice Gate Coef']) if 'Sluice Gate Coef' in attr_names else 0
                    if sluice_coef > 0:
                        msg = CheckMessage(
                            message_id="BR_PW_01",
                            severity=Severity.INFO,
                            check_type="STRUCT",
                            river=river,
                            reach=reach,
                            station=station,
                            structure=name,
                            message=format_message("BR_PW_01", cd=f"{sluice_coef:.2f}"),
                            help_text=get_help_text("BR_PW_01"),
                            value=sluice_coef
                        )
                        messages.append(msg)

                    # BR_LW_02: Check bridge weir coefficient
                    if weir_coef > 0:
                        if weir_coef < 2.5 or weir_coef > 3.1:
                            msg = CheckMessage(
                                message_id="BR_LW_02",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("BR_LW_02", coef=weir_coef, name=name),
                                help_text=get_help_text("BR_LW_02"),
                                value=weir_coef
                            )
                            messages.append(msg)

                    # BR_LW_01: Check lateral weir length vs roadway width
                    weir_length = float(attr['Weir Length']) if 'Weir Length' in attr_names else 0
                    roadway_width = 0
                    if 'Roadway Left Sta' in attr_names and 'Roadway Right Sta' in attr_names:
                        roadway_left = float(attr['Roadway Left Sta'])
                        roadway_right = float(attr['Roadway Right Sta'])
                        roadway_width = abs(roadway_right - roadway_left)
                    elif 'BR US Left Bank' in attr_names and 'BR US Right Bank' in attr_names:
                        # Use abutment stations as proxy for roadway width
                        left_abut = float(attr['BR US Left Bank'])
                        right_abut = float(attr['BR US Right Bank'])
                        roadway_width = abs(right_abut - left_abut) if right_abut > left_abut else 0

                    if weir_length > 0 and roadway_width > 0:
                        # Flag if weir length differs from roadway width by more than 50%
                        diff_pct = abs(weir_length - roadway_width) / roadway_width * 100
                        if diff_pct > 50:
                            msg = CheckMessage(
                                message_id="BR_LW_01",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("BR_LW_01", length=weir_length, roadway=roadway_width),
                                help_text=get_help_text("BR_LW_01"),
                                value=weir_length,
                                threshold=roadway_width
                            )
                            messages.append(msg)

                    # Check for high flow method (BR_PW_02)
                    high_flow_method = attr['High Flow Method'] if 'High Flow Method' in attr_names else None
                    if high_flow_method is not None:
                        if isinstance(high_flow_method, bytes):
                            high_flow_method = high_flow_method.decode('utf-8').strip()
                        else:
                            high_flow_method = str(high_flow_method).strip()

                        # Check if it's not Energy method (0 = Energy, 1 = Momentum, etc.)
                        try:
                            hf_method_int = int(high_flow_method)
                            if hf_method_int != 0:  # Not Energy method
                                msg = CheckMessage(
                                    message_id="BR_PW_02",
                                    severity=Severity.INFO,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    structure=name,
                                    message=get_message_template("BR_PW_02"),
                                    help_text=get_help_text("BR_PW_02")
                                )
                                messages.append(msg)
                        except (ValueError, TypeError):
                            pass

                    # Store high flow method value for BR_PF_07 check
                    high_flow_method_value = None
                    if high_flow_method is not None:
                        try:
                            high_flow_method_value = int(high_flow_method) if not isinstance(high_flow_method, str) else int(high_flow_method)
                        except (ValueError, TypeError):
                            high_flow_method_value = high_flow_method

                    bridges.append({
                        'index': i,
                        'river': river,
                        'reach': reach,
                        'station': station,
                        'name': name,
                        'low_chord': low_chord,
                        'high_chord': high_chord,
                        'deck_elev': deck_elev,
                        'weir_coef': weir_coef,
                        'sluice_coef': sluice_coef,
                        'high_flow_method': high_flow_method_value
                    })

        except Exception as e:
            logger.warning(f"Could not read bridge attributes for flow type check: {e}")
            return messages

        if not bridges:
            return messages

        # Now check results-based flow types (BR_TF_*, BR_PF_*)
        if plan_hdf is None or not plan_hdf.exists():
            return messages

        try:
            with h5py.File(plan_hdf, 'r') as plan_h:
                # Check for steady results
                if 'Results/Steady' not in plan_h:
                    return messages

                # Get profile names
                profile_path = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Profile Names'
                alt_profile_path = 'Results/Steady/Output/Output Blocks/Steady Profiles/Profile Names'

                available_profiles = []
                for ppath in [profile_path, alt_profile_path]:
                    if ppath in plan_h:
                        profile_names = plan_h[ppath][:]
                        available_profiles = [p.decode('utf-8').strip() if isinstance(p, bytes) else str(p).strip()
                                             for p in profile_names]
                        break

                if not available_profiles:
                    return messages

                # Try to get structure output data
                struct_output_base = None
                for base in ['Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/Structure Output',
                            'Results/Steady/Output/Output Blocks/Steady Profiles/Structure Output',
                            'Results/Steady/Structures']:
                    if base in plan_h:
                        struct_output_base = base
                        break

                # Track flow types per bridge for BR_PF_03 check
                bridge_flow_types = {}  # bridge_key -> {profile: flow_type}

                for bridge in bridges:
                    bridge_key = (bridge['river'], bridge['reach'], bridge['station'])
                    bridge_flow_types[bridge_key] = {}

                    for profile in profiles:
                        if profile not in available_profiles:
                            continue

                        prof_idx = available_profiles.index(profile)

                        # Initialize flow type detection
                        us_wse = None
                        ds_wse = None
                        pressure_flow = 0.0
                        weir_flow = 0.0
                        froude_us = None

                        # Try to get structure-specific output
                        if struct_output_base:
                            struct_name = bridge['name']
                            struct_path = f"{struct_output_base}/{struct_name}"

                            if struct_path in plan_h:
                                struct_data = plan_h[struct_path]

                                # Get pressure flow
                                if 'Pressure Flow' in struct_data:
                                    pf_data = struct_data['Pressure Flow'][:]
                                    if prof_idx < len(pf_data):
                                        pressure_flow = float(pf_data[prof_idx])

                                # Get weir flow
                                if 'Weir Flow' in struct_data:
                                    wf_data = struct_data['Weir Flow'][:]
                                    if prof_idx < len(wf_data):
                                        weir_flow = float(wf_data[prof_idx])

                                # Get US/DS WSE if available
                                if 'US WSE' in struct_data:
                                    us_wse_data = struct_data['US WSE'][:]
                                    if prof_idx < len(us_wse_data):
                                        us_wse = float(us_wse_data[prof_idx])

                                if 'DS WSE' in struct_data:
                                    ds_wse_data = struct_data['DS WSE'][:]
                                    if prof_idx < len(ds_wse_data):
                                        ds_wse = float(ds_wse_data[prof_idx])

                        # Classify flow type
                        flow_tolerance = 0.1  # cfs tolerance
                        has_pressure_flow = abs(pressure_flow) > flow_tolerance
                        has_weir_flow = abs(weir_flow) > flow_tolerance

                        low_chord = bridge['low_chord']

                        # Determine flow type
                        flow_type = None
                        msg_id = None
                        severity = Severity.INFO

                        if has_pressure_flow and has_weir_flow:
                            # BR_TF_06: High flow (pressure and weir combined)
                            flow_type = "pressure_weir"
                            msg_id = "BR_TF_06"
                            severity = Severity.WARNING
                        elif has_pressure_flow and not has_weir_flow:
                            # BR_TF_04: High flow (pressure only)
                            flow_type = "pressure"
                            msg_id = "BR_TF_04"
                            severity = Severity.WARNING
                        elif has_weir_flow and not has_pressure_flow:
                            # BR_TF_05: High flow (weir only)
                            flow_type = "weir"
                            msg_id = "BR_TF_05"
                            severity = Severity.INFO
                        elif us_wse is not None and ds_wse is not None and low_chord > 0:
                            # Low flow classification based on WSE vs low chord
                            us_below_low_chord = us_wse < low_chord
                            ds_below_low_chord = ds_wse < low_chord

                            if us_below_low_chord and ds_below_low_chord:
                                # BR_TF_01: Class A - free surface both sides
                                flow_type = "class_a"
                                msg_id = "BR_TF_01"
                                severity = Severity.INFO
                            elif not us_below_low_chord and ds_below_low_chord:
                                # BR_TF_02: Class B - hydraulic jump downstream
                                flow_type = "class_b"
                                msg_id = "BR_TF_02"
                                severity = Severity.WARNING
                            elif froude_us is not None and froude_us > 1.0:
                                # BR_TF_03: Class C - supercritical
                                flow_type = "class_c"
                                msg_id = "BR_TF_03"
                                severity = Severity.WARNING
                            else:
                                # Default to Class A for low flow without enough info
                                flow_type = "class_a"
                                msg_id = "BR_TF_01"
                                severity = Severity.INFO
                        else:
                            # Not enough data to classify - skip this profile
                            continue

                        # Store flow type for BR_PF_03 check
                        bridge_flow_types[bridge_key][profile] = flow_type

                        # Generate message for this bridge/profile
                        if msg_id:
                            msg = CheckMessage(
                                message_id=msg_id,
                                severity=severity,
                                check_type="STRUCT",
                                river=bridge['river'],
                                reach=bridge['reach'],
                                station=bridge['station'],
                                structure=bridge['name'],
                                message=format_message(msg_id, profile=profile),
                                help_text=get_help_text(msg_id)
                            )
                            messages.append(msg)

                        # BR_PF_01: Pressure flow detected
                        if has_pressure_flow:
                            msg = CheckMessage(
                                message_id="BR_PF_01",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=bridge['river'],
                                reach=bridge['reach'],
                                station=bridge['station'],
                                structure=bridge['name'],
                                message=format_message("BR_PF_01", profile=profile),
                                help_text=get_help_text("BR_PF_01"),
                                value=pressure_flow
                            )
                            messages.append(msg)

                        # BR_PF_02: Weir flow detected
                        if has_weir_flow:
                            msg = CheckMessage(
                                message_id="BR_PF_02",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=bridge['river'],
                                reach=bridge['reach'],
                                station=bridge['station'],
                                structure=bridge['name'],
                                message=format_message("BR_PF_02", profile=profile),
                                help_text=get_help_text("BR_PF_02"),
                                value=weir_flow
                            )
                            messages.append(msg)

                        # BR_PF_04: Pressure flow with Class B low flow
                        # Class B is when US WSE > low chord but DS WSE < low chord
                        if has_pressure_flow and flow_type == "class_b":
                            msg = CheckMessage(
                                message_id="BR_PF_04",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=bridge['river'],
                                reach=bridge['reach'],
                                station=bridge['station'],
                                structure=bridge['name'],
                                message=format_message("BR_PF_04", profile=profile),
                                help_text=get_help_text("BR_PF_04")
                            )
                            messages.append(msg)

                        # BR_PF_05, BR_PF_06: Submergence and tailwater control checks
                        # These require both US and DS WSE data plus deck elevation
                        deck_elev = bridge['deck_elev']
                        high_chord = bridge['high_chord']
                        effective_deck = deck_elev if deck_elev > 0 else high_chord

                        if has_pressure_flow and us_wse is not None and ds_wse is not None and effective_deck > 0:
                            # Calculate submergence ratio for orifice flow check
                            # Submergence = (TW depth above deck) / (HW depth above deck)
                            hw_depth_above_deck = us_wse - effective_deck
                            tw_depth_above_deck = ds_wse - effective_deck

                            if hw_depth_above_deck > 0:
                                submergence_ratio = tw_depth_above_deck / hw_depth_above_deck if tw_depth_above_deck > 0 else 0

                                # BR_PF_05: Submergence ratio indicates orifice flow
                                if submergence_ratio >= thresholds.structures.orifice_flow_submergence_ratio:
                                    msg = CheckMessage(
                                        message_id="BR_PF_05",
                                        severity=Severity.INFO,
                                        check_type="STRUCT",
                                        river=bridge['river'],
                                        reach=bridge['reach'],
                                        station=bridge['station'],
                                        structure=bridge['name'],
                                        message=format_message("BR_PF_05", submergence=submergence_ratio, profile=profile),
                                        help_text=get_help_text("BR_PF_05"),
                                        value=submergence_ratio,
                                        threshold=thresholds.structures.orifice_flow_submergence_ratio
                                    )
                                    messages.append(msg)

                            # BR_PF_06: Tailwater controls pressure flow
                            # When TW approaches or exceeds deck elevation
                            tw_control_threshold = effective_deck - thresholds.structures.tailwater_control_tolerance_ft
                            if ds_wse >= tw_control_threshold:
                                msg = CheckMessage(
                                    message_id="BR_PF_06",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=bridge['river'],
                                    reach=bridge['reach'],
                                    station=bridge['station'],
                                    structure=bridge['name'],
                                    message=format_message("BR_PF_06", tw_elev=ds_wse, deck_elev=effective_deck, profile=profile),
                                    help_text=get_help_text("BR_PF_06"),
                                    value=ds_wse,
                                    threshold=tw_control_threshold
                                )
                                messages.append(msg)

                        # BR_PF_07: Energy-based pressure flow method mismatch
                        # When pressure flow occurs, check if energy method is used
                        if has_pressure_flow and bridge.get('high_flow_method') is not None:
                            hf_method = bridge.get('high_flow_method')
                            # 0 = Energy, non-zero = other methods (Momentum, etc.)
                            if hf_method != 0 and hf_method != '0':
                                method_names = {
                                    1: 'Momentum', '1': 'Momentum',
                                    2: 'Yarnell', '2': 'Yarnell',
                                    3: 'WSPRO', '3': 'WSPRO'
                                }
                                method_name = method_names.get(hf_method, str(hf_method))
                                msg = CheckMessage(
                                    message_id="BR_PF_07",
                                    severity=Severity.INFO,
                                    check_type="STRUCT",
                                    river=bridge['river'],
                                    reach=bridge['reach'],
                                    station=bridge['station'],
                                    structure=bridge['name'],
                                    message=format_message("BR_PF_07", method=method_name, profile=profile),
                                    help_text=get_help_text("BR_PF_07")
                                )
                                messages.append(msg)

                        # BR_PF_08: Pressure flow coefficient outside typical range
                        # Check the sluice gate coefficient (pressure flow Cd)
                        if has_pressure_flow and bridge.get('sluice_coef') is not None:
                            sluice_coef = bridge.get('sluice_coef', 0)
                            if sluice_coef > 0:
                                pf_coef_min = thresholds.structures.pressure_flow_coef_min
                                pf_coef_max = thresholds.structures.pressure_flow_coef_max
                                if sluice_coef < pf_coef_min or sluice_coef > pf_coef_max:
                                    msg = CheckMessage(
                                        message_id="BR_PF_08",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=bridge['river'],
                                        reach=bridge['reach'],
                                        station=bridge['station'],
                                        structure=bridge['name'],
                                        message=format_message("BR_PF_08", coef=sluice_coef, profile=profile),
                                        help_text=get_help_text("BR_PF_08"),
                                        value=sluice_coef,
                                        threshold=pf_coef_min  # Use min as reference
                                    )
                                    messages.append(msg)

                # BR_PF_03: Check if highest frequency profile differs from others
                for bridge_key, profile_types in bridge_flow_types.items():
                    if len(profile_types) < 2:
                        continue

                    # Find the highest frequency profile (typically first in list)
                    sorted_profiles = [p for p in profiles if p in profile_types]
                    if len(sorted_profiles) < 2:
                        continue

                    highest_freq_profile = sorted_profiles[0]
                    highest_freq_type = profile_types.get(highest_freq_profile)

                    # Check if any other profile has a different type
                    different_types = [p for p in sorted_profiles[1:]
                                      if profile_types.get(p) != highest_freq_type]

                    if different_types and highest_freq_type:
                        # Find the bridge info
                        bridge_info = next((b for b in bridges
                                           if (b['river'], b['reach'], b['station']) == bridge_key), None)
                        if bridge_info:
                            msg = CheckMessage(
                                message_id="BR_PF_03",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=bridge_info['river'],
                                reach=bridge_info['reach'],
                                station=bridge_info['station'],
                                structure=bridge_info['name'],
                                message=format_message("BR_PF_03", flow_type=highest_freq_type),
                                help_text=get_help_text("BR_PF_03")
                            )
                            messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check bridge flow types from results: {e}")

        return messages

    # =========================================================================
    # Structure Distance and Geometry Checks
    # =========================================================================

    @staticmethod
    def _check_structure_distances(
        geom_hdf: Path,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check upstream/downstream distances at structures (ST_DT_* checks).

        Validates:
        - ST_DT_01: Upstream distance too short for flow expansion
        - ST_DT_02: Downstream distance too short for contraction recovery

        Args:
            geom_hdf: Path to geometry HDF file
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for structure distance issues
        """
        messages = []

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()
                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()
                    name = attr['Node Name'].decode('utf-8').strip() if 'Node Name' in attr_names and isinstance(attr['Node Name'], bytes) else station

                    # Get distances
                    us_dist = float(attr['Upstream Distance']) if 'Upstream Distance' in attr_names else 0
                    ds_dist = float(attr['Downstream Distance']) if 'Downstream Distance' in attr_names else 0

                    # Get opening width for ratio check (if available)
                    opening_width = 0
                    if 'Bridge' in struct_type:
                        # For bridges, use abutment stations
                        left_abut = float(attr['BR US Left Bank']) if 'BR US Left Bank' in attr_names else 0
                        right_abut = float(attr['BR US Right Bank']) if 'BR US Right Bank' in attr_names else 0
                        if left_abut > 0 and right_abut > 0:
                            opening_width = abs(right_abut - left_abut)

                    # Determine minimum distance thresholds
                    # Rule of thumb: US distance should be 1x expansion length (min 50 ft for bridges)
                    # DS distance should be 2x contraction length (min 100 ft)
                    if 'Bridge' in struct_type:
                        min_us = max(50, opening_width * 1.0) if opening_width > 0 else 50
                        min_ds = max(30, opening_width * 0.5) if opening_width > 0 else 30
                    elif 'Culvert' in struct_type:
                        min_us = 30
                        min_ds = 20
                    elif 'Inline' in struct_type or 'Weir' in struct_type:
                        min_us = 20
                        min_ds = 20
                    else:
                        continue  # Unknown structure type

                    # ST_DT_01: Check upstream distance
                    if us_dist > 0 and us_dist < min_us:
                        msg = CheckMessage(
                            message_id="ST_DT_01",
                            severity=Severity.WARNING,
                            check_type="STRUCT",
                            river=river,
                            reach=reach,
                            station=station,
                            structure=name,
                            message=format_message("ST_DT_01", dist=f"{us_dist:.1f}", name=name),
                            help_text=get_help_text("ST_DT_01"),
                            value=us_dist,
                            threshold=min_us
                        )
                        messages.append(msg)

                    # ST_DT_02: Check downstream distance
                    if ds_dist > 0 and ds_dist < min_ds:
                        msg = CheckMessage(
                            message_id="ST_DT_02",
                            severity=Severity.WARNING,
                            check_type="STRUCT",
                            river=river,
                            reach=reach,
                            station=station,
                            structure=name,
                            message=format_message("ST_DT_02", dist=f"{ds_dist:.1f}", name=name),
                            help_text=get_help_text("ST_DT_02"),
                            value=ds_dist,
                            threshold=min_ds
                        )
                        messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check structure distances: {e}")

        return messages

    @staticmethod
    def _check_structure_ineffective_section3(
        geom_hdf: Path,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check structure ineffective flow at Section 3 (ST_IF_04L/R checks).

        Validates that ineffective flow areas extend to abutments at Section 3
        (downstream face of bridge).

        Args:
            geom_hdf: Path to geometry HDF file
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for Section 3 ineffective flow issues
        """
        messages = []

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    # Only check bridges (have abutments)
                    if 'Bridge' not in struct_type:
                        continue

                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                    # Get downstream ineffective flow stations (Section 3)
                    ds_ineff_left_sta = float(attr['DS Ineff Left Sta']) if 'DS Ineff Left Sta' in attr_names else 0
                    ds_ineff_right_sta = float(attr['DS Ineff Right Sta']) if 'DS Ineff Right Sta' in attr_names else 0

                    # Get downstream bank stations (abutments)
                    br_ds_left_bank = float(attr['BR DS Left Bank']) if 'BR DS Left Bank' in attr_names else 0
                    br_ds_right_bank = float(attr['BR DS Right Bank']) if 'BR DS Right Bank' in attr_names else 0

                    tolerance = 5.0  # 5 ft tolerance

                    # ST_IF_04L: Left ineffective should extend to left abutment
                    if ds_ineff_left_sta > 0 and br_ds_left_bank > 0:
                        # Left ineffective right station should be near left abutment
                        if ds_ineff_right_sta < br_ds_left_bank - tolerance:
                            msg = CheckMessage(
                                message_id="ST_IF_04L",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_IF_04L"),
                                help_text=get_help_text("ST_IF_04L")
                            )
                            messages.append(msg)

                    # ST_IF_04R: Right ineffective should extend to right abutment
                    if ds_ineff_right_sta > 0 and br_ds_right_bank > 0:
                        # Right ineffective left station should be near right abutment
                        if ds_ineff_left_sta > br_ds_right_bank + tolerance:
                            msg = CheckMessage(
                                message_id="ST_IF_04R",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_IF_04R"),
                                help_text=get_help_text("ST_IF_04R")
                            )
                            messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check Section 3 ineffective flow: {e}")

        return messages

    @staticmethod
    def _check_structure_permanent_ineffective(
        geom_hdf: Path,
        is_floodway: bool = False
    ) -> List[CheckMessage]:
        """
        Check for permanent ineffective flow at structures (ST_IF_05).

        Permanent ineffective flow may be problematic in floodway analysis.

        Args:
            geom_hdf: Path to geometry HDF file
            is_floodway: True if this is a floodway analysis

        Returns:
            List of CheckMessage objects for permanent ineffective flow issues
        """
        messages = []

        if not is_floodway:
            return messages  # Only check in floodway context

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    if 'Bridge' not in struct_type:
                        continue

                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                    # Check for permanent ineffective flags
                    us_ineff_perm = False
                    ds_ineff_perm = False

                    if 'US Ineff Permanent' in attr_names:
                        us_ineff_perm = bool(attr['US Ineff Permanent'])
                    if 'DS Ineff Permanent' in attr_names:
                        ds_ineff_perm = bool(attr['DS Ineff Permanent'])

                    if us_ineff_perm or ds_ineff_perm:
                        msg = CheckMessage(
                            message_id="ST_IF_05",
                            severity=Severity.WARNING,
                            check_type="STRUCT",
                            river=river,
                            reach=reach,
                            station=station,
                            message=get_message_template("ST_IF_05"),
                            help_text=get_help_text("ST_IF_05")
                        )
                        messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check permanent ineffective flow: {e}")

        return messages

    @staticmethod
    def _check_structure_geometry_alignment(
        geom_hdf: Path,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check structure geometry alignment (ST_GE_02L/R, ST_GE_03 checks).

        Validates:
        - ST_GE_02L/R: Section 3 effective stations align with roadway
        - ST_GE_03: Ground/roadway station differences

        Args:
            geom_hdf: Path to geometry HDF file
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for geometry alignment issues
        """
        messages = []

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()

                    if 'Bridge' not in struct_type:
                        continue

                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()

                    # Get Section 3 bank stations
                    br_ds_left_bank = float(attr['BR DS Left Bank']) if 'BR DS Left Bank' in attr_names else 0
                    br_ds_right_bank = float(attr['BR DS Right Bank']) if 'BR DS Right Bank' in attr_names else 0

                    # Get XS bank stations for comparison
                    xs_ds_left_bank = float(attr['XS DS Left Bank']) if 'XS DS Left Bank' in attr_names else 0
                    xs_ds_right_bank = float(attr['XS DS Right Bank']) if 'XS DS Right Bank' in attr_names else 0

                    tolerance = 50.0  # 50 ft tolerance

                    # ST_GE_02L: Left bank alignment at Section 3
                    if br_ds_left_bank > 0 and xs_ds_left_bank > 0:
                        if abs(br_ds_left_bank - xs_ds_left_bank) > tolerance:
                            msg = CheckMessage(
                                message_id="ST_GE_02L",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_GE_02L"),
                                help_text=get_help_text("ST_GE_02L")
                            )
                            messages.append(msg)

                    # ST_GE_02R: Right bank alignment at Section 3
                    if br_ds_right_bank > 0 and xs_ds_right_bank > 0:
                        if abs(br_ds_right_bank - xs_ds_right_bank) > tolerance:
                            msg = CheckMessage(
                                message_id="ST_GE_02R",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_GE_02R"),
                                help_text=get_help_text("ST_GE_02R")
                            )
                            messages.append(msg)

                    # ST_GE_03: Ground/roadway station difference
                    # Check if roadway extends significantly beyond ground
                    roadway_left = float(attr['Roadway Left Sta']) if 'Roadway Left Sta' in attr_names else 0
                    roadway_right = float(attr['Roadway Right Sta']) if 'Roadway Right Sta' in attr_names else 0
                    ground_left = float(attr['Ground Left Sta']) if 'Ground Left Sta' in attr_names else 0
                    ground_right = float(attr['Ground Right Sta']) if 'Ground Right Sta' in attr_names else 0

                    roadway_tolerance = 10.0  # 10 ft tolerance

                    if roadway_left > 0 and ground_left > 0:
                        if abs(roadway_left - ground_left) > roadway_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GE_03",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_GE_03"),
                                help_text=get_help_text("ST_GE_03")
                            )
                            messages.append(msg)
                    elif roadway_right > 0 and ground_right > 0:
                        if abs(roadway_right - ground_right) > roadway_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GE_03",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                message=get_message_template("ST_GE_03"),
                                help_text=get_help_text("ST_GE_03")
                            )
                            messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check structure geometry alignment: {e}")

        return messages

    @staticmethod
    def _check_structure_ground(
        geom_hdf: Path,
        thresholds: ValidationThresholds
    ) -> List[CheckMessage]:
        """
        Check structure ground/terrain data validity (ST_GD_* checks).

        Validates:
        - ST_GD_01: Ground data missing at structure
        - ST_GD_02: Ground elevation discontinuity at structure
        - ST_GD_03L/R: Left/Right ground below structure invert
        - ST_GD_04L/R: Left/Right ground above structure deck
        - ST_GD_05: Ground slope exceeds threshold at structure
        - ST_GD_06: Ground data inconsistent between approach sections
        - ST_GD_07: Approach section ground doesn't match structure
        - ST_GD_08: Pier ground elevation issues
        - ST_GD_09: Abutment ground elevation issues
        - ST_GD_10: Embankment slope too steep
        - ST_GD_11: Fill depth exceeds reasonable limit

        Args:
            geom_hdf: Path to geometry HDF file
            thresholds: ValidationThresholds instance

        Returns:
            List of CheckMessage objects for structure ground data issues
        """
        messages = []

        # Threshold values for ground checks
        ground_elev_tolerance = 2.0  # ft - tolerance for ground/structure elevation comparison
        ground_discontinuity_threshold = 5.0  # ft - max acceptable discontinuity
        ground_slope_threshold = 0.1  # ft/ft - 10% slope threshold
        embankment_slope_threshold = 1.5  # H:V - steeper than 1.5:1 is unusual
        fill_depth_threshold = 30.0  # ft - max reasonable fill depth

        try:
            with h5py.File(geom_hdf, 'r') as hdf:
                if 'Geometry/Structures/Attributes' not in hdf:
                    return messages

                struct_attrs = hdf['Geometry/Structures/Attributes'][:]
                attr_names = struct_attrs.dtype.names

                # Get cross section data for approach section comparisons
                xs_attrs = None
                xs_sta_elev_info = None
                xs_sta_elev_values = None
                if 'Geometry/Cross Sections/Attributes' in hdf:
                    xs_attrs = hdf['Geometry/Cross Sections/Attributes'][:]
                if 'Geometry/Cross Sections/Station Elevation Info' in hdf:
                    xs_sta_elev_info = hdf['Geometry/Cross Sections/Station Elevation Info'][:]
                if 'Geometry/Cross Sections/Station Elevation Values' in hdf:
                    xs_sta_elev_values = hdf['Geometry/Cross Sections/Station Elevation Values'][:]

                # Check for structure ground data
                struct_ground_data = None
                struct_ground_info = None
                if 'Geometry/Structures/Ground Data' in hdf:
                    struct_ground_data = hdf['Geometry/Structures/Ground Data'][:]
                if 'Geometry/Structures/Ground Info' in hdf:
                    struct_ground_info = hdf['Geometry/Structures/Ground Info'][:]

                # Check deck/roadway data
                deck_data = None
                deck_info = None
                if 'Geometry/Structures/Deck Data' in hdf:
                    deck_data = hdf['Geometry/Structures/Deck Data'][:]
                if 'Geometry/Structures/Deck Info' in hdf or 'Geometry/Structures/Table Info' in hdf:
                    deck_info = hdf.get('Geometry/Structures/Deck Info', hdf.get('Geometry/Structures/Table Info', None))
                    if deck_info is not None:
                        deck_info = deck_info[:]

                # Check pier data
                pier_data = None
                pier_info = None
                if 'Geometry/Structures/Pier Data' in hdf:
                    pier_data = hdf['Geometry/Structures/Pier Data'][:]
                if 'Geometry/Structures/Pier Info' in hdf:
                    pier_info = hdf['Geometry/Structures/Pier Info'][:]

                for i, attr in enumerate(struct_attrs):
                    struct_type = attr['Type'].decode('utf-8').strip() if isinstance(attr['Type'], bytes) else str(attr['Type']).strip()
                    river = attr['River'].decode('utf-8').strip() if isinstance(attr['River'], bytes) else str(attr['River']).strip()
                    reach = attr['Reach'].decode('utf-8').strip() if isinstance(attr['Reach'], bytes) else str(attr['Reach']).strip()
                    station = attr['RS'].decode('utf-8').strip() if isinstance(attr['RS'], bytes) else str(attr['RS']).strip()
                    name = attr['Node Name'].decode('utf-8').strip() if 'Node Name' in attr_names and isinstance(attr['Node Name'], bytes) else station

                    # Get approach section RS values
                    us_rs = attr['US RS'].decode('utf-8').strip() if 'US RS' in attr_names and isinstance(attr['US RS'], bytes) else ''
                    ds_rs = attr['DS RS'].decode('utf-8').strip() if 'DS RS' in attr_names and isinstance(attr['DS RS'], bytes) else ''

                    # ST_GD_01: Check if ground data exists for this structure
                    has_ground_data = False
                    struct_ground_pts = []

                    if struct_ground_data is not None and struct_ground_info is not None and i < len(struct_ground_info):
                        try:
                            info = struct_ground_info[i]
                            # Info typically contains (start_index, count) or similar
                            if hasattr(info, '__len__') and len(info) >= 2:
                                start_idx = int(info[0])
                                count = int(info[1])
                                if count > 0:
                                    has_ground_data = True
                                    for j in range(count):
                                        if start_idx + j < len(struct_ground_data):
                                            pt = struct_ground_data[start_idx + j]
                                            sta = float(pt[0]) if len(pt) > 0 else 0
                                            elev = float(pt[1]) if len(pt) > 1 else 0
                                            struct_ground_pts.append((sta, elev))
                        except (IndexError, TypeError, ValueError):
                            pass

                    if not has_ground_data and 'Bridge' in struct_type:
                        # Only warn for bridges - culverts may not have explicit ground data
                        msg = CheckMessage(
                            message_id="ST_GD_01",
                            severity=Severity.WARNING,
                            check_type="STRUCT",
                            river=river,
                            reach=reach,
                            station=station,
                            structure=name,
                            message=format_message("ST_GD_01", name=name),
                            help_text=get_help_text("ST_GD_01")
                        )
                        messages.append(msg)
                        continue  # Skip other ground checks if no ground data

                    if not struct_ground_pts:
                        continue

                    # Get structure geometry for comparison
                    # For bridges: get invert (low chord) and deck (high chord) elevations
                    invert_elev = None
                    deck_elev = None
                    left_abut_sta = None
                    right_abut_sta = None

                    if 'Bridge' in struct_type:
                        # Get deck/roadway data
                        if deck_data is not None and deck_info is not None and i < len(deck_info):
                            try:
                                d_info = deck_info[i]
                                deck_elevs = []
                                if hasattr(d_info, '__len__'):
                                    # Try to extract deck elevations
                                    if 'Deck High Chord (Index)' in d_info.dtype.names:
                                        hc_idx = int(d_info['Deck High Chord (Index)'])
                                        hc_cnt = int(d_info['Deck High Chord (Count)']) if 'Deck High Chord (Count)' in d_info.dtype.names else 0
                                        for j in range(hc_cnt):
                                            if hc_idx + j < len(deck_data):
                                                deck_elevs.append(float(deck_data[hc_idx + j][1]))
                                if deck_elevs:
                                    deck_elev = max(deck_elevs)
                            except (IndexError, TypeError, ValueError, KeyError):
                                pass

                        # Get low chord / invert elevation
                        if 'BR US Low Chord' in attr_names:
                            try:
                                invert_elev = float(attr['BR US Low Chord'])
                            except (TypeError, ValueError):
                                pass

                        # Get abutment stations
                        if 'BR US Left Bank' in attr_names:
                            try:
                                left_abut_sta = float(attr['BR US Left Bank'])
                            except (TypeError, ValueError):
                                pass
                        if 'BR US Right Bank' in attr_names:
                            try:
                                right_abut_sta = float(attr['BR US Right Bank'])
                            except (TypeError, ValueError):
                                pass

                    elif 'Culvert' in struct_type:
                        # For culverts, get invert from structure attributes
                        if 'US Invert' in attr_names:
                            try:
                                invert_elev = float(attr['US Invert'])
                            except (TypeError, ValueError):
                                pass

                    # Get ground elevations at key locations
                    left_ground_elev = struct_ground_pts[0][1] if struct_ground_pts else None
                    right_ground_elev = struct_ground_pts[-1][1] if struct_ground_pts else None

                    # Calculate min/max ground elevations in the channel area
                    channel_ground_min = None
                    channel_ground_max = None
                    if struct_ground_pts and left_abut_sta is not None and right_abut_sta is not None:
                        channel_pts = [(s, e) for s, e in struct_ground_pts if left_abut_sta <= s <= right_abut_sta]
                        if channel_pts:
                            channel_ground_min = min(e for _, e in channel_pts)
                            channel_ground_max = max(e for _, e in channel_pts)

                    # ST_GD_02: Ground elevation discontinuity
                    # Check for large elevation difference between US and DS ground
                    us_ground_elev = None
                    ds_ground_elev = None
                    if xs_attrs is not None and xs_sta_elev_values is not None and xs_sta_elev_info is not None:
                        # Find approach section elevations
                        for j, xs in enumerate(xs_attrs):
                            xs_rs = xs['RS'].decode('utf-8').strip() if isinstance(xs['RS'], bytes) else str(xs['RS']).strip()
                            if xs_rs == us_rs or xs_rs == ds_rs:
                                try:
                                    info = xs_sta_elev_info[j]
                                    start_idx = int(info[0])
                                    count = int(info[1])
                                    if count > 0:
                                        # Get min elevation (channel thalweg)
                                        elevs = []
                                        for k in range(count):
                                            if start_idx + k < len(xs_sta_elev_values):
                                                elevs.append(float(xs_sta_elev_values[start_idx + k][1]))
                                        if elevs:
                                            if xs_rs == us_rs:
                                                us_ground_elev = min(elevs)
                                            else:
                                                ds_ground_elev = min(elevs)
                                except (IndexError, TypeError, ValueError):
                                    pass

                    if us_ground_elev is not None and ds_ground_elev is not None:
                        elev_diff = abs(us_ground_elev - ds_ground_elev)
                        if elev_diff > ground_discontinuity_threshold:
                            msg = CheckMessage(
                                message_id="ST_GD_02",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_02", diff=elev_diff, name=name),
                                help_text=get_help_text("ST_GD_02"),
                                value=elev_diff,
                                threshold=ground_discontinuity_threshold
                            )
                            messages.append(msg)

                    # ST_GD_02BU/BD: Bridge deck elevation check at upstream/downstream faces
                    # Compare deck elevations with approach XS ground at deck station locations
                    if 'Bridge' in struct_type and deck_data is not None and deck_info is not None and i < len(deck_info):
                        try:
                            d_info = deck_info[i]

                            # Get deck high chord (top of deck) station-elevation pairs
                            us_deck_sta_elev = []
                            ds_deck_sta_elev = []

                            if hasattr(d_info, 'dtype') and d_info.dtype.names is not None:
                                # Extract upstream deck profile (US high chord)
                                if 'Deck US High Chord (Index)' in d_info.dtype.names:
                                    us_hc_idx = int(d_info['Deck US High Chord (Index)'])
                                    us_hc_cnt = int(d_info['Deck US High Chord (Count)']) if 'Deck US High Chord (Count)' in d_info.dtype.names else 0
                                    for dk in range(us_hc_cnt):
                                        if us_hc_idx + dk < len(deck_data):
                                            sta = float(deck_data[us_hc_idx + dk][0])
                                            elev = float(deck_data[us_hc_idx + dk][1])
                                            us_deck_sta_elev.append((sta, elev))
                                elif 'Deck High Chord (Index)' in d_info.dtype.names:
                                    # Fallback: use generic high chord for both US and DS
                                    hc_idx = int(d_info['Deck High Chord (Index)'])
                                    hc_cnt = int(d_info['Deck High Chord (Count)']) if 'Deck High Chord (Count)' in d_info.dtype.names else 0
                                    for dk in range(hc_cnt):
                                        if hc_idx + dk < len(deck_data):
                                            sta = float(deck_data[hc_idx + dk][0])
                                            elev = float(deck_data[hc_idx + dk][1])
                                            us_deck_sta_elev.append((sta, elev))
                                            ds_deck_sta_elev.append((sta, elev))

                                # Extract downstream deck profile (DS high chord)
                                if 'Deck DS High Chord (Index)' in d_info.dtype.names:
                                    ds_hc_idx = int(d_info['Deck DS High Chord (Index)'])
                                    ds_hc_cnt = int(d_info['Deck DS High Chord (Count)']) if 'Deck DS High Chord (Count)' in d_info.dtype.names else 0
                                    for dk in range(ds_hc_cnt):
                                        if ds_hc_idx + dk < len(deck_data):
                                            sta = float(deck_data[ds_hc_idx + dk][0])
                                            elev = float(deck_data[ds_hc_idx + dk][1])
                                            ds_deck_sta_elev.append((sta, elev))

                            # Get upstream approach XS station-elevation data
                            us_xs_sta_elev = []
                            ds_xs_sta_elev = []
                            if xs_attrs is not None and xs_sta_elev_values is not None and xs_sta_elev_info is not None:
                                for j, xs in enumerate(xs_attrs):
                                    xs_rs = xs['RS'].decode('utf-8').strip() if isinstance(xs['RS'], bytes) else str(xs['RS']).strip()
                                    if xs_rs == us_rs or xs_rs == ds_rs:
                                        try:
                                            info = xs_sta_elev_info[j]
                                            start_idx = int(info[0])
                                            count = int(info[1])
                                            if count > 0:
                                                xs_pts = []
                                                for k in range(count):
                                                    if start_idx + k < len(xs_sta_elev_values):
                                                        sta = float(xs_sta_elev_values[start_idx + k][0])
                                                        elev = float(xs_sta_elev_values[start_idx + k][1])
                                                        xs_pts.append((sta, elev))
                                                if xs_rs == us_rs:
                                                    us_xs_sta_elev = xs_pts
                                                else:
                                                    ds_xs_sta_elev = xs_pts
                                        except (IndexError, TypeError, ValueError):
                                            pass

                            # Helper function to interpolate ground elevation at a station
                            def interpolate_ground_at_station(sta_elev_list, target_sta):
                                """Interpolate ground elevation at target station from XS data."""
                                if not sta_elev_list or len(sta_elev_list) < 2:
                                    return None
                                # Find bracketing points
                                for k in range(len(sta_elev_list) - 1):
                                    sta1, elev1 = sta_elev_list[k]
                                    sta2, elev2 = sta_elev_list[k + 1]
                                    if sta1 <= target_sta <= sta2:
                                        if (sta2 - sta1) > 0:
                                            t = (target_sta - sta1) / (sta2 - sta1)
                                            return elev1 + t * (elev2 - elev1)
                                        return elev1
                                # Check if target is outside range (extrapolate to nearest)
                                if target_sta < sta_elev_list[0][0]:
                                    return sta_elev_list[0][1]
                                if target_sta > sta_elev_list[-1][0]:
                                    return sta_elev_list[-1][1]
                                return None

                            # ST_GD_02BU: Check upstream deck vs Section 1 (US XS) ground
                            if us_deck_sta_elev and us_xs_sta_elev:
                                # Check deck elevation at abutment stations
                                for deck_sta, deck_el in us_deck_sta_elev:
                                    ground_el = interpolate_ground_at_station(us_xs_sta_elev, deck_sta)
                                    if ground_el is not None:
                                        # Deck should be above or at ground level
                                        diff = abs(deck_el - ground_el)
                                        if diff > ground_elev_tolerance and deck_el < ground_el:
                                            msg = CheckMessage(
                                                message_id="ST_GD_02BU",
                                                severity=Severity.WARNING,
                                                check_type="STRUCT",
                                                river=river,
                                                reach=reach,
                                                station=station,
                                                structure=name,
                                                message=format_message("ST_GD_02BU", deck_elev=deck_el, ground_elev=ground_el, name=name),
                                                help_text=get_help_text("ST_GD_02BU"),
                                                value=diff,
                                                threshold=ground_elev_tolerance
                                            )
                                            messages.append(msg)
                                            break  # Only report once per structure

                            # ST_GD_02BD: Check downstream deck vs Section 4 (DS XS) ground
                            if ds_deck_sta_elev and ds_xs_sta_elev:
                                for deck_sta, deck_el in ds_deck_sta_elev:
                                    ground_el = interpolate_ground_at_station(ds_xs_sta_elev, deck_sta)
                                    if ground_el is not None:
                                        diff = abs(deck_el - ground_el)
                                        if diff > ground_elev_tolerance and deck_el < ground_el:
                                            msg = CheckMessage(
                                                message_id="ST_GD_02BD",
                                                severity=Severity.WARNING,
                                                check_type="STRUCT",
                                                river=river,
                                                reach=reach,
                                                station=station,
                                                structure=name,
                                                message=format_message("ST_GD_02BD", deck_elev=deck_el, ground_elev=ground_el, name=name),
                                                help_text=get_help_text("ST_GD_02BD"),
                                                value=diff,
                                                threshold=ground_elev_tolerance
                                            )
                                            messages.append(msg)
                                            break  # Only report once per structure

                        except Exception as e:
                            logger.debug(f"Could not check deck elevation at bridge {name}: {e}")

                    # ST_GD_03L/R: Ground below structure invert
                    if invert_elev is not None:
                        if left_ground_elev is not None and left_ground_elev < invert_elev - ground_elev_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GD_03L",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_03L", ground_elev=left_ground_elev, invert_elev=invert_elev, name=name),
                                help_text=get_help_text("ST_GD_03L"),
                                value=left_ground_elev
                            )
                            messages.append(msg)

                        if right_ground_elev is not None and right_ground_elev < invert_elev - ground_elev_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GD_03R",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_03R", ground_elev=right_ground_elev, invert_elev=invert_elev, name=name),
                                help_text=get_help_text("ST_GD_03R"),
                                value=right_ground_elev
                            )
                            messages.append(msg)

                    # ST_GD_04L/R: Ground above structure deck (unusual but may be intentional)
                    if deck_elev is not None:
                        if left_ground_elev is not None and left_ground_elev > deck_elev + ground_elev_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GD_04L",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_04L", ground_elev=left_ground_elev, deck_elev=deck_elev, name=name),
                                help_text=get_help_text("ST_GD_04L"),
                                value=left_ground_elev
                            )
                            messages.append(msg)

                        if right_ground_elev is not None and right_ground_elev > deck_elev + ground_elev_tolerance:
                            msg = CheckMessage(
                                message_id="ST_GD_04R",
                                severity=Severity.INFO,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_04R", ground_elev=right_ground_elev, deck_elev=deck_elev, name=name),
                                help_text=get_help_text("ST_GD_04R"),
                                value=right_ground_elev
                            )
                            messages.append(msg)

                    # ST_GD_05: Ground slope at structure
                    if len(struct_ground_pts) >= 2:
                        for k in range(len(struct_ground_pts) - 1):
                            sta1, elev1 = struct_ground_pts[k]
                            sta2, elev2 = struct_ground_pts[k + 1]
                            if abs(sta2 - sta1) > 0.1:  # Avoid division by very small values
                                slope = abs(elev2 - elev1) / abs(sta2 - sta1)
                                if slope > ground_slope_threshold:
                                    msg = CheckMessage(
                                        message_id="ST_GD_05",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        structure=name,
                                        message=format_message("ST_GD_05", slope=slope, name=name),
                                        help_text=get_help_text("ST_GD_05"),
                                        value=slope,
                                        threshold=ground_slope_threshold
                                    )
                                    messages.append(msg)
                                    break  # Only report once per structure

                    # ST_GD_06: Ground data inconsistent between approach sections
                    if us_ground_elev is not None and ds_ground_elev is not None:
                        # Also check against structure ground
                        if channel_ground_min is not None:
                            if abs(us_ground_elev - channel_ground_min) > ground_discontinuity_threshold:
                                msg = CheckMessage(
                                    message_id="ST_GD_06",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    structure=name,
                                    message=format_message("ST_GD_06", name=name, us_elev=us_ground_elev, ds_elev=ds_ground_elev),
                                    help_text=get_help_text("ST_GD_06")
                                )
                                messages.append(msg)

                    # ST_GD_07: Approach section ground doesn't match structure ground
                    if us_ground_elev is not None and channel_ground_min is not None:
                        diff = abs(us_ground_elev - channel_ground_min)
                        if diff > ground_discontinuity_threshold:
                            msg = CheckMessage(
                                message_id="ST_GD_07",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_07", xs_elev=us_ground_elev, struct_elev=channel_ground_min, name=name),
                                help_text=get_help_text("ST_GD_07"),
                                value=diff
                            )
                            messages.append(msg)

                    # ST_GD_08: Pier ground elevation issues
                    if pier_data is not None and pier_info is not None and i < len(pier_info) and 'Bridge' in struct_type:
                        try:
                            p_info = pier_info[i]
                            if hasattr(p_info, '__len__') and len(p_info) >= 2:
                                p_start = int(p_info[0])
                                p_count = int(p_info[1])
                                for pj in range(p_count):
                                    if p_start + pj < len(pier_data):
                                        pier_pt = pier_data[p_start + pj]
                                        pier_sta = float(pier_pt[0]) if len(pier_pt) > 0 else 0
                                        pier_elev = float(pier_pt[1]) if len(pier_pt) > 1 else 0
                                        # Check if pier is above channel ground
                                        if channel_ground_min is not None and pier_elev > channel_ground_min + ground_elev_tolerance:
                                            msg = CheckMessage(
                                                message_id="ST_GD_08",
                                                severity=Severity.WARNING,
                                                check_type="STRUCT",
                                                river=river,
                                                reach=reach,
                                                station=station,
                                                structure=name,
                                                message=format_message("ST_GD_08", pier_elev=pier_elev, name=name, issue=f"above channel ground ({channel_ground_min:.2f} ft)"),
                                                help_text=get_help_text("ST_GD_08"),
                                                value=pier_elev
                                            )
                                            messages.append(msg)
                                            break  # Only report once per structure
                        except (IndexError, TypeError, ValueError):
                            pass

                    # ST_GD_09: Abutment ground elevation issues
                    if left_abut_sta is not None and struct_ground_pts:
                        # Find ground elevation at left abutment
                        left_abut_ground = None
                        for k in range(len(struct_ground_pts) - 1):
                            sta1, elev1 = struct_ground_pts[k]
                            sta2, elev2 = struct_ground_pts[k + 1]
                            if sta1 <= left_abut_sta <= sta2:
                                # Linear interpolation
                                t = (left_abut_sta - sta1) / (sta2 - sta1) if (sta2 - sta1) != 0 else 0
                                left_abut_ground = elev1 + t * (elev2 - elev1)
                                break

                        if left_abut_ground is not None:
                            # Abutment ground should be at or above channel ground
                            if channel_ground_min is not None and left_abut_ground < channel_ground_min - ground_elev_tolerance:
                                msg = CheckMessage(
                                    message_id="ST_GD_09",
                                    severity=Severity.WARNING,
                                    check_type="STRUCT",
                                    river=river,
                                    reach=reach,
                                    station=station,
                                    structure=name,
                                    message=format_message("ST_GD_09", abut_elev=left_abut_ground, name=name, issue="left abutment below channel ground"),
                                    help_text=get_help_text("ST_GD_09"),
                                    value=left_abut_ground
                                )
                                messages.append(msg)

                    # ST_GD_10: Embankment slope too steep
                    # Check slope from channel edge to overbank ground
                    if left_abut_sta is not None and struct_ground_pts and len(struct_ground_pts) >= 2:
                        # Find ground at left edge and at abutment
                        left_edge = struct_ground_pts[0]
                        left_abut_ground = None
                        for k in range(len(struct_ground_pts) - 1):
                            sta1, elev1 = struct_ground_pts[k]
                            sta2, elev2 = struct_ground_pts[k + 1]
                            if sta1 <= left_abut_sta <= sta2:
                                t = (left_abut_sta - sta1) / (sta2 - sta1) if (sta2 - sta1) != 0 else 0
                                left_abut_ground = elev1 + t * (elev2 - elev1)
                                break

                        if left_abut_ground is not None and left_edge[0] < left_abut_sta:
                            horiz_dist = left_abut_sta - left_edge[0]
                            vert_dist = abs(left_abut_ground - left_edge[1])
                            if vert_dist > 0.1:  # Significant height difference
                                slope_hv = horiz_dist / vert_dist if vert_dist > 0 else float('inf')
                                if slope_hv < embankment_slope_threshold:
                                    msg = CheckMessage(
                                        message_id="ST_GD_10",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        structure=name,
                                        message=format_message("ST_GD_10", slope=slope_hv, name=name, side="left"),
                                        help_text=get_help_text("ST_GD_10"),
                                        value=slope_hv,
                                        threshold=embankment_slope_threshold
                                    )
                                    messages.append(msg)

                    # Similar check for right side
                    if right_abut_sta is not None and struct_ground_pts and len(struct_ground_pts) >= 2:
                        right_edge = struct_ground_pts[-1]
                        right_abut_ground = None
                        for k in range(len(struct_ground_pts) - 1):
                            sta1, elev1 = struct_ground_pts[k]
                            sta2, elev2 = struct_ground_pts[k + 1]
                            if sta1 <= right_abut_sta <= sta2:
                                t = (right_abut_sta - sta1) / (sta2 - sta1) if (sta2 - sta1) != 0 else 0
                                right_abut_ground = elev1 + t * (elev2 - elev1)
                                break

                        if right_abut_ground is not None and right_edge[0] > right_abut_sta:
                            horiz_dist = right_edge[0] - right_abut_sta
                            vert_dist = abs(right_edge[1] - right_abut_ground)
                            if vert_dist > 0.1:
                                slope_hv = horiz_dist / vert_dist if vert_dist > 0 else float('inf')
                                if slope_hv < embankment_slope_threshold:
                                    msg = CheckMessage(
                                        message_id="ST_GD_10",
                                        severity=Severity.WARNING,
                                        check_type="STRUCT",
                                        river=river,
                                        reach=reach,
                                        station=station,
                                        structure=name,
                                        message=format_message("ST_GD_10", slope=slope_hv, name=name, side="right"),
                                        help_text=get_help_text("ST_GD_10"),
                                        value=slope_hv,
                                        threshold=embankment_slope_threshold
                                    )
                                    messages.append(msg)

                    # ST_GD_11: Fill depth exceeds reasonable limit
                    if deck_elev is not None and channel_ground_min is not None:
                        fill_depth = deck_elev - channel_ground_min
                        if fill_depth > fill_depth_threshold:
                            msg = CheckMessage(
                                message_id="ST_GD_11",
                                severity=Severity.WARNING,
                                check_type="STRUCT",
                                river=river,
                                reach=reach,
                                station=station,
                                structure=name,
                                message=format_message("ST_GD_11", fill_depth=fill_depth, name=name),
                                help_text=get_help_text("ST_GD_11"),
                                value=fill_depth,
                                threshold=fill_depth_threshold
                            )
                            messages.append(msg)

        except Exception as e:
            logger.warning(f"Could not check structure ground data: {e}")

        return messages
