import json
from pathlib import Path

import pandas as pd
import pytest

import ras_commander.usgs as usgs
from ras_commander.usgs.study import (
    UsgsDrainageAreaComparison,
    UsgsObservations,
)


def _mock_services():
    continuous_flow = pd.DataFrame({
        "datetime": pd.to_datetime([
            "2024-01-01 00:00:00",
            "2024-01-01 01:00:00",
            "2024-01-01 02:00:00",
            "2024-01-01 04:00:00",
        ]),
        "value": [100.0, 110.0, 125.0, 150.0],
    })
    daily_flow = pd.DataFrame({
        "datetime": pd.to_datetime([
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
        ]),
        "value": [105.0, 120.0, 140.0],
    })
    peak_flow = pd.DataFrame({
        "datetime": pd.to_datetime([
            "2020-05-01",
            "2023-04-15",
        ]),
        "value": [2100.0, 2650.0],
        "gage_height_ft": [11.2, 13.4],
    })
    empty_stage = pd.DataFrame(columns=["datetime", "value"])

    return {
        "metadata": lambda site_id: {
            "site_id": site_id,
            "station_name": "Mock River at Example",
            "latitude": 39.1,
            "longitude": -89.2,
            "drainage_area_sqmi": 125.0,
            "state": "IL",
            "available_parameters": ["00060", "00065"],
        },
        "continuous_flow": lambda site_id, start_datetime, end_datetime: continuous_flow,
        "daily_flow": lambda site_id, start_datetime, end_datetime: daily_flow,
        "peak_flow": lambda site_id, start_datetime, end_datetime: peak_flow,
        "continuous_stage": lambda site_id, start_datetime, end_datetime: empty_stage,
        "daily_stage": lambda site_id, start_datetime, end_datetime: empty_stage,
    }


class TestUsgsStudyExports:
    def test_study_exports_available_from_package(self):
        expected = {
            "UsgsObservations",
            "UsgsDrainageAreaComparison",
            "retrieve_peak_flow_data",
            "retrieve_observed_dataset",
            "summarize_observed_dataset",
            "analyze_observation_gaps",
            "compare_drainage_areas",
        }

        assert expected.issubset(set(usgs.__all__))
        assert callable(usgs.retrieve_observed_dataset)
        assert callable(usgs.summarize_observed_dataset)
        assert callable(usgs.analyze_observation_gaps)
        assert callable(usgs.compare_drainage_areas)


class TestUsgsObservationPrimitives:
    def test_get_dataset_and_gap_analysis_are_chainable(self):
        dataset = UsgsObservations.get_dataset(
            site_id="05586100",
            dataset_id="continuous_flow",
            start_datetime="2024-01-01",
            end_datetime="2024-01-05",
            services=_mock_services(),
        )
        summary = UsgsObservations.summarize_dataset(
            dataset_id="continuous_flow",
            frame=dataset,
            status="ok",
        )
        gap_analysis = UsgsObservations.analyze_gaps(
            dataset_id="continuous_flow",
            frame=dataset,
        )

        assert list(dataset.columns) == ["datetime", "value"]
        assert summary["dataset_id"] == "continuous_flow"
        assert summary["record_count"] == 4
        assert gap_analysis["status"] == "ok"
        assert gap_analysis["gap_count"] == 1


class TestDrainageAreaComparison:
    def test_compare_areas_handles_subset_inputs(self):
        comparison = UsgsDrainageAreaComparison.compare_areas(
            gauge_area_sqmi=100.0,
            model_area_sqmi=112.0,
        )

        assert comparison["provided_area_count"] == 2
        assert comparison["reference_key"] == "gauge_area_sqmi"
        assert comparison["comparisons"]["model_area_sqmi"][
            "difference_from_reference_sqmi"
        ] == pytest.approx(12.0)
        assert comparison["comparisons"]["model_area_sqmi"][
            "difference_from_reference_percent"
        ] == pytest.approx(12.0)
        assert comparison["agreement_status"] == "review"

class TestExampleNotebook:
    def test_example_notebook_exists_for_workflow_assembly(self):
        notebook_path = Path("examples/911a_usgs_study_package_from_primitives.ipynb")
        assert notebook_path.exists()
