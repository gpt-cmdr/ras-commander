"""Cached native sessions are released before an HDF is replaced in place.

Windows refuses to replace or rename a file the engine still maps. Writers call
``fast_hdf.release_native_sessions`` on both paths immediately before
``os.replace``/``shutil.move``; a session opened earlier in the same public call
(or persisted outside one) must not block the replacement or serve stale values.
"""
import importlib
import os
import sys

import h5py
import numpy as np
import pytest


@pytest.fixture
def native():
    return pytest.importorskip("ras_commander_fast_hdf")


def _write(path, offset):
    with h5py.File(path, "w") as f:
        f.create_dataset("values", data=np.arange(12, dtype="f8").reshape(3, 4) + offset)


def test_release_unblocks_replace_and_drops_stale_values(native, tmp_path):
    fast_hdf = importlib.import_module("ras_commander.fast_hdf")
    fast_hdf.close_sessions()
    target, staged = tmp_path / "model.g01.hdf", tmp_path / ".model.g01.hdf.tmp"
    _write(target, 0)
    _write(staged, 100)
    with h5py.File(target) as f:
        np.testing.assert_array_equal(
            fast_hdf.read_dataset(f["values"], backend="rust"), f["values"][()])
    with fast_hdf._session(native, target):
        pass  # the session stays cached after the read
    if sys.platform == "win32":
        with pytest.raises(PermissionError):
            os.replace(staged, target)

    fast_hdf.release_native_sessions(staged, target)
    os.replace(staged, target)
    with h5py.File(target) as f:
        np.testing.assert_array_equal(
            fast_hdf.read_dataset(f["values"], backend="rust"),
            np.arange(12, dtype="f8").reshape(3, 4) + 100)
    fast_hdf.close_sessions()


def test_release_ignores_unknown_and_missing_paths(tmp_path):
    fast_hdf = importlib.import_module("ras_commander.fast_hdf")
    fast_hdf.release_native_sessions(None, tmp_path / "absent.hdf", tmp_path / "notes.txt")
