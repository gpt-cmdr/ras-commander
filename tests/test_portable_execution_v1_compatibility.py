"""Compatibility with retained ras-commander 0.97.0 portable execution outputs.

The fixtures in ``tests/data/portable_execution`` are synthetic but keep the
exact key structure (every nesting level) of a request, a successful receipt,
a Slurm submission handle, and a Slurm batch manifest written by the 0.97.0
wheel used for a 436-unit production Slurm run. Identifiers, digests, hosts,
and paths are synthetic. ``execution_receipt.json`` binds
``runtime_project/SAMPLE CREEK.p02.hdf`` to the SHA-256 of ``_RESULT_BYTES``.
"""

from dataclasses import fields
import json
from pathlib import Path
import shutil
import subprocess
import sys

from ras_commander.RasSlurm import (
    SLURM_BATCH_SCHEMA,
    SLURM_SUBMISSION_SCHEMA,
    SlurmSiteConfig,
    SlurmSubmission,
    SlurmTransportConfig,
)
from ras_commander.remote import portable_slurm_launcher
from ras_commander.remote.ExecutionContract import (
    RECEIPT_SCHEMA,
    REQUEST_SCHEMA,
    RasExecutionReceipt,
    RasExecutionRequest,
    validate_execution_receipt,
)


FIXTURES = Path(__file__).parent / "data" / "portable_execution"
_RESULT_BYTES = b"synthetic steady result hdf\n"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundles" / "run-0123456789abcdef"
    bundle.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "request.json", bundle / "request.json")
    output = bundle / "results"
    hdf = output / "runtime_project" / "SAMPLE CREEK.p02.hdf"
    hdf.parent.mkdir(parents=True)
    hdf.write_bytes(_RESULT_BYTES)
    shutil.copyfile(FIXTURES / "execution_receipt.json", output / "execution_receipt.json")
    return bundle / "request.json"


def test_v1_request_fields_schema_and_digest_are_stable():
    payload = _load("request.json")
    request = RasExecutionRequest.from_dict(payload)

    assert payload["schema"] == REQUEST_SCHEMA == "ras-commander-execution-request/v1"
    assert set(payload) == {item.name for item in fields(RasExecutionRequest)}
    assert request.to_dict() == payload
    # The canonical digest is what receipts and Slurm steps bind to.
    assert request.digest == _load("execution_receipt.json")["request_sha256"]
    assert request.digest == _load("slurm_batch.json")["steps"][0]["request_sha256"]


def test_v1_receipt_fields_schema_and_validation_are_stable(tmp_path):
    payload = _load("execution_receipt.json")
    receipt = RasExecutionReceipt(**payload)

    assert payload["schema"] == RECEIPT_SCHEMA == "ras-commander-execution-receipt/v1"
    assert set(payload) == {item.name for item in fields(RasExecutionReceipt)}
    assert receipt.to_dict() == payload
    assert receipt.success and receipt.hydraulic_validated
    assert set(payload["compute_diagnostics"]) >= {
        "completed",
        "has_errors",
        "fresh_result",
        "preprocessing",
        "source_validation",
    }

    request_path = _bundle(tmp_path)
    receipt_path = request_path.parent / "results" / "execution_receipt.json"
    validated = validate_execution_receipt(
        request_path,
        receipt_path,
        expected_runtime_identity=payload["runtime_container_identity"],
        verify_result_hdf_digest=True,
    )
    assert validated == receipt


def test_v1_slurm_submission_handle_round_trips(tmp_path):
    request_path = _bundle(tmp_path)
    payload = _load("slurm_submission.json")
    text = json.dumps(payload).replace(
        "__SUBMISSION_DIRECTORY__", tmp_path.resolve().as_posix()
    )
    payload = json.loads(text)

    submission = SlurmSubmission.from_dict(payload)

    assert payload["schema"] == SLURM_SUBMISSION_SCHEMA
    assert set(payload["site"]) == {item.name for item in fields(SlurmSiteConfig)}
    assert set(payload["transport"]) == {
        item.name for item in fields(SlurmTransportConfig)
    }
    assert submission.request_paths == (request_path.resolve(),)
    assert submission.transport.transfer_mode == "scp"
    assert SlurmSubmission.from_dict(submission.to_dict()) == submission


def test_v1_slurm_batch_steps_are_accepted_by_the_launcher():
    payload = _load("slurm_batch.json")

    assert payload["schema"] == SLURM_BATCH_SCHEMA
    assert payload["launcher"]["version"] == portable_slurm_launcher.LAUNCHER_VERSION
    assert set(payload["site"]) == {item.name for item in fields(SlurmSiteConfig)}
    for step in payload["steps"]:
        portable_slurm_launcher._validate_step(step)


def test_public_exports_resolve_to_classes_after_submodule_imports():
    code = (
        "import ras_commander.RasSlurm, ras_commander.remote.RasPortableDocker\n"
        "import ras_commander as rc, ras_commander.remote as remote, inspect\n"
        "names = ('RasSlurm', 'SlurmSiteConfig', 'SlurmSubmission', 'RasPortableDocker',\n"
        "         'RasExecutionRequest', 'RasExecutionReceipt', 'validate_execution_receipt')\n"
        "for name in names:\n"
        "    assert name in rc.__all__ and name in remote.__all__, name\n"
        "    for owner in (rc, remote):\n"
        "        value = getattr(owner, name)\n"
        "        assert inspect.isclass(value) or inspect.isfunction(value), (owner, name, value)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
