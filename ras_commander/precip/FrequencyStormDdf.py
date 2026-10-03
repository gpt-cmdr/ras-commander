"""Duration-dependent frequency rainfall, qualified against reference deliverables.

This is distinct from the fixed temporal pattern exported as FrequencyStorm.
The supported configuration reproduces seven delivered HMS 4.10 storms; it is
not a general implementation of every HMS frequency-storm option.
"""

from typing import Sequence

import numpy as np
import pandas as pd

from ..LoggingConfig import get_logger, log_call

logger = get_logger(__name__)


class FrequencyStormDdf:
    """Generate the centered 24-hour, five-minute Hydro-35 DDF configuration.

    Qualification: independent reference data, seven events,
    HMS 4.10, no area reduction, matching input/output annual-series flags.
    Supply final depth-duration inputs in inches. No areal reduction or
    annual/partial-duration conversion is performed here.
    """

    DURATIONS_MINUTES = (5, 15, 60, 120, 180, 360, 720, 1440)

    @staticmethod
    @log_call
    def generate_hyetograph(
        depths_inches: Sequence[float],
        durations_minutes: Sequence[float],
        *,
        simulation_duration_hours: float = 24.0,
    ) -> pd.DataFrame:
        """Build interval-end depths from all eight duration-labelled inputs.

        Hydro-35 supplies P10 = .59*P15 + .41*P5 and
        P30 = .49*P60 + .51*P15. Log-log interpolation gives cumulative
        depths every five minutes. Successive differences are placed around
        the center in duration order, left first, without globally sorting.
        That ordering matches the delivered data even at DDF slope changes.

        The five-minute central block occupies 12:00–12:05 (zero-based interval
        index 144). Output includes one zero-depth start row, followed by
        interval-end ordinates. Optional dry intervals extend the series
        beyond 24 hours; no wet depth is rescaled.

        Args:
            depths_inches: Eight positive, nondecreasing cumulative depths.
            durations_minutes: Explicitly [5, 15, 60, 120, 180, 360, 720, 1440].
                Labels are mandatory: other eight-depth HMS vectors exist.
            simulation_duration_hours: At least 24 hours, in whole five-minute
                increments. For the reference ten-day control window use 240.

        Returns:
            DataFrame with hour, incremental_depth, cumulative_depth. Depths
            are inches, with 289 rows for the default 24-hour window.

        Raises:
            ValueError: Unsupported duration labels, invalid depths, or window.

        Notes:
            Only the documented 24h/5min/50%-centered configuration is qualified.
            HEC's manual describes sorting; the delivered reference outputs instead
            match duration-order placement. Do not infer universal HMS behavior.
            https://www.hec.usace.army.mil/confluence/hmsdocs/hmstrm/meteorology/precipitation/frequency-storm
        """
        depths = np.asarray(depths_inches, dtype=np.float64)
        durations = np.asarray(durations_minutes, dtype=np.float64)
        if durations.shape != (8,) or not np.array_equal(durations, FrequencyStormDdf.DURATIONS_MINUTES):
            raise ValueError(
                "durations_minutes must explicitly be [5, 15, 60, 120, 180, 360, 720, 1440]; "
                "other duration/interval/peak configurations are not qualified"
            )
        if (depths.shape != (8,) or not np.all(np.isfinite(depths))
                or np.any(depths <= 0) or np.any(np.diff(depths) < 0)):
            raise ValueError("depths_inches must contain eight finite, positive, nondecreasing depths")
        if not np.isfinite(simulation_duration_hours) or simulation_duration_hours < 24:
            raise ValueError("simulation_duration_hours must be finite and at least 24")
        interval_count = simulation_duration_hours * 12
        if not np.isclose(interval_count, round(interval_count), rtol=0, atol=1e-8):
            raise ValueError("simulation_duration_hours must contain whole five-minute intervals")

        p5, p15, p60 = depths[:3]
        augmented_durations = np.array([5, 10, 15, 30, 60, 120, 180, 360, 720, 1440])
        augmented_depths = np.concatenate((
            [p5, .59 * p15 + .41 * p5, p15, .49 * p60 + .51 * p15], depths[2:]
        ))
        cumulative = np.exp(np.interp(
            np.log(np.arange(5, 1441, 5)), np.log(augmented_durations), np.log(augmented_depths)
        ))
        increments = np.diff(np.concatenate(([0.0], cumulative)))
        # Preserve duration order; global sorting changes the delivered storm.
        positions = [144]
        for offset in range(1, 145):
            positions.append(144 - offset)
            if 144 + offset < 288:
                positions.append(144 + offset)
        output = np.zeros(int(round(interval_count)) + 1, dtype=np.float64)
        output[np.asarray(positions) + 1] = increments
        result = pd.DataFrame({
            'hour': np.arange(output.size, dtype=np.float64) / 12,
            'incremental_depth': output,
            'cumulative_depth': np.cumsum(output),
        })
        result.attrs.update(
            units='inches', timestep_minutes=5, storm_duration_hours=24,
            peak_position_percent=50, interval_convention='interval_end_with_zero_start',
            method='Hydro35 log-log duration-order placement',
            qualification='reference HMS 4.10 seven delivered frequency events',
            area_reduction_applied=False, series_conversion_applied=False,
        )
        logger.info("Generated DDF frequency storm: %.6f inches, %d five-minute intervals",
                    output.sum(), output.size - 1)
        return result
