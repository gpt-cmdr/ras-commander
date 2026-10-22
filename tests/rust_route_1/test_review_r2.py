"""Review-r2 P3 regressions (synthetic temporary files; no fixture gate).

- P3-A: the h5py guard classifies dtypes explicitly; only text and text-only
  compounds are metadata.
- P3-B: no Hdf* module imports FastHdfError without using it.
- P3-C: the private h5py selector is isolated in ``h5py_selection_shape`` with a
  fallback that leaves the selection to h5py.
- P3-D: ``reraise_required`` honours an explicit backend.
"""
import ast
from pathlib import Path

import h5py
import numpy as np
import pytest

from ._h5py_guard import classify

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("dtype,expected", [
    (np.dtype("f8"), "numeric"),
    (np.dtype("i4"), "numeric"),
    (np.dtype("?"), "numeric"),
    (np.dtype("c16"), "numeric"),
    (h5py.enum_dtype({"a": 0, "b": 1}, basetype="i1"), "numeric"),
    (h5py.vlen_dtype(np.dtype("i4")), "numeric"),
    (h5py.string_dtype("utf-8"), "string"),
    (np.dtype("S16"), "string"),
    (np.dtype("V8"), "other"),
    (h5py.ref_dtype, "other"),
    (np.dtype([("River", "S16"), ("Reach", "S16")]), "compound-text"),
    (np.dtype([("Name", "S16"), ("n", "<f4")]), "compound-numeric"),
    (np.dtype([("Name", "S16"), ("codes", "S4", (3,))]), "compound-text"),
    (np.dtype([("Name", "S16"), ("xy", "<f8", (2,))]), "compound-numeric"),
])
def test_guard_classifies_dtypes_explicitly(dtype, expected):
    assert classify(dtype) == expected


def test_no_unused_fasthdferror_imports():
    for path in sorted((ROOT / "ras_commander" / "hdf").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = any(isinstance(n, ast.ImportFrom) and n.module and n.module.endswith("fast_hdf")
                       and any(a.name == "FastHdfError" for a in n.names) for n in ast.walk(tree))
        used = any(isinstance(n, ast.Name) and n.id == "FastHdfError" for n in ast.walk(tree))
        assert used or not imported, f"{path.name} imports FastHdfError without using it"


def _small(tmp_path):
    path = tmp_path / "small.h5"
    with h5py.File(path, "w") as f:
        f["values"] = np.arange(12, dtype="<f8").reshape(4, 3)
    return path


def test_selection_helper_matches_h5py(tmp_path):
    from ras_commander._fast_hdf_typed import h5py_selection_shape
    with h5py.File(_small(tmp_path), "r") as f:
        ds = f["values"]
        for args in [(), (slice(1, 3),), (2,), (slice(None), 1), ([0, 2],)]:
            assert h5py_selection_shape(ds, args) == np.shape(ds[args if args else ()])
        with pytest.raises(ValueError):
            h5py_selection_shape(ds, (slice(None, None, -1),))


def test_selection_helper_fallback_leaves_selection_to_h5py(tmp_path, monkeypatch):
    pytest.importorskip("ras_commander_fast_hdf")
    import h5py._hl.selections as selections
    from ras_commander import fast_hdf
    from ras_commander._fast_hdf_typed import h5py_selection_shape
    monkeypatch.delattr(selections, "select")
    with h5py.File(_small(tmp_path), "r") as f:
        ds = f["values"]
        assert h5py_selection_shape(ds, (slice(1, 3),)) is None
        with fast_hdf.trace_reads() as trace:
            out = fast_hdf.read_typed(ds, slice(1, 3), backend="auto")
        assert out.tobytes() == ds[1:3].tobytes()
        assert trace and trace[-1]["backend"] in {"h5py-fallback", "native-generic"}
        with pytest.raises(fast_hdf.FastHdfError):
            fast_hdf.read_typed(ds, (slice(None), [0, 2]), backend="rust")


def test_reraise_required_honours_explicit_backend(monkeypatch):
    from ras_commander.fast_hdf import FastHdfError, reraise_required
    exc = FastHdfError("refused")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    reraise_required(exc)
    with pytest.raises(FastHdfError):
        reraise_required(exc, "rust")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    with pytest.raises(FastHdfError):
        reraise_required(exc)
    reraise_required(exc, "python")
    reraise_required(ValueError("not native"), "rust")
