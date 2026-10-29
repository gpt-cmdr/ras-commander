"""Regression tests for the HEC-RAS 7.0.2 single-plan project declaration.

HEC-RAS 7.0.2 ``Ras.exe -c`` computes the project's listed plans in order and
ignores the requested plan, so ``RasCmdr.compute_plan`` and
``RasPreprocess.preprocess_plan`` expose only the requested ``Plan File=``
entry during the owned launch and restore the original project bytes
afterwards.  These tests exercise the real project-file format as a byte
transaction (CRLF, non-ASCII bytes, no trailing newline) and the two launch
routes with exact-path fake launchers; they are not hydraulic qualification.
"""

import importlib
import json
import os
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import h5py
import pandas as pd
import pytest

from ras_commander import _single_plan_project as single_plan
from ras_commander.RasCmdr import RasCmdr
from ras_commander.RasPreprocess import RasPreprocess
from ras_commander.RasTcu import RasTcu, TcuStatus


rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
raspreprocess_module = importlib.import_module("ras_commander.RasPreprocess")

# Real HEC-RAS project-file layout: CRLF records, Current Plan=p05, the
# requested plan listed second, latin-1 and UTF-8 bytes, no final newline.
PROJECT_BYTES = (
    b"Proj Title=R\xedo B\xe1lsamo dam break\r\n"
    b"Current Plan=p05\r\n"
    b"Default Exp/Contr=0.3,0.1\r\n"
    b"English Units\r\n"
    b"Geom File=g03\r\n"
    b"Unsteady File=u07\r\n"
    b"Plan File=p13\r\n"
    b"Plan File=p03\r\n"
    b"BEGIN DESCRIPTION:\r\n"
    b" Two plans; plan 03 is listed second \xe2\x80\x94 bytes stay as written\r\n"
    b"\r\n"
    b"END DESCRIPTION:\r\n"
    b"DSS Start Date=01JAN1999\r\n"
    b"DXF Filename="
)
FILTERED_BYTES = (
    PROJECT_BYTES.replace(b"Current Plan=p05\r\n", b"Current Plan=p03\r\n")
    .replace(b"Plan File=p13\r\n", b"")
)
PLAN_BYTES = b"Plan Title=fixture\r\nGeom File=g03\r\n"
RELEASE_702 = Path("HEC-RAS") / "7.0.2" / "Ras.exe"
RELEASE_701 = Path("HEC-RAS") / "7.0.1" / "Ras.exe"
OLD_TIMES_NS = (1_600_000_000_000_000_000, 1_600_000_000_000_000_000)


@pytest.fixture(autouse=True)
def simulated_engine_tcu(monkeypatch):
    monkeypatch.setattr(RasTcu, "status", staticmethod(
        lambda **kwargs: TcuStatus(True, "test", None, None, "simulated-accepted")))


def _write_project(folder: Path, *, name="Demo", data=PROJECT_BYTES, mode=0o640):
    folder.mkdir(parents=True, exist_ok=True)
    prj = folder / f"{name}.prj"
    prj.write_bytes(data)
    (folder / f"{name}.p03").write_bytes(PLAN_BYTES)
    (folder / f"{name}.p13").write_bytes(PLAN_BYTES)
    os.chmod(prj, mode)
    os.utime(prj, ns=OLD_TIMES_NS)
    return prj


def _declarations(data: bytes):
    return [
        line for line in data.split(b"\r\n")
        if line.startswith((b"Plan File=", b"Current Plan="))
    ]


def _residue(prj: Path):
    return sorted(p.name for p in prj.parent.iterdir() if ".single-plan." in p.name)


def _assert_pristine(prj: Path, data=PROJECT_BYTES, mode=0o640):
    status = os.stat(prj)
    assert prj.read_bytes() == data
    assert stat.S_IMODE(status.st_mode) == stat.S_IMODE(stat.S_IFREG | mode) or (
        os.name == "nt"
    )
    assert status.st_mtime_ns == OLD_TIMES_NS[1]
    assert _residue(prj) == []


def _make_executable(tmp_path: Path, relative: Path) -> Path:
    executable = tmp_path / relative
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"synthetic ras executable")
    return executable


def _live_owner():
    import psutil

    return {
        "pid": os.getpid(),
        "create_time": float(psutil.Process().create_time()),
        "host": socket.gethostname(),
    }


def _dead_owner():
    # A process identity that cannot be alive: an implausible pid paired with
    # a create time from 1970, which can never match a reused pid.
    return {"pid": 4_000_000 + os.getpid() % 1000, "create_time": 1.0,
            "host": socket.gethostname()}


def _write_claim(prj: Path, *, owner, original: bytes, filtered: bytes, mode=0o640):
    claim = prj.with_name(prj.name + single_plan.CLAIM_SUFFIX)
    claim.write_text(json.dumps({
        "format": single_plan.CLAIM_FORMAT,
        "owner": owner,
        "launch_owner": "test",
        "plan_number": "03",
        "project_path": str(prj),
        "backup_path": str(prj.with_name(prj.name + single_plan.BACKUP_SUFFIX)),
        "original_sha256": single_plan._sha256(original),
        "filtered_sha256": single_plan._sha256(filtered),
        "original_mode": mode,
        "created_at": "2026-10-29T00:00:00",
    }), encoding="utf-8")
    return claim


# ---------------------------------------------------------------- release gate

@pytest.mark.parametrize(
    "ras_exe_path, ras_version, expected",
    [
        (r"C:\Program Files (x86)\HEC\HEC-RAS\7.0.2\Ras.exe", None, True),
        (r"C:\Program Files (x86)\HEC\HEC-RAS\7.0.2\Ras.exe", "7.0.2", True),
        (r"C:\scratch\runtime\7.0.2\Ras.exe", "702", True),
        ("Ras.exe", "7.0.2", True),
        (r"C:\Program Files (x86)\HEC\HEC-RAS\7.0.1\Ras.exe", "7.0.1", False),
        (r"C:\Program Files (x86)\HEC\HEC-RAS\7.0\Ras.exe", "7.0", False),
        (r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe", "6.6", False),
        (r"C:\Program Files (x86)\HEC\HEC-RAS\5.0.7\Ras.exe", "5.0.7", False),
        (None, None, False),
    ],
)
def test_single_plan_project_gate_is_702_only(ras_exe_path, ras_version, expected):
    assert single_plan.single_plan_project_required(
        ras_exe_path=ras_exe_path, ras_version=ras_version
    ) is expected


# ------------------------------------------------------------ pure filtering

def test_filter_exposes_only_requested_plan_and_keeps_every_other_byte():
    filtered, summary = single_plan.filter_project_declaration(PROJECT_BYTES, "03")

    assert filtered == FILTERED_BYTES
    assert _declarations(filtered) == [b"Current Plan=p03", b"Plan File=p03"]
    assert summary["removed_plan_entries"] == ["p13"]
    assert summary["current_plan_before"] == ["p05"]
    assert summary["newline"] == "crlf"
    assert summary["inserted_current_plan"] is False
    # Non-ASCII bytes and the missing final newline survive untouched.
    assert b"R\xedo B\xe1lsamo" in filtered
    assert b"\xe2\x80\x94" in filtered
    assert filtered.endswith(b"DXF Filename=")


def test_filter_accepts_numeric_and_prefixed_plan_identifiers():
    for plan in (3, "3", "03", "p03", "P03"):
        filtered, _ = single_plan.filter_project_declaration(PROJECT_BYTES, plan)
        assert filtered == FILTERED_BYTES


def test_filter_inserts_current_plan_after_title_for_lf_projects():
    data = b"Proj Title=LF\nPlan File=p01\nPlan File=p02\nDSS File=dss\n"

    filtered, summary = single_plan.filter_project_declaration(data, "02")

    assert filtered == b"Proj Title=LF\nCurrent Plan=p02\nPlan File=p02\nDSS File=dss\n"
    assert summary["inserted_current_plan"] is True
    assert summary["newline"] == "lf"


@pytest.mark.parametrize(
    "data, plan, kind",
    [
        (PROJECT_BYTES, "04", "plan_missing"),
        (PROJECT_BYTES + b"\r\nPlan File=p03\r\n", "03", "plan_duplicated"),
    ],
)
def test_filter_rejects_missing_and_duplicated_declarations(data, plan, kind):
    with pytest.raises(single_plan.SinglePlanProjectError) as excinfo:
        single_plan.filter_project_declaration(data, plan, project_name="Demo.prj")
    assert excinfo.value.kind == kind
    assert "Demo.prj" in str(excinfo.value)


# ---------------------------------------------------------- file transaction

def test_apply_then_restore_returns_exact_bytes_mode_and_timestamp(tmp_path):
    prj = _write_project(tmp_path)
    transaction = single_plan.SinglePlanProjectTransaction(
        prj, "03", launch_owner="test"
    )

    transaction.apply()

    assert transaction.applied is True
    assert prj.read_bytes() == FILTERED_BYTES
    assert stat.S_IMODE(os.stat(prj).st_mode) == 0o640 or os.name == "nt"
    assert transaction.backup_path.read_bytes() == PROJECT_BYTES
    claim = json.loads(transaction.claim_path.read_text(encoding="utf-8"))
    assert claim["format"] == single_plan.CLAIM_FORMAT
    assert claim["owner"]["pid"] == os.getpid()
    assert claim["plan_number"] == "03"
    assert claim["original_sha256"] == single_plan._sha256(PROJECT_BYTES)
    assert claim["filtered_sha256"] == single_plan._sha256(FILTERED_BYTES)
    evidence = transaction.to_dict()
    assert evidence["removed_plan_entries"] == ["p13"]
    assert evidence["current_plan_before"] == ["p05"]
    assert evidence["restore"] is None

    outcome = transaction.restore()

    assert outcome.ok is True
    assert transaction.released is True
    _assert_pristine(prj)
    assert transaction.to_dict()["restore"]["proved"] is True
    # A second restore is a no-op that reports the cached outcome.
    assert transaction.restore() is outcome


def test_restore_runs_in_caller_finally_after_exception(tmp_path):
    prj = _write_project(tmp_path)
    transaction = single_plan.SinglePlanProjectTransaction(prj, "03")

    with pytest.raises(RuntimeError, match="launch exploded"):
        try:
            transaction.apply()
            assert prj.read_bytes() == FILTERED_BYTES
            raise RuntimeError("launch exploded")
        finally:
            assert transaction.restore().ok is True

    _assert_pristine(prj)


@pytest.mark.parametrize("plan, kind", [("04", "plan_missing"), ("03", "plan_duplicated")])
def test_invalid_declaration_fails_before_any_mutation(tmp_path, plan, kind):
    data = PROJECT_BYTES if kind == "plan_missing" else PROJECT_BYTES + b"\r\nPlan File=p03"
    prj = _write_project(tmp_path, data=data)
    transaction = single_plan.SinglePlanProjectTransaction(prj, plan)

    with pytest.raises(single_plan.SinglePlanProjectError) as excinfo:
        transaction.apply()

    assert excinfo.value.kind == kind
    assert transaction.applied is False
    _assert_pristine(prj, data=data)
    assert transaction.restore().ok is True
    _assert_pristine(prj, data=data)


def test_live_claim_from_another_launch_fails_closed(tmp_path):
    prj = _write_project(tmp_path)
    claim = _write_claim(prj, owner=_live_owner(), original=PROJECT_BYTES, filtered=FILTERED_BYTES)
    claim_bytes = claim.read_bytes()

    with pytest.raises(single_plan.SinglePlanProjectError) as excinfo:
        single_plan.SinglePlanProjectTransaction(prj, "03").apply()

    assert excinfo.value.kind == "claim_conflict"
    assert "still running" in str(excinfo.value)
    assert str(claim) in str(excinfo.value)
    assert claim.read_bytes() == claim_bytes
    assert prj.read_bytes() == PROJECT_BYTES
    assert _residue(prj) == [claim.name]


def test_stale_claim_with_intact_single_plan_project_is_recovered(tmp_path):
    prj = _write_project(tmp_path, data=FILTERED_BYTES)
    backup = prj.with_name(prj.name + single_plan.BACKUP_SUFFIX)
    backup.write_bytes(PROJECT_BYTES)
    _write_claim(prj, owner=_dead_owner(), original=PROJECT_BYTES, filtered=FILTERED_BYTES)
    transaction = single_plan.SinglePlanProjectTransaction(prj, "13")

    transaction.apply()

    # The stale predecessor's original (both plans) was recovered first, so
    # this launch could expose plan 13 and back up the full declaration.
    assert transaction.to_dict()["stale_claim_recovered"] is True
    assert transaction.backup_path.read_bytes() == PROJECT_BYTES
    assert _declarations(prj.read_bytes()) == [b"Current Plan=p13", b"Plan File=p13"]
    assert transaction.restore().ok is True
    assert prj.read_bytes() == PROJECT_BYTES
    assert _residue(prj) == []


def test_stale_claim_with_foreign_project_bytes_fails_closed(tmp_path):
    foreign = PROJECT_BYTES.replace(b"Plan File=p13\r\n", b"Plan File=p13\r\nPlan File=p14\r\n")
    prj = _write_project(tmp_path, data=foreign)
    backup = prj.with_name(prj.name + single_plan.BACKUP_SUFFIX)
    backup.write_bytes(PROJECT_BYTES)
    claim = _write_claim(prj, owner=_dead_owner(), original=PROJECT_BYTES, filtered=FILTERED_BYTES)

    with pytest.raises(single_plan.SinglePlanProjectError) as excinfo:
        single_plan.SinglePlanProjectTransaction(prj, "03").apply()

    assert excinfo.value.kind == "claim_conflict"
    assert "neither" in str(excinfo.value)
    assert prj.read_bytes() == foreign
    assert backup.read_bytes() == PROJECT_BYTES
    assert claim.exists()


def test_active_project_launch_is_refused_before_mutation(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    other = _write_project(tmp_path / "other", name="Other")
    ras_exe = r"C:\Program Files (x86)\HEC\HEC-RAS\7.0.2\Ras.exe"
    records = [
        ("Ras.exe", 4242, (f'"{ras_exe}"', "-c", f'"{other}"', f'"{other.with_suffix(".p13")}"'), None),
    ]
    monkeypatch.setattr(single_plan, "_engine_process_records", lambda: list(records))

    conflicts, complete = single_plan.active_project_launches(prj)
    assert (conflicts, complete) == ([], True)

    records.append(
        ("RasUnsteady64.exe", 4343, ("RasUnsteady64.exe", "b03"), str(prj.parent)),
    )
    with pytest.raises(single_plan.SinglePlanProjectError) as excinfo:
        single_plan.SinglePlanProjectTransaction(prj, "03").apply()
    assert excinfo.value.kind == "active_launch"
    assert "RasUnsteady64.exe (pid 4343)" in str(excinfo.value)
    _assert_pristine(prj)

    records[-1] = (
        "Ras.exe", 4444, (f'"{ras_exe}"', "-c", f'"{prj}"', f'"{prj.with_suffix(".p13")}"'), None,
    )
    with pytest.raises(single_plan.SinglePlanProjectError) as excinfo:
        single_plan.SinglePlanProjectTransaction(prj, "03").apply()
    assert excinfo.value.kind == "active_launch"
    _assert_pristine(prj)

    monkeypatch.setattr(single_plan, "_engine_process_records", lambda: None)
    with pytest.raises(single_plan.SinglePlanProjectError) as excinfo:
        single_plan.SinglePlanProjectTransaction(prj, "03").apply()
    assert excinfo.value.kind == "inventory_incomplete"
    _assert_pristine(prj)


def test_restoration_failure_keeps_backup_and_claim_with_recovery_path(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    transaction = single_plan.SinglePlanProjectTransaction(prj, "03")
    transaction.apply()
    real_write = single_plan._write_file_atomically

    def failing_write(path, data, mode):
        if Path(path) == prj and data == PROJECT_BYTES:
            raise PermissionError(13, "simulated locked project file")
        return real_write(path, data, mode)

    monkeypatch.setattr(single_plan, "_write_file_atomically", failing_write)

    outcome = transaction.restore()

    assert outcome.restored is False
    assert outcome.proved is False
    assert "simulated locked project file" in outcome.detail
    assert str(transaction.backup_path) in outcome.detail
    assert str(transaction.claim_path) in outcome.detail
    assert transaction.backup_path.read_bytes() == PROJECT_BYTES
    assert transaction.claim_path.exists()
    assert prj.read_bytes() == FILTERED_BYTES
    assert transaction.to_dict()["restore"]["restored"] is False
    # A following launch on the same project fails closed on the retained claim.
    with pytest.raises(single_plan.SinglePlanProjectError) as excinfo:
        single_plan.SinglePlanProjectTransaction(prj, "03").apply()
    assert excinfo.value.kind == "claim_conflict"


def test_unexpected_project_rewrite_is_preserved_and_original_restored(tmp_path):
    prj = _write_project(tmp_path)
    transaction = single_plan.SinglePlanProjectTransaction(prj, "03")
    transaction.apply()
    rewritten = FILTERED_BYTES + b"\r\nDSS Export Filename=changed-by-engine\r\n"
    prj.write_bytes(rewritten)

    outcome = transaction.restore()

    assert outcome.ok is True
    assert outcome.unexpected_rewrite_path is not None
    preserved = Path(outcome.unexpected_rewrite_path)
    assert preserved.parent == prj.parent
    assert preserved.read_bytes() == rewritten
    assert prj.read_bytes() == PROJECT_BYTES
    assert _residue(prj) == [preserved.name]
    assert str(preserved) in outcome.detail


def test_unproved_quiescence_retains_filtered_project_and_claim(tmp_path):
    prj = _write_project(tmp_path)
    transaction = single_plan.SinglePlanProjectTransaction(prj, "03")
    transaction.apply()

    outcome = transaction.restore(owned_quiescent=False)

    assert outcome.restored is False
    assert outcome.proved is False
    assert "could not be proved stopped" in outcome.detail
    assert prj.read_bytes() == FILTERED_BYTES
    assert transaction.backup_path.read_bytes() == PROJECT_BYTES
    assert transaction.claim_path.exists()
    with pytest.raises(single_plan.SinglePlanProjectError) as excinfo:
        single_plan.SinglePlanProjectTransaction(prj, "03").apply()
    assert excinfo.value.kind == "claim_conflict"
    assert prj.read_bytes() == FILTERED_BYTES


def test_lifecycle_finishes_once_and_uses_quiescence_proof(tmp_path):
    prj = _write_project(tmp_path)
    lifecycle = single_plan.SinglePlanLaunchLifecycle()
    assert lifecycle.pending is False
    assert lifecycle.finish() is None
    lifecycle.transaction = single_plan.SinglePlanProjectTransaction(prj, "03")
    lifecycle.transaction.apply()
    proofs = []
    lifecycle.prove_quiescent = lambda: proofs.append(True) or True

    first = lifecycle.finish()
    second = lifecycle.finish()

    assert first is second
    assert first.ok is True
    assert proofs == [True]
    _assert_pristine(prj)


# ------------------------------------------------------ RasCmdr.compute_plan

class _ComputeRas:
    """Minimal ras-like object for compute_plan route tests."""

    def __init__(self, project_folder: Path, executable: Path, version: str):
        self.project_folder = project_folder
        self.project_name = "Demo"
        self.prj_file = project_folder / "Demo.prj"
        self.ras_exe_path = executable
        self.ras_version = version
        self.refresh_calls = []
        self.plan_df = self.geom_df = self.flow_df = self.unsteady_df = None
        self.results_df = None

    def check_initialized(self):
        return None

    def get_plan_entries(self):
        self.refresh_calls.append("plan")
        return "plan_df"

    def get_geom_entries(self):
        self.refresh_calls.append("geom")
        return "geom_df"

    def get_flow_entries(self):
        self.refresh_calls.append("flow")
        return "flow_df"

    def get_unsteady_entries(self):
        self.refresh_calls.append("unsteady")
        return "unsteady_df"

    def update_results_df(self, plan_numbers=None):
        self.refresh_calls.append(("results", plan_numbers))


class _CopiedRas(_ComputeRas):
    """Stand-in for the RasPrj that compute_plan builds for a dest_folder copy."""

    def __init__(self):
        pass

    def initialize(self, project_folder, ras_exe_path, **kwargs):
        _ComputeRas.__init__(
            self, Path(project_folder), ras_exe_path, "7.0.2"
        )
        assert kwargs.get("prj_file") in (None, self.prj_file)


def _patch_compute_route(monkeypatch, *, wait=None, cancellation=None):
    """Exact-path fake launcher that records the project bytes it would read."""
    launches = []

    class FakePopen:
        pid = 2468

        def __init__(self, argv, **kwargs):
            project = Path(kwargs["cwd"]) / "Demo.prj"
            launches.append({
                "argv": argv,
                "cwd": kwargs["cwd"],
                "project_bytes": project.read_bytes(),
                "residue": _residue(project),
            })
            self.returncode = 0

        def wait(self, timeout=None):
            if wait is not None:
                return wait(self, timeout)
            return self.returncode

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(rascmdr_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(RasCmdr, "_launcher_create_time", staticmethod(lambda pid: 123.5))
    monkeypatch.setattr(
        RasCmdr, "_confirm_plan_solver_quiescence",
        staticmethod(lambda plan_number, ras_object: True),
    )
    monkeypatch.setattr(
        RasCmdr, "inspect_plan_processes",
        staticmethod(lambda plan_number, *, ras_object: SimpleNamespace(complete=True, matched=[])),
    )
    monkeypatch.setattr(
        RasCmdr, "_wait_for_async_plan_completion",
        staticmethod(lambda *args, **kwargs: True),
    )
    monkeypatch.setattr(
        RasCmdr, "_rasunsteady_process_running_for_tmp_hdf",
        staticmethod(lambda tmp_hdf_path: False),
    )
    monkeypatch.setattr(
        rascmdr_module.RasPlan, "get_plan_path",
        staticmethod(lambda plan_number, ras_object: Path(ras_object.project_folder) / "Demo.p03"),
    )
    monkeypatch.setattr(
        rascmdr_module.BcoMonitor, "enable_detailed_logging",
        staticmethod(lambda plan_path: None),
    )
    if cancellation is not None:
        monkeypatch.setattr(
            RasCmdr, "cancel_plan_exact",
            staticmethod(lambda plan_number, *, ras_object: cancellation),
        )
    return launches


def _cancellation(quiescence_confirmed):
    payload = {"plan_number": "03", "cancellation_attempted": True,
               "quiescence_confirmed": quiescence_confirmed}
    return SimpleNamespace(quiescence_confirmed=quiescence_confirmed, to_dict=lambda: dict(payload))


@pytest.mark.parametrize("use_dest_folder", [False, True])
def test_compute_plan_exposes_only_requested_plan_on_702(tmp_path, monkeypatch, use_dest_folder):
    source = tmp_path / "source"
    prj = _write_project(source)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _ComputeRas(source, executable, "7.0.2")
    launches = _patch_compute_route(monkeypatch)
    dest_folder = None
    if use_dest_folder:
        dest_folder = tmp_path / "copy"
        monkeypatch.setattr(rascmdr_module, "RasPrj", _CopiedRas)

    result = RasCmdr.compute_plan(
        "03", ras_object=ras_obj, dest_folder=dest_folder, force_rerun=True,
        verify=True, dialog_watchdog=False,
    )

    assert result.success is True
    assert result.completion_verified is True
    assert len(launches) == 1
    launch = launches[0]
    launched_project = Path(launch["cwd"]) / "Demo.prj"
    assert launched_project == (dest_folder / "Demo.prj" if use_dest_folder else prj)
    assert launch["project_bytes"] == FILTERED_BYTES
    assert _declarations(launch["project_bytes"]) == [b"Current Plan=p03", b"Plan File=p03"]
    assert launch["residue"] == ["Demo.prj.single-plan.claim", "Demo.prj.single-plan.orig"]
    assert launch["argv"].endswith(f'"{launched_project.resolve()}" "{(launched_project.parent / "Demo.p03").resolve()}"')
    # The original declaration is back before the result is returned.
    _assert_pristine(prj)
    if use_dest_folder:
        assert launched_project.read_bytes() == PROJECT_BYTES
        assert _residue(launched_project) == []
    details = result.execution_details
    assert details["failure_stage"] is None
    guard = details["single_plan_project"]
    assert guard["launch_owner"] == "RasCmdr.compute_plan"
    assert guard["plan_number"] == "03"
    assert guard["removed_plan_entries"] == ["p13"]
    assert guard["applied"] is True and guard["released"] is True
    assert guard["restore"]["restored"] is True and guard["restore"]["proved"] is True


def test_compute_plan_timeout_restores_project_and_releases_claim(tmp_path, monkeypatch):
    source = tmp_path / "source"
    prj = _write_project(source)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _ComputeRas(source, executable, "7.0.2")

    def hang(process, timeout):
        raise subprocess.TimeoutExpired("Ras.exe", timeout)

    launches = _patch_compute_route(monkeypatch, wait=hang, cancellation=_cancellation(True))

    result = RasCmdr.compute_plan(
        "03", ras_object=ras_obj, force_rerun=True, max_runtime=5, dialog_watchdog=False,
    )

    assert result.success is False
    assert len(launches) == 1
    assert launches[0]["project_bytes"] == FILTERED_BYTES
    details = result.execution_details
    assert details["failure_type"] == "TimeoutError"
    assert details["runtime_timed_out"] is True
    assert details["solver_quiescence_confirmed"] is True
    assert details["single_plan_project"]["restore"]["proved"] is True
    _assert_pristine(prj)


def test_compute_plan_unproved_cancellation_retains_filtered_project_and_claim(tmp_path, monkeypatch):
    source = tmp_path / "source"
    prj = _write_project(source)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _ComputeRas(source, executable, "7.0.2")

    def hang(process, timeout):
        raise subprocess.TimeoutExpired("Ras.exe", timeout)

    _patch_compute_route(monkeypatch, wait=hang, cancellation=_cancellation(False))

    result = RasCmdr.compute_plan(
        "03", ras_object=ras_obj, force_rerun=True, max_runtime=5, dialog_watchdog=False,
    )

    assert result.success is False
    details = result.execution_details
    assert details["failure_type"] == "TimeoutError"
    assert details["solver_quiescence_confirmed"] is False
    restore = details["single_plan_project"]["restore"]
    assert restore["restored"] is False
    assert restore["proved"] is False
    assert prj.read_bytes() == FILTERED_BYTES
    assert _residue(prj) == ["Demo.prj.single-plan.claim", "Demo.prj.single-plan.orig"]
    assert (source / "Demo.prj.single-plan.orig").read_bytes() == PROJECT_BYTES
    # The unconfirmed launch blocks DataFrame refresh and the next guarded launch.
    assert ras_obj.refresh_calls == []


def test_compute_plan_restore_failure_fails_an_otherwise_successful_run(tmp_path, monkeypatch):
    source = tmp_path / "source"
    prj = _write_project(source)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _ComputeRas(source, executable, "7.0.2")
    _patch_compute_route(monkeypatch)
    real_write = single_plan._write_file_atomically

    def failing_write(path, data, mode):
        if Path(path) == prj and data == PROJECT_BYTES:
            raise PermissionError(13, "simulated locked project file")
        return real_write(path, data, mode)

    monkeypatch.setattr(single_plan, "_write_file_atomically", failing_write)

    result = RasCmdr.compute_plan(
        "03", ras_object=ras_obj, force_rerun=True, dialog_watchdog=False,
    )

    assert result.success is False
    details = result.execution_details
    assert details["failure_stage"] == "single_plan_project_restore"
    assert details["failure_type"] == "SinglePlanProjectRestoreError"
    assert str(source / "Demo.prj.single-plan.orig") in details["failure_detail"]
    assert prj.read_bytes() == FILTERED_BYTES
    assert (source / "Demo.prj.single-plan.orig").read_bytes() == PROJECT_BYTES
    assert (source / "Demo.prj.single-plan.claim").exists()


def test_compute_plan_invalid_declaration_fails_before_launch(tmp_path, monkeypatch):
    source = tmp_path / "source"
    data = PROJECT_BYTES.replace(b"Plan File=p03\r\n", b"")
    prj = _write_project(source, data=data)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _ComputeRas(source, executable, "7.0.2")
    launches = _patch_compute_route(monkeypatch)

    result = RasCmdr.compute_plan(
        "03", ras_object=ras_obj, force_rerun=True, dialog_watchdog=False,
    )

    assert result.success is False
    assert launches == []
    details = result.execution_details
    assert details["calculation_attempted"] is False
    assert details["failure_stage"] == "single_plan_project_guard"
    assert details["failure_type"] == "SinglePlanProjectError"
    assert "does not declare 'Plan File=p03'" in details["failure_detail"]
    assert details["single_plan_project"]["applied"] is False
    _assert_pristine(prj, data=data)


def test_compute_plan_prior_release_leaves_project_untouched(tmp_path, monkeypatch):
    source = tmp_path / "source"
    prj = _write_project(source)
    executable = _make_executable(tmp_path, RELEASE_701)
    ras_obj = _ComputeRas(source, executable, "7.0.1")
    launches = _patch_compute_route(monkeypatch)

    result = RasCmdr.compute_plan(
        "03", ras_object=ras_obj, force_rerun=True, dialog_watchdog=False,
    )

    assert result.success is True
    assert len(launches) == 1
    assert launches[0]["project_bytes"] == PROJECT_BYTES
    assert launches[0]["residue"] == []
    assert "single_plan_project" not in result.execution_details
    _assert_pristine(prj)


# ------------------------------------------- RasPreprocess.preprocess_plan

class _PreprocessRas:
    def __init__(self, project_folder: Path, executable: Path, version: str):
        self.project_folder = project_folder
        self.project_name = "Demo"
        self.ras_exe_path = executable
        self.ras_version = version
        self.plan_df = pd.DataFrame([{"plan_number": "03", "Geom File": "g03"}])

    def check_initialized(self):
        return None


class _LaunchedProcess:
    pid = 12345
    returncode = None

    def poll(self):
        return self.returncode


def _write_preprocess_outputs(folder: Path):
    with h5py.File(folder / "Demo.p03.tmp.hdf", "w") as hdf:
        hdf.create_group("Event Conditions").attrs["Completed Successfully"] = True
    (folder / "Demo.b03").write_bytes(b"ready")
    (folder / "Demo.x03").write_bytes(b"ready")


def _patch_preprocess_route(monkeypatch, tmp_path, *, signal=True, raise_error=None):
    process = _LaunchedProcess()
    launches = []
    terminated = []

    class Monitor:
        blocked_reason = None
        signal_source = "alternate" if signal else None

        @staticmethod
        def enable_detailed_logging(_plan_file):
            return True

        def __init__(self, **kwargs):
            self.alternate_signal_condition = kwargs["alternate_signal_condition"]

        def monitor_until_signal(self, _process):
            if raise_error is not None:
                raise raise_error
            if not signal:
                return False
            _write_preprocess_outputs(tmp_path)
            assert self.alternate_signal_condition()
            return True

    def unsteady_probe(root_pid, tmp_hdf, b_file, x_file, artifact_baseline=None):
        return RasPreprocess._preprocessing_artifacts_ready(
            tmp_hdf, b_file, x_file, artifact_baseline=artifact_baseline
        )

    def popen(command, **kwargs):
        project = Path(kwargs["cwd"]) / "Demo.prj"
        launches.append({
            "command": command,
            "project_bytes": project.read_bytes(),
            "residue": _residue(project),
        })
        return process

    def terminate(child):
        terminated.append(child)
        child.returncode = -9

    monkeypatch.setattr(raspreprocess_module, "BcoMonitor", Monitor)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(RasPreprocess, "_unsteady_compute_started", staticmethod(unsteady_probe))
    monkeypatch.setattr(RasPreprocess, "_preprocess_process_inventory", staticmethod(lambda: []))
    monkeypatch.setattr(
        RasPreprocess, "_tcu_supervision_availability_error", staticmethod(lambda: None),
    )
    monkeypatch.setattr(RasPreprocess, "_terminate_process_tree", staticmethod(terminate))
    return process, launches, terminated


def test_preprocess_plan_exposes_only_requested_plan_on_702(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _PreprocessRas(tmp_path, executable, "7.0.2")
    process, launches, terminated = _patch_preprocess_route(monkeypatch, tmp_path)

    result = RasPreprocess.preprocess_plan(
        "03", ras_object=ras_obj, clear_existing=False, fix_line_endings=False,
        require_linux_solver_ready=False,
    )

    assert result.success is True, result.error
    assert result.signal_source == "owned_process_artifacts"
    assert terminated == [process]
    assert len(launches) == 1
    assert launches[0]["project_bytes"] == FILTERED_BYTES
    assert launches[0]["residue"] == ["Demo.prj.single-plan.claim", "Demo.prj.single-plan.orig"]
    assert launches[0]["command"][-1].endswith(f'"{prj}" "{tmp_path / "Demo.p03"}"')
    _assert_pristine(prj)


def test_preprocess_plan_timeout_restores_project(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _PreprocessRas(tmp_path, executable, "7.0.2")
    process, launches, terminated = _patch_preprocess_route(monkeypatch, tmp_path, signal=False)

    result = RasPreprocess.preprocess_plan(
        "03", ras_object=ras_obj, max_wait=2, clear_existing=False,
    )

    assert result.success is False
    assert result.timed_out is True
    assert result.signal_source == "timeout"
    assert "single-plan" not in (result.error or "")
    assert terminated == [process]
    assert launches[0]["project_bytes"] == FILTERED_BYTES
    _assert_pristine(prj)


def test_preprocess_plan_exception_restores_project(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _PreprocessRas(tmp_path, executable, "7.0.2")
    process, launches, terminated = _patch_preprocess_route(
        monkeypatch, tmp_path, raise_error=RuntimeError("monitor exploded"),
    )

    with pytest.raises(RuntimeError, match="monitor exploded"):
        RasPreprocess.preprocess_plan("03", ras_object=ras_obj, clear_existing=False)

    assert launches[0]["project_bytes"] == FILTERED_BYTES
    assert terminated == [process]
    _assert_pristine(prj)


def test_preprocess_plan_unproved_quiescence_fails_result_and_retains_claim(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _PreprocessRas(tmp_path, executable, "7.0.2")
    _patch_preprocess_route(monkeypatch, tmp_path)
    # Residue inventory unavailable: quiescence cannot be proved.
    monkeypatch.setattr(RasPreprocess, "_preprocess_process_inventory", staticmethod(lambda: None))

    result = RasPreprocess.preprocess_plan(
        "03", ras_object=ras_obj, clear_existing=False, fix_line_endings=False,
        require_linux_solver_ready=False,
    )

    assert result.success is False
    assert "could not be proved stopped" in result.error
    assert str(prj.with_name("Demo.prj.single-plan.claim")) in result.error
    assert prj.read_bytes() == FILTERED_BYTES
    assert _residue(prj) == ["Demo.prj.single-plan.claim", "Demo.prj.single-plan.orig"]


def test_preprocess_plan_invalid_declaration_fails_before_launch(tmp_path, monkeypatch):
    data = PROJECT_BYTES.replace(b"Plan File=p03\r\n", b"")
    prj = _write_project(tmp_path, data=data)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _PreprocessRas(tmp_path, executable, "7.0.2")
    _process, launches, _terminated = _patch_preprocess_route(monkeypatch, tmp_path)

    result = RasPreprocess.preprocess_plan("03", ras_object=ras_obj, clear_existing=False)

    assert result.success is False
    assert launches == []
    assert "Could not expose plan 03 as the only HEC-RAS 7.0.2 project plan" in result.error
    assert "does not declare 'Plan File=p03'" in result.error
    _assert_pristine(prj, data=data)


def test_preprocess_plan_prior_release_leaves_project_untouched(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    executable = _make_executable(tmp_path, RELEASE_701)
    ras_obj = _PreprocessRas(tmp_path, executable, "7.0.1")
    _process, launches, _terminated = _patch_preprocess_route(monkeypatch, tmp_path)

    result = RasPreprocess.preprocess_plan(
        "03", ras_object=ras_obj, clear_existing=False, fix_line_endings=False,
        require_linux_solver_ready=False,
    )

    assert result.success is True, result.error
    assert launches[0]["project_bytes"] == PROJECT_BYTES
    assert launches[0]["residue"] == []
    _assert_pristine(prj)


def test_orphan_backup_is_not_overwritten(tmp_path):
    prj = _write_project(tmp_path)
    transaction = single_plan.SinglePlanProjectTransaction(prj, '03')
    transaction.backup_path.write_bytes(b'retained recovery data')
    with pytest.raises(single_plan.SinglePlanProjectError, match='retained backup'):
        transaction.apply()
    assert transaction.backup_path.read_bytes() == b'retained recovery data'
    assert prj.read_bytes() == PROJECT_BYTES
    assert not transaction.claim_path.exists()


def test_project_edit_during_claim_acquisition_is_preserved(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    transaction = single_plan.SinglePlanProjectTransaction(prj, '03')
    acquire = transaction._acquire_claim
    edited = PROJECT_BYTES + b'User note=changed\r\n'

    def acquire_then_edit(*args):
        acquire(*args)
        prj.write_bytes(edited)

    monkeypatch.setattr(transaction, '_acquire_claim', acquire_then_edit)
    with pytest.raises(single_plan.SinglePlanProjectError, match='changed while acquiring'):
        transaction.apply()
    assert prj.read_bytes() == edited
    assert not transaction.claim_path.exists()
    assert not transaction.backup_path.exists()


def test_unproved_quiescence_does_not_write_project(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    transaction = single_plan.SinglePlanProjectTransaction(prj, '03')
    transaction.apply()

    def unexpected_write(*args):
        pytest.fail('A surviving engine must not see the restored full plan list')

    monkeypatch.setattr(single_plan, '_write_file_atomically', unexpected_write)
    outcome = transaction.restore(owned_quiescent=False)
    assert not outcome.restored and not outcome.proved
    assert prj.read_bytes() == FILTERED_BYTES
    assert transaction.backup_path.read_bytes() == PROJECT_BYTES


def test_restore_read_error_is_reported_with_recovery_files(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    transaction = single_plan.SinglePlanProjectTransaction(prj, '03')
    transaction.apply()
    read = single_plan._read_bytes

    def denied(path):
        if path == prj:
            raise PermissionError('project is locked')
        return read(path)

    monkeypatch.setattr(single_plan, '_read_bytes', denied)
    outcome = transaction.restore()
    assert not outcome.ok
    assert 'project is locked' in outcome.detail
    assert transaction.backup_path.read_bytes() == PROJECT_BYTES
    assert transaction.claim_path.exists()


def test_failed_rewrite_preservation_does_not_overwrite_rewrite(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    transaction = single_plan.SinglePlanProjectTransaction(prj, '03')
    transaction.apply()
    rewrite = FILTERED_BYTES + b'User note=changed\r\n'
    prj.write_bytes(rewrite)
    write = Path.write_bytes

    def deny_rewrite_copy(path, data):
        if single_plan.REWRITE_SUFFIX in path.name:
            raise PermissionError('recovery copy denied')
        return write(path, data)

    monkeypatch.setattr(Path, 'write_bytes', deny_rewrite_copy)
    outcome = transaction.restore()
    assert not outcome.ok
    assert prj.read_bytes() == rewrite
    assert transaction.backup_path.read_bytes() == PROJECT_BYTES
    assert transaction.claim_path.exists()


def test_competing_stale_recovery_is_refused(tmp_path):
    prj = _write_project(tmp_path, data=FILTERED_BYTES)
    transaction = single_plan.SinglePlanProjectTransaction(prj, '03')
    transaction.backup_path.write_bytes(PROJECT_BYTES)
    _write_claim(prj, owner=_dead_owner(), original=PROJECT_BYTES, filtered=FILTERED_BYTES)
    recovery = transaction.claim_path.with_name(transaction.claim_path.name + '.recovery')
    recovery.touch()
    with pytest.raises(single_plan.SinglePlanProjectError, match='Another recovery'):
        transaction.apply()
    assert prj.read_bytes() == FILTERED_BYTES
    assert recovery.exists()
    assert transaction.claim_path.exists()


def test_malformed_additional_plan_declaration_is_refused():
    with pytest.raises(single_plan.SinglePlanProjectError, match='malformed Plan File'):
        single_plan.filter_project_declaration(PROJECT_BYTES + b'\r\nPlan File=unexpected\r\n', '03')


def test_preprocess_refuses_active_project_before_artifact_cleanup(tmp_path, monkeypatch):
    prj = _write_project(tmp_path)
    executable = _make_executable(tmp_path, RELEASE_702)
    ras_obj = _PreprocessRas(tmp_path, executable, '7.0.2')
    _process, launches, _terminated = _patch_preprocess_route(monkeypatch, tmp_path)
    (tmp_path / 'Demo.b03').write_bytes(b'active engine input')
    monkeypatch.setattr(single_plan, 'active_project_launches', lambda _: (['Ras.exe (pid 123)'], True))

    result = RasPreprocess.preprocess_plan(
        '03', ras_object=ras_obj, clear_existing=True, require_linux_solver_ready=False,
    )

    assert not result.success
    assert 'already using' in result.error
    assert not launches
    assert (tmp_path / 'Demo.b03').read_bytes() == b'active engine input'
    _assert_pristine(prj)
