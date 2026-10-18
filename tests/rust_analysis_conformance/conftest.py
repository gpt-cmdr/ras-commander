"""Native temporal-reduction conformance fixtures.

``RAS_RESULTS_REQUIRE_NATIVE=1`` turns a missing extension into a failure
instead of a skip, so qualification runs cannot pass without native code.
"""
import hashlib
import importlib
import os
from pathlib import Path

import pytest

import ras_commander

ROOT = Path(__file__).resolve().parents[2]


def native_module():
    try:
        module = importlib.import_module("ras_commander_fast_hdf")
    except ImportError:
        module = None
    if module is None or not hasattr(module, "temporal_reduce"):
        if os.environ.get("RAS_RESULTS_REQUIRE_NATIVE") == "1":
            pytest.fail("ras_commander_fast_hdf.temporal_reduce is required but unavailable")
        pytest.skip("native temporal_reduce is not built")
    return module


@pytest.fixture(scope="session")
def native():
    module = native_module()
    # The package under test must be this checkout, not an installed copy.
    assert Path(ras_commander.__file__).resolve().is_relative_to(ROOT), ras_commander.__file__
    # The package re-exports an inner extension; hash the actual binary.
    binary = Path(getattr(module, "ras_commander_fast_hdf", module).__file__)
    assert binary.suffix in {".pyd", ".so"}, binary
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    print(f"\nnative module {binary} sha256 {digest}")
    return module


@pytest.fixture
def native_calls(native, monkeypatch):
    """Count native kernel invocations made through the public adapter."""
    calls = []
    original = native.temporal_reduce

    def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(native, "temporal_reduce", counted)
    return calls


@pytest.fixture
def forbid_python(monkeypatch):
    """Fail if the adapter's Python reference reduction runs."""
    from ras_commander import fast_results

    def refuse(*args, **kwargs):
        raise AssertionError("Python reference reduction ran in a native-required test")

    monkeypatch.setattr(fast_results, "_python_reduce", refuse)
