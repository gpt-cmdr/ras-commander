"""ROUTE-NONHDF equivalence: routed h5py read sites outside ``ras_commander/hdf``.

Same contract and harness as PY-ROUTE-1/2 (``tests/rust_route_1``): every routed
function (or, where the public function needs HEC-RAS or .NET execution, its read
helper) runs on real fixtures in h5py-only (``RAS_COMMANDER_FAST_HDF=0``), auto and
required-native mode. Results must be identical by ``assert_identical`` and
exceptions identical by type and message. The required run is wrapped by the
independent h5py interception gate (``_h5py_guard.watch_h5py_reads``: dataset values
through ``Dataset.__getitem__``/``read_direct`` and attribute values through
``AttributeManager.__getitem__``); only text datasets and text-only identity tables
may be read through h5py. Every case also runs against an engine whose every call
raises ``CorruptDataError``: auto must give the h5py outcome and required mode must
raise ``FastHdfError`` whenever the function made a native read.

Gate: ``RAS_ROUTE1_FIXTURES`` and/or ``RAS_ROUTE2_FIXTURES`` (JSON manifests); the
suite skips with an explicit reason when neither is set. Optional
``RAS_ROUTE_NONHDF_RESULTS`` = JSONL file receiving one outcome per test.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rust_route_1.test_routed_equivalence import NATIVE, _run, _same  # noqa: E402
from rust_route_1._h5py_guard import offending  # noqa: E402

from ._case import all_cases, load_fixtures  # noqa: E402

FIXTURES, PROJECTS = load_fixtures()
CASES = all_cases()
RESULTS = os.environ.get("RAS_ROUTE_NONHDF_RESULTS")
if RESULTS and os.environ.get("PYTEST_XDIST_WORKER"):
    RESULTS = f"{RESULTS}.{os.environ['PYTEST_XDIST_WORKER']}"
GATED = bool(os.environ.get("RAS_ROUTE1_FIXTURES") or os.environ.get("RAS_ROUTE2_FIXTURES"))
pytestmark = pytest.mark.skipif(
    not GATED, reason="Set RAS_ROUTE1_FIXTURES / RAS_ROUTE2_FIXTURES to the real-fixture JSON manifests")


def _params():
    out = []
    for name in sorted(CASES):
        case = CASES[name]
        if "project" in case.kinds:
            out += [pytest.param(name, p, p["name"], id=f"{name}-{p['name']}") for p in PROJECTS]
        for f in FIXTURES:
            if f["kind"] in case.kinds:
                out.append(pytest.param(name, f["path"], f["name"], id=f"{name}-{f['name']}"))
    return out


@pytest.mark.parametrize("case,target,label", _params())
def test_nonhdf_function(case, target, label, monkeypatch):
    native = pytest.importorskip("ras_commander_fast_hdf")
    assert native.API_VERSION == 11
    from ras_commander import fast_hdf
    spec = CASES[case]
    if spec.max_mb is not None and isinstance(target, str) and Path(target).stat().st_size > spec.max_mb * 1e6:
        pytest.skip(f"{case}: bounded to fixtures below {spec.max_mb} MB ({spec.note or 'slow in h5py mode'})")
    call = spec.call
    py, py_trace, _ = _run(monkeypatch, "0", call, target)
    if py[0] == "raise" and issubclass(py[1], pytest.skip.Exception):
        pytest.skip(py[2])
    assert all(r["backend"] == "h5py" for r in py_trace), "h5py mode performed a native read"
    auto, auto_trace, _ = _run(monkeypatch, "auto", call, target)
    req, req_trace, req_direct = _run(monkeypatch, "required", call, target)
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
        outcome = ("native-identical" if typed else "native-literal" if native_reads
                   else "metadata-only" if req_trace else "no-value-read")
    inj_auto, _, _ = _run(monkeypatch, "auto", call, target, inject=True)
    _same(py, inj_auto)
    inj_req, _, _ = _run(monkeypatch, "required", call, target, inject=True)
    if native_reads:
        assert inj_req[0] == "raise" and inj_req[1] is fast_hdf.FastHdfError, \
            f"required native swallowed an injected engine failure: {inj_req[:3]}"
    if RESULTS:
        with open(RESULTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "case": case, "fixture": label, "outcome": outcome, "helper": spec.helper,
                "result": py[0] if py[0] == "ok" else f"raise {py[1].__name__}",
                "typed_reads": len(typed),
                "typed_routes": sorted({str(r["route"]) for r in typed}),
                "generic_reads": len([r for r in req_trace if r["backend"] == "native-generic"]),
                "attr_reads": len([r for r in req_trace if str(r.get("route") or "").startswith("attr")]),
                "metadata_reads": len([r for r in req_trace if r["backend"] == "h5py-metadata"]),
                "h5py_direct_reads": len(req_direct),
                "h5py_direct_offending": len(bypass),
                "injected_required": f"raise {inj_req[1].__name__}" if inj_req[0] == "raise" else "ok",
                "refusal": str(req[2])[:300] if outcome == "native-refused" else None,
            }) + "\n")


@pytest.mark.skipif(not GATED, reason="fixture manifests not set")
def test_every_case_has_a_fixture():
    """A declared case that no fixture exercises would be silently untested."""
    kinds = {f["kind"] for f in FIXTURES} | ({"project"} if PROJECTS else set())
    missing = [n for n, c in CASES.items() if not (c.kinds & kinds)]
    assert not missing, f"cases without any fixture of their kinds: {missing}"
