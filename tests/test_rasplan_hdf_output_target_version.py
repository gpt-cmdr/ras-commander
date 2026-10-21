"""HEC-RAS 7.0 HDF output labels: declared-version gate vs target_ras_version."""

from pathlib import Path

import pytest

from ras_commander.RasPlan import RasPlan

LABEL = "Face Surface Velocity"  # one of the 14 HEC-RAS 7.0 secondary-flow labels
RAS70_EXE = r"C:\Program Files (x86)\HEC\HEC-RAS\7.0\Ras.exe"
RAS66_EXE = r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe"


class _DummyRas:
    def check_initialized(self):
        return None


def _write_plan(path: Path, program_version: str = "6.60") -> Path:
    lines = ["Plan Title=HDF Target", "Geom File=g01", "Flow File=u01"]
    if program_version is not None:
        lines.insert(1, f"Program Version={program_version}")
    lines += ["HDF Compression= 9 ", "Calibration Method= 0 "]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _program_version_line(path: Path) -> list:
    return [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("Program Version=")
    ]


def test_default_gate_still_rejects_on_declared_6x(tmp_path):
    plan = _write_plan(tmp_path / "P.p01")
    before = plan.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="target_ras_version"):
        RasPlan.set_hdf_output_variables(plan, [LABEL], ras_object=_DummyRas())
    with pytest.raises(ValueError):
        RasPlan.add_hdf_output_variable(plan, LABEL, ras_object=_DummyRas())
    assert plan.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("target", ["7.0", "7.0.1", "70", "701", 7.0, RAS70_EXE])
def test_target_version_allows_label_on_declared_6x(tmp_path, target):
    plan = _write_plan(tmp_path / "P.p01")
    assert RasPlan.set_hdf_output_variables(
        plan, [LABEL, "Face Flow"], ras_object=_DummyRas(), target_ras_version=target
    )
    assert set(RasPlan.get_hdf_output_variables(plan, ras_object=_DummyRas())) == {
        LABEL,
        "Face Flow",
    }
    # The declared Program Version is left as written.
    assert _program_version_line(plan) == ["Program Version=6.60"]


@pytest.mark.parametrize("target", ["6.6", "66", RAS66_EXE])
def test_older_target_rejects_even_when_declared_7(tmp_path, target):
    plan = _write_plan(tmp_path / "P.p01", program_version="7.00")
    with pytest.raises(ValueError, match="target HEC-RAS version"):
        RasPlan.add_hdf_output_variable(
            plan, LABEL, ras_object=_DummyRas(), target_ras_version=target
        )


def test_unparseable_target_raises(tmp_path):
    plan = _write_plan(tmp_path / "P.p01")
    with pytest.raises(ValueError, match="Could not determine"):
        RasPlan.set_hdf_output_variables(
            plan, [LABEL], ras_object=_DummyRas(), target_ras_version="Ras.exe"
        )


def test_target_does_not_affect_unversioned_labels(tmp_path):
    plan = _write_plan(tmp_path / "P.p01")
    assert RasPlan.add_hdf_output_variable(
        plan, "Face Flow", ras_object=_DummyRas(), target_ras_version="6.6"
    )


def test_profile_and_aliases_pass_target(tmp_path):
    plan = _write_plan(tmp_path / "P.p01")
    with pytest.raises(ValueError):
        RasPlan.use_optimal_hdf_settings(
            plan, additional_variables=[LABEL], ras_object=_DummyRas()
        )
    assert RasPlan.use_optimal_hdf_settings(
        plan, additional_variables=[LABEL], ras_object=_DummyRas(),
        target_ras_version="7.0",
    )
    plan2 = _write_plan(tmp_path / "P.p02")
    assert RasPlan.enable_hdf_output_variable(
        plan2, LABEL, ras_object=_DummyRas(), target_ras_version="7.0"
    )
    assert RasPlan.set_hdf_output_variable(
        plan2, LABEL, enabled=False, ras_object=_DummyRas(), target_ras_version="6.6"
    )
    assert LABEL not in RasPlan.get_hdf_output_variables(plan2, ras_object=_DummyRas())


@pytest.mark.parametrize(
    "value, expected",
    [("7.0", 7.0), ("7.0.1", 7.0), ("70", 7.0), ("701", 7.0), ("66", 6.6),
     ("6.7 Beta 5", 6.7), (7.0, 7.0), (RAS70_EXE, 7.0),
     (r"C:\HEC\HEC-RAS\6.7 Beta 5\Ras.exe", 6.7), ("Ras.exe", None), (None, None)],
)
def test_target_version_parsing(value, expected):
    assert RasPlan._target_ras_version_to_float(value) == expected


@pytest.mark.parametrize(
    "declared, exe, expected",
    [("6.60", RAS70_EXE, "7.0"), ("5.07", RAS70_EXE, "7.0"),
     ("7.00", RAS66_EXE, None), ("7.00", RAS70_EXE, None),
     (None, RAS70_EXE, None), ("6.60", "Ras.exe", None), ("6.60", None, None)],
)
def test_engine_target_only_relaxes_declared_gate(tmp_path, declared, exe, expected):
    plan = _write_plan(tmp_path / "P.p01", program_version=declared)
    assert RasPlan._engine_hdf_target_version(plan, exe) == expected


def test_real_example_plan_declares_pre_70(tmp_path):
    """Shipped example plans declare 5.x/6.x; target_ras_version unblocks them."""
    from ras_commander import RasExamples, RasPrj, init_ras_project

    try:
        folder = RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=tmp_path)
    except Exception as exc:  # pragma: no cover - offline/no cache
        pytest.skip(f"Example project unavailable: {exc}")
    ras_obj = init_ras_project(
        folder, ras_object=RasPrj(), load_results_summary=False, hide_intro=True
    )
    plan = RasPlan.get_plan_path("03", ras_obj)
    declared = RasPlan._version_to_float(
        RasPlan._parse_plan_program_version(
            Path(plan).read_text(encoding="utf-8", errors="replace").splitlines()
        )
    )
    assert declared is not None and declared < 7.0
    with pytest.raises(ValueError):
        RasPlan.set_hdf_output_variables("03", [LABEL], ras_object=ras_obj)
    assert RasPlan.set_hdf_output_variables(
        "03", [LABEL], ras_object=ras_obj, target_ras_version="7.0.1"
    )
    assert LABEL in RasPlan.get_hdf_output_variables("03", ras_object=ras_obj)


# --- Tightened target parsing and keyword-only signatures (audit follow-up) ---


@pytest.mark.parametrize(
    "target",
    [
        "D:/Tools/x86/Ras.exe",
        r"D:\Tools\x86\Ras.exe",
        "C:/HEC/HEC-RAS/Ras.exe",
        "1000",
        "latest",
        "/app/bin/RasUnsteady",
    ],
)
def test_unversioned_targets_do_not_parse(target):
    assert RasPlan._target_ras_version_to_float(target) is None


@pytest.mark.parametrize(
    "target, expected",
    [
        (r"C:\Program Files (x86)\HEC\HEC-RAS\7.0\Ras.exe", 7.0),
        ("C:/Program Files (x86)/HEC/HEC-RAS/6.7 Beta 5/Ras.exe", 6.7),
        (70, 7.0),
        (7, 7.0),
        ("6.6", 6.6),
    ],
)
def test_versioned_targets_parse(target, expected):
    assert RasPlan._target_ras_version_to_float(target) == expected


def test_explicit_unversioned_exe_target_raises(tmp_path):
    plan = _write_plan(tmp_path / "P.p01")
    with pytest.raises(ValueError, match="Could not determine"):
        RasPlan.set_hdf_output_variables(
            plan, [LABEL], ras_object=_DummyRas(),
            target_ras_version="D:/Tools/x86/Ras.exe",
        )


@pytest.mark.parametrize(
    "name",
    [
        "apply_hdf_output_profile",
        "use_optimal_hdf_settings",
        "set_hdf_output_variable",
        "enable_hdf_output_variable",
        "set_hdf_output_variables",
        "add_hdf_output_variable",
    ],
)
def test_target_ras_version_is_keyword_only(name):
    import inspect

    param = inspect.signature(getattr(RasPlan, name)).parameters["target_ras_version"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is None


# --- RasCmdr.compute_plan call site (no solver) ---


class _Captured(Exception):
    """Stops compute_plan right after the HDF writer call is captured."""


def _compute_plan_hdf_target(
    monkeypatch, tmp_path, *, declared, exe_folder, ras_version=None, **compute_kwargs
):
    import importlib

    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    RasCmdr = rascmdr_module.RasCmdr

    plan = _write_plan(tmp_path / "TestProject.p01", program_version=declared)
    prj = tmp_path / "TestProject.prj"
    prj.write_text("Proj Title=TestProject\nPlan File=p01\n", encoding="utf-8")
    exe = tmp_path / exe_folder / "Ras.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"synthetic ras executable")

    ras_obj = _DummyRas()
    ras_obj.project_folder = tmp_path
    ras_obj.project_name = "TestProject"
    ras_obj.prj_file = prj
    ras_obj.ras_exe_path = exe
    ras_obj.ras_version = ras_version or exe_folder

    captured = {}

    def capture(name):
        def _writer(*args, **kwargs):
            captured["writer"] = name
            captured["target_ras_version"] = kwargs.get("target_ras_version", "<missing>")
            raise _Captured()
        return staticmethod(_writer)

    monkeypatch.setattr(
        rascmdr_module.RasPlan,
        "get_plan_path",
        staticmethod(lambda plan_number, ras_object: plan),
    )
    monkeypatch.setattr(rascmdr_module.RasPlan, "set_hdf_output_variables", capture("set_hdf_output_variables"))
    monkeypatch.setattr(rascmdr_module.RasPlan, "use_optimal_hdf_settings", capture("use_optimal_hdf_settings"))
    # The synthetic exe has no accepted Terms & Conditions record.
    monkeypatch.setattr(
        RasCmdr, "_tcu_blocks_launch", staticmethod(lambda ras_object: False)
    )
    monkeypatch.setattr(
        rascmdr_module.subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("compute_plan must not launch in this test"),
    )

    result = RasCmdr.compute_plan(
        "01",
        ras_object=ras_obj,
        force_rerun=True,
        dialog_watchdog=False,
        **compute_kwargs,
    )
    assert result.success is False
    assert "writer" in captured, "compute_plan did not reach the HDF writer"
    return captured


@pytest.mark.parametrize(
    "declared, exe_folder, expected",
    [
        ("6.60", "7.0", "7.0"),   # newer engine than declared: pass the engine
        ("5.10", "7.0", "7.0"),
        ("6.60", "6.6", None),    # same engine: keep the declared gate
        ("7.00", "7.0", None),
        # Unversioned install folder: the exe path names no engine version,
        # so the declared gate stays (x86 must not read as 86.0).
        ("6.60", "x86", None),
    ],
)
def test_compute_plan_passes_engine_version_only_when_newer(
    monkeypatch, tmp_path, declared, exe_folder, expected
):
    captured = _compute_plan_hdf_target(
        monkeypatch, tmp_path, declared=declared, exe_folder=exe_folder,
        ras_version="7.0" if exe_folder == "x86" else None,
        hdf_output_variables=[LABEL],
    )
    assert captured["writer"] == "set_hdf_output_variables"
    assert captured["target_ras_version"] == expected


def test_compute_plan_profile_path_passes_engine_version(monkeypatch, tmp_path):
    captured = _compute_plan_hdf_target(
        monkeypatch, tmp_path, declared="6.60", exe_folder="7.0",
        hdf_output_profile="balanced", hdf_additional_variables=[LABEL],
    )
    assert captured["writer"] == "use_optimal_hdf_settings"
    assert captured["target_ras_version"] == "7.0"
