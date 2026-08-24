"""Regression coverage for quasi-unsteady and sediment plan associations."""

import logging
from pathlib import Path

import pandas as pd
import pytest

from ras_commander import inspect_project_assets, stage_project
from ras_commander.RasPrj import RasPrj
from ras_commander.schemas import DATAFRAME_SCHEMAS


def _write_quasi_unsteady_project(root: Path) -> Path:
    root.mkdir()
    project_name = "MobileBed"
    project = root / f"{project_name}.prj"
    project.write_text(
        "Proj Title=Mobile Bed Fixture\n"
        "Current Plan=p01\n"
        "Geom File=g01\n"
        "QuasiSteady File=q01\n"
        "Sediment File=s01\n"
        "Plan File=p01\n",
        encoding="ascii",
    )
    (root / f"{project_name}.p01").write_text(
        "Plan Title=Quasi-Unsteady Sediment\n"
        "Program Version=6.60\n"
        "Geom File=g01\n"
        "Flow File=q01\n"
        "Sediment File=s01\n",
        encoding="ascii",
    )
    (root / f"{project_name}.g01").write_text(
        "Geom Title=Mobile Bed\n",
        encoding="ascii",
    )
    (root / f"{project_name}.q01").write_text("Flow Title=Quasi\n", encoding="ascii")
    (root / f"{project_name}.s01").write_text("Sediment Title=Mobile\n", encoding="ascii")
    return project


def test_plan_df_resolves_quasi_unsteady_flow_with_normalized_contract_columns(
    tmp_path: Path,
) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "quasi")
    ras_project = RasPrj()
    ras_project.initialize(
        project.parent,
        None,
        suppress_logging=True,
        prj_file=project,
        load_results_summary=False,
        load_hdf_metadata=False,
    )

    plan = ras_project.plan_df.iloc[0]
    assert plan["flow_type"] == "Quasi-Unsteady"
    assert plan["unsteady_number"] is None
    assert plan["Flow File"] == "01"
    assert plan["Flow Path"] == str(project.parent / "MobileBed.q01")
    assert plan["Sediment File"] == "01"
    assert plan["Sediment Path"] == str(project.parent / "MobileBed.s01")
    assert plan["breach_definition_count"] == 0
    assert plan["breach_active_count"] == 0
    assert str(ras_project.plan_df["breach_definition_count"].dtype) == "Int64"
    assert str(ras_project.plan_df["breach_active_count"].dtype) == "Int64"
    assert plan["quasi_unsteady_number"] == "01"
    assert plan["flow_file_prefix"] == "q"
    assert plan["sediment_number"] == "01"

    ras_project._plan_flow_prefixes.clear()
    assert ras_project._flow_prefix_for_plan(plan) == "q"


def test_inventory_includes_required_quasi_unsteady_and_sediment_assets(
    tmp_path: Path,
) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "quasi")

    assets = inspect_project_assets(project, depth="current_plan", hash_files=True)

    quasi = assets.loc[assets["asset_kind"] == "quasi_unsteady_flow"].iloc[0]
    sediment = assets.loc[assets["asset_kind"] == "sediment"].iloc[0]
    assert quasi["reference_raw"] == "q01"
    assert quasi["resolved_path"] == str(project.parent / "MobileBed.q01")
    assert quasi["required"] is True
    assert quasi["inspection_state"] == "available"
    assert quasi["parent_asset_id"] == assets.loc[
        assets["asset_kind"] == "plan", "asset_id"
    ].iloc[0]
    assert sediment["reference_raw"] == "s01"
    assert sediment["resolved_path"] == str(project.parent / "MobileBed.s01")
    assert sediment["required"] is True
    assert sediment["inspection_state"] == "available"


def test_project_depth_includes_unused_declared_quasi_and_sediment_assets(
    tmp_path: Path,
) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "unused-components")
    project.write_text(
        project.read_text(encoding="ascii")
        + "QuasiSteady File=q02\nSediment File=s02\nPlan File=p02\n",
        encoding="ascii",
    )
    (project.parent / "MobileBed.p02").write_text(
        "Plan Title=Shared Quasi-Unsteady Sediment\n"
        "Program Version=6.60\n"
        "Geom File=g01\n"
        "Flow File=q01\n"
        "Sediment File=s01\n",
        encoding="ascii",
    )
    (project.parent / "MobileBed.q02").write_text(
        "Flow Title=Unused Quasi\n",
        encoding="ascii",
    )
    (project.parent / "MobileBed.s02").write_text(
        "Sediment Title=Unused Mobile\n",
        encoding="ascii",
    )

    assets = inspect_project_assets(project, depth="project")

    assert list(
        assets.loc[
            assets["asset_kind"] == "quasi_unsteady_flow",
            "reference_raw",
        ]
    ) == ["q01", "q02"]
    assert list(
        assets.loc[assets["asset_kind"] == "sediment", "reference_raw"]
    ) == ["s01", "s02"]


def test_missing_required_sediment_asset_is_not_ready(tmp_path: Path) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "missing-sediment")
    (project.parent / "MobileBed.s01").unlink()

    assets = inspect_project_assets(project, depth="current_plan")

    sediment = assets.loc[assets["asset_kind"] == "sediment"].iloc[0]
    assert sediment["required"] is True
    assert sediment["inspection_state"] == "missing"
    assert sediment["readiness"] == "not_ready"
    assert sediment["reason_code"] == "path_missing"

    ras_project = RasPrj()
    ras_project.initialize(
        project.parent,
        None,
        suppress_logging=True,
        prj_file=project,
        load_results_summary=False,
        load_hdf_metadata=False,
    )
    plan = ras_project.plan_df.iloc[0]
    assert plan["Sediment File"] == "01"
    assert plan["Sediment Path"] == str(project.parent / "MobileBed.s01")


def test_missing_required_quasi_flow_asset_is_not_ready(tmp_path: Path) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "missing-quasi")
    (project.parent / "MobileBed.q01").unlink()

    assets = inspect_project_assets(project, depth="current_plan")

    quasi = assets.loc[assets["asset_kind"] == "quasi_unsteady_flow"].iloc[0]
    assert quasi["required"] is True
    assert quasi["inspection_state"] == "missing"
    assert quasi["readiness"] == "not_ready"
    assert quasi["reason_code"] == "path_missing"


def test_uppercase_sediment_reference_resolves_portable_lowercase_path(
    tmp_path: Path,
) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "uppercase-sediment")
    plan = project.parent / "MobileBed.p01"
    plan.write_text(
        plan.read_text(encoding="ascii").replace("Sediment File=s01", "Sediment File=S01"),
        encoding="ascii",
    )

    assets = inspect_project_assets(project, depth="current_plan")

    sediment = assets.loc[assets["asset_kind"] == "sediment"].iloc[0]
    assert sediment["reference_raw"] == "S01"
    assert sediment["resolved_path"] == str(project.parent / "MobileBed.s01")
    assert sediment["inspection_state"] == "available"

    ras_project = RasPrj()
    ras_project.initialize(
        project.parent,
        None,
        suppress_logging=True,
        prj_file=project,
        load_results_summary=False,
        load_hdf_metadata=False,
    )
    plan_row = ras_project.plan_df.iloc[0]
    assert plan_row["Sediment File"] == "01"
    assert plan_row["Sediment Path"] == str(project.parent / "MobileBed.s01")


@pytest.mark.parametrize("reference", ["x01", "s1", "sABC", "s01extra"])
def test_plan_df_exposes_null_sediment_columns_without_valid_reference(
    tmp_path: Path,
    reference: str,
) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "invalid-sediment")
    plan = project.parent / "MobileBed.p01"
    plan.write_text(
        plan.read_text(encoding="ascii").replace(
            "Sediment File=s01",
            f"Sediment File={reference}",
        ),
        encoding="ascii",
    )

    ras_project = RasPrj()
    ras_project.initialize(
        project.parent,
        None,
        suppress_logging=True,
        prj_file=project,
        load_results_summary=False,
        load_hdf_metadata=False,
    )

    plan_row = ras_project.plan_df.iloc[0]
    assert pd.isna(plan_row["Sediment File"])
    assert pd.isna(plan_row["Sediment Path"])


def test_three_digit_sediment_reference_is_normalized(tmp_path: Path) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "three-digit-sediment")
    plan_path = project.parent / "MobileBed.p01"
    plan_path.write_text(
        plan_path.read_text(encoding="ascii").replace(
            "Sediment File=s01",
            "Sediment File=s123",
        ),
        encoding="ascii",
    )

    ras_project = RasPrj()
    ras_project.initialize(
        project.parent,
        None,
        suppress_logging=True,
        prj_file=project,
        load_results_summary=False,
        load_hdf_metadata=False,
    )

    plan_row = ras_project.plan_df.iloc[0]
    assert plan_row["Sediment File"] == "123"
    assert plan_row["Sediment Path"] == str(project.parent / "MobileBed.s123")


def test_get_plan_value_resolves_numbered_plan_and_sediment_key(tmp_path: Path) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "plan-value")
    ras_project = RasPrj()
    ras_project.initialize(
        project.parent,
        None,
        suppress_logging=True,
        prj_file=project,
        load_results_summary=False,
        load_hdf_metadata=False,
    )

    assert RasPrj.get_plan_value("01", "Sediment File", ras_object=ras_project) == "s01"


def test_stage_project_accepts_input_complete_quasi_project_without_derived_hdf(
    tmp_path: Path,
) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "source")
    destination = tmp_path / "published"

    result = stage_project(project, destination)

    geometry_hdf = result.assets.loc[
        result.assets["asset_kind"] == "geometry_hdf"
    ].iloc[0]
    assert result.execution_readiness == "ready"
    assert geometry_hdf["required"] is False
    assert geometry_hdf["inspection_state"] == "not_applicable"
    assert geometry_hdf["readiness"] == "not_required"
    assert geometry_hdf["reason_code"] == "not_required_for_quasi_unsteady_plan"
    assert result.ras_object.prj_file == destination / "MobileBed.prj"


def test_existing_steady_and_unsteady_prefixes_remain_compatible(tmp_path: Path) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "flows")
    ras_project = RasPrj()
    ras_project.project_folder = project.parent
    ras_project.project_name = project.stem

    assert ras_project._process_flow_file({"Flow File": "f02"}) == {
        "unsteady_number": None,
        "quasi_unsteady_number": None,
        "flow_file_prefix": "f",
        "Flow File": "02",
    }
    assert ras_project._process_flow_file({"Flow File": "u03"}) == {
        "unsteady_number": "03",
        "quasi_unsteady_number": None,
        "flow_file_prefix": "u",
        "Flow File": "03",
    }
    assert ras_project._process_flow_file({"Flow File": "Q04"}) == {
        "unsteady_number": None,
        "quasi_unsteady_number": "04",
        "flow_file_prefix": "q",
        "Flow File": "04",
    }


def test_plan_df_counts_stored_active_and_inactive_breach_definitions(
    tmp_path: Path,
) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "breaches")
    plan_path = project.parent / "MobileBed.p01"
    plan_path.write_text(
        plan_path.read_text(encoding="ascii")
        + "Breach Loc=River,Reach,1000,True\n"
        + "Breach Method= 0\n"
        + "Breach Loc=                ,                ,        ,False,Dam\n"
        + "Breach Method= 0\n",
        encoding="ascii",
    )

    ras_project = RasPrj()
    ras_project.initialize(
        project.parent,
        None,
        suppress_logging=True,
        prj_file=project,
        load_results_summary=False,
        load_hdf_metadata=False,
    )

    plan = ras_project.plan_df.iloc[0]
    assert plan["breach_definition_count"] == 2
    assert plan["breach_active_count"] == 1

    refreshed = ras_project.get_plan_entries().iloc[0]
    assert refreshed["breach_definition_count"] == 2
    assert refreshed["breach_active_count"] == 1
    assert refreshed["Sediment Path"] == str(project.parent / "MobileBed.s01")
    assert refreshed["flow_type"] == "Quasi-Unsteady"
    assert str(ras_project.get_plan_entries()["breach_definition_count"].dtype) == "Int64"
    assert str(ras_project.get_plan_entries()["breach_active_count"].dtype) == "Int64"


def test_plan_df_uses_nullable_counts_when_breach_inspection_fails(
    tmp_path: Path,
    caplog,
) -> None:
    project = _write_quasi_unsteady_project(tmp_path / "invalid-breach")
    plan_path = project.parent / "MobileBed.p01"
    plan_path.write_text(
        plan_path.read_text(encoding="ascii")
        + "Breach Loc=River,Reach,1000,unknown,Dam\n"
        + "Breach Method= 0\n",
        encoding="ascii",
    )
    caplog.set_level(logging.WARNING, logger="ras_commander.RasPrj")

    ras_project = RasPrj()
    ras_project.initialize(
        project.parent,
        None,
        suppress_logging=True,
        prj_file=project,
        load_results_summary=False,
        load_hdf_metadata=False,
    )

    plan = ras_project.plan_df.iloc[0]
    assert pd.isna(plan["breach_definition_count"])
    assert pd.isna(plan["breach_active_count"])
    assert any(
        "Could not inspect breach definitions" in record.getMessage()
        for record in caplog.records
    )


def test_plan_df_schema_registers_plan_feature_columns_once() -> None:
    schema_columns = DATAFRAME_SCHEMAS["plan_df"]["columns"]
    names = [column["name"] for column in schema_columns]

    for name in (
        "Sediment File",
        "Sediment Path",
        "breach_definition_count",
        "breach_active_count",
    ):
        assert names.count(name) == 1

    dtypes = {column["name"]: column["dtype"] for column in schema_columns}
    assert dtypes["breach_definition_count"] == "Int64"
    assert dtypes["breach_active_count"] == "Int64"


def test_empty_plan_dataframe_keeps_canonical_feature_columns(tmp_path: Path) -> None:
    ras_project = RasPrj()
    ras_project.project_folder = tmp_path
    ras_project.project_name = "Empty"
    ras_project._plan_flow_prefixes = {}

    plan_df = ras_project._enrich_plan_dataframe(pd.DataFrame())

    for column in (
        "Sediment File",
        "Sediment Path",
        "breach_definition_count",
        "breach_active_count",
        "flow_type",
    ):
        assert column in plan_df.columns
    assert str(plan_df["breach_definition_count"].dtype) == "Int64"
    assert str(plan_df["breach_active_count"].dtype) == "Int64"
