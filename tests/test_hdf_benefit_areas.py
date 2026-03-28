"""
Tests for HdfBenefitAreas module.

Tests verify:
1. Module and class can be imported
2. API accepts correct parameters
3. Returns expected output structure with GeoDataFrames
4. Works with multi-project context (ras_object parameter)

Full integration tests with actual plan execution should be run manually
or in CI/CD with HEC-RAS installed.
"""

import pytest
from pathlib import Path


class TestHdfBenefitAreasImport:
    """Test HdfBenefitAreas can be imported from various locations."""

    def test_import_from_hdf_subpackage(self):
        """Test import from hdf subpackage."""
        from ras_commander.hdf import HdfBenefitAreas
        assert HdfBenefitAreas is not None

    def test_import_from_main_package(self):
        """Test import from main ras_commander package."""
        from ras_commander import HdfBenefitAreas
        assert HdfBenefitAreas is not None

    def test_class_has_expected_methods(self):
        """Test that HdfBenefitAreas has expected public methods."""
        from ras_commander import HdfBenefitAreas

        assert hasattr(HdfBenefitAreas, 'identify_benefit_areas')

        # Should be static method (no self parameter)
        import inspect
        sig = inspect.signature(HdfBenefitAreas.identify_benefit_areas)
        assert 'self' not in sig.parameters


class TestAPISignature:
    """Test API signature matches specification."""

    def test_identify_benefit_areas_parameters(self):
        """Test that identify_benefit_areas has correct parameters."""
        from ras_commander import HdfBenefitAreas
        import inspect

        sig = inspect.signature(HdfBenefitAreas.identify_benefit_areas)
        params = sig.parameters

        # Required parameters
        assert 'existing_hdf_path' in params
        assert 'proposed_hdf_path' in params

        # Optional parameters with defaults
        assert 'min_delta' in params
        assert params['min_delta'].default == 0.1

        assert 'match_precision' in params
        assert params['match_precision'].default == 6

        assert 'adjacency_method' in params
        assert params['adjacency_method'].default == "polygon_edges"

        assert 'dissolve' in params
        assert params['dissolve'].default is True

        # CRITICAL: ras_object parameter must be present
        assert 'ras_object' in params
        assert params['ras_object'].default is None

    def test_returns_dict_annotation(self):
        """Test that return type annotation is dict."""
        from ras_commander import HdfBenefitAreas
        import inspect

        sig = inspect.signature(HdfBenefitAreas.identify_benefit_areas)

        # Check return annotation (dict[str, GeoDataFrame])
        # Note: Full type checking requires running analysis
        assert sig.return_annotation != inspect.Signature.empty


class TestExpectedBehavior:
    """Test expected behavior without running full analysis."""

    def test_file_not_found_error_for_missing_plans(self):
        """Test that missing HDF files raise FileNotFoundError."""
        from ras_commander import HdfBenefitAreas, RasExamples, init_ras_project

        # Extract example project but don't run plans
        path = RasExamples.extract_project("Muncie")
        init_ras_project(path, "6.5")

        # Plans likely don't have HDF files yet
        with pytest.raises(FileNotFoundError, match="Existing plan HDF not found"):
            HdfBenefitAreas.identify_benefit_areas(
                existing_hdf_path="01",
                proposed_hdf_path="02"
            )

    def test_return_structure_keys(self):
        """Test that return dict has expected keys (if plans exist)."""
        # This test would run if HDF files existed
        # For now, just document expected structure

        expected_keys = {
            'benefit_polygons',
            'rise_polygons',
            'existing_points',
            'proposed_points',
            'difference_points'
        }

        # Verify this is documented in docstring
        from ras_commander import HdfBenefitAreas
        docstring = HdfBenefitAreas.identify_benefit_areas.__doc__

        for key in expected_keys:
            assert key in docstring, f"Expected key '{key}' not documented"


# Integration test - requires HEC-RAS execution
# Marked to skip by default, run manually when testing with real projects
@pytest.mark.skip(reason="Requires HEC-RAS execution - run manually")
class TestIntegrationWithExecution:
    """Integration tests requiring HEC-RAS plan execution."""

    def test_full_workflow_with_existing_project(self):
        """
        Full integration test: extract project, run plans, analyze.

        This test is skipped by default because it requires:
        - HEC-RAS 6.x installation
        - Several minutes to execute plans
        - Actual 2D model results

        To run manually:
            pytest tests/test_hdf_benefit_areas.py -k test_full_workflow -v
        """
        from ras_commander import (
            RasExamples, init_ras_project, RasCmdr, HdfBenefitAreas
        )

        # Extract 2D example project
        path = RasExamples.extract_project("BaldEagleCrkMulti2D")
        init_ras_project(path, "6.5")

        # Run two plans (existing and proposed)
        # Note: This takes several minutes
        RasCmdr.compute_plan("01", num_cores=2)
        RasCmdr.compute_plan("02", num_cores=2)

        # Identify benefit areas using plan numbers
        results = HdfBenefitAreas.identify_benefit_areas(
            existing_hdf_path="01",
            proposed_hdf_path="02",
            min_delta=0.1
        )

        # Validate output structure
        assert isinstance(results, dict)
        assert 'benefit_polygons' in results
        assert 'rise_polygons' in results
        assert 'existing_points' in results
        assert 'proposed_points' in results
        assert 'difference_points' in results

        # Validate all are GeoDataFrames
        import geopandas as gpd
        for key, gdf in results.items():
            assert isinstance(gdf, gpd.GeoDataFrame), f"{key} is not a GeoDataFrame"

        # Validate schema
        assert 'group_id' in results['benefit_polygons'].columns
        assert 'cell_count' in results['benefit_polygons'].columns
        assert 'area_sqft' in results['benefit_polygons'].columns
        assert 'area_acres' in results['benefit_polygons'].columns

        assert 'wse_difference' in results['difference_points'].columns
        assert 'change_type' in results['difference_points'].columns

    def test_multi_project_workflow(self):
        """Test with multiple RasPrj objects (ras_object parameter)."""
        from ras_commander import (
            RasExamples, RasPrj, init_ras_project, RasCmdr, HdfBenefitAreas
        )

        # Create two separate project objects
        project1 = RasPrj()
        path1 = RasExamples.extract_project("BaldEagleCrkMulti2D", suffix="project1")
        init_ras_project(path1, "6.5", ras_object=project1)

        project2 = RasPrj()
        path2 = RasExamples.extract_project("Muncie", suffix="project2")
        init_ras_project(path2, "6.5", ras_object=project2)

        # Run plans on project1
        RasCmdr.compute_plan("01", ras_object=project1)
        RasCmdr.compute_plan("02", ras_object=project1)

        # CRITICAL: Must pass ras_object when using local ras
        results = HdfBenefitAreas.identify_benefit_areas(
            existing_hdf_path="01",
            proposed_hdf_path="02",
            ras_object=project1  # MUST pass this
        )

        # Validate results are from project1
        assert isinstance(results, dict)
        assert len(results) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
