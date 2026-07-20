"""Tests for deterministic, non-disclosing Wine-prefix fingerprints."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from ras_commander.WinePrefixFingerprint import (
    WinePrefixFingerprintError,
    fingerprint_wine_prefix,
)

_C_DEVICE_NAME = "c:" if os.name != "nt" else "c-drive"
_Z_DEVICE_NAME = "z:" if os.name != "nt" else "z-root"
_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ras_commander"
    / "WinePrefixFingerprint.py"
)
_CLI_PATH = (
    Path(__file__).resolve().parent
    / "qualification"
    / "fingerprint_wine_prefix.py"
)


def _make_prefix(root: Path, *, reverse_order: bool = False) -> Path:
    root.mkdir()
    files = [
        ("user.reg", b"REGEDIT4\n[user-secret]\n\"token\"=\"alpha\"\n"),
        ("system.reg", b"REGEDIT4\n[system-secret]\n"),
        ("userdef.reg", b"REGEDIT4\n[defaults]\n"),
        ("drive_c/data/payload.bin", b"\x00\x01payload\xff"),
    ]
    if reverse_order:
        files.reverse()
    for relative, content in files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "empty").mkdir()
    return root


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and set(value) <= set("0123456789abcdef")


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _make_transfer_receipt(path: Path) -> dict:
    target = {
        "path": r"C:\Program Files (x86)\HEC\HEC-RAS\6.5\Ras.exe",
        "version": "6.5",
        "sha256": "a" * 64,
        "detected_version": "6.5",
        "file_version": "6.5.0.0",
        "product_version": "6.5.0.0",
        "architecture": "x86",
    }
    probe = {
        "identity": target,
        "status": "ready",
        "interactions": 0,
        "process_tree_terminated": True,
        "survivors": [],
    }
    receipt = {
        "schema_version": 1,
        "kind": "exact_version_captured_acceptance_transfer",
        "status": "accepted_and_restarts_verified",
        "target": target,
        "prefix_instance_token_sha256": "b" * 64,
        "destination_is_disposable": True,
        "restart_cooldown_seconds": 45.0,
        "restart_probes": [probe, probe],
        "safe_completion": True,
        "passed": True,
        "created_at_utc": "2026-07-18T00:00:00+00:00",
    }
    receipt["report_sha256"] = _canonical_hash(receipt)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _make_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"symbolic links are unavailable: {symlink_error}")
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(
            "symbolic links and junctions are unavailable: "
            f"{completed.stderr.strip()}"
        )


def _remove_directory_link(link: Path) -> None:
    if link.is_symlink():
        link.unlink()
    else:
        link.rmdir()


def _add_dosdevices(
    prefix: Path,
    *,
    external_target: Path,
    external_name: str = _Z_DEVICE_NAME,
) -> Path:
    dosdevices = prefix / "dosdevices"
    dosdevices.mkdir()
    _make_directory_link(dosdevices / _C_DEVICE_NAME, prefix / "drive_c")
    _make_directory_link(dosdevices / external_name, external_target)
    return dosdevices


def _run_native_cli(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess:
    poison_root = tmp_path / "poison-imports"
    poison_package = poison_root / "ras_commander"
    poison_package.mkdir(parents=True, exist_ok=True)
    (poison_package / "__init__.py").write_text(
        "raise RuntimeError('ras_commander package import is forbidden')\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(poison_root)
    return subprocess.run(
        [sys.executable, str(_CLI_PATH), *arguments],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_exact_clones_are_deterministic_and_do_not_disclose_registry_values(
    tmp_path: Path,
):
    first = _make_prefix(tmp_path / "first")
    second = _make_prefix(tmp_path / "second", reverse_order=True)
    os.utime(first / "user.reg", (1_000_000_000, 1_000_000_000))
    os.utime(second / "user.reg", (1_700_000_000, 1_700_000_000))

    first_result = fingerprint_wine_prefix(first)
    second_result = fingerprint_wine_prefix(second)

    assert first_result == second_result
    assert first_result.file_count == 4
    assert first_result.total_bytes == sum(
        path.stat().st_size for path in first.rglob("*") if path.is_file()
    )
    assert first_result.user_reg_sha256 == hashlib.sha256(
        (first / "user.reg").read_bytes()
    ).hexdigest()
    assert first_result.system_reg_sha256 == hashlib.sha256(
        (first / "system.reg").read_bytes()
    ).hexdigest()
    assert first_result.userdef_reg_sha256 == hashlib.sha256(
        (first / "userdef.reg").read_bytes()
    ).hexdigest()
    assert all(
        _is_sha256(value)
        for name, value in asdict(first_result).items()
        if name.endswith("sha256") and value is not None
    )
    serialized = json.dumps(asdict(first_result), sort_keys=True)
    assert "user-secret" not in serialized
    assert "system-secret" not in serialized
    assert "token" not in serialized
    assert "alpha" not in serialized


def test_content_change_updates_root_and_only_affected_registry_hash(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    before = fingerprint_wine_prefix(prefix)
    registry = prefix / "user.reg"
    registry.write_bytes(registry.read_bytes().replace(b"alpha", b"bravo"))

    after = fingerprint_wine_prefix(prefix)

    assert after.root_sha256 != before.root_sha256
    assert after.user_reg_sha256 != before.user_reg_sha256
    assert after.system_reg_sha256 == before.system_reg_sha256
    assert after.userdef_reg_sha256 == before.userdef_reg_sha256
    assert after.file_count == before.file_count
    assert after.total_bytes == before.total_bytes


def test_size_change_updates_root_and_total_bytes(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    before = fingerprint_wine_prefix(prefix)
    payload = prefix / "drive_c" / "data" / "payload.bin"
    payload.write_bytes(payload.read_bytes() + b"more")

    after = fingerprint_wine_prefix(prefix)

    assert after.root_sha256 != before.root_sha256
    assert after.file_count == before.file_count
    assert after.total_bytes == before.total_bytes + 4


def test_relative_path_change_updates_root_without_changing_content_totals(
    tmp_path: Path,
):
    prefix = _make_prefix(tmp_path / "prefix")
    before = fingerprint_wine_prefix(prefix)
    source = prefix / "drive_c" / "data" / "payload.bin"
    source.rename(source.with_name("renamed.bin"))

    after = fingerprint_wine_prefix(prefix)

    assert after.root_sha256 != before.root_sha256
    assert after.file_count == before.file_count
    assert after.total_bytes == before.total_bytes
    assert after.user_reg_sha256 == before.user_reg_sha256


def test_empty_directory_change_updates_root_but_not_file_totals(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    before = fingerprint_wine_prefix(prefix)
    (prefix / "another-empty-directory").mkdir()

    after = fingerprint_wine_prefix(prefix)

    assert after.root_sha256 != before.root_sha256
    assert after.file_count == before.file_count
    assert after.total_bytes == before.total_bytes


def test_entry_type_change_updates_root(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    node = prefix / "type-change"
    node.mkdir()
    before = fingerprint_wine_prefix(prefix)
    node.rmdir()
    node.write_bytes(b"")

    after = fingerprint_wine_prefix(prefix)

    assert after.root_sha256 != before.root_sha256
    assert after.file_count == before.file_count + 1
    assert after.total_bytes == before.total_bytes


def test_missing_registry_file_fails_closed(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    (prefix / "userdef.reg").unlink()

    with pytest.raises(WinePrefixFingerprintError, match="userdef.reg"):
        fingerprint_wine_prefix(prefix)


def test_link_resolving_outside_prefix_fails_closed(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"outside")
    link = prefix / "drive_c" / "escape"
    _make_directory_link(link, outside)

    with pytest.raises(WinePrefixFingerprintError, match="outside the prefix"):
        fingerprint_wine_prefix(prefix)


def test_prefix_root_link_is_rejected(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    alias = tmp_path / "prefix-alias"
    _make_directory_link(alias, prefix)

    with pytest.raises(WinePrefixFingerprintError, match="root must not"):
        fingerprint_wine_prefix(alias)


def test_safe_link_target_contributes_to_root_hash(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    first_target = prefix / "drive_c" / "first-target"
    second_target = prefix / "drive_c" / "second-target"
    first_target.mkdir()
    second_target.mkdir()
    link = prefix / "drive_c" / "target-link"
    _make_directory_link(link, first_target)
    before = fingerprint_wine_prefix(prefix)

    _remove_directory_link(link)
    _make_directory_link(link, second_target)
    after = fingerprint_wine_prefix(prefix)

    assert after.root_sha256 != before.root_sha256
    assert after.file_count == before.file_count
    assert after.total_bytes == before.total_bytes


def test_registry_file_must_not_be_a_link(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    target = prefix / "registry-directory"
    target.mkdir()
    (target / "content").write_bytes((prefix / "user.reg").read_bytes())
    (prefix / "user.reg").unlink()
    _make_directory_link(prefix / "user.reg", target)

    with pytest.raises(WinePrefixFingerprintError, match="user.reg"):
        fingerprint_wine_prefix(prefix)


def test_real_shape_dosdevices_requires_explicit_qualification_policy(
    tmp_path: Path,
):
    prefix = _make_prefix(tmp_path / "prefix")
    outside = tmp_path / "host-root"
    outside.mkdir()
    _add_dosdevices(prefix, external_target=outside)

    with pytest.raises(WinePrefixFingerprintError, match="outside the prefix"):
        fingerprint_wine_prefix(prefix)

    qualified = fingerprint_wine_prefix(
        prefix,
        exclude_wine_dosdevices=True,
    )
    assert _is_sha256(qualified.dosdevices_sha256)


def test_qualification_policy_is_deterministic_without_private_targets(
    tmp_path: Path,
):
    first = _make_prefix(tmp_path / "first")
    second = _make_prefix(tmp_path / "second", reverse_order=True)
    first_private_target = tmp_path / "private-target-alpha"
    second_private_target = tmp_path / "private-target-bravo"
    first_private_target.mkdir()
    second_private_target.mkdir()
    _add_dosdevices(first, external_target=first_private_target)
    _add_dosdevices(second, external_target=second_private_target)

    first_result = fingerprint_wine_prefix(
        first,
        exclude_wine_dosdevices=True,
    )
    second_result = fingerprint_wine_prefix(
        second,
        exclude_wine_dosdevices=True,
    )

    assert first_result == second_result
    serialized = json.dumps(asdict(first_result), sort_keys=True)
    assert "private-target-alpha" not in serialized
    assert "private-target-bravo" not in serialized


def test_dosdevice_name_change_updates_only_mapping_hash(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    outside = tmp_path / "host-root"
    outside.mkdir()
    dosdevices = _add_dosdevices(prefix, external_target=outside)
    before = fingerprint_wine_prefix(
        prefix,
        exclude_wine_dosdevices=True,
    )
    old_mapping = dosdevices / _Z_DEVICE_NAME
    _remove_directory_link(old_mapping)
    _make_directory_link(dosdevices / "y-root", outside)

    after = fingerprint_wine_prefix(
        prefix,
        exclude_wine_dosdevices=True,
    )

    assert after.root_sha256 == before.root_sha256
    assert after.dosdevices_sha256 != before.dosdevices_sha256
    assert after.file_count == before.file_count
    assert after.total_bytes == before.total_bytes


def test_dosdevice_target_class_change_updates_mapping_hash(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    outside = tmp_path / "host-root"
    outside.mkdir()
    dosdevices = _add_dosdevices(prefix, external_target=outside)
    before = fingerprint_wine_prefix(
        prefix,
        exclude_wine_dosdevices=True,
    )
    mapping = dosdevices / _Z_DEVICE_NAME
    _remove_directory_link(mapping)
    _make_directory_link(mapping, prefix / "drive_c")

    after = fingerprint_wine_prefix(
        prefix,
        exclude_wine_dosdevices=True,
    )

    assert after.root_sha256 == before.root_sha256
    assert after.dosdevices_sha256 != before.dosdevices_sha256


def test_qualification_policy_rejects_escape_outside_dosdevices(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    outside = tmp_path / "host-root"
    outside.mkdir()
    _add_dosdevices(prefix, external_target=outside)
    _make_directory_link(prefix / "drive_c" / "escape", outside)

    with pytest.raises(WinePrefixFingerprintError, match="outside the prefix"):
        fingerprint_wine_prefix(
            prefix,
            exclude_wine_dosdevices=True,
        )


def test_qualification_policy_rejects_non_link_dosdevice_entries(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")
    outside = tmp_path / "host-root"
    outside.mkdir()
    dosdevices = _add_dosdevices(prefix, external_target=outside)
    (dosdevices / "unexpected-file").write_bytes(b"must not be hidden")

    with pytest.raises(WinePrefixFingerprintError, match="link-only"):
        fingerprint_wine_prefix(
            prefix,
            exclude_wine_dosdevices=True,
        )


def test_fingerprint_module_imports_only_the_standard_library():
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            if node.module:
                imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots == {
        "__future__",
        "dataclasses",
        "hashlib",
        "os",
        "pathlib",
        "stat",
        "typing",
    }


def test_native_cli_loads_without_importing_ras_commander_package(tmp_path: Path):
    prefix = _make_prefix(tmp_path / "prefix")

    completed = _run_native_cli(tmp_path, str(prefix))

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    expected = fingerprint_wine_prefix(prefix)
    assert payload == {
        "schema_version": 1,
        "exclude_wine_dosdevices": False,
        **asdict(expected),
    }


def test_native_cli_supports_explicit_dosdevices_boundary_without_path_leak(
    tmp_path: Path,
):
    prefix = _make_prefix(tmp_path / "prefix")
    private_target = tmp_path / "private-host-target"
    private_target.mkdir()
    _add_dosdevices(prefix, external_target=private_target)

    strict = _run_native_cli(tmp_path, str(prefix))
    assert strict.returncode == 2
    assert "private-host-target" not in strict.stdout
    assert "private-host-target" not in strict.stderr

    qualified = _run_native_cli(
        tmp_path,
        "--exclude-wine-dosdevices",
        str(prefix),
    )
    assert qualified.returncode == 0, qualified.stderr
    payload = json.loads(qualified.stdout)
    assert payload["schema_version"] == 1
    assert payload["exclude_wine_dosdevices"] is True
    assert _is_sha256(payload["root_sha256"])
    assert _is_sha256(payload["dosdevices_sha256"])
    assert "private-host-target" not in qualified.stdout


def test_native_cli_emits_self_hashed_receipt_bound_post_restart_envelope(
    tmp_path: Path,
):
    prefix = _make_prefix(tmp_path / "prefix")
    private_target = tmp_path / "private-host-target"
    private_target.mkdir()
    _add_dosdevices(prefix, external_target=private_target)
    receipt_path = tmp_path / "private-transfer-receipt.json"
    receipt = _make_transfer_receipt(receipt_path)

    completed = _run_native_cli(
        tmp_path,
        "--exclude-wine-dosdevices",
        "--post-restart-receipt",
        str(receipt_path),
        str(prefix),
    )

    assert completed.returncode == 0, completed.stderr
    envelope = json.loads(completed.stdout)
    claimed = envelope.pop("envelope_sha256")
    assert claimed == _canonical_hash(envelope)
    assert envelope["schema_version"] == 2
    assert envelope["kind"] == "post_restart_wine_prefix_evidence"
    assert envelope["captured_after_verified_restarts"] is True
    assert envelope["binding"] == {
        "receipt_file_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "receipt_self_sha256": receipt["report_sha256"],
        "target_version": "6.5",
        "target_executable_sha256": "a" * 64,
        "profile_instance_sha256": "b" * 64,
    }
    assert envelope["fingerprint"]["schema_version"] == 1
    assert envelope["fingerprint"]["exclude_wine_dosdevices"] is True
    serialized = json.dumps(envelope, sort_keys=True)
    assert str(receipt_path) not in serialized
    assert receipt["target"]["path"] not in serialized


def test_native_cli_rejects_tampered_receipt_without_disclosing_its_path(
    tmp_path: Path,
):
    prefix = _make_prefix(tmp_path / "prefix")
    receipt_path = tmp_path / "private-secret-receipt.json"
    receipt = _make_transfer_receipt(receipt_path)
    receipt["passed"] = False
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    completed = _run_native_cli(
        tmp_path,
        "--post-restart-receipt",
        str(receipt_path),
        str(prefix),
    )

    assert completed.returncode == 2
    assert str(receipt_path) not in completed.stdout
    assert str(receipt_path) not in completed.stderr
    assert "private-secret-receipt" not in completed.stderr
