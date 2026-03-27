"""
Regression tests for the shipped USGS Phase 4 metric surface.

These tests codify the Phase 4 public API actually implemented in
``ras_commander.usgs.metrics`` and re-exported from ``ras_commander.usgs``:

- ``stage_to_depth()``
- ``calculate_stage_metrics()``
- ``normalized_rmse()``
- ``classify_performance_full()``
"""

import numpy as np
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
            'classify_performance_full',
        }

        assert expected.issubset(set(usgs.__all__))

    def test_phase4_metrics_import_from_package(self):
        """Package-level imports should expose the implemented metric helpers."""
        assert callable(usgs.stage_to_depth)
        assert callable(usgs.calculate_stage_metrics)
        assert callable(usgs.normalized_rmse)
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
        assert metrics['nrmse_peak'] == pytest.approx(
            usgs.normalized_rmse(observed, modeled, normalization='peak')
        )
        assert metrics['performance_rating_full'] == usgs.classify_performance_full(metrics)
