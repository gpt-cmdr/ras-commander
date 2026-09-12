"""Unit tests for RasTcu (HEC-RAS Terms & Conditions acceptance detection/seeding).

These tests avoid the real Windows registry by monkeypatching the small set of
internal helpers that touch winreg, so they run on any platform.
"""

import logging
import sys
from types import SimpleNamespace

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


def test_status_accepted_when_node_has_acceptance_state(monkeypatch):
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(RasTcu, "_resolve_exe", staticmethod(lambda *a, **k: _EXE))
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinregModule())
    monkeypatch.setattr(
        RasTcu,
        "_node_has_acceptance_state",
        staticmethod(lambda hive, sub, version=None: sub.endswith(r"\ras.exe")),
    )
    status = RasTcu.status(ras_version="6.6")
    assert status.accepted is True
    assert status.reason == "accepted"
    assert status.registry_key.endswith(r"HEC-RAS\6.6\ras.exe")


def test_status_checks_both_legacy_node_names_before_rejecting(monkeypatch):
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(RasTcu, "_resolve_exe", staticmethod(lambda *a, **k: _EXE))
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinregModule())
    monkeypatch.setattr(
        RasTcu,
        "_node_has_acceptance_state",
        staticmethod(lambda _hive, subkey, _version=None: subkey.endswith(r"\ras")),
    )
    monkeypatch.setattr(
        RasTcu,
        "_node_exists",
        staticmethod(lambda _hive, subkey: subkey.endswith(r"\ras.exe")),
    )

    status = RasTcu.status(ras_version="6.6")

    assert status.accepted is True
    assert status.registry_key.endswith(r"HEC-RAS\6.6\ras")


def test_status_not_accepted_when_no_subtree(monkeypatch):
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(RasTcu, "_resolve_exe", staticmethod(lambda *a, **k: _EXE))
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinregModule())
    monkeypatch.setattr(RasTcu, "_node_has_acceptance_state", staticmethod(lambda *args: False))
    monkeypatch.setattr(RasTcu, "_node_exists", staticmethod(lambda hive, sub: False))
    status = RasTcu.status(ras_version="6.6")
    assert status.accepted is False
    assert status.reason == "no-vb6-subtree"
    assert status.install_dir == _INSTALL


def test_status_rejects_personal_only_subtree(monkeypatch):
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr(RasTcu, "_resolve_exe", staticmethod(lambda *a, **k: _EXE))
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinregModule())
    monkeypatch.setattr(RasTcu, "_node_has_acceptance_state", staticmethod(lambda *args: False))
    monkeypatch.setattr(RasTcu, "_node_exists", staticmethod(lambda hive, sub: sub.endswith(r"\ras.exe")))
    status = RasTcu.status(ras_version="6.6")
    assert status.accepted is False
    assert status.reason == "unaccepted-vb6-subtree"
    assert status.registry_key.endswith(r"HEC-RAS\6.6\ras.exe")


def test_node_has_acceptance_state_ignores_projects_without_sentinel(monkeypatch):
    fake = _FakeWinregModule(
        {
            (1, "node"): {"values": [], "subkeys": ["Projects", "Form Position"]},
        }
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert RasTcu._node_has_acceptance_state(
        fake.HKEY_CURRENT_USER, "node", "6.6"
    ) is False


def test_node_has_acceptance_state_accepts_exact_projects_sentinel(monkeypatch):
    fake = _FakeWinregModule(
        {
            (1, "node"): {"values": [], "subkeys": ["Projects"]},
            (1, r"node\Projects"): {
                "values": [
                    ("Most Recent Project", r"C:\models\example.prj", 1),
                    ("System Statistic", "660", 1),
                ],
                "subkeys": [],
            },
        }
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert RasTcu._node_has_acceptance_state(
        fake.HKEY_CURRENT_USER, "node", "6.6"
    ) is True


@pytest.mark.parametrize("sentinel", ["", "   ", 0, False, b"660"])
def test_node_has_acceptance_state_rejects_empty_or_invalid_sentinel(monkeypatch, sentinel):
    fake = _FakeWinregModule(
        {
            (1, "node"): {"values": [], "subkeys": ["Projects"]},
            (1, r"node\Projects"): {
                "values": [("System Statistic", sentinel, 1)],
                "subkeys": [],
            },
        }
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert RasTcu._node_has_acceptance_state(
        fake.HKEY_CURRENT_USER, "node", "6.6"
    ) is False


def test_clear_values_preserves_tcu_sentinel(monkeypatch):
    projects = {
        "values": [
            ("Most Recent Project", r"C:\private\model.prj", 1),
            ("System Statistic", "660", 1),
        ],
        "subkeys": [],
    }
    fake = _FakeWinregModule({(1, "projects"): projects})
    monkeypatch.setitem(sys.modules, "winreg", fake)

    RasTcu._clear_values(1, "projects", preserve_names=("System Statistic",))

    assert projects["values"] == [("System Statistic", "660", 1)]


def test_node_has_acceptance_state_rejects_root_values(monkeypatch):
    fake = _FakeWinregModule(
        {
            (1, "node"): {"values": [("Accepted", "1", 1)], "subkeys": ["Projects"]},
        }
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert RasTcu._node_has_acceptance_state(
        fake.HKEY_CURRENT_USER, "node", "6.6"
    ) is False


def test_node_has_acceptance_state_rejects_non_personal_child(monkeypatch):
    fake = _FakeWinregModule(
        {
            (1, "node"): {"values": [], "subkeys": ["Projects", "TCU"]},
        }
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert RasTcu._node_has_acceptance_state(
        fake.HKEY_CURRENT_USER, "node", "6.6"
    ) is False


@pytest.mark.parametrize(
    ("value", "version", "expected"),
    [
        (1065353713, "5.0", True),
        ("1065353720", "5.0.7", True),
        (2136867313, "5.0", False),
        (2136867413, "6.0", False),
        (1065353813, "6.0", True),
        ("610", "6.1", True),
        ("631", "6.3.1", True),
        ("670 Beta 5 Development", "6.7 Beta 5", True),
        ("660", "6.5", False),
        ("", "6.6", False),
        (False, "6.6", False),
    ],
)
def test_sentinel_acceptance_is_release_specific(value, version, expected):
    assert RasTcu._sentinel_accepts_version(value, version) is expected


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("5.0", "1065353713"),
        ("5.0.5", "1065353718"),
        ("6.0", "1065353813"),
        ("6.1", "610"),
        ("6.7 Beta 5", None),
        ("unknown", None),
    ],
)
def test_accepted_sentinel_value_is_exact_for_target_release(version, expected):
    assert RasTcu._accepted_sentinel_value(version) == expected


@pytest.mark.parametrize(
    ("target", "expected_version"),
    [("5.0.5", "5.0.4"), ("6.0", "6.1")],
)
def test_find_donor_prefers_nearest_same_major_release(
    monkeypatch,
    target,
    expected_version,
):
    fake_winreg = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_USERS=2)
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    nodes = [
        rf"root\4.0\ras",
        rf"root\5.0.4\ras.exe",
        rf"root\5.0.6\ras.exe",
        rf"root\6.1\ras.exe",
    ]
    monkeypatch.setattr(
        RasTcu,
        "_iter_accepted_nodes",
        staticmethod(lambda _hive, _parent: iter(nodes)),
    )

    hive, donor = RasTcu._find_donor(
        rf"C:\Program Files (x86)\HEC\HEC-RAS\{target}"
    )

    assert hive == fake_winreg.HKEY_CURRENT_USER
    assert f"\\{expected_version}\\" in donor


def test_version_label_uses_parent_folder_for_executable_path():
    assert RasTcu._version_label(
        ras_version=r"C:\Program Files (x86)\HEC\HEC-RAS\5.0.7\Ras.exe"
    ) == "5.0.7"


def test_version_label_uses_parent_folder_for_ras_object_executable_path():
    ras_object = type(
        "FakeRas",
        (),
        {
            "ras_version": (
                r"C:\Program Files (x86)\HEC\HEC-RAS\5.0.7\Ras.exe"
            )
        },
    )()
    assert RasTcu._version_label(ras_object=ras_object) == "5.0.7"


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
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinregModule())
    monkeypatch.setattr(RasTcu, "_find_donor", staticmethod(lambda install_dir: (None, None)))
    with caplog.at_level(logging.WARNING, logger="ras_commander.RasTcu"):
        result = RasTcu.accept(ras_version="6.6")
    assert result.reason == "no-donor-available"
    assert any("no already-accepted" in r.getMessage() for r in caplog.records)


def test_accept_dry_run_does_not_write(monkeypatch):
    monkeypatch.setattr(RasTcu, "status", staticmethod(
        lambda *a, **k: TcuStatus(False, "6.6", _INSTALL, "key", "no-vb6-subtree")))
    fake = _FakeWinregModule()
    monkeypatch.setitem(sys.modules, "winreg", fake)
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
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(RasTcu, "_find_donor", staticmethod(lambda install_dir: (fake.HKEY_CURRENT_USER, "donor")))
    monkeypatch.setattr(RasTcu, "_copy_key", staticmethod(
        lambda *a, **k: a[4].append("one")))  # writes list is 5th positional arg
    monkeypatch.setattr(RasTcu, "_clear_values", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        RasTcu,
        "_write_target_sentinel",
        staticmethod(lambda *a, **k: True),
    )
    monkeypatch.setattr(RasTcu, "_node_has_acceptance_state", staticmethod(lambda *a, **k: True))
    acks = []
    monkeypatch.setattr(RasTcu, "_write_ack", staticmethod(lambda *a, **k: acks.append(a)))
    result = RasTcu.accept(ras_version="6.6")
    assert result.accepted is True
    assert result.reason == "accepted"
    assert len(acks) == 1  # audit record written


def test_accept_does_not_report_success_when_seeded_state_is_unverified(monkeypatch):
    monkeypatch.setattr(RasTcu, "status", staticmethod(
        lambda *a, **k: TcuStatus(False, "6.6", _INSTALL, "key", "personal-only-vb6-subtree")))
    fake = _FakeWinregModule()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(RasTcu, "_find_donor", staticmethod(lambda install_dir: (fake.HKEY_CURRENT_USER, "donor")))
    monkeypatch.setattr(RasTcu, "_copy_key", staticmethod(
        lambda *a, **k: a[4].append("one")))  # writes list is 5th positional arg
    monkeypatch.setattr(RasTcu, "_clear_values", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        RasTcu,
        "_write_target_sentinel",
        staticmethod(lambda *a, **k: True),
    )
    monkeypatch.setattr(RasTcu, "_node_has_acceptance_state", staticmethod(lambda *a, **k: False))
    acks = []
    monkeypatch.setattr(RasTcu, "_write_ack", staticmethod(lambda *a, **k: acks.append(a)))
    result = RasTcu.accept(ras_version="6.6")
    assert result.accepted is None
    assert result.reason == "seeded-unverified"
    assert acks == []


# --------------------------------------------------------------------------- #
# Minimal fake winreg (only what RasTcu references at import points)
# --------------------------------------------------------------------------- #
class _FakeKey:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeWinregModule:
    HKEY_CURRENT_USER = 1
    HKEY_USERS = 2
    KEY_SET_VALUE = 0x0002
    KEY_ALL_ACCESS = 0xF003F

    def __init__(self, registry=None):
        self.registry = registry or {}

    def OpenKey(self, hive, subkey, *_args):
        try:
            return _FakeKey(self.registry[(hive, subkey)])
        except KeyError as exc:
            raise OSError(subkey) from exc

    def QueryInfoKey(self, key):
        return (len(key.data.get("subkeys", [])), len(key.data.get("values", [])), None)

    def EnumKey(self, key, index):
        try:
            return key.data.get("subkeys", [])[index]
        except IndexError as exc:
            raise OSError(index) from exc

    def EnumValue(self, key, index):
        try:
            return key.data.get("values", [])[index]
        except IndexError as exc:
            raise OSError(index) from exc

    def DeleteValue(self, key, name):
        key.data["values"] = [
            value for value in key.data.get("values", []) if value[0] != name
        ]
