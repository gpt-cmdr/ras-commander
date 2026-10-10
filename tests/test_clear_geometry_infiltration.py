"""Clearing infiltration on clone geometries preserves unrelated associations."""

import hashlib
import os
import shutil
import stat
import subprocess
import sys

import h5py
import pytest

from ras_commander import RasMap
from ras_commander import _geometry_association as association
from ras_commander._geometry_association import (
    clear_geometry_infiltration,
    read_geometry_association,
)

INFILTRATION_ATTRS = (
    "Infiltration Filename",
    "Infiltration Layername",
    "Infiltration File Date",
)


def _geometry_file(path):
    with h5py.File(path, "w") as handle:
        geometry = handle.create_group("Geometry")
        for name, value in zip(INFILTRATION_ATTRS, ("infiltration.hdf", "SCS", "old")):
            geometry.attrs[name] = value
        geometry.create_dataset("Preserved", data=[1, 2, 3], compression="gzip")
    return path


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_clear_geometry_infiltration_is_selective_and_idempotent(tmp_path):
    path = tmp_path / "child.g02.hdf"
    with h5py.File(path, "w") as h:
        g = h.create_group("Geometry")
        for k, v in {
            "Terrain Filename": "terrain.hdf",
            "Land Cover Filename": "cover.hdf",
            "Infiltration Filename": "infiltration.hdf",
            "Infiltration Layername": "SCS",
            "Infiltration File Date": "old",
            "Other": "untouched",
        }.items():
            g.attrs[k] = v
    assert clear_geometry_infiltration(path) == path.resolve()
    assert not read_geometry_association(path).get("infiltration_hdf_path")
    with h5py.File(path) as h:
        assert dict(h["Geometry"].attrs) == {
            "Terrain Filename": "terrain.hdf",
            "Land Cover Filename": "cover.hdf",
            "Other": "untouched",
        }
    before_noop = _sha256(path)
    assert RasMap.clear_geometry_infiltration(str(path)) == path.resolve()
    assert _sha256(path) == before_noop


@pytest.mark.parametrize(
    "name", ["parent.p01.hdf", "parent.u01.hdf", "terrain.hdf", "project.g01"]
)
def test_clear_geometry_infiltration_rejects_non_geometry_before_open(name, tmp_path):
    with pytest.raises(ValueError, match="gNN"):
        clear_geometry_infiltration(tmp_path / name)


@pytest.mark.parametrize("link_kind", ["external", "soft_external", "soft_internal"])
def test_clear_geometry_infiltration_rejects_indirect_geometry_without_writes(
    tmp_path, monkeypatch, link_kind
):
    parent = _geometry_file(tmp_path / "parent.g01.hdf")
    child = tmp_path / "child.g02.hdf"
    with h5py.File(child, "w") as handle:
        if link_kind == "external":
            handle["Geometry"] = h5py.ExternalLink(parent.name, "/Geometry")
        elif link_kind == "soft_external":
            handle["Alias"] = h5py.ExternalLink(parent.name, "/Geometry")
            handle["Geometry"] = h5py.SoftLink("/Alias")
        else:
            handle.create_group("Alias").attrs[INFILTRATION_ATTRS[0]] = (
                "infiltration.hdf"
            )
            handle["Geometry"] = h5py.SoftLink("/Alias")
    before = {path: _sha256(path) for path in (parent, child)}
    real_file = h5py.File
    modes = []

    def record_mode(path, mode="r", *args, **kwargs):
        modes.append(mode)
        return real_file(path, mode, *args, **kwargs)

    monkeypatch.setattr(h5py, "File", record_mode)
    with pytest.raises(ValueError, match="direct.*owned.*group"):
        RasMap.clear_geometry_infiltration(child)
    assert modes == ["r"]
    assert {path: _sha256(path) for path in before} == before
    assert set(tmp_path.iterdir()) == {parent, child}


@pytest.mark.parametrize("layout", ["dataset", "missing", "non_hdf"])
def test_clear_geometry_infiltration_rejects_malformed_geometry(tmp_path, layout):
    path = tmp_path / "child.g02.hdf"
    if layout == "non_hdf":
        path.write_bytes(b"not HDF data")
    else:
        with h5py.File(path, "w") as handle:
            if layout == "dataset":
                handle.create_dataset("Geometry", data=[1, 2, 3])
    before = _sha256(path)
    error = {"dataset": ValueError, "missing": KeyError, "non_hdf": OSError}[layout]
    with pytest.raises(error):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]


def test_clear_geometry_infiltration_missing_file(tmp_path):
    path = tmp_path / "child.g02.hdf"
    with pytest.raises(FileNotFoundError):
        RasMap.clear_geometry_infiltration(path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mask", range(8))
def test_clear_geometry_infiltration_clears_partial_associations(tmp_path, mask):
    parent = _geometry_file(tmp_path / "parent.g01.hdf")
    path = tmp_path / "child.g02.hdf"
    shutil.copy2(parent, path)
    with h5py.File(path, "r+") as handle:
        geometry = handle["Geometry"]
        geometry.attrs["Other"] = "untouched"
        for index, name in enumerate(INFILTRATION_ATTRS):
            if not mask & (1 << index):
                del geometry.attrs[name]
    before = _sha256(path)
    parent_before = _sha256(parent)
    assert RasMap.clear_geometry_infiltration(path) == path.resolve()
    assert _sha256(parent) == parent_before
    with h5py.File(path, "r") as handle:
        geometry = handle["Geometry"]
        assert dict(geometry.attrs) == {"Other": "untouched"}
        assert geometry["Preserved"][:].tolist() == [1, 2, 3]
        assert geometry["Preserved"].compression == "gzip"
    if mask == 0:
        assert _sha256(path) == before
    assert set(tmp_path.iterdir()) == {parent, path}


def test_clear_geometry_infiltration_copy_failure_preserves_original(
    tmp_path, monkeypatch
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = _sha256(path)

    def fail_copy(original, backup, *args):
        assert original.name == str(path)
        backup.write(b"incomplete backup")
        raise OSError("injected copy I/O failure")

    monkeypatch.setattr(association.shutil, "copyfileobj", fail_copy)
    with pytest.raises(OSError, match="injected copy"):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("failed_attr", INFILTRATION_ATTRS)
def test_clear_geometry_infiltration_delete_failure_preserves_original(
    tmp_path, monkeypatch, failed_attr
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = _sha256(path)
    real_delete = h5py.AttributeManager.__delitem__

    def fail_delete(attrs, name):
        if name == failed_attr:
            raise OSError("injected attribute-delete I/O failure")
        real_delete(attrs, name)

    monkeypatch.setattr(h5py.AttributeManager, "__delitem__", fail_delete)
    with pytest.raises(OSError, match="injected attribute-delete"):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]


def test_clear_geometry_infiltration_validation_failure_preserves_original(
    tmp_path, monkeypatch
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = _sha256(path)

    def fail_validation(edited_path):
        assert edited_path == path
        with h5py.File(edited_path, "r") as handle:
            assert all(
                name not in handle["Geometry"].attrs for name in INFILTRATION_ATTRS
            )
        # Ensure rollback also removes bytes appended after the backup.
        with edited_path.open("ab") as original:
            original.write(b"injected trailing bytes" * 32)
        raise OSError("injected validation I/O failure")

    monkeypatch.setattr(association, "read_geometry_association", fail_validation)
    with pytest.raises(OSError, match="injected validation"):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("retained_attr", INFILTRATION_ATTRS)
def test_clear_geometry_infiltration_validates_every_attribute_before_success(
    tmp_path, monkeypatch, retained_attr
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = _sha256(path)
    real_delete = h5py.AttributeManager.__delitem__

    def retain_attribute(attrs, name):
        if name != retained_attr:
            real_delete(attrs, name)

    monkeypatch.setattr(h5py.AttributeManager, "__delitem__", retain_attribute)
    with pytest.raises(RuntimeError, match="remained after clearing"):
        RasMap.clear_geometry_infiltration(path)
    assert _sha256(path) == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("fail", [False, True])
def test_clear_geometry_infiltration_preserves_hard_link_identity(
    tmp_path, monkeypatch, fail
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    alias = tmp_path / "alias.g02.hdf"
    os.link(path, alias)
    before_stat = path.stat()
    before = _sha256(path)

    def fail_validation(edited_path):
        raise OSError("injected validation I/O failure")

    def forbid_replace(*args):
        pytest.fail("the original file must never be replaced or renamed")

    monkeypatch.setattr(association.os, "replace", forbid_replace)
    monkeypatch.setattr(association.os, "rename", forbid_replace)
    if fail:
        monkeypatch.setattr(association, "read_geometry_association", fail_validation)
        with pytest.raises(OSError, match="injected validation"):
            RasMap.clear_geometry_infiltration(path)
        assert _sha256(path) == before
    else:
        RasMap.clear_geometry_infiltration(path)
        assert not read_geometry_association(alias)["infiltration_hdf_path"]
    after_stat = path.stat()
    assert (after_stat.st_dev, after_stat.st_ino, after_stat.st_nlink) == (
        before_stat.st_dev,
        before_stat.st_ino,
        before_stat.st_nlink,
    )
    assert os.path.samefile(path, alias)
    assert path.read_bytes() == alias.read_bytes()
    assert set(tmp_path.iterdir()) == {path, alias}


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership and mode contract")
@pytest.mark.parametrize("fail", [False, True])
def test_clear_geometry_infiltration_preserves_posix_mode_owner(
    tmp_path, monkeypatch, fail
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    path.chmod(0o640)
    if os.geteuid() == 0:
        os.chown(path, 12345, 12346)
    before_stat = path.stat()
    before = path.read_bytes()
    if fail:

        def fail_validation(edited_path):
            raise OSError("injected validation I/O failure")

        monkeypatch.setattr(association, "read_geometry_association", fail_validation)
        with pytest.raises(OSError, match="injected validation"):
            RasMap.clear_geometry_infiltration(path)
        assert path.read_bytes() == before
    else:
        RasMap.clear_geometry_infiltration(path)
    after_stat = path.stat()
    assert (stat.S_IMODE(after_stat.st_mode), after_stat.st_uid, after_stat.st_gid) == (
        stat.S_IMODE(before_stat.st_mode),
        before_stat.st_uid,
        before_stat.st_gid,
    )
    assert after_stat.st_ino == before_stat.st_ino
    assert list(tmp_path.iterdir()) == [path]


def _windows_security(path, information=7):
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.GetFileSecurityW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    api.GetFileSecurityW.restype = wintypes.BOOL
    needed = wintypes.DWORD()
    api.GetFileSecurityW(str(path), information, None, 0, ctypes.byref(needed))
    descriptor = ctypes.create_string_buffer(needed.value)
    if not api.GetFileSecurityW(
        str(path), information, descriptor, len(descriptor), ctypes.byref(needed)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return descriptor.raw


def _restrict_windows_acl(path):
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.restype = ctypes.c_void_p
    api.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.DWORD),
    )
    api.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    owner = wintypes.LPWSTR()
    if not api.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        _windows_security(path, 1), 1, 1, ctypes.byref(owner), None
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        sid = owner.value.removeprefix("O:")
    finally:
        kernel.LocalFree(owner)
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    )
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    descriptor = ctypes.c_void_p()
    if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        f"D:P(A;;FA;;;{sid})", 1, ctypes.byref(descriptor), None
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    api.SetFileSecurityW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p)
    api.SetFileSecurityW.restype = wintypes.BOOL
    try:
        if not api.SetFileSecurityW(str(path), 0x80000004, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


@pytest.mark.skipif(os.name != "nt", reason="Windows security descriptor contract")
@pytest.mark.parametrize("failure", [None, "delete", "validation"])
def test_clear_geometry_infiltration_preserves_protected_windows_acl(
    tmp_path, monkeypatch, failure
):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    _restrict_windows_acl(path)
    security = _windows_security(path)
    before_stat = path.stat()
    before = path.read_bytes()
    real_delete = h5py.AttributeManager.__delitem__

    def fail_delete(attrs, name):
        if name == INFILTRATION_ATTRS[1]:
            raise OSError("injected deletion failure")
        real_delete(attrs, name)

    def fail_validation(edited_path):
        raise OSError("injected validation failure")

    if failure == "delete":
        monkeypatch.setattr(h5py.AttributeManager, "__delitem__", fail_delete)
    elif failure == "validation":
        monkeypatch.setattr(association, "read_geometry_association", fail_validation)
    if failure:
        with pytest.raises(OSError, match="injected"):
            RasMap.clear_geometry_infiltration(path)
        assert path.read_bytes() == before
    else:
        RasMap.clear_geometry_infiltration(path)
        assert not read_geometry_association(path)["infiltration_hdf_path"]
    assert _windows_security(path) == security
    after_stat = path.stat()
    assert (
        after_stat.st_dev,
        after_stat.st_ino,
        after_stat.st_nlink,
        after_stat.st_mode,
    ) == (
        before_stat.st_dev,
        before_stat.st_ino,
        before_stat.st_nlink,
        before_stat.st_mode,
    )
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name != "nt", reason="Windows backup DACL contract")
def test_backup_access_is_restricted_before_copy(tmp_path, monkeypatch):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    _restrict_windows_acl(path)
    source_dacl = _windows_security(path, 4)
    real_copy = shutil.copyfileobj

    def check_backup(original, backup, *args):
        (backup_path,) = tmp_path.glob(".*-infiltration-backup-*.hdf.bak")
        assert backup_path.stat().st_size == 0
        assert _windows_security(backup_path, 4) == source_dacl
        return real_copy(original, backup, *args)

    monkeypatch.setattr(association.shutil, "copyfileobj", check_backup)
    RasMap.clear_geometry_infiltration(path)
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name != "nt", reason="Windows backup DACL contract")
def test_backup_acl_failure_does_not_edit_original(tmp_path, monkeypatch):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = path.read_bytes()

    def fail_acl(original, backup):
        assert backup.stat().st_size == 0
        raise OSError("injected backup ACL failure")

    monkeypatch.setattr(association, "_protect_windows_backup_acl", fail_acl)
    with pytest.raises(OSError, match="injected backup ACL"):
        RasMap.clear_geometry_infiltration(path)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("fail_at", [1, 2])
def test_fsync_failure_preserves_original(tmp_path, monkeypatch, fail_at):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = path.read_bytes()
    before_stat = path.stat()
    real_fsync = os.fsync
    calls = []

    def fail_fsync(descriptor):
        calls.append(descriptor)
        if len(calls) == fail_at:
            raise OSError("injected fsync failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(association.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="injected fsync"):
        RasMap.clear_geometry_infiltration(path)
    assert path.read_bytes() == before
    assert path.stat().st_ino == before_stat.st_ino
    assert len(calls) == (1 if fail_at == 1 else 3)
    assert list(tmp_path.iterdir()) == [path]


def test_backup_cleanup_failure_rolls_back(tmp_path, monkeypatch):
    from pathlib import Path

    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = path.read_bytes()
    real_unlink = Path.unlink
    attempts = []

    def fail_once(backup, *args, **kwargs):
        assert backup != path
        attempts.append(backup)
        if len(attempts) == 1:
            raise OSError("injected cleanup failure")
        return real_unlink(backup, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)
    with pytest.raises(OSError, match="injected cleanup"):
        RasMap.clear_geometry_infiltration(path)
    assert path.read_bytes() == before
    assert len(attempts) == 2
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_interruption_rolls_back(tmp_path, monkeypatch, error):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = path.read_bytes()
    real_delete = h5py.AttributeManager.__delitem__

    def interrupt(attrs, name):
        real_delete(attrs, name)
        if name == INFILTRATION_ATTRS[1]:
            raise error("injected interruption")

    monkeypatch.setattr(h5py.AttributeManager, "__delitem__", interrupt)
    with pytest.raises(error, match="injected interruption"):
        RasMap.clear_geometry_infiltration(path)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_restore_failure_retains_exact_backup(tmp_path, monkeypatch):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = path.read_bytes()
    before_stat = path.stat()
    real_copy = shutil.copyfileobj

    def fail_validation(edited_path):
        raise OSError("injected validation failure")

    def fail_restore(source, destination, *args):
        if destination.name == str(path):
            destination.write(b"incomplete restoration")
            raise OSError("injected restore failure")
        return real_copy(source, destination, *args)

    monkeypatch.setattr(association, "read_geometry_association", fail_validation)
    monkeypatch.setattr(association.shutil, "copyfileobj", fail_restore)
    with pytest.raises(
        RuntimeError, match="restoration failed; recovery backup:"
    ) as caught:
        RasMap.clear_geometry_infiltration(path)
    (backup,) = tmp_path.glob(".*-infiltration-backup-*.hdf.bak")
    assert str(backup) in str(caught.value)
    assert backup.read_bytes() == before
    assert path.stat().st_ino == before_stat.st_ino


def test_process_crash_leaves_exact_recovery_backup(tmp_path):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = path.read_bytes()
    before_stat = path.stat()
    script = """
import os
import sys
import h5py
from ras_commander import RasMap
real_delete = h5py.AttributeManager.__delitem__
def crash(attrs, name):
    real_delete(attrs, name)
    os._exit(86)
h5py.AttributeManager.__delitem__ = crash
RasMap.clear_geometry_infiltration(sys.argv[1])
"""
    result = subprocess.run([sys.executable, "-c", script, str(path)], check=False)
    assert result.returncode == 86
    (backup,) = tmp_path.glob(".*-infiltration-backup-*.hdf.bak")
    assert backup.read_bytes() == before
    assert path.stat().st_ino == before_stat.st_ino
    # Exercise documented recovery into the existing file object.
    with path.open("r+b") as original, backup.open("rb") as source:
        original.truncate(0)
        shutil.copyfileobj(source, original)
        original.flush()
        os.fsync(original.fileno())
    backup.unlink()
    assert path.read_bytes() == before
    assert path.stat().st_ino == before_stat.st_ino


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only file attribute")
def test_readonly_input_fails_without_backup_leak(tmp_path):
    path = _geometry_file(tmp_path / "child.g02.hdf")
    before = path.read_bytes()
    path.chmod(stat.S_IREAD)
    try:
        with pytest.raises(PermissionError):
            RasMap.clear_geometry_infiltration(path)
        assert path.read_bytes() == before
        assert list(tmp_path.iterdir()) == [path]
    finally:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
