from types import SimpleNamespace

import pandas as pd

from ras_commander.RasPlan import RasPlan
from ras_commander.RasPrj import RasPrj


def _geometry_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "geom_number": ["01", "02", "03", "04"],
            "has_1d_xs": [True, False, True, None],
            "has_2d_mesh": [False, True, True, None],
            "num_cross_sections": [12, 0, 7, 0],
            "mesh_cell_count": [0, 500, 250, 0],
            "mesh_area_names": [[], ["Mesh 2D"], ["Mixed Mesh"], []],
            "geometry_metadata_source": ["hdf", "hdf", "text", "unavailable"],
            "geometry_metadata_valid": [True, True, True, False],
            "geometry_metadata_error": [None, None, None, "unreadable"],
        }
    )


def test_plan_df_combines_flow_and_geometry_classification():
    project = RasPrj()
    project.geom_df = _geometry_rows()
    plans = pd.DataFrame(
        {
            "plan_number": ["01", "02", "03", "04", "05", "06"],
            "unsteady_number": [None, "02", "03", "04", None, "06"],
            "Flow File": ["01", "02", "03", "04", None, "06"],
            "geometry_number": ["01", "02", "03", "04", "01", "99"],
        }
    )

    classified = project._enrich_plan_classification(plans)

    assert classified["flow_type"].tolist() == [
        "Steady",
        "Unsteady",
        "Unsteady",
        "Unsteady",
        "Unknown",
        "Unsteady",
    ]
    assert classified["geometry_type"].tolist() == [
        "1D",
        "2D",
        "1D/2D",
        "Unknown",
        "1D",
        "Unknown",
    ]
    assert classified["plan_type"].tolist() == [
        "steady_1d",
        "unsteady_2d",
        "unsteady_1d_2d",
        "unknown",
        "unknown",
        "unknown",
    ]
    assert str(classified["has_1d_xs"].dtype) == "boolean"
    assert str(classified["has_2d_mesh"].dtype) == "boolean"
    assert pd.isna(classified.loc[3, "has_1d_xs"])
    assert pd.isna(classified.loc[5, "has_2d_mesh"])
    assert classified.loc[5, "geometry_metadata_error"] == (
        "Referenced geometry was not found in geom_df"
    )


def test_plan_classification_reports_missing_geometry_reference():
    project = RasPrj()
    project.geom_df = _geometry_rows()
    plans = pd.DataFrame(
        {
            "plan_number": ["01"],
            "unsteady_number": ["01"],
            "Flow File": ["01"],
            "geometry_number": [None],
        }
    )

    classified = project._enrich_plan_classification(plans)

    assert classified.loc[0, "geometry_type"] == "Unknown"
    assert classified.loc[0, "plan_type"] == "unknown"
    assert classified.loc[0, "geometry_metadata_error"] == (
        "Plan geometry reference is missing"
    )


def test_rasplan_flow_type_fallback_fails_closed_without_flow_reference():
    project = SimpleNamespace(
        plan_df=pd.DataFrame(
            {
                "plan_number": ["01", "02", "03"],
                "unsteady_number": ["01", None, None],
                "Flow File": ["01", "02", None],
            }
        ),
        check_initialized=lambda: None,
    )

    assert RasPlan.get_plan_flow_type("01", project) == "Unsteady"
    assert RasPlan.get_plan_flow_type("02", project) == "Steady"
    assert RasPlan.get_plan_flow_type("03", project) == "Unknown"
