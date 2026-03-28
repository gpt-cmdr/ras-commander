"""
Tests for HdfInfiltration infiltration region methods.

Tests verify:
1. Module and class can be imported with all 3 new methods
2. API accepts correct parameters
3. Returns expected output (None/empty) for projects without infiltration regions
"""

import pytest
from pathlib import Path
import inspect


class TestImport:
    """Tier 1: Verify HdfInfiltration is importable and has all new methods."""

    def test_import_from_hdf_subpackage(self):
        """Test import from hdf subpackage."""
        from ras_commander.hdf import HdfInfiltration
        assert HdfInfiltration is not None

    def test_import_from_main_package(self):
        """Test import from main ras_commander package."""
        from ras_commander import HdfInfiltration
        assert HdfInfiltration is not None

    def test_has_get_infiltration_region_names(self):
        """Test that HdfInfiltration has get_infiltration_region_names."""
        from ras_commander import HdfInfiltration
        assert hasattr(HdfInfiltration, 'get_infiltration_region_names')

    def test_has_get_infiltration_calibration_regions(self):
        """Test that HdfInfiltration has get_infiltration_calibration_regions."""
        from ras_commander import HdfInfiltration
        assert hasattr(HdfInfiltration, 'get_infiltration_calibration_regions')

    def test_has_get_infiltration_region_polygons(self):
        """Test that HdfInfiltration has get_infiltration_region_polygons."""
        from ras_commander import HdfInfiltration
        assert hasattr(HdfInfiltration, 'get_infiltration_region_polygons')

    def test_region_names_is_static(self):
        """Test that get_infiltration_region_names is a static method."""
        from ras_commander import HdfInfiltration
        sig = inspect.signature(HdfInfiltration.get_infiltration_region_names)
        assert 'self' not in sig.parameters

    def test_calibration_regions_is_static(self):
        """Test that get_infiltration_calibration_regions is a static method."""
        from ras_commander import HdfInfiltration
        sig = inspect.signature(HdfInfiltration.get_infiltration_calibration_regions)
        assert 'self' not in sig.parameters

    def test_region_polygons_is_static(self):
        """Test that get_infiltration_region_polygons is a static method."""
        from ras_commander import HdfInfiltration
        sig = inspect.signature(HdfInfiltration.get_infiltration_region_polygons)
        assert 'self' not in sig.parameters


class TestAPISignature:
    """Tier 2: Verify API signatures match specification."""

    def test_region_names_hdf_path_parameter(self):
        """Test that get_infiltration_region_names has hdf_path parameter."""
        from ras_commander import HdfInfiltration
        sig = inspect.signature(HdfInfiltration.get_infiltration_region_names)
        assert 'hdf_path' in sig.parameters

    def test_calibration_regions_hdf_path_parameter(self):
        """Test that get_infiltration_calibration_regions has hdf_path parameter."""
        from ras_commander import HdfInfiltration
        sig = inspect.signature(HdfInfiltration.get_infiltration_calibration_regions)
        assert 'hdf_path' in sig.parameters

    def test_region_polygons_hdf_path_parameter(self):
        """Test that get_infiltration_region_polygons has hdf_path parameter."""
        from ras_commander import HdfInfiltration
        sig = inspect.signature(HdfInfiltration.get_infiltration_region_polygons)
        assert 'hdf_path' in sig.parameters


class TestExpectedBehavior:
    """Tier 3: Verify None/empty returns for projects without infiltration regions."""

    def test_region_names_returns_none_without_infiltration(self):
        """Test that get_infiltration_region_names returns None for project without infiltration."""
        from ras_commander import HdfInfiltration, RasExamples, init_ras_project

        path = RasExamples.extract_project("Muncie")
        init_ras_project(path, "6.6")

        geom_hdfs = list(path.glob("*.g*.hdf"))
        if not geom_hdfs:
            pytest.skip("No geometry HDF files found in Muncie")

        result = HdfInfiltration.get_infiltration_region_names(geom_hdfs[0])
        # Muncie typically has no infiltration regions
        assert result is None or result == []

    def test_calibration_regions_returns_none_without_infiltration(self):
        """Test that get_infiltration_calibration_regions returns None for project without infiltration."""
        from ras_commander import HdfInfiltration, RasExamples, init_ras_project

        path = RasExamples.extract_project("Muncie")
        init_ras_project(path, "6.6")

        geom_hdfs = list(path.glob("*.g*.hdf"))
        if not geom_hdfs:
            pytest.skip("No geometry HDF files found in Muncie")

        result = HdfInfiltration.get_infiltration_calibration_regions(geom_hdfs[0])
        assert result is None or result == {}

    def test_region_polygons_returns_empty_gdf_without_infiltration(self):
        """Test that get_infiltration_region_polygons returns empty GeoDataFrame for project without infiltration."""
        from ras_commander import HdfInfiltration, RasExamples, init_ras_project
        import geopandas as gpd

        path = RasExamples.extract_project("Muncie")
        init_ras_project(path, "6.6")

        geom_hdfs = list(path.glob("*.g*.hdf"))
        if not geom_hdfs:
            pytest.skip("No geometry HDF files found in Muncie")

        result = HdfInfiltration.get_infiltration_region_polygons(geom_hdfs[0])
        assert isinstance(result, gpd.GeoDataFrame)
        assert len(result) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
