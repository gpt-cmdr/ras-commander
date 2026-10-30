"""Core-install onboarding: RasExamples and geom_df without optional extras.

The core ``ras-commander`` install has only h5py, numpy, and pandas. These
tests block the optional packages in a subprocess to emulate that install.
"""

import json
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

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


def _run_core_only(body: str, *args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "-c", _BLOCKER + body, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_geom_package_imports_without_shapely():
    payload = _run_core_only(r'''
import json
import ras_commander.geom
from ras_commander.geom import GeomMesh
print(json.dumps({
    "mesh": GeomMesh.__name__,
    "loaded": sorted(name for name in ("shapely", "geopandas") if name in sys.modules),
}))
''')

    assert payload == {"mesh": "GeomMesh", "loaded": []}


def test_rasexamples_imports_and_download_error_names_full_extra(tmp_path):
    payload = _run_core_only(
        r'''
import json
from pathlib import Path
from ras_commander import RasExamples
rex = sys.modules["ras_commander.RasExamples"]

with rex._progress_bar(total=3) as bar:
    bar.update(3)

RasExamples._user_data_dir = Path(sys.argv[1])
try:
    RasExamples.get_example_projects("6.6")
except ImportError as exc:
    message = str(exc)
else:
    message = None
print(json.dumps({"message": message}))
''',
        str(tmp_path),
    )

    assert payload["message"] is not None
    assert "requests" in payload["message"]
    assert 'pip install "ras-commander[full]"' in payload["message"]


def test_geometry_hdf_counts_without_geopandas(tmp_path):
    import h5py
    import numpy as np

    hdf_path = tmp_path / "Model.g01.hdf"
    xs_attrs = np.array([(b"River A",)] * 3, dtype=np.dtype([("River", "S16")]))
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset("Geometry/Cross Sections/Attributes", data=xs_attrs)

    payload = _run_core_only(
        r'''
import json
from ras_commander.geom.GeomMetadata import GeomMetadata
counts = GeomMetadata.get_geometry_counts(None, sys.argv[1])
print(json.dumps({
    "source": counts["geometry_metadata_source"],
    "error": counts["geometry_metadata_error"],
    "xs": counts["num_cross_sections"],
    "geopandas_loaded": "geopandas" in sys.modules,
}))
''',
        str(hdf_path),
    )

    assert payload == {
        "source": "hdf",
        "error": None,
        "xs": 3,
        "geopandas_loaded": False,
    }


def test_hdfxsec_count_delegates_to_core_helper(tmp_path):
    pytest.importorskip("geopandas")
    import h5py
    import numpy as np

    from ras_commander.hdf.HdfXsec import HdfXsec

    hdf_path = tmp_path / "Model.g01.hdf"
    xs_attrs = np.array([(b"River A",)] * 2, dtype=np.dtype([("River", "S16")]))
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset("Geometry/Cross Sections/Attributes", data=xs_attrs)
    with h5py.File(hdf_path, "r") as hdf:
        assert HdfXsec._get_cross_section_count(hdf) == 2
        assert HdfXsec._cross_section_group(hdf).name == "/Geometry/Cross Sections"


def test_core_only_extract_and_init_bald_eagle(tmp_path):
    # Populate the shared example archive cache with the full environment so
    # the core-only subprocess exercises extraction, not the download.
    from ras_commander.RasExamples import RasExamples

    RasExamples.extract_project("Balde Eagle Creek", output_path=tmp_path / "warm")

    payload = _run_core_only(
        r'''
import json
from ras_commander import RasExamples, init_ras_project
from ras_commander.RasPrj import RasPrj
project = RasExamples.extract_project("Balde Eagle Creek", output_path=sys.argv[1])
ras = init_ras_project(project, ras_object=RasPrj())
row = ras.geom_df.iloc[0]
print(json.dumps({
    "source": row["geometry_metadata_source"],
    "error": row["geometry_metadata_error"],
    "xs": int(row["num_cross_sections"]),
}))
''',
        str(tmp_path / "core"),
    )

    assert payload["source"] == "hdf"
    assert payload["error"] is None
    assert payload["xs"] > 0
