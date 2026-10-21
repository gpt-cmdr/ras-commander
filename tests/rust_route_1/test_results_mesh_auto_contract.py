"""PY-ROUTE-2 item 4: HdfResultsMesh readers keep the h5py outcome in auto mode.

``fast_hdf.read_dataset`` (the reader behind HdfResultsMesh) previously treated a
native Corrupt refusal as fatal in auto mode. h5py behaviour is the public
contract, so auto now reproduces the h5py outcome on any native failure,
Corrupt/checksum included; required native still raises ``FastHdfError``.

Review-r2 adds the exception-type cases (h5py ``ValueError``/``OSError`` must not
become ``FastHdfError`` in auto) and the partial-result cases: h5py's
``get_mesh_cells_timeseries``/``get_mesh_faces_timeseries`` drop the damaged
variable and return the rest, and auto must return that same partial result.

Each case rewrites one real 2D result dataset of a *copy* of AustinOyster.p01 with
its exact values in Fletcher32 chunks, shows required native reads the clean copy
through the typed mesh-result route, flips one stored checksum byte, then
compares h5py, auto and required outcomes.

Gate: ``RAS_ROUTE1_FIXTURES`` (same manifest as the equivalence suite).
"""
import pytest

from .test_routed_r2 import _fixture, _flip, _fletcher32_copy, _outcome, _same

BASE = "Results/Unsteady/Output/Output Blocks/Base Output"
AREA = "Perimeter 1"
CASES = {
    "get_mesh_max_ws": (
        f"{BASE}/Summary Output/2D Flow Areas/{AREA}/Maximum Water Surface",
        lambda v: v.shape,
        lambda hdf, path: hdf.HdfResultsMesh.get_mesh_max_ws(path),
    ),
    "get_mesh_timeseries": (
        f"{BASE}/Unsteady Time Series/2D Flow Areas/{AREA}/Water Surface",
        lambda v: (min(16, v.shape[0]), v.shape[1]),
        lambda hdf, path: hdf.HdfResultsMesh.get_mesh_timeseries(path, AREA, "Water Surface"),
    ),
    # review-r2: exception types (h5py ValueError/OSError) and partial results.
    "get_mesh_summary[MaxWS]": (
        f"{BASE}/Summary Output/2D Flow Areas/{AREA}/Maximum Water Surface",
        lambda v: v.shape,
        lambda hdf, path: hdf.HdfResultsMesh.get_mesh_summary(path, "Maximum Water Surface"),
    ),
    "get_mesh_summary_values[MaxWS]": (
        f"{BASE}/Summary Output/2D Flow Areas/{AREA}/Maximum Water Surface",
        lambda v: v.shape,
        lambda hdf, path: hdf.HdfResultsMesh.get_mesh_summary_values(path, "Maximum Water Surface"),
    ),
    "get_mesh_cells_timeseries[partial]": (
        f"{BASE}/Unsteady Time Series/2D Flow Areas/{AREA}/Water Surface",
        lambda v: (min(16, v.shape[0]), v.shape[1]),
        lambda hdf, path: hdf.HdfResultsMesh.get_mesh_cells_timeseries(path),
    ),
    "get_mesh_faces_timeseries[partial]": (
        f"{BASE}/Unsteady Time Series/2D Flow Areas/{AREA}/Face Velocity",
        lambda v: (min(16, v.shape[0]), v.shape[1]),
        lambda hdf, path: hdf.HdfResultsMesh.get_mesh_faces_timeseries(path, AREA),
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_results_mesh_checksum_damage(case, tmp_path, monkeypatch):
    from ras_commander import fast_hdf, hdf
    key, chunks, method = CASES[case]
    source = _fixture("AustinOyster.p01")
    copy = tmp_path / f"{case}.p01.hdf"
    offset = _fletcher32_copy(source, copy, key, chunks)
    call = lambda: method(hdf, copy)

    clean, clean_trace, _ = _outcome(monkeypatch, "required", call)
    assert clean[0] == "ok", clean[:3]
    served = [r for r in clean_trace if r["path"] == "/" + key]
    assert served and all(r["backend"].startswith("native") for r in served), served

    _flip(copy, offset)
    py, _, _ = _outcome(monkeypatch, "0", call)
    auto, auto_trace, _ = _outcome(monkeypatch, "auto", call)
    req, _, _ = _outcome(monkeypatch, "required", call)
    if case.endswith("[partial]"):
        # h5py drops the damaged variable and returns the rest: a successful
        # partial result that auto must reproduce exactly.
        assert py[0] == "ok", py[:3]
    _same(py, auto, f"{case}: auto keeps the h5py outcome on checksum damage")
    assert any(r["path"] == "/" + key and r["backend"] == "h5py-fallback" for r in auto_trace), auto_trace
    assert req[0] == "raise" and req[1] is fast_hdf.FastHdfError, req[:3]
