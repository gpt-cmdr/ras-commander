"""``export_final_mannings_raster``: the Final n Values rule through the fast-hdf engine.

Synthetic geometry and land cover; RAS Mapper conformance on real models is recorded in the
fast-hdf documentation (docs/reference/land-cover-precipitation.md).
"""
import h5py
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ras_commander.hdf.HdfLandCover import HdfLandCover

if not HdfLandCover.rasmapper_final_mannings_available():
    pytest.skip("fast-hdf without FinalManningsModel", allow_module_level=True)

SQUARE = [[0.0, 0.0], [0.0, 8.0], [8.0, 8.0], [8.0, 0.0], [0.0, 0.0]]
REGION = [[0.0, 4.0], [0.0, 8.0], [4.0, 8.0], [4.0, 4.0], [0.0, 4.0]]
LC = "Geometry/Land Cover (Manning's n)"


def _polygon(f, group, ring):
    g = f.require_group(group)
    g.create_dataset("Polygon Info", data=np.array([[0, len(ring), 0, 1]], dtype="<i4"))
    g.create_dataset("Polygon Parts", data=np.array([[0, len(ring)]], dtype="<i4"))
    g.create_dataset("Polygon Points", data=np.array(ring, dtype="<f8"))


def _project(tmp_path, cross_sections=False):
    geom = tmp_path / "m.g01.hdf"
    with h5py.File(geom, "w") as f:
        f.create_group("Geometry").attrs["Land Cover Filename"] = np.bytes_(b".\\lc.hdf")
        f.create_group("Geometry/2D Flow Areas").create_dataset(
            "Attributes",
            data=np.array(
                [(b"Area", 0.5, 16)],
                dtype=[("Name", "S8"), ("Mann", "<f4"), ("Cell Count", "<i4")],
            ),
        )
        _polygon(f, "Geometry/2D Flow Areas", SQUARE)
        f.create_group(LC).create_dataset(
            "Attributes", data=np.array([(b"West",)], dtype=[("Name", "S8")])
        )
        _polygon(f, LC, REGION)
        f[LC].create_dataset(
            "Calibration Table",
            data=np.array(
                [(b"Grass", 0.04, 0.2)],
                dtype=[("Land Cover Name", "S8"), ("Base Manning's n Value", "<f4"), ("West", "<f4")],
            ),
        )
        if cross_sections:
            f.create_group("Geometry/Cross Sections").create_dataset(
                "Attributes", data=np.array([(b"XS",)], dtype=[("River", "S8")])
            )
    with h5py.File(tmp_path / "lc.hdf", "w") as f:
        f.create_dataset(
            "Raster Map",
            data=np.array(
                [(0, b"NoData"), (1, b"Grass"), (7, b"Forest")],
                dtype=[("ID", "u1"), ("Name", "S8")],
            ),
        )
        f.create_dataset(
            "Variables",
            data=np.array(
                [(b"NoData", -9999.0), (b"Grass", 0.03), (b"Forest", 0.1)],
                dtype=[("Name", "S8"), ("ManningsN", "<f4")],
            ),
        )
    pixels = np.zeros((8, 8), dtype="u1")
    pixels[:7, :4] = 1
    pixels[:7, 4:] = 7
    with rasterio.open(
        tmp_path / "lc.tif", "w", driver="GTiff", width=8, height=8, count=1, dtype="uint8",
        transform=from_origin(0, 8, 1, 1), crs="EPSG:26918",
    ) as dst:
        dst.write(pixels, 1)
    return geom


def _writers():
    writers = ["rasterio"]
    try:
        import terrio

        if hasattr(terrio, "GeoTiffWriter"):
            writers.append("terrio")
    except ImportError:
        pass
    return writers


@pytest.mark.parametrize("writer", _writers())
def test_rule_and_georeferencing(tmp_path, writer):
    geom = _project(tmp_path)
    out = HdfLandCover.export_final_mannings_raster(geom, tmp_path / "n.tif", writer=writer)
    with rasterio.open(out) as d:
        a = d.read(1)
        assert d.nodata == -9999.0
        assert (d.transform.c, d.transform.f, d.transform.a) == (0.0, 8.0, 1.0)
        assert d.crs.to_epsg() == 26918
    assert a.shape == (8, 8)
    assert a[0, 0] == pytest.approx(0.2)  # region override on Grass
    assert a[0, 7] == pytest.approx(0.1)  # Forest: land-cover n, outside the region
    assert a[5, 0] == pytest.approx(0.04)  # calibration-table base n replaces 0.03
    assert a[7, 0] == pytest.approx(0.5)  # class 0: the 2D flow area default
    assert [p.name for p in tmp_path.glob("*partial*")] == []


def test_refusal_leaves_a_previous_raster(tmp_path):
    geom = _project(tmp_path, cross_sections=True)
    previous = tmp_path / "n.tif"
    previous.write_bytes(b"previous")
    with pytest.raises(Exception, match="cross sections"):
        HdfLandCover.export_final_mannings_raster(geom, previous)
    assert previous.read_bytes() == b"previous"


def test_bad_writer_is_refused(tmp_path):
    with pytest.raises(ValueError, match="writer"):
        HdfLandCover.export_final_mannings_raster(
            _project(tmp_path), tmp_path / "n.tif", writer="gdal"
        )
