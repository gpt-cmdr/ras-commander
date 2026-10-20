"""PERF-3 public geometry exactness on real read-only files."""
import json,os
from pathlib import Path
import h5py,numpy as np,pytest
from shapely import points,to_wkb
from shapely.geometry import Point
from ras_commander import HdfMesh

@pytest.mark.parametrize("coords",[np.empty((0,2)),np.array([[1.,-0.],[np.nan,2.],[np.nan,np.nan]]),np.array([[1.,2.,3.]])])
def test_vector_points_keep_scalar_point_wkb(coords):
    assert list(to_wkb(points(coords)))==[Point(row).wkb for row in coords]

@pytest.mark.parametrize("ghosts",[True,False])
def test_real_cell_point_order_ids_and_wkb(ghosts):
    manifest=os.environ.get("RAS_FIM_WAVE1_FIXTURES")
    if not manifest:pytest.skip("RAS_FIM_WAVE1_FIXTURES required for real geometry regression")
    path=next(Path(x["path"]) for x in json.loads(Path(manifest).read_text()) if "Austin" in x["path"])
    expected=[]
    with h5py.File(path,"r") as f:
        counts={} if ghosts else HdfMesh._physical_cell_counts(f)
        for area in HdfMesh.get_mesh_area_names(path):
            xy=f[f"Geometry/2D Flow Areas/{area}/Cells Center Coordinate"][()]
            if area in counts:xy=xy[:counts[area]]
            expected.extend((area,i,Point(row).wkb) for i,row in enumerate(xy))
    got=HdfMesh.get_mesh_cell_points(path,include_ghost_cells=ghosts)
    assert list(zip(got.mesh_name,got.cell_id,got.geometry.to_wkb()))==expected


def _real_fixtures():
    manifest = os.environ.get("RAS_FIM_WAVE1_FIXTURES")
    if not manifest:
        return [pytest.param(None, marks=pytest.mark.skip(reason="RAS_FIM_WAVE1_FIXTURES required for complete GeoDataFrame parity"))]
    return [pytest.param(Path(item["path"]), id=Path(item["path"]).name)
            for item in json.loads(Path(manifest).read_text())]


@pytest.mark.parametrize("path", _real_fixtures())
@pytest.mark.parametrize("ghosts", [True, False])
def test_complete_cell_points_frame_matches_previous_h5py_in_both_backends(path, ghosts, monkeypatch):
    """Compare all frame metadata and bytes, including the h5py-only fallback."""
    import importlib.util
    import pandas as pd
    from geopandas.testing import assert_geodataframe_equal
    from ras_commander import fast_hdf

    reference = Path(__file__).with_name("_perf3_cell_points_before.py")
    spec = importlib.util.spec_from_file_location("perf3_previous_cell_points", reference)
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    monkeypatch.setenv("RAS_COMMANDER_HDF_SESSION_CACHE", "1")
    fast_hdf.close_sessions()
    try:
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "python")
        expected = previous.previous_cell_points(path, include_ghost_cells=ghosts)
        assert len(expected) > 0, "real reference must not silently return an empty frame"
        assert not fast_hdf._sessions, "reference must use h5py-only numeric reads"
        for backend in ("python", "rust"):
            fast_hdf.close_sessions()
            monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", backend)
            with fast_hdf.trace_reads() as trace:
                actual = HdfMesh.get_mesh_cell_points(path, include_ghost_cells=ghosts)
            # PY-ROUTE-1: cell centers come from the typed engine reader (path-level
            # binding, no cached HdfSession), so execution is proven by the read trace.
            native = any(r["backend"] == "native-typed" and r["path"].endswith("/Cells Center Coordinate")
                         for r in trace)
            assert native == (backend == "rust"), "required backend must actually execute"
            assert all(r["backend"] == "h5py" for r in trace) == (backend == "python")
            assert_geodataframe_equal(actual, expected, check_dtype=True,
                                      check_index_type="exact", check_column_type="exact",
                                      check_frame_type=True, check_like=False,
                                      check_geom_type=True, check_crs=True, normalize=False)
            pd.testing.assert_frame_equal(actual.drop(columns=actual.geometry.name),
                                          expected.drop(columns=expected.geometry.name),
                                          check_dtype=True, check_exact=True,
                                          check_index_type="exact", check_column_type="exact")
            pd.testing.assert_series_equal(actual.dtypes, expected.dtypes, check_exact=True)
            pd.testing.assert_index_equal(actual.index, expected.index, exact=True)
            pd.testing.assert_index_equal(actual.columns, expected.columns, exact=True)
            assert actual.geometry.name == expected.geometry.name
            assert actual.attrs == expected.attrs
            assert type(actual.crs) is type(expected.crs)
            assert actual.crs == expected.crs
            if expected.crs is not None:
                assert actual.crs.to_wkt() == expected.crs.to_wkt()
            assert list(actual.geometry.to_wkb()) == list(expected.geometry.to_wkb())
    finally:
        fast_hdf.close_sessions()
