"""PY-ROUTE-1 public-method equivalence on real fixtures.

Each routed public HDF reader runs three times per fixture: h5py only
(``RAS_COMMANDER_FAST_HDF=0``), auto, and required native. Results must be
identical by ``_exact.assert_identical`` (bits, dtypes, index, CRS WKT, WKB,
attrs); exceptions must match by type and message. ``fast_hdf.trace_reads``
proves the backend: h5py mode has no native read; required mode served every
typed-family read natively (no fallback). A typed refusal in required mode must
raise ``FastHdfError`` while auto then shows an h5py fallback with h5py results.

Gate: ``RAS_ROUTE1_FIXTURES`` = JSON manifest ``{"fixtures": [{"name", "path"}]}``.
Optional ``RAS_ROUTE1_RESULTS`` = JSONL file receiving one outcome per test.
"""
import json
import os
from pathlib import Path

import pytest

from ._exact import assert_identical
from ._cases import CASES

MANIFEST = os.environ.get("RAS_ROUTE1_FIXTURES")
FIXTURES = json.loads(Path(MANIFEST).read_text())["fixtures"] if MANIFEST else []
RESULTS = os.environ.get("RAS_ROUTE1_RESULTS")
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="Set RAS_ROUTE1_FIXTURES to the PY-ROUTE-1 real-fixture JSON manifest")

NATIVE = {"native-typed", "native-generic"}


def _run(monkeypatch, mode, call, path):
    from ras_commander import fast_hdf
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
    fast_hdf.close_sessions()
    with fast_hdf.trace_reads() as trace:
        try:
            value = call(path)
        except Exception as exc:  # compared, never hidden
            return ("raise", type(exc), str(exc), exc), list(trace)
    return ("ok", value), list(trace)


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
    py, py_trace = _run(monkeypatch, "0", call, path)
    assert all(r["backend"] == "h5py" for r in py_trace), "h5py mode performed a native read"
    auto, auto_trace = _run(monkeypatch, "auto", call, path)
    req, req_trace = _run(monkeypatch, "required", call, path)
    _same(py, auto)
    typed = [r for r in req_trace if r["backend"] == "native-typed"]
    if req[0] == "raise" and req[1] is fast_hdf.FastHdfError:
        outcome = "native-refused"
        assert any(r["backend"] == "h5py-fallback" for r in auto_trace), \
            "required native refused but auto did not record an h5py fallback"
    else:
        _same(py, req)
        assert not [r for r in req_trace if r["backend"] in {"h5py", "h5py-fallback"}], \
            "required native mode used h5py for a value read"
        outcome = "native-identical" if typed else "no-typed-read"
    if RESULTS:
        with open(RESULTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "case": case, "fixture": fixture["name"], "outcome": outcome,
                "result": py[0] if py[0] == "ok" else f"raise {py[1].__name__}",
                "typed_reads": len(typed),
                "typed_routes": sorted({r["route"] for r in typed}),
                "metadata_reads": sorted({r["path"] for r in req_trace if r["backend"] == "h5py-metadata"}),
                "generic_reads": len([r for r in req_trace if r["backend"] == "native-generic"]),
                "refusal": str(req[2])[:300] if outcome == "native-refused" else None,
            }) + "\n")
