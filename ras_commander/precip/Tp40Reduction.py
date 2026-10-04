"""Bounded HEC-HMS-compatible TP-40 reduction factors for a stated storm area.

The qualified range is five minutes through 24 hours and 0 through 400 square
miles.  This module only transforms already selected point depth-duration
values; it does not choose an evaluation area, alter series conventions, or
perform annual/partial-duration conversion.
"""

import math

from ..LoggingConfig import get_logger, log_call


logger = get_logger(__name__)


class Tp40Reduction:
    """Evaluate the qualified HEC-HMS TP-40 depth-area-reduction relation.

    The factor coefficient is log-log interpolated between the published
    duration knots.  The qualified HEC-HMS convention uses the 30-minute
    coefficient for durations at or below 30 minutes.  This is intentionally
    explicit because the technical-reference prose says durations below 30
    minutes are unadjusted; callers requiring that convention must not use
    this compatibility helper.  The resulting areal reduction factor is

    ``1 - f_D * (1 - exp(-0.015 * area_sqmi))``.

    The underlying equation is documented in the HEC-HMS Technical Reference
    Manual, *Depth-Area Reduction Relationships*.  The coefficient knots match
    the HEC-HMS TP-40/TP-49 implementation.  TP-49 durations are deliberately
    outside this focused TP-40 interface.

    https://www.hec.usace.army.mil/Software/hec-hms/documentation/
    HEC-HMS_Technical_Reference_Manual-20231106.pdf
    """

    MIN_DURATION_MINUTES = 5.0
    MAX_DURATION_MINUTES = 1440.0
    MAX_AREA_SQMI = 400.0
    _DURATION_KNOTS_MINUTES = (30.0, 60.0, 180.0, 360.0, 1440.0)
    _COEFFICIENT_KNOTS = (0.48, 0.35, 0.22, 0.17, 0.09)

    @staticmethod
    @log_call
    def factor(duration_minutes: float, storm_area_sqmi: float) -> float:
        """Return the unitless TP-40 factor for duration and storm area.

        Args:
            duration_minutes: Storm duration from 5 through 1,440 minutes.
                Durations through 30 minutes use the 30-minute coefficient in
                this qualified HEC-HMS-compatible convention.
            storm_area_sqmi: Explicit evaluation area from 0 through 400 square
                miles.  This must be the documented storm area, not an inferred
                grid-cell or polygon area.

        Returns:
            A unitless multiplier in (0, 1], equal to one for zero area.

        Raises:
            ValueError: If the supplied duration or area is outside the
                qualified TP-40 domain, or is not finite.
        """
        duration = float(duration_minutes)
        area = float(storm_area_sqmi)
        if not math.isfinite(duration) or not (
            Tp40Reduction.MIN_DURATION_MINUTES <= duration
            <= Tp40Reduction.MAX_DURATION_MINUTES
        ):
            raise ValueError(
                "duration_minutes must be finite and within the qualified "
                "TP-40 range [5, 1440] minutes"
            )
        if not math.isfinite(area) or not (0.0 <= area <= Tp40Reduction.MAX_AREA_SQMI):
            raise ValueError(
                "storm_area_sqmi must be finite and within the qualified "
                "TP-40 range [0, 400] square miles"
            )

        coefficient = Tp40Reduction._coefficient(duration)
        reduction = 1.0 - coefficient * (1.0 - math.exp(-0.015 * area))
        logger.debug(
            "TP-40 reduction factor %.12f for %.3f min and %.6f sq mi",
            reduction,
            duration,
            area,
        )
        return reduction

    @staticmethod
    def _coefficient(duration_minutes: float) -> float:
        """Return the log-log-interpolated duration coefficient ``f_D``."""
        duration = max(duration_minutes, Tp40Reduction._DURATION_KNOTS_MINUTES[0])
        knots = Tp40Reduction._DURATION_KNOTS_MINUTES
        coefficients = Tp40Reduction._COEFFICIENT_KNOTS
        for index in range(1, len(knots)):
            upper_duration = knots[index]
            if duration <= upper_duration:
                lower_duration = knots[index - 1]
                lower_coefficient = coefficients[index - 1]
                upper_coefficient = coefficients[index]
                fraction = (
                    (math.log(duration) - math.log(lower_duration))
                    / (math.log(upper_duration) - math.log(lower_duration))
                )
                return math.exp(
                    math.log(lower_coefficient)
                    + fraction * (math.log(upper_coefficient) - math.log(lower_coefficient))
                )
        return coefficients[-1]
