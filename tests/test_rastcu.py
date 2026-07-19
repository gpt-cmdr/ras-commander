"""Unit tests for RasTcu (HEC-RAS Terms & Conditions acceptance detection/seeding).

These tests avoid the real Windows registry by monkeypatching the small set of
internal helpers that touch winreg, so they run on any platform.
"""

import logging

import pytest

from ras_commander.RasTcu import RasTcu, TcuStatus

_EXE = r"C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe"
_INSTALL = r"C:\Program Files (x86)\HEC\HEC-RAS\6.6"


# --------------------------------------------------------------------------- #
# Pure logic
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "version,expected",
    [
        ("4.0", "ras"),
        ("4.1.0", "ras"),
        ("5.0.7", "ras.exe"),
        ("6.6", "ras.exe"),
        ("7.0", "ras.exe"),
    ],
)
def test_node_name_matches_version_family(version, expected):
    assert RasTcu._node_name_for(version) == expected


def test_tcu_status_truthiness():
    assert bool(TcuStatus(True, "6.6", _INSTALL, "k", "accepted")) is True
    assert bool(TcuStatus(False, "6.6", _INSTALL, "k", "no-vb6-subtree")) is False
    assert bool(TcuStatus(None, "6.6", _INSTALL, "k", "not-windows")) is False


# --------------------------------------------------------------------------- #
# status()
# --------------------------------------------------------------------------- #
def test_status_non_windows_is_unknown(monkeypatch):
    monkeypatch.setattr("os.name", "posix")
    status = RasTcu.status(ras_version="6.6")
    assert status.accepted is None
    assert status.reason == "not-windows"


def test_status_version_unresolved(monkeypatch):
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(RasTcu, "_resolve_exe", staticmethod(lambda *a, **k: None))
    status = RasTcu.status(ras_version="6.6")
    assert status.accepted is None
    assert status.reason == "version-unresolved"


def test_status_accepted_when_node_has_subkeys(monkeypatch):
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(RasTcu, "_resolve_exe", staticmethod(lambda *a, **k: _EXE))
    # Pretend winreg is importable and the ras.exe node has subkeys.
    monkeypatch.setitem(__import__("sys").modules, "winreg", _FakeWinregModule())
    monkeypatch.setattr(RasTcu, "_node_has_subkeys", staticmethod(lambda hive, sub: sub.endswith(r"\ras.exe")))
    status = RasTcu.status(ras_version="6.6")
    assert status.accepted is True
    assert status.reason == "accepted"
    assert status.registry_key.endswith(r"HEC-RAS\6.6\ras.exe")


def test_status_not_accepted_when_no_subtree(monkeypatch):
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(RasTcu, "_resolve_exe", staticmethod(lambda *a, **k: _EXE))
    monkeypatch.setitem(__import__("sys").modules, "winreg", _FakeWinregModule())
    monkeypatch.setattr(RasTcu, "_node_has_subkeys", staticmethod(lambda hive, sub: False))
    status = RasTcu.status(ras_version="6.6")
    assert status.accepted is False
    assert status.reason == "no-vb6-subtree"
    assert status.install_dir == _INSTALL


def test_is_accepted_wrapper(monkeypatch):
    monkeypatch.setattr(RasTcu, "status", staticmethod(
        lambda *a, **k: TcuStatus(True, "6.6", _INSTALL, "k", "accepted")))
    assert RasTcu.is_accepted(ras_version="6.6") is True


# --------------------------------------------------------------------------- #
# accept()
# --------------------------------------------------------------------------- #
def test_accept_noop_when_already_accepted(monkeypatch):
    monkeypatch.setattr(RasTcu, "status", staticmethod(
        lambda *a, **k: TcuStatus(True, "6.6", _INSTALL, "key", "accepted")))
    result = RasTcu.accept(ras_version="6.6")
    assert result.accepted is True
    assert result.reason == "already-accepted"


def test_accept_returns_unknown_off_windows(monkeypatch):
    monkeypatch.setattr(RasTcu, "status", staticmethod(
        lambda *a, **k: TcuStatus(None, "6.6", None, None, "not-windows")))
    result = RasTcu.accept(ras_version="6.6")
    assert result.accepted is None
    assert result.reason == "not-windows"


def test_accept_warns_when_no_donor(monkeypatch, caplog):
    monkeypatch.setattr(RasTcu, "status", staticmethod(
        lambda *a, **k: TcuStatus(False, "6.6", _INSTALL, "key", "no-vb6-subtree")))
    monkeypatch.setitem(__import__("sys").modules, "winreg", _FakeWinregModule())
    monkeypatch.setattr(RasTcu, "_find_donor", staticmethod(lambda install_dir: (None, None)))
    with caplog.at_level(logging.WARNING, logger="ras_commander.RasTcu"):
        result = RasTcu.accept(ras_version="6.6")
    assert result.reason == "no-donor-available"
    assert any("no already-accepted" in r.getMessage() for r in caplog.records)


def test_accept_dry_run_does_not_write(monkeypatch):
    monkeypatch.setattr(RasTcu, "status", staticmethod(
        lambda *a, **k: TcuStatus(False, "6.6", _INSTALL, "key", "no-vb6-subtree")))
    fake = _FakeWinregModule()
    monkeypatch.setitem(__import__("sys").modules, "winreg", fake)
    monkeypatch.setattr(RasTcu, "_find_donor", staticmethod(lambda install_dir: (fake.HKEY_CURRENT_USER, "donor\\path")))

    copied = {"writes": 0}

    def fake_copy(src_hive, src_path, dst_hive, dst_path, writes, dry_run):
        assert dry_run is True
        writes.extend(["a", "b", "c"])
        copied["writes"] = 3

    monkeypatch.setattr(RasTcu, "_copy_key", staticmethod(fake_copy))
    result = RasTcu.accept(ras_version="6.6", dry_run=True)
    # dry-run reports not-yet-accepted and performs no real acceptance
    assert result.accepted is False
    assert copied["writes"] == 3


def test_accept_success_records_acceptance(monkeypatch):
    monkeypatch.setattr(RasTcu, "status", staticmethod(
        lambda *a, **k: TcuStatus(False, "6.6", _INSTALL, "key", "no-vb6-subtree")))
    fake = _FakeWinregModule()
    monkeypatch.setitem(__import__("sys").modules, "winreg", fake)
    monkeypatch.setattr(RasTcu, "_find_donor", staticmethod(lambda install_dir: (fake.HKEY_CURRENT_USER, "donor")))
    monkeypatch.setattr(RasTcu, "_copy_key", staticmethod(
        lambda *a, **k: a[4].append("one")))  # writes list is 5th positional arg
    monkeypatch.setattr(RasTcu, "_clear_values", staticmethod(lambda *a, **k: None))
    acks = []
    monkeypatch.setattr(RasTcu, "_write_ack", staticmethod(lambda *a, **k: acks.append(a)))
    result = RasTcu.accept(ras_version="6.6")
    assert result.accepted is True
    assert result.reason == "accepted"
    assert len(acks) == 1  # audit record written


# --------------------------------------------------------------------------- #
# Minimal fake winreg (only what RasTcu references at import points)
# --------------------------------------------------------------------------- #
class _FakeWinregModule:
    HKEY_CURRENT_USER = 1
    HKEY_USERS = 2
    KEY_SET_VALUE = 0x0002
    KEY_ALL_ACCESS = 0xF003F
