"""Regenerate the small HDF type fixtures used by tests/test_rust_hdf_safety.py.

Run from the repository root:  python tests/fixtures/rust_hdf_types/make_fixtures.py

Two files hold identical content: ``numeric_types_v1.h5`` uses the earliest
library format (version 1 object headers) and ``numeric_types_v2.h5`` the
HDF5 1.10–1.12 bounds (version 2 ``OHDR`` headers). Do not use ``latest``:
with an HDF5 2.0 writer it introduces layouts/types older h5py cannot open.
``manifest.json`` records SHA256 hashes and
the expected native verdict for every dataset; the test checks both.
Regeneration is not byte-reproducible (HDF5 stores object timestamps), so the
manifest pins the committed bytes rather than the generator output.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
from h5py import h5d, h5s, h5t

HERE = Path(__file__).resolve().parent

# Expected verdicts: "exact" must match h5py byte-for-byte; "reject" must raise
# UnsupportedError from the native reader. "exact_or_reject" depends on the
# pinned hdf5-reader: it rejects committed-datatype references (shared message
# v2 type 2) until the dependency patch in the hdf-safety OUTPUT is applied.
EXACT, REJECT, EXACT_OR_REJECT = "exact", "reject", "exact_or_reject"


def _custom(f, name, tid, values, memtype):
    """Write a dataset whose file datatype is a hand-built HDF5 type."""
    group, leaf = name.rsplit("/", 1)
    space = h5s.create_simple(values.shape)
    dset = h5d.create(f.require_group(group).id, leaf.encode(), tid, space)
    dset.write(h5s.ALL, h5s.ALL, values, mtype=memtype)


def build(path: Path, libver: str | tuple[str, str]) -> dict[str, str]:
    expected: dict[str, str] = {}
    with h5py.File(path, "w", libver=libver, track_order=False) as f:
        def add(name, data, verdict, **kwargs):
            f.create_dataset(name, data=data, track_times=False, **kwargs)
            expected[name] = verdict

        # Integer precision boundaries, including uint64 values above 2**53.
        add("int/u64_bounds", np.array(
            [0, 1, 2**53 - 1, 2**53, 2**53 + 1, 2**63, 2**64 - 2, 2**64 - 1], dtype="<u8"), EXACT)
        add("int/i64_bounds", np.array(
            [-2**63, -2**53 - 1, -1, 0, 2**53 + 1, 2**63 - 1], dtype="<i8"), EXACT)
        for code in ("i1", "u1", "i2", "u2", "i4", "u4"):
            info = np.iinfo(code)
            add(f"int/{code}_bounds", np.array([info.min, 0, info.max], dtype="<" + code), EXACT)
        # Floating values whose bytes must survive: NaN payload, -0.0, inf, subnormal.
        f4 = np.array([0.0, -0.0, np.inf, -np.inf, 1.5, np.finfo("f4").tiny / 2], dtype="<f4")
        f8 = np.array([0.0, -0.0, np.inf, -np.inf, 1.5, np.finfo("f8").tiny / 2], dtype="<f8")
        f4 = np.append(f4, np.frombuffer(b"\x01\x00\xc0\x7f", "<f4"))
        f8 = np.append(f8, np.frombuffer(b"\x01\x00\x00\x00\x00\x00\xf8\x7f", "<f8"))
        add("float/f4_special", f4, EXACT)
        add("float/f8_special", f8, EXACT)

        # Non-native byte order: h5py converts; the native reader must refuse.
        for code in ("i2", "i4", "u8", "f4", "f8"):
            add(f"endian/be_{code}", np.arange(4, dtype=">" + code), REJECT)
        add("endian/be_i1", np.arange(4, dtype=">i1"), EXACT)  # single byte: order irrelevant

        # Encodings the pinned hdf5-reader parses but would misdecode.
        t = h5t.STD_I32LE.copy(); t.set_precision(24); t.set_offset(4)
        _custom(f, "encoding/i32_precision24_offset4", t,
                np.array([1, -1, 1000, -8388608], "i4"), h5t.NATIVE_INT32)
        t = h5t.STD_U16LE.copy(); t.set_precision(12)
        _custom(f, "encoding/u16_precision12", t, np.array([1, 4095, 7], "u2"), h5t.NATIVE_UINT16)
        t = h5t.STD_I16LE.copy(); t.set_precision(12)
        _custom(f, "encoding/i16_precision12_negative", t, np.array([-1, -2048, 5], "i2"),
                h5t.NATIVE_INT16)
        t = h5t.IEEE_F32LE.copy(); t.set_ebias(100)
        _custom(f, "encoding/f32_exponent_bias100", t, np.array([1.0, 2.5], "f4"), h5t.NATIVE_FLOAT)
        t = h5t.IEEE_F64LE.copy(); t.set_order(h5t.ORDER_VAX)
        _custom(f, "encoding/f64_vax_order", t, np.array([1.0, 2.5]), h5t.NATIVE_DOUBLE)
        for name in ("i32_precision24_offset4", "u16_precision12", "i16_precision12_negative",
                     "f32_exponent_bias100", "f64_vax_order"):
            expected[f"encoding/{name}"] = REJECT

        # Other classes and widths outside the numeric contract.
        add("class/f16", np.array([1.0, 2.0], dtype="<f2"), REJECT)
        add("class/enum_u1", np.array([0, 1], "u1"), REJECT,
            dtype=h5py.enum_dtype({"OFF": 0, "ON": 1}, basetype="u1"))
        add("class/compound", np.array([(1, 2.0)], dtype=[("a", "<i4"), ("b", "<f8")]), REJECT)
        add("class/fixed_string", np.array([b"abc", b"de"], dtype="S3"), REJECT)
        add("class/bool", np.array([True, False]), REJECT)

        # Committed (shared) datatype: probe must follow the named-type header.
        f["class/named_i4"] = np.dtype("<i4")
        add("class/uses_named_i4", np.arange(5, dtype="<i4"), EXACT_OR_REJECT,
            dtype=f["class/named_i4"])

        # Shapes and dataspaces.
        add("shape/empty_1d", np.zeros((0,), "<f8"), EXACT)
        add("shape/empty_2d", np.zeros((3, 0), "<i4"), EXACT)
        add("shape/scalar_f8", np.float64(3.25), EXACT)
        add("shape/rank3_i2", np.arange(4 * 5 * 6, dtype="<i2").reshape(4, 5, 6), EXACT)
        add("shape/chunked_2d_f4", np.arange(37 * 23, dtype="<f4").reshape(37, 23), EXACT,
            chunks=(8, 5))

        # Fill values: unallocated chunks/contiguous storage read as fill.
        d = f.create_dataset("fill/chunked_partial_i4", shape=(10, 10), dtype="<i4", chunks=(4, 4),
                             fillvalue=-7, track_times=False)
        d[0:4, 0:4] = 1
        expected["fill/chunked_partial_i4"] = EXACT
        f.create_dataset("fill/contiguous_unwritten_f8", shape=(6,), dtype="<f8", fillvalue=2.5,
                         track_times=False)
        expected["fill/contiguous_unwritten_f8"] = EXACT
        f.create_dataset("fill/chunked_unwritten_u8", shape=(5,), dtype="<u8", chunks=(2,),
                         fillvalue=2**64 - 1, track_times=False)
        expected["fill/chunked_unwritten_u8"] = EXACT

        # Filters that HEC-RAS files commonly use.
        data = np.arange(2000, dtype="<f8").reshape(40, 50) / 7
        add("filter/gzip_shuffle_f8", data, EXACT, chunks=(16, 16), compression="gzip",
            compression_opts=4, shuffle=True)
        add("filter/fletcher32_i8", np.arange(300, dtype="<i8"), EXACT, chunks=(64,),
            fletcher32=True)

        # Many attributes push the object header into continuation blocks.
        d = f.create_dataset("header/continued_u4", data=np.arange(9, dtype="<u4"),
                             track_times=False)
        for i in range(60):
            d.attrs[f"attribute_{i:02d}"] = np.full(8, i, dtype="<f8")
        expected["header/continued_u4"] = EXACT
    return expected


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = {
        "generator": "tests/fixtures/rust_hdf_types/make_fixtures.py",
        "h5py": h5py.__version__,
        "hdf5": h5py.version.hdf5_version,
        "files": {},
    }
    for name, libver in (("numeric_types_v1.h5", "earliest"),
                         ("numeric_types_v2.h5", ("v110", "v112"))):
        path = HERE / name
        expected = build(path, libver)
        manifest["files"][name] = {"libver": libver, "sha256": sha256(path),
                                   "datasets": dict(sorted(expected.items()))}
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
