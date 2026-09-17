"""Optional ``stored_maps`` block for portable steady execution requests."""

import hashlib
import importlib
import json
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from ras_commander.ComputeResults import ComputeResult
from ras_commander.RasSlurm import RasSlurm, SlurmSiteConfig
from ras_commander.remote import PortableExecution
from ras_commander.remote.ExecutionContract import (
    STORED_MAPS_SCHEMA,
    RasExecutionReceipt,
    RasExecutionRequest,
    StoredMapsRequest,
    validate_execution_receipt,
)
from ras_commander.remote.RasPortableDocker import RasPortableDocker


OCI = "registry.example/hecras/steady@sha256:" + "a" * 64
LAUNCHER_SHA256 = "39fe0f12038e54be05ff4a58d5d91398189bfc00d543cd6164fc0765fcf2ffb1"
FIXTURES = Path(__file__).parent / "data" / "portable_execution"
MAPS = {"terrain_name": "Terrain 1m", "profiles": ["PF 1", 1], "timeout_seconds": 900}


def _request(tmp_path: Path, stored_maps=MAPS, execution_id="sample-001") -> Path:
    bundle = tmp_path / execution_id
    source = bundle / "input" / "sample.prj"
    source.parent.mkdir(parents=True)
    source.write_text("Proj Title=sample\nCurrent Plan=p01\nPlan File=p01\n")
    (source.parent / "sample.p01").write_text(
        "Plan Title=portable\nGeom File=g01\nFlow File=f01\n"
    )
    (source.parent / "sample.g01").write_text("Geom Title=sample\n")
    (source.parent / "sample.f01").write_text("Flow Title=sample\n")
    request = RasExecutionRequest.create(
        execution_id=execution_id,
        request_directory=bundle,
        source_project_path="input/sample.prj",
        plan_number="01",
        output_directory="results",
        ras_executable="/opt/hec-ras/Ras.exe",
        container_identity=OCI,
        timeout_seconds=60,
        stored_maps=stored_maps,
    )
    return request.write(bundle / "request.json")


# --------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------


def test_request_without_block_keeps_v1_bytes_and_digest():
    payload = json.loads((FIXTURES / "request.json").read_text(encoding="utf-8"))
    receipt = json.loads(
        (FIXTURES / "execution_receipt.json").read_text(encoding="utf-8")
    )

    request = RasExecutionRequest.from_dict(payload)

    assert "stored_maps" not in payload
    assert request.stored_maps is None
    assert request.to_dict() == payload
    assert request.digest == receipt["request_sha256"]
    assert request.execution_timeout_seconds == request.timeout_seconds
    assert "stored_maps" not in RasExecutionReceipt(**receipt).to_dict()


def test_request_with_block_round_trips_with_defaults(tmp_path):
    path = _request(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["stored_maps"] == {
        "inundation_boundary": False,
        "map_types": ["depth"],
        "mode": "steady_profiles",
        "profiles": ["PF 1", 1],
        "schema": STORED_MAPS_SCHEMA,
        "terrain_name": "Terrain 1m",
        "timeout_seconds": 900,
    }
    request = RasExecutionRequest.read(path)
    assert isinstance(request.stored_maps, StoredMapsRequest)
    assert request.to_dict() == payload
    assert request.execution_timeout_seconds == 960
    without = RasExecutionRequest.from_dict(
        {key: value for key, value in payload.items() if key != "stored_maps"}
    )
    assert without.digest != request.digest

    all_profiles = StoredMapsRequest(terrain_name="Terrain 1m")
    assert all_profiles.to_dict()["profiles"] is None


@pytest.mark.parametrize(
    "block",
    [
        {"terrain_name": "T", "surprise": True},
        {"terrain_name": "T", "schema": "ras-commander-stored-maps-request/v2"},
        {"terrain_name": "T", "mode": "timesteps"},
        {"terrain_name": ""},
        {"profiles": ["PF 1"]},
        {"terrain_name": "T", "profiles": []},
        {"terrain_name": "T", "profiles": "PF 1"},
        {"terrain_name": "T", "profiles": ["PF 1", "PF 1"]},
        {"terrain_name": "T", "profiles": [-1]},
        {"terrain_name": "T", "profiles": [True]},
        {"terrain_name": "T", "map_types": []},
        {"terrain_name": "T", "map_types": ["inundation_boundary"]},
        {"terrain_name": "T", "map_types": ["depth", "depth"]},
        {"terrain_name": "T", "inundation_boundary": "yes"},
        {"terrain_name": "T", "timeout_seconds": 0},
        {"terrain_name": "T", "timeout_seconds": True},
        None,
    ],
)
def test_stored_maps_block_is_strict(tmp_path, block):
    payload = json.loads(_request(tmp_path, stored_maps=None).read_text())
    payload["stored_maps"] = block
    with pytest.raises((TypeError, ValueError)):
        RasExecutionRequest.from_dict(payload)


# --------------------------------------------------------------------------
# execute_request with fakes
# --------------------------------------------------------------------------


class _Harness:
    def __init__(self, monkeypatch, *, hydraulic_passed=True, store=None):
        self.calls = []
        self.store_kwargs = None
        self.ras_objects = []
        harness = self

        def initialize(ras_self, project_folder, ras_exe_path, **kwargs):
            ras_self.project_folder = Path(project_folder)
            ras_self.project_name = "sample"
            ras_self.prj_file = ras_self.project_folder / "sample.prj"
            ras_self.ras_exe_path = ras_exe_path
            ras_self.initialized = True
            ras_self.plan_df = pd.DataFrame(
                [{"plan_number": "01", "Flow Path": ras_self.project_folder / "sample.f01"}]
            )
            harness.ras_objects.append(ras_self)
            harness.calls.append("initialize")

        def compute(plan_number, **kwargs):
            harness.calls.append("compute")
            project = kwargs["ras_object"].project_folder
            (project / "sample.c01").write_bytes(b"fresh-c")
            (project / "sample.p01.hdf").write_bytes(b"validated-result")
            return ComputeResult(success=True)

        def validate(*args, **kwargs):
            harness.calls.append("validate")
            return {
                "passed": hydraulic_passed,
                "reason_codes": [] if hydraulic_passed else ["STEADY_FLOW_SCHEDULE_MISMATCH"],
            }

        def default_store(plan_number, **kwargs):
            maps = Path(kwargs["output_path"])
            maps.mkdir(parents=True)
            rows = []
            for index, name in enumerate(("PF 1", "PF 2")):
                (maps / f"Depth ({name}).vrt").write_text("vrt")
                (maps / f"Depth ({name}).Terrain.tif").write_bytes(b"tif")
                rows.append(
                    {
                        "plan_number": plan_number,
                        "result_hdf_path": "ignored",
                        "profile_index": index,
                        "profile_name": name,
                        "map_type": "depth",
                        "output_mode": "Stored Current Terrain",
                        "primary_path": str(maps / f"Depth ({name}).vrt"),
                        "files": [],
                        "file_count": 2,
                    }
                )
            return pd.DataFrame(rows)

        def store_maps(plan_number, **kwargs):
            harness.calls.append("store_maps")
            harness.store_kwargs = dict(kwargs, plan_number=plan_number)
            return (store or default_store)(plan_number, **kwargs)

        process = importlib.import_module("ras_commander.RasProcess").RasProcess
        monkeypatch.setattr(PortableExecution.RasPrj, "initialize", initialize)
        monkeypatch.setattr(
            PortableExecution.RasPlan, "is_plan_steady_state", lambda *a, **k: True
        )
        monkeypatch.setattr(PortableExecution.RasCmdr, "compute_plan", compute)
        monkeypatch.setattr(
            PortableExecution.HdfResultsPlan,
            "get_compute_messages_hdf_only",
            lambda path: "Complete Process\n",
        )
        monkeypatch.setattr(PortableExecution, "validate_steady_results", validate)
        monkeypatch.setattr(process, "store_maps_at_steady_profiles", store_maps)


def test_maps_run_after_validation_on_fresh_runtime_project(tmp_path, monkeypatch):
    path = _request(tmp_path)
    harness = _Harness(monkeypatch)

    receipt = PortableExecution.execute_request(path)

    assert harness.calls == [
        "initialize",
        "compute",
        "validate",
        "initialize",
        "store_maps",
    ]
    compute_ras, maps_ras = harness.ras_objects
    assert maps_ras is not compute_ras
    output = path.parent / "results"
    assert maps_ras.project_folder == output / "runtime_project"
    kwargs = harness.store_kwargs
    assert kwargs["ras_object"] is maps_ras
    assert kwargs["plan_number"] == "01"
    assert kwargs["profiles"] == ["PF 1", 1]
    assert kwargs["map_types"] == ["depth"]
    assert kwargs["output_path"] == output / "maps"
    assert kwargs["terrain_name"] == "Terrain 1m"
    assert kwargs["inundation_boundary"] is False
    assert kwargs["timeout"] == 900

    assert receipt.success and receipt.hydraulic_validated and receipt.solver_verified
    section = receipt.stored_maps
    assert section["status"] == "passed"
    assert section["reason_code"] == "STORED_MAPS_COMPLETED"
    assert section["requested"] == RasExecutionRequest.read(path).stored_maps.to_dict()
    assert section["output_directory"] == "maps"
    assert section["error"] is None
    assert section["elapsed_seconds"] >= 0
    assert section["products"] == [
        {
            "profile_index": 0,
            "profile_name": "PF 1",
            "map_type": "depth",
            "primary_path": "maps/Depth (PF 1).vrt",
            "file_count": 2,
        },
        {
            "profile_index": 1,
            "profile_name": "PF 2",
            "map_type": "depth",
            "primary_path": "maps/Depth (PF 2).vrt",
            "file_count": 2,
        },
    ]
    written = RasExecutionReceipt.read(output / "execution_receipt.json")
    assert written == receipt
    assert validate_execution_receipt(
        path, output / "execution_receipt.json", verify_result_hdf_digest=True
    ) == receipt


def test_maps_are_skipped_when_hydraulics_fail(tmp_path, monkeypatch):
    path = _request(tmp_path)
    harness = _Harness(monkeypatch, hydraulic_passed=False)

    receipt = PortableExecution.execute_request(path)

    assert "store_maps" not in harness.calls
    assert not receipt.success
    assert receipt.solver_verified and not receipt.hydraulic_validated
    assert receipt.stored_maps["status"] == "skipped"
    assert (
        receipt.stored_maps["reason_code"]
        == "STORED_MAPS_SKIPPED_HYDRAULICS_NOT_VALIDATED"
    )
    assert receipt.stored_maps["products"] == []
    assert "hydraulic validation" in receipt.error


def _failing(exception):
    def store(plan_number, **kwargs):
        raise exception

    return store


@pytest.mark.parametrize(
    ("store", "reason"),
    [
        (_failing(RuntimeError("StoreAllMaps failed")), "STORED_MAPS_FAILED"),
        (
            _failing(subprocess.TimeoutExpired(["helper"], 900)),
            "STORED_MAPS_TIMEOUT",
        ),
        (lambda plan_number, **kwargs: pd.DataFrame(), "STORED_MAPS_OUTPUT_INVALID"),
    ],
)
def test_map_failure_keeps_hydraulic_evidence(tmp_path, monkeypatch, store, reason):
    path = _request(tmp_path)
    _Harness(monkeypatch, store=store)

    receipt = PortableExecution.execute_request(path)

    assert not receipt.success
    assert receipt.status == "failed"
    assert receipt.solver_verified and receipt.hydraulic_validated
    assert receipt.result_validation["passed"] is True
    assert receipt.result_hdf_sha256 == hashlib.sha256(b"validated-result").hexdigest()
    assert receipt.stored_maps["status"] == "failed"
    assert receipt.stored_maps["reason_code"] == reason
    assert receipt.stored_maps["error"]
    assert receipt.error.startswith(f"Stored maps failed ({reason})")
    output = path.parent / "results"
    # A failed-maps receipt is still a valid, bound receipt.
    assert validate_execution_receipt(path, output / "execution_receipt.json")


def test_products_outside_maps_directory_fail(tmp_path, monkeypatch):
    def store(plan_number, **kwargs):
        outside = Path(kwargs["output_path"]).parent / "Depth (PF 1).vrt"
        outside.write_text("vrt")
        return pd.DataFrame(
            [
                {
                    "profile_index": 0,
                    "profile_name": "PF 1",
                    "map_type": "depth",
                    "primary_path": str(outside),
                    "file_count": 1,
                }
            ]
        )

    path = _request(tmp_path)
    _Harness(monkeypatch, store=store)
    receipt = PortableExecution.execute_request(path)

    assert receipt.stored_maps["reason_code"] == "STORED_MAPS_OUTPUT_OUTSIDE_RESULTS"
    assert receipt.hydraulic_validated and not receipt.success


def test_mapping_that_rewrites_result_hdf_fails_closed(tmp_path, monkeypatch):
    harness_holder = {}

    def store(plan_number, **kwargs):
        ras_object = kwargs["ras_object"]
        (ras_object.project_folder / "sample.p01.hdf").write_bytes(b"rewritten")
        maps = Path(kwargs["output_path"])
        maps.mkdir(parents=True)
        (maps / "Depth (PF 1).vrt").write_text("vrt")
        harness_holder["called"] = True
        return pd.DataFrame(
            [
                {
                    "profile_index": 0,
                    "profile_name": "PF 1",
                    "map_type": "depth",
                    "primary_path": str(maps / "Depth (PF 1).vrt"),
                    "file_count": 1,
                }
            ]
        )

    path = _request(tmp_path)
    _Harness(monkeypatch, store=store)
    receipt = PortableExecution.execute_request(path)

    assert harness_holder["called"]
    assert receipt.stored_maps["reason_code"] == "STORED_MAPS_RESULT_HDF_CHANGED"
    assert not receipt.success and receipt.hydraulic_validated


def test_request_without_block_writes_no_stored_maps_section(tmp_path, monkeypatch):
    path = _request(tmp_path, stored_maps=None)
    harness = _Harness(monkeypatch)

    receipt = PortableExecution.execute_request(path)

    assert receipt.success
    assert "store_maps" not in harness.calls
    written = json.loads((path.parent / "results" / "execution_receipt.json").read_text())
    assert "stored_maps" not in written


# --------------------------------------------------------------------------
# Receipt validation
# --------------------------------------------------------------------------


def test_receipt_rejects_success_without_passed_maps_and_mismatched_block(
    tmp_path, monkeypatch
):
    path = _request(tmp_path)
    _Harness(monkeypatch)
    receipt = PortableExecution.execute_request(path)
    payload = receipt.to_dict()

    failed = json.loads(json.dumps(payload))
    failed["stored_maps"]["status"] = "failed"
    failed["stored_maps"]["reason_code"] = "STORED_MAPS_FAILED"
    with pytest.raises(ValueError, match="passed stored_maps"):
        RasExecutionReceipt(**failed)

    escaped = json.loads(json.dumps(payload))
    escaped["stored_maps"]["products"][0]["primary_path"] = "../outside.vrt"
    with pytest.raises(ValueError):
        RasExecutionReceipt(**escaped)

    output = path.parent / "results"
    (output / "maps" / "Depth (PF 2).vrt").unlink()
    with pytest.raises(ValueError, match="product is missing"):
        validate_execution_receipt(path, output / "execution_receipt.json")

    missing = json.loads(json.dumps(payload))
    missing.pop("stored_maps")
    RasExecutionReceipt(**missing).write(output / "execution_receipt.json")
    with pytest.raises(ValueError, match="missing the requested stored_maps"):
        validate_execution_receipt(path, output / "execution_receipt.json")


# --------------------------------------------------------------------------
# Timeout budgets
# --------------------------------------------------------------------------


def test_docker_timeout_includes_stored_maps_budget(tmp_path, monkeypatch):
    path = _request(tmp_path)
    seen = {}

    def run(command, **kwargs):
        if command[1:3] == ("image", "inspect"):
            return subprocess.CompletedProcess(command, 0, json.dumps([OCI]), "")
        seen["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 1, "", "no receipt")

    module = importlib.import_module("ras_commander.remote.RasPortableDocker")
    monkeypatch.setattr(module.subprocess, "run", run)
    RasPortableDocker.execute_request(path)

    assert seen["timeout"] == 60 + 900 + 120


def test_slurm_step_budget_includes_maps_and_launcher_is_unchanged(tmp_path):
    with_maps = _request(tmp_path / "inputs", execution_id="job-maps")
    without = _request(tmp_path / "inputs", stored_maps=None, execution_id="job-v1")
    site = SlurmSiteConfig(
        site_name="example",
        apptainer_image="/opt/images/hecras.sif",
        apptainer_image_sha256="b" * 64,
        container_identity=OCI,
    )

    submission = RasSlurm.render_submission(
        [with_maps, without], tmp_path / "submission", site=site
    )
    batch = json.loads((submission.submission_directory / "slurm_batch.json").read_text())

    assert [step["timeout_seconds"] for step in batch["steps"]] == [960, 60]
    assert submission.launcher_sha256 == LAUNCHER_SHA256


def test_wine_handoff_timeout_includes_stored_maps_budget(tmp_path, monkeypatch):
    cli = importlib.import_module("ras_commander.remote.execute_request")
    bundle = tmp_path / "bundle"
    source = bundle / "input" / "sample.prj"
    source.parent.mkdir(parents=True)
    source.write_text("Proj Title=sample\n")
    request = RasExecutionRequest.create(
        execution_id="sample-001",
        request_directory=bundle,
        source_project_path="input/sample.prj",
        plan_number="01",
        output_directory="results",
        ras_executable=r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe",
        container_identity=OCI,
        timeout_seconds=60,
        stored_maps=MAPS,
    )
    request_path = request.write(bundle / "request.json")
    seed = tmp_path / "seed"
    seed.mkdir()
    monkeypatch.setenv("RAS_COMMANDER_WINE_PREFIX_SEED", str(seed))
    monkeypatch.setenv("RAS_COMMANDER_WINE_PYTHON", r"C:\Python311\python.exe")
    monkeypatch.setattr(cli, "_is_linux", lambda: True)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    timeouts = {}

    def run(command, **kwargs):
        if command[0].endswith("winepath"):
            return subprocess.CompletedProcess(
                command, 0, stdout=r"Z:\job\request.json" + "\n", stderr=""
            )
        if command[0].endswith("xvfb-run"):
            timeouts["delegate"] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cli.subprocess, "run", run)

    assert cli.main(["execute-request", str(request_path)]) == 0
    assert timeouts["delegate"] == 60 + 900 + 300


def _one_row_store(name="PF 1", index=0, filename="Depth (PF 1).vrt", map_type="depth"):
    def store(plan_number, **kwargs):
        maps = Path(kwargs["output_path"])
        maps.mkdir(parents=True, exist_ok=True)
        (maps / filename).write_text("vrt")
        return pd.DataFrame(
            [
                {
                    "profile_index": index,
                    "profile_name": name,
                    "map_type": map_type,
                    "primary_path": str(maps / filename),
                    "file_count": 2,
                }
            ]
        )

    return store


@pytest.mark.parametrize(
    "store",
    [
        # Profile index 1 was requested but not returned.
        _one_row_store(),
        # A product type that was not requested.
        _one_row_store(map_type="velocity"),
    ],
)
def test_incomplete_or_unrequested_products_fail_without_losing_receipt(
    tmp_path, monkeypatch, store
):
    path = _request(tmp_path)
    _Harness(monkeypatch, store=store)

    receipt = PortableExecution.execute_request(path)

    assert receipt.stored_maps["status"] == "failed"
    assert receipt.stored_maps["reason_code"] == "STORED_MAPS_OUTPUT_INVALID"
    assert receipt.hydraulic_validated and not receipt.success
    assert (path.parent / "results" / "execution_receipt.json").is_file()


def test_builtin_timeout_error_is_a_timeout(tmp_path, monkeypatch):
    path = _request(tmp_path)
    _Harness(monkeypatch, store=_failing(TimeoutError("helper timed out")))

    receipt = PortableExecution.execute_request(path)

    assert receipt.stored_maps["reason_code"] == "STORED_MAPS_TIMEOUT"


def test_receipt_ties_maps_status_to_hydraulic_flags(tmp_path, monkeypatch):
    path = _request(tmp_path)
    _Harness(monkeypatch, hydraulic_passed=False)
    payload = PortableExecution.execute_request(path).to_dict()

    inconsistent = json.loads(json.dumps(payload))
    inconsistent["hydraulic_validated"] = True
    with pytest.raises(ValueError, match="skipped exactly when"):
        RasExecutionReceipt(**inconsistent)

    colon = json.loads(json.dumps(payload))
    colon["stored_maps"]["products"] = [
        {
            "profile_index": 0,
            "profile_name": "PF 1",
            "map_type": "depth",
            "primary_path": "maps/Depth.tif:stream",
            "file_count": 1,
        }
    ]
    with pytest.raises(ValueError, match="relative POSIX"):
        RasExecutionReceipt(**colon)


def test_incomplete_products_record_generated_partial_evidence(tmp_path, monkeypatch):
    process_module = importlib.import_module("ras_commander.RasProcess")

    def store(plan_number, **kwargs):
        maps = Path(kwargs["output_path"])
        maps.mkdir(parents=True)
        (maps / "Depth (PF 1).vrt").write_text("vrt")
        frame = pd.DataFrame(
            [
                {
                    "profile_index": 0,
                    "profile_name": "PF 1",
                    "map_type": "depth",
                    "primary_path": str(maps / "Depth (PF 1).vrt"),
                    "file_count": 2,
                    "status": "generated",
                },
                {
                    "profile_index": 1,
                    "profile_name": "PF 2",
                    "map_type": "depth",
                    "primary_path": None,
                    "file_count": 0,
                    "status": "missing",
                },
            ]
        )
        raise process_module.StoredMapProductsIncompleteError("missing PF 2", frame)

    path = _request(tmp_path)
    _Harness(monkeypatch, store=store)
    receipt = PortableExecution.execute_request(path)

    section = receipt.stored_maps
    assert section["status"] == "failed"
    assert section["reason_code"] == "STORED_MAPS_PRODUCT_MISSING"
    assert [row["primary_path"] for row in section["products"]] == [
        "maps/Depth (PF 1).vrt"
    ]
    assert receipt.hydraulic_validated and not receipt.success
