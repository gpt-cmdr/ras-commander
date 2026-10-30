"""HDF result modules under the core and ``compute`` installs.

The ``compute`` extra adds only process-supervision packages to the core
h5py/numpy/pandas install. These tests block the optional packages in a
subprocess to emulate that install. The result modules must import, the
geometry-free paths must work, and xarray or GeoDataFrame paths must raise an
``ImportError`` that names the exact install command.
"""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FULL_EXTRA = 'pip install "ras-commander[full]"'

_BLOCKER = r'''
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
'''

_TS = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
_SUMMARY = (
    "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/"
    "2D Flow Areas"
)


def _run_core_only(body: str, *args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-c", _BLOCKER + body, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _write_results_hdf(path: Path) -> Path:
    """Write a synthetic plan-results HDF with 1D and 2D result datasets."""
    import h5py

    xs_attrs = np.array(
        [(b"River A", b"Reach 1", b"100", b"XS 100"),
         (b"River A", b"Reach 1", b"200", b"XS 200")],
        dtype=np.dtype([
            ("River", "S16"), ("Reach", "S16"), ("Station", "S8"), ("Name", "S8"),
        ]),
    )
    series = np.array([[1.0, 2.0], [3.0, 5.0], [2.0, 4.0]])
    mesh_attrs = np.array([(b"Mesh A",)], dtype=np.dtype([("Name", "S16")]))
    max_ws = np.array([[10.0, 11.5, 12.0], [0.25, 0.5, 0.75]])

    with h5py.File(path, "w") as hdf:
        info = hdf.create_group("Plan Data/Plan Information")
        info.attrs["Simulation Start Time"] = b"01Jan2000 00:00:00"
        hdf.create_dataset("Geometry/2D Flow Areas/Attributes", data=mesh_attrs)
        # Mesh series readers check the series width against the cell count.
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Mesh A/Cells Center Coordinate",
            data=np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]),
        )
        hdf.create_dataset(
            f"{_SUMMARY}/Mesh A/Maximum Water Surface", data=max_ws
        )
        hdf.create_dataset(
            f"{_TS}/Time Date Stamp (ms)",
            data=np.array([
                b"01Jan2000 00:00:00:000",
                b"01Jan2000 01:00:00:000",
                b"01Jan2000 02:00:00:000",
            ]),
        )
        hdf.create_dataset(
            f"{_TS}/2D Flow Areas/Mesh A/Water Surface",
            data=np.array([[10.0, 11.0, 11.5], [10.0, 11.5, 12.0], [9.5, 11.0, 11.0]]),
        )
        hdf.create_dataset(f"{_TS}/Time", data=np.array([0.0, 1 / 24, 2 / 24]))
        xs = f"{_TS}/Cross Sections"
        hdf.create_dataset(f"{xs}/Cross Section Attributes", data=xs_attrs)
        hdf.create_dataset(
            f"{xs}/Cross Section Only", data=np.array([b"XS 100", b"XS 200"])
        )
        for name in (
            "Water Surface", "Velocity Total", "Velocity Channel",
            "Flow Lateral", "Flow",
        ):
            hdf.create_dataset(f"{xs}/{name}", data=series)
    return path


def test_result_modules_import_without_optional_packages():
    payload = _run_core_only(r'''
import json
from ras_commander import (
    HdfMesh, HdfPipe, HdfPump, HdfResultView, HdfResultsMesh, HdfResultsPlan,
    HdfResultsXsec,
)
loaded = sorted(
    name for name in ("geopandas", "shapely", "xarray") if name in sys.modules
)
print(json.dumps({"loaded": loaded, "names": [
    HdfResultsMesh.__name__, HdfResultsXsec.__name__, HdfPipe.__name__,
    HdfPump.__name__, HdfResultView.__name__,
]}))
''')

    assert payload == {
        "loaded": [],
        "names": [
            "HdfResultsMesh", "HdfResultsXsec", "HdfPipe", "HdfPump",
            "HdfResultView",
        ],
    }


@pytest.mark.synthetic_hdf_layout
def test_geometry_free_results_and_actionable_errors_without_extras(tmp_path):
    hdf_path = _write_results_hdf(tmp_path / "Synthetic.p01.hdf")

    payload = _run_core_only(
        r'''
import json
from ras_commander import HdfResultsMesh, HdfResultsXsec

hdf = sys.argv[1]
values = HdfResultsMesh.get_mesh_summary_values(hdf, "Maximum Water Surface")

errors = {}
for label, call in (
    ("mesh_max_ws", lambda: HdfResultsMesh.get_mesh_max_ws(hdf)),
    ("mesh_max_depth", lambda: HdfResultsMesh.get_mesh_max_depth(hdf)),
    ("mesh_timeseries", lambda: HdfResultsMesh.get_mesh_timeseries(
        hdf, "Mesh A", "Water Surface")),
    ("xsec_timeseries", lambda: HdfResultsXsec.get_xsec_timeseries(hdf)),
):
    try:
        call()
    except ImportError as exc:
        errors[label] = str(exc)
    except Exception as exc:
        errors[label] = f"WRONG TYPE {type(exc).__name__}: {exc}"
    else:
        errors[label] = None

print(json.dumps({
    "values": values["maximum_water_surface"].tolist(),
    "cells": values["cell_id"].tolist(),
    "errors": errors,
}))
''',
        str(hdf_path),
    )

    assert payload["values"] == [10.0, 11.5, 12.0]
    assert payload["cells"] == [0, 1, 2]
    expected_package = {
        "mesh_max_ws": "geopandas",
        "mesh_max_depth": "geopandas",
        "mesh_timeseries": "xarray",
        "xsec_timeseries": "xarray",
    }
    for label, package in expected_package.items():
        message = payload["errors"][label]
        assert message is not None, label
        assert not message.startswith("WRONG TYPE"), message
        assert f"'{package}'" in message, message
        assert FULL_EXTRA in message, message
        assert f"pip install {package}" in message, message


@pytest.mark.synthetic_hdf_layout
def test_xsec_timeseries_unchanged_with_xarray(tmp_path):
    pytest.importorskip("xarray")
    from ras_commander import HdfResultsXsec

    hdf_path = _write_results_hdf(tmp_path / "Synthetic.p01.hdf")
    ds = HdfResultsXsec.get_xsec_timeseries(hdf_path)

    assert list(ds["cross_section"].values) == ["XS 100", "XS 200"]
    assert ds["Maximum_Flow"].values.tolist() == [3.0, 5.0]
    assert ds.sizes["time"] == 3


@pytest.mark.synthetic_hdf_layout
def test_mesh_summary_geodataframe_unchanged_with_geopandas(tmp_path):
    pytest.importorskip("geopandas")
    from ras_commander import HdfResultsMesh

    hdf_path = _write_results_hdf(tmp_path / "Synthetic.p01.hdf")
    gdf = HdfResultsMesh.get_mesh_max_ws(hdf_path)

    assert type(gdf).__name__ == "GeoDataFrame"
    assert gdf["maximum_water_surface"].tolist() == [10.0, 11.5, 12.0]
