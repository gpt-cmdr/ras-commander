"""HdfFluvialPluvial engine= policy against RAS_COMMANDER_FAST_HDF (API re-audit P2-N2, P2-N3).

- The default ``engine="python"`` keeps main's failure policy (logged ERROR and
  an empty GeoDataFrame) in python and auto modes, but required mode surfaces a
  routed read's ``FastHdfError`` instead of swallowing it (P2-N2).
- ``engine="auto"`` resolves through ``fast_hdf._mode`` (P2-N3): ``0`` never
  tries native, ``auto`` tries native and falls back, ``required`` is native or
  ``FastHdfError``. Explicit ``"python"``/``"native"`` ignore the environment.
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


# --- P2-N2: default python engine in required mode ------------------------------

@pytest.mark.parametrize("method", sorted(METHODS))
def test_python_engine_reraises_fast_hdf_error_in_required_mode(plan, monkeypatch, method):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    _python_fails(monkeypatch, FastHdfError("controlled native refusal"))
    with pytest.raises(FastHdfError, match="controlled native refusal"):
        getattr(HdfFluvialPluvial, method)(plan)


@pytest.mark.parametrize("mode", ["0", "auto"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_python_engine_keeps_empty_result_outside_required_mode(plan, monkeypatch, method, mode):
    # In python/auto mode a FastHdfError cannot reach here from the routed
    # readers; if one did, main's policy (empty frame) applies unchanged.
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    _python_fails(monkeypatch, FastHdfError("controlled native refusal"))
    out = getattr(HdfFluvialPluvial, method)(plan)
    assert isinstance(out, gpd.GeoDataFrame) and out.empty and not out.attrs


@pytest.mark.parametrize("mode", ["0", "auto", "required"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_python_engine_ordinary_failure_is_empty_in_every_mode(plan, monkeypatch, method, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    _python_fails(monkeypatch, RuntimeError("controlled ordinary failure"))
    out = getattr(HdfFluvialPluvial, method)(plan)
    assert isinstance(out, gpd.GeoDataFrame) and out.empty and not out.attrs


# --- P2-N3: engine="auto" follows RAS_COMMANDER_FAST_HDF -----------------------------

@pytest.mark.parametrize("mode", ["0", "off", "false", "python"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_auto_engine_never_tries_native_in_python_mode(plan, monkeypatch, method, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    calls = _native(monkeypatch, method, AssertionError("native must not run"))
    _python_fails(monkeypatch, RuntimeError("reference ran"))
    out = getattr(HdfFluvialPluvial, method)(plan, engine="auto")
    assert calls == []
    assert out.empty
    engine = out.attrs["fluvial_engine"]
    assert engine["requested"] == "auto" and engine["used"] == "python"
    assert "RAS_COMMANDER_FAST_HDF" in engine["fallback_reason"]


@pytest.mark.parametrize("method", sorted(METHODS))
def test_auto_engine_falls_back_in_auto_mode(plan, monkeypatch, method):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    calls = _native(monkeypatch, method, FluvialNativeUnsupportedError("controlled unsupported"))
    _python_fails(monkeypatch, RuntimeError("reference ran"))
    out = getattr(HdfFluvialPluvial, method)(plan, engine="auto")
    assert len(calls) == 1
    assert out.attrs["fluvial_engine"] == {
        "requested": "auto", "used": "python", "fallback_reason": "controlled unsupported"}


@pytest.mark.parametrize("method", sorted(METHODS))
def test_auto_engine_requires_native_in_required_mode(plan, monkeypatch, method):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
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


@pytest.mark.parametrize("mode", ["0", "auto", "required"])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_explicit_engines_ignore_the_environment(plan, monkeypatch, method, mode):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    calls = _native(monkeypatch, method, FluvialNativeUnsupportedError("controlled unsupported"))
    with pytest.raises(FluvialNativeUnsupportedError):
        getattr(HdfFluvialPluvial, method)(plan, engine="native")
    assert len(calls) == 1
    _python_fails(monkeypatch, RuntimeError("reference ran"))
    out = getattr(HdfFluvialPluvial, method)(plan, engine="python")
    assert len(calls) == 1 and out.empty and not out.attrs


def test_unknown_engine_is_still_rejected(plan, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
    with pytest.raises(ValueError, match="engine must be one of"):
        HdfFluvialPluvial.generate_fluvial_pluvial_polygons(plan, engine="rust")


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
    assert out.attrs["fluvial_engine"]["used"] == "python"
    assert "version 11 is required" in out.attrs["fluvial_engine"]["fallback_reason"]


@pytest.mark.parametrize("method", sorted(METHODS))
def test_incompatible_extension_required_raises(plan, monkeypatch, incompatible_extension, method):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    with pytest.raises(FastHdfError, match="version 11 is required"):
        getattr(HdfFluvialPluvial, method)(plan, engine="auto")
