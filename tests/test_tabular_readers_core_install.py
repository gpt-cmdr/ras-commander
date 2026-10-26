"""Typed tabular HDF readers under the core install (no geo stack).

``include_geometry=False`` readers and the modules that host them must work
with only h5py/numpy/pandas. A meta-path blocker in a subprocess hides
GeoPandas, Shapely, pyproj and the other optional packages, as in
``test_compute_extra_results_imports.py``. The same synthetic HDF is then read
with the geo stack present to check that the tables equal the default
GeoDataFrames without geometry, with stored dtypes kept.
"""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

h5py = pytest.importorskip("h5py")

REPO_ROOT = Path(__file__).resolve().parents[1]

_BLOCKER = r"""
import importlib.abc
import sys

forbidden = {
    "geopandas", "rasterio", "matplotlib", "scipy", "xarray", "shapely",
    "pyarrow", "pyproj", "rasterstats", "rtree", "requests", "tqdm",
    "hms_commander",
}

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in forbidden:
            raise ModuleNotFoundError(f"No module named {fullname!r}")
        return None

sys.meta_path.insert(0, Blocker())
"""

_SUMMARY = (
    "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/"
    "2D Flow Areas/Mesh A"
)
_TS = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
_BED = (
    "Results/Unsteady/Output/Output Blocks/Sediment Bed/"
    "Unsteady Time Series"
)

_READERS = r"""
import json
from ras_commander import HdfMesh, HdfPump, HdfResultsMesh, HdfResultsSediment

def readers(hdf, **kw):
    return {
        "max_ws": lambda: HdfResultsMesh.get_mesh_max_ws(hdf, **kw),
        "max_face_v": lambda: HdfResultsMesh.get_mesh_max_face_v(hdf, **kw),
        "max_iter": lambda: HdfResultsMesh.get_mesh_max_iter(hdf, **kw),
        "max_depth": lambda: HdfResultsMesh.get_mesh_max_depth(hdf, **kw),
        "cell_points": lambda: HdfMesh.get_mesh_cell_points(hdf, **kw),
        "bed_change": lambda: HdfResultsSediment.get_cell_bed_change(
            hdf, unit_system="US Customary", **kw),
        "d50": lambda: HdfResultsSediment.get_active_layer_grain_class(hdf, **kw),
        "pumps": lambda: HdfPump.get_pump_stations(hdf, **kw),
    }
"""


def _write_hdf(path: Path) -> Path:
    """Plan-like HDF: one mesh of 3 physical + 1 ghost cell, 2 faces, 1 pump."""
    mesh_attrs = np.array(
        [(b"Mesh A", 3)], dtype=np.dtype([("Name", "S16"), ("Cell Count", "i4")])
    )
    centers = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.5], [3.0, 0.5]])
    pump_attrs = np.array(
        [(b"Pump A", 2)], dtype=np.dtype([("Name", "S16"), ("Pump Groups", "i4")])
    )
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Units System"] = np.bytes_("US Customary")
        geom = hdf.create_group("Geometry")
        geom.attrs["SI Units"] = np.bytes_("False")
        info = hdf.create_group("Plan Data/Plan Information")
        info.attrs["Simulation Start Time"] = np.bytes_("01Jan2000 00:00:00")
        hdf.create_dataset("Geometry/2D Flow Areas/Attributes", data=mesh_attrs)
        mesh = hdf.create_group("Geometry/2D Flow Areas/Mesh A")
        mesh.create_dataset("Cells Center Coordinate", data=centers)
        mesh.create_dataset(
            "Cells Surface Area", data=np.array([10, 20, 30, 0], dtype="f4")
        )
        mesh.create_dataset(
            "Cells Minimum Elevation",
            data=np.array([5.0, 6.0, 7.0, np.nan], dtype="f4"),
        )
        hdf.create_dataset(
            f"{_SUMMARY}/Maximum Water Surface",
            data=np.array(
                [[10.0, 11.5, 12.0, 0.0], [0.25, 0.5, 0.75, 0.0]], dtype="f4"
            ),
        )
        hdf.create_dataset(
            f"{_SUMMARY}/Maximum Face Velocity",
            data=np.array([[1.5, -2.0], [0.5, 0.75]], dtype="f4"),
        )
        hdf.create_dataset(
            f"{_SUMMARY}/Cell Last Iteration",
            data=np.array([3, 4, 5, 0], dtype="i4"),
        )
        hdf.create_dataset(f"{_TS}/Time", data=np.array([0.0, 1 / 24]))
        hdf.create_dataset(
            f"{_TS}/Time Date Stamp (ms)",
            data=np.array([b"01Jan2000 00:00:00:000", b"01Jan2000 01:00:00:000"]),
        )
        hdf.create_dataset(
            f"{_TS}/2D Flow Areas/Mesh A/Water Surface",
            data=np.array(
                [[6.0, 7.0, 8.0, 0.0], [10.0, 11.5, 12.0, 0.0]], dtype="f4"
            ),
        )
        bed = hdf.create_group(f"{_BED}/2D Flow Areas/Mesh A")
        bed.create_dataset(
            "Cell Bed Change",
            data=np.array([[0, 0, 0, 0], [-1.0, 2.0, -0.5, 9.0]], dtype="f4"),
        )
        d50 = bed.create_dataset(
            "Cell Active Layer Percentile Diameters - D50",
            data=np.array([[2.0] * 4, [2.5, 3.0, 4.0, 0.0]], dtype="f4"),
        )
        d50.attrs["Units"] = np.bytes_("mm")
        hdf.create_dataset(f"{_BED}/Time", data=np.array([0.0, 1.0]))
        pumps = hdf.create_group("Geometry/Pump Stations")
        pumps.create_dataset("Attributes", data=pump_attrs)
        pumps.create_dataset("Points", data=np.array([[100.0, 200.0]]))
    return path


def _run_core_only(body: str, *args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-c", _BLOCKER + body, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_geo_modules_import_without_geo_stack():
    payload = _run_core_only(r"""
import json
import ras_commander.hdf
from ras_commander.hdf import (
    HdfBndry, HdfProject, HdfResultsBreach, HdfStorageArea, HdfStruc, HdfXsec,
)
loaded = sorted(n for n in ("geopandas", "shapely", "pyproj") if n in sys.modules)
print(json.dumps({"loaded": loaded, "names": [
    HdfBndry.__name__, HdfXsec.__name__, HdfStruc.__name__,
    HdfStorageArea.__name__, HdfProject.__name__, HdfResultsBreach.__name__,
]}))
""")
    assert payload == {
        "loaded": [],
        "names": [
            "HdfBndry", "HdfXsec", "HdfStruc", "HdfStorageArea", "HdfProject",
            "HdfResultsBreach",
        ],
    }


def test_breach_reader_runs_without_geo_stack(tmp_path):
    hdf_path = _write_hdf(tmp_path / "Synthetic.p01.hdf")
    payload = _run_core_only(r"""
import json
from ras_commander import HdfResultsBreach, HdfStruc
info = HdfStruc.get_sa2d_breach_info(sys.argv[1])
variables = HdfResultsBreach.get_breaching_variables(sys.argv[1])
print(json.dumps({"info": type(info).__name__, "info_rows": len(info),
                  "variables": type(variables).__name__, "rows": len(variables)}))
""", str(hdf_path))
    assert payload == {
        "info": "DataFrame", "info_rows": 0, "variables": "DataFrame", "rows": 0,
    }


def test_tabular_readers_without_geo_stack_match_default(tmp_path):
    hdf_path = _write_hdf(tmp_path / "Synthetic.p01.hdf")
    core = _run_core_only(_READERS + r"""
out = {}
for label, call in readers(sys.argv[1], include_geometry=False).items():
    frame = call()
    out[label] = {
        "type": type(frame).__name__,
        "dtypes": {c: str(t) for c, t in frame.dtypes.items()},
        "columns": list(frame.columns),
        "rows": len(frame),
    }
print(json.dumps(out))
""", str(hdf_path))

    for label, result in core.items():
        assert result["type"] == "DataFrame", label
        assert "geometry" not in result["columns"], label
        assert "object" not in result["dtypes"].values(), (label, result["dtypes"])
    # Stored dtypes are kept: float32 values, int32 iterations, int64 keys.
    for label, column in (
        ("max_ws", "maximum_water_surface"), ("max_face_v", "maximum_face_velocity"),
        ("max_depth", "maximum_depth"), ("bed_change", "bed_change"),
        ("d50", "d50_mm"),
    ):
        assert core[label]["dtypes"][column] == "float32", (label, core[label])
    assert core["max_iter"]["dtypes"]["cell_last_iteration"] == "int32"
    assert core["max_ws"]["dtypes"]["cell_id"] == "int64"
    assert core["max_face_v"]["dtypes"]["face_id"] == "int64"
    assert core["cell_points"]["columns"] == ["mesh_name", "cell_id", "x", "y"]
    assert core["max_ws"]["rows"] == 3  # the ghost cell is dropped by default
    assert core["cell_points"]["rows"] == 4  # ghosts are kept by default
    assert core["pumps"]["columns"] == ["station_id", "Name", "Pump Groups", "x", "y"]


def test_tables_equal_default_frames_without_geometry(tmp_path):
    pytest.importorskip("geopandas")
    namespace = {}
    exec(_READERS, namespace)

    hdf_path = _write_hdf(tmp_path / "Synthetic.p01.hdf")
    defaults = namespace["readers"](hdf_path)
    tables = namespace["readers"](hdf_path, include_geometry=False)
    for label, default_call in defaults.items():
        gdf, table = default_call(), tables[label]()
        assert type(table) is pd.DataFrame, label
        expected = pd.DataFrame(gdf.drop(columns="geometry"))
        if label in ("cell_points", "pumps"):
            expected["x"] = gdf.geometry.x.to_numpy()
            expected["y"] = gdf.geometry.y.to_numpy()
        # The table keeps stored dtypes where the GeoDataFrame may cast.
        expected = expected.astype(table.dtypes.to_dict())
        pd.testing.assert_frame_equal(table, expected, check_exact=True, obj=label)
        assert table.attrs == gdf.attrs, label
        assert np.array_equal(
            table.drop(columns=["x", "y"], errors="ignore").select_dtypes("number"),
            pd.DataFrame(gdf.drop(columns="geometry")).select_dtypes("number"),
        ), label
