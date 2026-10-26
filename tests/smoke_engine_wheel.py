"""Exercise an installed platform wheel with a small real GeoTIFF and Step05 request.

Synthetic packaging smoke test; not real-model numerical qualification.
Run explicitly: python tests/smoke_engine_wheel.py.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
import rasterio
from affine import Affine

from scipy.spatial import Delaunay


def sloping_smoke(engine, root, terrain):
    """Packaging smoke: typed geometry, two profiles, native ownership and AOI."""
    import io
    import struct
    folder=root/"sloping-inputs";folder.mkdir()
    tables={
        "centers":([[2,2],[-1,2],[2,5],[5,2],[2,-1]],"<f8"),
        "cell_info":([[0,4],[4,1],[5,1],[6,1],[7,1]],"<i4"),
        "cell_faces":([[0,1],[1,1],[2,1],[3,1],[0,-1],[1,-1],[2,-1],[3,-1]],"<i4"),
        "cell_minimum":([100,0,0,0,0],"<f4"),
        "face_vertices":([[0,1],[1,2],[2,3],[3,0]],"<i4"),
        "face_cells":([[0,1],[0,2],[0,3],[0,4]],"<i4"),
        "face_info":(np.zeros((4,2)),"<i4"),
        "face_points":(np.empty((0,2)),"<f8"),
        "face_minimum":([100]*4,"<f4"),
        "vertices":([[0,0],[0,4],[4,4],[4,0]],"<f8"),
        "vertex_info":([[0,2],[2,2],[4,2],[6,2]],"<i4"),
        "vertex_faces":([[3,1],[0,1],[0,1],[1,1],[1,1],[2,1],[2,1],[3,1]],"<i4"),
    }
    descriptors={}
    for key,(data,dtype) in tables.items():
        array=np.asarray(data,dtype=dtype);filename=f"{key}.bin";array.tofile(folder/filename)
        descriptors[key]={"path":filename,"rows":len(array)}
    (folder/"mesh.json").write_text(json.dumps({"schema":"ras-commander-sloping-mesh/1","arrays":descriptors}))
    def polygon(filename,points):
        wkb=struct.pack("<BIII",1,3,1,len(points))+np.asarray(points,dtype="<f8").tobytes()
        (folder/filename).write_bytes(struct.pack("<I",len(wkb))+wkb)
    polygon("cell.wkb",[[0,0],[0,4],[4,4],[4,0],[0,0]])
    polygon("aoi.wkb",[[0,0],[0,4],[2,4],[2,0],[0,0]])
    for name,value in [("a",101),("b",102)]:np.array([value,0,0,0,0],dtype="<f4").tofile(folder/f"{name}.bin")
    request=dict(schema="ras-commander-sloping-request/1",terrain=str(terrain),epsg=3857,
        crs_identity={"kind":"epsg"},terrain_transform=[0.,1.,0.,8.,0.,-1.],window=[0,4,4,4],
        geometry_file="cell.wkb",mesh_files=["mesh.json"],owner_cells=[[0,0]],
        profiles=[dict(id=name,values_files=[f"{name}.bin"]) for name in ["a","b"]],
        threads=4,max_working_bytes=256<<20)
    path=folder/"request.json";path.write_text(json.dumps(request))
    subprocess.run([engine,"sloping",str(path),str(folder/"files")],check=True,capture_output=True)
    for name,value in [("a",1),("b",2)]:
        actual=np.fromfile(folder/"files"/name/"depth.bin",dtype="<f4")
        np.testing.assert_array_equal(actual,np.full(16,value,dtype="<f4"))
    request.update(stream_outputs=True,aoi_file="aoi.wkb",threads=1)
    path.write_text(json.dumps(request))
    output=subprocess.run([engine,"sloping",str(path),str(folder/"stream")],check=True,capture_output=True).stdout
    stream=io.BytesIO(output)
    for name,value in [("a",1),("b",2)]:
        assert json.loads(stream.readline())==dict(id=name,status="complete",pixels=16)
        for band,level in [("depth",value),("wse",100+value)]:
            actual=np.frombuffer(stream.read(64),dtype="<f4").reshape(4,4)
            expected=np.full((4,4),level,dtype="<f4");expected[:,2:]=np.nan
            np.testing.assert_array_equal(actual,expected,err_msg=band)
    assert not stream.read()
    print("Installed wheel: plain sloping binary geometry, profiles, file/stream AOI PASS")


def main():
    engine = shutil.which("ras2fim-batch")
    assert engine, "wheel did not install ras2fim-batch on PATH"
    method = json.loads(subprocess.check_output([engine, "method"], text=True))
    assert "step05_r2" in method
    assert method["horizontal"]["method_id"] == "horizontal-cell-constant/1"
    assert method["sloping"]["method_id"] == "rasmapper-plain-sloping/1"
    with tempfile.TemporaryDirectory(prefix="ras2fim-wheel-") as tmp:
        root = Path(tmp)
        terrain = root / "terrain.tif"
        with rasterio.open(terrain, "w", driver="GTiff", width=8, height=8,
                           count=1, dtype="float32", crs="EPSG:3857",
                           transform=Affine(1, 0, 0, 0, -1, 8), nodata=-9999) as ds:
            ds.write(np.full((8, 8), 100, dtype=np.float32), 1)
        sloping_smoke(engine,root,terrain)
        ownership=np.tile(np.array([1,1,1,2,2,0],dtype="<u4"),(4,1))
        ownership.tofile(root/"owner.bin")
        np.array([100.5,102.],dtype="<f4").tofile(root/"a.bin")
        np.array([103.,np.nan],dtype="<f4").tofile(root/"b.bin")
        request={"schema":"ras2fim-horizontal-request/1","terrain":str(terrain),"epsg":3857,
                 "crs_identity":{"kind":"epsg"},"terrain_transform":[0.,1.,0.,8.,0.,-1.],
                 "window":[1,2,6,4],"owner_file":"owner.bin","cell_count":2,
                 "profiles":[{"id":"a","values_file":"a.bin"},{"id":"b","values_file":"b.bin"}],
                 "min_depth":0.5,"threads":2,"max_working_bytes":256<<20}
        (root/"horizontal.json").write_text(json.dumps(request))
        subprocess.run([engine,"horizontal",str(root/"horizontal.json"),str(root/"horizontal")],check=True)
        report=json.loads((root/"horizontal/report.json").read_text())
        assert report["status"]=="complete" and len(report["profiles"])==2
        for name,values in [("a",np.array([np.nan,100.5,102.],dtype="float32")),
                            ("b",np.array([np.nan,103.,np.nan],dtype="float32"))]:
            expected=values[ownership]-np.float32(100.)
            expected[~(expected>0.5)]=np.nan
            actual=np.fromfile(root/"horizontal"/name/"depth.bin",dtype="<f4").reshape(4,6)
            np.testing.assert_array_equal(actual,expected)
        request["stream_outputs"]=True
        (root/"stream.json").write_text(json.dumps(request))
        streamed=subprocess.run([engine,"horizontal",str(root/"stream.json"),str(root/"stream")],check=True,capture_output=True).stdout
        import io
        pipe=io.BytesIO(streamed)
        for name in ("a","b"):
            header=json.loads(pipe.readline())
            assert header=={"id":name,"status":"complete","pixels":24}
            for product in ("depth","wse"):
                data=np.frombuffer(pipe.read(24*4),dtype="<f4")
                expected=np.fromfile(root/"horizontal"/name/f"{product}.bin",dtype="<f4")
                np.testing.assert_array_equal(data.view("<u4"),expected.view("<u4"))
        assert not pipe.read()
        assert not list((root/"stream").rglob("*.bin"))
        inputs = root / "inputs"
        inputs.mkdir()
        samples = np.array([[0., 0., 105.], [7., 0., 105.],
                            [0., 7., 105.], [7., 7., 105.]])
        tri = Delaunay(samples[:, :2])
        arrays = {"samples": (samples, "<f8"), "simplices": (tri.simplices, "<u4"),
                  "transform": (tri.transform, "<f8"), "neighbors": (tri.neighbors, "<i4"),
                  "equations": (tri.equations, "<f8"),
                  "x_axis": (np.arange(1., 4.), "<f8"),
                  "y_axis": (np.arange(1., 4.), "<f8"),
                  "wet_mask": (np.ones((3, 3)), "u1")}
        files = {}
        for name, (values, dtype) in arrays.items():
            arr = np.ascontiguousarray(values, dtype=dtype)
            filename = name + ".bin"
            arr.tofile(inputs / filename)
            files[name] = {"file": filename, "dtype": arr.dtype.str, "shape": list(arr.shape)}
        meta = {"schema": "ras2fim-step05-inputs/1", "rows": 3, "cols": 3,
                "raster_affine": {"x0": 1., "y0": 1., "res_x": 1., "res_y": 1.},
                "delaunay": {"paraboloid_scale": tri.paraboloid_scale,
                             "paraboloid_shift": tri.paraboloid_shift,
                             "min_bound": tri.min_bound.tolist(),
                             "max_bound": tri.max_bound.tolist(), "nsimplex": tri.nsimplex},
                "files": files}
        (inputs / "inputs.json").write_text(json.dumps(meta))
        mask = root / "mask.u8"
        mask.write_bytes(bytes([1, 0, 1, 1]))
        aois = [{"id": "full"}, {"id": "bbox", "window": [1, 1, 2, 2]},
                {"id": "polygon", "window": [1, 1, 2, 2], "mask_u8": str(mask)}]
        request = {"schema": "ras2fim-step05-request/1",
                   "terrain": {"path": str(terrain), "epsg": 3857,
                               "crs_identity": {"kind": "epsg"}},
                   "source_crs": {"kind": "terrain"},
                   "budgets": {"threads": 2, "max_cache_bytes": 4 << 20,
                               "max_profile_bytes": 128 << 20, "max_inflight_profiles": 2},
                   "interpolation": {"selection": "auto"},
                   "nudge": {"dst_epsg": 3857, "error_threshold": 0.125,
                             "memory_limit_bytes": 67108864., "method": "lookup"},
                   "profiles": [{"id": name, "inputs_dir": str(inputs),
                                 "dest_grid": {"geotransform": [1., 1., 0., 4., 0., -1.],
                                               "width": 3, "height": 3}, "aois": aois}
                                for name in ["wsel_a", "wsel_b"]]}
        rp = root / "request.json"
        rp.write_text(json.dumps(request))
        out = root / "out"
        result = subprocess.run([engine, "step05", str(rp), str(out)])
        if result.returncode:
            raise AssertionError((out / "report.json").read_text())
        report = json.loads((out / "report.json").read_text())
        assert report["status"] == "complete", report
        for name in ["wsel_a", "wsel_b"]:
            for product, expected in [("depth.f32", 5.), ("wse.f32", 105.)]:
                base = out / "units" / name
                full = np.fromfile(base / "full" / product, dtype="<f4").reshape(3, 3)
                np.testing.assert_array_equal(full, np.full((3, 3), expected))
                for aoi in ["bbox", "polygon"]:
                    got = np.fromfile(base / aoi / product, dtype="<f4").reshape(2, 2)
                    want = full[1:3, 1:3].copy()
                    if aoi == "polygon":
                        want[0, 1] = np.nan
                    np.testing.assert_array_equal(got, want)
        print("Installed wheel: Step05 shared-terrain batch, bbox and polygon mask PASS")


if __name__ == "__main__":
    main()
