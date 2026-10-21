"""PY-ROUTE-1 public-method equivalence on real fixtures.

Each routed public HDF reader runs three times per fixture: h5py only
(``RAS_COMMANDER_FAST_HDF=0``), auto, and required native. Results must be
identical by ``_exact.assert_identical`` (bits, dtypes, index, CRS WKT, WKB,
attrs); exceptions must match by type and message. ``fast_hdf.trace_reads``
proves the backend: h5py mode has no native read; required mode served every
typed-family read natively (no fallback). A typed refusal in required mode must
raise ``FastHdfError`` while auto then shows an h5py fallback with h5py results.

The trace only sees reads made through the routing wrappers, so required mode
also runs under ``_h5py_guard.watch_h5py_reads`` (independent interception of
``h5py.Dataset.__getitem__``/``read_direct``): a NATIVE method may read only the
documented metadata (strings, routed compound identity/attribute tables) through
h5py. Finally the engine is replaced by one whose every call raises
``CorruptDataError``: auto must still return the h5py outcome, and required mode
must raise ``FastHdfError`` whenever the method performs a native read.

Gate: ``RAS_ROUTE1_FIXTURES`` = JSON manifest ``{"fixtures": [{"name", "path"}]}``.
Optional ``RAS_ROUTE1_RESULTS`` = JSONL file receiving one outcome per test.
"""
import json
import os
from pathlib import Path

import pytest

from ._exact import assert_identical
from ._cases import CASES
from ._h5py_guard import offending, watch_h5py_reads

MANIFEST = os.environ.get("RAS_ROUTE1_FIXTURES")
FIXTURES = json.loads(Path(MANIFEST).read_text())["fixtures"] if MANIFEST else []
RESULTS = os.environ.get("RAS_ROUTE1_RESULTS")
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="Set RAS_ROUTE1_FIXTURES to the PY-ROUTE-1 real-fixture JSON manifest")

NATIVE = {"native-typed", "native-generic"}


# Inventory label H5PY (chunked digest reads stay on h5py); exercised for parity only.
H5PY_LABELLED = {"HdfMesh.get_mesh_geometry_inventory"}
# HdfResultsMesh readers keep the FIM-wave1 policy that predates this branch:
# fast_hdf.read_dataset treats a native Corrupt refusal as fatal in auto mode too
# ("native exceptions are never converted to successful empty results"); the
# method may wrap that FastHdfError in its own exception type.
CORRUPT_FATAL_IN_AUTO = "HdfResultsMesh."


def _native_failure(exc):
    """Whether ``exc`` is, or was raised from, a FastHdfError."""
    from ras_commander import fast_hdf
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, fast_hdf.FastHdfError):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


class _FailingEngine:
    """The real extension with every callable replaced by a Corrupt refusal."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        value = getattr(self._real, name)
        if isinstance(value, type) and issubclass(value, BaseException):
            return value
        if callable(value):
            def fail(*args, **kwargs):
                raise self._real.CorruptDataError(f"injected engine failure in {name}")
            return fail
        return value


def _run(monkeypatch, mode, call, path, inject=False):
    from ras_commander import fast_hdf
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    fast_hdf.close_sessions()
    real_native = fast_hdf._native
    if inject:
        def failing(m):
            module = real_native(m)
            return None if module is None else _FailingEngine(module)
        monkeypatch.setattr(fast_hdf, "_native", failing)
    try:
        with watch_h5py_reads() as direct, fast_hdf.trace_reads() as trace:
            try:
                value = call(path)
            except Exception as exc:  # compared, never hidden
                return ("raise", type(exc), str(exc), exc), list(trace), list(direct)
        return ("ok", value), list(trace), list(direct)
    finally:
        monkeypatch.setattr(fast_hdf, "_native", real_native)
        fast_hdf.close_sessions()


def _same(a, b):
    assert a[0] == b[0], f"outcome {a[0]} vs {b[0]}: {a[1:3]} / {b[1:3]}"
    if a[0] == "ok":
        assert_identical(a[1], b[1])
    else:
        assert a[1] is b[1] and a[2] == b[2], f"exception {a[1:3]} vs {b[1:3]}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f["name"] for f in FIXTURES])
@pytest.mark.parametrize("case", sorted(CASES), ids=sorted(CASES))
def test_public_method(case, fixture, monkeypatch):
    native = pytest.importorskip("ras_commander_fast_hdf")
    assert native.API_VERSION == 9
    from ras_commander import fast_hdf
    call = CASES[case]
    path = fixture["path"]
    py, py_trace, _ = _run(monkeypatch, "0", call, path)
    assert all(r["backend"] == "h5py" for r in py_trace), "h5py mode performed a native read"
    auto, auto_trace, _ = _run(monkeypatch, "auto", call, path)
    req, req_trace, req_direct = _run(monkeypatch, "required", call, path)
    _same(py, auto)
    typed = [r for r in req_trace if r["backend"] == "native-typed"]
    native_reads = [r for r in req_trace if r["backend"] in NATIVE]
    bypass = [] if case in H5PY_LABELLED else offending(req_direct)
    assert not bypass, f"required native read values through h5py directly: {bypass[:5]}"
    if req[0] == "raise" and req[1] is fast_hdf.FastHdfError:
        outcome = "native-refused"
        assert any(r["backend"] == "h5py-fallback" for r in auto_trace), \
            "required native refused but auto did not record an h5py fallback"
    else:
        _same(py, req)
        assert not [r for r in req_trace if r["backend"] in {"h5py", "h5py-fallback"}], \
            "required native mode used h5py for a value read"
        outcome = "native-identical" if typed else "no-typed-read"
    # Injected engine failure: every native call raises CorruptDataError.
    inj_auto, _, _ = _run(monkeypatch, "auto", call, path, inject=True)
    if (case.startswith(CORRUPT_FATAL_IN_AUTO) and inj_auto[0] == "raise"
            and _native_failure(inj_auto[3])):
        injected_auto = "corrupt-fatal (FIM-wave1 policy)"
    else:
        _same(py, inj_auto)
        injected_auto = "h5py-outcome"
    inj_req, _, _ = _run(monkeypatch, "required", call, path, inject=True)
    if native_reads and case not in H5PY_LABELLED:
        assert inj_req[0] == "raise" and inj_req[1] is fast_hdf.FastHdfError, \
            f"required native swallowed an injected engine failure: {inj_req[:3]}"
    injected_required = f"raise {inj_req[1].__name__}" if inj_req[0] == "raise" else "ok"
    if RESULTS:
        with open(RESULTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "case": case, "fixture": fixture["name"], "outcome": outcome,
                "result": py[0] if py[0] == "ok" else f"raise {py[1].__name__}",
                "typed_reads": len(typed),
                "typed_routes": sorted({r["route"] for r in typed}),
                "metadata_reads": sorted({r["path"] for r in req_trace if r["backend"] == "h5py-metadata"}),
                "generic_reads": len([r for r in req_trace if r["backend"] == "native-generic"]),
                "h5py_direct_reads": len(req_direct),
                "h5py_direct_offending": len(bypass),
                "injected_auto": injected_auto,
                "injected_required": injected_required,
                "refusal": str(req[2])[:300] if outcome == "native-refused" else None,
            }) + "\n")
