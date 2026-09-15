"""Exercise live asset containment with the public staged-boundary inventory."""

from pathlib import Path

import h5py
import pandas as pd
import pytest

from ras_commander import inspect_project_assets, stage_project
from ras_commander.RasProject import ProjectPopulationError
from scripts.qualification.execution_evidence import live_worker


def _inline_project(root: Path, *, use_dss: str = "False", dss_file: str = "") -> Path:
    root.mkdir()
    project = root / "Inline.prj"
    project.write_text(
        "Proj Title=Inline boundary gate regression\n"
        "Current Plan=p01\nPlan File=p01\nGeom File=g01\nUnsteady File=u01\n",
        encoding="ascii",
    )
    project.with_suffix(".p01").write_text(
        "Plan Title=Inline\nProgram Version=6.60\nShort Identifier=Inline\n"
        "Simulation Date=23JAN2007,0000,23JAN2007,2400\n"
        "Geom File=g01\nFlow File=u01\n",
        encoding="ascii",
    )
    project.with_suffix(".g01").write_text("Geom Title=Geometry\n", encoding="ascii")
    with h5py.File(project.with_suffix(".g01.hdf"), "w") as hdf:
        hdf.attrs["Projection"] = ""
    pathname = "//RIVER/UPSTREAM/FLOW//1HOUR/RUN/" if use_dss == "True" else ""
    project.with_suffix(".u01").write_text(
        "Flow Title=Inline flow\nProgram Version=6.60\n"
        "Use Restart=0\nPrecipitation Mode=Disable\n"
        "Boundary Location=Brunner,1,1000,\x00\x00,,,,\n"
        "Interval=1HOUR\nFlow Hydrograph=3\n      10      20      10\n"
        f"DSS File={dss_file}\nDSS Path={pathname}\nUse DSS={use_dss}\n"
        "Boundary Location=Brunner,1,0,\x00\x00,,,,\nFriction Slope=0.00189\n",
        encoding="ascii",
    )
    return project


def _descriptions(assets: pd.DataFrame) -> pd.Series:
    return assets["reason_code"].eq("inline_or_structured_boundary").fillna(False)


def test_public_inline_boundary_stage_passes_without_changing_inventory(tmp_path: Path):
    project = _inline_project(tmp_path / "source")
    staged = stage_project(project, tmp_path / "stage")
    before = staged.assets.copy(deep=True)
    assert staged.execution_readiness == "ready"
    assert _descriptions(staged.assets).sum() == 2
    assert staged.assets.loc[_descriptions(staged.assets), "resolved_path"].isna().all()

    result = live_worker._require_live_stage_assets_safe(
        staged.assets, stage_root=staged.destination_root
    )

    assert result["descriptive_boundary_count"] == 2
    assert result["execution_candidate_count"] >= result["required_asset_count"] > 0
    assert result["external_execution_asset_count"] == 0
    pd.testing.assert_frame_equal(staged.assets, before)
    assert staged.source_fingerprint_before == staged.source_fingerprint_after
    assert staged.copied_fingerprint == staged.source_fingerprint_before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset_kind", "unknown"),
        ("asset_kind", "dss_file"),
        ("asset_role", "unknown"),
        ("required", True),
        ("resolved_path", "unproved-input.dss"),
        ("path_scope", "external"),
        ("path_scope", "internal"),
        ("portable", False),
        ("inspection_state", "failed"),
        ("readiness", "not_ready"),
        ("reason_code", "boundary_inventory_mismatch"),
        ("reference_raw", "DSS File=unproved-input.dss"),
        ("source_api", "unknown_reader"),
        ("owner_file", None),
    ],
)
def test_noncanonical_boundary_row_is_not_exempted(tmp_path: Path, field, value):
    staged = stage_project(_inline_project(tmp_path / "source"), tmp_path / "stage")
    assets = staged.assets.copy()
    index = assets.index[_descriptions(assets)][0]
    assets.loc[index, field] = value

    with pytest.raises(live_worker.LiveAssetGateError):
        live_worker._require_live_stage_assets_safe(
            assets, stage_root=staged.destination_root
        )


def test_boundary_owner_must_be_a_proved_internal_unsteady_file(tmp_path: Path):
    staged = stage_project(_inline_project(tmp_path / "source"), tmp_path / "stage")
    assets = staged.assets.copy()
    index = assets.index[_descriptions(assets)][0]
    outside = tmp_path / "outside.u01"
    outside.write_text("Flow Title=Outside\n", encoding="ascii")
    assets.loc[index, "owner_file"] = str(outside)

    with pytest.raises(live_worker.LiveAssetGateError, match="execution_asset_scope_unproved"):
        live_worker._require_live_stage_assets_safe(
            assets, stage_root=staged.destination_root
        )


def test_boundary_with_unproved_owning_file_inventory_is_not_exempted(tmp_path: Path):
    staged = stage_project(_inline_project(tmp_path / "source"), tmp_path / "stage")
    assets = staged.assets.copy()
    owner = assets.index[assets["asset_kind"].eq("unsteady_flow")][0]
    assets.loc[owner, "required"] = False

    with pytest.raises(live_worker.LiveAssetGateError, match="execution_asset_scope_unproved"):
        live_worker._require_live_stage_assets_safe(
            assets, stage_root=staged.destination_root
        )


@pytest.mark.parametrize("dependency", ["external", "missing", "uninspected"])
def test_inline_description_never_exempts_dss_child_dependency(tmp_path: Path, dependency):
    dss_file = str(tmp_path / "outside.dss") if dependency == "external" else "input.dss"
    project = _inline_project(tmp_path / "source", use_dss="True", dss_file=dss_file)
    if dependency != "missing":
        path = Path(dss_file) if dependency == "external" else project.parent / dss_file
        path.write_bytes(b"A DSS dependency; no reader or HEC execution is permitted")
    if dependency == "missing":
        with pytest.raises(ProjectPopulationError, match="required_component_unavailable"):
            stage_project(project, tmp_path / "stage")
        assets = inspect_project_assets(project)
        stage_root = project.parent
    else:
        staged = stage_project(project, tmp_path / "stage")
        assets = staged.assets
        stage_root = staged.destination_root
    assert _descriptions(assets).sum() == 2
    assert assets["asset_kind"].eq("dss_file").any()
    expected = "external_execution_asset" if dependency == "external" else "required_execution_asset_unready"

    with pytest.raises(live_worker.LiveAssetGateError, match=expected):
        live_worker._require_live_stage_assets_safe(
            assets, stage_root=stage_root
        )


def test_unrecognized_use_dss_still_rejects_ambiguous_dependency(tmp_path: Path):
    project = _inline_project(tmp_path / "source", use_dss="Unrecognized")
    staged = stage_project(project, tmp_path / "stage")
    assert staged.assets["reason_code"].eq("boundary_use_dss_unrecognized").any()

    with pytest.raises(live_worker.LiveAssetGateError, match="execution_asset_scope_unproved"):
        live_worker._require_live_stage_assets_safe(
            staged.assets, stage_root=staged.destination_root
        )
