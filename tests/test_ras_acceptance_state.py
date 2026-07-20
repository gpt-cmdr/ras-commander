"""Fail-closed tests for opaque HEC-RAS acceptance-state qualification."""

from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path

import pytest

acceptance_module = importlib.import_module("ras_commander.RasAcceptanceState")
from ras_commander.RasAcceptanceState import (  # noqa: E402
    AcceptanceProbeResult,
    RasAcceptanceState,
    RegistryValueSnapshot,
)
from ras_commander.RasDialogWatchdog import ObservedWindow  # noqa: E402


class _FakeRegistry:
    def __init__(self, states=None):
        self.states = dict(states or {})
        self.writes = []
        self.deletes = []

    def snapshot(self, key):
        return self.states.get(
            key,
            RegistryValueSnapshot(key, "System Statistic", False, None, None),
        )

    def set_value(self, key, value, registry_type):
        self.writes.append((key, value, registry_type))
        self.states[key] = RegistryValueSnapshot(
            key,
            "System Statistic",
            True,
            str(value),
            registry_type,
        )
        return []

    def delete_value(self, key):
        self.deletes.append(key)
        self.states[key] = RegistryValueSnapshot(
            key,
            "System Statistic",
            False,
            None,
            None,
        )

    def restore_value(self, snapshot, _created_prefixes):
        self.states[snapshot.key] = snapshot

    def subtree_snapshot(self, root):
        prefix = root.casefold() + "\\"
        return {
            key[len(root) + 1 :]: snapshot
            for key, snapshot in self.states.items()
            if key.casefold().startswith(prefix) and snapshot.exists
        }

    def restore_subtree(self, root, snapshot):
        prefix = root.casefold() + "\\"
        self.states = {
            key: value
            for key, value in self.states.items()
            if not key.casefold().startswith(prefix)
        }
        for relative, value in snapshot.items():
            self.states[f"{root}\\{relative}"] = value


def _fake_executable(tmp_path: Path, version: str, *, content=b"same-binary") -> Path:
    folder = tmp_path / version
    folder.mkdir(parents=True, exist_ok=True)
    executable = folder / "Ras.exe"
    executable.write_bytes(content)
    return executable


def _ready_probe(identity, *, elapsed=15.0):
    return AcceptanceProbeResult(
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
        elapsed_seconds=elapsed,
        observed_at_utc="2026-07-18T00:00:00+00:00",
        main_window_signature=("ThunderRT6Main", "RAS", "0", "1"),
        topology_signatures=("1|ThunderRT6Main|RAS|owner=0|enabled=1",),
        observed_process_ids=(1,),
    )


def _verified_bundle(executable, version, fake, value="opaque-source-state"):
    identity = RasAcceptanceState.executable_identity(
        executable,
        expected_version=version,
        verify_executable_version=False,
    )
    key = RasAcceptanceState.registry_subkey(
        str(executable),
        expected_version=version,
    )
    fake.states[key] = RegistryValueSnapshot(
        key,
        "System Statistic",
        True,
        value,
        acceptance_module.winreg.REG_SZ,
    )
    probe = _ready_probe(identity)
    bundle = RasAcceptanceState.capture(
        executable,
        expected_version=version,
        source_probe=probe,
        verify_executable_version=False,
        registry=fake,
    )
    return identity, bundle


def _captured_diagnostic(monkeypatch, tmp_path, *, clean=False):
    version = "7.0.1"
    executable = _fake_executable(tmp_path, version)
    fake = _FakeRegistry()
    identity, bundle = _verified_bundle(executable, version, fake)
    monkeypatch.setattr(
        RasAcceptanceState,
        "probe",
        lambda *_args, **_kwargs: _ready_probe(identity),
    )
    diagnostic = RasAcceptanceState.diagnose_candidate(
        executable,
        candidate_value=bundle.state.value or "",
        candidate_registry_type=bundle.state.registry_type,
        source_version=version,
        expected_version=version,
        permitted_transition=(version, version),
        diagnostic_label="exact-version-captured-state",
        source_bundle=bundle,
        verify_executable_version=False,
        clean_application_subtree_for_probe=clean,
        registry=fake,
    )
    return executable, fake, bundle, diagnostic


@pytest.mark.parametrize(
    ("version", "application_name"),
    [
        ("4.0", "ras"),
        ("4.1.0", "ras"),
        ("5.0.3", "ras.exe"),
        ("6.3.1", "ras.exe"),
        ("7.0", "ras.exe"),
        ("7.0.1", "ras.exe"),
        ("6.7 Beta 5", "ras.exe"),
    ],
)
def test_application_name_tracks_observed_version_split(version, application_name):
    assert RasAcceptanceState.application_name_for_version(version) == application_name


def test_registry_subkey_is_exact_install_path_scoped():
    key = RasAcceptanceState.registry_subkey(
        r"C:\Program Files (x86)\HEC\HEC-RAS\7.0.1\Ras.exe",
        expected_version="7.0.1",
    )

    assert key.endswith(r"\7.0.1\ras.exe\Projects")
    assert key.startswith("Software\\VB and VBA Program Settings\\")


@pytest.mark.parametrize(
    "version",
    ["4.0", "4.1.0", "5.0.3", "6.0", "6.1", "6.3.1", "7.0", "7.0.1"],
)
def test_capture_preserves_state_as_an_opaque_string(tmp_path, version):
    executable = _fake_executable(tmp_path, version)
    fake = _FakeRegistry()
    opaque_value = f"opaque-test-state:{version}"
    _identity, bundle = _verified_bundle(executable, version, fake, opaque_value)

    assert bundle.state.value == opaque_value
    assert bundle.state.registry_type == acceptance_module.winreg.REG_SZ
    assert bundle.no_modal_verified


def test_temporary_state_restores_missing_value_after_baseexception(tmp_path):
    executable = _fake_executable(tmp_path, "7.0.1")
    fake = _FakeRegistry()
    key = RasAcceptanceState.registry_subkey(
        str(executable),
        expected_version="7.0.1",
    )

    with pytest.raises(KeyboardInterrupt):
        with RasAcceptanceState.temporary_system_statistic(
            executable,
            "randomized-negative-control",
            expected_version="7.0.1",
            registry_type=acceptance_module.winreg.REG_SZ,
            diagnostic_label="restore-on-baseexception",
            verify_executable_version=False,
            registry=fake,
        ):
            raise KeyboardInterrupt

    assert fake.snapshot(key).exists is False


def test_exact_version_captured_candidate_restores_and_records_ready(
    monkeypatch,
    tmp_path,
):
    executable, fake, bundle, diagnostic = _captured_diagnostic(
        monkeypatch,
        tmp_path,
    )

    assert diagnostic.passed is True
    assert diagnostic.registry_restored is True
    assert diagnostic.candidate_origin == "captured_verified"
    assert fake.snapshot(bundle.state.key) == bundle.state


def test_cross_version_candidate_is_rejected_before_launch(monkeypatch, tmp_path):
    source = _fake_executable(tmp_path / "source", "7.0", content=b"binary")
    target = _fake_executable(tmp_path / "target", "7.0.1", content=b"binary")
    fake = _FakeRegistry()
    _identity, bundle = _verified_bundle(source, "7.0", fake)
    launched = False

    def probe(*_args, **_kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("probe must not run")

    monkeypatch.setattr(RasAcceptanceState, "probe", probe)
    with pytest.raises(ValueError, match="exact-version source evidence"):
        RasAcceptanceState.diagnose_candidate(
            target,
            candidate_value=bundle.state.value or "",
            candidate_registry_type=bundle.state.registry_type,
            source_version="7.0",
            expected_version="7.0.1",
            permitted_transition=("7.0", "7.0.1"),
            diagnostic_label="cross-version-rejected",
            source_bundle=bundle,
            verify_executable_version=False,
            registry=fake,
        )

    assert launched is False


def test_arbitrary_positive_origin_is_rejected(tmp_path):
    executable = _fake_executable(tmp_path, "7.0.1")

    with pytest.raises(ValueError, match="Unsupported candidate_origin"):
        RasAcceptanceState.diagnose_candidate(
            executable,
            candidate_value="arbitrary-state",
            candidate_registry_type=acceptance_module.winreg.REG_SZ,
            source_version="7.0.1",
            expected_version="7.0.1",
            permitted_transition=("7.0.1", "7.0.1"),
            diagnostic_label="arbitrary-positive-rejected",
            candidate_origin="derived-positive",
            verify_executable_version=False,
            registry=_FakeRegistry(),
        )


def test_source_bundle_executable_hash_must_match_target(tmp_path):
    source = _fake_executable(tmp_path / "source", "7.0.1", content=b"source")
    target = _fake_executable(tmp_path / "target", "7.0.1", content=b"target")
    fake = _FakeRegistry()
    _identity, bundle = _verified_bundle(source, "7.0.1", fake)

    with pytest.raises(ValueError, match="executable hash"):
        RasAcceptanceState.diagnose_candidate(
            target,
            candidate_value=bundle.state.value or "",
            candidate_registry_type=bundle.state.registry_type,
            source_version="7.0.1",
            expected_version="7.0.1",
            permitted_transition=("7.0.1", "7.0.1"),
            diagnostic_label="hash-mismatch-rejected",
            source_bundle=bundle,
            verify_executable_version=False,
            registry=fake,
        )


def test_executable_identity_rejects_mislabeled_binary(monkeypatch, tmp_path):
    executable = _fake_executable(tmp_path, "wrong-folder")
    monkeypatch.setattr(
        acceptance_module.RasUtils,
        "get_executable_version",
        lambda _path: {
            "valid_pe": True,
            "normalized_version": "6.6",
            "file_version": "6.6.0.0",
            "product_version": "6.6.0.0",
            "architecture": "x86",
            "error": None,
        },
    )

    with pytest.raises(ValueError, match="version mismatch"):
        RasAcceptanceState.executable_identity(executable, expected_version="7.0.1")


def test_temporary_state_aborts_before_launch_on_failed_exact_readback(tmp_path):
    class NoWriteRegistry(_FakeRegistry):
        def set_value(self, key, value, registry_type):
            self.writes.append((key, value, registry_type))
            return []

    executable = _fake_executable(tmp_path, "7.0.1")
    fake = NoWriteRegistry()

    with pytest.raises(RuntimeError, match="failed exact readback"):
        with RasAcceptanceState.temporary_system_statistic(
            executable,
            "randomized-negative-control",
            expected_version="7.0.1",
            registry_type=acceptance_module.winreg.REG_SZ,
            diagnostic_label="readback-mismatch",
            verify_executable_version=False,
            registry=fake,
        ):
            pytest.fail("transaction yielded despite failed readback")


def test_candidate_rewrite_after_probe_cannot_pass(monkeypatch, tmp_path):
    version = "7.0.1"
    executable = _fake_executable(tmp_path, version)
    fake = _FakeRegistry()
    identity, bundle = _verified_bundle(executable, version, fake)

    def rewrite_then_return(*_args, **_kwargs):
        fake.states[bundle.state.key] = replace(
            bundle.state,
            value="rewritten-by-target",
        )
        return _ready_probe(identity)

    monkeypatch.setattr(RasAcceptanceState, "probe", rewrite_then_return)
    receipt = RasAcceptanceState.diagnose_candidate(
        executable,
        candidate_value=bundle.state.value or "",
        candidate_registry_type=bundle.state.registry_type,
        source_version=version,
        expected_version=version,
        permitted_transition=(version, version),
        diagnostic_label="target-rewrite",
        source_bundle=bundle,
        verify_executable_version=False,
        registry=fake,
    )

    assert receipt.after_probe.value == "rewritten-by-target"
    assert receipt.candidate_stayed_exact is False
    assert receipt.passed is False
    assert receipt.registry_restored is True
    assert fake.snapshot(bundle.state.key) == bundle.state


def test_no_modal_verified_rejects_late_block_evidence(tmp_path):
    identity = RasAcceptanceState.executable_identity(
        _fake_executable(tmp_path, "7.0.1"),
        expected_version="7.0.1",
        verify_executable_version=False,
    )
    result = replace(
        _ready_probe(identity),
        blocked_reason="late modal",
        blocked_titles=("Unexpected",),
    )

    assert result.no_modal_verified is False


def test_exact_version_captured_state_can_provision_disposable_target(
    monkeypatch,
    tmp_path,
):
    executable, fake, bundle, diagnostic = _captured_diagnostic(
        monkeypatch,
        tmp_path,
    )
    provision = RasAcceptanceState.provision(
        executable,
        diagnostic=diagnostic,
        authorization_reference="unit-authority-reference",
        destination_is_disposable=True,
        dry_run=False,
        source_bundle=bundle,
        verify_executable_version=False,
        registry=fake,
    )

    assert provision.written is True
    assert fake.snapshot(provision.key).value == bundle.state.value


def test_exact_version_capture_transfers_across_paths_with_same_binary_hash(
    monkeypatch,
    tmp_path,
):
    version = "6.6"
    source = _fake_executable(tmp_path / "native", version, content=b"same-binary")
    target = _fake_executable(tmp_path / "wine", version, content=b"same-binary")
    fake = _FakeRegistry()
    _source_identity, bundle = _verified_bundle(source, version, fake)
    target_identity = RasAcceptanceState.executable_identity(
        target,
        expected_version=version,
        verify_executable_version=False,
    )
    monkeypatch.setattr(
        RasAcceptanceState,
        "probe",
        lambda *_args, **_kwargs: _ready_probe(target_identity),
    )

    diagnostic = RasAcceptanceState.diagnose_candidate(
        target,
        candidate_value=bundle.state.value or "",
        candidate_registry_type=bundle.state.registry_type,
        source_version=version,
        expected_version=version,
        permitted_transition=(version, version),
        diagnostic_label="exact-build-cross-path-transfer",
        source_bundle=bundle,
        verify_executable_version=False,
        clean_application_subtree_for_probe=True,
        registry=fake,
    )
    provision = RasAcceptanceState.provision(
        target,
        diagnostic=diagnostic,
        authorization_reference="unit-authority-reference",
        destination_is_disposable=True,
        dry_run=False,
        source_bundle=bundle,
        verify_executable_version=False,
        replace_application_subtree=True,
        registry=fake,
    )

    assert diagnostic.passed
    assert provision.written
    assert fake.snapshot(provision.key).value == bundle.state.value


def test_synthetic_negative_can_never_be_provisioned(monkeypatch, tmp_path):
    version = "7.0.1"
    executable = _fake_executable(tmp_path, version)
    identity = RasAcceptanceState.executable_identity(
        executable,
        expected_version=version,
        verify_executable_version=False,
    )
    monkeypatch.setattr(
        RasAcceptanceState,
        "probe",
        lambda *_args, **_kwargs: _ready_probe(identity),
    )
    fake = _FakeRegistry()
    diagnostic = RasAcceptanceState.diagnose_candidate(
        executable,
        candidate_value="randomized-negative-control",
        candidate_registry_type=acceptance_module.winreg.REG_SZ,
        source_version=version,
        expected_version=version,
        permitted_transition=(version, version),
        diagnostic_label="negative-only",
        candidate_origin="synthetic_negative",
        verify_executable_version=False,
        registry=fake,
    )

    with pytest.raises(ValueError, match="captured_verified"):
        RasAcceptanceState.provision(
            executable,
            diagnostic=diagnostic,
            authorization_reference="unit-authority-reference",
            destination_is_disposable=True,
            dry_run=False,
            verify_executable_version=False,
            registry=fake,
        )


def test_beta_identity_requires_exact_install_directory_qualifier(
    monkeypatch,
    tmp_path,
):
    executable = _fake_executable(tmp_path, "6.7 Beta 5")
    monkeypatch.setattr(
        acceptance_module.RasUtils,
        "get_executable_version",
        lambda _path: {
            "valid_pe": True,
            "normalized_version": "6.7",
            "file_version": "6.7.0.0",
            "product_version": "6.7.0.0",
            "architecture": "x86",
            "error": None,
        },
    )

    with pytest.raises(ValueError, match="exact beta name"):
        RasAcceptanceState.executable_identity(
            executable,
            expected_version="6.7 Beta 4a",
        )


def test_acceptance_window_partition_rejects_unknown_nonstandard_window():
    main = ObservedWindow(1, 10, "ThunderRT6Main", "RAS", "", 0, True, None)
    known_companion = ObservedWindow(
        2,
        10,
        "ThunderRT6FormDC",
        "HEC-RAS 7.0.1",
        "",
        1,
        True,
        None,
    )
    transitional_main = ObservedWindow(
        4,
        10,
        "ThunderRT6Main",
        "",
        "",
        0,
        True,
        None,
    )
    unknown = ObservedWindow(
        3,
        10,
        "ThunderRT6FormDC",
        "Unexpected question",
        "Continue?",
        1,
        True,
        None,
    )

    mains, unknowns = acceptance_module._acceptance_window_partition(
        (main, known_companion, transitional_main, unknown),
        ("hec-ras", "river analysis system"),
    )

    assert mains == (main,)
    assert unknowns == (unknown,)


def test_temporary_state_restores_sibling_subtree_mutation(tmp_path):
    executable = _fake_executable(tmp_path, "7.0.1")
    key = RasAcceptanceState.registry_subkey(
        str(executable),
        expected_version="7.0.1",
    )
    root = key.rsplit("\\Projects", 1)[0]
    sibling_key = f"{root}\\Preferences"
    sibling = RegistryValueSnapshot(
        sibling_key,
        "System Statistic",
        True,
        "sibling-before",
        acceptance_module.winreg.REG_SZ,
    )
    fake = _FakeRegistry({sibling_key: sibling})

    with pytest.raises(KeyboardInterrupt):
        with RasAcceptanceState.temporary_system_statistic(
            executable,
            "randomized-negative-control",
            expected_version="7.0.1",
            registry_type=acceptance_module.winreg.REG_SZ,
            diagnostic_label="subtree-baseexception",
            verify_executable_version=False,
            registry=fake,
        ):
            fake.states[sibling_key] = replace(sibling, value="mutated")
            raise KeyboardInterrupt

    assert fake.snapshot(key).exists is False
    assert fake.snapshot(sibling_key) == sibling


def test_provision_rejects_legal_probe(monkeypatch, tmp_path):
    executable, fake, bundle, diagnostic = _captured_diagnostic(
        monkeypatch,
        tmp_path,
    )
    legal_probe = replace(
        diagnostic.probe,
        status="legal_modal",
        blocked_reason="TCU",
        blocked_titles=("Terms and Conditions for Use (TCU)",),
    )

    with pytest.raises(ValueError, match="verified no-modal"):
        RasAcceptanceState.provision(
            executable,
            diagnostic=replace(diagnostic, passed=True, probe=legal_probe),
            authorization_reference="unit-authority-reference",
            destination_is_disposable=True,
            dry_run=False,
            source_bundle=bundle,
            verify_executable_version=False,
            registry=fake,
        )


def test_provision_rejects_inconsistent_restoration_or_observed_value(
    monkeypatch,
    tmp_path,
):
    executable, fake, bundle, diagnostic = _captured_diagnostic(
        monkeypatch,
        tmp_path,
    )
    common = dict(
        ras_executable=executable,
        authorization_reference="unit-authority-reference",
        destination_is_disposable=True,
        dry_run=False,
        source_bundle=bundle,
        verify_executable_version=False,
        registry=fake,
    )

    with pytest.raises(ValueError, match="restore its exact prior value"):
        RasAcceptanceState.provision(
            diagnostic=replace(diagnostic, registry_restored=False),
            **common,
        )
    with pytest.raises(ValueError, match="applied/observed"):
        RasAcceptanceState.provision(
            diagnostic=replace(
                diagnostic,
                after_probe=replace(diagnostic.applied, value="rewritten"),
            ),
            **common,
        )


def test_clean_subtree_provision_requires_matching_diagnostic(
    monkeypatch,
    tmp_path,
):
    executable, fake, bundle, diagnostic = _captured_diagnostic(
        monkeypatch,
        tmp_path,
    )

    with pytest.raises(ValueError, match="clean-subtree diagnostic"):
        RasAcceptanceState.provision(
            executable,
            diagnostic=diagnostic,
            authorization_reference="unit-authority-reference",
            destination_is_disposable=True,
            dry_run=False,
            source_bundle=bundle,
            verify_executable_version=False,
            replace_application_subtree=True,
            registry=fake,
        )
