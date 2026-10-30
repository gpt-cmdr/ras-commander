"""``fast_hdf.h5py_until_qualified``: auto mode stays on h5py until a fixture qualifies native.

A decorated function makes no native read in auto mode (nested default-``auto``
reads are scoped to h5py); ``RAS_COMMANDER_FAST_HDF=native`` or an explicit
native scope still runs it natively, and ``h5py`` never reads natively. Every
name registered in ``fast_hdf.UNQUALIFIED_NATIVE`` must resolve to a public
attribute marked ``__native_qualified__ = False``.

Every test sets RAS_COMMANDER_FAST_HDF itself, so the module is mode-independent.
"""
import importlib

import h5py
import numpy as np
import pytest

from ras_commander import fast_hdf

# Modules that decorate functions with h5py_until_qualified.
DECORATING_MODULES = [
    "ras_commander.check._utils",
    "ras_commander.check.check_floodways",
    "ras_commander.geom.GeomMesh",
    "ras_commander.geom.GeomProjection",
    "ras_commander.hdf.HdfInfiltration",
    "ras_commander.hdf.HdfLandCover",
    "ras_commander.hdf.HdfPlan",
    "ras_commander.hdf.HdfResultsPlan",
    "ras_commander.hdf.HdfResultsSediment",
    "ras_commander.parent_display",
    "ras_commander.RasEncroachments",
    "ras_commander.RasFlowOptimization",
    "ras_commander.RasUnsteady",
    "ras_commander._container_compute",
    "ras_commander._landcover_native",
]


@pytest.fixture
def small_hdf(tmp_path):
    path = tmp_path / "qualified.hdf"
    with h5py.File(path, "w") as hdf:
        hdf["contiguous"] = np.arange(12, dtype="f4").reshape(3, 4)
        hdf.create_dataset("chunked", data=np.arange(400, dtype="f8").reshape(10, 40), chunks=(5, 40))
    return path


@pytest.fixture
def decorated(monkeypatch):
    """A locally decorated reader; registered in a private set, not the real registry."""
    registry = set()
    monkeypatch.setattr(fast_hdf, "UNQUALIFIED_NATIVE", registry)

    @fast_hdf.h5py_until_qualified
    def read_both(path):
        with h5py.File(path, "r") as hdf:
            return {name: (fast_hdf.read_dataset(hdf[name]), fast_hdf.read_typed(hdf[name]))
                    for name in ("contiguous", "chunked")}

    assert registry == {f"{read_both.__module__}.{read_both.__qualname__}"}
    assert read_both.__native_qualified__ is False
    return read_both


def _undecorated(path):
    with h5py.File(path, "r") as hdf:
        return {name: (fast_hdf.read_dataset(hdf[name]), fast_hdf.read_typed(hdf[name]))
                for name in ("contiguous", "chunked")}


def _traced(func, path):
    with fast_hdf.trace_reads() as records:
        values = func(path)
    with h5py.File(path, "r") as hdf:
        for name, pair in values.items():
            for value in pair:
                np.testing.assert_array_equal(value, hdf[name][()])
    reads = [r for r in records if r["backend"] != "diagnostic"]
    assert reads, "trace recorded no reads"
    return [r["backend"] for r in reads]


def _native_extension():
    if not fast_hdf.available():
        pytest.skip("ras_commander_fast_hdf extension unavailable")


@pytest.mark.parametrize("value", [None, "auto", "1"])
def test_auto_mode_makes_no_native_reads(small_hdf, decorated, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    else:
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", value)
    backends = _traced(decorated, small_hdf)
    assert not [b for b in backends if b.startswith("native")], backends
    if fast_hdf.available():
        # The same reads undecorated are native in auto mode: the decorator did the work.
        assert any(b.startswith("native") for b in _traced(_undecorated, small_hdf))


@pytest.mark.parametrize("value", ["native", "required", "rust"])
def test_native_mode_still_reads_natively(small_hdf, decorated, monkeypatch, value):
    _native_extension()
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", value)
    backends = _traced(decorated, small_hdf)
    assert all(b.startswith("native") for b in backends), backends


def test_explicit_native_scope_still_reads_natively(small_hdf, decorated, monkeypatch):
    _native_extension()
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    with fast_hdf.backend_scope("native"):
        backends = _traced(decorated, small_hdf)
    assert all(b.startswith("native") for b in backends), backends


@pytest.mark.parametrize("value", ["h5py", "0", "python"])
def test_h5py_mode_makes_no_native_reads(small_hdf, decorated, monkeypatch, value):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", value)
    backends = _traced(decorated, small_hdf)
    assert not [b for b in backends if b.startswith("native")], backends


def test_decorated_function_does_not_leak_its_scope(small_hdf, decorated, monkeypatch):
    _native_extension()
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    _traced(decorated, small_hdf)
    assert fast_hdf._mode("auto") == "auto"
    assert any(b.startswith("native") for b in _traced(_undecorated, small_hdf))


def _resolve(dotted):
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        for attr in parts[split:]:
            obj = getattr(obj, attr)
        return obj
    raise ImportError(dotted)


def test_every_unqualified_name_is_importable_and_marked():
    for name in DECORATING_MODULES:
        importlib.import_module(name)
    registered = set(fast_hdf.UNQUALIFIED_NATIVE)
    assert registered
    # Every decorating module contributed at least one name.
    for module_name in DECORATING_MODULES:
        assert any(n.startswith(module_name + ".") for n in registered), module_name
    unmarked = []
    for name in sorted(registered):
        obj = _resolve(name)
        assert callable(obj), name
        if getattr(obj, "__native_qualified__", None) is not False:
            unmarked.append(name)
    assert not unmarked, unmarked
