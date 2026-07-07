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
import logging

import geopandas as gpd
from shapely.geometry import Point, Polygon


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


class TestBenefitAreaLoggingAndPolygons:
    """Focused regressions for benefit/rise analysis logging and polygon building."""

    @staticmethod
    def _sample_points(existing_values=(10.0, 10.0), proposed_values=(9.5, 10.3)):
        return (
            gpd.GeoDataFrame(
                {
                    "mesh_name": ["M1", "M1"],
                    "cell_id": [0, 1],
                    "maximum_water_surface": list(existing_values),
                },
                geometry=[Point(0.5, 0.5), Point(1.5, 0.5)],
                crs="EPSG:2272",
            ),
            gpd.GeoDataFrame(
                {
                    "mesh_name": ["M1", "M1"],
                    "cell_id": [0, 1],
                    "maximum_water_surface": list(proposed_values),
                },
                geometry=[Point(0.5, 0.5), Point(1.5, 0.5)],
                crs="EPSG:2272",
            ),
        )

    @staticmethod
    def _sample_cells():
        return gpd.GeoDataFrame(
            {
                "mesh_name": ["M1", "M1"],
                "cell_id": [0, 1],
            },
            geometry=[
                Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
                Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
            ],
            crs="EPSG:2272",
        )

    def test_spatial_join_handles_mesh_name_and_cell_id_columns(self):
        """Benefit polygons should build when points and cells share standard columns."""
        from ras_commander.hdf.HdfBenefitAreas import HdfBenefitAreas

        existing_points, proposed_points = self._sample_points()
        matched = HdfBenefitAreas._match_points_by_xy(existing_points, proposed_points, 6)
        benefit_points, _ = HdfBenefitAreas._apply_threshold_and_classify(matched, 0.1)
        cells = self._sample_cells()

        benefit_polygons = HdfBenefitAreas._build_contiguous_polygons(
            benefit_points,
            cells,
            "Benefit Area",
            adjacency_method="polygon_edges",
            dissolve=True,
        )

        assert not benefit_polygons.empty
        assert benefit_polygons["cell_count"].sum() == 1
        assert benefit_polygons["area_sqft"].sum() == pytest.approx(1.0)

    def test_identify_benefit_areas_logs_one_concise_success_line(
        self, tmp_path, monkeypatch, caplog
    ):
        """Successful analysis should leave one compact INFO summary."""
        from ras_commander.hdf import HdfBenefitAreas, HdfMesh, HdfResultsMesh

        existing_hdf = tmp_path / "existing.p01.hdf"
        proposed_hdf = tmp_path / "proposed.p02.hdf"
        existing_hdf.touch()
        proposed_hdf.touch()

        existing_points, proposed_points = self._sample_points()
        cells = self._sample_cells()

        def fake_get_mesh_max_ws(hdf_path):
            return existing_points if Path(hdf_path) == existing_hdf else proposed_points

        monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_ws", fake_get_mesh_max_ws)
        monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda _hdf_path: cells)

        caplog.set_level(logging.INFO, logger="ras_commander.hdf.HdfBenefitAreas")
        results = HdfBenefitAreas.identify_benefit_areas(
            existing_hdf,
            proposed_hdf,
            min_delta=0.1,
        )

        assert set(results) == {
            "benefit_polygons",
            "rise_polygons",
            "existing_points",
            "proposed_points",
            "difference_points",
        }
        messages = [
            record.getMessage()
            for record in caplog.records
            if record.name == "ras_commander.hdf.HdfBenefitAreas"
        ]
        success_messages = [
            message for message in messages
            if message.startswith("Benefit analysis complete:")
        ]
        assert len(success_messages) == 1
        assert "benefit_areas=1" in success_messages[0]
        assert "rise_areas=1" in success_messages[0]
        assert "matched_points=2" in success_messages[0]
        assert not any(message.strip().startswith("Benefit areas:") for message in messages)

    def test_missing_max_wse_error_is_actionable(self, tmp_path, monkeypatch):
        from ras_commander.hdf import HdfBenefitAreas, HdfResultsMesh

        existing_hdf = tmp_path / "existing.p01.hdf"
        proposed_hdf = tmp_path / "proposed.p02.hdf"
        existing_hdf.touch()
        proposed_hdf.touch()

        monkeypatch.setattr(
            HdfResultsMesh,
            "get_mesh_max_ws",
            lambda _hdf_path: gpd.GeoDataFrame(),
        )

        with pytest.raises(ValueError, match="Maximum Water Surface"):
            HdfBenefitAreas.identify_benefit_areas(existing_hdf, proposed_hdf)

    def test_missing_mesh_cells_error_mentions_geometry_preprocessor(
        self, tmp_path, monkeypatch
    ):
        from ras_commander.hdf import HdfBenefitAreas, HdfMesh, HdfResultsMesh

        existing_hdf = tmp_path / "existing.p01.hdf"
        proposed_hdf = tmp_path / "proposed.p02.hdf"
        existing_hdf.touch()
        proposed_hdf.touch()

        existing_points, proposed_points = self._sample_points()

        def fake_get_mesh_max_ws(hdf_path):
            return existing_points if Path(hdf_path) == existing_hdf else proposed_points

        monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_ws", fake_get_mesh_max_ws)
        monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", lambda _hdf_path: gpd.GeoDataFrame())

        with pytest.raises(ValueError, match="geometry preprocessor"):
            HdfBenefitAreas.identify_benefit_areas(existing_hdf, proposed_hdf)


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
