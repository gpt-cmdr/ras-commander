"""An HDF rewritten inside one public call is read anew by the next native read.

ras-commander's own workflows rewrite an HDF in the middle of a public call: in
place with h5py (``"r+"``/``"a"``), by replacing it after
``fast_hdf.release_native_sessions``, or through HEC-RAS / RAS Mapper in another
process (for example the breakline repair and remesh loop of
``RasBreakout2D.prepare_cloned_geometry``). File identity (size and
modification time) may be remembered only within one adapter-level read, never
across reads, so every read after a rewrite must return the new contents. Runs
with any installed extension (path-based or session-source typed reads).
"""
import importlib
import os

import h5py
import numpy as np
import pytest


@pytest.fixture
def fast_hdf(monkeypatch):
    pytest.importorskip("ras_commander_fast_hdf")
    monkeypatch.delenv("RAS_COMMANDER_HDF_SESSION_CACHE", raising=False)
    module = importlib.import_module("ras_commander.fast_hdf")
    if not module.available():
        pytest.skip("ras_commander.fast_hdf does not accept the installed extension")
    module.close_sessions()
    yield module
    module.close_sessions()


def _write(path, offset, rows=3):
    with h5py.File(path, "w") as f:
        f.create_dataset("Geometry/Names", data=np.array([b"n%d" % (i + offset) for i in range(rows)], dtype="S8"))
        f.create_dataset("Results/Values", data=np.arange(rows, dtype="f8") + offset)
        f["Results"].attrs["Offset"] = np.int64(offset)


def _read(path, fast_hdf):
    with h5py.File(path, "r") as f:
        return (list(fast_hdf.read_typed(f["Geometry/Names"], backend="rust")),
                fast_hdf.read_typed(f["Results/Values"], backend="rust").tolist(),
                int(fast_hdf.read_attr(f["Results"], "Offset", backend="rust")))


def _later_mtime(path):
    # Filesystem timestamps can be coarse; make the rewrite's identity change certain.
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2 * 10**9))


@pytest.fixture
def public_call():
    from ras_commander.Decorators import log_call

    @log_call
    def call(body, *args):
        return body(*args)
    return call


def test_in_place_rewrite_inside_a_public_call_is_seen(fast_hdf, public_call, tmp_path):
    path = tmp_path / "model.g01.hdf"
    _write(path, 0)

    def read_rewrite_read(hdf_path):
        first = _read(hdf_path, fast_hdf)
        # In-place write, no release_native_sessions (as the breakline repair loop does).
        with h5py.File(hdf_path, "r+") as f:
            f["Geometry/Names"][...] = np.array([b"m7", b"m8", b"m9"], dtype="S8")
            f["Results/Values"][...] = np.array([7.0, 8.0, 9.0])
            f["Results"].attrs["Offset"] = np.int64(7)
        _later_mtime(hdf_path)
        return first, _read(hdf_path, fast_hdf)

    first, second = public_call(read_rewrite_read, path)
    assert first == ([b"n0", b"n1", b"n2"], [0.0, 1.0, 2.0], 0)
    assert second == ([b"m7", b"m8", b"m9"], [7.0, 8.0, 9.0], 7)
    assert not fast_hdf._sessions


def test_append_mode_rewrite_inside_a_public_call_is_seen(fast_hdf, public_call, tmp_path):
    path = tmp_path / "model.g01.hdf"
    _write(path, 0)

    def read_rewrite_read(hdf_path):
        first = _read(hdf_path, fast_hdf)
        with h5py.File(hdf_path, "a") as f:  # delete and recreate, new size
            del f["Geometry"], f["Results"]
            f.create_dataset("Geometry/Names", data=np.array([b"x%d" % i for i in range(5)], dtype="S8"))
            f.create_dataset("Results/Values", data=np.arange(5, dtype="f8") * 2)
            f["Results"].attrs["Offset"] = np.int64(5)
        _later_mtime(hdf_path)
        return first, _read(hdf_path, fast_hdf)

    first, second = public_call(read_rewrite_read, path)
    assert first[2] == 0 and len(first[0]) == 3
    assert second == ([b"x0", b"x1", b"x2", b"x3", b"x4"], [0.0, 2.0, 4.0, 6.0, 8.0], 5)


def test_replace_inside_a_public_call_is_seen(fast_hdf, public_call, tmp_path):
    path, staged = tmp_path / "model.g01.hdf", tmp_path / "staged.hdf"
    _write(path, 0)
    _write(staged, 5, rows=4)

    def read_replace_read(hdf_path):
        first = _read(hdf_path, fast_hdf)
        fast_hdf.release_native_sessions(staged, hdf_path)  # as ras-commander's writers do
        os.replace(staged, hdf_path)
        return first, _read(hdf_path, fast_hdf)

    first, second = public_call(read_replace_read, path)
    assert first == ([b"n0", b"n1", b"n2"], [0.0, 1.0, 2.0], 0)
    assert second == ([b"n5", b"n6", b"n7", b"n8"], [5.0, 6.0, 7.0, 8.0], 5)


def test_rewrite_between_nested_public_calls_is_seen(fast_hdf, public_call, tmp_path):
    # The shape of the breakout repair loop: an outer public call runs an audit
    # (itself a public call), rewrites the HDF, and audits again.
    path = tmp_path / "model.g01.hdf"
    _write(path, 0)

    def outer(hdf_path):
        first = public_call(_read, hdf_path, fast_hdf)
        with h5py.File(hdf_path, "r+") as f:
            f["Results"].attrs["Offset"] = np.int64(3)
            f["Results/Values"][...] = np.array([3.0, 4.0, 5.0])
        _later_mtime(hdf_path)
        return first, public_call(_read, hdf_path, fast_hdf)

    first, second = public_call(outer, path)
    assert first[1:] == ([0.0, 1.0, 2.0], 0)
    assert second[1:] == ([3.0, 4.0, 5.0], 3)


def test_one_read_stats_each_file_once_and_reads_do_not_share_stats(fast_hdf, public_call, tmp_path, monkeypatch):
    path = tmp_path / "model.p01.hdf"
    _write(path, 0)
    stats = []
    real_stat = os.stat

    def counting_stat(p, *args, **kwargs):
        if os.path.basename(os.fspath(p)) == path.name:
            stats.append(os.fspath(p))
        return real_stat(p, *args, **kwargs)

    def one_read(hdf_path):
        with h5py.File(hdf_path, "r") as f:
            # Warm-up: the path is resolved once per public call, and on Python <= 3.12
            # Path.resolve() stats the file itself; measure the reads after it.
            fast_hdf.read_typed(f["Results/Values"], backend="rust")
            stats.clear()
            fast_hdf.read_typed(f["Results/Values"], backend="rust")
            first = list(stats)
            stats.clear()
            fast_hdf.read_typed(f["Results/Values"], backend="rust")
            return first, list(stats)

    monkeypatch.setattr(os, "stat", counting_stat)
    first, second = public_call(one_read, path)
    # Within one read: at most one stat per path spelling (h5py's filename, resolved path).
    assert first and len(first) == len(set(first)) <= 2
    # The next read stats the file again (nothing is remembered across reads).
    assert second and set(second) == set(first)
