"""Binding regressions not reliably represented by the real HEC-RAS corpus.

Real-data conformance lives in test_fast_hdf_real.py. Tests requiring the optional
extension explicitly skip when absent, rather than succeeding through fallback.
"""
import h5py
import numpy as np
import pytest


@pytest.fixture
def native():
    return pytest.importorskip("ras_commander_fast_hdf")


def assert_exact(actual, expected):
    assert actual.shape == expected.shape
    assert actual.dtype == expected.dtype
    assert actual.tobytes(order="C") == expected.tobytes(order="C")


@pytest.mark.parametrize("dtype", ["i1", "u1", "i2", "u2", "i4", "u4", "i8", "u8", "f4", "f8"])
@pytest.mark.parametrize("compressed", [False, True])
def test_numeric_dtype_shape_and_chunk_tail(native, tmp_path, dtype, compressed):
    path = tmp_path / "types.hdf"
    values = np.arange(77, dtype=dtype).reshape(7, 11)
    if dtype in ("i8", "u8"):
        values += 2**54  # Detect accidental conversion through f64.
    kwargs = dict(chunks=(3, 4), compression="gzip", shuffle=True) if compressed else {}
    with h5py.File(path, "w") as f:
        f.create_dataset("data", data=values, **kwargs)
    for parallel in (False, True):
        assert_exact(native.read_numeric(str(path), "data", threads=2, parallel=parallel), values)
        result = native.read_numeric(str(path), "data", selection=[(1, 7, 2), (2, 11, 3)],
                                     threads=2, parallel=parallel)
        assert_exact(result, values[1:7:2, 2:11:3])


def test_float_payload_and_fill(native, tmp_path):
    path = tmp_path / "payload.hdf"
    values = np.array([0, 0x80000000, 0x7FC12345, 0x7F800000, 0xFF800000], dtype="u4").view("f4")
    with h5py.File(path, "w") as f:
        f.create_dataset("payload", data=values, compression="gzip")
        fill = f.create_dataset("fill", shape=(8, 9), chunks=(3, 4), dtype="i4", fillvalue=-9999)
        fill[:2, :3] = 42
    with h5py.File(path, "r") as f:
        for name in f:
            assert_exact(native.read_numeric(str(path), name, threads=2), f[name][()])


def test_scalar_and_empty(native, tmp_path):
    path = tmp_path / "small.hdf"
    with h5py.File(path, "w") as f:
        f["scalar"] = np.int32(42)
        f.create_dataset("empty", shape=(0, 3), dtype="f8")
    with h5py.File(path, "r") as f:
        for name in f:
            assert_exact(native.read_numeric(str(path), name), np.asarray(f[name][()]))


@pytest.mark.parametrize("dtype", [">f4", ">i4"])
def test_endian_is_preserved_or_explicitly_unsupported(native, tmp_path, dtype):
    path = tmp_path / "endian.hdf"
    with h5py.File(path, "w") as f:
        f["data"] = np.arange(5, dtype=dtype)
    with h5py.File(path, "r") as f:
        try:
            result = native.read_numeric(str(path), "data")
        except native.UnsupportedError:
            return  # The adapter must then use h5py, preserving the dtype.
        assert_exact(result, f["data"][()])


def test_unsupported_and_missing_are_distinct(native, tmp_path):
    path = tmp_path / "unsupported.hdf"
    with h5py.File(path, "w") as f:
        f["strings"] = np.array([b"abc", b"def"])
        f["compound"] = np.array([(1, 2.5)], dtype=[("id", "i4"), ("value", "f8")])
    for name in ("strings", "compound"):
        with pytest.raises(native.UnsupportedError):
            native.read_numeric(str(path), name)
    with pytest.raises(Exception) as exc:
        native.read_numeric(str(path), "missing")
    assert not isinstance(exc.value, native.UnsupportedError)


def test_batch_and_invalid_selection(native, tmp_path):
    path = tmp_path / "selection.hdf"
    values = np.arange(12, dtype="i4").reshape(3, 4)
    with h5py.File(path, "w") as f:
        f["a"] = values
        f["b"] = values + 3
    batch = native.read_numeric_batch(str(path), ["a", "b"], threads=2)
    assert set(batch) == {"a", "b"}
    assert_exact(batch["a"], values)
    assert_exact(batch["b"], values + 3)
    for selection in [[(0, 3, 0), (0, 4, 1)], [(0, 4, 1), (0, 4, 1)], [(0, 3, 1)]]:
        with pytest.raises((ValueError, IndexError)):
            native.read_numeric(str(path), "a", selection=selection)


def test_adapter_disable_and_live_writable_handle(tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    path = tmp_path / "live.hdf"
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
    with h5py.File(path, "w", driver="core", backing_store=False) as f:
        ds = f.create_dataset("data", data=np.arange(10, dtype="i4"))
        assert_exact(fast_hdf.read_dataset(ds), ds[()])
        assert_exact(fast_hdf.read_dataset(ds, slice(2, 8, 2)), ds[2:8:2])
    assert not path.exists()


def test_adapter_unsupported_preserves_endian(tmp_path):
    from ras_commander import fast_hdf
    path = tmp_path / "fallback.hdf"
    with h5py.File(path, "w") as f:
        f["data"] = np.arange(10, dtype=">i4")
        f["strings"] = np.array([b"one", b"two"])
    with h5py.File(path, "r") as f:
        for ds in f.values():
            assert_exact(fast_hdf.read_dataset(ds), ds[()])


def test_non_deflate_filter_is_exact_or_falls_back(native, tmp_path):
    from ras_commander import fast_hdf
    path = tmp_path / "lzf.hdf"
    values = np.arange(1000, dtype="i4").reshape(20, 50)
    with h5py.File(path, "w") as f:
        f.create_dataset("data", data=values, compression="lzf", shuffle=True)
    try:
        assert_exact(native.read_numeric(str(path), "data"), values)
    except native.UnsupportedError:
        pass
    with h5py.File(path, "r") as f:
        assert_exact(fast_hdf.read_dataset(f["data"]), values)


def test_adapter_native_required_is_observable(native, tmp_path):
    from ras_commander import fast_hdf
    assert fast_hdf.available()
    path = tmp_path / "required.hdf"
    with h5py.File(path, "w") as f:
        f["data"] = np.arange(8, dtype="f4")
    with h5py.File(path, "r") as f:
        assert_exact(fast_hdf.read_dataset(f["data"], backend="rust"), f["data"][()])


def test_missing_extension_auto_fallback_and_explicit_error(tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    real_import = fast_hdf.importlib.import_module
    def without_native(name, *args, **kwargs):
        if name == "ras_commander_fast_hdf":
            raise ImportError("Optional extension intentionally absent")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(fast_hdf.importlib, "import_module", without_native)
    # Forget a cached import of an installed extension; monkeypatch restores it.
    monkeypatch.setattr(fast_hdf, "_native_state", None)
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    assert not fast_hdf.available()
    path = tmp_path / "fallback.hdf"
    with h5py.File(path, "w") as f:
        f["data"] = np.arange(6, dtype="i4")
    with h5py.File(path, "r") as f:
        assert_exact(fast_hdf.read_dataset(f["data"]), f["data"][()])
        with pytest.raises(fast_hdf.FastHdfError, match="unavailable"):
            fast_hdf.read_dataset(f["data"], backend="rust")


@pytest.mark.parametrize("selection", [(1, slice(None)), (Ellipsis, -1),
    (slice(2, 2), slice(None)), (slice(None, None, 2), slice(1, 4, 2))])
def test_adapter_indexing_contract(native, tmp_path, selection):
    from ras_commander import fast_hdf
    path = tmp_path / "index.hdf"
    with h5py.File(path, "w") as f:
        f["data"] = np.arange(20, dtype="f8").reshape(4, 5)
    with h5py.File(path, "r") as f:
        assert_exact(fast_hdf.read_dataset(f["data"], selection, backend="rust"),
                     np.asarray(f["data"][selection]))


def test_failed_native_write_is_atomic(native, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    output = tmp_path / "existing.pmtiles"
    output.write_bytes(b"existing archive")
    coords = np.array([[0., 0.], [.1, 0.], [.1, .1], [0., 0.]])
    layer = dict(coordinates=coords, offsets=np.array([0, 4], dtype="i8"),
                 cell_ids=np.array([0], dtype="i8"))
    def failed_write(layers, destination, *args, **kwargs):
        from pathlib import Path
        Path(destination).write_bytes(b"incomplete staged archive")
        raise OSError("Injected disk write failure")
    monkeypatch.setattr(native, "write_pmtiles", failed_write)
    with pytest.raises(fast_hdf.FastHdfError, match="Injected disk write failure"):
        fast_hdf.export_pmtiles(output, {"cells": layer}, backend="rust")
    assert output.read_bytes() == b"existing archive"
    assert [p.name for p in tmp_path.iterdir()] == [output.name]
