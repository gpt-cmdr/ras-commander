from pathlib import Path

import pandas as pd
import pytest

from ras_commander.ComputeResults import ComputeResult
from ras_commander.remote.ExecutionContract import (
    PreprocessPolicy,
    RasExecutionReceipt,
    RasExecutionRequest,
    sha256_tree,
)
from ras_commander.remote import PortableExecution


OCI = "registry.example/hecras/steady@sha256:" + "a" * 64


def _request(tmp_path: Path, policy=PreprocessPolicy.REBUILD) -> Path:
    bundle = tmp_path / "bundle"
    source = bundle / "input" / "sample.prj"
    source.parent.mkdir(parents=True)
    source.write_text("Proj Title=sample\nCurrent Plan=p01\nPlan File=p01\n")
    (source.parent / "sample.p01").write_text(
        "Plan Title=portable\nGeom File=g01\nFlow File=f01\n"
    )
    (source.parent / "sample.g01").write_text("Geom Title=sample\n")
    (source.parent / "sample.f01").write_text("Flow Title=sample\n")
    (source.parent / "sample.c01").write_bytes(b"historic-c")
    (source.parent / "sample.g01.hdf").write_bytes(b"historic-geometry")
    (source.parent / "sample.p01.hdf").write_bytes(b"historic-result")
    request = RasExecutionRequest.create(
        execution_id="sample-001",
        request_directory=bundle,
        source_project_path="input/sample.prj",
        plan_number="1",
        output_directory="output/sample-001",
        ras_executable="/opt/hec-ras/Ras.exe",
        container_identity=OCI,
        preprocess_policy=policy,
        timeout_seconds=60,
    )
    return request.write(bundle / "request.json")


def test_request_is_portable_source_identified_and_one_core(tmp_path):
    path = _request(tmp_path)
    request = RasExecutionRequest.read(path)

    assert request.plan_number == "01"
    assert request.num_cores == 1
    assert request.source_project_path == "input/sample.prj"
    assert request.output_directory == "output/sample-001"
    assert len(request.digest) == 64
    assert request.resolve_paths(path)[0].name == "sample.prj"


def test_request_accepts_conservative_absolute_windows_ras_executable(tmp_path):
    path = _request(tmp_path)
    payload = RasExecutionRequest.read(path).to_dict()
    payload["ras_executable"] = (
        r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe"
    )

    request = RasExecutionRequest.from_dict(payload)

    assert request.ras_executable.endswith(r"HEC-RAS\6.6\Ras.exe")


def test_request_accepts_immutable_sif_container_identity(tmp_path):
    path = _request(tmp_path)
    payload = RasExecutionRequest.read(path).to_dict()
    payload["container_identity"] = "sif:sha256:" + "b" * 64

    request = RasExecutionRequest.from_dict(payload)

    assert request.container_identity == payload["container_identity"]


def test_source_tree_hash_excludes_declared_output_tree(tmp_path):
    path = _request(tmp_path)
    request = RasExecutionRequest.read(path)
    source, output = request.resolve_paths(path)
    output.mkdir(parents=True)
    (output / "generated.txt").write_text("result")

    assert sha256_tree(source.parent) == request.source_tree_sha256


def test_copy_and_digest_binds_the_exact_runtime_bytes(tmp_path):
    path = _request(tmp_path)
    request = RasExecutionRequest.read(path)
    source, _ = request.resolve_paths(path)
    source_root = source.parent
    expected_files = {
        item.relative_to(source_root): item.read_bytes()
        for item in source_root.rglob("*")
        if item.is_file()
    }

    runtime_root = tmp_path / "runtime-copy"
    tree_digest, project_digest = PortableExecution._copytree_with_file_digest(
        source_root,
        runtime_root,
        source,
    )

    assert tree_digest == request.source_tree_sha256
    assert project_digest == request.source_project_sha256
    assert {
        item.relative_to(runtime_root): item.read_bytes()
        for item in runtime_root.rglob("*")
        if item.is_file()
    } == expected_files


@pytest.mark.parametrize(
    ("source", "output"),
    [
        ("../sample.prj", "output/run"),
        ("input/sample.prj", "../output"),
        ("C:/sample.prj", "output/run"),
    ],
)
def test_request_rejects_paths_outside_bundle(tmp_path, source, output):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    with pytest.raises(ValueError):
        RasExecutionRequest.create(
            execution_id="run",
            request_directory=bundle,
            source_project_path=source,
            plan_number="01",
            output_directory=output,
            ras_executable="/opt/hec-ras/Ras.exe",
            container_identity=OCI,
        )


def test_request_rejects_non_one_core_and_unknown_fields(tmp_path):
    path = _request(tmp_path)
    payload = RasExecutionRequest.read(path).to_dict()
    payload["num_cores"] = 2
    with pytest.raises(ValueError, match="num_cores=1"):
        RasExecutionRequest.from_dict(payload)
    payload["num_cores"] = 1
    payload["surprise"] = True
    with pytest.raises(TypeError):
        RasExecutionRequest.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ras_executable", '/opt/ras/Ras.exe";touch /tmp/x'),
        ("ras_executable", r"C:\HEC-RAS\..\Windows\Ras.exe"),
        ("ras_executable", r"C:\HEC-RAS\Ras.exe & calc.exe"),
        ("container_identity", "registry.example/hecras:latest"),
        ("source_project_path", "input,evil/sample.prj"),
        ("output_directory", "output:evil/run"),
    ],
)
def test_request_rejects_executable_image_and_mount_injection(tmp_path, field, value):
    path = _request(tmp_path)
    payload = RasExecutionRequest.read(path).to_dict()
    payload[field] = value
    with pytest.raises(ValueError):
        RasExecutionRequest.from_dict(payload)


def test_execute_request_rejects_source_tampering(tmp_path):
    path = _request(tmp_path)
    source, _ = RasExecutionRequest.read(path).resolve_paths(path)
    source.write_text(source.read_text() + "tampered\n")
    with pytest.raises(ValueError, match="hash"):
        PortableExecution.execute_request(path)


@pytest.mark.parametrize(
    "policy",
    [
        PreprocessPolicy.REUSE,
        PreprocessPolicy.REBUILD,
        PreprocessPolicy.FORCE_REBUILD,
    ],
)
def test_execute_request_maps_preprocessing_and_preserves_source(
    tmp_path, monkeypatch, policy
):
    path = _request(tmp_path, policy)
    request = RasExecutionRequest.read(path)
    source, output = request.resolve_paths(path)
    before = source.read_bytes()
    seen = {}
    hash_counts = {"source_tree": 0, "result_hdf": 0}
    original_tree_hash = PortableExecution._copytree_with_file_digest
    original_file_hash = PortableExecution.sha256_file

    def hash_tree_once(*args, **kwargs):
        hash_counts["source_tree"] += 1
        return original_tree_hash(*args, **kwargs)

    def hash_result_once(path):
        hash_counts["result_hdf"] += 1
        return original_file_hash(path)

    def initialize(self, project_folder, ras_exe_path, **kwargs):
        self.project_folder = Path(project_folder)
        self.project_name = "sample"
        self.prj_file = self.project_folder / "sample.prj"
        self.ras_exe_path = ras_exe_path
        self.initialized = True
        self.plan_df = pd.DataFrame(
            [{"plan_number": "01", "Flow Path": self.project_folder / "sample.f01"}]
        )

    def compute(plan_number, **kwargs):
        seen.update(kwargs)
        project = kwargs["ras_object"].project_folder
        if policy is not PreprocessPolicy.REUSE:
            (project / "sample.c01").write_bytes(b"fresh-c")
        if policy is PreprocessPolicy.FORCE_REBUILD:
            (project / "sample.g01.hdf").write_bytes(b"fresh-geometry")
        hdf = project / "sample.p01.hdf"
        hdf.write_bytes(b"test-hdf")
        return ComputeResult(success=True)

    monkeypatch.setattr(PortableExecution.RasPrj, "initialize", initialize)
    monkeypatch.setattr(PortableExecution, "_copytree_with_file_digest", hash_tree_once)
    monkeypatch.setattr(PortableExecution, "sha256_file", hash_result_once)
    monkeypatch.setattr(
        PortableExecution.RasPlan, "is_plan_steady_state", lambda *a, **k: True
    )
    monkeypatch.setattr(PortableExecution.RasCmdr, "compute_plan", compute)
    monkeypatch.setattr(
        PortableExecution.HdfResultsPlan,
        "get_compute_messages_hdf_only",
        lambda path: "Complete Process\nWarning: review",
    )
    monkeypatch.setattr(
        PortableExecution,
        "validate_steady_results",
        lambda *args, **kwargs: {"passed": True, "reason_codes": []},
    )

    receipt = PortableExecution.execute_request(path)

    assert receipt.success
    assert seen["num_cores"] == 1
    assert seen["clear_geompre"] is False
    assert seen["force_geompre"] is False
    assert seen["verify"] is True
    assert seen["max_runtime"] == 60.0
    assert source.read_bytes() == before
    assert receipt.source_unchanged
    assert receipt.solver_verified
    assert receipt.hydraulic_validated
    assert receipt.compute_diagnostics["preprocessing"]["passed"]
    assert receipt.compute_diagnostics["source_validation"] == {
        "passed": True,
        "method": "single-pass-runtime-copy-and-hash",
        "post_compute_rehash": False,
        "execution_target": "isolated-runtime-copy",
    }
    assert receipt.compute_diagnostics["fresh_result"]["passed"]
    assert receipt.compute_diagnostics["fresh_result"]["prior_hdf"] is not None
    assert receipt.compute_messages_sha256 is None
    assert hash_counts == {"source_tree": 1, "result_hdf": 1}
    assert (output / "runtime_project" / "sample.prj").is_file()
    assert (output / "execution_receipt.json").is_file()
    assert (output / "compute_messages.txt").is_file()


def test_reuse_compares_stats_and_rejects_changed_compiled_artifact(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    project = runtime / "sample.prj"
    project.write_text("project")
    plan = runtime / "sample.p01"
    plan.write_text("Geom File=g01\n")
    compiled = runtime / "sample.c01"
    compiled.write_bytes(b"qualified")

    evidence, retained = PortableExecution._prepare_preprocessing(
        PreprocessPolicy.REUSE.value, project, plan
    )
    compiled.write_bytes(b"changed")

    assert not PortableExecution._complete_preprocessing_evidence(
        evidence, retained, 0
    )
    assert evidence["retained_unchanged"] is False
    assert "sha256" not in evidence["retained_artifacts_before"][0]


def test_rebuild_accepts_fresh_geometry_hdf_without_legacy_compiled_file(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    project = runtime / "sample.prj"
    project.write_text("project")
    plan = runtime / "sample.p01"
    plan.write_text("Geom File=g01\n")

    evidence, candidates = PortableExecution._prepare_preprocessing(
        PreprocessPolicy.REBUILD.value, project, plan
    )
    (runtime / "sample.g01.hdf").write_bytes(b"fresh-geometry")

    assert PortableExecution._complete_preprocessing_evidence(evidence, candidates, 0)
    assert evidence["generated_artifacts"] == [
        {
            "path": "sample.g01.hdf",
            "size_bytes": len(b"fresh-geometry"),
            "mtime_ns": (runtime / "sample.g01.hdf").stat().st_mtime_ns,
            "fresh_for_run": True,
            "created_after_verified_absence": True,
        }
    ]


def test_preprocess_clear_failure_cannot_yield_success(tmp_path, monkeypatch):
    path = _request(tmp_path, PreprocessPolicy.REBUILD)
    original_unlink = Path.unlink
    solver_called = False

    def unlink(item, *args, **kwargs):
        if item.name == "sample.c01" and item.parent.name == "runtime_project":
            raise PermissionError("locked preprocessor artifact")
        return original_unlink(item, *args, **kwargs)

    def compute(*args, **kwargs):
        nonlocal solver_called
        solver_called = True
        return ComputeResult(success=True)

    def initialize(self, project_folder, ras_exe_path, **kwargs):
        self.project_folder = Path(project_folder)
        self.project_name = "sample"
        self.prj_file = self.project_folder / "sample.prj"
        self.ras_exe_path = ras_exe_path
        self.initialized = True
        self.plan_df = pd.DataFrame(
            [{"plan_number": "01", "Flow Path": self.project_folder / "sample.f01"}]
        )

    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(PortableExecution.RasPrj, "initialize", initialize)
    monkeypatch.setattr(
        PortableExecution.RasPlan, "is_plan_steady_state", lambda *a, **k: True
    )
    monkeypatch.setattr(PortableExecution.RasCmdr, "compute_plan", compute)

    receipt = PortableExecution.execute_request(path)

    assert not receipt.success
    assert not solver_called
    assert "locked preprocessor artifact" in receipt.error


def test_successful_receipt_requires_complete_evidence(tmp_path):
    request_path = _request(tmp_path)
    request = RasExecutionRequest.read(request_path)
    with pytest.raises(ValueError, match="requires solver"):
        RasExecutionReceipt(
            execution_id=request.execution_id,
            request_sha256=request.digest,
            container_identity=request.container_identity,
            runtime_container_identity=request.container_identity,
            success=True,
            status="succeeded",
            started_at="2026-09-13T00:00:00Z",
            finished_at="2026-09-13T00:00:01Z",
            source_tree_sha256_before=request.source_tree_sha256,
            source_tree_sha256_after=request.source_tree_sha256,
            source_unchanged=True,
            solver_verified=True,
            hydraulic_validated=True,
            result_validation={"passed": True},
        )


def test_execute_request_records_nonsteady_failure_without_solver(tmp_path, monkeypatch):
    path = _request(tmp_path)

    def initialize(self, project_folder, ras_exe_path, **kwargs):
        self.project_folder = Path(project_folder)
        self.project_name = "sample"
        self.prj_file = self.project_folder / "sample.prj"
        self.initialized = True

    monkeypatch.setattr(PortableExecution.RasPrj, "initialize", initialize)
    monkeypatch.setattr(
        PortableExecution.RasPlan, "is_plan_steady_state", lambda *a, **k: False
    )
    receipt = PortableExecution.execute_request(path)

    assert not receipt.success
    assert "not classified as a steady plan" in receipt.error


def test_execute_request_refuses_nonempty_output(tmp_path):
    path = _request(tmp_path)
    _, output = RasExecutionRequest.read(path).resolve_paths(path)
    output.mkdir(parents=True)
    (output / "foreign.txt").write_text("do not overwrite")

    with pytest.raises(ValueError, match="absent or empty"):
        PortableExecution.execute_request(path)


def test_delegated_wine_allows_only_its_single_active_task_root(
    tmp_path, monkeypatch
):
    path = _request(tmp_path)
    request = RasExecutionRequest.read(path)
    _, output = request.resolve_paths(path)
    task_root = output / ".ras-wine-runtime-sample-001-abcdef12"
    prefix = task_root / "prefix"
    prefix.mkdir(parents=True)
    monkeypatch.setenv("RAS_COMMANDER_WINE_DELEGATED", "1")
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_WINDOWS", str(prefix.resolve()))

    PortableExecution._validate_initial_output(output, request)

    (output / "foreign.txt").write_text("not part of the task runtime")
    with pytest.raises(ValueError, match="absent or empty"):
        PortableExecution._validate_initial_output(output, request)


def test_delegated_wine_rejects_wrong_execution_task_root(tmp_path, monkeypatch):
    path = _request(tmp_path)
    request = RasExecutionRequest.read(path)
    _, output = request.resolve_paths(path)
    prefix = output / ".ras-wine-runtime-other-abcdef12" / "prefix"
    prefix.mkdir(parents=True)
    monkeypatch.setenv("RAS_COMMANDER_WINE_DELEGATED", "1")
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_WINDOWS", str(prefix.resolve()))

    with pytest.raises(ValueError, match="absent or empty"):
        PortableExecution._validate_initial_output(output, request)


def test_validate_steady_results_compares_effective_flow_schedule(monkeypatch):
    authored = {
        "profile_names": ["PF 1", "PF 2"],
        "flow_changes": [
            {
                "river": "River",
                "reach": "Reach",
                "station": "1000",
                "flows": [100, 200],
            },
            {
                "river": "River",
                "reach": "Reach",
                "station": "500",
                "flows": [150, 250],
            },
        ],
    }
    rows = pd.DataFrame(
        [
            {"river": "River", "reach": "Reach", "node_id": "900", "profile": "PF 1", "flow": 100.005, "wsel": 11.0},
            {"river": "River", "reach": "Reach", "node_id": "400", "profile": "PF 1", "flow": 150.0, "wsel": 12.0},
            {"river": "River", "reach": "Reach", "node_id": "900", "profile": "PF 2", "flow": 200.0, "wsel": 13.0},
            {"river": "River", "reach": "Reach", "node_id": "400", "profile": "PF 2", "flow": 250.0, "wsel": 14.0},
        ]
    )
    monkeypatch.setattr(
        PortableExecution.RasSteady, "read_flow_file", lambda path: authored
    )
    monkeypatch.setattr(
        PortableExecution.HdfResultsPlan,
        "get_steady_profile_names",
        lambda path: ["PF 1", "PF 2"],
    )
    monkeypatch.setattr(
        PortableExecution.HdfResultsPlan,
        "get_steady_results",
        lambda path: rows,
    )

    validation = PortableExecution.validate_steady_results(
        "result.hdf", "flow.f01"
    )

    assert validation["passed"]
    assert validation["flow_rows_compared"] == 4
    assert validation["flow_mismatch_count"] == 0
    assert validation["max_absolute_flow_mismatch"] == pytest.approx(0.005)


def test_validate_steady_results_fails_closed_on_mismatch_and_nonfinite(monkeypatch):
    authored = {
        "profile_names": ["PF 1"],
        "flow_changes": [
            {
                "river": "River",
                "reach": "Reach",
                "station": "1000",
                "flows": [100],
            }
        ],
    }
    rows = pd.DataFrame(
        [
            {"river": "River", "reach": "Reach", "node_id": "900", "profile": "PF 1", "flow": 120.0, "wsel": 11.0},
            {"river": "Other", "reach": "Reach", "node_id": "900", "profile": "PF 1", "flow": 100.0, "wsel": float("nan")},
        ]
    )
    monkeypatch.setattr(
        PortableExecution.RasSteady, "read_flow_file", lambda path: authored
    )
    monkeypatch.setattr(
        PortableExecution.HdfResultsPlan,
        "get_steady_profile_names",
        lambda path: ["PF 1"],
    )
    monkeypatch.setattr(
        PortableExecution.HdfResultsPlan,
        "get_steady_results",
        lambda path: rows,
    )

    validation = PortableExecution.validate_steady_results(
        "result.hdf", "flow.f01"
    )

    assert not validation["passed"]
    assert "STEADY_NONFINITE_WSEL" in validation["reason_codes"]
    assert "STEADY_FLOW_SCHEDULE_UNMATCHED" in validation["reason_codes"]
    assert "STEADY_FLOW_SCHEDULE_MISMATCH" in validation["reason_codes"]
