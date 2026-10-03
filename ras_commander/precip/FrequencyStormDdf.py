"""Duration-dependent frequency rainfall, qualified against reference deliverables.

This is distinct from the fixed temporal pattern exported as FrequencyStorm.
The bounded configurations are checked against independent delivered records;
this is not a general implementation of every HMS frequency-storm option.
"""

from typing import Sequence

import numpy as np
import pandas as pd

from ..LoggingConfig import get_logger, log_call
from .Tp40Reduction import Tp40Reduction

logger = get_logger(__name__)


class FrequencyStormDdf:
    """Generate a 24-hour, five-minute balanced depth-duration storm.

    Standard eight-knot and explicit ten-knot inputs, centered and 67% peak
    placement, and optional TP-40 reduction are supported. Supply depths in
    inches with matching input/output statistical series. Annual/partial-
    duration conversion is not performed.
    """

    DURATIONS_MINUTES = (5, 15, 60, 120, 180, 360, 720, 1440)
    EXPLICIT_DURATIONS_MINUTES = (5, 10, 15, 30, 60, 120, 180, 360, 720, 1440)

    @staticmethod
    @log_call
    def generate_hyetograph(
        depths_inches: Sequence[float],
        durations_minutes: Sequence[float],
        *,
        simulation_duration_hours: float = 24.0,
        peak_position_percent: float = 50.0,
        area_reduction_method: str = "none",
        storm_area_sqmi: float | None = None,
    ) -> pd.DataFrame:
        """Build interval-end depths from duration-labelled cumulative inputs.

        Hydro-35 supplies P10 = .59*P15 + .41*P5 and
        P30 = .49*P60 + .51*P15. Log-log interpolation gives cumulative
        depths every five minutes. Explicit 10/30-minute values are retained.
        Optional TP-40 factors apply to augmented knots before interpolation.
        Successive differences are placed around the requested peak in
        duration order, left first, without globally sorting.
        That ordering matches the delivered data even at DDF slope changes.

        At 50% placement, the peak block occupies 12:00–12:05 (zero-based
        interval index 144); at 67%, it occupies 16:00–16:05 (index 192). Output includes one zero-depth start row, followed by
        interval-end ordinates. Optional dry intervals extend the series
        beyond 24 hours; no wet depth is rescaled.

        Args:
            depths_inches: Positive, nondecreasing cumulative depths in inches.
            durations_minutes: Standard eight durations [5, 15, 60, 120, 180,
                360, 720, 1440], or those plus explicit 10 and 30 minutes.
                Labels are mandatory: other eight-depth vectors exist.
            simulation_duration_hours: At least 24 hours, in whole five-minute
                increments. For the reference ten-day control window use 240.
            peak_position_percent: Qualified positions 50 or 67. The placement
                indices are 144 and 192 respectively, counting from zero.
            area_reduction_method: 'none' or 'TP-40'. Already reduced depths
                must use 'none' to avoid applying reduction twice.
            storm_area_sqmi: Explicit evaluation storm area in square miles,
                required with TP-40. This is not inferred from a cell or polygon.

        Returns:
            DataFrame with hour, incremental_depth, cumulative_depth. Depths
            are inches, with 289 rows for the default 24-hour window.

        Raises:
            ValueError: Unsupported duration labels, invalid depths, or window.

        Notes:
            Only the documented 24h/5min/50% and 67% configurations are covered.
            HEC's manual describes sorting; the delivered reference outputs instead
            match duration-order placement. Do not infer universal HMS behavior.
            https://www.hec.usace.army.mil/confluence/hmsdocs/hmstrm/meteorology/precipitation/frequency-storm
        """
        depths = np.asarray(depths_inches, dtype=np.float64)
        durations = np.asarray(durations_minutes, dtype=np.float64)
        standard = np.array_equal(durations, FrequencyStormDdf.DURATIONS_MINUTES)
        explicit = np.array_equal(durations, FrequencyStormDdf.EXPLICIT_DURATIONS_MINUTES)
        if not standard and not explicit:
            raise ValueError(
                "durations_minutes must explicitly match the standard eight or ten knots"
            )
        if (depths.shape != durations.shape or not np.all(np.isfinite(depths))
                or np.any(depths <= 0) or np.any(np.diff(depths) < 0)):
            raise ValueError("depths_inches must contain finite, positive, nondecreasing depths matching durations")
        if not np.isfinite(simulation_duration_hours) or simulation_duration_hours < 24:
            raise ValueError("simulation_duration_hours must be finite and at least 24")
        interval_count = simulation_duration_hours * 12
        if not np.isfinite(interval_count) or not np.isclose(interval_count, round(interval_count), rtol=0, atol=1e-8):
            raise ValueError("simulation_duration_hours must contain whole five-minute intervals")
        if peak_position_percent not in (50, 67):
            raise ValueError("peak_position_percent must be 50 or 67 for qualified configurations")
        if area_reduction_method not in ("none", "TP-40"):
            raise ValueError("area_reduction_method must be 'none' or 'TP-40'")
        if area_reduction_method == "none" and storm_area_sqmi is not None:
            raise ValueError("storm_area_sqmi requires area_reduction_method='TP-40'")
        if area_reduction_method == "TP-40" and storm_area_sqmi is None:
            raise ValueError("TP-40 requires explicit storm_area_sqmi")

        augmented_durations = np.array([5, 10, 15, 30, 60, 120, 180, 360, 720, 1440])
        if standard:
            p5, p15, p60 = depths[:3]
            augmented_depths = np.concatenate((
                [p5, .59 * p15 + .41 * p5, p15, .49 * p60 + .51 * p15], depths[2:]))
        else:
            augmented_depths = depths.copy()
        factors = np.ones(10)
        if area_reduction_method == "TP-40":
            factors = np.asarray([Tp40Reduction.factor(float(d), storm_area_sqmi)
                                  for d in augmented_durations])
            augmented_depths *= factors
        if np.any(np.diff(augmented_depths) < 0):
            raise ValueError("Area-adjusted cumulative depths must not decrease")
        cumulative = np.exp(np.interp(
            np.log(np.arange(5, 1441, 5)), np.log(augmented_durations), np.log(augmented_depths)
        ))
        increments = np.diff(np.concatenate(([0.0], cumulative)))
        # Preserve duration order; global sorting changes the delivered storm.
        peak = int(peak_position_percent * 288 / 100)
        positions = [peak]
        left, right = peak - 1, peak + 1
        for rank in range(1, 288):
            if left >= 0 and (right >= 288 or rank % 2 == 1):
                positions.append(left)
                left -= 1
            else:
                positions.append(right)
                right += 1
        output = np.zeros(int(round(interval_count)) + 1, dtype=np.float64)
        output[np.asarray(positions) + 1] = increments
        result = pd.DataFrame({
            'hour': np.arange(output.size, dtype=np.float64) / 12,
            'incremental_depth': output,
            'cumulative_depth': np.cumsum(output),
        })
        result.attrs.update(
            units='inches', timestep_minutes=5, storm_duration_hours=24,
            peak_position_percent=peak_position_percent,
            peak_placement_index_zero_based=peak,
            actual_peak_index_zero_based=int(np.argmax(output[1:289])),
            interval_convention='interval_end_with_zero_start',
            method='Hydro35 log-log duration-order placement',
            qualification='bounded independent reference comparisons; see method documentation',
            knot_mode='derived_standard_ten' if standard else 'explicit_standard_ten',
            area_reduction_applied=area_reduction_method == 'TP-40',
            area_reduction_method=area_reduction_method, storm_area_sqmi=storm_area_sqmi,
            area_reduction_factors=factors.tolist(),
            point_storm_depth_inches=float(depths[-1]),
            areal_storm_depth_inches=float(augmented_depths[-1]),
            series_conversion_applied=False,
        )
        logger.info("Generated DDF frequency storm: %.6f inches, %d five-minute intervals",
                    output.sum(), output.size - 1)
        return result
