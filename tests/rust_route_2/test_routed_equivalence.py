"""PY-ROUTE-2 public-method equivalence on real fixtures (Wave 3 families).

Same contract and harness as PY-ROUTE-1 (``tests/rust_route_1``): every routed
method runs in h5py-only, auto and required-native mode on every fixture, results
must be identical by ``assert_identical`` (bits, dtypes, index, columns, CRS WKT,
WKB, attrs, xarray coords) and exceptions identical by type and message. The
required-native run is wrapped by the independent h5py value-read interception
(r4 gate): only documented metadata may be read through h5py. Every case is also
run against an engine whose every call raises ``CorruptDataError``: auto must give
the h5py outcome, and required mode must raise ``FastHdfError`` whenever the method
made a native read.

Gate: ``RAS_ROUTE2_FIXTURES`` = JSON manifest ``{"fixtures": [{"name", "path"}]}``.
Optional ``RAS_ROUTE2_RESULTS`` = JSONL file receiving one outcome per test.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rust_route_1.test_routed_equivalence import NATIVE, _run, _same  # noqa: E402
from rust_route_1._h5py_guard import offending  # noqa: E402

from ._cases import CASES, PROJECT_CASES  # noqa: E402

MANIFEST = os.environ.get("RAS_ROUTE2_FIXTURES")
_MANIFEST = json.loads(Path(MANIFEST).read_text()) if MANIFEST else {}
FIXTURES = _MANIFEST.get("fixtures", [])
# Read-only project folders for multi-file land-cover/infiltration methods.
PROJECTS = _MANIFEST.get("projects", [])
RESULTS = os.environ.get("RAS_ROUTE2_RESULTS")
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="Set RAS_ROUTE2_FIXTURES to the PY-ROUTE-2 real-fixture JSON manifest")


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f["name"] for f in FIXTURES])
@pytest.mark.parametrize("case", sorted(CASES), ids=sorted(CASES))
def test_public_method(case, fixture, monkeypatch):
    _check(case, CASES[case], fixture["path"], fixture["name"], monkeypatch)


@pytest.mark.parametrize("project", PROJECTS, ids=[p["name"] for p in PROJECTS])
@pytest.mark.parametrize("case", sorted(PROJECT_CASES), ids=sorted(PROJECT_CASES))
def test_project_method(case, project, monkeypatch):
    _check(case, PROJECT_CASES[case], project, project["name"], monkeypatch)


def _check(case, call, path, label, monkeypatch):
    native = pytest.importorskip("ras_commander_fast_hdf")
    assert native.API_VERSION == 10
    from ras_commander import fast_hdf
    py, py_trace, _ = _run(monkeypatch, "0", call, path)
    assert all(r["backend"] == "h5py" for r in py_trace), "h5py mode performed a native read"
    auto, auto_trace, _ = _run(monkeypatch, "auto", call, path)
    req, req_trace, req_direct = _run(monkeypatch, "required", call, path)
    _same(py, auto)
    typed = [r for r in req_trace if r["backend"] == "native-typed"]
    native_reads = [r for r in req_trace if r["backend"] in NATIVE]
    bypass = offending(req_direct)
    assert not bypass, f"required native read values through h5py directly: {bypass[:5]}"
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
                "case": case, "fixture": label, "outcome": outcome,
                "result": py[0] if py[0] == "ok" else f"raise {py[1].__name__}",
                "typed_reads": len(typed),
                "typed_routes": sorted({r["route"] for r in typed}),
                "generic_reads": len([r for r in req_trace if r["backend"] == "native-generic"]),
                "metadata_reads": sorted({r["path"] for r in req_trace if r["backend"] == "h5py-metadata"}),
                "h5py_direct_reads": len(req_direct),
                "h5py_direct_offending": len(bypass),
                "injected_required": f"raise {inj_req[1].__name__}" if inj_req[0] == "raise" else "ok",
                "refusal": str(req[2])[:300] if outcome == "native-refused" else None,
            }) + "\n")
