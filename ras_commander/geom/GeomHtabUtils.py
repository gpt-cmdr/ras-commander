"""
GeomHtabUtils - Utility functions for HTAB parameter calculations

This module provides utility functions for calculating optimal HTAB (Hydraulic Table)
parameters for HEC-RAS geometry files. These functions support both cross section
property tables and structure (bridge, culvert, inline weir) property tables.

HTAB parameters control how HEC-RAS pre-computes hydraulic property tables:
- Cross sections: Starting elevation, increment, and number of points
- Structures: Maximum headwater, tailwater, flow, and curve point counts

All methods are static and designed to be used without instantiation.

List of Functions:
- calculate_optimal_xs_htab() - Calculate optimal XS HTAB parameters from invert and max WSE
- calculate_optimal_structure_htab() - Calculate optimal structure HTAB parameters
- validate_xs_htab_params() - Validate XS HTAB parameters against limits
- validate_structure_htab_params() - Validate structure HTAB parameters

Example Usage:
    >>> from ras_commander.geom import GeomHtabUtils
    >>>
    >>> # Calculate optimal XS HTAB
    >>> params = GeomHtabUtils.calculate_optimal_xs_htab(
    ...     invert=580.0, max_wse=605.0, safety_factor=1.3
    ... )
    >>> print(f"Starting El: {params['starting_el']}")
    >>> print(f"Increment: {params['increment']}")
    >>> print(f"Num Points: {params['num_points']}")
    >>>
    >>> # Calculate optimal structure HTAB
    >>> struct_params = GeomHtabUtils.calculate_optimal_structure_htab(
    ...     struct_invert=590.0, max_hw=605.0, max_tw=600.0, max_flow=25000.0
    ... )
    >>> print(f"HW Max: {struct_params['hw_max']}")
    >>> print(f"Max Flow: {struct_params['max_flow']}")

Technical Notes:
    - Safety factors prevent extrapolation errors during simulation
    - XS HTAB: 30% safety factor (1.3x) on depth is recommended
    - Structure HTAB: 100% safety factor (2.0x) on HW/TW/flow is recommended
    - Maximum 500 points for XS (HEC-RAS limit)
    - Increment is adjusted if 500 points insufficient for range

References:
    - HEC-RAS User's Manual: Geometric Preprocessor
    - HEC-RAS User's Manual: HTAB Internal Boundaries Table
    - Paige Brue, Kleinschmidt: HTAB optimization best practices
"""

from typing import Dict, List, Tuple, Optional, Union
import math

from ..LoggingConfig import get_logger
from ..Decorators import log_call

logger = get_logger(__name__)


class GeomHtabUtils:
    """
    Utility functions for HTAB parameter calculations.

    All methods are static and designed to be used without instantiation.

    These functions calculate optimal HTAB parameters based on observed
    maximum water surface elevations and flows, applying appropriate
    safety factors to prevent extrapolation during simulation.
    """

    # HEC-RAS HTAB limits
    MIN_XS_POINTS = 20          # Minimum number of XS HTAB points
    MAX_XS_POINTS = 500         # Maximum number of XS HTAB points (HEC-RAS limit)
    DEFAULT_XS_INCREMENT = 0.1  # Default elevation increment (ft)
    MIN_XS_INCREMENT = 0.01     # Minimum reasonable increment
    MAX_XS_INCREMENT = 2.0      # Maximum reasonable increment

    # Structure HTAB defaults
    DEFAULT_FREE_FLOW_POINTS = 20     # Default free flow curve points
    DEFAULT_SUBMERGED_CURVES = 30     # Default number of submerged curves
    DEFAULT_POINTS_PER_CURVE = 20     # Default points per submerged curve
    MIN_FREE_FLOW_POINTS = 10         # Minimum free flow points
    MAX_FREE_FLOW_POINTS = 20         # Maximum free flow points
    MIN_SUBMERGED_CURVES = 10         # Minimum submerged curves
    MAX_SUBMERGED_CURVES = 30         # Maximum submerged curves

    # Safety factor defaults
    DEFAULT_XS_SAFETY_FACTOR = 1.3    # 30% safety on XS depth
    DEFAULT_HW_SAFETY_FACTOR = 2.0    # 100% safety on headwater
    DEFAULT_FLOW_SAFETY_FACTOR = 2.0  # 100% safety on flow
    DEFAULT_TW_SAFETY_FACTOR = 2.0    # 100% safety on tailwater

    @staticmethod
    @log_call
    def calculate_optimal_xs_htab(
        invert: float,
        max_wse: float,
        safety_factor: float = 1.3,
        target_increment: float = 0.1,
        max_points: int = 500
    ) -> Dict[str, Union[float, int]]:
        """
        Calculate optimal cross section HTAB parameters from invert and max WSE.

        This function computes the optimal starting elevation, increment, and
        number of points for a cross section's hydraulic table based on the
        observed maximum water surface elevation and a safety factor.

        Algorithm:
            1. Calculate max depth: max_wse - invert
            2. Apply safety factor: target_depth = max_depth * safety_factor
            3. Calculate target max elevation: invert + target_depth
            4. Set starting_el = invert (copy invert, don't use default offset)
            5. Check if target increment fits within max_points
            6. If not, increase increment to fit range in max_points
            7. Round increment to clean value (2 decimal places)

        Args:
            invert: Cross section invert elevation (minimum elevation in XS)
            max_wse: Maximum water surface elevation from simulation results
            safety_factor: Multiplier on max depth to provide buffer (default 1.3 = 30%)
                          Recommended: 1.2-1.5 for typical floods, 2.0 for dam break
            target_increment: Desired elevation increment in feet (default 0.1)
                             Smaller increments give more accurate interpolation
            max_points: Maximum number of points (HEC-RAS limit is 500)

        Returns:
            dict: Optimal HTAB parameters with keys:
                - 'starting_el' (float): Starting elevation (equals invert)
                - 'increment' (float): Elevation increment
                - 'num_points' (int): Number of points
                - 'actual_max_el' (float): Actual maximum elevation covered
                - 'target_max_el' (float): Target maximum elevation with safety
                - 'target_depth' (float): Target depth with safety factor applied
                - 'coverage_adequate' (bool): True if actual_max >= target_max

        Raises:
            ValueError: If invert >= max_wse (invalid inputs)
            ValueError: If safety_factor < 1.0
            ValueError: If max_points < MIN_XS_POINTS or > MAX_XS_POINTS

        Examples:
            >>> # Standard flood scenario
            >>> params = GeomHtabUtils.calculate_optimal_xs_htab(
            ...     invert=580.0, max_wse=605.0, safety_factor=1.3
            ... )
            >>> print(params)
            {'starting_el': 580.0, 'increment': 0.1, 'num_points': 500,
             'actual_max_el': 629.9, 'target_max_el': 612.5, 'target_depth': 32.5,
             'coverage_adequate': True}

            >>> # Very deep cross section (needs larger increment)
            >>> params = GeomHtabUtils.calculate_optimal_xs_htab(
            ...     invert=400.0, max_wse=500.0, safety_factor=1.3
            ... )
            >>> print(f"Increment adjusted to: {params['increment']}")
            Increment adjusted to: 0.27

            >>> # Dam break scenario with higher safety factor
            >>> params = GeomHtabUtils.calculate_optimal_xs_htab(
            ...     invert=580.0, max_wse=620.0, safety_factor=2.0
            ... )

        Notes:
            - Starting elevation is always set to invert (HEC-RAS default +0.5-1ft
              often misses low flow calculations)
            - For very deep cross sections (>49.9 ft with 0.1 increment), the
              increment is automatically increased to fit within 500 points
            - The increment is rounded to 2 decimal places for clean values

        See Also:
            - validate_xs_htab_params(): Validate parameters before use
            - feature_dev_notes/HTAB_Parameter_Modification/optimal_values_algorithm.md
        """
        # Input validation
        if max_wse <= invert:
            raise ValueError(
                f"max_wse ({max_wse}) must be greater than invert ({invert}). "
                "Check that these values are in the same units and datum."
            )

        if safety_factor < 1.0:
            raise ValueError(
                f"safety_factor ({safety_factor}) must be >= 1.0. "
                "Use 1.3 for typical floods, 2.0 for extreme events."
            )

        if max_points < GeomHtabUtils.MIN_XS_POINTS:
            raise ValueError(
                f"max_points ({max_points}) must be >= {GeomHtabUtils.MIN_XS_POINTS}"
            )

        if max_points > GeomHtabUtils.MAX_XS_POINTS:
            raise ValueError(
                f"max_points ({max_points}) must be <= {GeomHtabUtils.MAX_XS_POINTS} "
                "(HEC-RAS limit)"
            )

        if target_increment <= 0:
            raise ValueError(
                f"target_increment ({target_increment}) must be positive"
            )

        # Step 1: Calculate target elevation range with safety factor
        max_depth = max_wse - invert
        target_depth = max_depth * safety_factor
        target_max_el = invert + target_depth

        logger.debug(
            f"XS HTAB calculation: invert={invert}, max_wse={max_wse}, "
            f"max_depth={max_depth:.2f}, target_depth={target_depth:.2f}"
        )

        # Step 2: Check if target increment works with max_points
        # Coverage at target increment: target_increment * (max_points - 1)
        coverage_at_target = target_increment * (max_points - 1)

        if coverage_at_target >= target_depth:
            # Target increment works - use it with max_points for best resolution
            final_increment = target_increment
            final_points = max_points
            logger.debug(
                f"Using target increment {target_increment}: "
                f"coverage={coverage_at_target:.2f} >= target={target_depth:.2f}"
            )
        else:
            # Need larger increment to fit target_depth in max_points
            # Calculate minimum required increment
            calculated_increment = target_depth / (max_points - 1)

            # Round up to clean value (2 decimal places)
            final_increment = math.ceil(calculated_increment * 100) / 100
            final_points = max_points

            logger.info(
                f"Increased XS HTAB increment from {target_increment} to "
                f"{final_increment} to cover {target_depth:.1f} ft depth range"
            )

        # Calculate actual max elevation that will be covered
        actual_max_el = invert + final_increment * (final_points - 1)
        coverage_adequate = actual_max_el >= target_max_el

        # Round invert UP to 0.01 ft precision for starting_el
        # This ensures starting_el >= invert (HEC-RAS requirement)
        starting_el_rounded = math.ceil(invert * 100) / 100

        result = {
            'starting_el': starting_el_rounded,
            'increment': final_increment,
            'num_points': final_points,
            'actual_max_el': round(actual_max_el, 2),
            'target_max_el': round(target_max_el, 2),
            'target_depth': round(target_depth, 2),
            'coverage_adequate': coverage_adequate
        }

        logger.info(
            f"Optimal XS HTAB: starting_el={starting_el_rounded}, increment={final_increment}, "
            f"num_points={final_points}, actual_max_el={actual_max_el:.2f}"
        )

        return result

    @staticmethod
    @log_call
    def calculate_optimal_structure_htab(
        struct_invert: float,
        max_hw: float,
        max_tw: float,
        max_flow: float,
        hw_safety: float = 2.0,
        flow_safety: float = 2.0,
        tw_safety: float = 2.0,
        free_flow_points: int = 20,
        submerged_curves: int = 30,
        points_per_curve: int = 20
    ) -> Dict[str, Union[float, int]]:
        """
        Calculate optimal structure HTAB parameters.

        This function computes optimal HTAB parameters for hydraulic structures
        (bridges, culverts, inline weirs) based on observed maximum headwater,
        tailwater, and flow values with appropriate safety factors.

        The safety factors are applied to the RANGE above the structure invert,
        not to the absolute values. This provides a more reasonable result than
        simply multiplying the headwater elevation by 2.0.

        Algorithm:
            1. Calculate HW range above invert: hw_range = max_hw - struct_invert
            2. Apply safety factor to range: safe_hw_range = hw_range * hw_safety
            3. Calculate HW max: hw_max = struct_invert + safe_hw_range
            4. Repeat for tailwater
            5. For flow, apply safety factor directly: flow_max = max_flow * flow_safety
            6. Set maximum curve point counts for best resolution

        Args:
            struct_invert: Structure invert elevation (lowest opening elevation)
            max_hw: Maximum headwater elevation from simulation results
            max_tw: Maximum tailwater elevation from simulation results
            max_flow: Maximum flow through structure from simulation results
            hw_safety: Safety factor on headwater range (default 2.0 = 100%)
            flow_safety: Safety factor on flow (default 2.0 = 100%)
            tw_safety: Safety factor on tailwater range (default 2.0 = 100%)
            free_flow_points: Points on free flow rating curve (default 20, max 20)
            submerged_curves: Number of submerged flow curves (default 30, max 30)
            points_per_curve: Points per submerged curve (default 20, max 20)

        Returns:
            dict: Optimal structure HTAB parameters with keys:
                - 'hw_max' (float): Maximum headwater elevation
                - 'tw_max' (float): Maximum tailwater elevation
                - 'max_flow' (float): Maximum flow
                - 'use_user_curves' (int): Flag to use user-specified curves (-1)
                - 'free_flow_points' (int): Points on free flow curve
                - 'submerged_curves' (int): Number of submerged curves
                - 'points_per_curve' (int): Points per submerged curve
                - 'hw_range_applied' (float): Headwater range with safety applied
                - 'tw_range_applied' (float): Tailwater range with safety applied

        Raises:
            ValueError: If max_hw < struct_invert
            ValueError: If safety factors < 1.0
            ValueError: If curve point counts out of range

        Examples:
            >>> # Standard structure optimization
            >>> params = GeomHtabUtils.calculate_optimal_structure_htab(
            ...     struct_invert=590.0, max_hw=605.0, max_tw=600.0, max_flow=25000.0
            ... )
            >>> print(f"HW Max: {params['hw_max']}")  # 590 + (605-590)*2 = 620
            HW Max: 620.0
            >>> print(f"Max Flow: {params['max_flow']}")  # 25000 * 2 = 50000
            Max Flow: 50000.0

            >>> # Dam break scenario with extreme flows
            >>> params = GeomHtabUtils.calculate_optimal_structure_htab(
            ...     struct_invert=500.0, max_hw=550.0, max_tw=530.0, max_flow=100000.0,
            ...     hw_safety=3.0, flow_safety=3.0  # Higher safety for extreme events
            ... )

        Notes:
            - Safety is applied to RANGE above invert (e.g., if HW=605, invert=590,
              range=15, with 2.0 safety: 590 + 15*2 = 620) rather than multiplying
              the absolute elevation (605 * 2 = 1210, which is unreasonable)
            - Flow safety is applied directly as a multiplier since flow has no
              inherent reference elevation
            - Setting curve points to maximum values provides best interpolation
              resolution for rating curves

        See Also:
            - validate_structure_htab_params(): Validate parameters before use
            - feature_dev_notes/HTAB_Parameter_Modification/optimal_values_algorithm.md
        """
        # Input validation
        if max_hw < struct_invert:
            raise ValueError(
                f"max_hw ({max_hw}) must be >= struct_invert ({struct_invert}). "
                "Check that these values are in the same units and datum."
            )

        if max_tw < struct_invert:
            logger.warning(
                f"max_tw ({max_tw}) is below struct_invert ({struct_invert}). "
                "This may indicate unusual hydraulic conditions or data error."
            )
            # Allow this case but use invert as minimum
            max_tw = max(max_tw, struct_invert)

        if hw_safety < 1.0:
            raise ValueError(f"hw_safety ({hw_safety}) must be >= 1.0")

        if flow_safety < 1.0:
            raise ValueError(f"flow_safety ({flow_safety}) must be >= 1.0")

        if tw_safety < 1.0:
            raise ValueError(f"tw_safety ({tw_safety}) must be >= 1.0")

        if max_flow <= 0:
            raise ValueError(f"max_flow ({max_flow}) must be positive")

        # Validate and clamp curve point counts
        free_flow_points = max(
            GeomHtabUtils.MIN_FREE_FLOW_POINTS,
            min(free_flow_points, GeomHtabUtils.MAX_FREE_FLOW_POINTS)
        )
        submerged_curves = max(
            GeomHtabUtils.MIN_SUBMERGED_CURVES,
            min(submerged_curves, GeomHtabUtils.MAX_SUBMERGED_CURVES)
        )
        points_per_curve = max(
            GeomHtabUtils.MIN_FREE_FLOW_POINTS,  # Same limits
            min(points_per_curve, GeomHtabUtils.MAX_FREE_FLOW_POINTS)
        )

        # Calculate headwater max (safety applied to range above invert)
        hw_range = max_hw - struct_invert
        safe_hw_range = hw_range * hw_safety
        hw_max = struct_invert + safe_hw_range

        logger.debug(
            f"HW calculation: invert={struct_invert}, max_hw={max_hw}, "
            f"range={hw_range:.2f}, safe_range={safe_hw_range:.2f}, hw_max={hw_max:.2f}"
        )

        # Calculate tailwater max (safety applied to range above invert)
        tw_range = max_tw - struct_invert
        safe_tw_range = tw_range * tw_safety
        tw_max = struct_invert + safe_tw_range

        logger.debug(
            f"TW calculation: max_tw={max_tw}, range={tw_range:.2f}, "
            f"safe_range={safe_tw_range:.2f}, tw_max={tw_max:.2f}"
        )

        # Calculate flow max (direct multiplier)
        flow_max = max_flow * flow_safety

        result = {
            'hw_max': round(hw_max, 2),
            'tw_max': round(tw_max, 2),
            'max_flow': round(flow_max, 2),
            'use_user_curves': -1,  # Enable user-specified curves
            'free_flow_points': free_flow_points,
            'submerged_curves': submerged_curves,
            'points_per_curve': points_per_curve,
            'hw_range_applied': round(safe_hw_range, 2),
            'tw_range_applied': round(safe_tw_range, 2)
        }

        logger.info(
            f"Optimal structure HTAB: hw_max={hw_max:.2f}, tw_max={tw_max:.2f}, "
            f"max_flow={flow_max:.2f}, free_flow_points={free_flow_points}, "
            f"submerged_curves={submerged_curves}"
        )

        return result

    @staticmethod
    @log_call
    def validate_xs_htab_params(
        params: Dict[str, Union[float, int]],
        xs_invert: float,
        xs_top: float
    ) -> Tuple[List[str], List[str]]:
        """
        Validate XS HTAB parameters.

        This function validates cross section HTAB parameters against HEC-RAS
        limits and best practices, returning lists of errors and warnings.

        Args:
            params: HTAB parameters dict with keys:
                - 'starting_el': Starting elevation
                - 'increment': Elevation increment
                - 'num_points': Number of points
            xs_invert: Cross section invert (minimum) elevation
            xs_top: Cross section top (maximum) elevation

        Returns:
            tuple: (errors, warnings) where:
                - errors (List[str]): Critical issues that will cause problems
                - warnings (List[str]): Non-critical issues to review

        Examples:
            >>> params = {'starting_el': 580.0, 'increment': 0.1, 'num_points': 500}
            >>> errors, warnings = GeomHtabUtils.validate_xs_htab_params(
            ...     params, xs_invert=580.0, xs_top=595.0
            ... )
            >>> if errors:
            ...     print(f"ERRORS: {errors}")
            >>> if warnings:
            ...     print(f"WARNINGS: {warnings}")

        Validation Checks:
            ERRORS (will cause HEC-RAS problems):
            - num_points < 20 or > 500 (HEC-RAS limits)
            - increment <= 0
            - starting_el significantly above invert (>1 ft)

            WARNINGS (may cause issues):
            - starting_el > invert + 0.5 (missing low flow range)
            - increment > 1.0 (coarse resolution)
            - actual_max < xs_top (doesn't cover full XS)

        Notes:
            - An empty errors list indicates parameters are valid for HEC-RAS
            - Warnings should be reviewed but don't prevent use
        """
        errors = []
        warnings = []

        starting_el = params.get('starting_el')
        increment = params.get('increment')
        num_points = params.get('num_points')

        # Validate required keys exist
        if starting_el is None:
            errors.append("Missing required parameter: starting_el")
        if increment is None:
            errors.append("Missing required parameter: increment")
        if num_points is None:
            errors.append("Missing required parameter: num_points")

        # If missing required keys, return early
        if errors:
            return errors, warnings

        # Validate num_points against HEC-RAS limits
        if num_points < GeomHtabUtils.MIN_XS_POINTS:
            errors.append(
                f"num_points ({num_points}) below HEC-RAS minimum ({GeomHtabUtils.MIN_XS_POINTS})"
            )

        if num_points > GeomHtabUtils.MAX_XS_POINTS:
            errors.append(
                f"num_points ({num_points}) above HEC-RAS maximum ({GeomHtabUtils.MAX_XS_POINTS})"
            )

        # Validate increment
        if increment <= 0:
            errors.append(f"increment ({increment}) must be positive")
        elif increment < GeomHtabUtils.MIN_XS_INCREMENT:
            warnings.append(
                f"Very small increment ({increment}) may cause numerical issues. "
                f"Minimum recommended: {GeomHtabUtils.MIN_XS_INCREMENT}"
            )

        if increment > GeomHtabUtils.MAX_XS_INCREMENT:
            warnings.append(
                f"Large increment ({increment}) may cause interpolation errors. "
                f"Consider using <= {GeomHtabUtils.MAX_XS_INCREMENT}"
            )

        # Validate starting elevation relative to invert
        if starting_el > xs_invert + 1.0:
            errors.append(
                f"starting_el ({starting_el}) is more than 1 ft above invert "
                f"({xs_invert}). This will miss low flow calculations."
            )
        elif starting_el > xs_invert + 0.5:
            warnings.append(
                f"starting_el ({starting_el}) is above invert + 0.5 ({xs_invert + 0.5}). "
                "Consider using invert as starting elevation to capture low flows."
            )

        if starting_el < xs_invert:
            errors.append(
                f"starting_el ({starting_el}) is below invert ({xs_invert}). "
                "HEC-RAS requires starting_el >= invert. Use math.ceil(invert * 100) / 100 "
                "to round invert up to 0.01 ft precision."
            )

        # Calculate actual max elevation and check coverage
        if increment > 0 and num_points > 0:
            actual_max = starting_el + increment * (num_points - 1)

            if actual_max < xs_top:
                warnings.append(
                    f"HTAB max ({actual_max:.2f}) is below XS top ({xs_top:.2f}). "
                    "Extrapolation may occur at high water levels."
                )

        logger.debug(
            f"XS HTAB validation: {len(errors)} errors, {len(warnings)} warnings"
        )

        return errors, warnings

    @staticmethod
    @log_call
    def validate_structure_htab_params(
        params: Dict[str, Union[float, int]],
        struct_invert: float,
        max_expected_hw: float,
        max_expected_flow: float
    ) -> Tuple[List[str], List[str]]:
        """
        Validate structure HTAB parameters.

        This function validates structure (bridge, culvert, inline weir) HTAB
        parameters against expected values and best practices.

        Args:
            params: HTAB parameters dict with keys:
                - 'hw_max': Maximum headwater elevation
                - 'max_flow': Maximum flow
                - 'free_flow_points': Optional - points on free flow curve
                - 'submerged_curves': Optional - number of submerged curves
                - 'points_per_curve': Optional - points per submerged curve
            struct_invert: Structure invert (lowest opening) elevation
            max_expected_hw: Maximum expected headwater from results
            max_expected_flow: Maximum expected flow from results

        Returns:
            tuple: (errors, warnings) where:
                - errors (List[str]): Critical issues that will cause problems
                - warnings (List[str]): Non-critical issues to review

        Examples:
            >>> params = {'hw_max': 620.0, 'max_flow': 50000.0, 'free_flow_points': 20}
            >>> errors, warnings = GeomHtabUtils.validate_structure_htab_params(
            ...     params, struct_invert=590.0, max_expected_hw=605.0,
            ...     max_expected_flow=25000.0
            ... )
            >>> print(f"Valid: {len(errors) == 0}")
            Valid: True

        Validation Checks:
            ERRORS (will cause HEC-RAS problems):
            - hw_max < max_expected_hw (will extrapolate)
            - max_flow < max_expected_flow (will extrapolate)
            - hw_max < struct_invert (physically impossible)

            WARNINGS (may cause issues):
            - free_flow_points < 10 (coarse rating curve)
            - submerged_curves < 10 (coarse submerged flow)
            - hw_max only slightly above max_expected (low safety margin)
        """
        errors = []
        warnings = []

        hw_max = params.get('hw_max')
        max_flow = params.get('max_flow')
        free_flow_points = params.get('free_flow_points')
        submerged_curves = params.get('submerged_curves')
        points_per_curve = params.get('points_per_curve')

        # Validate required parameters
        if hw_max is None:
            errors.append("Missing required parameter: hw_max")
        if max_flow is None:
            errors.append("Missing required parameter: max_flow")

        if errors:
            return errors, warnings

        # Validate hw_max against expected and invert
        if hw_max < max_expected_hw:
            errors.append(
                f"hw_max ({hw_max}) is below expected maximum ({max_expected_hw}). "
                "Extrapolation will occur. Increase hw_max with safety factor."
            )
        elif hw_max < max_expected_hw * 1.1:
            warnings.append(
                f"hw_max ({hw_max}) is less than 10% above expected maximum "
                f"({max_expected_hw}). Consider increasing safety margin."
            )

        if hw_max < struct_invert:
            errors.append(
                f"hw_max ({hw_max}) is below structure invert ({struct_invert}). "
                "This is physically impossible."
            )

        # Validate max_flow against expected
        if max_flow < max_expected_flow:
            errors.append(
                f"max_flow ({max_flow}) is below expected maximum ({max_expected_flow}). "
                "Extrapolation will occur. Increase max_flow with safety factor."
            )
        elif max_flow < max_expected_flow * 1.1:
            warnings.append(
                f"max_flow ({max_flow}) is less than 10% above expected maximum "
                f"({max_expected_flow}). Consider increasing safety margin."
            )

        # Validate curve point counts
        if free_flow_points is not None:
            if free_flow_points < GeomHtabUtils.MIN_FREE_FLOW_POINTS:
                warnings.append(
                    f"Low free_flow_points ({free_flow_points}) may give coarse "
                    f"rating curve. Recommended: {GeomHtabUtils.DEFAULT_FREE_FLOW_POINTS}"
                )

        if submerged_curves is not None:
            if submerged_curves < GeomHtabUtils.MIN_SUBMERGED_CURVES:
                warnings.append(
                    f"Low submerged_curves ({submerged_curves}) may give coarse "
                    f"submerged flow results. Recommended: {GeomHtabUtils.DEFAULT_SUBMERGED_CURVES}"
                )

        if points_per_curve is not None:
            if points_per_curve < 10:
                warnings.append(
                    f"Low points_per_curve ({points_per_curve}) may give coarse "
                    f"results. Recommended: {GeomHtabUtils.DEFAULT_POINTS_PER_CURVE}"
                )

        logger.debug(
            f"Structure HTAB validation: {len(errors)} errors, {len(warnings)} warnings"
        )

        return errors, warnings

    @staticmethod
    def get_xs_htab_defaults() -> Dict[str, Union[float, int]]:
        """
        Get default XS HTAB parameter recommendations.

        Returns:
            dict: Recommended default values with keys:
                - 'increment': Default elevation increment (0.1 ft)
                - 'num_points': Default number of points (500)
                - 'safety_factor': Default safety factor (1.3)
                - 'min_points': Minimum points (20)
                - 'max_points': Maximum points (500)
        """
        return {
            'increment': GeomHtabUtils.DEFAULT_XS_INCREMENT,
            'num_points': GeomHtabUtils.MAX_XS_POINTS,
            'safety_factor': GeomHtabUtils.DEFAULT_XS_SAFETY_FACTOR,
            'min_points': GeomHtabUtils.MIN_XS_POINTS,
            'max_points': GeomHtabUtils.MAX_XS_POINTS,
            'min_increment': GeomHtabUtils.MIN_XS_INCREMENT,
            'max_increment': GeomHtabUtils.MAX_XS_INCREMENT
        }

    @staticmethod
    def get_structure_htab_defaults() -> Dict[str, Union[float, int]]:
        """
        Get default structure HTAB parameter recommendations.

        Returns:
            dict: Recommended default values with keys:
                - 'hw_safety': Default headwater safety factor (2.0)
                - 'tw_safety': Default tailwater safety factor (2.0)
                - 'flow_safety': Default flow safety factor (2.0)
                - 'free_flow_points': Default free flow points (20)
                - 'submerged_curves': Default submerged curves (30)
                - 'points_per_curve': Default points per curve (20)
        """
        return {
            'hw_safety': GeomHtabUtils.DEFAULT_HW_SAFETY_FACTOR,
            'tw_safety': GeomHtabUtils.DEFAULT_TW_SAFETY_FACTOR,
            'flow_safety': GeomHtabUtils.DEFAULT_FLOW_SAFETY_FACTOR,
            'free_flow_points': GeomHtabUtils.DEFAULT_FREE_FLOW_POINTS,
            'submerged_curves': GeomHtabUtils.DEFAULT_SUBMERGED_CURVES,
            'points_per_curve': GeomHtabUtils.DEFAULT_POINTS_PER_CURVE,
            'min_free_flow_points': GeomHtabUtils.MIN_FREE_FLOW_POINTS,
            'max_free_flow_points': GeomHtabUtils.MAX_FREE_FLOW_POINTS,
            'min_submerged_curves': GeomHtabUtils.MIN_SUBMERGED_CURVES,
            'max_submerged_curves': GeomHtabUtils.MAX_SUBMERGED_CURVES
        }
