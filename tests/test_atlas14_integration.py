"""
Integration tests for Atlas14Storm from hms-commander.

Tests verify that:
1. Atlas14Storm can be imported from ras_commander.precip
2. Basic hyetograph generation works
3. Depth conservation is maintained (HMS equivalence)
4. ATLAS14_AVAILABLE flag works correctly
"""

import pytest
import numpy as np
import pandas as pd


class TestAtlas14Import:
    """Test Atlas14Storm import from ras_commander.precip."""

    def test_import_availability_flag(self):
        """Test that ATLAS14_AVAILABLE flag is exposed."""
        from ras_commander.precip import ATLAS14_AVAILABLE
        assert isinstance(ATLAS14_AVAILABLE, bool)

    def test_import_atlas14storm(self):
        """Test that Atlas14Storm can be imported."""
        from ras_commander.precip import Atlas14Storm, ATLAS14_AVAILABLE

        if ATLAS14_AVAILABLE:
            assert Atlas14Storm is not None
            assert hasattr(Atlas14Storm, 'generate_hyetograph')
        else:
            # If hms-commander not installed, Atlas14Storm should be None
            assert Atlas14Storm is None

    def test_import_atlas14config(self):
        """Test that Atlas14Config can be imported."""
        from ras_commander.precip import Atlas14Config, ATLAS14_AVAILABLE

        if ATLAS14_AVAILABLE:
            assert Atlas14Config is not None
        else:
            assert Atlas14Config is None


@pytest.mark.skipif(
    not __import__('ras_commander.precip', fromlist=['ATLAS14_AVAILABLE']).ATLAS14_AVAILABLE,
    reason="hms-commander not installed"
)
class TestAtlas14Generation:
    """Test Atlas14Storm hyetograph generation."""

    def test_basic_generation(self):
        """Test basic hyetograph generation for Texas region 3."""
        from ras_commander.precip import Atlas14Storm

        # Generate 100-year, 24-hour storm for Houston, TX
        hyeto = Atlas14Storm.generate_hyetograph(
            total_depth_inches=17.9,
            state="tx",
            region=3,
            aep_percent=1.0
        )

        assert hyeto is not None
        assert len(hyeto) > 0
        assert isinstance(hyeto, pd.DataFrame)
        assert 'incremental_depth' in hyeto.columns

    def test_depth_conservation(self):
        """Test that total depth is exactly conserved (HMS equivalence proof)."""
        from ras_commander.precip import Atlas14Storm

        test_depth = 10.0

        hyeto = Atlas14Storm.generate_hyetograph(
            total_depth_inches=test_depth,
            state="tx",
            region=3,
            aep_percent=1.0
        )

        # HMS equivalence requires 10^-6 precision
        total = hyeto['incremental_depth'].sum()
        assert abs(total - test_depth) < 1e-6, \
            f"Depth conservation failed: expected {test_depth}, got {total}"

    def test_non_negative_values(self):
        """Test that all hyetograph values are non-negative."""
        from ras_commander.precip import Atlas14Storm

        hyeto = Atlas14Storm.generate_hyetograph(
            total_depth_inches=5.0,
            state="tx",
            region=3,
            aep_percent=10.0
        )

        assert (hyeto['incremental_depth'] >= 0).all(), "Hyetograph contains negative values"

    def test_different_quartiles(self):
        """Test generation with different quartiles."""
        from ras_commander.precip import Atlas14Storm

        # Atlas14Storm uses proper capitalized quartile names
        quartiles = [
            "First Quartile",
            "Second Quartile",
            "Third Quartile",
            "Fourth Quartile",
            "All Cases"
        ]
        test_depth = 8.5

        for quartile in quartiles:
            hyeto = Atlas14Storm.generate_hyetograph(
                total_depth_inches=test_depth,
                state="tx",
                region=3,
                aep_percent=2.0,
                quartile=quartile
            )

            assert hyeto is not None, f"Generation failed for quartile: {quartile}"
            total = hyeto['incremental_depth'].sum()
            assert abs(total - test_depth) < 1e-6, \
                f"Depth conservation failed for quartile {quartile}"


@pytest.mark.skipif(
    not __import__('ras_commander.precip', fromlist=['ATLAS14_AVAILABLE']).ATLAS14_AVAILABLE,
    reason="hms-commander not installed"
)
class TestAtlas14Config:
    """Test Atlas14Config dataclass functionality."""

    def test_config_creation(self):
        """Test that Atlas14Config can be instantiated."""
        from ras_commander.precip import Atlas14Config

        # Atlas14Config has: state, region, duration (not duration_hours, no aep_percent)
        config = Atlas14Config(
            state="tx",
            region=3,
            duration=24
        )

        assert config.state == "tx"
        assert config.region == 3
        assert config.duration == 24
        # Verify URL property works
        assert "tx_3_24h_temporal.csv" in config.url


class TestStormGeneratorCoexistence:
    """Test that StormGenerator still works alongside Atlas14Storm."""

    def test_storm_generator_import(self):
        """Test that StormGenerator can still be imported."""
        from ras_commander.precip import StormGenerator

        assert StormGenerator is not None
        # StormGenerator is an instantiated class, not static
        assert hasattr(StormGenerator, 'download_from_coordinates') or \
               hasattr(StormGenerator, 'generate_hyetograph')

    def test_both_available(self):
        """Test that both methods are available in __all__."""
        from ras_commander.precip import __all__

        assert 'StormGenerator' in __all__
        assert 'Atlas14Storm' in __all__
        assert 'ATLAS14_AVAILABLE' in __all__


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
