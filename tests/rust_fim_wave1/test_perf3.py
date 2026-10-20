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
