"""Offline tests of the Wine preprocessing container controller and worker.

Ported from ras2fim-2d ``tests/test_wine_preprocessing_stage.py``: the tests of
``prepare.py``, ``windows_worker.py`` and ``bundle_profile.py``. The ras2fim
host-staging tests do not apply here. Wine, Docker and HEC-RAS are replaced by
runners and stand-in modules; HDF compute messages use real h5py files.
"""

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import types
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPE = REPO_ROOT / "containers" / "hecras-wine-precompute"


def load_container_script(name):
    path = RECIPE / (name + ".py")
    spec = importlib.util.spec_from_file_location("rc_container_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_project(models, name):
    project_dir = models / name
    project_dir.mkdir()
    project = project_dir / (name + ".prj")
    project.write_text(
        "Proj Title=" + name + "\nCurrent Plan=p01\nPlan File=p01\n",
        encoding="utf-8",
    )
    project.with_suffix(".p01").write_text(
        "Plan Title=Test\nGeom File=g01\nFlow File=u01\n", encoding="utf-8"
    )
    return project


# --- Recipe consistency ----------------------------------------------------

def test_recipe_uses_ras_commander_environment_and_label_names():
    for name in ("Dockerfile", "prepare.py", "verify_bundled_runtime.sh",
                 "windows_worker.py", "model_checks.py", "bundle_profile.py"):
        text = (RECIPE / name).read_text(encoding="utf-8")
        assert "RAS2FIM_" not in text, name
        assert "io.clb." not in text, name
    dockerfile = (RECIPE / "Dockerfile").read_text(encoding="utf-8")
    declared = set(re.findall(r"\b(RAS_COMMANDER_PREPARE_[A-Z0-9_]+)=", dockerfile))
    read = set()
    for name in ("prepare.py", "verify_bundled_runtime.sh"):
        read |= set(re.findall(r"\b(RAS_COMMANDER_PREPARE_[A-Z0-9_]+)\b",
                               (RECIPE / name).read_text(encoding="utf-8")))
    assert read <= declared
    assert declared == {
        "RAS_COMMANDER_PREPARE_JOB_ROOT",
        "RAS_COMMANDER_PREPARE_RUNTIME_MANIFEST",
        "RAS_COMMANDER_PREPARE_SCRATCH_ROOT",
        "RAS_COMMANDER_PREPARE_HECRAS_VERSION",
        "RAS_COMMANDER_PREPARE_RAS_COMMANDER_COMMIT",
        "RAS_COMMANDER_PREPARE_RAS_COMMANDER_WHEEL_SHA256",
        "RAS_COMMANDER_PREPARE_BUNDLED_RUNTIME",
    }


def test_dockerfile_copies_existing_recipe_files():
    dockerfile = (RECIPE / "Dockerfile").read_text(encoding="utf-8")
    sources = re.findall(r"^COPY (containers/\S+) ", dockerfile, re.MULTILINE)
    assert len(sources) == 4
    for source in sources:
        assert (REPO_ROOT / source).is_file(), source
        assert source.startswith("containers/hecras-wine-precompute/")


def test_controller_and_executor_share_the_cpu_shim_variable():
    prepare = load_container_script("prepare")
    assert prepare.CPU_SHIM_VARIABLE == "RAS_COMMANDER_WINE_CPU_SHIM"
    from ras_commander.remote import execute_request
    assert execute_request._WINE_CPU_SHIM == prepare.CPU_SHIM_VARIABLE


def test_example_manifest_matches_runtime_schema():
    prepare = load_container_script("prepare")
    data = json.loads((RECIPE / "runtime-manifest.example.json").read_text(encoding="utf-8"))
    assert data["schema"] == prepare.RUNTIME_SCHEMA
    assert data["kind"] == "wine"
    assert data["wine"]["prefix_seed"] == "prefix"


# --- Windows worker --------------------------------------------------------

@pytest.mark.parametrize("num_cores", [None, 1, 2, 8])
@pytest.mark.parametrize("applied", [True, False])
def test_wine_worker_uses_ras_commander_preprocessing_api(tmp_path, monkeypatch, num_cores, applied):
    worker = load_container_script("windows_worker")
    checks = types.ModuleType("model_checks")
    checks.preflight = lambda *args: ([], tmp_path / "Model.g01.hdf", {}, [])
    checks.normalize_inputs = lambda paths: []
    checks.validate_outputs = lambda *args: {"geometry": {"area": {}}, "temporary_plan": {"area": {}}}
    monkeypatch.setitem(sys.modules, "model_checks", checks)
    calls = {}
    plan_path = tmp_path / "Model.p01"

    class FakeProject:
        pass

    class FakeResult:
        success = True
        plan_number = "01"
        geometry_number = "01"
        tmp_hdf_path = tmp_path / "Model.p01.tmp.hdf"
        b_file_path = tmp_path / "Model.b01"
        x_file_path = tmp_path / "Model.x01"
        elapsed_seconds = 1.5
        signal_source = "bco"
        full_result_copied = False
        timed_out = False
        error = None

        def __bool__(self):
            return True

    class FakeGeomPreprocessor:
        @staticmethod
        def clear_geompre_files(path, *, ras_object):
            calls["clear"] = (path, ras_object)

    class FakePlan:
        @staticmethod
        def get_plan_path(plan, *, ras_object):
            return plan_path

        @staticmethod
        def set_num_cores(path, count, *, ras_object, refresh_dataframes):
            calls["cores"] = (path, count, ras_object, refresh_dataframes)

        @staticmethod
        def set_2d_flow_options(path, *, cores, include_default, ras_object):
            calls["mesh_cores"] = (path, cores, include_default, ras_object)

        @staticmethod
        def get_plan_value(path, key, *, ras_object):
            assert path == plan_path
            assert key == "UNET D2 Cores"
            return calls["cores"][1] if applied else None

        @staticmethod
        def update_run_flags(path, *, ras_object, **flags):
            calls["flags"] = flags

    class FakePreprocess:
        @staticmethod
        def preprocess_plan(plan, **kwargs):
            assert "cores" in calls
            calls["prepare"] = (plan, kwargs)
            return FakeResult()

    def fake_init(project, **kwargs):
        calls["init"] = kwargs

    module = types.ModuleType("ras_commander")
    module.GeomPreprocessor = FakeGeomPreprocessor
    module.RasPlan = FakePlan
    module.RasPreprocess = FakePreprocess
    module.RasPrj = FakeProject
    module.init_ras_project = fake_init
    monkeypatch.setitem(sys.modules, "ras_commander", module)
    monkeypatch.setattr(
        worker,
        "verify_ras_commander",
        lambda *args: {
            "ras_commander_wheel_sha256": "d" * 64,
            "ras_commander_distribution_version": "0.99.2",
        },
    )

    arguments = (
        str(tmp_path / "Model.prj"),
        "01",
        "C:/HEC-RAS/6.6/Ras.exe",
        "C:/runtime/ras_commander.whl",
        "d" * 64,
        300,
        True,
    )
    options = {} if num_cores is None else {"num_cores": num_cores}
    if not applied:
        with pytest.raises(RuntimeError, match="no effective UNET D2 Cores setting"):
            worker.run_worker(*arguments, **options)
        assert "prepare" not in calls
        return
    result = worker.run_worker(*arguments, **options)

    assert result["success"] is True
    assert calls["init"]["accept_tcu"] is True
    assert calls["clear"][0] == plan_path
    assert calls["cores"] == (plan_path, num_cores or 2, calls["init"]["ras_object"], False)
    assert calls["mesh_cores"] == (plan_path, num_cores or 2, True, calls["init"]["ras_object"])
    assert result["num_cores"] == (num_cores or 2)
    assert calls["flags"] == {"geometry_preprocessor": True}
    assert calls["prepare"][1]["max_wait"] == 300
    assert calls["prepare"][1]["clear_existing"] is True
    assert calls["prepare"][1]["fix_line_endings"] is True


@pytest.mark.parametrize("script", ["prepare", "windows_worker"])
@pytest.mark.parametrize("value", ["0", "9", "-1", "2.0", "two"])
def test_core_cli_rejects_out_of_range_and_noninteger_values(script, value):
    module = load_container_script(script)
    args = ["prepare", "--project", "model.prj"] if script == "prepare" else [
        "--project", "model.prj", "--plan", "01", "--ras-executable", "Ras.exe",
        "--ras-commander-wheel", "runtime.whl", "--expected-ras-commander-wheel-sha256",
        "d" * 64, "--timeout", "300", "--result", "result.json",
    ]
    with pytest.raises(SystemExit) as exc:
        module.build_parser().parse_args(args + ["--num-cores", value])
    assert exc.value.code == 2


@pytest.mark.parametrize("num_cores", [0, 9, -1, 2.0, "2", True, None])
def test_core_validation_precedes_runtime_or_model_access(tmp_path, monkeypatch, num_cores):
    prepare = load_container_script("prepare")
    worker = load_container_script("windows_worker")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid core count must fail before runtime access")

    monkeypatch.setattr(prepare, "load_runtime", forbidden)
    monkeypatch.setattr(worker, "verify_ras_commander", forbidden)
    with pytest.raises(prepare.JobError, match="integer from 1 to 8"):
        prepare.run_prepare("missing.prj", "01", 300, False, "invalid", tmp_path,
                            "runtime.json", "6.5", num_cores=num_cores)
    with pytest.raises(ValueError, match="integer from 1 to 8"):
        worker.run_worker("missing.prj", "01", "Ras.exe", "runtime.whl", "d" * 64,
                          300, False, num_cores=num_cores)
    assert list(tmp_path.iterdir()) == []


# --- Linux controller ------------------------------------------------------

def _runtime(prefix, version):
    return {
        "identity": {"kind": "wine", "hec_ras_version": version},
        "prefix": prefix, "wheel_sha": "d" * 64,
        "windows_python": "python.exe", "ras_executable": "Ras.exe",
        "ras_commander_wheel": "runtime.whl",
    }


@pytest.mark.parametrize("num_cores", [None, 1, 8])
@pytest.mark.parametrize("returned_cores", [None, "requested"])
def test_controller_propagates_cores_and_records_receipt(tmp_path, monkeypatch, num_cores, returned_cores):
    prepare = load_container_script("prepare")
    project = write_project(tmp_path, "core-test")
    prefix = tmp_path / "seed"
    prefix.mkdir()
    monkeypatch.setenv("RAS_COMMANDER_PREPARE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setenv("RAS_COMMANDER_WINE_CPU_SHIM", "0")
    monkeypatch.setattr(prepare, "load_runtime", lambda *args: _runtime(prefix, "6.5"))
    commands = []
    expected = num_cores or 2

    def runner(command, environment, timeout):
        if command[0] == "winepath":
            return SimpleNamespace(returncode=0, stdout=command[-1], stderr="")
        commands.append(command)
        assert command[command.index("--num-cores") + 1] == str(expected)
        outputs = prepare.expected_outputs(project, "01", "01")
        for output in outputs:
            output.write_bytes(b"prepared artifact")
        payload = {
            "success": True, "plan": "01", "geometry": "01",
            "num_cores": expected if returned_cores == "requested" else None,
            "timed_out": False, "full_result_copied": False, "signal_source": "bco",
            "ras_commander_wheel_sha256": "d" * 64,
            "hdf_validation": {"geometry": {"area": {}}, "temporary_plan": {"area": {}}},
            **dict(zip(("tmp_hdf_path", "b_file_path", "x_file_path"), map(str, outputs))),
        }
        Path(command[command.index("--result") + 1]).write_text(json.dumps(payload))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    options = {} if num_cores is None else {"num_cores": num_cores}
    success, receipt_path = prepare.run_prepare(
        project, "01", 300, False, "cores", project.parent, "runtime.json", "6.5",
        runner=runner, **options,
    )
    receipt = json.loads(receipt_path.read_text())
    assert len(commands) == 1
    assert receipt["arguments"]["num_cores"] == expected
    assert success is (returned_cores == "requested")
    if not success:
        assert "different core count" in receipt["error"]["message"]


def test_controller_uses_wine_environment_and_records_it(tmp_path, monkeypatch):
    prepare = load_container_script("prepare")
    project = write_project(tmp_path, "env-test")
    prefix = tmp_path / "seed"
    prefix.mkdir()
    shim = tmp_path / "cpushim.so"
    shim.write_bytes(b"shim")
    monkeypatch.setenv("RAS_COMMANDER_PREPARE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setenv("RAS_COMMANDER_WINE_CPU_SHIM", str(shim))
    monkeypatch.delenv("LD_PRELOAD", raising=False)
    monkeypatch.delenv("WINEDLLOVERRIDES", raising=False)
    monkeypatch.setattr(prepare, "load_runtime", lambda *args: _runtime(prefix, "6.6"))
    seen = {}

    def runner(command, environment, timeout):
        if command[0] == "winepath":
            return SimpleNamespace(returncode=0, stdout=command[-1], stderr="")
        seen["command"] = command
        seen["environment"] = environment
        Path(command[command.index("--result") + 1]).write_text(json.dumps({
            "success": False,
            "error": "RuntimeError: HEC-RAS reported a failed child program before a "
                     "readiness signal: Error with program: RasProcess.exe",
        }))
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    success, receipt_path = prepare.run_prepare(
        project, "01", 300, False, "env", project.parent, "runtime.json", "6.6", runner=runner)
    receipt = json.loads(receipt_path.read_text())

    assert success is False
    assert "Error with program: RasProcess.exe" in receipt["error"]["message"]
    assert seen["environment"]["LD_PRELOAD"] == str(shim.resolve())
    assert seen["environment"]["WINEDLLOVERRIDES"] == "winedbg.exe=d"
    assert receipt["wine_environment"]["cpu_shim"]["sha256"] == hashlib.sha256(b"shim").hexdigest()


def test_controller_reads_renamed_scratch_root(tmp_path, monkeypatch):
    prepare = load_container_script("prepare")
    project = write_project(tmp_path, "scratch-test")
    prefix = tmp_path / "seed"
    prefix.mkdir()
    (prefix / "user.reg").write_text("registry")
    scratch = tmp_path / "node-scratch"
    monkeypatch.setenv("RAS_COMMANDER_PREPARE_SCRATCH_ROOT", str(scratch))
    monkeypatch.setenv("RAS_COMMANDER_WINE_CPU_SHIM", "0")
    monkeypatch.setattr(prepare, "load_runtime", lambda *args: _runtime(prefix, "6.6"))
    seen = {}

    def runner(command, environment, timeout):
        if command[0] == "winepath":
            return SimpleNamespace(returncode=0, stdout=command[-1], stderr="")
        seen["prefix"] = Path(environment["WINEPREFIX"])
        Path(command[command.index("--result") + 1]).write_text(json.dumps({"success": False}))
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    prepare.run_prepare(project, "01", 300, False, "scratch", project.parent,
                        "runtime.json", "6.6", runner=runner)
    assert seen["prefix"] == scratch / "scratch" / "wineprefix"
    assert (seen["prefix"] / "user.reg").read_text() == "registry"


# --- Wine environment ------------------------------------------------------

def test_wine_environment_preloads_shim_and_disables_debugger(tmp_path):
    prepare = load_container_script("prepare")
    shim = tmp_path / "cpushim.so"
    shim.write_bytes(b"shim")
    base = {"RAS_COMMANDER_WINE_CPU_SHIM": str(shim), "LD_PRELOAD": "/other.so",
            "WINEDLLOVERRIDES": "mscoree=n", "WINEDEBUG": "err+all,fixme-all"}

    environment, record = prepare.wine_environment(tmp_path / "prefix", base)

    assert environment["WINEPREFIX"] == str(tmp_path / "prefix")
    assert environment["LD_PRELOAD"].split() == [str(shim.resolve()), "/other.so"]
    assert environment["WINEDLLOVERRIDES"] == "mscoree=n;winedbg.exe=d"
    assert record == {
        "WINEDEBUG": "err+all,fixme-all",
        "WINEDLLOVERRIDES": "mscoree=n;winedbg.exe=d",
        "KMP_AFFINITY": "disabled",
        "cpu_shim": {"path": str(shim.resolve()), "sha256": hashlib.sha256(b"shim").hexdigest()},
    }
    again, _ = prepare.wine_environment(tmp_path / "prefix", environment)
    assert again["LD_PRELOAD"] == environment["LD_PRELOAD"]
    assert again["WINEDLLOVERRIDES"] == environment["WINEDLLOVERRIDES"]


def test_wine_environment_defaults_to_the_image_shim_when_unset(tmp_path, monkeypatch):
    prepare = load_container_script("prepare")
    shim = tmp_path / "cpushim.so"
    shim.write_bytes(b"default shim")
    monkeypatch.setattr(prepare, "DEFAULT_CPU_SHIM", shim)
    environment, record = prepare.wine_environment(tmp_path, {})
    assert environment["LD_PRELOAD"] == str(shim.resolve())
    assert record["cpu_shim"]["path"] == str(shim.resolve())
    monkeypatch.setattr(prepare, "DEFAULT_CPU_SHIM", tmp_path / "absent.so")
    environment, record = prepare.wine_environment(tmp_path, {})
    assert "LD_PRELOAD" not in environment
    assert record["cpu_shim"] is None


@pytest.mark.parametrize("overrides", ["winedbg.exe=n,b", "mscoree,winedbg=b"])
def test_wine_environment_keeps_an_explicit_debugger_setting(tmp_path, overrides):
    prepare = load_container_script("prepare")
    environment, _ = prepare.wine_environment(
        tmp_path, {"RAS_COMMANDER_WINE_CPU_SHIM": "0", "WINEDLLOVERRIDES": overrides})
    assert environment["WINEDLLOVERRIDES"] == overrides


@pytest.mark.parametrize("setting", ["0", ""])
def test_wine_environment_shim_can_be_disabled(tmp_path, setting):
    prepare = load_container_script("prepare")
    environment, record = prepare.wine_environment(tmp_path, {"RAS_COMMANDER_WINE_CPU_SHIM": setting})
    assert "LD_PRELOAD" not in environment
    assert record["cpu_shim"] is None


def test_wine_environment_rejects_a_missing_explicit_shim(tmp_path):
    prepare = load_container_script("prepare")
    with pytest.raises(prepare.JobError, match="RAS_COMMANDER_WINE_CPU_SHIM"):
        prepare.wine_environment(tmp_path, {"RAS_COMMANDER_WINE_CPU_SHIM": str(tmp_path / "missing.so")})


def test_wine_environment_does_not_confuse_preload_path_prefixes(tmp_path):
    prepare = load_container_script("prepare")
    shim = tmp_path / "cpushim.so"
    shim.write_bytes(b"shim")
    other = str(shim) + ".other"
    environment, _ = prepare.wine_environment(
        tmp_path, {"RAS_COMMANDER_WINE_CPU_SHIM": str(shim), "LD_PRELOAD": other})
    assert environment["LD_PRELOAD"].split() == [str(shim), other]
    environment, _ = prepare.wine_environment(
        tmp_path, {"RAS_COMMANDER_WINE_CPU_SHIM": str(shim), "LD_PRELOAD": "/other.so:" + str(shim)})
    assert environment["LD_PRELOAD"] == "/other.so:" + str(shim)


# --- Child-program failures ------------------------------------------------

CRASH_MESSAGES = (
    "Writing Geometry...\r\n"
    "Computing 2D Flow Area 'Perimeter 1' tables: Property tables do not exist.\r\n\r\n"
    "Error with program: RasProcess.exe  Process Count = 1  Exit Code = -1073741819\r\n"
)


class _Result:
    """Bool-compatible stand-in for ras-commander's PreprocessResult."""

    def __init__(self, **values):
        self.__dict__.update(values)

    def __bool__(self):
        return bool(self.success)


def _preprocess_result(tmp_path, signal_source):
    return _Result(
        success=True, plan_number="01", geometry_number="01",
        tmp_hdf_path=tmp_path / "Model.p01.tmp.hdf", b_file_path=tmp_path / "Model.b01",
        x_file_path=tmp_path / "Model.x01", elapsed_seconds=1.0,
        signal_source=signal_source, full_result_copied=False, timed_out=False, error=None,
    )


def _write_compute_messages(path, messages):
    import h5py
    import numpy as np

    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("Results/Summary/Compute Messages (text)",
                           data=np.array([messages.encode("latin-1")]))


def _install_fake_ras_commander(monkeypatch, tmp_path, preprocess_plan):
    """Install minimal ras_commander and model_checks modules for run_worker."""
    import h5py

    checks = types.ModuleType("model_checks")
    checks.preflight = lambda *args: ([], tmp_path / "Model.g01.hdf", {}, [])
    checks.normalize_inputs = lambda paths: []
    checks.validate_outputs = lambda *args: {"geometry": {"area": {}}, "temporary_plan": {"area": {}}}
    monkeypatch.setitem(sys.modules, "model_checks", checks)

    class FakePlan:
        @staticmethod
        def get_plan_path(plan, *, ras_object):
            return tmp_path / "Model.p01"

        @staticmethod
        def set_num_cores(*args, **kwargs):
            return None

        @staticmethod
        def set_2d_flow_options(*args, **kwargs):
            return None

        @staticmethod
        def get_plan_value(*args, **kwargs):
            return 2

        @staticmethod
        def update_run_flags(*args, **kwargs):
            return None

    class FakeHdfResultsPlan:
        @staticmethod
        def get_compute_messages_hdf_only(path):
            with h5py.File(path, "r") as hdf:
                return hdf["Results/Summary/Compute Messages (text)"][()][0].decode("latin-1")

    module = types.ModuleType("ras_commander")
    module.GeomPreprocessor = types.SimpleNamespace(clear_geompre_files=lambda *a, **k: None)
    module.RasPlan = FakePlan
    module.RasPreprocess = types.SimpleNamespace(preprocess_plan=preprocess_plan)
    module.RasPrj = object
    module.HdfResultsPlan = FakeHdfResultsPlan
    module.init_ras_project = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "ras_commander", module)


def _worker(monkeypatch):
    worker = load_container_script("windows_worker")
    monkeypatch.setattr(worker, "verify_ras_commander", lambda *args: {
        "ras_commander_wheel_sha256": "d" * 64,
        "ras_commander_distribution_version": "0.99.2",
    })
    return worker


def _run_worker(worker, tmp_path, **kwargs):
    return worker.run_worker(str(tmp_path / "Model.prj"), "01", "C:/HEC-RAS/6.6/Ras.exe",
                             "C:/runtime/ras_commander.whl", "d" * 64, 300, True, **kwargs)


def test_worker_reports_child_program_failure_after_natural_exit(tmp_path, monkeypatch):
    """A ras-commander result without the child-program check must not succeed."""
    worker = _worker(monkeypatch)

    def preprocess_plan(plan, ras_object, max_wait, clear_existing, fix_line_endings):
        _write_compute_messages(tmp_path / "Model.p01.hdf", CRASH_MESSAGES)
        return _preprocess_result(tmp_path, "natural_completion")

    _install_fake_ras_commander(monkeypatch, tmp_path, preprocess_plan)
    with pytest.raises(RuntimeError) as exc:
        _run_worker(worker, tmp_path)
    assert "failed child program" in str(exc.value)
    assert "Error with program: RasProcess.exe" in str(exc.value)
    assert "Exit Code = -1073741819" in str(exc.value)


def test_worker_ignores_child_error_in_an_unchanged_plan_hdf(tmp_path, monkeypatch):
    worker = _worker(monkeypatch)
    _write_compute_messages(tmp_path / "Model.p01.hdf", CRASH_MESSAGES)

    def preprocess_plan(plan, ras_object, max_wait, clear_existing, fix_line_endings):
        return _preprocess_result(tmp_path, "natural_completion")

    _install_fake_ras_commander(monkeypatch, tmp_path, preprocess_plan)
    assert _run_worker(worker, tmp_path)["success"] is True


# --- Release profile export ------------------------------------------------

@pytest.mark.parametrize("relative,excluded", [
    ("prefix/drive_c/Program Files (x86)/HEC/HEC-RAS/6.5/Ras.exe", False),
    ("prefix/drive_c/Program Files (x86)/HEC/HEC-RAS/7.0.1/Ras.exe", True),
    ("prefix/drive_c/users/rasworker/AppData/Local/Temp/setup.exe", True),
    ("prefix/drive_c/users/rasworker/Documents/model.prj", True),
    ("prefix/drive_c/users/rasworker/AppData/Local/HEC/settings.xml", False),
    ("prefix/drive_c/users/rasworker/AppData/Local/pip/cache/download", True),
    ("prefix/drive_c/windows/system32/kernel32.dll", False),
    ("prefix/user.reg", False),
    ("prefix/drive_c/a0da2ed8e5bc9f2258/Setup.exe", True),
    ("prefix/drive_c/ProgramData/HEC/Installation Cache/setup.msi", True),
    ("prefix/drive_c/Python311/Lib/site-packages/pyogrio/tests/fixtures/test.prj", False),
    ("prefix/drive_c/ras2fim-runtime/ras_commander-0.99.2-py3-none-any.whl", False),
])
def test_release_profile_keeps_runtime_and_excludes_private_or_temporary_files(monkeypatch, relative, excluded):
    # bundle_profile imports the controller as ``prepare``; restore sys.modules after.
    monkeypatch.setitem(sys.modules, "prepare", load_container_script("prepare"))
    bundle = load_container_script("bundle_profile")
    assert bundle.excluded_path(relative, "6.5") is excluded


def test_release_profile_destination_must_stay_outside_the_repository(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "prepare", load_container_script("prepare"))
    bundle = load_container_script("bundle_profile")
    source = tmp_path / "profile"
    source.mkdir()
    with pytest.raises(bundle.JobError, match="outside the source repository"):
        bundle.export_profile(source, REPO_ROOT / "working" / "release", "6.5")


def test_wine_environment_disables_openmp_affinity_unless_set(tmp_path):
    prepare = load_container_script("prepare")
    environment, record = prepare.wine_environment(tmp_path / "prefix", {"RAS_COMMANDER_WINE_CPU_SHIM": "0"})
    assert environment["KMP_AFFINITY"] == "disabled" and record["KMP_AFFINITY"] == "disabled"
    kept, _ = prepare.wine_environment(tmp_path / "prefix",
                                       {"RAS_COMMANDER_WINE_CPU_SHIM": "0", "KMP_AFFINITY": "compact"})
    assert kept["KMP_AFFINITY"] == "compact"


def test_controller_accepts_every_gridded_preprocessing_signal():
    """The controller must accept RasPreprocess's gridded-precipitation early stops."""
    import re as _re
    from pathlib import Path as _Path
    prepare = load_container_script("prepare")
    source = (_Path(__file__).resolve().parents[1] / "ras_commander" / "RasPreprocess.py").read_text()
    gridded = set(_re.findall(r'"((?:bco_)?completepreprocess_writer_quiescent)"', source))
    assert gridded == {"completepreprocess_writer_quiescent", "bco_completepreprocess_writer_quiescent"}
    assert gridded <= prepare.ACCEPTED_SIGNALS
    assert {"timeout", "blocked_legal_dialog", "natural_completion", "full_result_copy"}.isdisjoint(
        prepare.ACCEPTED_SIGNALS)
