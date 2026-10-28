"""HdfFluvialPluvial engine= policy against RAS_COMMANDER_FAST_HDF (API re-audit P2-N2, P2-N3).

- ``engine="h5py"`` (the reference) keeps main's failure policy (logged ERROR
  and an empty GeoDataFrame) in h5py and auto modes, but native (required) mode
  surfaces a routed read's ``FastHdfError`` instead of swallowing it (P2-N2).
- ``engine="auto"`` (the default) resolves through ``fast_hdf._mode`` (P2-N3):
  ``h5py``/``0`` never tries native, ``auto`` tries native and falls back to the
  reference on any native error, ``native``/``required`` is native or
  ``FastHdfError``. Explicit ``"h5py"``/``"native"`` ignore the environment.
  ``"python"`` is not a fluvial engine.
- The native fluvial engine uses fast_hdf's extension availability and API
  version check.

Every test sets RAS_COMMANDER_FAST_HDF itself, so the suite is mode-independent.
"""
import importlib

import geopandas as gpd
import h5py
import pytest

from ras_commander import fast_hdf
from ras_commander.fast_hdf import FastHdfError
from ras_commander.hdf import HdfFluvialPluvial, HdfMesh

module = importlib.import_module("ras_commander.hdf.HdfFluvialPluvial")
FluvialNativeUnsupportedError = module.FluvialNativeUnsupportedError

METHODS = {
    "calculate_fluvial_pluvial_boundary": "_native_boundary",
    "generate_fluvial_pluvial_polygons": "_native_polygons",
}


@pytest.fixture
def plan(tmp_path):
    path = tmp_path / "policy.p01.hdf"
    with h5py.File(path, "w"):
        pass
    return path


def _python_fails(monkeypatch, exc):
    def fail(*args, **kwargs):
        raise exc
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", fail)


def _native(monkeypatch, method, outcome):
    calls = []

    def native(*args, **kwargs):
        calls.append(args)
        if isinstance(outcome, BaseException):
            raise outcome
        return gpd.GeoDataFrame()
    monkeypatch.setattr(HdfFluvialPluvial, METHODS[method], staticmethod(native))
    return calls


# --- P2-N2: explicit h5py engine ---------------------------------------------
# engine="h5py" runs the reference with every nested read on h5py, so a routed
# FastHdfError cannot arise; any failure keeps main's policy (empty frame).

@pytest.mark.parametrize("mode", ["0", "h5py", "auto", "required", "native"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_h5py_engine_keeps_empty_result_in_every_mode(plan, monkeypatch, method, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    _python_fails(monkeypatch, FastHdfError("controlled native refusal"))
    out = getattr(HdfFluvialPluvial, method)(plan, engine="h5py")
    assert isinstance(out, gpd.GeoDataFrame) and out.empty and not out.attrs


@pytest.mark.parametrize("method", sorted(METHODS))
def test_h5py_engine_forces_h5py_reads_under_native_env(plan, monkeypatch, method):
    from ras_commander import fast_hdf
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "native")
    seen = []
    original = fast_hdf._mode
    monkeypatch.setattr(fast_hdf, "_mode", lambda backend: seen.append(original(backend)) or seen[-1])
    getattr(HdfFluvialPluvial, method)(plan, engine="h5py")
    assert seen and set(seen) == {"python"}


@pytest.mark.parametrize("mode", ["0", "h5py", "auto", "required", "native"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_h5py_engine_ordinary_failure_is_empty_in_every_mode(plan, monkeypatch, method, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    _python_fails(monkeypatch, RuntimeError("controlled ordinary failure"))
    out = getattr(HdfFluvialPluvial, method)(plan, engine="h5py")
    assert isinstance(out, gpd.GeoDataFrame) and out.empty and not out.attrs


# --- P2-N3: engine="auto" follows RAS_COMMANDER_FAST_HDF -----------------------------

@pytest.mark.parametrize("mode", ["h5py", "0", "off", "false", "python"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_auto_engine_never_tries_native_in_h5py_mode(plan, monkeypatch, method, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    calls = _native(monkeypatch, method, AssertionError("native must not run"))
    _python_fails(monkeypatch, RuntimeError("reference ran"))
    out = getattr(HdfFluvialPluvial, method)(plan, engine="auto")
    assert calls == []
    assert out.empty
    engine = out.attrs["fluvial_engine"]
    assert engine["requested"] == "auto" and engine["used"] == "h5py"
    assert "RAS_COMMANDER_FAST_HDF" in engine["fallback_reason"]


@pytest.mark.parametrize("method", sorted(METHODS))
def test_auto_engine_falls_back_in_auto_mode(plan, monkeypatch, method):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    calls = _native(monkeypatch, method, FluvialNativeUnsupportedError("controlled unsupported"))
    _python_fails(monkeypatch, RuntimeError("reference ran"))
    out = getattr(HdfFluvialPluvial, method)(plan, engine="auto")
    assert len(calls) == 1
    assert out.attrs["fluvial_engine"] == {
        "requested": "auto", "used": "h5py", "fallback_reason": "controlled unsupported"}


@pytest.mark.parametrize("method", sorted(METHODS))
def test_auto_engine_falls_back_on_any_native_error(plan, monkeypatch, method):
    # Not only FluvialNativeUnsupportedError: auto gives the reference outcome
    # (here main's logged failure and empty frame) whatever the native path raised.
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    calls = _native(monkeypatch, method, RuntimeError("controlled native crash"))
    _python_fails(monkeypatch, RuntimeError("reference ran"))
    reference = getattr(HdfFluvialPluvial, method)(plan, engine="h5py")
    out = getattr(HdfFluvialPluvial, method)(plan, engine="auto")
    assert len(calls) == 1
    assert out.attrs["fluvial_engine"] == {
        "requested": "auto", "used": "h5py", "fallback_reason": "controlled native crash"}
    assert out.empty and reference.empty and list(out.columns) == list(reference.columns)
    with pytest.raises(RuntimeError, match="controlled native crash"):
        getattr(HdfFluvialPluvial, method)(plan, engine="native")
    assert len(calls) == 2


@pytest.mark.parametrize("mode", ["required", "native"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_auto_engine_propagates_native_error_in_required_mode(plan, monkeypatch, method, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    _native(monkeypatch, method, RuntimeError("controlled native crash"))
    _python_fails(monkeypatch, AssertionError("reference must not run"))
    with pytest.raises(RuntimeError, match="controlled native crash"):
        getattr(HdfFluvialPluvial, method)(plan, engine="auto")


@pytest.mark.parametrize("method", sorted(METHODS))
@pytest.mark.parametrize("mode", ["required", "native"])
def test_auto_engine_requires_native_in_required_mode(plan, monkeypatch, method, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    calls = _native(monkeypatch, method, FluvialNativeUnsupportedError("controlled unsupported"))
    _python_fails(monkeypatch, AssertionError("reference must not run"))
    with pytest.raises(FastHdfError, match="controlled unsupported") as info:
        getattr(HdfFluvialPluvial, method)(plan, engine="auto")
    assert isinstance(info.value.__cause__, FluvialNativeUnsupportedError)
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["auto", "required"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_auto_engine_uses_native_result(plan, monkeypatch, method, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    calls = _native(monkeypatch, method, None)
    out = getattr(HdfFluvialPluvial, method)(plan, engine="auto")
    assert len(calls) == 1
    assert out.attrs["fluvial_engine"] == {"requested": "auto", "used": "native", "fallback_reason": None}


@pytest.mark.parametrize("mode", ["0", "h5py", "auto", "required", "native"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_explicit_engines_ignore_the_environment(plan, monkeypatch, method, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    calls = _native(monkeypatch, method, FluvialNativeUnsupportedError("controlled unsupported"))
    with pytest.raises(FluvialNativeUnsupportedError):
        getattr(HdfFluvialPluvial, method)(plan, engine="native")
    assert len(calls) == 1
    _python_fails(monkeypatch, RuntimeError("reference ran"))
    out = getattr(HdfFluvialPluvial, method)(plan, engine="h5py")
    assert len(calls) == 1 and out.empty and not out.attrs


@pytest.mark.parametrize("engine", ["rust", "python"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_unknown_engine_is_still_rejected(plan, monkeypatch, method, engine):
    # Legacy backend spellings are not fluvial engines ("python" was the old default).
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
    with pytest.raises(ValueError, match="engine must be one of"):
        getattr(HdfFluvialPluvial, method)(plan, engine=engine)


def test_default_engine_is_auto(plan, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    for method in sorted(METHODS):
        _native(monkeypatch, method, None)
        out = getattr(HdfFluvialPluvial, method)(plan)
        assert out.attrs["fluvial_engine"] == {"requested": "auto", "used": "native", "fallback_reason": None}


# --- P2-N3: the native fluvial engine shares fast_hdf's extension gate ---------------

@pytest.fixture
def incompatible_extension(monkeypatch):
    monkeypatch.setattr(fast_hdf, "_native_state", (
        None, "Incompatible ras-commander-fast-hdf API; version 11 is required", None))


@pytest.mark.parametrize("method", sorted(METHODS))
def test_incompatible_extension_is_unsupported_for_native(plan, monkeypatch, incompatible_extension, method):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    with pytest.raises(FluvialNativeUnsupportedError, match="version 11 is required"):
        getattr(HdfFluvialPluvial, method)(plan, engine="native")


@pytest.mark.parametrize("method", sorted(METHODS))
def test_incompatible_extension_auto_falls_back(plan, monkeypatch, incompatible_extension, method):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    _python_fails(monkeypatch, RuntimeError("reference ran"))
    out = getattr(HdfFluvialPluvial, method)(plan, engine="auto")
    assert out.attrs["fluvial_engine"]["used"] == "h5py"
    assert "version 11 is required" in out.attrs["fluvial_engine"]["fallback_reason"]


@pytest.mark.parametrize("method", sorted(METHODS))
def test_incompatible_extension_required_raises(plan, monkeypatch, incompatible_extension, method):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    with pytest.raises(FastHdfError, match="version 11 is required"):
        getattr(HdfFluvialPluvial, method)(plan, engine="auto")
