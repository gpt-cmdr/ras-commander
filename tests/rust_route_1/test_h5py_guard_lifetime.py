"""Regression: the h5py read guard must not repatch h5py classes per context.

Root cause of the intermittent native access violation in the route suites
(runs/release-20261022/AV_ROOT_CAUSE.md): ``watch_h5py_reads`` used to assign and
restore ``h5py.AttributeManager.__getitem__`` on every entry. After ~1000 such
class modifications CPython 3.13 runs out of type versions for the class, stops
invalidating the BINARY_SUBSCR_GETITEM cache (a borrowed pointer to the per-context
wrapper), and ``obj.attrs[k]`` then executes a freed wrapper: the current context
silently records nothing, or the interpreter faults in PyEval_EvalFrameDefault.
"""
import h5py
import numpy as np
import pytest

from . import _h5py_guard
from ._h5py_guard import watch_h5py_reads

PATCHED = [(h5py.Dataset, "__getitem__"), (h5py.Dataset, "read_direct"),
           (h5py.AttributeManager, "__getitem__")]
NAMES = [f"a{i}" for i in range(8)]


@pytest.fixture
def ds(tmp_path):
    path = tmp_path / "guard.h5"
    with h5py.File(path, "w") as f:
        d = f.create_dataset("d", data=np.arange(6, dtype="f4").reshape(2, 3))
        for i, name in enumerate(NAMES):
            d.attrs[name] = np.bytes_(f"v{i}".ljust(16))
    with h5py.File(path, "r") as f:
        yield f["d"]


def _read_attrs(obj, names):
    # same shape as _fast_hdf_typed.read_attrs' h5py path: a specializable obj.attrs[k]
    return {k: obj.attrs[k] for k in names}


def test_contexts_do_not_modify_h5py_classes(ds):
    # Deterministic form of the regression: every context must see the very same
    # installed wrappers, and they stay installed after exit (no per-context patch).
    seen = []
    for _ in range(50):
        with watch_h5py_reads():
            seen.append({key: key[0].__dict__[key[1]] for key in PATCHED})
            _read_attrs(ds, NAMES)
            ds[()]
    after = {key: key[0].__dict__[key[1]] for key in PATCHED}
    for current in seen + [after]:
        for key in PATCHED:
            assert current[key] is seen[0][key], f"{key[0].__name__}.{key[1]} was repatched"
    try:
        import _testcapi
        h5py.AttributeManager.__getitem__  # a lookup assigns the version tag
        version = _testcapi.type_get_version(h5py.AttributeManager)
    except (ImportError, AttributeError):
        return
    for _ in range(20):
        with watch_h5py_reads():
            _read_attrs(ds, NAMES)
    h5py.AttributeManager.__getitem__
    assert _testcapi.type_get_version(h5py.AttributeManager) == version, "class modified by a context"


_STRESS = r"""
import gc, sys, h5py, numpy as np
sys.path.insert(0, sys.argv[2])
from rust_route_1._h5py_guard import watch_h5py_reads
names = [f"a{i}" for i in range(8)]
with h5py.File(sys.argv[1], "w") as f:
    d = f.create_dataset("d", data=np.zeros(3, "f4"))
    for n in names:
        d.attrs[n] = np.bytes_(n)
def read(obj):
    return {k: obj.attrs[k] for k in names}
with h5py.File(sys.argv[1], "r") as f:
    d = f["d"]
    for i in range(int(sys.argv[3])):
        churn = i >= 400   # the old guard exhausts AttributeManager's versions near 500
        junk = [(lambda: j) for j in range(30_000)] if churn else None
        with watch_h5py_reads() as records:
            read(d)
        junk2 = [(lambda: j) for j in range(30_000)] if churn else None
        del junk, junk2
        gc.collect()
        if sum(r.get("target") == "attribute" for r in records) != len(names):
            print(f"context {i}: recorded {len(records)} of {len(names)} attribute reads", flush=True)
            sys.exit(3)
        read(d)   # specialized obj.attrs[k] outside any context
print("ok", flush=True)
"""


def test_many_contexts_with_allocator_churn_subprocess(tmp_path):
    # 900 contexts (> the 1000 type versions a 3.13 class may use when each context
    # patches and restores it) with obmalloc churn so a freed wrapper's arena is
    # released. With per-context patching the child records into a dead list
    # (exit 3) or dies with an access violation; it must now finish cleanly.
    import subprocess
    import sys
    from pathlib import Path
    proc = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", _STRESS, str(tmp_path / "s.h5"),
         str(Path(__file__).resolve().parents[1]), "900"],
        capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0 and "ok" in proc.stdout, (
        f"rc={proc.returncode:#x}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")


def test_every_context_records_its_reads_after_many_contexts(ds):
    for i in range(1300):
        with watch_h5py_reads() as records:
            values = _read_attrs(ds, NAMES)
            ds[0, 1:]
        attrs = [r for r in records if r.get("target") == "attribute"]
        assert len(attrs) == len(NAMES), f"context {i}: {len(attrs)} attribute reads recorded"
        assert [r["path"] for r in attrs] == [f"/d@{n}" for n in NAMES]
        assert sum(r["how"] == "getitem" for r in records) == 1
        assert values["a3"] == b"v3".ljust(16)


def test_nested_contexts_and_no_recording_outside(ds):
    with watch_h5py_reads() as outer:
        with watch_h5py_reads() as inner:
            _read_attrs(ds, NAMES[:2])
        _read_attrs(ds, NAMES[:1])
    _read_attrs(ds, NAMES)  # outside every context: not recorded anywhere
    assert len(inner) == 2 and len(outer) == 3
    assert not _h5py_guard._ACTIVE


def test_foreign_patch_is_refused(ds, monkeypatch):
    def other(self, name):
        return None
    monkeypatch.setattr(h5py.AttributeManager, "__getitem__", other)
    with pytest.raises(RuntimeError, match="patched by another caller"):
        with watch_h5py_reads():
            pass
