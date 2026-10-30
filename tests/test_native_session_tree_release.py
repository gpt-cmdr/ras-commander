"""Directory moves inside a public call: sessions under the tree must be released first.

Sessions opened inside a public call stay mapped until the outermost call returns
(``ras_commander._native_scope``). Windows refuses to rename, replace or delete a
folder holding a mapped file, so code that moves or removes a project tree inside
a public call releases the sessions under it first.
"""

import os

import h5py
import numpy as np
import pytest

from ras_commander import _native_scope, fast_hdf


@pytest.fixture
def native(monkeypatch):
    module, _, _ = fast_hdf._load_native()
    if module is None:
        pytest.skip("native extension not installed")
    monkeypatch.delenv("RAS_COMMANDER_HDF_SESSION_CACHE", raising=False)
    yield module
    fast_hdf.close_sessions()


def _open_under(folder):
    root = os.path.normcase(str(folder.resolve())) + os.sep
    with fast_hdf._sessions_lock:
        return [key[0] for key in fast_hdf._sessions if os.path.normcase(key[0]).startswith(root)]


def _project(tmp_path):
    folder = tmp_path / "staged" / "project"
    (folder / "nested").mkdir(parents=True)
    for path in (folder / "Model.g01.hdf", folder / "nested" / "Model.p01.hdf"):
        with h5py.File(path, "w") as hdf:
            hdf["values"] = np.arange(4.0)
    return folder


def test_release_native_sessions_closes_every_session_under_a_directory(tmp_path, native):
    folder = _project(tmp_path)
    outside = tmp_path / "Other.p01.hdf"
    with h5py.File(outside, "w") as hdf:
        hdf["values"] = np.arange(4.0)
    depth = _native_scope.enter()
    try:
        for path in (folder / "Model.g01.hdf", folder / "nested" / "Model.p01.hdf", outside):
            with fast_hdf._session(native, path):
                pass
        assert len(_open_under(folder)) == 2

        fast_hdf.release_native_sessions(folder)

        assert _open_under(folder) == []
        assert _open_under(tmp_path) == [str(outside.resolve())]  # other files stay cached
        os.rename(folder, tmp_path / "published")  # refused on Windows while mapped
    finally:
        _native_scope.leave(depth)
    assert (tmp_path / "published" / "nested" / "Model.p01.hdf").is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length paths")
def test_release_matches_sessions_opened_through_extended_length_paths(tmp_path, native):
    # Staging reads its copy through \\?\ paths; the folder is released by its plain path.
    folder = _project(tmp_path)
    depth = _native_scope.enter()
    try:
        with fast_hdf._session(native, "\\\\?\\" + str((folder / "Model.g01.hdf").resolve())):
            pass
        assert fast_hdf._sessions
        fast_hdf.release_native_sessions(folder)
        assert _open_under(folder) == [] and not fast_hdf._sessions
        os.rename(folder, tmp_path / "published")
    finally:
        _native_scope.leave(depth)


def test_released_tree_reads_again_with_the_same_values(tmp_path, native):
    folder = _project(tmp_path)
    path = folder / "Model.g01.hdf"
    depth = _native_scope.enter()
    try:
        with h5py.File(path, "r") as hdf:
            before = fast_hdf.read_dataset(hdf["values"])
        fast_hdf.release_native_sessions(folder)
        with h5py.File(path, "r") as hdf:
            after = fast_hdf.read_dataset(hdf["values"])
    finally:
        _native_scope.leave(depth)
    np.testing.assert_array_equal(before, after)
    np.testing.assert_array_equal(after, np.arange(4.0))
