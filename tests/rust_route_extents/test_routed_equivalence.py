"""ROUTE-EXTENTS public-method equivalence on real fixtures.

Project extents, point/profile queries, mesh max-depth and depth rasters, the
hydraulic product package, CRS/unit/attribute readers and the fixed-length text
datasets (engine ``raw_fixed_strings``). Same contract and harness as PY-ROUTE-1
(``tests/rust_route_1``): every case runs in h5py-only, auto and required-native
mode, results must be identical by ``assert_identical`` and exceptions by type
and message; the required run is wrapped by the h5py dataset/attribute
interception gate; and every case is re-run against an engine whose every call
raises ``CorruptDataError`` (auto must give the h5py outcome, required must raise
``FastHdfError`` whenever the method made a native read).

Text datasets are no longer an h5py metadata exception for these methods: their
fixed-length strings are read through the engine, so a required-mode h5py read of
a text dataset made by a case's own call is reported here (``text_via_h5py``).

Gate: ``RAS_ROUTE_EXTENTS_FIXTURES`` = JSON manifest ``{"fixtures": [{"name", "path"}]}``.
Optional ``RAS_ROUTE_EXTENTS_RESULTS`` = JSONL file receiving one outcome per test.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rust_route_1.test_routed_equivalence import NATIVE, _run, _same  # noqa: E402
from rust_route_1._h5py_guard import offending  # noqa: E402

from ._cases import CASES  # noqa: E402

MANIFEST = os.environ.get("RAS_ROUTE_EXTENTS_FIXTURES")
FIXTURES = json.loads(Path(MANIFEST).read_text())["fixtures"] if MANIFEST else []
RESULTS = os.environ.get("RAS_ROUTE_EXTENTS_RESULTS")
if RESULTS and os.environ.get("PYTEST_XDIST_WORKER"):
    RESULTS = f"{RESULTS}.{os.environ['PYTEST_XDIST_WORKER']}"
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="Set RAS_ROUTE_EXTENTS_FIXTURES to the real-fixture JSON manifest")


def _text_via_h5py(records):
    """Fixed/variable text dataset values read through h5py outside the harness."""
    return [r for r in records if r.get("target") != "attribute" and not r["harness"]
            and r["kind"] == "string"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f["name"] for f in FIXTURES])
@pytest.mark.parametrize("case", sorted(CASES), ids=sorted(CASES))
def test_public_method(case, fixture, monkeypatch):
    native = pytest.importorskip("ras_commander_fast_hdf")
    assert native.API_VERSION == 11
    from ras_commander import fast_hdf
    call, path = CASES[case], fixture["path"]
    py, py_trace, _ = _run(monkeypatch, "0", call, path)  # pytest.skip propagates
    assert all(r["backend"] == "h5py" for r in py_trace), "h5py mode performed a native read"
    auto, auto_trace, _ = _run(monkeypatch, "auto", call, path)
    req, req_trace, req_direct = _run(monkeypatch, "required", call, path)
    _same(py, auto)
    typed = [r for r in req_trace if r["backend"] == "native-typed"]
    native_reads = [r for r in req_trace if r["backend"] in NATIVE]
    bypass = offending(req_direct)
    assert not bypass, f"required native read values through h5py directly: {bypass[:5]}"
    text_h5py = _text_via_h5py(req_direct)
    if req[0] == "raise" and req[1] is fast_hdf.FastHdfError:
        outcome = "native-refused"
        assert any(r["backend"] == "h5py-fallback" for r in auto_trace), \
            "required native refused but auto did not record an h5py fallback"
    else:
        _same(py, req)
        assert not [r for r in req_trace if r["backend"] in {"h5py", "h5py-fallback"}], \
            "required native mode used h5py for a value read"
        if typed:
            outcome = "native-identical"
        elif native_reads:
            outcome = "native-literal"
        else:
            outcome = "no-typed-read"
    inj_auto, _, _ = _run(monkeypatch, "auto", call, path, inject=True)
    _same(py, inj_auto)
    inj_req, _, _ = _run(monkeypatch, "required", call, path, inject=True)
    if native_reads:
        assert inj_req[0] == "raise" and inj_req[1] is fast_hdf.FastHdfError, \
            f"required native swallowed an injected engine failure: {inj_req[:3]}"
    if RESULTS:
        with open(RESULTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "case": case, "fixture": fixture["name"], "outcome": outcome,
                "result": py[0] if py[0] == "ok" else f"raise {py[1].__name__}",
                "typed_reads": len(typed),
                "typed_routes": sorted({r["route"] for r in typed}),
                "generic_reads": len([r for r in req_trace if r["backend"] == "native-generic"]),
                "metadata_reads": sorted({r["path"] for r in req_trace if r["backend"] == "h5py-metadata"}),
                "text_via_h5py": sorted({r["path"] for r in text_h5py}),
                "h5py_direct_reads": len(req_direct),
                "h5py_direct_offending": len(bypass),
                "h5py_attribute_reads": len([r for r in req_direct if r.get("target") == "attribute"
                                             and not r["harness"]]),
                "injected_required": f"raise {inj_req[1].__name__}" if inj_req[0] == "raise" else "ok",
                "refusal": str(req[2])[:300] if outcome == "native-refused" else None,
            }) + "\n")
