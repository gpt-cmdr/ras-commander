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


def main():
    engine = shutil.which("ras2fim-batch")
    assert engine, "wheel did not install ras2fim-batch on PATH"
    method = json.loads(subprocess.check_output([engine, "method"], text=True))
    assert "step05_r2" in method
    with tempfile.TemporaryDirectory(prefix="ras2fim-wheel-") as tmp:
        root = Path(tmp)
        terrain = root / "terrain.tif"
        with rasterio.open(terrain, "w", driver="GTiff", width=8, height=8,
                           count=1, dtype="float32", crs="EPSG:3857",
                           transform=Affine(1, 0, 0, 0, -1, 8)) as ds:
            ds.write(np.full((8, 8), 100, dtype=np.float32), 1)
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
