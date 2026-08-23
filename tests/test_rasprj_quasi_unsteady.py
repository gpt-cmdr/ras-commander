"""Regression coverage for quasi-unsteady and sediment plan associations."""

from pathlib import Path

from ras_commander import inspect_project_assets, stage_project
from ras_commander.RasPrj import RasPrj


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


def test_plan_df_resolves_quasi_unsteady_flow_without_new_contract_columns(
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
    assert "quasi_unsteady_number" not in ras_project.plan_df.columns
    assert "flow_file_prefix" not in ras_project.plan_df.columns

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
        "Flow File": "02",
    }
    assert ras_project._process_flow_file({"Flow File": "u03"}) == {
        "unsteady_number": "03",
        "Flow File": "03",
    }
    assert ras_project._process_flow_file({"Flow File": "Q04"}) == {
        "unsteady_number": None,
        "Flow File": "04",
    }
