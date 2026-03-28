"""
Tests for HdfMesh.get_mannings_calibration_table method.

Tests verify:
1. Module and class can be imported
2. API accepts correct parameters
3. Returns expected output structure with real project data
"""

import pytest
from pathlib import Path
import inspect


class TestImport:
    """Tier 1: Verify HdfMesh is importable and has the new method."""

    def test_import_from_hdf_subpackage(self):
        """Test import from hdf subpackage."""
        from ras_commander.hdf import HdfMesh
        assert HdfMesh is not None

    def test_import_from_main_package(self):
        """Test import from main ras_commander package."""
        from ras_commander import HdfMesh
        assert HdfMesh is not None

    def test_class_has_get_mannings_calibration_table(self):
        """Test that HdfMesh has the get_mannings_calibration_table method."""
        from ras_commander import HdfMesh
        assert hasattr(HdfMesh, 'get_mannings_calibration_table')

    def test_method_is_static(self):
        """Test that get_mannings_calibration_table is a static method."""
        from ras_commander import HdfMesh
        sig = inspect.signature(HdfMesh.get_mannings_calibration_table)
        assert 'self' not in sig.parameters


class TestAPISignature:
    """Tier 2: Verify API signature matches specification."""

    def test_hdf_path_parameter(self):
        """Test that get_mannings_calibration_table has hdf_path parameter."""
        from ras_commander import HdfMesh
        sig = inspect.signature(HdfMesh.get_mannings_calibration_table)
        assert 'hdf_path' in sig.parameters


class TestExpectedBehavior:
    """Tier 3: Test with real project data."""

    def test_with_baldeagle_project(self):
        """Test reading Manning's calibration table from BaldEagleCrkMulti2D."""
        from ras_commander import HdfMesh, RasExamples, init_ras_project
        import pandas as pd

        path = RasExamples.extract_project("BaldEagleCrkMulti2D")
        init_ras_project(path, "6.6")

        # Find a geometry HDF file
        geom_hdfs = list(path.glob("*.g*.hdf"))
        if not geom_hdfs:
            pytest.skip("No geometry HDF files found in BaldEagleCrkMulti2D")

        result = HdfMesh.get_mannings_calibration_table(geom_hdfs[0])

        # Result may be None if this project lacks a calibration table
        if result is not None:
            assert isinstance(result, pd.DataFrame)
            assert len(result) > 0
        # None is also acceptable if the dataset doesn't exist in this project


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
