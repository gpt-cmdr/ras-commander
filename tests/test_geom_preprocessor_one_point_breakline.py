"""HEC-RAS 7.0.1 keeps an authored 1-point breakline; the completion check must accept it."""

import os
import platform
from pathlib import Path

import pytest

HECRAS_INTEGRATION_ENV = "RAS_COMMANDER_RUN_HECRAS_INTEGRATION"


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(
    platform.system() != "Windows" or os.environ.get(HECRAS_INTEGRATION_ENV) != "1",
    reason="Requires Windows, HEC-RAS, and explicit opt-in integration execution",
)
def test_one_point_breakline_survives_native_preprocessing(tmp_path):
    import h5py

    from ras_commander import RasExamples, RasPrj, init_ras_project
    from ras_commander.geom import GeomPreprocessor, GeomStorage

    project = Path(RasExamples.extract_project("Chippewa_2D", output_path=tmp_path))
    geom = project / "Chippewa_2D.g01"
    areas = GeomStorage.get_storage_area_polygons(geom, exclude_2d=False)
    inside = areas.loc[areas["Name"] == "Perimeter 1"].geometry.iloc[0].representative_point()
    point = (round(inside.x, 4), round(inside.y, 4))
    GeomStorage.set_breaklines(
        geom, "Perimeter 1",
        [{"name": "Point BL", "coords": [point], "cell_size_near": None, "cell_size_far": None}],
        create_backup=False,
    )
    ras = init_ras_project(project, os.environ.get("RAS_COMMANDER_HECRAS_VERSION", "7.0.1"),
                           ras_object=RasPrj())
    result = GeomPreprocessor.run_geometry_preprocessor("02", ras_object=ras, max_wait=3600)
    assert result.success, result.error
    with h5py.File(Path(str(geom) + ".hdf"), "r") as hdf:
        group = hdf["Geometry/2D Flow Area Break Lines"]
        names = [bytes(n).rstrip(b"\x00").decode().strip() for n in group["Attributes"][()]["Name"]]
        start, count = (int(v) for v in group["Polyline Info"][names.index("Point BL"), :2])
        assert group["Polyline Points"][start:start + count].tolist() == [list(point)]
