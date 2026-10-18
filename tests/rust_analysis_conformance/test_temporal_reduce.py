"""Synthetic edge, layout and corruption coverage for temporal reductions.

Real multi-plan parity lives in ``tests/rust_results_public``; these cases
supplement it with layouts and values HEC-RAS fixtures do not contain.
"""
import shutil

import h5py
import numpy as np
import pytest

from ras_commander import fast_results
from ras_commander.fast_hdf import FastHdfError
from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh

from .oracle import assert_matches, oracle

NAN, INF = np.float32(np.nan), np.float32(np.inf)


def adversarial(times=23, elements=9, seed=7):
    rng = np.random.default_rng(seed)
    v = rng.integers(-3, 4, size=(times, elements)).astype(np.float32)  # many ties
    v[rng.random(v.shape) < 0.15] = NAN
    v[0, 1], v[5, 1], v[9, 2] = INF, -INF, INF
    v[:, 3] = NAN  # all missing
    v[:, 4] = -7.5  # valid negative constant: tie keeps first row
    v[4, 5] = v[17, 5] = 50.0  # tie across a block boundary
    return v


def write(path, data, **kwargs):
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("series", data=data, **kwargs)
    return path


def reduce_file(path, backend, **kwargs):
    with h5py.File(path, "r") as hdf:
        return fast_results.temporal_reduce(hdf["series"], backend=backend, **kwargs)


LAYOUTS = {
    "contiguous": {},
    "chunked_gzip": dict(chunks=(4, 9), compression="gzip"),
    "chunked_shuffle": dict(chunks=(5, 9), compression="gzip", shuffle=True),
    "partial_column_chunks": dict(chunks=(3, 4), compression="gzip"),
    "single_row_chunks": dict(chunks=(1, 9), compression="gzip", compression_opts=9),
}


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
@pytest.mark.parametrize("block_bytes", [1, 37, 64 << 20])
@pytest.mark.parametrize("threshold", [None, 0.0, 2.0])
def test_layouts_match_oracle_and_python(tmp_path, native_calls, forbid_python,
                                         layout, block_bytes, threshold):
    values = adversarial()
    path = write(tmp_path / "s.h5", values, **LAYOUTS[layout])
    native = reduce_file(path, "rust", threshold=threshold, max_block_bytes=block_bytes)
    assert native.backend == "rust" and len(native_calls) == 1
    expected = oracle(values, threshold=threshold)
    assert_matches(native, expected)
    assert native.peak_index[5] == 4 and native.peak_index[4] == 0
    assert np.isnan(native.maximum[3]) and native.peak_index[3] == -1


@pytest.mark.parametrize("threshold", [None, 0.5])
def test_offset_derivation_and_python_reference(tmp_path, native, threshold):
    values = adversarial() + np.float32(10.0)
    offset = np.linspace(8.0, 13.0, values.shape[1]).astype(np.float32)
    offset[6] = NAN  # missing minimum elevation => element is all-missing
    path = write(tmp_path / "s.h5", values, chunks=(4, 9), compression="gzip")
    expected = oracle(values, offset, threshold)
    for backend in ("rust", "python"):
        result = reduce_file(path, backend, offset=offset, threshold=threshold)
        assert result.backend == backend
        assert_matches(result, expected)
    assert (expected["maximum"][np.isfinite(expected["maximum"])] >= 0).all()


def test_legacy_public_route_matches_native(tmp_path, native, native_calls, monkeypatch):
    values = adversarial()
    offset = np.full(values.shape[1], 1.0, dtype=np.float32)
    path = write(tmp_path / "s.h5", values, chunks=(4, 9), compression="gzip")
    with h5py.File(path, "r") as hdf:
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
        legacy = HdfResultsMesh._get_mesh_temporal_maximum(hdf["series"], offset)
        assert not native_calls
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
        accelerated = HdfResultsMesh._get_mesh_temporal_maximum(hdf["series"], offset)
        assert len(native_calls) == 1
    np.testing.assert_array_equal(legacy, accelerated)
    assert legacy.dtype == accelerated.dtype == np.float32


def test_parallel_slabs_and_threads_are_deterministic(tmp_path, native):
    rng = np.random.default_rng(3)
    values = rng.normal(size=(17, 10_000)).astype(np.float32)
    values[rng.random(values.shape) < 0.05] = NAN
    path = write(tmp_path / "s.h5", values, chunks=(3, 2500), compression="gzip")
    one = reduce_file(path, "rust", threads=1, threshold=0.25)
    many = reduce_file(path, "rust", threads=4, threshold=0.25, max_block_bytes=100_000)
    assert_matches(one, oracle(values, threshold=0.25))
    assert_matches(many, oracle(values, threshold=0.25))
    assert one.maximum.tobytes() == many.maximum.tobytes()


@pytest.mark.parametrize("shape", [(0, 4), (5, 0), (0, 0)])
def test_empty_series(tmp_path, native, shape):
    path = write(tmp_path / "s.h5", np.zeros(shape, dtype=np.float32), maxshape=(None, None),
                 chunks=(2, 2))
    for backend in ("rust", "python"):
        result = reduce_file(path, backend, threshold=1.0)
        assert result.rows == shape[0]
        assert_matches(result, oracle(np.zeros(shape, dtype=np.float32), threshold=1.0))


def test_typed_large_values_and_float64_narrowing(tmp_path, native):
    f32 = np.finfo(np.float32)
    stored = np.array(
        [[16777217.0, 1e39, 0.1, float(f32.max), float(f32.smallest_subnormal)],
         [16777216.0, -1e39, 0.2, -float(f32.max), 0.0],
         [1.0, 3.0, np.nextafter(0.2, 1.0), 1.0, -0.0]],
        dtype=np.float64,
    )
    path = write(tmp_path / "s.h5", stored, chunks=(2, 5), compression="gzip")
    native_result = reduce_file(path, "rust")
    expected = oracle(stored)
    assert_matches(native_result, expected)
    # Exact float32 bits, including rounding of float64 storage and subnormals.
    assert native_result.maximum.tobytes() == expected["maximum"].tobytes()
    assert native_result.maximum[0] == np.float32(16777216.0)
    # +/-1e39 overflow to +/-inf and are missing; the finite 3.0 remains.
    assert native_result.maximum[1] == 3.0 and native_result.finite_count[1] == 1
    assert native_result.maximum[3] == f32.max


def test_integer_series_uses_python_or_fails_when_required(tmp_path, native, native_calls):
    values = np.array([[1, 2**24 + 1], [3, -5]], dtype=np.int32)
    path = write(tmp_path / "s.h5", values)
    result = reduce_file(path, "auto")
    assert result.backend == "python" and not native_calls
    assert_matches(result, oracle(values))
    with pytest.raises(FastHdfError):
        reduce_file(path, "rust")
    assert not native_calls


def test_unsupported_filter_falls_back_only_in_auto(tmp_path, native, native_calls):
    values = adversarial()
    path = write(tmp_path / "s.h5", values, chunks=(4, 9), compression="lzf")
    auto = reduce_file(path, "auto")
    assert auto.backend == "python" and len(native_calls) == 1
    assert_matches(auto, oracle(values))
    with pytest.raises(FastHdfError, match="unsupported filter"):
        reduce_file(path, "rust")


def test_nonnative_byte_order_falls_back_only_in_auto(tmp_path, native, native_calls):
    values = adversarial().astype(">f4")
    path = write(tmp_path / "s.h5", values, chunks=(4, 9))
    auto = reduce_file(path, "auto")
    assert auto.backend == "python" and len(native_calls) == 1  # native refused it
    assert_matches(auto, oracle(values))
    with pytest.raises(FastHdfError, match="Native reduction failed"):
        reduce_file(path, "rust")


@pytest.mark.parametrize("backend", ["auto", "rust"])
def test_corrupt_chunks_raise_instead_of_empty_result(tmp_path, native, backend):
    path = write(tmp_path / "s.h5", adversarial(200, 400), chunks=(10, 400), compression="gzip")
    damaged = tmp_path / "damaged.h5"
    shutil.copyfile(path, damaged)
    with h5py.File(path, "r") as hdf:
        dsid = hdf["series"].id
        chunks = [dsid.get_chunk_info(i) for i in range(dsid.get_num_chunks())]
    with open(damaged, "r+b") as handle:  # keep metadata, destroy one late chunk
        info = chunks[-3]
        handle.seek(info.byte_offset)
        handle.write(b"\xff" * info.size)
    with h5py.File(damaged, "r") as hdf:
        with pytest.raises(FastHdfError):
            fast_results.temporal_reduce(hdf["series"], backend=backend)


def test_invalid_requests(tmp_path, native):
    with h5py.File(tmp_path / "s.h5", "w") as hdf:
        hdf["one_d"] = np.zeros(3, dtype=np.float32)
        hdf["three_d"] = np.zeros((2, 2, 2), dtype=np.float32)
        hdf["series"] = np.zeros((2, 3), dtype=np.float32)
    with h5py.File(tmp_path / "s.h5", "r") as hdf:
        for name in ("one_d", "three_d"):
            with pytest.raises(ValueError):
                fast_results.temporal_reduce(hdf[name], backend="rust")
        series = hdf["series"]
        with pytest.raises(ValueError, match="offset shape"):
            fast_results.temporal_reduce(series, np.zeros(2), backend="rust")
        for bad in (np.nan, np.inf, 1e39):
            with pytest.raises(ValueError):
                fast_results.temporal_reduce(series, threshold=bad, backend="rust")
        with pytest.raises(ValueError):
            fast_results.temporal_reduce(series, backend="rust", max_block_bytes=0)
        with pytest.raises(FastHdfError):
            fast_results.temporal_reduce(np.zeros((2, 3)), backend="rust")
