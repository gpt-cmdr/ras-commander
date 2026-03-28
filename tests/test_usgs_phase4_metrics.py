"""
Regression tests for the USGS Phase 4 metric surface.

These tests codify the Phase 4 public API implemented in
``ras_commander.usgs.metrics`` and re-exported from ``ras_commander.usgs``.
The original feature surface includes:

- ``stage_to_depth()``
- ``calculate_stage_metrics()``
- ``normalized_rmse()``
- ``nrmse_depth_normalized()``
- ``flow_weighted_rmse()``
- ``fdc_high_flow_bias()``
- ``baseflow_nse()``
- ``rising_limb_timing_error()``
- ``recession_bias()``
- ``classify_performance_full()``
"""

import numpy as np
import pandas as pd
import pytest

import ras_commander.usgs as usgs
from ras_commander.usgs.metrics import RasUsgsMetrics


class TestUsgsPhase4Exports:
    """Verify the shipped Phase 4 public API surface."""

    def test_phase4_metric_names_in___all__(self):
        """Phase 4 metric names should remain in the package export list."""
        expected = {
            'stage_to_depth',
            'calculate_stage_metrics',
            'normalized_rmse',
            'nrmse_depth_normalized',
            'flow_weighted_rmse',
            'fdc_high_flow_bias',
            'baseflow_nse',
            'rising_limb_timing_error',
            'recession_bias',
            'classify_performance_full',
        }

        assert expected.issubset(set(usgs.__all__))

    def test_phase4_metrics_import_from_package(self):
        """Package-level imports should expose the implemented metric helpers."""
        assert callable(usgs.stage_to_depth)
        assert callable(usgs.calculate_stage_metrics)
        assert callable(usgs.normalized_rmse)
        assert callable(usgs.nrmse_depth_normalized)
        assert callable(usgs.flow_weighted_rmse)
        assert callable(usgs.fdc_high_flow_bias)
        assert callable(usgs.baseflow_nse)
        assert callable(usgs.rising_limb_timing_error)
        assert callable(usgs.recession_bias)
        assert callable(usgs.classify_performance_full)


class TestUsgsPhase4Behavior:
    """Verify basic behavior for the implemented Phase 4 metrics."""

    def test_stage_to_depth_uses_minimum_observed_stage_by_default(self):
        """Default datum should fall back to the minimum valid stage value."""
        stage = np.array([100.0, 101.0, 102.0], dtype=float)

        depth, datum = usgs.stage_to_depth(stage)

        assert datum == pytest.approx(100.0)
        assert depth.tolist() == pytest.approx([0.0, 1.0, 2.0])

    def test_calculate_stage_metrics_returns_depth_based_metrics(self):
        """Depth-based metrics should be computed from a shared datum."""
        observed_stage = np.array([100.0, 101.0, 102.0], dtype=float)
        modeled_stage = np.array([100.0, 101.5, 101.5], dtype=float)

        metrics = usgs.calculate_stage_metrics(observed_stage, modeled_stage)

        assert metrics['datum'] == pytest.approx(100.0)
        assert metrics['rmse_depth'] == pytest.approx(np.sqrt(1.0 / 6.0))
        assert metrics['pbias_depth'] == pytest.approx(0.0)
        assert metrics['mean_obs_depth'] == pytest.approx(1.0)
        assert metrics['nrmse_depth'] == pytest.approx(np.sqrt(1.0 / 6.0))

    def test_normalized_rmse_supports_peak_normalization(self):
        """Peak normalization should match RMSE divided by peak observed."""
        observed = np.array([1.0, 2.0, 4.0], dtype=float)
        modeled = np.array([1.0, 3.0, 5.0], dtype=float)

        result = usgs.normalized_rmse(observed, modeled, normalization='peak')

        expected_rmse = np.sqrt(2.0 / 3.0)
        assert result == pytest.approx(expected_rmse / 4.0)

    def test_nrmse_depth_normalized_matches_stage_metric_output(self):
        """Named wrapper should match the stage-metric dictionary output."""
        observed_stage = np.array([100.0, 101.0, 102.0], dtype=float)
        modeled_stage = np.array([100.0, 101.5, 101.5], dtype=float)

        result = usgs.nrmse_depth_normalized(observed_stage, modeled_stage)
        stage_metrics = usgs.calculate_stage_metrics(observed_stage, modeled_stage)

        assert result == pytest.approx(stage_metrics['nrmse_depth'])

    def test_flow_weighted_rmse_emphasizes_peak_errors(self):
        """High-flow weighting should exceed standard RMSE when peaks miss."""
        observed = np.array([1.0, 1.0, 10.0], dtype=float)
        modeled = np.array([1.0, 1.0, 8.0], dtype=float)

        standard_rmse = np.sqrt(np.mean((observed - modeled) ** 2))
        weighted_rmse = usgs.flow_weighted_rmse(observed, modeled)

        assert weighted_rmse > standard_rmse

    def test_fdc_high_flow_bias_uses_sorted_high_flow_fdc_segment(self):
        """FDC high-flow bias should align with FHV-style ranking logic."""
        observed = np.array([10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
        modeled = np.array([12.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0])

        result = usgs.fdc_high_flow_bias(
            observed,
            modeled,
            high_flow_exceedance=0.2
        )

        expected = 100.0 * ((12.0 + 9.0) - (10.0 + 9.0)) / (10.0 + 9.0)
        assert result == pytest.approx(expected)

    def test_baseflow_nse_returns_perfect_fit_for_identical_series(self):
        """Baseflow NSE should be perfect when observed and modeled match."""
        observed = np.array([2.0, 3.0, 8.0, 4.0, 3.0, 2.5], dtype=float)

        result = usgs.baseflow_nse(observed, observed)

        assert result == pytest.approx(1.0)

    def test_baseflow_nse_accepts_explicit_timestep_configuration(self):
        """The separation assumptions should be explicit and configurable."""
        observed = np.array([2.0, 3.0, 8.0, 4.0, 3.0, 2.5], dtype=float)

        result = usgs.baseflow_nse(
            observed,
            observed,
            alpha=0.925,
            passes=3,
            timestep_hours=0.25,
            alpha_reference_timestep_hours=1.0
        )

        assert result == pytest.approx(1.0)

    def test_rising_limb_timing_error_is_zero_for_identical_hydrographs(self):
        """Identical rising limbs should have zero timing error."""
        observed = np.array([1.0, 2.0, 4.0, 8.0, 6.0], dtype=float)
        time_index = pd.date_range('2024-01-01', periods=5, freq='h')

        result = usgs.rising_limb_timing_error(
            observed,
            observed,
            time_index=time_index
        )

        assert result == pytest.approx(0.0)

    def test_recession_bias_uses_post_peak_non_increasing_segment(self):
        """Recession bias should be computed on the recession limb only."""
        observed = np.array([1.0, 3.0, 5.0, 4.0, 2.0], dtype=float)
        modeled = np.array([1.0, 3.0, 5.0, 5.0, 3.0], dtype=float)

        result = usgs.recession_bias(observed, modeled)

        assert result == pytest.approx((2.0 / 11.0) * 100.0)
    def test_classify_performance_full_uses_three_criterion_thresholds(self):
        """Full performance classification should honor NSE, RSR, and PBIAS."""
        assert usgs.classify_performance_full(
            {'nse': 0.80, 'rsr': 0.40, 'pbias': 5.0}
        ) == 'Very Good'
        assert usgs.classify_performance_full(
            {'nse': 0.70, 'rsr': 0.55, 'pbias': 14.0}
        ) == 'Good'
        assert usgs.classify_performance_full(
            {'nse': 0.60, 'rsr': 0.65, 'pbias': 20.0}
        ) == 'Satisfactory'
        assert usgs.classify_performance_full(
            {'nse': 0.40, 'rsr': 0.40, 'pbias': 5.0}
        ) == 'Unsatisfactory'

    def test_calculate_all_metrics_includes_phase4_outputs(self):
        """The aggregate metric report should include integrated Phase 4 outputs."""
        observed = np.arange(1.0, 11.0, dtype=float)
        modeled = observed * 1.05

        metrics = RasUsgsMetrics.calculate_all_metrics(observed, modeled)

        assert 'nrmse_peak' in metrics
        assert 'performance_rating_full' in metrics
        assert 'flow_weighted_rmse' in metrics
        assert 'fdc_high_flow_bias' in metrics
        assert 'baseflow_nse' in metrics
        assert 'recession_bias' in metrics
        assert metrics['nrmse_peak'] == pytest.approx(
            usgs.normalized_rmse(observed, modeled, normalization='peak')
        )
        assert metrics['performance_rating_full'] == usgs.classify_performance_full(metrics)

    def test_calculate_all_metrics_includes_time_dependent_phase4_outputs(self):
        """Time-aware aggregate metrics should include timing/frequency outputs."""
        time_index = pd.date_range('2020-01-01', periods=48, freq='30D')
        observed = np.linspace(1.0, 20.0, len(time_index))
        modeled = observed * 1.05

        metrics = RasUsgsMetrics.calculate_all_metrics(
            observed,
            modeled,
            time_index=time_index
        )

        assert 'rising_limb_timing_error' in metrics
