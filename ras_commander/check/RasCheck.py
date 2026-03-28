"""
RasCheck - Quality Assurance Validation for HEC-RAS Models.

NOTE: This is an UNOFFICIAL Python implementation inspired by the FEMA cHECk-RAS tool.
It is part of the ras-commander library and is NOT affiliated with or endorsed by FEMA.
The original cHECk-RAS is a Windows application developed for FEMA's National Flood
Insurance Program. This implementation provides similar functionality using modern
HDF-based data access for HEC-RAS 6.x models.

This module is a thin facade that delegates to domain-specific check modules:
- check_unsteady.py (CheckUnsteady): Mass balance, computation, peaks, stability, mesh
- check_nt.py (CheckNt): Manning's n, HTAB parameters
- check_xs.py (CheckXs): Cross section validation
- check_structures.py (CheckStructures): Bridge, culvert, inline weir validation
- check_floodways.py (CheckFloodways): Floodway encroachment validation
- check_profiles.py (CheckProfiles): Multiple profile consistency

Supported Checks:

Steady Flow:
- NT Check: Manning's n values and transition loss coefficients
- XS Check: Cross section spacing, ineffective flow, reach lengths
- Structure Check: Bridge, culvert, and inline weir validation
- Floodway Check: Surcharge validation and discharge matching
- Profiles Check: Multiple profile comparison and consistency

Unsteady Flow:
- NT Check: Manning's n values (geometry-only, shared with steady)
- Mass Balance Check: Volume conservation validation
- Computation Check: HEC-RAS warnings and performance analysis
- Peaks Check: Maximum WSE and velocity validation
- Stability Check: Iteration counts and convergence metrics
- 2D Mesh Check: Cell quality and face velocity validation (when 2D present)

Example:
    >>> from ras_commander.check import RasCheck
    >>> # Auto-detects steady vs unsteady flow
    >>> results = RasCheck.run_all("01")
    >>> print(f"Flow type: {results.flow_type}")
    >>> print(f"Found {results.get_error_count()} errors")
    >>> results.to_html("check_report.html")
"""

from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
import pandas as pd

from ..Decorators import standardize_input, log_call
from ..LoggingConfig import get_logger
from ..RasPrj import ras
from .thresholds import ValidationThresholds, get_default_thresholds
from .messages import get_message_template, get_help_text, format_message
from .types import Severity, FlowType, CheckMessage, CheckResults
from . import _utils
from .check_unsteady import CheckUnsteady
from .check_nt import CheckNt
from .check_xs import CheckXs
from .check_structures import CheckStructures
from .check_floodways import CheckFloodways
from .check_profiles import CheckProfiles

logger = get_logger(__name__)


class RasCheck:
    """
    Quality assurance validation for HEC-RAS 6.x models.

    Supports both steady flow and unsteady flow plans. Flow type is
    auto-detected from the plan HDF file.

    All methods are static and follow ras-commander conventions.
    Use @standardize_input decorator for flexible path handling.

    This class is a facade that delegates to domain-specific check classes:
    - CheckUnsteady: Mass balance, computation, peaks, stability, mesh quality
    - CheckNt: Manning's n values, HTAB parameters
    - CheckXs: Cross section validation
    - CheckStructures: Bridge, culvert, inline weir validation
    - CheckFloodways: Floodway encroachment validation
    - CheckProfiles: Multiple profile consistency
    """

    @staticmethod
    @log_call
    def run_all(
        plan: Union[str, Path],
        profiles: Optional[List[str]] = None,
        floodway_profile: Optional[str] = None,
        surcharge: float = 1.0,
        thresholds: Optional[ValidationThresholds] = None,
        ras_object=None
    ) -> CheckResults:
        """
        Run all validation checks on a HEC-RAS plan.

        Auto-detects steady vs unsteady flow and runs appropriate checks.

        Args:
            plan: Plan number (e.g., "01") or path to plan HDF file
            profiles: List of profile names to check (steady flow only, ignored for unsteady)
            floodway_profile: Name of floodway profile (steady flow only)
            surcharge: Maximum allowable surcharge in feet (steady flow only, default 1.0)
            thresholds: Custom ValidationThresholds (uses defaults if None)
            ras_object: Optional RasPrj instance (uses global ras if None)

        Returns:
            CheckResults object containing all validation messages and summaries.
            The flow_type attribute indicates whether steady or unsteady checks were run.

        Example (steady flow):
            >>> results = RasCheck.run_all("01",
            ...     profiles=['10yr', '50yr', '100yr', 'Floodway'],
            ...     floodway_profile='Floodway',
            ...     surcharge=1.0)
            >>> print(f"Flow type: {results.flow_type}")
            >>> print(f"Found {results.get_error_count()} errors")

        Example (unsteady flow):
            >>> results = RasCheck.run_all("01")  # Auto-detects unsteady
            >>> print(f"Flow type: {results.flow_type}")  # FlowType.UNSTEADY

        Notes:
            - For steady plans: Runs NT, XS, Structure, Floodway, Profiles checks
            - For unsteady plans: Runs NT, Mass Balance, Computation, Peaks, and Stability checks
            - Geometry-only checks (NT) work for both flow types
            - Floodway analysis is not applicable to unsteady flow
        """
        results = CheckResults()
        ras_obj = ras_object or ras

        if thresholds is None:
            thresholds = get_default_thresholds()

        # Resolve HDF paths
        plan_hdf, geom_hdf = _utils.resolve_hdf_paths(plan, ras_obj)

        # Detect flow type
        flow_type = _utils.detect_flow_type(plan_hdf)
        results.flow_type = flow_type

        logger.info(f"Detected flow type: {flow_type.value}")

        # Dispatch based on flow type
        if flow_type == FlowType.STEADY:
            return RasCheck._run_steady_checks(
                plan_hdf, geom_hdf, profiles, floodway_profile, surcharge, thresholds, results
            )
        elif flow_type == FlowType.UNSTEADY:
            return RasCheck._run_unsteady_checks(
                plan_hdf, geom_hdf, thresholds, results
            )
        else:
            # Geometry only - run NT check only
            logger.info("No results found in plan HDF, running geometry-only checks")
            nt_results = CheckNt.check_nt(geom_hdf, thresholds)
            results.messages.extend(nt_results.messages)
            results.nt_summary = nt_results.nt_summary
            results.statistics = _utils.calculate_statistics(results)
            return results

    @staticmethod
    def _run_steady_checks(
        plan_hdf: Path,
        geom_hdf: Path,
        profiles: Optional[List[str]],
        floodway_profile: Optional[str],
        surcharge: float,
        thresholds: ValidationThresholds,
        results: CheckResults
    ) -> CheckResults:
        """Run all steady flow checks."""
        # Get profile information
        available_profiles = _utils.get_available_profiles(plan_hdf)
        if profiles is None:
            profiles = available_profiles

        # Run individual checks (delegated to domain modules)
        nt_results = CheckNt.check_nt(geom_hdf, thresholds)
        results.messages.extend(nt_results.messages)
        results.nt_summary = nt_results.nt_summary

        xs_results = CheckXs.check_xs(plan_hdf, geom_hdf, profiles, thresholds)
        results.messages.extend(xs_results.messages)
        results.xs_summary = xs_results.xs_summary

        struct_results = CheckStructures.check_structures(plan_hdf, geom_hdf, profiles, thresholds)
        results.messages.extend(struct_results.messages)
        results.struct_summary = struct_results.struct_summary

        if floodway_profile and floodway_profile in profiles:
            base_profile = profiles[0] if profiles[0] != floodway_profile else profiles[1]
            fw_results = CheckFloodways.check_floodways(
                plan_hdf, geom_hdf, base_profile, floodway_profile, surcharge, thresholds
            )
            results.messages.extend(fw_results.messages)
            results.floodway_summary = fw_results.floodway_summary

        if len(profiles) >= 2:
            # Exclude floodway from profiles check
            check_profiles = [p for p in profiles if p != floodway_profile]
            if len(check_profiles) >= 2:
                prof_results = CheckProfiles.check_profiles(plan_hdf, check_profiles, thresholds)
                results.messages.extend(prof_results.messages)
                results.profiles_summary = prof_results.profiles_summary

        # HTAB parameter checks (geometry-only, uses plain text .g## file)
        geom_file = geom_hdf.parent / geom_hdf.stem  # model.g01.hdf -> model.g01
        if geom_file.exists():
            htab_results = CheckNt.check_htab_params(geom_file, thresholds)
            results.messages.extend(htab_results.messages)

            struct_htab_results = CheckNt.check_structure_htab_params(geom_file, thresholds)
            results.messages.extend(struct_htab_results.messages)

            subgrid_results = CheckNt.check_subgrid_sampling(geom_file, thresholds)
            results.messages.extend(subgrid_results.messages)

        # Calculate statistics
        results.statistics = _utils.calculate_statistics(results)

        return results

    @staticmethod
    def _run_unsteady_checks(
        plan_hdf: Path,
        geom_hdf: Path,
        thresholds: ValidationThresholds,
        results: CheckResults
    ) -> CheckResults:
        """
        Run all unsteady flow checks.

        Unsteady checks include:
        - NT Check: Manning's n values (geometry-only, shared with steady)
        - Mass Balance Check: Volume conservation validation
        - Computation Check: HEC-RAS warnings and performance
        - Peaks Check: Maximum WSE and velocity validation
        - Stability Check: Iteration counts and convergence (when 2D present)
        - 2D Mesh Check: Cell quality and face velocity (when 2D present)

        Note:
            Floodway and Profiles checks are NOT applicable to unsteady flow.
        """
        logger.info("Running unsteady flow validation checks")

        # Geometry checks (shared with steady)
        nt_results = CheckNt.check_nt(geom_hdf, thresholds)
        results.messages.extend(nt_results.messages)
        results.nt_summary = nt_results.nt_summary

        # Unsteady-specific checks
        mass_balance_results = CheckUnsteady.check_mass_balance(plan_hdf, thresholds)
        results.messages.extend(mass_balance_results.messages)
        results.mass_balance_summary = mass_balance_results.mass_balance_summary

        computation_results = CheckUnsteady.check_computation(plan_hdf, thresholds)
        results.messages.extend(computation_results.messages)

        # Peaks validation
        peaks_results = CheckUnsteady.check_peaks(plan_hdf, geom_hdf, thresholds)
        results.messages.extend(peaks_results.messages)
        results.peaks_summary = peaks_results.peaks_summary

        # Stability and 2D mesh checks (when 2D present)
        if _utils.has_2d_mesh(plan_hdf):
            stability_results = CheckUnsteady.check_stability(plan_hdf, thresholds)
            results.messages.extend(stability_results.messages)
            results.stability_summary = stability_results.stability_summary

            mesh_results = CheckUnsteady.check_mesh_quality(plan_hdf, geom_hdf, thresholds)
            results.messages.extend(mesh_results.messages)
            results.mesh_summary = mesh_results.mesh_summary
        else:
            msg = CheckMessage(
                message_id="US_INFO_01",
                severity=Severity.INFO,
                check_type="UNSTEADY",
                message="No 2D flow areas found - 2D stability and mesh quality checks skipped"
            )
            results.messages.append(msg)

        # Add info message about floodway not applicable
        msg = CheckMessage(
            message_id="US_INFO_02",
            severity=Severity.INFO,
            check_type="UNSTEADY",
            message="Floodway analysis is not applicable to unsteady flow simulations"
        )
        results.messages.append(msg)

        # HTAB parameter checks (geometry-only, uses plain text .g## file)
        geom_file = geom_hdf.parent / geom_hdf.stem  # model.g01.hdf -> model.g01
        if geom_file.exists():
            htab_results = CheckNt.check_htab_params(geom_file, thresholds)
            results.messages.extend(htab_results.messages)

            struct_htab_results = CheckNt.check_structure_htab_params(geom_file, thresholds)
            results.messages.extend(struct_htab_results.messages)

            subgrid_results = CheckNt.check_subgrid_sampling(geom_file, thresholds)
            results.messages.extend(subgrid_results.messages)

        # Calculate statistics
        results.statistics = _utils.calculate_statistics(results)

        return results

    # =========================================================================
    # Facade delegates - preserve backward-compatible public API
    # =========================================================================

    @staticmethod
    def check_nt(geom_hdf, thresholds=None):
        """Delegate to CheckNt.check_nt."""
        return CheckNt.check_nt(geom_hdf, thresholds)

    @staticmethod
    def check_htab_params(geom_file, thresholds=None):
        """Delegate to CheckNt.check_htab_params."""
        return CheckNt.check_htab_params(geom_file, thresholds)

    @staticmethod
    def check_structure_htab_params(geom_file, thresholds=None):
        """Delegate to CheckNt.check_structure_htab_params."""
        return CheckNt.check_structure_htab_params(geom_file, thresholds)

    @staticmethod
    def check_xs(plan_hdf, geom_hdf, profiles, thresholds=None):
        """Delegate to CheckXs.check_xs."""
        return CheckXs.check_xs(plan_hdf, geom_hdf, profiles, thresholds)

    @staticmethod
    def check_structures(plan_hdf, geom_hdf, profiles, thresholds=None):
        """Delegate to CheckStructures.check_structures."""
        return CheckStructures.check_structures(plan_hdf, geom_hdf, profiles, thresholds)

    @staticmethod
    def check_floodways(plan_hdf, geom_hdf, base_profile, floodway_profile, surcharge=1.0, thresholds=None):
        """Delegate to CheckFloodways.check_floodways."""
        return CheckFloodways.check_floodways(plan_hdf, geom_hdf, base_profile, floodway_profile, surcharge, thresholds)

    @staticmethod
    def check_profiles(plan_hdf, profiles, thresholds=None):
        """Delegate to CheckProfiles.check_profiles."""
        return CheckProfiles.check_profiles(plan_hdf, profiles, thresholds)

    @staticmethod
    def check_unsteady_mass_balance(plan_hdf, thresholds=None):
        """Delegate to CheckUnsteady.check_mass_balance."""
        return CheckUnsteady.check_mass_balance(plan_hdf, thresholds)

    @staticmethod
    def check_unsteady_computation(plan_hdf, thresholds=None):
        """Delegate to CheckUnsteady.check_computation."""
        return CheckUnsteady.check_computation(plan_hdf, thresholds)

    @staticmethod
    def check_unsteady_peaks(plan_hdf, geom_hdf, thresholds=None):
        """Delegate to CheckUnsteady.check_peaks."""
        return CheckUnsteady.check_peaks(plan_hdf, geom_hdf, thresholds)

    @staticmethod
    def check_unsteady_stability(plan_hdf, thresholds=None):
        """Delegate to CheckUnsteady.check_stability."""
        return CheckUnsteady.check_stability(plan_hdf, thresholds)

    @staticmethod
    def check_mesh_quality(plan_hdf, geom_hdf, thresholds=None):
        """Delegate to CheckUnsteady.check_mesh_quality."""
        return CheckUnsteady.check_mesh_quality(plan_hdf, geom_hdf, thresholds)

    @staticmethod
    def check_subgrid_sampling(geom_file, thresholds=None):
        """Delegate to CheckNt.check_subgrid_sampling."""
        return CheckNt.check_subgrid_sampling(geom_file, thresholds)
