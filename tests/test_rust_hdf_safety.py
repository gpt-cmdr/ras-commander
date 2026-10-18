"""Fail-closed safety of the native numeric HDF reader.

Native reads must equal h5py by dtype, shape and bytes, or raise
``UnsupportedError``; they must never return differently decoded values.
Committed type fixtures live in tests/fixtures/rust_hdf_types/ (see
make_fixtures.py and manifest.json). Real HEC-RAS files are optional: set
``RAS_HDF_SAFETY_REAL`` to an ``os.pathsep``-separated list of .hdf files, or
rely on the default candidate paths; missing files are explicit skips.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import fast_hdf

native = pytest.importorskip("ras_commander_fast_hdf")

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rust_hdf_types"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
FILES = sorted(MANIFEST["files"])
CASES = [(name, dataset, verdict) for name in FILES
         for dataset, verdict in MANIFEST["files"][name]["datasets"].items()]


def fixture(name: str) -> str:
    return str(FIXTURES / name)


def expected(path: str, dataset: str) -> np.ndarray:
    with h5py.File(path, "r") as f:
        return np.asarray(f[dataset][()])


def assert_exact(actual, reference: np.ndarray) -> None:
    actual = np.asarray(actual)
    assert actual.dtype == reference.dtype
    assert actual.shape == reference.shape
    assert actual.tobytes() == reference.tobytes()


def is_unsupported(exc: BaseException) -> bool:
    return isinstance(exc, native.UnsupportedError)


@pytest.mark.parametrize("name", FILES)
def test_fixture_bytes_match_manifest(name):
    digest = hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
    assert digest == MANIFEST["files"][name]["sha256"]


@pytest.mark.parametrize("name,dataset,verdict", CASES, ids=[f"{n}:{d}" for n, d, _ in CASES])
@pytest.mark.parametrize("parallel", [True, False], ids=["parallel", "serial"])
def test_native_read_is_exact_or_rejected(name, dataset, verdict, parallel):
    path = fixture(name)
    capability = None
    try:
        # The pinned parser can fail to open some datasets at all; that must
        # also surface as UnsupportedError rather than a generic error.
        capability = native.numeric_capability(path, dataset)
        assert capability["schema_version"] == 1
        actual = native.read_numeric(path, dataset, threads=2, parallel=parallel)
    except Exception as exc:  # noqa: BLE001 - classification is the assertion
        assert is_unsupported(exc), f"{dataset}: {type(exc).__name__}: {exc}"
        assert verdict in {"reject", "exact_or_reject"}, f"{dataset} unexpectedly rejected: {exc}"
        if capability is not None:
            assert capability["supported"] is False and capability["reason"]
        return
    assert verdict in {"exact", "exact_or_reject"}, f"{dataset} decoded instead of rejected"
    # No reference decoder is needed when native must reject a type; older
    # h5py may itself reject newer encodings before native can be tested.
    reference = expected(path, dataset)
    assert_exact(actual, reference)
    assert capability["supported"] is True and capability["reason"] is None
    assert np.dtype(capability["numpy_dtype"]) == reference.dtype
    assert list(capability["shape"]) == list(reference.shape)


def test_capability_reports_discarded_encoding_fields():
    path = fixture("numeric_types_v1.h5")
    cap = native.numeric_capability(path, "encoding/i32_precision24_offset4")
    assert (cap["type_class"], cap["bit_offset"], cap["bit_precision"]) == ("integer", 4, 24)
    assert not cap["supported"] and "precision" in cap["reason"]
    cap = native.numeric_capability(path, "encoding/f32_exponent_bias100")
    assert cap["float_layout"]["exponent_bias"] == 100 and not cap["supported"]
    cap = native.numeric_capability(path, "encoding/f64_vax_order")
    assert cap["float_layout"]["vax_order"] is True and "VAX" in cap["reason"]
    cap = native.numeric_capability(path, "float/f8_special")
    assert cap["float_layout"] == {
        "sign_location": 63, "exponent_location": 52, "exponent_size": 11,
        "mantissa_location": 0, "mantissa_size": 52, "exponent_bias": 1023,
        "mantissa_normalization": 2, "vax_order": False,
    }
    assert cap["supported"] and cap["numpy_dtype"] == "<f8"


def test_uint64_above_2_53_is_preserved():
    path = fixture("numeric_types_v2.h5")
    values = native.read_numeric(path, "int/u64_bounds")
    assert values.dtype == np.uint64
    assert [int(v) for v in values[3:6]] == [2**53, 2**53 + 1, 2**63]
    assert int(values[-1]) == 2**64 - 1 and int(values[-2]) == 2**64 - 2


SELECTIONS = [
    ("shape/rank3_i2", [(0, 4, 1), (0, 5, 1), (0, 6, 1)]),
    ("shape/rank3_i2", [(1, 4, 2), (0, 5, 3), (5, 6, 1)]),
    ("shape/rank3_i2", [(2, 2, 1), (0, 5, 1), (0, 6, 1)]),  # zero-length axis
    ("shape/chunked_2d_f4", [(3, 37, 7), (4, 23, 5)]),       # crosses chunk edges
    ("shape/chunked_2d_f4", [(36, 37, 1), (22, 23, 1)]),
    ("shape/empty_2d", [(0, 3, 1), (0, 0, 1)]),
    ("fill/chunked_partial_i4", [(2, 10, 3), (1, 9, 2)]),    # written + unallocated
    ("filter/gzip_shuffle_f8", [(15, 33, 4), (0, 50, 9)]),
    ("int/u64_bounds", [(3, 8, 2)]),
    ("shape/scalar_f8", []),
]


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("dataset,selection", SELECTIONS,
                         ids=[f"{d}{s}" for d, s in SELECTIONS])
def test_selection_matches_h5py(name, dataset, selection):
    path = fixture(name)
    with h5py.File(path, "r") as f:
        reference = np.asarray(f[dataset][tuple(slice(*s) for s in selection)])
    assert_exact(native.read_numeric(path, dataset, selection=selection, threads=2), reference)


@pytest.mark.parametrize("selection", [
    [(0, 4, 1)],                                 # rank too small
    [(0, 4, 1), (0, 5, 1), (0, 6, 1), (0, 1, 1)],  # rank too large
    [(0, 5, 1), (0, 5, 1), (0, 6, 1)],           # end beyond extent
    [(0, 4, 0), (0, 5, 1), (0, 6, 1)],           # zero step
    [(3, 2, 1), (0, 5, 1), (0, 6, 1)],           # start after end
])
def test_invalid_selection_raises_value_error(selection):
    with pytest.raises(ValueError) as info:
        native.read_numeric(fixture("numeric_types_v1.h5"), "shape/rank3_i2", selection=selection)
    assert not is_unsupported(info.value)


def test_missing_paths_raise_key_error():
    path = fixture("numeric_types_v1.h5")
    for dataset in ("no/such/dataset", "int/missing"):
        with pytest.raises(KeyError):
            native.read_numeric(path, dataset)
        with pytest.raises(KeyError):
            native.numeric_capability(path, dataset)


def test_batch_fails_closed_on_one_unsupported_dataset():
    path = fixture("numeric_types_v1.h5")
    ok = ["int/u64_bounds", "float/f8_special"]
    batch = native.read_numeric_batch(path, ok, threads=2)
    for dataset in ok:
        assert_exact(batch[dataset], expected(path, dataset))
    with pytest.raises(native.UnsupportedError):
        native.read_numeric_batch(path, ok + ["encoding/i32_precision24_offset4"])


@pytest.mark.parametrize("dataset", ["encoding/i32_precision24_offset4", "endian/be_f8",
                                     "encoding/f32_exponent_bias100"])
def test_adapter_required_raises_and_auto_uses_h5py(dataset):
    path = fixture("numeric_types_v2.h5")
    with h5py.File(path, "r") as f:
        ds = f[dataset]
        with pytest.raises(fast_hdf.FastHdfError):
            fast_hdf.read_dataset(ds, backend="rust")
        assert_exact(fast_hdf.read_dataset(ds, backend="auto"), np.asarray(ds[()]))


def test_adapter_required_env_reads_supported_dataset_natively(monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    path = fixture("numeric_types_v1.h5")
    with h5py.File(path, "r") as f:
        ds = f["fill/chunked_partial_i4"]
        assert_exact(fast_hdf.read_dataset(ds, np.s_[1:9, ::3]), np.asarray(ds[1:9, ::3]))
        with pytest.raises(fast_hdf.FastHdfError):
            fast_hdf.read_dataset(f["encoding/f64_vax_order"])


def _malformed(tmp_path: Path, filename: str) -> dict[str, Path]:
    good = (FIXTURES / filename).read_bytes()
    with h5py.File(FIXTURES / filename, "r") as f:
        gzip_offset = f["filter/gzip_shuffle_f8"].id.get_chunk_info(0).byte_offset
        fletcher_offset = f["filter/fletcher32_i8"].id.get_chunk_info(0).byte_offset
    cases = {
        "empty": b"",
        "not_hdf5": b"definitely not an HDF5 file" * 40,
        "truncated_superblock": good[:40],
        "truncated_half": good[: len(good) // 2],
    }
    for label, offset in (("corrupt_gzip_chunk", gzip_offset), ("corrupt_fletcher32", fletcher_offset)):
        damaged = bytearray(good)
        damaged[offset + 2: offset + 18] = bytes(16)
        cases[label] = bytes(damaged)
    out = {}
    for label, data in cases.items():
        out[label] = tmp_path / f"{label}.h5"
        out[label].write_bytes(data)
    return out


@pytest.mark.parametrize("label", ["empty", "not_hdf5", "truncated_superblock",
                                   "truncated_half", "corrupt_gzip_chunk", "corrupt_fletcher32"])
@pytest.mark.parametrize("filename", ["numeric_types_v1.h5", "numeric_types_v2.h5"])
def test_malformed_input_raises_without_returning_data(tmp_path, label, filename):
    path = str(_malformed(tmp_path, filename)[label])
    dataset = {"corrupt_fletcher32": "filter/fletcher32_i8"}.get(label, "filter/gzip_shuffle_f8")
    with pytest.raises((OSError, ValueError, KeyError)) as info:
        native.read_numeric(path, dataset)
    # Corruption is never reported as a benign capability gap.
    assert not is_unsupported(info.value), info.value


# ---------------------------------------------------------------------------
# Real HEC-RAS files: every numeric dataset must be supported and exact.
# ---------------------------------------------------------------------------

_SCRATCH = Path(os.environ.get("RAS_HDF_SAFETY_WORKING",
                              Path(__file__).resolve().parents[1] / "working"))
_H = Path("H:/CLB-Repos/ras-commander")
DEFAULT_REAL = [
    _SCRATCH / "real_src" / "507" / "Sacramento.g01.hdf",
    _SCRATCH / "real_src" / "507" / "WaterQualityExamp.g01.hdf",
    _H / "example_projects" / "BaldEagleCrkMulti2D_extent_demo" / "BaldEagleDamBrk.g12.hdf",
    # Preexisting computed 5.0.7 plan result (not executed by this test slice).
    Path("C:/Users/mallory/scratch/rust-hdf-task-workspaces/review-fluvial/qualification")
    / "JUL2020_D100RAS.p04.hdf",
    _SCRATCH / "real_src" / "600" / "WaterQualityExamp.p01.hdf",
    _SCRATCH / "real_src" / "600" / "Chippewa_2D.g01.hdf",
    _SCRATCH / "rasexamples" / "Muncie" / "Muncie.g02.hdf",
    _H / "example_projects" / "BaldEagleCrkMulti2D_213" / "BaldEagleDamBrk.p03.hdf",
    _H / "example_projects" / "Muncie_conn_test" / "Muncie.p01.hdf",
    _H / "example_projects" / "Weise_2D" / "Weise.g08.hdf",
    _H / "working" / "qualarea-BaldEagleDamBrk.g09.hdf",
    _SCRATCH / "plan_runs" / "70_run" / "BaldEagle.p01.hdf",
]
_env = os.environ.get("RAS_HDF_SAFETY_REAL")
REAL = [Path(p) for p in _env.split(os.pathsep) if p] if _env else DEFAULT_REAL


def stored_version(path: Path) -> str:
    with h5py.File(path, "r") as f:
        value = f.attrs.get("File Version")
    return value.decode() if isinstance(value, bytes) else str(value)


@pytest.mark.parametrize("path", REAL, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_real_hecras_numeric_datasets_supported_and_exact(path, record_property):
    if not path.is_file():
        pytest.skip(f"Real fixture unavailable: {path}")
    version = stored_version(path)
    record_property("stored_version", version)
    record_property("sha256", hashlib.sha256(path.read_bytes()).hexdigest())
    names = []
    with h5py.File(path, "r") as f:
        f.visititems(lambda n, o: names.append(n) if isinstance(o, h5py.Dataset)
                     and o.dtype.kind in "iuf" and o.dtype.fields is None
                     and o.shape is not None else None)
        assert names, f"No numeric datasets in {path}"
        for name in names:
            cap = native.numeric_capability(str(path), name)
            assert cap["supported"], f"{path}:{name} rejected: {cap['reason']}"
            assert_exact(native.read_numeric(str(path), name, threads=2), np.asarray(f[name][()]))
    record_property("numeric_datasets", len(names))


@pytest.mark.parametrize("major", ["5", "6", "7"])
def test_real_coverage_includes_stored_major_version(major):
    found = [p for p in REAL if p.is_file()
             and re.match(rf"HEC-RAS {major}\.", stored_version(p))]
    if not found:
        pytest.skip(f"No available real fixture stores HEC-RAS {major}.x (coverage unavailable)")
