from __future__ import annotations

import sys
from dataclasses import dataclass

import pytest

from ras_commander.RasTcu import RasTcu


@dataclass
class _Key:
    registry: "_FakeWinreg"
    hive: str
    path: str

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    HKEY_USERS = "HKU"
    REG_SZ = 1
    REG_DWORD = 4
    KEY_SET_VALUE = 2
    KEY_ALL_ACCESS = 3

    def __init__(self):
        self.values = {}

    @staticmethod
    def _key(hive, path):
        return hive, str(path).casefold()

    def add_value(self, hive, path, name, value, value_type=REG_SZ):
        self.values.setdefault(self._key(hive, path), {})[name] = (
            value,
            value_type,
        )

    def _paths(self, hive):
        return [path for key_hive, path in self.values if key_hive == hive]

    def _subkeys(self, hive, path):
        prefix = str(path).casefold().rstrip("\\")
        prefix_with_separator = f"{prefix}\\" if prefix else ""
        children = set()
        for candidate in self._paths(hive):
            if not candidate.startswith(prefix_with_separator):
                continue
            remainder = candidate[len(prefix_with_separator) :]
            if remainder:
                children.add(remainder.split("\\", 1)[0])
        return sorted(children)

    def OpenKey(self, hive, path, *_args):
        key = self._key(hive, path)
        if key not in self.values and not self._subkeys(hive, path):
            raise OSError(path)
        return _Key(self, hive, str(path))

    def CreateKey(self, hive, path):
        self.values.setdefault(self._key(hive, path), {})
        return _Key(self, hive, str(path))

    def QueryInfoKey(self, key):
        values = self.values.get(self._key(key.hive, key.path), {})
        return len(self._subkeys(key.hive, key.path)), len(values), 0

    def QueryValueEx(self, key, name):
        try:
            return self.values[self._key(key.hive, key.path)][name]
        except KeyError as exc:
            raise OSError(name) from exc

    def EnumKey(self, key_or_hive, index):
        if isinstance(key_or_hive, _Key):
            children = self._subkeys(key_or_hive.hive, key_or_hive.path)
        else:
            children = self._subkeys(key_or_hive, "")
        try:
            return children[index]
        except IndexError as exc:
            raise OSError(index) from exc

    def SetValueEx(self, key, name, _reserved, value_type, value):
        self.add_value(key.hive, key.path, name, value, value_type)


@pytest.fixture
def fake_registry(monkeypatch):
    registry = _FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(
        RasTcu,
        "_resolve_exe",
        staticmethod(
            lambda *_args, **_kwargs: (
                r"C:\Program Files (x86)\HEC\HEC-RAS\7.0.1\Ras.exe"
            )
        ),
    )
    return registry


def _application_path(version="7.0.1"):
    return (
        r"Software\VB and VBA Program Settings\C:\Program Files (x86)\HEC"
        rf"\HEC-RAS\{version}\ras.exe"
    )


def test_status_does_not_treat_unrelated_vb6_subtree_as_acceptance(
    fake_registry,
):
    fake_registry.add_value(
        fake_registry.HKEY_CURRENT_USER,
        _application_path() + r"\Form Position",
        "Main",
        "1,2,3,4",
    )

    status = RasTcu.status(ras_version="7.0.1")

    assert status.accepted is False
    assert status.reason == "acceptance-sentinel-missing"


def test_status_requires_exact_string_sentinel(fake_registry):
    projects = _application_path() + r"\Projects"
    fake_registry.add_value(
        fake_registry.HKEY_CURRENT_USER,
        projects,
        "System Statistic",
        701,
        fake_registry.REG_DWORD,
    )
    assert RasTcu.status(ras_version="7.0.1").accepted is False

    fake_registry.add_value(
        fake_registry.HKEY_CURRENT_USER,
        projects,
        "System Statistic",
        "opaque",
        fake_registry.REG_SZ,
    )
    assert RasTcu.status(ras_version="7.0.1").accepted is True


def test_accept_refuses_unverified_cross_version_donor(fake_registry):
    fake_registry.add_value(
        fake_registry.HKEY_CURRENT_USER,
        _application_path("7.0") + r"\Projects",
        "System Statistic",
        "opaque-70",
    )

    status = RasTcu.accept(ras_version="7.0.1", write_ack=False)

    assert status.accepted is None
    assert status.reason == "no-exact-version-donor"
    target = fake_registry._key(
        fake_registry.HKEY_CURRENT_USER,
        _application_path() + r"\Projects",
    )
    assert target not in fake_registry.values


def test_accept_transfers_only_exact_version_sentinel(fake_registry):
    sid = "S-1-5-21-123"
    donor = sid + "\\" + _application_path()
    fake_registry.add_value(
        fake_registry.HKEY_USERS,
        donor + r"\Projects",
        "System Statistic",
        "opaque-701",
    )
    fake_registry.add_value(
        fake_registry.HKEY_USERS,
        donor + r"\Form Position",
        "Main",
        "private-layout",
    )

    status = RasTcu.accept(ras_version="7.0.1", write_ack=False)

    assert status.accepted is True
    target_projects = fake_registry.values[
        fake_registry._key(
            fake_registry.HKEY_CURRENT_USER,
            _application_path() + r"\Projects",
        )
    ]
    assert target_projects == {
        "System Statistic": ("opaque-701", fake_registry.REG_SZ)
    }
    assert fake_registry._key(
        fake_registry.HKEY_CURRENT_USER,
        _application_path() + r"\Form Position",
    ) not in fake_registry.values
