"""Native/auto vs Python parity under permuted cell-polygon presentations (#572).

The Python reference is order-invariant: it depends only on stored mesh and
results, never on cell-polygon row order, ring direction or ring start vertex.
The native engine never reads the polygon frame, so for every presentation
engine="native" must equal engine="h5py" (the reference) exactly (same rows, attributes,
topologically equal polygons; row-wise identical boundary lines) or raise
FluvialNativeUnsupportedError, and engine="auto" must equal the reference.

Fixture: BaldEagleDamBrk.p18.hdf under RAS_FLUVIAL_PUBLIC_FIXTURES (two meshes,
4425 cells, conflicting seeds at delta_t=1 and 12). Missing fixture skips.
"""
import importlib
import os
from pathlib import Path

import numpy as np
import pytest
import shapely

pytest.importorskip("ras_commander_fast_hdf")
module = importlib.import_module("ras_commander.hdf.HdfFluvialPluvial")
from ras_commander.hdf import HdfMesh  # noqa: E402
from ras_commander.hdf.HdfFluvialPluvial import (  # noqa: E402
    FluvialNativeUnsupportedError,
    HdfFluvialPluvial,
)

FIXTURES = Path(os.environ.get("RAS_FLUVIAL_PUBLIC_FIXTURES", "missing"))


@pytest.fixture(scope="module", autouse=True)
def _default_backend_policy():
    """Pin RAS_COMMANDER_FAST_HDF=auto for this native-engine qualification module.

    engine="auto" follows the backend policy (API re-audit P2-N3): it runs the
    h5py reference under ``h5py`` and raises FastHdfError instead of falling back
    under ``native``. These tests qualify native/auto parity under the default
    policy; tests/test_fluvial_engine_policy.py covers the other policies.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
        yield
PRESENTATIONS = ["original", "rows_reversed", "rows_shuffled", "rings_reversed", "rings_rotated"]


@pytest.fixture(scope="module")
def hdf():
    path = FIXTURES / "BaldEagleDamBrk.p18.hdf"
    if not path.exists():
        pytest.skip(f"fixture unavailable: {path}")
    return path


@pytest.fixture(scope="module")
def cells(hdf):
    frame = HdfMesh.get_mesh_cell_polygons(hdf)
    frame.attrs = {}
    return frame


def present(cells, how):
    if how == "original":
        return cells.copy()
    if how == "rows_reversed":
        return cells.iloc[::-1].reset_index(drop=True)
    if how == "rows_shuffled":
        return cells.sample(frac=1.0, random_state=572).reset_index(drop=True)
    out = cells.copy()
    if how == "rings_reversed":
        out["geometry"] = shapely.reverse(cells.geometry.values)
        return out
    if how == "rings_rotated":
        rotated = []
        for geom in cells.geometry.values:
            ring = np.asarray(geom.exterior.coords)[:-1]
            ring = np.vstack([ring[1:], ring[:1], ring[1:2]])
            rotated.append(shapely.polygons(ring))
        out["geometry"] = rotated
        return out
    raise ValueError(how)


def run(kind, hdf, frame, engine, **kwargs):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module.HdfMesh, "get_mesh_cell_polygons", staticmethod(lambda *a, **k: frame.copy()))
        if kind == "polygons":
            return HdfFluvialPluvial.generate_fluvial_pluvial_polygons(hdf, engine=engine, **kwargs)
        return HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(hdf, engine=engine, **kwargs)


def assert_polygons_equal(actual, expected):
    assert not expected.empty
    assert list(actual.columns) == list(expected.columns)
    assert actual.crs == expected.crs
    assert list(zip(actual.mesh_name, actual.classification, actual.cell_id)) == list(
        zip(expected.mesh_name, expected.classification, expected.cell_id))
    for a, b in zip(actual.geometry, expected.geometry):
        assert a.equals(b), a.symmetric_difference(b).area


def assert_lines_equal(actual, expected):
    assert not expected.empty
    assert actual.crs == expected.crs and len(actual) == len(expected)
    assert all(a.equals_exact(b, 0) for a, b in zip(actual.geometry, expected.geometry))


@pytest.fixture(scope="module")
def baselines(hdf, cells):
    return {(kind, dt): run(kind, hdf, cells, "h5py", delta_t=dt)
            for kind in ("polygons", "boundary") for dt in (1, 12)}


@pytest.mark.parametrize("delta_t", [1, 12])
@pytest.mark.parametrize("how", PRESENTATIONS)
def test_polygons_native_and_auto_equal_python_for_any_presentation(hdf, cells, baselines, how, delta_t):
    frame = present(cells, how)
    reference = baselines[("polygons", delta_t)]
    python = run("polygons", hdf, frame, "h5py", delta_t=delta_t)
    assert_polygons_equal(python, reference)
    native = run("polygons", hdf, frame, "native", delta_t=delta_t, diagnostics=True)
    assert native.attrs["fluvial_engine"]["used"] == "native"
    # Conflicting seeds are present, so the set-based (ambiguous) rule is exercised.
    assert native.attrs["fluvial_native"]["classification"]["conflicting_seeds"] > 0
    assert_polygons_equal(native, python)
    auto = run("polygons", hdf, frame, "auto", delta_t=delta_t)
    assert auto.attrs["fluvial_engine"] == {"requested": "auto", "used": "native", "fallback_reason": None}
    assert_polygons_equal(auto, python)


@pytest.mark.parametrize("delta_t", [1, 12])
@pytest.mark.parametrize("how", PRESENTATIONS)
def test_boundary_native_and_auto_equal_python_for_any_presentation(hdf, cells, baselines, how, delta_t):
    frame = present(cells, how)
    reference = baselines[("boundary", delta_t)]
    python = run("boundary", hdf, frame, "h5py", delta_t=delta_t)
    assert_lines_equal(python, reference)
    for engine in ("native", "auto"):
        result = run("boundary", hdf, frame, engine, delta_t=delta_t)
        assert result.attrs["fluvial_engine"]["used"] == "native"
        assert_lines_equal(result, python)


def test_delta_t_zero_native_raises_auto_equals_python(hdf, cells):
    """Equal-time pairs: Python seeds nothing; the native kernel cannot, so it refuses."""
    frame = present(cells, "rows_shuffled")
    with pytest.raises(FluvialNativeUnsupportedError, match="delta_t=0"):
        run("polygons", hdf, frame, "native", delta_t=0)
    python = run("polygons", hdf, frame, "h5py", delta_t=0)
    auto = run("polygons", hdf, frame, "auto", delta_t=0)
    assert auto.attrs["fluvial_engine"]["used"] == "h5py"
    assert_polygons_equal(auto, python)
