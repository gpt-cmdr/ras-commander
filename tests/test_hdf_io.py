"""Unit tests for the shared read-only HDF open helper (ras_commander.hdf_io)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import hdf_io

FIXTURE_ENV = "RAS_H5PY_CACHE_FIXTURES"
_ENV_KEYS = (
    "RAS_COMMANDER_HDF_CHUNK_CACHE_MB",
    "RAS_COMMANDER_HDF_CHUNK_CACHE_SLOTS",
    "RAS_COMMANDER_HDF_CHUNK_CACHE_W0",
    "RAS_COMMANDER_HDF_HANDLE_CACHE",
    "RAS_COMMANDER_HDF_HANDLE_CACHE_SIZE",
)


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    hdf_io.configure_hdf_reads(
        chunk_cache_bytes=None,
        chunk_cache_slots=None,
        chunk_cache_w0=None,
        handle_cache=None,
        handle_cache_size=None,
    )
    hdf_io.close_hdf_handles()
    yield
    hdf_io.configure_hdf_reads(
        chunk_cache_bytes=None,
        chunk_cache_slots=None,
        chunk_cache_w0=None,
        handle_cache=None,
        handle_cache_size=None,
    )
    hdf_io.close_hdf_handles()


def _make_hdf(path: Path, rows: int = 8, cols: int = 64) -> Path:
    # Mechanics-only file for the helper; real-fixture parity lives in
    # test_hdf_io_fixture_parity.py.
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(
            "ts",
            data=np.arange(rows * cols, dtype=np.float32).reshape(rows, cols),
            chunks=(1, cols),
            compression="gzip",
        )
    return path


def _chunk_cache(hdf: h5py.File) -> tuple:
    return hdf["ts"].id.get_access_plist().get_chunk_cache()


def test_default_chunk_cache_is_applied_to_datasets(tmp_path):
    path = _make_hdf(tmp_path / "a.hdf")
    with hdf_io.open_hdf_read(path) as hdf:
        assert hdf.mode == "r"
        assert _chunk_cache(hdf) == (
            hdf_io.DEFAULT_CHUNK_CACHE_SLOTS,
            hdf_io.DEFAULT_CHUNK_CACHE_BYTES,
            hdf_io.DEFAULT_CHUNK_CACHE_W0,
        )
        mdc, nslots, nbytes, w0 = hdf.id.get_access_plist().get_cache()
        assert (nslots, nbytes, w0) == (10007, 64 * 1024 * 1024, 1.0)
    assert not hdf.id.valid  # reuse off: closed on exit


def test_default_slot_count_is_prime():
    n = hdf_io.DEFAULT_CHUNK_CACHE_SLOTS
    assert n > 1000 and all(n % d for d in range(2, int(n ** 0.5) + 1))


def test_env_overrides_and_off_switch(tmp_path, monkeypatch):
    path = _make_hdf(tmp_path / "a.hdf")
    monkeypatch.setenv("RAS_COMMANDER_HDF_CHUNK_CACHE_MB", "8")
    monkeypatch.setenv("RAS_COMMANDER_HDF_CHUNK_CACHE_SLOTS", "2003")
    monkeypatch.setenv("RAS_COMMANDER_HDF_CHUNK_CACHE_W0", "0.5")
    with hdf_io.open_hdf_read(path) as hdf:
        assert _chunk_cache(hdf) == (2003, 8 * 1024 * 1024, 0.5)
    monkeypatch.setenv("RAS_COMMANDER_HDF_CHUNK_CACHE_MB", "0")
    assert hdf_io.hdf_read_settings()["chunk_cache_bytes"] is None
    with h5py.File(path, "r") as plain:
        default = _chunk_cache(plain)
    with hdf_io.open_hdf_read(path) as hdf:
        assert _chunk_cache(hdf) == default


def test_configure_takes_precedence_and_none_resets(tmp_path, monkeypatch):
    path = _make_hdf(tmp_path / "a.hdf")
    monkeypatch.setenv("RAS_COMMANDER_HDF_CHUNK_CACHE_MB", "8")
    hdf_io.configure_hdf_reads(chunk_cache_bytes=16 * 1024 * 1024)
    with hdf_io.open_hdf_read(path) as hdf:
        assert _chunk_cache(hdf)[1] == 16 * 1024 * 1024
    hdf_io.configure_hdf_reads(chunk_cache_bytes=None)
    with hdf_io.open_hdf_read(path) as hdf:
        assert _chunk_cache(hdf)[1] == 8 * 1024 * 1024
    with pytest.raises(ValueError):
        hdf_io.configure_hdf_reads(chunk_cache_w0=1.5)
    with pytest.raises(ValueError):
        hdf_io.configure_hdf_reads(chunk_cache_slots=0)


def test_h5py_file_read_is_caller_owned(tmp_path):
    path = _make_hdf(tmp_path / "a.hdf")
    hdf_io.configure_hdf_reads(handle_cache=True)
    first = hdf_io.h5py_file_read(path)
    second = hdf_io.h5py_file_read(path)
    try:
        assert first is not second
        assert _chunk_cache(first)[1] == hdf_io.DEFAULT_CHUNK_CACHE_BYTES
        assert hdf_io.cached_hdf_handle_count() == 0
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("reuse", [False, True])
def test_missing_file_raises_like_h5py(tmp_path, reuse):
    hdf_io.configure_hdf_reads(handle_cache=reuse)
    missing = tmp_path / "missing.hdf"
    with pytest.raises(FileNotFoundError) as plain:
        h5py.File(missing, "r")
    with pytest.raises(FileNotFoundError) as routed:
        with hdf_io.open_hdf_read(missing):
            pass
    assert type(routed.value) is type(plain.value)
    assert str(routed.value) == str(plain.value)


@pytest.mark.parametrize("reuse", [False, True])
def test_not_hdf5_raises_like_h5py(tmp_path, reuse):
    hdf_io.configure_hdf_reads(handle_cache=reuse)
    bogus = tmp_path / "bogus.hdf"
    bogus.write_bytes(b"not an hdf5 file")
    with pytest.raises(OSError) as plain:
        h5py.File(bogus, "r")
    with pytest.raises(OSError) as routed:
        with hdf_io.open_hdf_read(bogus):
            pass
    assert type(routed.value) is type(plain.value)
    assert str(routed.value) == str(plain.value)
    assert hdf_io.cached_hdf_handle_count() == 0


def test_body_exception_propagates_and_closes(tmp_path):
    path = _make_hdf(tmp_path / "a.hdf")
    with pytest.raises(KeyError):
        with hdf_io.open_hdf_read(path) as hdf:
            hdf["does/not/exist"]
    assert not hdf.id.valid


def test_handle_reuse_returns_same_open_handle(tmp_path):
    path = _make_hdf(tmp_path / "a.hdf")
    hdf_io.configure_hdf_reads(handle_cache=True)
    with hdf_io.open_hdf_read(path) as first:
        values = first["ts"][2]
    with hdf_io.open_hdf_read(path) as second:
        assert second is first
        assert np.array_equal(second["ts"][2], values)
    assert first.id.valid
    assert first.filename == str(path)
    assert hdf_io.cached_hdf_handle_count() == 1
    assert hdf_io.close_hdf_handles(path) == 1
    assert not first.id.valid
    assert hdf_io.cached_hdf_handle_count() == 0


def test_env_enables_reuse(tmp_path, monkeypatch):
    path = _make_hdf(tmp_path / "a.hdf")
    monkeypatch.setenv("RAS_COMMANDER_HDF_HANDLE_CACHE", "1")
    with hdf_io.open_hdf_read(path) as first:
        pass
    with hdf_io.open_hdf_read(path) as again:
        assert again is first
    other_spelling = str(path).replace("\\", "/")
    with hdf_io.open_hdf_read(other_spelling) as second:
        pass
    assert first.id.valid and second.id.valid
    # Each spelling keeps its own handle so File.filename is exactly what the
    # caller passed (as without reuse); close-by-path matches all spellings.
    assert first.filename == str(path)
    assert second.filename == other_spelling
    assert hdf_io.cached_hdf_handle_count() == 2
    assert hdf_io.close_hdf_handles(path) == 2


def test_reuse_invalidates_on_size_or_mtime_change(tmp_path):
    path = _make_hdf(tmp_path / "a.hdf")
    hdf_io.configure_hdf_reads(handle_cache=True)
    with hdf_io.open_hdf_read(path) as first:
        assert first["ts"].shape == (8, 64)
    hdf_io.close_hdf_handles(path)  # writer must close before replacing on Windows
    _make_hdf(tmp_path / "a.hdf", rows=12)
    with hdf_io.open_hdf_read(path) as cached:
        assert cached["ts"].shape == (12, 64)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    with hdf_io.open_hdf_read(path) as reopened:
        assert reopened is not cached
    assert not cached.id.valid
    assert hdf_io.cached_hdf_handle_count() == 1


def test_lru_limit_and_in_use_handles_are_not_evicted(tmp_path):
    hdf_io.configure_hdf_reads(handle_cache=True, handle_cache_size=2)
    paths = [_make_hdf(tmp_path / f"{i}.hdf") for i in range(3)]
    with hdf_io.open_hdf_read(paths[0]) as held:
        with hdf_io.open_hdf_read(paths[1]) as second:
            pass
        with hdf_io.open_hdf_read(paths[2]) as third:
            pass
        assert held.id.valid  # oldest, but in use: skipped by eviction
        assert not second.id.valid  # oldest idle handle evicted instead
        assert third.id.valid
        assert hdf_io.cached_hdf_handle_count() == 2
    with hdf_io.open_hdf_read(paths[1]):
        pass
    assert not held.id.valid  # now idle and oldest
    assert third.id.valid
    assert hdf_io.cached_hdf_handle_count() == 2


def test_close_while_in_use_defers_until_release(tmp_path):
    path = _make_hdf(tmp_path / "a.hdf")
    hdf_io.configure_hdf_reads(handle_cache=True)
    with hdf_io.open_hdf_read(path) as hdf:
        assert hdf_io.close_hdf_handles() == 1
        assert hdf.id.valid
        assert np.array_equal(hdf["ts"][0], np.arange(64, dtype=np.float32))
    assert not hdf.id.valid


def test_caller_closing_shared_handle_is_tolerated(tmp_path):
    path = _make_hdf(tmp_path / "a.hdf")
    hdf_io.configure_hdf_reads(handle_cache=True)
    with hdf_io.open_hdf_read(path) as hdf:
        hdf.close()
    assert hdf_io.cached_hdf_handle_count() == 0
    with hdf_io.open_hdf_read(path) as again:
        assert again.id.valid


def test_disabling_reuse_closes_cached_handles(tmp_path):
    path = _make_hdf(tmp_path / "a.hdf")
    hdf_io.configure_hdf_reads(handle_cache=True)
    with hdf_io.open_hdf_read(path) as hdf:
        pass
    hdf_io.configure_hdf_reads(handle_cache=False)
    assert not hdf.id.valid
    assert hdf_io.cached_hdf_handle_count() == 0


def test_cached_read_handle_blocks_inprocess_writer_until_closed(tmp_path):
    """Why reuse is opt-in: HDF5 refuses r+ while a read-only handle is open."""
    path = _make_hdf(tmp_path / "a.hdf")
    hdf_io.configure_hdf_reads(handle_cache=True)
    with hdf_io.open_hdf_read(path):
        pass
    with pytest.raises(OSError, match="already open for read-only"):
        h5py.File(path, "r+")
    hdf_io.close_hdf_handles(path)
    with h5py.File(path, "r+") as writer:
        writer["ts"][0, 0] = -1.0


def test_decorator_routes_through_helper(tmp_path):
    from ras_commander.Decorators import standardize_input

    path = _make_hdf(tmp_path / "a.hdf")
    seen = {}

    @standardize_input(file_type="plan_hdf")
    def reader(hdf_file, row):
        seen["cache"] = hdf_file["ts"].id.get_access_plist().get_chunk_cache()
        return hdf_file["ts"][row]

    assert np.array_equal(reader(path, 1), np.arange(64, 128, dtype=np.float32))
    assert seen["cache"][1] == hdf_io.DEFAULT_CHUNK_CACHE_BYTES


def _rascmdr_module():
    import importlib

    return importlib.import_module("ras_commander.RasCmdr")


@pytest.mark.parametrize(
    "entry, args",
    [
        ("compute_plan", ("01",)),
        ("compute_parallel", ()),
        ("compute_test_mode", ()),
    ],
)
def test_execution_entry_points_close_cached_handles(tmp_path, monkeypatch, entry, args):
    module = _rascmdr_module()
    path = _make_hdf(tmp_path / "a.hdf")
    hdf_io.configure_hdf_reads(handle_cache=True)
    with hdf_io.open_hdf_read(path) as hdf:
        pass
    assert hdf_io.cached_hdf_handle_count() == 1

    class Stop(Exception):
        pass

    def stop(api_name):
        raise Stop(api_name)

    monkeypatch.setattr(module, "_require_process_supervision", stop)
    with pytest.raises(Stop):
        getattr(module.RasCmdr, entry)(*args)
    assert hdf_io.cached_hdf_handle_count() == 0
    assert not hdf.id.valid


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing-violation semantics")
def test_windows_replace_and_delete_after_close_on_real_fixture(tmp_path):
    root = os.environ.get(FIXTURE_ENV)
    if not root:
        pytest.skip(f"set {FIXTURE_ENV} to the qualification fixture directory")
    source = Path(root) / "AustinOyster.p01.hdf"
    if not source.is_file():
        pytest.skip(f"{source} not available")
    from ras_commander import HdfResultsMesh

    target = tmp_path / source.name
    replacement = tmp_path / "replacement.hdf"
    shutil.copy2(source, target)
    shutil.copy2(source, replacement)
    hdf_io.configure_hdf_reads(handle_cache=True)
    before = HdfResultsMesh.get_mesh_max_ws(target)
    assert hdf_io.cached_hdf_handle_count() >= 1
    with pytest.raises(PermissionError):
        os.replace(replacement, target)
    with pytest.raises(PermissionError):
        os.remove(target)
    hdf_io.close_hdf_handles(target)
    assert hdf_io.cached_hdf_handle_count() == 0
    os.replace(replacement, target)
    after = HdfResultsMesh.get_mesh_max_ws(target)
    assert before.equals(after)
    hdf_io.close_hdf_handles()
    os.remove(target)
    assert not target.exists()
