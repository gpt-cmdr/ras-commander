"""Regression tests for raster-area calculations in HdfInfiltration."""

import importlib.util
from pathlib import Path

import h5py
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin


def _write_geom_hdf(path: Path, mesh_name: str = "Mesh 1") -> None:
    """Create a minimal geometry HDF with one 2D flow area perimeter."""
    attrs_dtype = np.dtype([("Name", "S32")])
    attrs_data = np.array([(mesh_name.encode("utf-8"),)], dtype=attrs_dtype)
    perimeter = np.array(
        [
            [0.0, 0.0],
            [20.0, 0.0],
            [20.0, 20.0],
            [0.0, 20.0],
            [0.0, 0.0],
        ],
        dtype=float,
    )

    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("Geometry/2D Flow Areas/Attributes", data=attrs_data)
        hdf.create_dataset(
            f"Geometry/2D Flow Areas/{mesh_name}/Perimeter",
            data=perimeter,
        )


def _write_soil_hdf(path: Path) -> None:
    """Create a minimal soil HDF with a raster map."""
    raster_map_dtype = np.dtype([("RasterValue", "<i4"), ("Name", "S32")])
    raster_map = np.array(
        [
            (1, b"Soil A"),
            (2, b"Soil B"),
        ],
        dtype=raster_map_dtype,
    )

    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("Raster Map", data=raster_map)


def _write_landcover_hdf(path: Path) -> None:
    """Create a minimal land-cover HDF with a raster map and variables."""
    raster_map_dtype = np.dtype([("RasterValue", "<i4"), ("Name", "S32")])
    raster_map = np.array(
        [
            (1, b"Forest"),
            (2, b"Urban"),
        ],
        dtype=raster_map_dtype,
    )
    variables_dtype = np.dtype(
        [
            ("Name", "S32"),
            ("ManningsN", "<f8"),
            ("PercentImpervious", "<f8"),
        ]
    )
    variables = np.array(
        [
            (b"Forest", 0.12, 5.0),
            (b"Urban", 0.03, 85.0),
        ],
        dtype=variables_dtype,
    )

    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("Raster Map", data=raster_map)
        hdf.create_dataset("Variables", data=variables)


def _write_raster(
    path: Path,
    array: np.ndarray,
    x_res: float,
    y_res: float,
    crs: str | None = "EPSG:5070",
    nodata: int = -9999,
) -> None:
    """Create a categorical GeoTIFF with a known cell size."""
    height, width = array.shape
    transform = from_origin(0.0, float(height) * y_res, x_res, y_res)

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=array.dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)


class TestRasterAreaHelpers:
    """Unit tests for the shared pixel-count conversion helpers."""

    def test_categorical_counts_to_area_excludes_nodata(self):
        """NoData counts should not contribute to area or percentages."""
        from ras_commander import HdfInfiltration

        area_by_value, total_area_sqm = (
            HdfInfiltration._categorical_counts_to_area_sqm(
                stats={1: 3, 2: 1, -9999: 2},
                no_data=-9999,
                cell_area_sqm=25.0,
            )
        )

        assert total_area_sqm == pytest.approx(100.0)
        assert area_by_value[1] == pytest.approx(75.0)
        assert area_by_value[2] == pytest.approx(25.0)

    def test_raster_cell_area_uses_crs_linear_units(self, tmp_path: Path):
        """Feet-based rasters should be converted to square meters."""
        from ras_commander import HdfInfiltration

        tif_path = tmp_path / "feet_grid.tif"
        array = np.array([[1, 1], [1, 1]], dtype=np.int16)
        _write_raster(
            tif_path,
            array=array,
            x_res=10.0,
            y_res=20.0,
            crs="EPSG:2277",
        )

        with rasterio.open(tif_path) as src:
            cell_area_sqm = HdfInfiltration._get_raster_cell_area_sqm(src)
            expected = 200.0 * (src.crs.linear_units_factor[1] ** 2)

        assert cell_area_sqm == pytest.approx(expected)

    def test_raster_cell_area_requires_projected_crs(self, tmp_path: Path):
        """Missing CRS should fail instead of silently assuming meters."""
        from ras_commander import HdfInfiltration

        tif_path = tmp_path / "no_crs_grid.tif"
        array = np.array([[1, 1], [1, 1]], dtype=np.int16)
        _write_raster(
            tif_path,
            array=array,
            x_res=10.0,
            y_res=10.0,
            crs=None,
        )

        with rasterio.open(tif_path) as src:
            with pytest.raises(ValueError, match="Raster CRS is missing"):
                HdfInfiltration._get_raster_cell_area_sqm(src)

    def test_calculate_soil_statistics_requires_cell_area(self):
        """The low-level helper should not silently assume 1 sqm pixels."""
        from ras_commander import HdfInfiltration

        with pytest.raises(ValueError, match="cell_area_sqm must be provided"):
            HdfInfiltration.calculate_soil_statistics(
                zonal_stats=[{1: 2, 2: 1}],
                raster_map={1: "Soil A", 2: "Soil B"},
            )

    def test_calculate_soil_statistics_scales_by_cell_area(self):
        """The low-level helper should honor the provided raster cell area."""
        from ras_commander import HdfInfiltration

        result = HdfInfiltration.calculate_soil_statistics(
            zonal_stats=[{1: 2, 2: 1, -9999: 4}],
            raster_map={1: "Soil A", 2: "Soil B"},
            cell_area_sqm=25.0,
            no_data=-9999,
        )

        assert list(result["mukey"]) == ["Soil A", "Soil B"]
        assert result.iloc[0]["Percentage"] == pytest.approx(66.6666667)
        assert result.iloc[1]["Percentage"] == pytest.approx(33.3333333)
        assert result.iloc[0]["Area in Acres"] == pytest.approx(
            50.0 * HdfInfiltration.SQM_TO_ACRE
        )


@pytest.mark.skipif(
    importlib.util.find_spec("rasterstats") is None,
    reason="rasterstats not installed",
)
class TestPublicRasterStats:
    """Public API regression tests for raster statistics."""

    def test_get_soils_raster_stats_scales_counts_by_cell_area(
        self,
        tmp_path: Path,
    ):
        """Areas should reflect the raster resolution, not raw pixel counts."""
        from ras_commander import HdfInfiltration

        geom_hdf_path = tmp_path / "model.g01.hdf"
        soil_hdf_path = tmp_path / "soil_layer.hdf"
        soil_tif_path = soil_hdf_path.with_suffix(".tif")

        _write_geom_hdf(geom_hdf_path)
        _write_soil_hdf(soil_hdf_path)
        _write_raster(
            soil_tif_path,
            array=np.array([[1, 1], [2, -9999]], dtype=np.int16),
            x_res=10.0,
            y_res=10.0,
        )

        result = HdfInfiltration.get_soils_raster_stats(
            geom_hdf_path,
            soil_hdf_path=soil_hdf_path,
        )

        assert list(result["mukey"]) == ["Soil A", "Soil B"]

        soil_a = result.iloc[0]
        soil_b = result.iloc[1]

        assert soil_a["area_sqm"] == pytest.approx(200.0)
        assert soil_b["area_sqm"] == pytest.approx(100.0)
        assert soil_a["percentage"] == pytest.approx(66.6666667)
        assert soil_b["percentage"] == pytest.approx(33.3333333)
        assert soil_a["area_acres"] == pytest.approx(
            200.0 * HdfInfiltration.SQM_TO_ACRE
        )

    def test_get_landcover_raster_stats_scales_counts_by_cell_area(
        self,
        tmp_path: Path,
    ):
        """Land-cover area outputs should also reflect raster resolution."""
        from ras_commander import HdfInfiltration

        geom_hdf_path = tmp_path / "model.g01.hdf"
        landcover_hdf_path = tmp_path / "landcover_layer.hdf"
        landcover_tif_path = landcover_hdf_path.with_suffix(".tif")

        _write_geom_hdf(geom_hdf_path)
        _write_landcover_hdf(landcover_hdf_path)
        _write_raster(
            landcover_tif_path,
            array=np.array([[1, 1], [2, -9999]], dtype=np.int16),
            x_res=10.0,
            y_res=10.0,
        )

        result = HdfInfiltration.get_landcover_raster_stats(
            geom_hdf_path,
            landcover_hdf_path=landcover_hdf_path,
        )

        assert list(result["land_cover"]) == ["Forest", "Urban"]

        forest = result.iloc[0]
        urban = result.iloc[1]

        assert forest["area_sqm"] == pytest.approx(200.0)
        assert urban["area_sqm"] == pytest.approx(100.0)
        assert forest["percentage"] == pytest.approx(66.6666667)
        assert urban["percentage"] == pytest.approx(33.3333333)
        assert forest["mannings_n"] == pytest.approx(0.12)
        assert urban["percent_impervious"] == pytest.approx(85.0)
