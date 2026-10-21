"""Copied project folders re-initialize against the source project's .prj.

Regression coverage for RasCmdr.compute_plan(dest_folder=...) and the other
copy/re-initialize paths picking the first .prj in a multi-project folder.
No HEC-RAS solver is needed.
"""

import shutil
from pathlib import Path

import pytest

from ras_commander import RasExamples, RasPrj, init_ras_project


@pytest.fixture(scope="module")
def pump_station(tmp_path_factory):
    """Real example folder holding two projects: PumpRule.prj and Pumps.prj."""
    out = tmp_path_factory.mktemp("prj_selection")
    try:
        project = RasExamples.extract_project(
            "Pumping Station with Rules", output_path=out
        )
    except Exception as exc:  # pragma: no cover - offline/no cache
        pytest.skip(f"Example project unavailable: {exc}")
    assert sorted(p.name for p in project.glob("*.prj")) == [
        "PumpRule.prj",
        "Pumps.prj",
    ]
    return project


def _copy(src: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


@pytest.mark.parametrize("prj_name", ["PumpRule.prj", "Pumps.prj"])
def test_copy_reinitializes_same_project(pump_station, tmp_path, prj_name):
    source = init_ras_project(
        pump_station / prj_name,
        ras_object=RasPrj(),
        load_results_summary=False,
        hide_intro=True,
    )
    dest = _copy(pump_station, tmp_path / "dest")

    selected = RasPrj._matching_copied_prj_file(dest, source.prj_file)
    assert selected == dest / prj_name

    copy_ras = RasPrj()
    copy_ras.initialize(
        dest,
        source.ras_exe_path,
        prj_file=selected,
        load_results_summary=False,
    )
    assert copy_ras.prj_file.name == prj_name
    assert list(copy_ras.plan_df["plan_number"]) == list(
        source.plan_df["plan_number"]
    )


def test_folder_search_alone_picks_other_project(pump_station, tmp_path):
    """Documents the original defect: a folder init ignores the source project."""
    source = init_ras_project(
        pump_station / "Pumps.prj",
        ras_object=RasPrj(),
        load_results_summary=False,
        hide_intro=True,
    )
    dest = _copy(pump_station, tmp_path / "dest")
    folder_ras = RasPrj()
    folder_ras.initialize(dest, source.ras_exe_path, load_results_summary=False)
    assert folder_ras.prj_file.name != source.prj_file.name


def test_single_project_folder_keeps_folder_search(tmp_path):
    folder = tmp_path / "single"
    folder.mkdir()
    (folder / "Only.prj").write_text("Proj Title=Only\n", encoding="utf-8")
    assert RasPrj._matching_copied_prj_file(folder, Path("Only.prj")) is None


def test_missing_source_name_falls_back(tmp_path):
    folder = tmp_path / "multi"
    folder.mkdir()
    for name in ("A.prj", "B.prj"):
        (folder / name).write_text("Proj Title=x\n", encoding="utf-8")
    assert RasPrj._matching_copied_prj_file(folder, Path("C.prj")) is None
    assert RasPrj._matching_copied_prj_file(folder, None) is None
    assert RasPrj._matching_copied_prj_file(folder, Path("B.prj")) == folder / "B.prj"
