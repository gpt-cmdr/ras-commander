"""Complete area replacement against native text layout and real example data."""

import importlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ras_commander import GeomBcLines, RasUnsteady


def _block(name, area):
    return (
        f"BC Line Name={name}\nBC Line Storage Area={area}\n"
        "BC Line Arc= 2\n"
        "               0               0              10               0\n"
        "BC Line Text Position= 0 , 0\n"
    )


@pytest.fixture
def project(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "test.g01").write_text(
        "Geom Title=Replacement\nStorage Area=Target,,\nStorage Area 2D Points= 4\n"
        "Storage Area=Other,,\nStorage Area 2D Points= 4\n"
        + _block("Old1", "Target")
        + _block("Old2", "Target")
        + _block("Retained", "Other")
        + "LCMann Time=preserve\n"
    )
    (source / "test.u01").write_text(
        "Flow Title=Replacement\nProgram Version=6.60\nUse Restart=0\n"
        "Boundary Location=,,,,,Target,,Old1\nFriction Slope=0.001\n"
        "Boundary Location=,,,,,Other,,Retained\nFriction Slope=0.002\n"
        "Boundary Location=,,,,,Target,,Old2\nFriction Slope=0.003\n"
        "Boundary Location=,,,,,Target,,\nPrecipitation Hydrograph= 2\n"
        "       0       1\nUse DSS=False\n"
        "Met Point Raster Parameters=preserve\n"
    )
    clone = tmp_path / "clone"
    shutil.copytree(source, clone)
    return source, clone / "test.g01", clone / "test.u01"


def _spec(name="New", bc_type="Normal Depth"):
    spec = {
        "name": name,
        "coordinates": [(0, 0), (10, 0)],
        "bc_type": bc_type,
        "friction_slope": 0.001,
    }
    if bc_type != "Normal Depth":
        spec["hydrograph_df"] = pd.DataFrame({"hour": [0, 1, 2], "value": [1, 2, 1]})
    return spec


def test_complete_area_replacement_preserves_source_other_area_and_rainfall(project):
    source, geom, flow = project
    originals = {path.name: path.read_bytes() for path in source.iterdir()}
    other_geometry = _block("Retained", "Other")
    rainfall = flow.read_text().split("Boundary Location=,,,,,Target,,\n", 1)[1]
    result = GeomBcLines.replace_bc_lines(
        str(geom), [str(flow)], area_2d="Target", lines=[_spec()]
    )
    assert result.bc_line.tolist() == ["New"]
    assert result.attrs["removed_bc_lines"] == ["Old1", "Old2"]
    assert all(Path(p).is_file() for p in result.attrs["backup_paths"])
    assert "Old1" not in geom.read_text() + flow.read_text()
    assert "Old2" not in geom.read_text() + flow.read_text()
    assert other_geometry in geom.read_text()
    assert (
        "Boundary Location=,,,,,Other,,Retained\nFriction Slope=0.002\n"
        in flow.read_text()
    )
    assert flow.read_text().endswith(rainfall)
    assert {path.name: path.read_bytes() for path in source.iterdir()} == originals
    assert {
        (b["parts"][5], b["parts"][7])
        for b in RasUnsteady._find_boundary_blocks(flow.read_text().splitlines(True))
    } == {("Target", "New"), ("Other", "Retained"), ("Target", "")}


@pytest.mark.parametrize("bc_type", ["Flow Hydrograph", "Stage Hydrograph"])
def test_hydrograph_types_multiple_flows_and_crlf(project, bc_type):
    _, geom, flow = project
    for path in (geom, flow):
        path.write_bytes(
            path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        )
    second = flow.with_suffix(".u02")
    shutil.copyfile(flow, second)
    result = GeomBcLines.replace_bc_lines(
        geom, [flow, second], area_2d="Target", lines=[_spec(bc_type=bc_type)]
    )
    assert len(result) == 2
    for path in (geom, flow, second):
        assert b"\n" not in path.read_bytes().replace(b"\r\n", b"")
    assert (
        next(
            line
            for line in flow.read_text().splitlines()
            if line.startswith(f"{bc_type}=")
        )
        .split("=", 1)[1]
        .strip()
        == "3"
    )
    assert flow.read_bytes() == second.read_bytes()


def test_empty_replacement_clears_named_lines_preserves_area_forcing(project):
    _, geom, flow = project
    result = GeomBcLines.replace_bc_lines(geom, [flow], area_2d="Target", lines=[])
    assert result.empty
    assert list(result.columns) == [
        "geom_file",
        "unsteady_file",
        "area_2d",
        "bc_line",
        "bc_type",
    ]
    assert "Old" not in geom.read_text() + flow.read_text()
    assert "Precipitation Hydrograph=" in flow.read_text()


@pytest.mark.parametrize(
    "change",
    [
        {"name": "Retained"},
        {"name": "bad\nname"},
        {"name": "x" * 33},
        {"coordinates": [(0, 0), (float("nan"), 1)]},
        {"coordinates": [(0, 0), (0, 0)]},
        {"bc_type": "Unknown"},
        {"friction_slope": -1},
    ],
)
def test_invalid_spec_does_not_write(project, change):
    _, geom, flow = project
    original = [geom.read_bytes(), flow.read_bytes()]
    spec = _spec()
    spec.update(change)
    with pytest.raises(ValueError):
        GeomBcLines.replace_bc_lines(geom, [flow], area_2d="Target", lines=[spec])
    assert [geom.read_bytes(), flow.read_bytes()] == original
    assert not list(geom.parent.glob("*.bak*"))


def test_later_file_commit_failure_rolls_back_all_bytes(project, monkeypatch):
    _, geom, flow = project
    original = [geom.read_bytes(), flow.read_bytes()]
    module = importlib.import_module("ras_commander.geom.GeomBcLines")
    replace = module.os.replace
    failed = False

    def fail_once(source, destination):
        nonlocal failed
        if Path(destination) == flow and not failed:
            failed = True
            raise OSError("Injected second-file commit failure")
        return replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_once)
    with pytest.raises(OSError, match="Injected"):
        GeomBcLines.replace_bc_lines(geom, [flow], area_2d="Target", lines=[_spec()])
    assert failed
    assert [geom.read_bytes(), flow.read_bytes()] == original


def test_metadata_requires_every_associated_flow(project):
    _, geom, flow = project
    second = flow.with_suffix(".u02")
    shutil.copyfile(flow, second)
    ras_object = SimpleNamespace(
        check_initialized=lambda: None,
        geom_df=pd.DataFrame({"full_path": [str(geom)], "geom_number": ["01"]}),
        plan_df=pd.DataFrame(
            {"geometry_number": ["01", "01"], "Flow Path": [str(flow), str(second)]}
        ),
    )
    with pytest.raises(ValueError, match="every flow"):
        GeomBcLines.replace_bc_lines(
            geom, [flow], area_2d="Target", lines=[_spec()], ras_object=ras_object
        )


def test_metadata_refresh_failure_reports_successful_commit(project, caplog):
    _, geom, flow = project

    def failed_refresh():
        raise RuntimeError("Metadata failure")

    ras_object = SimpleNamespace(
        check_initialized=lambda: None,
        geom_df=pd.DataFrame({"full_path": [str(geom)], "geom_number": ["01"]}),
        plan_df=pd.DataFrame({"geometry_number": ["01"], "Flow Path": [str(flow)]}),
        get_boundary_conditions=failed_refresh,
    )
    result = GeomBcLines.replace_bc_lines(
        geom, [flow], area_2d="Target", lines=[_spec()], ras_object=ras_object
    )
    assert result.attrs["boundaries_df_refreshed"] is False
    assert "refresh failed" in caplog.text
    assert "BC Line Name=New" in geom.read_text()


def test_later_flow_validation_failure_preserves_all_files(project):
    _, geom, flow = project
    second = flow.with_suffix(".u02")
    second.write_text(
        flow.read_text().replace("Target,,Old1", "Target,,Old1,unexpected")
    )
    paths = (geom, flow, second)
    original = [path.read_bytes() for path in paths]
    with pytest.raises(ValueError, match="Malformed"):
        GeomBcLines.replace_bc_lines(
            geom, [flow, second], area_2d="Target", lines=[_spec()]
        )
    assert [path.read_bytes() for path in paths] == original
    assert not list(geom.parent.glob("*.bak*"))


def test_retains_existing_backups_and_accepts_native_trailing_comma(project):
    _, geom, flow = project
    backup = geom.with_name(geom.name + ".bak")
    backup.write_bytes(b"previous retained evidence")
    flow.write_text(flow.read_text().replace("Target,,Old1\n", "Target,,Old1,\n"))
    GeomBcLines.replace_bc_lines(geom, [flow], area_2d="Target", lines=[_spec()])
    assert backup.read_bytes() == b"previous retained evidence"
    assert geom.with_name(geom.name + ".bak.1").is_file()


def test_clear_final_boundary_preserves_global_trailer(project):
    _, geom, flow = project
    flow.write_text(
        "Flow Title=only\nBoundary Location=,,,,,Target,,Old1\nFriction Slope=0.001\nMet Point Raster Parameters=retain\n"
    )
    GeomBcLines.replace_bc_lines(geom, [flow], area_2d="Target", lines=[])
    assert flow.read_text() == "Flow Title=only\nMet Point Raster Parameters=retain\n"


def test_malformed_native_block_fails_before_writes(project):
    _, geom, flow = project
    geom.write_text(geom.read_text().replace("BC Line Text Position= 0 , 0\n", "", 1))
    original = [geom.read_bytes(), flow.read_bytes()]
    with pytest.raises(ValueError, match="Unterminated"):
        GeomBcLines.replace_bc_lines(geom, [flow], area_2d="Target", lines=[_spec()])
    assert [geom.read_bytes(), flow.read_bytes()] == original


@pytest.mark.slow
def test_real_chippewa_clone_complete_replacement(tmp_path):
    from ras_commander import RasExamples, RasPrj, init_ras_project

    source = RasExamples.extract_project(
        "Chippewa_2D", output_path=tmp_path, suffix="_source"
    )
    if isinstance(source, list):
        source = source[0]
    clone = tmp_path / "child"
    shutil.copytree(source, clone)
    project = RasPrj()
    init_ras_project(clone, ras_object=project, hide_intro=True)
    plan = project.plan_df.iloc[0]
    geom = Path(
        project.geom_df.loc[
            project.geom_df.geom_number == plan.geometry_number, "full_path"
        ].iloc[0]
    )
    plans = project.plan_df[project.plan_df.geometry_number == plan.geometry_number]
    flows = [
        Path(value)
        for value in plans["Flow Path"].dropna().unique()
        if Path(value).suffix.startswith(".u")
    ]
    source_original = (Path(source) / geom.name).read_bytes()
    GeomBcLines.replace_bc_lines(
        geom,
        flows,
        area_2d="Perimeter 1",
        lines=[
            {
                **_spec(),
                "coordinates": [(1027205.96, 7858200.24), (1025994.94, 7858316.68)],
            }
        ],
        ras_object=project,
    )
    assert "BC Line Name=Upstream" not in geom.read_text()
    assert "BC Line Name=Downstream" not in geom.read_text()
    assert "BC Line Name=New" in geom.read_text()
    assert (Path(source) / geom.name).read_bytes() == source_original
    for flow in flows:
        blocks = RasUnsteady._find_boundary_blocks(flow.read_text().splitlines(True))
        assert [
            b["parts"][7]
            for b in blocks
            if len(b["parts"]) >= 8 and b["parts"][5] == "Perimeter 1" and b["parts"][7]
        ] == ["New"]
