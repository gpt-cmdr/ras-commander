"""
Tests for StormGenerator static class pattern conversion.

This test file validates the v0.88.0 conversion of StormGenerator
from instance-based to static class pattern.
"""

import warnings
import pytest
import pandas as pd
import numpy as np

from ras_commander.precip import StormGenerator


class TestStormGeneratorStaticPattern:
    """Test that StormGenerator follows the static class pattern."""

    def test_methods_are_static(self):
        """All public methods should be static."""
        static_methods = [
            'download_from_coordinates',
            'generate_hyetograph',
            'load_csv',
            'validate_hyetograph',
            'generate_all',
            'save_hyetograph',
            'plot_hyetographs',
            'parse_duration',
            'interpolate_depths',
            'compute_incremental_depths',
        ]

        for method_name in static_methods:
            assert isinstance(
                StormGenerator.__dict__[method_name],
                staticmethod
            ), f"{method_name} should be a staticmethod"

    def test_deprecation_warning_on_init(self):
        """Instantiating StormGenerator should emit DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            gen = StormGenerator()

            assert len(w) == 1, "Should have exactly one warning"
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()
            assert "v0.89.0" in str(w[0].message)

    def test_generate_hyetograph_signature(self):
        """generate_hyetograph should have ddf_data as first parameter."""
        import inspect
        sig = inspect.signature(StormGenerator.generate_hyetograph)
        params = list(sig.parameters.keys())

        assert params[0] == 'ddf_data', \
            f"First parameter should be ddf_data, got {params[0]}"
        assert 'total_depth_inches' in params
        assert 'duration_hours' in params
        assert 'position_percent' in params


class TestStormGeneratorFunctionality:
    """Test that StormGenerator functionality works with static pattern."""

    @pytest.fixture
    def sample_ddf_data(self):
        """Create sample DDF data for testing."""
        # Create a simple DDF dataframe
        durations = [1, 2, 3, 6, 12, 24]
        data = {
            'duration_hours': durations,
            '5': [1.0, 1.3, 1.5, 2.0, 2.5, 3.0],
            '10': [1.2, 1.5, 1.8, 2.4, 3.0, 3.6],
            '25': [1.5, 1.9, 2.2, 2.9, 3.6, 4.3],
            '50': [1.7, 2.2, 2.5, 3.3, 4.1, 4.9],
            '100': [2.0, 2.5, 2.9, 3.8, 4.7, 5.6],
        }
        df = pd.DataFrame(data)
        df.attrs['metadata'] = {
            'source': 'test',
            'ari_columns': ['5', '10', '25', '50', '100'],
            'durations_hours': durations,
        }
        return df

    def test_generate_hyetograph_static(self, sample_ddf_data):
        """Test hyetograph generation with static method."""
        target_depth = 5.0
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=sample_ddf_data,
            total_depth_inches=target_depth,
            duration_hours=24,
            position_percent=50
        )

        assert isinstance(hyeto, pd.DataFrame)
        assert 'hour' in hyeto.columns
        assert 'incremental_depth' in hyeto.columns
        assert 'cumulative_depth' in hyeto.columns

        # Check depth conservation
        final_depth = hyeto['cumulative_depth'].iloc[-1]
        assert abs(final_depth - target_depth) < 1e-6, \
            f"Depth not conserved: {final_depth} vs {target_depth}"

    def test_validate_hyetograph_static(self, sample_ddf_data):
        """Test hyetograph validation with static method."""
        target_depth = 10.0
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=sample_ddf_data,
            total_depth_inches=target_depth,
            duration_hours=24,
            position_percent=50
        )

        # Should pass validation
        result = StormGenerator.validate_hyetograph(
            hyeto,
            expected_total_depth=target_depth
        )
        assert result is True

    def test_validate_hyetograph_fails_on_mismatch(self, sample_ddf_data):
        """Test that validation fails when depth doesn't match."""
        hyeto = StormGenerator.generate_hyetograph(
            ddf_data=sample_ddf_data,
            total_depth_inches=10.0,
            duration_hours=24,
            position_percent=50
        )

        # Should fail validation with wrong expected depth
        with pytest.raises(ValueError, match="Hyetograph validation failed"):
            StormGenerator.validate_hyetograph(
                hyeto,
                expected_total_depth=20.0  # Wrong depth
            )

    def test_generate_all_static(self, sample_ddf_data):
        """Test batch generation with static method."""
        events = {
            '10yr': {'total_depth_inches': 3.6, 'duration_hours': 24},
            '100yr': {'total_depth_inches': 5.6, 'duration_hours': 24},
        }

        storms = StormGenerator.generate_all(
            ddf_data=sample_ddf_data,
            events=events,
            position_percent=50
        )

        assert len(storms) == 2
        assert '10yr' in storms
        assert '100yr' in storms

        for name, hyeto in storms.items():
            assert hyeto is not None
            expected_depth = events[name]['total_depth_inches']
            actual_depth = hyeto['cumulative_depth'].iloc[-1]
            assert abs(actual_depth - expected_depth) < 1e-6

    def test_parse_duration_static(self):
        """Test duration parsing (already static)."""
        assert StormGenerator.parse_duration("5-min") == pytest.approx(5/60)
        assert StormGenerator.parse_duration("1-hr") == 1.0
        assert StormGenerator.parse_duration("24-hr") == 24.0
        assert StormGenerator.parse_duration("1-day") == 24.0

    def test_different_position_percents(self, sample_ddf_data):
        """Test that different peak positions work."""
        for pos in [0, 25, 50, 75, 100]:
            hyeto = StormGenerator.generate_hyetograph(
                ddf_data=sample_ddf_data,
                total_depth_inches=5.0,
                duration_hours=24,
                position_percent=pos
            )

            # All should conserve depth
            assert abs(hyeto['cumulative_depth'].iloc[-1] - 5.0) < 1e-6


class TestStormGeneratorErrorHandling:
    """Test error handling in static pattern."""

    def test_generate_hyetograph_no_data(self):
        """Test error when no DDF data provided."""
        with pytest.raises(ValueError, match="No data provided"):
            StormGenerator.generate_hyetograph(
                ddf_data=None,
                total_depth_inches=10.0,
                duration_hours=24
            )

    def test_generate_hyetograph_empty_data(self):
        """Test error when empty DDF data provided."""
        empty_df = pd.DataFrame()
        with pytest.raises(ValueError, match="No data provided"):
            StormGenerator.generate_hyetograph(
                ddf_data=empty_df,
                total_depth_inches=10.0,
                duration_hours=24
            )

    def test_generate_hyetograph_negative_depth(self):
        """Test error when negative depth provided."""
        sample_df = pd.DataFrame({
            'duration_hours': [1, 2, 24],
            '100': [1.0, 1.5, 5.0]
        })
        with pytest.raises(ValueError, match="must be positive"):
            StormGenerator.generate_hyetograph(
                ddf_data=sample_df,
                total_depth_inches=-10.0,
                duration_hours=24
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
