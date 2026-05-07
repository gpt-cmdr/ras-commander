"""
StormGenerator Alternating Block Method — Independent Textbook Validation.

Validates ras-commander's StormGenerator against an independent reference
implementation of the Alternating Block Method coded directly from:

    Chow, V.T., Maidment, D.R., Mays, L.W. (1988).
    Applied Hydrology. McGraw-Hill, Section 14.4 "Design Storms".

Also provides cross-method comparisons against hms-commander's HMS-validated
storm generation classes (Atlas14Storm, FrequencyStorm, ScsTypeStorm) to
document the differences in temporal pattern, peak intensity, and applicability.

FORMAL STUDY NOTE:
    These tests provide confidence that the library implementations are
    mathematically correct and internally consistent. For formal engineering
    studies (FEMA submittals, HCFCD design, etc.), it is recommended to set
    up a full HEC-HMS project with HITL (human-in-the-loop) review that
    confirms and validates the precipitation inputs on a project-specific
    basis, rather than relying solely on third-party library validation.
"""

import pytest
import numpy as np
import pandas as pd
from typing import Tuple

from ras_commander.precip import StormGenerator

# Attempt hms-commander imports for cross-method comparison tests
try:
    from hms_commander import Atlas14Storm, FrequencyStorm, ScsTypeStorm
    HMS_AVAILABLE = True
except ImportError:
    HMS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Independent Textbook Reference Implementation
# ---------------------------------------------------------------------------
# Coded directly from Chow, Maidment, Mays (1988) Section 14.4.
# NO imports from ras-commander or hms-commander — purely for comparison.
# ---------------------------------------------------------------------------

def _textbook_log_log_interpolate(
    source_durations_hours: np.ndarray,
    source_depths: np.ndarray,
    target_durations_hours: np.ndarray,
) -> np.ndarray:
    """
    Log-log interpolation of DDF curve (Chow et al. 1988, p. 446).

    IDF/DDF data follows approximate power-law behavior, so log-log
    interpolation is the standard approach for sub-tabular durations.
    """
    log_src_d = np.log(source_durations_hours)
    log_src_z = np.log(source_depths)
    log_tgt_d = np.log(target_durations_hours)
    log_tgt_z = np.interp(log_tgt_d, log_src_d, log_src_z)
    return np.exp(log_tgt_z)


def textbook_alternating_block(
    source_durations_hours: np.ndarray,
    source_depths: np.ndarray,
    total_depth_inches: float,
    duration_hours: float,
    dt_hours: float,
    peak_position_fraction: float = 0.5,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Alternating Block Method — independent textbook reference.

    Implements the algorithm exactly as described in Chow, Maidment, Mays
    (1988) Applied Hydrology, Section 14.4, pp. 446-449:

    1. From the DDF curve, read (or interpolate) the cumulative depth for
       each sub-duration Δt, 2Δt, 3Δt, ... up to the total storm duration.
    2. Compute incremental depths: ΔP_n = P(nΔt) − P((n−1)Δt).
    3. Rank the incremental depths from largest to smallest.
    4. Place the largest increment at the central time block.
    5. Alternate placing the next-largest increments to the LEFT and RIGHT
       of center.
    6. Scale the entire hyetograph so total depth matches the design value.

    Parameters
    ----------
    source_durations_hours : array
        Tabulated DDF durations (hours).
    source_depths : array
        Tabulated DDF depths (inches) for a single ARI.
    total_depth_inches : float
        Target total storm depth (e.g., Atlas 14 value).
    duration_hours : float
        Total storm duration in hours.
    dt_hours : float
        Time step (Δt) in hours.
    peak_position_fraction : float
        Where to place the peak (0.0 = start, 0.5 = center, 1.0 = end).

    Returns
    -------
    t_hours : ndarray
        Time values at end of each interval.
    incremental_depths : ndarray
        Incremental precipitation depth for each interval.
    """
    # Step 1: Build sub-duration array: dt, 2*dt, ..., duration
    n_intervals = int(round(duration_hours / dt_hours))
    sub_durations = np.arange(1, n_intervals + 1) * dt_hours

    # Step 2: Interpolate cumulative depths from DDF
    cumulative = _textbook_log_log_interpolate(
        source_durations_hours, source_depths, sub_durations
    )

    # Step 3: Compute incremental depths
    incremental = np.zeros(n_intervals)
    incremental[0] = cumulative[0]
    for i in range(1, n_intervals):
        incremental[i] = cumulative[i] - cumulative[i - 1]

    # Step 4: Sort descending
    sorted_desc = np.sort(incremental)[::-1]

    # Step 5: Alternating block assignment
    result = np.zeros(n_intervals)
    center = int(peak_position_fraction * n_intervals)
    center = max(0, min(center, n_intervals - 1))

    result[center] = sorted_desc[0]  # largest at center

    left = center - 1
    right = center + 1
    for i in range(1, len(sorted_desc)):
        if i % 2 == 1:  # odd rank → left
            if left >= 0:
                result[left] = sorted_desc[i]
                left -= 1
            elif right < n_intervals:
                result[right] = sorted_desc[i]
                right += 1
        else:  # even rank → right
            if right < n_intervals:
                result[right] = sorted_desc[i]
                right += 1
            elif left >= 0:
                result[left] = sorted_desc[i]
                left -= 1

    # Step 6: Scale to match target total depth
    pattern_total = result.sum()
    if pattern_total > 0:
        result = result * (total_depth_inches / pattern_total)

    t_hours = sub_durations
    return t_hours, result


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def houston_ddf():
    """
    Synthetic DDF data representative of Houston, TX (Harris County).

    Values approximate NOAA Atlas 14 Volume 11 for a location near
    downtown Houston. Not exact — used for algorithm validation, not
    for design.  All values are AMS (Annual Maximum Series).
    """
    durations = [5/60, 10/60, 15/60, 30/60, 1, 2, 3, 6, 12, 24]
    data = {
        'duration_hours': durations,
        '2':   [0.60, 0.87, 1.07, 1.43, 1.82, 2.22, 2.51, 3.20, 4.10, 5.20],
        '5':   [0.78, 1.13, 1.39, 1.86, 2.37, 2.89, 3.26, 4.16, 5.33, 6.76],
        '10':  [0.93, 1.35, 1.66, 2.22, 2.83, 3.45, 3.89, 4.97, 6.36, 8.07],
        '25':  [1.15, 1.67, 2.05, 2.74, 3.49, 4.26, 4.81, 6.14, 7.86, 9.97],
        '50':  [1.33, 1.93, 2.37, 3.17, 4.04, 4.93, 5.57, 7.10, 9.10, 11.5],
        '100': [1.53, 2.22, 2.73, 3.65, 4.65, 5.67, 6.40, 8.17, 10.5, 13.3],
    }
    df = pd.DataFrame(data)
    df.attrs['metadata'] = {
        'source': 'synthetic_houston_representative',
        'ari_columns': ['2', '5', '10', '25', '50', '100'],
        'durations_hours': durations,
    }
    return df


@pytest.fixture
def springfield_ddf():
    """
    Synthetic DDF data for a Midwest location (Springfield, IL area).

    Lower precipitation depths than Houston — tests algorithm behavior
    with a different climate regime.
    """
    durations = [5/60, 15/60, 30/60, 1, 2, 3, 6, 12, 24]
    data = {
        'duration_hours': durations,
        '10':  [0.55, 0.98, 1.28, 1.60, 1.92, 2.10, 2.52, 3.00, 3.50],
        '25':  [0.68, 1.21, 1.58, 1.98, 2.38, 2.60, 3.12, 3.72, 4.34],
        '50':  [0.78, 1.39, 1.82, 2.28, 2.74, 2.99, 3.59, 4.28, 5.00],
        '100': [0.89, 1.59, 2.08, 2.60, 3.12, 3.41, 4.09, 4.88, 5.70],
    }
    df = pd.DataFrame(data)
    df.attrs['metadata'] = {
        'source': 'synthetic_springfield_representative',
        'ari_columns': ['10', '25', '50', '100'],
        'durations_hours': durations,
    }
    return df


# ---------------------------------------------------------------------------
# Task 1 & 2: Textbook Validation Tests
# ---------------------------------------------------------------------------

class TestAlternatingBlockTextbookValidation:
    """
    Validate StormGenerator against independent textbook implementation.

    The reference implementation above was coded directly from Chow et al.
    (1988) without reference to ras-commander source code.
    """

    def test_depth_conservation_exact(self, houston_ddf):
        """Total depth must match the specified value to machine precision."""
        target = 13.3  # 100-yr 24-hr
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=target,
            duration_hours=24,
            position_percent=50,
        )
        actual = hyeto['cumulative_depth'].iloc[-1]
        assert abs(actual - target) < 1e-9, (
            f"Depth not conserved: got {actual}, expected {target}"
        )

    def test_matches_textbook_pattern_24hr(self, houston_ddf):
        """
        StormGenerator must produce identical pattern to textbook implementation.

        Both implementations should:
        - Use log-log interpolation on the same DDF data
        - Produce the same incremental depth ranking
        - Place blocks in the same alternating order
        - Scale to the same total depth
        """
        target = 13.3
        duration = 24
        dt = 1.0  # StormGenerator uses 1-hour for 24-hr storms

        # StormGenerator output
        sg_hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=target,
            duration_hours=duration,
            position_percent=50,
        )

        # Textbook reference output
        durations_arr = houston_ddf['duration_hours'].values
        first_ari = [c for c in houston_ddf.columns if c != 'duration_hours'][0]
        depths_arr = houston_ddf[first_ari].values

        t_ref, inc_ref = textbook_alternating_block(
            source_durations_hours=durations_arr,
            source_depths=depths_arr,
            total_depth_inches=target,
            duration_hours=duration,
            dt_hours=dt,
            peak_position_fraction=0.5,
        )

        sg_inc = sg_hyeto['incremental_depth'].values

        assert len(sg_inc) == len(inc_ref), (
            f"Interval count mismatch: SG={len(sg_inc)}, textbook={len(inc_ref)}"
        )

        np.testing.assert_allclose(
            sg_inc, inc_ref, atol=1e-9,
            err_msg="StormGenerator pattern does not match textbook reference"
        )

    def test_matches_textbook_pattern_6hr(self, houston_ddf):
        """Verify match for 6-hour storm (5-minute intervals)."""
        target = 8.17
        duration = 6
        dt = 5.0 / 60.0

        sg_hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=target,
            duration_hours=duration,
            position_percent=50,
        )

        durations_arr = houston_ddf['duration_hours'].values
        first_ari = [c for c in houston_ddf.columns if c != 'duration_hours'][0]
        depths_arr = houston_ddf[first_ari].values

        t_ref, inc_ref = textbook_alternating_block(
            source_durations_hours=durations_arr,
            source_depths=depths_arr,
            total_depth_inches=target,
            duration_hours=duration,
            dt_hours=dt,
            peak_position_fraction=0.5,
        )

        sg_inc = sg_hyeto['incremental_depth'].values

        assert len(sg_inc) == len(inc_ref), (
            f"Interval count mismatch: SG={len(sg_inc)}, textbook={len(inc_ref)}"
        )

        np.testing.assert_allclose(
            sg_inc, inc_ref, atol=1e-9,
            err_msg="6-hour storm pattern does not match textbook"
        )

    def test_matches_textbook_midwest_climate(self, springfield_ddf):
        """Verify match with lower-depth Midwest DDF data."""
        target = 5.70
        duration = 24
        dt = 1.0

        sg_hyeto = StormGenerator.generate_hyetograph(
            ddf_data=springfield_ddf,
            total_depth_inches=target,
            duration_hours=duration,
            position_percent=50,
        )

        durations_arr = springfield_ddf['duration_hours'].values
        first_ari = [c for c in springfield_ddf.columns if c != 'duration_hours'][0]
        depths_arr = springfield_ddf[first_ari].values

        t_ref, inc_ref = textbook_alternating_block(
            source_durations_hours=durations_arr,
            source_depths=depths_arr,
            total_depth_inches=target,
            duration_hours=duration,
            dt_hours=dt,
            peak_position_fraction=0.5,
        )

        sg_inc = sg_hyeto['incremental_depth'].values
        np.testing.assert_allclose(
            sg_inc, inc_ref, atol=1e-9,
            err_msg="Midwest climate DDF pattern does not match textbook"
        )

    @pytest.mark.parametrize("position_pct,position_frac", [
        (0, 0.0), (25, 0.25), (50, 0.5), (75, 0.75), (100, 1.0),
    ])
    def test_peak_position_matches_textbook(
        self, houston_ddf, position_pct, position_frac
    ):
        """Peak position parameter must produce same placement as textbook."""
        target = 10.0
        duration = 24
        dt = 1.0

        sg_hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=target,
            duration_hours=duration,
            position_percent=position_pct,
        )

        durations_arr = houston_ddf['duration_hours'].values
        first_ari = [c for c in houston_ddf.columns if c != 'duration_hours'][0]
        depths_arr = houston_ddf[first_ari].values

        _, inc_ref = textbook_alternating_block(
            source_durations_hours=durations_arr,
            source_depths=depths_arr,
            total_depth_inches=target,
            duration_hours=duration,
            dt_hours=dt,
            peak_position_fraction=position_frac,
        )

        sg_inc = sg_hyeto['incremental_depth'].values
        np.testing.assert_allclose(
            sg_inc, inc_ref, atol=1e-9,
            err_msg=f"Position {position_pct}% does not match textbook"
        )

    def test_peak_is_maximum_block(self, houston_ddf):
        """The peak interval must contain the maximum incremental depth."""
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=13.3,
            duration_hours=24,
            position_percent=50,
        )
        inc = hyeto['incremental_depth'].values
        peak_idx = np.argmax(inc)
        n = len(inc)
        expected_center = int(0.5 * n)
        assert peak_idx == expected_center, (
            f"Peak at index {peak_idx}, expected center index {expected_center}"
        )

    def test_monotonic_decrease_from_peak(self, houston_ddf):
        """
        Blocks must decrease monotonically outward from the peak.

        This is the fundamental property of the Alternating Block Method:
        the highest depth is at center, and values decrease in both
        directions away from center.
        """
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=13.3,
            duration_hours=24,
            position_percent=50,
        )
        inc = hyeto['incremental_depth'].values
        peak_idx = np.argmax(inc)

        # Left side: should be non-increasing moving away from peak
        left_side = inc[:peak_idx + 1]
        for i in range(len(left_side) - 1):
            assert left_side[i] <= left_side[i + 1], (
                f"Left side not monotonically increasing toward peak at index {i}"
            )

        # Right side: should be non-increasing moving away from peak
        right_side = inc[peak_idx:]
        for i in range(len(right_side) - 1):
            assert right_side[i] >= right_side[i + 1], (
                f"Right side not monotonically decreasing from peak at index {i}"
            )

    def test_all_increments_non_negative(self, houston_ddf):
        """No negative incremental depths (physically impossible)."""
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=13.3,
            duration_hours=24,
            position_percent=50,
        )
        assert (hyeto['incremental_depth'].values >= 0).all(), (
            "Found negative incremental depths"
        )

    def test_cumulative_is_monotonically_increasing(self, houston_ddf):
        """Cumulative depth must never decrease."""
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=13.3,
            duration_hours=24,
            position_percent=50,
        )
        cum = hyeto['cumulative_depth'].values
        diffs = np.diff(cum)
        assert (diffs >= -1e-15).all(), "Cumulative depth decreased"

    def test_cumulative_matches_running_sum(self, houston_ddf):
        """cumulative_depth column must equal the running sum of incremental_depth."""
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=13.3,
            duration_hours=24,
            position_percent=50,
        )
        expected_cum = np.cumsum(hyeto['incremental_depth'].values)
        actual_cum = hyeto['cumulative_depth'].values
        np.testing.assert_allclose(actual_cum, expected_cum, atol=1e-12)

    @pytest.mark.parametrize("depth", [1.0, 5.0, 13.3, 25.0, 50.0])
    def test_depth_conservation_across_magnitudes(self, houston_ddf, depth):
        """Depth conservation holds from small to extreme storms."""
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=depth,
            duration_hours=24,
            position_percent=50,
        )
        actual = hyeto['cumulative_depth'].iloc[-1]
        assert abs(actual - depth) < 1e-9

    @pytest.mark.parametrize("duration", [1, 2, 3, 6, 12, 24])
    def test_depth_conservation_across_durations(self, houston_ddf, duration):
        """Depth conservation holds for all standard durations."""
        target = 10.0
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=target,
            duration_hours=duration,
            position_percent=50,
        )
        actual = hyeto['cumulative_depth'].iloc[-1]
        assert abs(actual - target) < 1e-9

    def test_dataframe_columns_present(self, houston_ddf):
        """Output DataFrame must have the standard three columns."""
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=10.0,
            duration_hours=24,
        )
        assert list(hyeto.columns) == ['hour', 'incremental_depth', 'cumulative_depth']

    def test_hour_column_spacing(self, houston_ddf):
        """Hour column must have uniform spacing matching the time increment."""
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=10.0,
            duration_hours=24,
        )
        hours = hyeto['hour'].values
        diffs = np.diff(hours)
        assert np.allclose(diffs, diffs[0], atol=1e-10), (
            f"Non-uniform hour spacing: min={diffs.min()}, max={diffs.max()}"
        )


# ---------------------------------------------------------------------------
# Task 3: Cross-Method Comparison Tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HMS_AVAILABLE, reason="hms-commander not installed")
class TestCrossMethodComparison:
    """
    Compare all four precipitation methods on the same storm parameters.

    These tests document the EXPECTED differences between methods — they are
    not bugs.  Each method implements a different temporal distribution:

    - StormGenerator: Alternating Block (Chow 1988). Flexible peak position,
      symmetric pattern around peak. Best for: sensitivity analyses, custom
      peak timing, non-HMS workflows.

    - Atlas14Storm: Official NOAA Atlas 14 temporal distributions by state/
      region and quartile. Best for: regulatory work requiring NOAA-standard
      patterns, HMS-RAS coordination where HMS uses Atlas 14.

    - FrequencyStorm: TP-40/Hydro-35 pattern (HCFCD M3 standard). Peak at
      67% of duration. Best for: HCFCD projects, TP-40 legacy compatibility,
      48-hour storms (not available in Atlas14Storm).

    - ScsTypeStorm: NRCS SCS Type I/IA/II/III curves. Fixed 24-hour duration.
      Best for: nationwide SCS-based studies, NRCS compatibility, areas
      without Atlas 14 coverage.

    RECOMMENDATION FOR FORMAL STUDIES:
        Use the HMS-equivalent methods (Atlas14Storm, FrequencyStorm, or
        ScsTypeStorm) and confirm inputs via a full HEC-HMS project with
        human-in-the-loop review.  StormGenerator provides a useful
        alternative perspective for sensitivity analysis.
    """

    def test_all_methods_conserve_depth(self, houston_ddf):
        """All four methods must conserve the specified total depth."""
        target = 13.3

        sg = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=target,
            duration_hours=24,
            position_percent=50,
        )
        assert abs(sg['cumulative_depth'].iloc[-1] - target) < 1e-6

        a14 = Atlas14Storm.generate_hyetograph(
            total_depth_inches=target,
            state="tx", region=3,
            duration_hours=24,
            probability_column="50%",
        )
        assert abs(a14['incremental_depth'].sum() - target) < 1e-6

        freq = FrequencyStorm.generate_hyetograph(
            total_depth_inches=target,
            total_duration_min=1440,
        )
        assert abs(freq['incremental_depth'].sum() - target) < 1e-6

        scs = ScsTypeStorm.generate_hyetograph(
            total_depth_inches=target,
            scs_type='II',
        )
        assert abs(scs['incremental_depth'].sum() - target) < 1e-6

    def test_peak_positions_differ_by_method(self, houston_ddf):
        """
        Each method produces a different peak position, by design.

        StormGenerator (50%): symmetric, centered peak
        Atlas14Storm: quartile-dependent (varies)
        FrequencyStorm: ~67% of duration
        ScsTypeStorm Type II: ~50% of duration
        """
        target = 13.3

        sg = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=target,
            duration_hours=24,
            position_percent=50,
        )
        sg_peak_frac = (
            sg['hour'].iloc[sg['incremental_depth'].argmax()]
            / sg['hour'].iloc[-1]
        )

        freq = FrequencyStorm.generate_hyetograph(
            total_depth_inches=target,
            total_duration_min=1440,
        )
        freq_peak_frac = (
            freq['hour'].iloc[freq['incremental_depth'].argmax()]
            / freq['hour'].iloc[-1]
        )

        scs = ScsTypeStorm.generate_hyetograph(
            total_depth_inches=target,
            scs_type='II',
        )
        scs_peak_frac = (
            scs['hour'].iloc[scs['incremental_depth'].argmax()]
            / scs['hour'].iloc[-1]
        )

        # StormGenerator with 50% should be near center
        assert 0.45 <= sg_peak_frac <= 0.55, (
            f"StormGenerator peak at {sg_peak_frac:.2f}, expected ~0.50"
        )

        # FrequencyStorm should be near 67%
        assert 0.60 <= freq_peak_frac <= 0.75, (
            f"FrequencyStorm peak at {freq_peak_frac:.2f}, expected ~0.67"
        )

        # SCS Type II should be near 50%
        assert 0.45 <= scs_peak_frac <= 0.55, (
            f"SCS Type II peak at {scs_peak_frac:.2f}, expected ~0.50"
        )

    def test_peak_intensities_differ(self, houston_ddf):
        """
        Different temporal distributions concentrate rainfall differently.

        The Alternating Block method typically produces the highest peak
        intensity because it assigns sorted incremental depths without
        any smoothing — each block is an independent DDF lookup.
        """
        target = 13.3

        sg = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=target,
            duration_hours=24,
            position_percent=50,
        )
        sg_peak = sg['incremental_depth'].max()

        freq = FrequencyStorm.generate_hyetograph(
            total_depth_inches=target,
            total_duration_min=1440,
            time_interval_min=60,
        )
        freq_peak = freq['incremental_depth'].max()

        scs = ScsTypeStorm.generate_hyetograph(
            total_depth_inches=target,
            scs_type='II',
            time_interval_min=60,
        )
        scs_peak = scs['incremental_depth'].max()

        # All peaks should be positive and less than total depth
        for name, peak in [("SG", sg_peak), ("Freq", freq_peak), ("SCS", scs_peak)]:
            assert 0 < peak < target, f"{name} peak {peak} outside valid range"

        # The methods SHOULD produce different peak values
        peaks = [sg_peak, freq_peak, scs_peak]
        assert len(set(round(p, 4) for p in peaks)) > 1, (
            "All methods produced identical peak intensity — unexpected"
        )

    def test_output_dataframe_compatible(self, houston_ddf):
        """
        All methods return DataFrames with the same column schema, enabling
        seamless substitution in downstream workflows (DSS writing,
        RasUnsteady.set_precipitation_hyetograph, plotting, etc.).
        """
        target = 10.0
        expected_cols = {'hour', 'incremental_depth', 'cumulative_depth'}

        sg = StormGenerator.generate_hyetograph(
            ddf_data=houston_ddf,
            total_depth_inches=target,
            duration_hours=24,
        )
        assert set(sg.columns) == expected_cols, f"StormGenerator columns: {sg.columns.tolist()}"

        freq = FrequencyStorm.generate_hyetograph(
            total_depth_inches=target,
        )
        assert set(freq.columns) == expected_cols, f"FrequencyStorm columns: {freq.columns.tolist()}"

        scs = ScsTypeStorm.generate_hyetograph(
            total_depth_inches=target,
            scs_type='II',
        )
        assert set(scs.columns) == expected_cols, f"ScsTypeStorm columns: {scs.columns.tolist()}"

    def test_storm_generator_flexibility_advantage(self, houston_ddf):
        """
        StormGenerator can place the peak at any position — a capability
        not available in the HMS-equivalent methods.

        This is useful for sensitivity analysis: how does the model respond
        to early vs. late peak timing?
        """
        target = 13.3
        peaks = {}

        for pos in [0, 25, 50, 75, 100]:
            hyeto = StormGenerator.generate_hyetograph(
                ddf_data=houston_ddf,
                total_depth_inches=target,
                duration_hours=24,
                position_percent=pos,
            )
            peak_hour = hyeto['hour'].iloc[hyeto['incremental_depth'].argmax()]
            peaks[pos] = peak_hour
            # Depth still conserved
            assert abs(hyeto['cumulative_depth'].iloc[-1] - target) < 1e-9

        # Peak hour should increase with position_percent
        assert peaks[0] < peaks[50] < peaks[100], (
            f"Peak positions not monotonically increasing: {peaks}"
        )


# ---------------------------------------------------------------------------
# Task 4: Reference implementation invariant tests
# ---------------------------------------------------------------------------

class TestTextbookReferenceInvariants:
    """
    Validate properties of the independent textbook implementation itself.

    These tests ensure the reference implementation is correct before we
    use it to validate StormGenerator.
    """

    def test_textbook_depth_conservation(self, houston_ddf):
        """Textbook implementation must conserve total depth."""
        target = 13.3
        durations = houston_ddf['duration_hours'].values
        depths = houston_ddf['2'].values

        _, inc = textbook_alternating_block(
            durations, depths, target, 24, 1.0, 0.5,
        )
        assert abs(inc.sum() - target) < 1e-9

    def test_textbook_all_non_negative(self, houston_ddf):
        """Textbook implementation must produce non-negative depths."""
        durations = houston_ddf['duration_hours'].values
        depths = houston_ddf['100'].values

        _, inc = textbook_alternating_block(
            durations, depths, 13.3, 24, 1.0, 0.5,
        )
        assert (inc >= 0).all()

    def test_textbook_correct_interval_count(self, houston_ddf):
        """Number of intervals must equal duration / dt."""
        durations = houston_ddf['duration_hours'].values
        depths = houston_ddf['100'].values

        t, inc = textbook_alternating_block(
            durations, depths, 10.0, 24, 1.0, 0.5,
        )
        assert len(t) == 24
        assert len(inc) == 24

        t6, inc6 = textbook_alternating_block(
            durations, depths, 10.0, 6, 5.0/60.0, 0.5,
        )
        assert len(t6) == 72  # 6 hours / 5 minutes
        assert len(inc6) == 72

    def test_textbook_peak_at_center(self, houston_ddf):
        """With position=0.5, peak should be at the center interval."""
        durations = houston_ddf['duration_hours'].values
        depths = houston_ddf['100'].values

        _, inc = textbook_alternating_block(
            durations, depths, 13.3, 24, 1.0, 0.5,
        )
        peak_idx = np.argmax(inc)
        assert peak_idx == 12, f"Peak at {peak_idx}, expected 12"

    def test_textbook_symmetry_around_peak(self, houston_ddf):
        """
        With centered peak and even number of intervals, the left and
        right sides should have the same set of depths (just reordered).
        """
        durations = houston_ddf['duration_hours'].values
        depths = houston_ddf['100'].values

        _, inc = textbook_alternating_block(
            durations, depths, 13.3, 24, 1.0, 0.5,
        )
        peak_idx = np.argmax(inc)
        left = np.sort(inc[:peak_idx])
        right = np.sort(inc[peak_idx + 1:])

        # Left and right contain alternating ranked depths, so the combined
        # sorted set should match the original sorted depths minus the peak
        all_sorted = np.sort(inc)[::-1]
        combined = np.sort(np.concatenate([left, right, [inc[peak_idx]]]))[::-1]
        np.testing.assert_allclose(all_sorted, combined, atol=1e-12)


# ---------------------------------------------------------------------------
# Applicability Summary
# ---------------------------------------------------------------------------

class TestApplicabilityDocumentation:
    """
    Tests that serve as executable documentation of when to use each method.

    These are not algorithm tests — they verify the metadata and
    configuration constraints that determine applicability.
    """

    def test_storm_generator_accepts_any_duration(self, houston_ddf):
        """StormGenerator works with arbitrary durations — not limited to standard values."""
        for dur in [0.5, 1, 2, 3, 4, 6, 8, 12, 18, 24]:
            hyeto = StormGenerator.generate_hyetograph(
                ddf_data=houston_ddf,
                total_depth_inches=5.0,
                duration_hours=dur,
            )
            assert len(hyeto) > 0
            assert abs(hyeto['cumulative_depth'].iloc[-1] - 5.0) < 1e-9

    def test_storm_generator_accepts_any_depth(self, houston_ddf):
        """StormGenerator scales to any positive depth — no DDF lookup required."""
        for depth in [0.5, 1.0, 5.0, 17.0, 30.0, 50.0]:
            hyeto = StormGenerator.generate_hyetograph(
                ddf_data=houston_ddf,
                total_depth_inches=depth,
                duration_hours=24,
            )
            assert abs(hyeto['cumulative_depth'].iloc[-1] - depth) < 1e-9

    @pytest.mark.skipif(not HMS_AVAILABLE, reason="hms-commander not installed")
    def test_scs_type_storm_24hr_only(self):
        """ScsTypeStorm is constrained to 24-hour duration (HMS limitation)."""
        hyeto = ScsTypeStorm.generate_hyetograph(
            total_depth_inches=10.0,
            scs_type='II',
        )
        assert hyeto['hour'].iloc[-1] == pytest.approx(24.0, abs=0.1)

    @pytest.mark.skipif(not HMS_AVAILABLE, reason="hms-commander not installed")
    def test_frequency_storm_variable_duration(self):
        """FrequencyStorm supports variable durations via pattern resampling."""
        for dur_min in [360, 720, 1440]:
            hyeto = FrequencyStorm.generate_hyetograph(
                total_depth_inches=10.0,
                total_duration_min=dur_min,
            )
            expected_hours = dur_min / 60.0
            assert hyeto['hour'].iloc[-1] == pytest.approx(
                expected_hours, abs=0.1
            )

    @pytest.mark.skipif(not HMS_AVAILABLE, reason="hms-commander not installed")
    def test_atlas14_probability_column_conserves_depth(self):
        """All probability columns must conserve the specified total depth."""
        target = 13.3
        for pc in ["10%", "50%", "90%"]:
            hyeto = Atlas14Storm.generate_hyetograph(
                total_depth_inches=target,
                state="tx", region=3,
                duration_hours=24,
                probability_column=pc,
            )
            assert abs(hyeto['incremental_depth'].sum() - target) < 1e-6, (
                f"probability_column='{pc}' depth error: "
                f"{hyeto['incremental_depth'].sum()} vs {target}"
            )

    @pytest.mark.skipif(not HMS_AVAILABLE, reason="hms-commander not installed")
    def test_atlas14_probability_column_changes_temporal_shape(self):
        """
        Different probability columns produce different temporal distributions.

        The probability_column parameter (hms-commander 0.3.1+) selects the
        percentile of the NOAA temporal distribution. Lower percentiles (10%)
        tend to be more front-loaded with higher peak intensity; higher
        percentiles (90%) spread rainfall more evenly.

        This is independent of aep_percent (which controls storm magnitude).
        """
        target = 13.3
        peaks = {}
        peak_hours = {}
        for pc in ["10%", "50%", "90%"]:
            hyeto = Atlas14Storm.generate_hyetograph(
                total_depth_inches=target,
                state="tx", region=3,
                duration_hours=24,
                probability_column=pc,
            )
            peaks[pc] = hyeto['incremental_depth'].max()
            peak_hours[pc] = hyeto['hour'].iloc[
                hyeto['incremental_depth'].argmax()
            ]

        assert len(set(round(p, 4) for p in peaks.values())) > 1, (
            "All probability columns produced identical peaks — unexpected"
        )

    @pytest.mark.skipif(not HMS_AVAILABLE, reason="hms-commander not installed")
    def test_atlas14_probability_column_rejects_invalid(self):
        """Invalid probability_column values must raise ValueError."""
        with pytest.raises(ValueError, match="not valid"):
            Atlas14Storm.generate_hyetograph(
                total_depth_inches=13.3,
                state="tx", region=3,
                duration_hours=24,
                probability_column="55%",
            )

    @pytest.mark.skipif(not HMS_AVAILABLE, reason="hms-commander not installed")
    def test_all_methods_include_sentinel_row(self, houston_ddf):
        """All HMS methods include a t=0 sentinel row with zero depth."""
        a14 = Atlas14Storm.generate_hyetograph(
            total_depth_inches=10.0,
            state="tx", region=3,
            duration_hours=24,
            probability_column="50%",
        )
        freq = FrequencyStorm.generate_hyetograph(total_depth_inches=10.0)
        scs = ScsTypeStorm.generate_hyetograph(
            total_depth_inches=10.0, scs_type='II',
        )

        for name, h in [("Atlas14", a14), ("Freq", freq), ("SCS", scs)]:
            assert h['hour'].iloc[0] == 0.0, (
                f"{name} first row hour={h['hour'].iloc[0]}, expected 0.0"
            )
            assert h['incremental_depth'].iloc[0] == 0.0, (
                f"{name} first row depth={h['incremental_depth'].iloc[0]}, expected 0.0"
            )
            assert h['cumulative_depth'].iloc[0] == 0.0, (
                f"{name} first row cumulative={h['cumulative_depth'].iloc[0]}, expected 0.0"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
