"""Native chunked reads above the engine's per-call budget (``fast_hdf._read_chunked``).

The engine refuses any single numeric read over 2 GiB before allocating.
``fast_hdf`` serves larger reads as bounded hyperslab blocks into one NumPy
output, after checking the declared size against the file's real storage. The
budgets are shrunk here (``small_budget``) so every dataset stays a few KiB;
the benchmarks in CHUNKED_READS.md cover the real 2 GiB boundary.
"""
import importlib
import struct
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

fast_hdf = importlib.import_module("ras_commander.fast_hdf")
CALL_BUDGET = 4096
BLOCK_BYTES = 1024
FIXTURES = Path(__file__).with_name("fixtures")


@pytest.fixture
def native():
    return pytest.importorskip("ras_commander_fast_hdf")


@pytest.fixture
def small_budget(native, monkeypatch):
    monkeypatch.setattr(fast_hdf, "_NATIVE_CALL_BUDGET", CALL_BUDGET)
    monkeypatch.setattr(fast_hdf, "_CHUNKED_BLOCK_BYTES", BLOCK_BYTES)
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    fast_hdf.close_sessions()
    yield
    fast_hdf.close_sessions()


def _read(dataset, selection=None, backend="rust"):
    with fast_hdf.trace_reads() as records:
        values = fast_hdf.read_dataset(dataset, selection, backend=backend)
    return values, records[-1]


def _assert_identical(actual, expected):
    # Same dtype (byte order included), shape and bytes: NaN payloads compare bitwise.
    assert isinstance(actual, np.ndarray)
    assert actual.dtype == expected.dtype and actual.dtype.str == expected.dtype.str
    assert actual.shape == expected.shape
    assert actual.tobytes() == expected.tobytes()


def _assert_chunked(record):
    assert record["backend"] == "native-generic" and record["route"] == "chunked"
    assert int(record["detail"].split()[0]) > 1


NAN_BITS = {
    "f4": ("<u4", [0x7FC00001, 0x7F800001, 0xFFC12345, 0x7FFFFFFF]),
    "f8": ("<u8", [0x7FF8000000000001, 0x7FF0000000000001, 0xFFF8DEADBEEF0001]),
}


def _values(dtype, shape, seed=0):
    rng = np.random.default_rng(seed)
    dtype = np.dtype(dtype)
    size = int(np.prod(shape))
    if dtype.kind == "f":
        values = rng.standard_normal(size).astype(dtype)
        bits, payloads = NAN_BITS[dtype.str[1:]]
        # Quiet, signalling and negative NaNs with payloads; also infinities.
        values[: len(payloads)] = np.array(payloads, dtype=bits).view(dtype.newbyteorder("<"))
        values[-1], values[-2] = np.inf, -np.inf
    else:
        info = np.iinfo(dtype)
        values = rng.integers(info.min, info.max, size=size, dtype=dtype, endpoint=True)
    rng.shuffle(values)
    return values.reshape(shape)


SHAPES = {1: ((3000,), (256,)), 2: ((40, 57), (7, 16)), 3: ((9, 13, 11), (2, 5, 4))}
LAYOUTS = {
    "contiguous": lambda chunks: {},
    "chunked": lambda chunks: {"chunks": chunks},
    "gzip": lambda chunks: {"chunks": chunks, "compression": "gzip", "shuffle": True},
}


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
@pytest.mark.parametrize("ndim", sorted(SHAPES))
@pytest.mark.parametrize("dtype", ["<f4", "<f8", "<i4", "<u8"])
def test_whole_read_is_identical_to_h5py(small_budget, tmp_path, dtype, ndim, layout):
    shape, chunks = SHAPES[ndim]
    path = tmp_path / "values.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("v", data=_values(dtype, shape), **LAYOUTS[layout](chunks))
    with h5py.File(path, "r") as f:
        expected = f["v"][()]
        assert expected.nbytes > CALL_BUDGET
        for backend in ("rust", "auto"):
            values, record = _read(f["v"], backend=backend)
            _assert_identical(values, expected)
            _assert_chunked(record)


def test_required_environment_serves_natively(small_budget, tmp_path, monkeypatch):
    path = tmp_path / "values.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("v", data=_values("<f4", (40, 57)), chunks=(3, 57), compression="gzip")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    with h5py.File(path, "r") as f:
        values, record = _read(f["v"], backend="auto")
        _assert_identical(values, f["v"][()])
        _assert_chunked(record)
        with fast_hdf.trace_reads() as records:
            typed = fast_hdf.read_typed(f["v"])
        _assert_identical(typed, f["v"][()])
        _assert_chunked(records[-1])


SELECTIONS = [
    (slice(1, 19), slice(2, 39), slice(None)),
    (slice(None, None, 2), slice(1, None, 3), slice(0, 17, 2)),
    (7, slice(None), slice(None)),
    (slice(3, 17), Ellipsis),
    (slice(2, 20, 7), slice(None), slice(4, 16)),
]


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
@pytest.mark.parametrize("selection", range(len(SELECTIONS)))
def test_partial_selection_crossing_chunks(small_budget, tmp_path, layout, selection):
    key = SELECTIONS[selection]
    path = tmp_path / "values.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("v", data=_values("<f8", (20, 40, 17)), **LAYOUTS[layout]((3, 6, 5)))
    with h5py.File(path, "r") as f:
        expected = f["v"][key]
        assert expected.nbytes > CALL_BUDGET
        for backend in ("rust", "auto"):
            values, record = _read(f["v"], key, backend=backend)
            _assert_identical(values, expected)
            _assert_chunked(record)


def test_blocks_follow_the_stored_chunk_grid(small_budget, tmp_path):
    path = tmp_path / "values.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("v", data=_values("<f4", (100, 10)), chunks=(6, 10))
        f.create_dataset("band", data=_values("<f4", (100, 10)), chunks=(50, 10))
    with h5py.File(path, "r") as f:
        # 1024-byte blocks hold 25 rows: 24 rows (four chunks) per block, on the grid.
        plan = list(fast_hdf._block_plan(f["v"], [(5, 100, 1), (0, 10, 1)], BLOCK_BYTES))
        starts = [src[0][0] for src, _ in plan]
        assert starts[0] == 5 and all(start % 24 == 0 for start in starts[1:])
        assert all(src[0][1] - src[0][0] <= 24 for src, _ in plan)
        # A 2000-byte chunk band exceeds the block but fits the call budget: whole bands.
        plan = list(fast_hdf._block_plan(f["band"], None, BLOCK_BYTES))
        assert [src[0] for src, _ in plan] == [(0, 50, 1), (50, 100, 1)]


def test_fill_values_for_unallocated_chunks(small_budget, tmp_path):
    path = tmp_path / "fill.h5"
    with h5py.File(path, "w") as f:
        ints = f.create_dataset("ints", shape=(48, 40), dtype="<i4", chunks=(8, 8), fillvalue=-7)
        ints[0:24] = np.arange(24 * 40, dtype="<i4").reshape(24, 40)
        ints[30, 33] = 5  # one more stored chunk among fill-only ones
        nan = f.create_dataset("nan", shape=(48, 40), dtype="<f8", chunks=(8, 8),
                               fillvalue=np.nan, compression="gzip")
        nan[8:48] = 1.5
    with h5py.File(path, "r") as f:
        for name in ("ints", "nan"):
            expected = f[name][()]
            assert f[name].id.get_num_chunks() < 30
            for backend in ("rust", "auto"):
                values, record = _read(f[name], backend=backend)
                _assert_identical(values, expected)
                _assert_chunked(record)


def test_big_endian_keeps_the_existing_byte_order_contract(small_budget, tmp_path):
    # The engine decodes native byte order only, at any size: auto serves the
    # exact h5py array (big-endian dtype) and required mode refuses.
    path = tmp_path / "be.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("v", data=_values("<f8", (40, 57)).astype(">f8"), chunks=(5, 57))
    with h5py.File(path, "r") as f:
        expected = f["v"][()]
        assert expected.dtype.str == ">f8"
        values, record = _read(f["v"], backend="auto")
        _assert_identical(values, expected)
        assert record["backend"] == "h5py-fallback"
        with pytest.raises(fast_hdf.FastHdfError, match="byte order"):
            fast_hdf.read_dataset(f["v"], backend="rust")


def test_batch_splits_at_the_call_budget(small_budget, tmp_path, monkeypatch):
    path = tmp_path / "batch.h5"
    arrays = {"a": _values("<f4", (500,), 1), "b": _values("<i4", (600,), 2),
              "big": _values("<f8", (30, 40), 3), "c": _values("<u8", (10,), 4)}
    with h5py.File(path, "w") as f:
        for name, data in arrays.items():
            f.create_dataset(name, data=data, chunks=True if data.size > 100 else None)
    chunked = []
    original = fast_hdf._read_chunked
    monkeypatch.setattr(fast_hdf, "_read_chunked",
                        lambda session, ds, *a: chunked.append(ds.name) or original(session, ds, *a))
    for backend in ("rust", "auto"):
        chunked.clear()
        result = fast_hdf.read_datasets(path, list(arrays), backend=backend)
        assert chunked == ["/big"]
        for name, data in arrays.items():
            _assert_identical(result[name], data)


def test_typed_stored_family_above_budget_uses_chunked_generic(native, monkeypatch):
    path = FIXTURES / "wave3" / "mesh-steady.h5"
    name = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles/2D Flow Areas/A/Flow"
    fast_hdf.close_sessions()
    with h5py.File(path, "r") as f:
        with fast_hdf.trace_reads() as records:
            fast_hdf.read_typed(f[name], backend="rust")
        assert records[-1]["route"] == "stored_family"
        monkeypatch.setattr(fast_hdf, "_NATIVE_CALL_BUDGET", 16)
        monkeypatch.setattr(fast_hdf, "_CHUNKED_BLOCK_BYTES", 8)
        with fast_hdf.trace_reads() as records:
            values = fast_hdf.read_typed(f[name], backend="rust")
        _assert_identical(values, f[name][()])
        assert records[0]["backend"] == "diagnostic"
        _assert_chunked(records[-1])
    fast_hdf.close_sessions()


def test_output_allocation_failure_is_a_python_error(small_budget, tmp_path, monkeypatch):
    path = tmp_path / "values.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("v", data=_values("<f4", (3000,)), chunks=(256,))
    original, armed = np.empty, [True]

    def empty(shape, *args, **kwargs):
        # Fail only the chunked output allocation, not h5py's own fallback read.
        if armed[0] and tuple(np.atleast_1d(shape)) == (3000,):
            armed[0] = False
            raise MemoryError("simulated allocation failure")
        return original(shape, *args, **kwargs)

    monkeypatch.setattr(fast_hdf.np, "empty", empty)
    with h5py.File(path, "r") as f:
        with pytest.raises(fast_hdf.FastHdfError, match="simulated allocation failure"):
            fast_hdf.read_dataset(f["v"], backend="rust")
        armed[0] = True
        # Auto mode turns the refusal into the h5py outcome.
        values, record = _read(f["v"], backend="auto")
        assert armed == [False] and record["backend"] == "h5py-fallback"
        monkeypatch.setattr(fast_hdf.np, "empty", original)
        _assert_identical(values, f["v"][()])


# ------------------------------------------------------------ implausible sizes
def test_declared_huge_datasets_are_refused_before_allocation(native, tmp_path, monkeypatch):
    # Real budgets. 2**50 bytes (1 PiB) declared in a file of about 2 KB.
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    path = tmp_path / "huge.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("chunked", shape=(2 ** 25, 2 ** 22), dtype="<f8", chunks=(256, 4096),
                         compression="gzip")
        f.create_dataset("contiguous", shape=(2 ** 47,), dtype="<f8")
    assert path.stat().st_size < 16384
    fast_hdf.close_sessions()
    allocations, original = [], np.empty
    monkeypatch.setattr(fast_hdf.np, "empty",
                        lambda shape, *a, **k: allocations.append(shape) or original(shape, *a, **k))
    with h5py.File(path, "r") as f:
        for name, reason in (("chunked", "have no stored chunks"), ("contiguous", "not allocated")):
            with pytest.raises(fast_hdf.FastHdfError, match=f"implausible declared size: .*{reason}"):
                fast_hdf.read_dataset(f[name], backend="rust")
            with pytest.raises(fast_hdf.FastHdfError, match="implausible declared size"):
                fast_hdf.read_datasets(path, [f[name].name], backend="rust")
            assert allocations == []
            # Auto returns h5py's own outcome: here NumPy cannot allocate 1 PiB.
            with fast_hdf.trace_reads() as records, pytest.raises(MemoryError):
                fast_hdf.read_dataset(f[name], backend="auto")
            assert records[-1]["backend"] == "h5py-fallback"
            allocations.clear()
        # A small natively servable selection of the same dataset still works.
        values = fast_hdf.read_dataset(f["chunked"], (slice(0, 2), slice(0, 3)), backend="rust")
        assert values.shape == (2, 3) and not values.any()
    fast_hdf.close_sessions()


def test_fill_only_beyond_budget_falls_back_in_auto(small_budget, tmp_path):
    path = tmp_path / "sparse.h5"
    with h5py.File(path, "w") as f:
        sparse = f.create_dataset("v", shape=(64, 64), dtype="<f4", chunks=(8, 8), fillvalue=3.0)
        sparse[0, 0] = 1.0
        f.create_dataset("unallocated", shape=(64, 64), dtype="<i4", fillvalue=9)
    with h5py.File(path, "r") as f:
        for name in ("v", "unallocated"):
            expected = f[name][()]
            values, record = _read(f[name], backend="auto")
            _assert_identical(values, expected)
            assert record["backend"] == "h5py-fallback"
            with pytest.raises(fast_hdf.FastHdfError, match="implausible declared size"):
                fast_hdf.read_dataset(f[name], backend="rust")


class _Plist:
    def __init__(self, layout, filters):
        self.layout, self.filters = layout, filters

    def get_layout(self):
        return self.layout

    def get_nfilters(self):
        return len(self.filters)

    def get_filter(self, index):
        return (self.filters[index], 0, (), b"")


def _stub(path, *, shape, chunks=None, layout=h5py.h5d.CHUNKED, filters=(), offset=None,
          stored=0, allocated=0):
    dsid = SimpleNamespace(get_create_plist=lambda: _Plist(layout, list(filters)),
                           get_offset=lambda: offset, get_storage_size=lambda: stored,
                           get_num_chunks=lambda: allocated)
    return SimpleNamespace(dtype=np.dtype("<f4"), shape=shape, chunks=chunks, id=dsid,
                           file=SimpleNamespace(filename=str(path)))


@pytest.mark.parametrize("fields,reason", [
    ({"layout": h5py.h5d.CONTIGUOUS, "offset": 6500}, "contiguous bytes at offset 6500"),
    ({"layout": h5py.h5d.CONTIGUOUS}, "not allocated"),
    ({"chunks": (10,), "stored": 20000, "allocated": 1}, "stored bytes in a"),
    ({"chunks": (10,), "stored": 400, "allocated": 100}, "would decode to 4000 bytes"),
    ({"chunks": (10,), "stored": 4, "allocated": 100,
      "filters": [h5py.h5z.FILTER_SHUFFLE, h5py.h5z.FILTER_DEFLATE]}, None),
    ({"chunks": (10,), "stored": 3, "allocated": 100,
      "filters": [h5py.h5z.FILTER_DEFLATE]}, "would decode to 4000 bytes from 3 stored"),
    ({"chunks": (100,), "stored": 0, "allocated": 0}, "have no stored chunks"),
    ({"chunks": (10,), "stored": 400, "allocated": 100,
      "filters": [h5py.h5z.FILTER_SCALEOFFSET]}, "no bounded expansion"),
    ({"chunks": (10,), "stored": 400, "allocated": 100, "filters": [4]}, "no bounded expansion"),
    ({"chunks": (100,), "stored": 400, "allocated": 1}, None),
    ({"chunks": (100,), "stored": 4000, "allocated": 10}, None),
])
def test_plausibility_policy(tmp_path, monkeypatch, fields, reason):
    path = tmp_path / "file.bin"
    path.write_bytes(b"\0" * 10000)
    monkeypatch.setattr(fast_hdf, "_NATIVE_CALL_BUDGET", 3600)
    # 1000 float32 values: 4000 declared bytes in a 10000 byte file.
    found = fast_hdf._implausible(_stub(path, shape=(1000,), **fields))
    if reason is None:
        assert found is None
    else:
        assert reason in found
    assert fast_hdf._implausible(
        _stub(path, shape=(1000,), layout=h5py.h5d.CONTIGUOUS, offset=4000)) is None


def test_engine_budget_matches_the_bridge_constant(native, tmp_path):
    path = tmp_path / "huge.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("v", shape=(2 ** 30,), dtype="<f4", chunks=(2 ** 20,))
    with native.HdfSession(path) as session:
        with pytest.raises(native.UnsupportedError) as info:
            session.read_numeric("/v")
    assert info.value.engine_code == "resource_limit"
    assert f"exceeds the {fast_hdf._NATIVE_CALL_BUDGET} byte read budget" in str(info.value)


def test_patched_contiguous_extent_never_aborts(native, tmp_path):
    # The original P1 shape: a contiguous dataset whose dataspace (and layout
    # size) declare 16 GiB in a 1 MB file. HDF5 itself refuses to open it, so
    # it never reaches fast_hdf; the engine refuses it without allocating.
    count = 123457
    path = tmp_path / "patched.h5"
    with h5py.File(path, "w", libver="earliest") as f:
        f.create_dataset("v", data=np.arange(count, dtype="<f8"))
    raw = bytearray(path.read_bytes())
    for old, new in ((count, 2 ** 31), (count * 8, 2 ** 34)):
        needle = struct.pack("<Q", old)
        hits = [i for i in range(len(raw) - 7) if raw[i:i + 8] == needle]
        assert hits
        for i in hits:
            raw[i:i + 8] = struct.pack("<Q", new)
    path.write_bytes(bytes(raw))
    with pytest.raises((OSError, KeyError)):
        with h5py.File(path, "r") as f:
            f["v"]
    with native.HdfSession(path) as session:
        with pytest.raises(native.UnsupportedError, match="read budget"):
            session.read_numeric("/v")
        with pytest.raises(native.CorruptDataError):
            session.read_numeric("/v", [(0, 2 ** 28, 1)])
        np.testing.assert_array_equal(session.read_numeric("/v", [(0, 4, 1)]), np.arange(4.0))
