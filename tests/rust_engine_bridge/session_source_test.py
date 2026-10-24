"""Typed reads inside one public call share the call's native session.

An extension that advertises ``SESSION_SOURCES`` accepts an open ``HdfSession``
in place of the path for its path-based typed entry points. Inside a public call
the adapter passes the call's cached session, so the HDF is mapped once and the
engine's metadata proofs are shared; the values must be exactly what the path
calls (and h5py) return, and nothing may stay open after the call returns.
"""
import importlib
import os

import h5py
import numpy as np
import pytest


@pytest.fixture
def native():
    module = pytest.importorskip("ras_commander_fast_hdf")
    if getattr(module, "SESSION_SOURCES", False) is not True:
        pytest.skip("extension without session sources")
    return module


@pytest.fixture
def fast_hdf(monkeypatch):
    monkeypatch.delenv("RAS_COMMANDER_HDF_SESSION_CACHE", raising=False)
    module = importlib.import_module("ras_commander.fast_hdf")
    module.close_sessions()
    yield module
    module.close_sessions()


def _write(path):
    with h5py.File(path, "w") as f:
        names = np.array([b"alpha", b"be", b"", b"gamma ray"], dtype="S10")
        f.create_dataset("Geometry/Names", data=names)
        group = f.create_group("Results")
        group.attrs["Units"] = np.bytes_(b"US Customary")
        group.attrs["Count"] = np.int32(4)
        values = f.create_dataset("Results/Values", data=np.arange(12, dtype="f8").reshape(3, 4))
        values.attrs["Scale"] = np.float64(0.5)


def _reads(path, fast_hdf):
    with h5py.File(path, "r") as f:
        return {
            "names": fast_hdf.read_typed(f["Geometry/Names"], backend="rust"),
            "group_attrs": fast_hdf.read_attrs(f["Results"], backend="rust"),
            "dataset_attrs": fast_hdf.read_attrs(f["Results/Values"], backend="rust"),
            "values": fast_hdf.read_typed(f["Results/Values"], backend="rust"),
            "names_again": fast_hdf.read_typed(f["Geometry/Names"], (slice(1, 3),), backend="rust"),
        }


def _h5py(path):
    with h5py.File(path, "r") as f:
        return {
            "names": f["Geometry/Names"][()],
            "group_attrs": {k: f["Results"].attrs[k] for k in f["Results"].attrs},
            "dataset_attrs": {k: f["Results/Values"].attrs[k] for k in f["Results/Values"].attrs},
            "values": f["Results/Values"][()],
            "names_again": f["Geometry/Names"][1:3],
        }


def _assert_same(a, b):
    assert a.keys() == b.keys()
    for key in a:
        x, y = a[key], b[key]
        if isinstance(x, dict):
            assert list(x) == list(y), key
            for name in x:
                assert type(x[name]) is type(y[name]) and x[name] == y[name], (key, name)
        else:
            assert x.dtype == y.dtype and x.shape == y.shape, key
            np.testing.assert_array_equal(x, y)


def _spy(native, monkeypatch, name, sources):
    real = getattr(native, name)

    def spy(source, *args, **kwargs):
        sources.append(type(source).__name__)
        return real(source, *args, **kwargs)
    monkeypatch.setattr(native, name, spy)


def test_public_call_maps_the_file_once_and_returns_the_path_values(native, fast_hdf, tmp_path, monkeypatch):
    from ras_commander.Decorators import log_call
    from ras_commander import _fast_hdf_typed
    path = tmp_path / "model.p01.hdf"
    _write(path)
    expected = _h5py(path)

    # Outside a public call: path calls, nothing cached.
    sources = []
    for name in ("raw_fixed_strings", "typed_group_attributes", "typed_dataset_attributes"):
        _spy(native, monkeypatch, name, sources)
    _fast_hdf_typed.clear_cache()
    outside = _reads(path, fast_hdf)
    assert sources and set(sources) == {"str"}
    assert not fast_hdf._sessions
    _assert_same(outside, expected)

    opened = []
    real_session = native.HdfSession

    def counting_session(*args, **kwargs):
        opened.append(args[0])
        return real_session(*args, **kwargs)
    monkeypatch.setattr(native, "HdfSession", counting_session)

    @log_call
    def public_call(hdf_path):
        return _reads(hdf_path, fast_hdf)

    sources.clear()
    _fast_hdf_typed.clear_cache()
    inside = public_call(path)
    assert sources and set(sources) == {"HdfSession"}
    assert len(opened) == 1
    _assert_same(inside, expected)
    # The call's session is closed when it returns: the file can be renamed.
    assert not fast_hdf._sessions
    os.replace(path, tmp_path / "renamed.p01.hdf")


def test_session_cache_off_and_older_extensions_keep_path_calls(native, fast_hdf, tmp_path, monkeypatch):
    from ras_commander.Decorators import log_call
    from ras_commander import _fast_hdf_typed
    path = tmp_path / "model.p01.hdf"
    _write(path)
    expected = _h5py(path)
    sources = []
    _spy(native, monkeypatch, "raw_fixed_strings", sources)

    @log_call
    def public_call(hdf_path):
        return _reads(hdf_path, fast_hdf)

    monkeypatch.setenv("RAS_COMMANDER_HDF_SESSION_CACHE", "0")
    _assert_same(public_call(path), expected)
    monkeypatch.delenv("RAS_COMMANDER_HDF_SESSION_CACHE")
    monkeypatch.setattr(native, "SESSION_SOURCES", False)
    _fast_hdf_typed.clear_cache()
    _assert_same(public_call(path), expected)
    assert sources and set(sources) == {"str"}
    assert not fast_hdf._sessions


def test_path_resolution_is_remembered_only_inside_a_public_call(fast_hdf, tmp_path, monkeypatch):
    from pathlib import Path
    from ras_commander.Decorators import log_call
    from ras_commander import _native_scope
    target = tmp_path / "model.p01.hdf"
    target.write_bytes(b"")
    calls = []
    real = Path.resolve

    def counting(self, *args, **kwargs):
        calls.append(str(self))
        return real(self, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", counting)

    for _ in range(3):
        assert fast_hdf._resolved(str(target)) == str(real(target))
    assert len(calls) == 3 and _native_scope.memo() is None

    @log_call
    def public_call():
        return [fast_hdf._resolved(str(target)) for _ in range(3)]

    calls.clear()
    assert public_call() == [str(real(target))] * 3
    assert len(calls) == 1
    assert _native_scope.memo() is None
    # A relative path is keyed with the working directory.
    monkeypatch.chdir(tmp_path)
    calls.clear()

    @log_call
    def relative_call():
        first = fast_hdf._resolved("model.p01.hdf")
        os.chdir(tmp_path.parent)
        second = fast_hdf._resolved("model.p01.hdf")
        return first, second

    first, second = relative_call()
    assert first == str(real(target)) and second == str(real(tmp_path.parent / "model.p01.hdf"))
    assert len(calls) == 2
