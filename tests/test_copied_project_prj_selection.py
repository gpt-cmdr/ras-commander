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


def test_module_level_helper_and_init_kwargs(tmp_path):
    """Callers import the module-level helper, so substituting the RasPrj class
    (as tests and wrappers do) cannot remove it."""
    from ras_commander import RasPrj as rasprj_module_cls
    from ras_commander.RasPrj import (
        _copied_prj_init_kwargs,
        _matching_copied_prj_file,
    )

    single = tmp_path / "single"
    single.mkdir()
    (single / "Only.prj").write_text("Proj Title=Only\n", encoding="utf-8")
    assert _copied_prj_init_kwargs(single, Path("Only.prj")) == {}

    multi = tmp_path / "multi"
    multi.mkdir()
    for name in ("A.prj", "B.prj"):
        (multi / name).write_text("Proj Title=x\n", encoding="utf-8")
    assert _copied_prj_init_kwargs(multi, Path("B.prj")) == {
        "prj_file": multi / "B.prj"
    }
    assert _copied_prj_init_kwargs(multi, Path("C.prj")) == {}
    assert _matching_copied_prj_file(multi, Path("A.prj")) == multi / "A.prj"
    assert rasprj_module_cls._matching_copied_prj_file(
        multi, Path("A.prj")
    ) == _matching_copied_prj_file(multi, Path("A.prj"))


def _posix_bash():
    """A bash that understands POSIX temp paths (not the WSL launcher)."""
    bash = shutil.which("bash")
    if bash is None or "system32" in bash.lower() or "windowsapps" in bash.lower():
        return None
    return bash


@pytest.mark.parametrize(
    "project_name, expected",
    [("Pumps", "Pumps"), ("PumpRule", "PumpRule"), ("", "PumpRule"), ("Missing", "PumpRule")],
)
def test_container_script_selects_project_name(tmp_path, project_name, expected):
    """run_ras.sh honours PROJECT_NAME in a multi-project folder.

    The script stops at its "no preprocessed file" check, so no HEC-RAS
    binary runs. Without PROJECT_NAME (or when it names no .prj) the
    original first-.prj selection is kept.
    """
    import os
    import subprocess

    bash = _posix_bash()
    if bash is None:
        pytest.skip("POSIX bash not available")

    script = (
        Path(__file__).resolve().parents[1]
        / "ras_commander"
        / "remote"
        / "docker"
        / "scripts"
        / "run_ras.sh"
    )
    work = tmp_path / "input"
    work.mkdir()
    for name in ("PumpRule.prj", "Pumps.prj"):
        (work / name).write_text("Proj Title=x\n", encoding="utf-8")
    text = script.read_text(encoding="utf-8")
    assert "cd /app/input\n" in text
    local_script = tmp_path / "run_ras_local.sh"
    local_script.write_bytes(
        text.replace("cd /app/input\n", 'cd "$RAS_TEST_INPUT"\n').encode("utf-8")
    )

    env = dict(os.environ)
    env["RAS_TEST_INPUT"] = work.as_posix()
    env.pop("PROJECT_NAME", None)
    if project_name:
        env["PROJECT_NAME"] = project_name
    if os.name == "nt":
        cygpath = subprocess.run(
            [bash, "-c", f"cygpath -u '{work}'"],
            capture_output=True,
            text=True,
        )
        if cygpath.returncode == 0 and cygpath.stdout.strip():
            env["RAS_TEST_INPUT"] = cygpath.stdout.strip()
        script_arg = subprocess.run(
            [bash, "-c", f"cygpath -u '{local_script}'"],
            capture_output=True,
            text=True,
        ).stdout.strip() or local_script.as_posix()
    else:
        script_arg = str(local_script)

    proc = subprocess.run(
        [bash, script_arg, "01"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert f"Project: {expected}\n" in proc.stdout, proc.stdout
    assert f"Looking for: {expected}.p01.tmp.hdf" in proc.stdout, proc.stdout
