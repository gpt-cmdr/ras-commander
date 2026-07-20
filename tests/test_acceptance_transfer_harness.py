"""Unit coverage for private-bundle capture and exact-version transfer CLIs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from ras_commander import (
    AcceptanceDiagnosticReceipt,
    AcceptanceProbeResult,
    AcceptanceStateBundle,
    RasExecutableIdentity,
    RegistryValueSnapshot,
)


def _load_script(name: str):
    script = Path(__file__).parent / "qualification" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture_cli = _load_script("run_capture_acceptance_bundle.py")
transfer_cli = _load_script("run_captured_acceptance_transfer.py")


def test_capture_diagnostic_and_persistent_transfer_scopes_are_distinct():
    diagnostic = {
        "4.0",
        "4.1.0",
        "5.0.3",
        "5.0.6",
        "5.0.7",
        "6.0",
        "6.1",
        "6.2",
        "6.3",
        "6.3.1",
        "6.4.1",
        "6.5",
        "6.6",
    }
    persistent = {"6.1", "6.2", "6.3", "6.3.1", "6.4.1", "6.5", "6.6"}

    assert capture_cli.CAPTURABLE_EXACT_VERSIONS == diagnostic
    assert transfer_cli.DIAGNOSTIC_EXACT_VERSIONS == diagnostic
    assert transfer_cli.PERSISTENT_TRANSFER_EXACT_VERSIONS == persistent
    assert persistent < diagnostic


def _bundle(version: str = "6.6") -> AcceptanceStateBundle:
    identity = RasExecutableIdentity(
        path=rf"C:\private-source\{version}\Ras.exe",
        version=version,
        sha256="a" * 64,
        detected_version=version,
        file_version=f"{version}.0.0",
        product_version=f"{version}.0.0",
        architecture="x86",
    )
    state = RegistryValueSnapshot(
        key=(
            rf"Software\VB and VBA Program Settings\C:\private-source\{version}"
            r"\ras.exe\Projects"
        ),
        name="System Statistic",
        exists=True,
        value="opaque-private-state",
        registry_type=1,
    )
    probe = AcceptanceProbeResult(
        identity=identity,
        status="ready",
        started=True,
        visible_window_seen=True,
        visible_titles=("RAS",),
        blocked_reason=None,
        blocked_titles=(),
        interactions=0,
        process_tree_terminated=True,
        survivors=(),
        elapsed_seconds=20.0,
        observed_at_utc="2026-07-18T00:00:00+00:00",
        main_window_signature=("ThunderRT6Main", "RAS", "0", "1"),
        topology_signatures=("main",),
        observed_process_ids=(1,),
    )
    fingerprint_payload = {
        "identity": asdict(identity),
        "state": asdict(state),
        "source_probe": asdict(probe),
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return AcceptanceStateBundle(
        identity=identity,
        state=state,
        source_probe=probe,
        captured_at_utc="2026-07-18T00:00:00+00:00",
        fingerprint=fingerprint,
    )


def _diagnostic(
    bundle: AcceptanceStateBundle,
    *,
    probe: AcceptanceProbeResult | None = None,
    passed: bool = True,
    restoration_safe: bool = True,
) -> AcceptanceDiagnosticReceipt:
    probe = probe or bundle.source_probe
    assert probe is not None
    before = RegistryValueSnapshot(
        key=bundle.state.key,
        name=bundle.state.name,
        exists=False,
        value=None,
        registry_type=None,
    )
    return AcceptanceDiagnosticReceipt(
        target=bundle.identity,
        source_version=bundle.identity.version,
        transition=(bundle.identity.version, bundle.identity.version),
        candidate_value=bundle.state.value or "",
        candidate_registry_type=bundle.state.registry_type or 1,
        candidate_fingerprint="b" * 64,
        before=before,
        applied=bundle.state,
        restored=before,
        probe=probe,
        registry_restored=restoration_safe,
        passed=passed,
        diagnostic_label="exact-version-captured-portability-diagnostic",
        created_at_utc="2026-07-18T00:00:00+00:00",
        after_probe=bundle.state,
        candidate_stayed_exact=restoration_safe,
        application_subtree_before_fingerprint="c" * 64,
        application_subtree_after_probe_fingerprint="d" * 64,
        application_subtree_restored_fingerprint=(
            "c" * 64 if restoration_safe else "e" * 64
        ),
        candidate_origin="captured_verified",
        source_bundle_fingerprint=bundle.fingerprint,
        clean_application_subtree_for_probe=True,
    )


def _diagnostic_probe(
    bundle: AcceptanceStateBundle,
    status: str,
    *,
    survivors: tuple[int, ...] = (),
) -> AcceptanceProbeResult:
    legal = status == "legal_modal"
    unknown = status == "unknown_modal"
    return AcceptanceProbeResult(
        identity=bundle.identity,
        status=status,
        started=True,
        visible_window_seen=True,
        visible_titles=("Terms and Conditions" if legal else "RAS",),
        blocked_reason=(
            "HEC-RAS terms and conditions"
            if legal
            else "Unrecognized visible window"
            if unknown
            else None
        ),
        blocked_titles=(
            ("Terms and Conditions",)
            if legal
            else ("Unexpected",)
            if unknown
            else ()
        ),
        interactions=0,
        process_tree_terminated=not survivors and status != "termination_failed",
        survivors=survivors,
        elapsed_seconds=0.5 if legal or unknown else 20.0,
        observed_at_utc="2026-07-18T00:00:01+00:00",
        topology_signatures=("observed",),
        observed_process_ids=(2,),
    )


def _write_bundle(path: Path, bundle: AcceptanceStateBundle) -> str:
    payload = {
        "schema_version": 1,
        "kind": "private_exact_version_acceptance_bundle",
        "bundle": asdict(bundle),
    }
    data = capture_cli._canonical_bytes(payload)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_private_bundle_round_trips_only_with_exact_file_hash(tmp_path):
    bundle = _bundle()
    path = tmp_path / "source-bundle.json"
    digest = _write_bundle(path, bundle)

    loaded = transfer_cli._load_bundle(path, digest)

    assert loaded == bundle
    with pytest.raises(ValueError, match="file hash"):
        transfer_cli._load_bundle(path, "0" * 64)


def test_transfer_receipt_serializer_never_emits_opaque_values():
    raw = {
        "candidate_value": "opaque-private-state",
        "snapshot": {"value": "opaque-private-state"},
        "authorization_reference": "opaque-authority",
    }

    safe = transfer_cli._safe_json(raw)
    serialized = json.dumps(safe, sort_keys=True)

    assert "opaque-private-state" not in serialized
    assert "opaque-authority" not in serialized
    assert serialized.count("opaque_sha256") == 3


def test_private_capture_refuses_repository_destination(tmp_path):
    assert not capture_cli._outside_repository(capture_cli.REPOSITORY_ROOT / "state.json")
    assert capture_cli._outside_repository(tmp_path / "state.json")


def test_older_build_diagnostic_is_restoring_hash_only_and_never_persistent(
    tmp_path,
    monkeypatch,
):
    bundle = _bundle("4.0")
    bundle_path = tmp_path / "private-bundle.json"
    bundle_sha256 = _write_bundle(bundle_path, bundle)
    output = tmp_path / "diagnostic.json"
    calls: list[str] = []

    class DiagnosticOnlyAcceptanceState:
        @staticmethod
        def diagnose_candidate(*_args, **kwargs):
            calls.append("diagnose")
            assert kwargs["source_bundle"] == bundle
            assert kwargs["source_version"] == "4.0"
            assert kwargs["expected_version"] == "4.0"
            assert kwargs["permitted_transition"] == ("4.0", "4.0")
            assert kwargs["clean_application_subtree_for_probe"] is True
            return _diagnostic(bundle)

        @staticmethod
        def provision(*_args, **_kwargs):
            raise AssertionError("diagnostic-only mode must not provision")

        @staticmethod
        def probe(*_args, **_kwargs):
            raise AssertionError("diagnostic-only mode must not run restart probes")

        @staticmethod
        def capture(*_args, **_kwargs):
            raise AssertionError("diagnostic-only mode must not read persisted state")

    monkeypatch.setattr(
        transfer_cli,
        "RasAcceptanceState",
        DiagnosticOnlyAcceptanceState,
    )
    monkeypatch.setattr(
        transfer_cli.time,
        "sleep",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("diagnostic-only mode must not run restart cooldowns")
        ),
    )
    monkeypatch.setattr(
        transfer_cli.sys,
        "argv",
        [
            "run_captured_acceptance_transfer.py",
            "--ras-executable",
            str(tmp_path / "Ras.exe"),
            "--expected-version",
            "4.0",
            "--source-bundle",
            str(bundle_path),
            "--source-bundle-sha256",
            bundle_sha256,
            "--output",
            str(output),
            "--timeout-seconds",
            "20",
            "--ready-seconds",
            "5",
            "--destination-is-disposable",
            "--diagnostic-only",
        ],
    )

    assert transfer_cli.main() == 0
    assert calls == ["diagnose"]
    serialized = output.read_text(encoding="utf-8")
    report = json.loads(serialized)
    assert report["kind"] == "exact_version_captured_acceptance_diagnostic"
    assert report["purpose"] == "expected_to_determine_portability_not_qualification"
    assert report["qualification_status"] == "diagnostic_only_nonqualifying"
    assert report["status"] == "portable"
    assert report["technical_effective"] is True
    assert report["persistence_performed"] is False
    assert report["restart_probes"] == []
    assert report["automated_ui_interactions"] == 0
    assert report["safe_completion"] is True
    assert report["passed"] is True
    assert "opaque-private-state" not in serialized
    assert report["diagnostic"]["candidate_value"].keys() == {"opaque_sha256"}
    claimed_hash = report.pop("report_sha256")
    assert claimed_hash == hashlib.sha256(
        json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def test_older_build_cannot_enter_persistent_transfer_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(
        transfer_cli.sys,
        "argv",
        [
            "run_captured_acceptance_transfer.py",
            "--ras-executable",
            str(tmp_path / "Ras.exe"),
            "--expected-version",
            "4.0",
            "--source-bundle",
            str(tmp_path / "not-read.json"),
            "--source-bundle-sha256",
            "a" * 64,
            "--authorization-reference-file",
            str(tmp_path / "not-read-authorization.txt"),
            "--prefix-instance-token-file",
            str(tmp_path / "not-read-prefix.txt"),
            "--output",
            str(tmp_path / "not-written.json"),
            "--destination-is-disposable",
        ],
    )

    with pytest.raises(SystemExit) as caught:
        transfer_cli.main()

    assert caught.value.code == 2


def test_persistent_transfer_still_requires_private_authority_files(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        transfer_cli.sys,
        "argv",
        [
            "run_captured_acceptance_transfer.py",
            "--ras-executable",
            str(tmp_path / "Ras.exe"),
            "--expected-version",
            "6.1",
            "--source-bundle",
            str(tmp_path / "not-read.json"),
            "--source-bundle-sha256",
            "a" * 64,
            "--output",
            str(tmp_path / "not-written.json"),
            "--destination-is-disposable",
        ],
    )

    with pytest.raises(SystemExit) as caught:
        transfer_cli.main()

    assert caught.value.code == 2


@pytest.mark.parametrize("cooldown", ["44.999", "nan", "inf"])
def test_persistent_transfer_rejects_invalid_restart_cooldown(
    tmp_path,
    monkeypatch,
    cooldown,
):
    monkeypatch.setattr(
        transfer_cli.sys,
        "argv",
        [
            "run_captured_acceptance_transfer.py",
            "--ras-executable",
            str(tmp_path / "Ras.exe"),
            "--expected-version",
            "6.1",
            "--source-bundle",
            str(tmp_path / "not-read.json"),
            "--source-bundle-sha256",
            "a" * 64,
            "--authorization-reference-file",
            str(tmp_path / "not-read-authorization.txt"),
            "--prefix-instance-token-file",
            str(tmp_path / "not-read-prefix.txt"),
            "--restart-cooldown-seconds",
            cooldown,
            "--output",
            str(tmp_path / "not-written.json"),
            "--destination-is-disposable",
        ],
    )

    with pytest.raises(SystemExit) as caught:
        transfer_cli.main()

    assert caught.value.code == 2
    assert not (tmp_path / "not-written.json").exists()


def test_safe_legal_modal_is_a_completed_not_portable_diagnostic(
    tmp_path,
    monkeypatch,
):
    bundle = _bundle("4.0")
    bundle_path = tmp_path / "private-bundle.json"
    bundle_sha256 = _write_bundle(bundle_path, bundle)
    output = tmp_path / "diagnostic.json"
    legal_probe = _diagnostic_probe(bundle, "legal_modal")

    class LegalNegativeAcceptanceState:
        @staticmethod
        def diagnose_candidate(*_args, **_kwargs):
            return _diagnostic(bundle, probe=legal_probe, passed=False)

        @staticmethod
        def provision(*_args, **_kwargs):
            raise AssertionError("a not-portable diagnostic must not provision")

        @staticmethod
        def probe(*_args, **_kwargs):
            raise AssertionError("a not-portable diagnostic must not restart")

        @staticmethod
        def capture(*_args, **_kwargs):
            raise AssertionError("a not-portable diagnostic must not persist")

    monkeypatch.setattr(
        transfer_cli,
        "RasAcceptanceState",
        LegalNegativeAcceptanceState,
    )
    monkeypatch.setattr(
        transfer_cli.sys,
        "argv",
        [
            "run_captured_acceptance_transfer.py",
            "--ras-executable",
            str(tmp_path / "Ras.exe"),
            "--expected-version",
            "4.0",
            "--source-bundle",
            str(bundle_path),
            "--source-bundle-sha256",
            bundle_sha256,
            "--output",
            str(output),
            "--destination-is-disposable",
            "--diagnostic-only",
        ],
    )

    assert transfer_cli.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "not_portable"
    assert report["technical_effective"] is False
    assert report["passed"] is True
    assert report["safe_completion"] is True
    assert report["persistence_performed"] is False
    assert report["restart_probes"] == []
    assert report["diagnostic"]["probe"]["status"] == "legal_modal"


@pytest.mark.parametrize(
    ("status", "survivors", "restoration_safe"),
    [
        ("unknown_modal", (), True),
        ("launch_failed", (), True),
        ("timeout", (), True),
        ("termination_failed", (99,), True),
        ("legal_modal", (), False),
    ],
)
def test_diagnostic_rejects_unsafe_or_unrestored_outcomes(
    tmp_path,
    monkeypatch,
    status,
    survivors,
    restoration_safe,
):
    bundle = _bundle("4.0")
    bundle_path = tmp_path / "private-bundle.json"
    bundle_sha256 = _write_bundle(bundle_path, bundle)
    output = tmp_path / "must-not-exist.json"
    outcome_probe = _diagnostic_probe(bundle, status, survivors=survivors)

    class UnsafeAcceptanceState:
        @staticmethod
        def diagnose_candidate(*_args, **_kwargs):
            return _diagnostic(
                bundle,
                probe=outcome_probe,
                passed=False,
                restoration_safe=restoration_safe,
            )

    monkeypatch.setattr(transfer_cli, "RasAcceptanceState", UnsafeAcceptanceState)
    monkeypatch.setattr(
        transfer_cli.sys,
        "argv",
        [
            "run_captured_acceptance_transfer.py",
            "--ras-executable",
            str(tmp_path / "Ras.exe"),
            "--expected-version",
            "4.0",
            "--source-bundle",
            str(bundle_path),
            "--source-bundle-sha256",
            bundle_sha256,
            "--output",
            str(output),
            "--destination-is-disposable",
            "--diagnostic-only",
        ],
    )

    with pytest.raises(RuntimeError, match="did not complete"):
        transfer_cli.main()

    assert not output.exists()


def test_legal_modal_cannot_continue_into_persistent_transfer(tmp_path, monkeypatch):
    bundle = _bundle("6.1")
    bundle_path = tmp_path / "private-bundle.json"
    bundle_sha256 = _write_bundle(bundle_path, bundle)
    authorization = tmp_path / "authorization.txt"
    prefix_token = tmp_path / "prefix.txt"
    authorization.write_text("approved", encoding="utf-8")
    prefix_token.write_text("unique-prefix", encoding="utf-8")
    legal_probe = _diagnostic_probe(bundle, "legal_modal")

    class NonportableAcceptanceState:
        @staticmethod
        def diagnose_candidate(*_args, **_kwargs):
            return _diagnostic(bundle, probe=legal_probe, passed=False)

        @staticmethod
        def provision(*_args, **_kwargs):
            raise AssertionError("legal-modal outcome must not provision")

    monkeypatch.setattr(
        transfer_cli,
        "RasAcceptanceState",
        NonportableAcceptanceState,
    )
    monkeypatch.setattr(
        transfer_cli.sys,
        "argv",
        [
            "run_captured_acceptance_transfer.py",
            "--ras-executable",
            str(tmp_path / "Ras.exe"),
            "--expected-version",
            "6.1",
            "--source-bundle",
            str(bundle_path),
            "--source-bundle-sha256",
            bundle_sha256,
            "--authorization-reference-file",
            str(authorization),
            "--prefix-instance-token-file",
            str(prefix_token),
            "--output",
            str(tmp_path / "must-not-exist.json"),
            "--destination-is-disposable",
        ],
    )

    with pytest.raises(RuntimeError, match="transfer diagnostic failed"):
        transfer_cli.main()
