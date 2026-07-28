"""Tests for explicit repair of pathological 2D-only geometry extents."""

from pathlib import Path

import h5py
import numpy as np

from ras_commander.geom import GeomStorage


def _write_2d_geometry(path: Path) -> None:
    path.write_text(
        "".join(
            [
                "Geom Title=Extent Test\n",
                "Viewing Rectangle=-45000000 , 950000000 , 43000000000 , -2000000000\n",
                "Storage Area=MainArea,,\n",
                "Storage Area Surface Line= 5\n",
                f"{100.0:16.7f}{200.0:16.7f}\n",
                f"{300.0:16.7f}{200.0:16.7f}\n",
                f"{300.0:16.7f}{500.0:16.7f}\n",
                f"{100.0:16.7f}{500.0:16.7f}\n",
                f"{100.0:16.7f}{200.0:16.7f}\n",
                "Storage Area Is2D=-1\n",
            ]
        ),
        encoding="utf-8",
    )


def test_repair_viewing_rectangle_updates_text_and_geometry_hdf(tmp_path):
    geom_path = tmp_path / "ExtentTest.g01"
    geom_hdf = Path(str(geom_path) + ".hdf")
    _write_2d_geometry(geom_path)
    with h5py.File(geom_hdf, "w") as hdf_file:
        geometry = hdf_file.create_group("Geometry")
        geometry.attrs["Extents"] = np.asarray(
            [-45000000.0, 950000000.0, -2000000000.0, 43000000000.0]
        )

    bounds = GeomStorage.repair_viewing_rectangle_from_2d_areas(
        geom_path,
        buffer_percent=0,
    )

    assert bounds == (100.0, 300.0, 200.0, 500.0)
    assert (
        "Viewing Rectangle=100 , 300 , 500 , 200\n"
        in geom_path.read_text(encoding="utf-8")
    )
    assert geom_path.with_suffix(".g01.bak").exists()
    with h5py.File(geom_hdf, "r") as hdf_file:
        assert np.array_equal(
            hdf_file["Geometry"].attrs["Extents"],
            np.asarray([100.0, 300.0, 200.0, 500.0]),
        )
