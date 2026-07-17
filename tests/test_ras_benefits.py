import builtins
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import time

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.features import rasterize
from shapely.geometry import Point, box


def test_benefit_api_is_exported_without_shadowing_hdf_benefit_areas():
    import ras_commander as ras

    assert ras.RasBenefits.__name__ == "RasBenefits"
    assert ras.BenefitAreaConfig.__name__ == "BenefitAreaConfig"
    assert ras.BenefitAreaResult.__name__ == "BenefitAreaResult"
    assert ras.BenefitCategory.FULLY_BENEFITED == 3
    assert ras.HdfBenefitAreas.__name__ == "HdfBenefitAreas"


@pytest.mark.parametrize("pre_plan", [None, "", "   "])
def test_benefit_config_requires_pre_plan(pre_plan, tmp_path):
    from ras_commander import BenefitAreaConfig

    with pytest.raises(ValueError, match="pre_plan_number is required"):
        BenefitAreaConfig(pre_plan, tmp_path / "terrain.tif")


@pytest.mark.parametrize("terrain", [None, "", "   "])
def test_benefit_terrain_is_required_with_actionable_remediation(terrain):
    from ras_commander import BenefitAreaConfig, RasBenefits

    with pytest.raises(ValueError, match="terrain_tif is required") as direct:
        RasBenefits.validate_terrain_tif(terrain)
    assert "create_terrain" in str(direct.value)
    assert "add_terrain_layer" in str(direct.value)

    with pytest.raises(ValueError, match="terrain_tif is required") as config:
        BenefitAreaConfig("01", terrain)
    assert "create_terrain" in str(config.value)
    assert "add_terrain_layer" in str(config.value)


@pytest.mark.parametrize("tolerance", [-1, float("inf"), True, "bad"])
def test_polygon_simplify_tolerance_must_be_nonnegative_number(tolerance, tmp_path):
    from ras_commander import BenefitAreaConfig

    with pytest.raises(
        (TypeError, ValueError),
        match="polygon_simplify_tolerance",
    ):
        BenefitAreaConfig(
            "01",
            tmp_path / "terrain.tif",
            polygon_simplify_tolerance=tolerance,
        )


def _write_raster(
    path: Path,
    data: np.ndarray,
    *,
    transform: Affine = Affine(10.0, 0.0, 1000.0, 0.0, -10.0, 2000.0),
    crs: str | None = "EPSG:2278",
    nodata: float | int | None = -9999.0,
) -> Path:
    array = np.asarray(data)
    if array.ndim == 2:
        array = array[np.newaxis, ...]
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=array.shape[2],
        height=array.shape[1],
        count=array.shape[0],
        dtype=array.dtype,
        transform=transform,
        crs=crs,
        nodata=nodata,
    ) as dst:
        dst.write(array)
    return path


def test_classify_depth_arrays_matches_documented_rules_and_thresholds():
    from ras_commander.RasBenefits import BenefitCategory, RasBenefits

    pre = np.array(
        [
            [1.0, 1.0, 1.0, 0.0, 0.30, 0.30001],
            [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        ],
        dtype=np.float32,
    )
    post = np.array(
        [
            [np.nan, 0.20, 0.90, 1.0, 0.05, 0.05001],
            [np.nan, 0.20, 0.90, 1.0, 0.20, 0.20],
        ],
        dtype=np.float32,
    )
    analysis_mask = np.ones(pre.shape, dtype=bool)
    analysis_mask[1, :] = False

    result = RasBenefits.classify_depth_arrays(
        pre,
        post,
        analysis_mask=analysis_mask,
        flood_min_depth=0.05,
        benefit_min_depth=0.25,
        minimum_region_pixels=None,
    )

    assert result.tolist() == [
        [
            BenefitCategory.FULLY_BENEFITED,
            BenefitCategory.PARTIALLY_BENEFITED,
            BenefitCategory.NO_CHANGE,
            BenefitCategory.NO_CHANGE,
            BenefitCategory.FULLY_BENEFITED,
            BenefitCategory.PARTIALLY_BENEFITED,
        ],
        [0, 0, 0, 0, 0, 0],
    ]


def test_filter_small_regions_uses_four_connectivity_and_retains_exact_threshold():
    from ras_commander.RasBenefits import BenefitCategory, RasBenefits

    classes = np.zeros((6, 8), dtype=np.uint8)
    classes[0, 0] = BenefitCategory.FULLY_BENEFITED
    classes[1, 1] = BenefitCategory.FULLY_BENEFITED  # diagonal is not connected
    classes[3, 0:4] = BenefitCategory.PARTIALLY_BENEFITED
    classes[5, 0:3] = BenefitCategory.NO_CHANGE

    filtered = RasBenefits.filter_small_regions(classes, minimum_region_pixels=4)

    assert filtered[0, 0] == 0
    assert filtered[1, 1] == 0
    assert np.all(filtered[3, 0:4] == BenefitCategory.PARTIALLY_BENEFITED)
    assert np.all(filtered[5, 0:3] == 0)
    assert np.array_equal(
        RasBenefits.filter_small_regions(classes, minimum_region_pixels=None),
        classes,
    )


def test_create_benefit_area_writes_categorical_geotiff_and_metadata(tmp_path):
    from ras_commander.RasBenefits import BenefitCategory, RasBenefits

    transform = Affine(10.0, 0.0, 1000.0, 0.0, -10.0, 2000.0)
    pre = np.array(
        [[1.0, 1.0, 1.0], [1.0, 1.0, -9999.0]],
        dtype=np.float32,
    )
    post = np.array(
        [[-9999.0, 0.50, 0.90], [0.20, 1.0, -9999.0]],
        dtype=np.float32,
    )
    pre_path = _write_raster(tmp_path / "pre.tif", pre, transform=transform)
    post_path = _write_raster(tmp_path / "post.tif", post, transform=transform)
    terrain_path = _write_raster(
        tmp_path / "terrain.tif",
        np.ones((8, 8), dtype=np.float32),
        transform=Affine(10.0, 0.0, 970.0, 0.0, -10.0, 2030.0),
    )
    output_path = tmp_path / "benefit_area.tif"

    result = RasBenefits.create_benefit_area(
        pre_path,
        post_path,
        terrain_path,
        output_path,
        minimum_region_pixels=None,
    )

    assert result.raster_path == output_path
    assert result.polygon_path is None
    with rasterio.open(output_path) as src:
        assert src.count == 1
        assert src.dtypes == ("uint8",)
        assert src.nodata == 0
        assert src.crs.to_epsg() == 2278
        assert src.transform == transform
        assert src.descriptions == ("Benefit Area",)
        assert src.tags()["benefit_area_schema"] == "benefit-area-depth-v1"
        assert src.tags()["minimum_region_pixels"] == "disabled"
        tagged_statistics = json.loads(src.tags()["benefit_statistics"])
        assert tagged_statistics["Fully Benefited"]["cell_count"] == 1
        assert src.colormap(1)[BenefitCategory.FULLY_BENEFITED][3] == 255
        assert src.read(1).tolist() == [
            [BenefitCategory.FULLY_BENEFITED, BenefitCategory.PARTIALLY_BENEFITED, BenefitCategory.NO_CHANGE],
            [BenefitCategory.PARTIALLY_BENEFITED, BenefitCategory.NO_CHANGE, 0],
        ]

    assert result.statistics["Fully Benefited"]["cell_count"] == 1
    assert result.statistics["Partially Benefited"]["cell_count"] == 2
    assert result.statistics["No Change"]["cell_count"] == 2


def test_create_benefit_area_applies_analysis_and_improvement_boundaries(tmp_path):
    from ras_commander.RasBenefits import BenefitCategory, RasBenefits

    transform = Affine(10.0, 0.0, 0.0, 0.0, -10.0, 40.0)
    depth = np.ones((4, 4), dtype=np.float32)
    pre_path = _write_raster(tmp_path / "pre.tif", depth, transform=transform)
    post_path = _write_raster(
        tmp_path / "post.tif",
        np.full((4, 4), -9999.0, dtype=np.float32),
        transform=transform,
    )
    terrain_path = _write_raster(
        tmp_path / "terrain.tif", depth, transform=transform
    )
    analysis = box(0.0, 0.0, 40.0, 40.0)
    improvement = box(10.0, 10.0, 30.0, 30.0)

    result = RasBenefits.create_benefit_area(
        pre_path,
        post_path,
        terrain_path,
        tmp_path / "benefit.tif",
        analysis_boundary=analysis,
        improvement_boundary=improvement,
        minimum_region_pixels=None,
    )

    with rasterio.open(result.raster_path) as src:
        values = src.read(1)
    assert np.count_nonzero(values == BenefitCategory.FULLY_BENEFITED) == 12
    assert np.count_nonzero(values == 0) == 4


@pytest.mark.parametrize(
    "analysis",
    [
        gpd.GeoDataFrame(geometry=[], crs="EPSG:2278"),
        gpd.GeoDataFrame(geometry=[None], crs="EPSG:2278"),
    ],
)
def test_empty_supplied_analysis_boundary_is_rejected(tmp_path, analysis):
    from ras_commander import RasBenefits

    depth = np.ones((2, 2), dtype=np.float32)
    pre = _write_raster(tmp_path / "pre.tif", depth)
    post = _write_raster(tmp_path / "post.tif", depth)
    terrain = _write_raster(tmp_path / "terrain.tif", depth)

    with pytest.raises(ValueError, match="analysis_boundary.*no"):
        RasBenefits.create_benefit_area(
            pre,
            post,
            terrain,
            tmp_path / "benefit.tif",
            analysis_boundary=analysis,
            minimum_region_pixels=None,
        )


def test_empty_improvement_boundary_means_no_exclusion(tmp_path):
    from ras_commander import BenefitCategory, RasBenefits

    pre_values = np.ones((2, 2), dtype=np.float32)
    post_values = np.full((2, 2), -9999.0, dtype=np.float32)
    pre = _write_raster(tmp_path / "pre.tif", pre_values)
    post = _write_raster(tmp_path / "post.tif", post_values)
    terrain = _write_raster(tmp_path / "terrain.tif", pre_values)

    result = RasBenefits.create_benefit_area(
        pre,
        post,
        terrain,
        tmp_path / "benefit.tif",
        improvement_boundary=gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:2278",
        ),
        minimum_region_pixels=None,
    )

    assert result.statistics["Fully Benefited"]["cell_count"] == 4
    with rasterio.open(result.raster_path) as src:
        assert np.all(src.read(1) == BenefitCategory.FULLY_BENEFITED)


@pytest.mark.parametrize(
    "boundary_keyword",
    ["analysis_boundary", "improvement_boundary"],
)
def test_boundaries_reject_non_polygon_geometry(tmp_path, boundary_keyword):
    from ras_commander import RasBenefits

    values = np.ones((2, 2), dtype=np.float32)
    pre = _write_raster(tmp_path / "pre.tif", values)
    post = _write_raster(tmp_path / "post.tif", values)
    terrain = _write_raster(tmp_path / "terrain.tif", values)

    with pytest.raises(ValueError, match="must contain polygon geometry"):
        RasBenefits.create_benefit_area(
            pre,
            post,
            terrain,
            tmp_path / "benefit.tif",
            minimum_region_pixels=None,
            **{boundary_keyword: Point(1005.0, 1995.0)},
        )


def test_optional_polygon_preserves_cell_edges_and_dissolves_by_status(tmp_path):
    from ras_commander.RasBenefits import RasBenefits

    transform = Affine(10.0, 0.0, 0.0, 0.0, -10.0, 30.0)
    pre = np.ones((3, 3), dtype=np.float32)
    post = np.full((3, 3), -9999.0, dtype=np.float32)
    pre_path = _write_raster(tmp_path / "pre.tif", pre, transform=transform)
    post_path = _write_raster(tmp_path / "post.tif", post, transform=transform)
    terrain_path = _write_raster(
        tmp_path / "terrain.tif", pre, transform=transform
    )
    polygon_path = tmp_path / "benefit.gpkg"

    result = RasBenefits.create_benefit_area(
        pre_path,
        post_path,
        terrain_path,
        tmp_path / "benefit.tif",
        minimum_region_pixels=None,
        polygon_output=polygon_path,
    )

    polygons = gpd.read_file(polygon_path, layer="benefit_area")
    assert result.polygon_path == polygon_path
    assert len(polygons) == 1
    assert polygons.iloc[0]["benefit_status"] == "Fully Benefited"
    assert polygons.geometry.iloc[0].area == pytest.approx(900.0)
    assert set(polygons.geometry.iloc[0].exterior.coords) == {
        (0.0, 0.0),
        (0.0, 30.0),
        (30.0, 0.0),
        (30.0, 30.0),
    }


def test_optional_polygon_simplification_reduces_edge_vertices_only(tmp_path):
    from ras_commander.RasBenefits import RasBenefits

    transform = Affine(10.0, 0.0, 0.0, 0.0, -10.0, 50.0)
    nodata = -9999.0
    pre = np.array(
        [
            [1, 1, 1, nodata, nodata],
            [1, 1, 1, 1, nodata],
            [1, 1, 1, 1, 1],
            [1, 1, 1, 1, nodata],
            [1, 1, 1, nodata, nodata],
        ],
        dtype=np.float32,
    )
    post = np.full(pre.shape, nodata, dtype=np.float32)
    terrain = np.where(pre == nodata, 0.0, pre).astype(np.float32)
    pre_path = _write_raster(tmp_path / "pre.tif", pre, transform=transform)
    post_path = _write_raster(tmp_path / "post.tif", post, transform=transform)
    terrain_path = _write_raster(
        tmp_path / "terrain.tif",
        terrain,
        transform=transform,
    )

    exact_polygon = tmp_path / "exact.gpkg"
    simplified_polygon = tmp_path / "simplified.gpkg"
    exact = RasBenefits.create_benefit_area(
        pre_path,
        post_path,
        terrain_path,
        tmp_path / "exact.tif",
        minimum_region_pixels=None,
        polygon_output=exact_polygon,
    )
    simplified = RasBenefits.create_benefit_area(
        pre_path,
        post_path,
        terrain_path,
        tmp_path / "simplified.tif",
        minimum_region_pixels=None,
        polygon_output=simplified_polygon,
        polygon_simplify_tolerance=12.0,
    )

    exact_geom = gpd.read_file(exact_polygon).geometry.iloc[0]
    simplified_geom = gpd.read_file(simplified_polygon).geometry.iloc[0]

    assert len(simplified_geom.exterior.coords) < len(exact_geom.exterior.coords)
    assert simplified.statistics == exact.statistics
    assert simplified.polygon_simplify_tolerance == 12.0


@pytest.mark.parametrize("suffix", [".gpkg", ".shp", ".geojson", ".json"])
def test_optional_polygon_writes_each_base_vector_format(tmp_path, suffix):
    from ras_commander import RasBenefits

    pre_values = np.ones((2, 2), dtype=np.float32)
    post_values = np.full((2, 2), -9999.0, dtype=np.float32)
    pre = _write_raster(tmp_path / "pre.tif", pre_values)
    post = _write_raster(tmp_path / "post.tif", post_values)
    terrain = _write_raster(tmp_path / "terrain.tif", pre_values)
    polygon = tmp_path / f"benefit{suffix}"

    result = RasBenefits.create_benefit_area(
        pre,
        post,
        terrain,
        tmp_path / f"benefit_{suffix[1:]}.tif",
        minimum_region_pixels=None,
        polygon_output=polygon,
    )

    read_kwargs = {"layer": "benefit_area"} if suffix == ".gpkg" else {}
    frame = gpd.read_file(polygon, **read_kwargs)
    assert result.polygon_path == polygon
    assert len(frame) == 1
    assert frame.geometry.iloc[0].area == pytest.approx(400.0)


def test_same_stem_raster_and_shapefile_can_be_replaced_transactionally(tmp_path):
    from ras_commander import BenefitCategory, RasBenefits

    values = np.ones((2, 2), dtype=np.float32)
    pre = _write_raster(tmp_path / "pre.tif", values)
    terrain = _write_raster(tmp_path / "terrain.tif", values)
    post_dry = _write_raster(
        tmp_path / "post_dry.tif",
        np.full(values.shape, -9999.0, dtype=np.float32),
    )
    post_flooded = _write_raster(tmp_path / "post_flooded.tif", values)
    output = tmp_path / "benefit.tif"
    polygon = tmp_path / "benefit.shp"

    RasBenefits.create_benefit_area(
        pre,
        post_dry,
        terrain,
        output,
        minimum_region_pixels=None,
        polygon_output=polygon,
    )
    RasBenefits.create_benefit_area(
        pre,
        post_flooded,
        terrain,
        output,
        minimum_region_pixels=None,
        polygon_output=polygon,
    )

    with rasterio.open(output) as src:
        assert np.all(src.read(1) == int(BenefitCategory.NO_CHANGE))
    assert len(gpd.read_file(polygon)) == 1
    assert not list(tmp_path.glob(".*.rollback"))


@pytest.mark.parametrize("suffix", [".parquet", ".geoparquet"])
def test_geoparquet_fails_early_with_actionable_extra_when_pyarrow_missing(
    monkeypatch,
    tmp_path,
    suffix,
):
    from ras_commander import RasBenefits

    values = np.ones((2, 2), dtype=np.float32)
    pre = _write_raster(tmp_path / "pre.tif", values)
    post = _write_raster(tmp_path / "post.tif", values)
    terrain = _write_raster(tmp_path / "terrain.tif", values)
    output = tmp_path / "benefit.tif"
    original_import = builtins.__import__

    def import_without_pyarrow(name, *args, **kwargs):
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ImportError("pyarrow intentionally unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_pyarrow)

    with pytest.raises(ImportError, match=r"ras-commander\[geoparquet\]"):
        RasBenefits.create_benefit_area(
            pre,
            post,
            terrain,
            output,
            minimum_region_pixels=None,
            polygon_output=tmp_path / f"benefit{suffix}",
        )

    assert not output.exists()


@pytest.mark.parametrize("suffix", [".parquet", ".geoparquet"])
def test_optional_polygon_writes_geoparquet_when_extra_is_installed(
    tmp_path,
    suffix,
):
    pytest.importorskip("pyarrow")
    from ras_commander import RasBenefits

    pre_values = np.ones((2, 2), dtype=np.float32)
    post_values = np.full((2, 2), -9999.0, dtype=np.float32)
    pre = _write_raster(tmp_path / "pre.tif", pre_values)
    post = _write_raster(tmp_path / "post.tif", post_values)
    terrain = _write_raster(tmp_path / "terrain.tif", pre_values)
    polygon = tmp_path / f"benefit{suffix}"

    RasBenefits.create_benefit_area(
        pre,
        post,
        terrain,
        tmp_path / f"benefit_{suffix[1:]}.tif",
        minimum_region_pixels=None,
        polygon_output=polygon,
    )

    frame = gpd.read_parquet(polygon)
    assert len(frame) == 1
    assert frame.geometry.iloc[0].area == pytest.approx(400.0)


def test_integrated_filter_and_exact_raster_polygon_grid_parity(tmp_path):
    from ras_commander import BenefitCategory, RasBenefits

    transform = Affine(10.0, 0.0, 100.0, 0.0, -10.0, 200.0)
    pre_values = np.zeros((12, 12), dtype=np.float32)
    # These two 15-cell components touch only at one diagonal corner. They
    # would form a retained 30-cell region under eight-connectivity, but each
    # is removed independently by the required four-connected 16-cell sieve.
    pre_values[0:3, 0:5] = 1.0
    pre_values[3:6, 5:10] = 1.0
    # A component exactly equal to the threshold must remain.
    pre_values[7:11, 0:4] = 1.0
    post_values = np.full(pre_values.shape, -9999.0, dtype=np.float32)
    pre = _write_raster(
        tmp_path / "pre.tif",
        pre_values,
        transform=transform,
    )
    post = _write_raster(
        tmp_path / "post.tif",
        post_values,
        transform=transform,
    )
    terrain = _write_raster(
        tmp_path / "terrain.tif",
        np.ones(pre_values.shape, dtype=np.float32),
        transform=transform,
    )
    polygon = tmp_path / "benefit.gpkg"

    result = RasBenefits.create_benefit_area(
        pre,
        post,
        terrain,
        tmp_path / "benefit.tif",
        minimum_region_pixels=16,
        polygon_output=polygon,
    )

    with rasterio.open(result.raster_path) as src:
        classified = src.read(1)
        rasterized_profile = src.profile
    expected = np.zeros(pre_values.shape, dtype=np.uint8)
    expected[7:11, 0:4] = int(BenefitCategory.FULLY_BENEFITED)
    np.testing.assert_array_equal(classified, expected)
    assert result.statistics["Fully Benefited"]["cell_count"] == 16

    frame = gpd.read_file(polygon, layer="benefit_area")
    assert len(frame) == 1
    geometry = frame.geometry.iloc[0]
    assert geometry.area == pytest.approx(1600.0)
    assert set(geometry.exterior.coords) == {
        (100.0, 90.0),
        (100.0, 130.0),
        (140.0, 90.0),
        (140.0, 130.0),
    }
    polygon_codes = rasterize(
        [(geometry, int(BenefitCategory.FULLY_BENEFITED))],
        out_shape=classified.shape,
        transform=rasterized_profile["transform"],
        fill=0,
        all_touched=False,
        dtype="uint8",
    )
    np.testing.assert_array_equal(polygon_codes, classified)


def test_area_statistics_use_43560_square_feet_per_acre():
    from rasterio.crs import CRS
    from ras_commander import RasBenefits

    statistics = RasBenefits._statistics_from_counts(
        {3: 43560},
        Affine.identity(),
        CRS.from_epsg(2278),
    )

    assert statistics["Fully Benefited"]["area_map_units"] == 43560.0
    assert statistics["Fully Benefited"]["area_acres"] == pytest.approx(1.0)


def test_optional_polygon_writes_empty_layer_when_no_cells_are_classified(tmp_path):
    from ras_commander import RasBenefits

    pre = _write_raster(
        tmp_path / "pre.tif",
        np.zeros((2, 2), dtype=np.float32),
    )
    post = _write_raster(
        tmp_path / "post.tif",
        np.zeros((2, 2), dtype=np.float32),
    )
    terrain = _write_raster(
        tmp_path / "terrain.tif",
        np.ones((2, 2), dtype=np.float32),
    )
    polygon_path = tmp_path / "benefit.gpkg"

    result = RasBenefits.create_benefit_area(
        pre,
        post,
        terrain,
        tmp_path / "benefit.tif",
        minimum_region_pixels=None,
        polygon_output=polygon_path,
    )

    assert result.polygon_path == polygon_path
    assert gpd.read_file(polygon_path, layer="benefit_area").empty


@pytest.mark.parametrize("suffix", [".vrt", ".img", ".hdf"])
def test_single_tiff_terrain_error_is_actionable(tmp_path, suffix):
    from ras_commander.RasBenefits import RasBenefits

    terrain = tmp_path / f"terrain{suffix}"
    terrain.write_text("not a terrain", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        RasBenefits.validate_terrain_tif(terrain)

    message = str(exc_info.value)
    assert "single GeoTIFF" in message
    assert "RasTerrain.vrt_to_tiff" in message
    assert "RasTerrain.create_terrain_from_rasters" in message
    assert "RasMap.add_terrain_layer" in message
    assert "RasMap.set_terrain_layer_visibility" in message


def test_single_tiff_terrain_rejects_multiband_and_missing_crs(tmp_path):
    from ras_commander.RasBenefits import RasBenefits

    multiband = _write_raster(
        tmp_path / "multiband.tif",
        np.ones((2, 2, 2), dtype=np.float32),
    )
    no_crs = _write_raster(
        tmp_path / "no_crs.tif",
        np.ones((2, 2), dtype=np.float32),
        crs=None,
    )

    with pytest.raises(ValueError, match="one raster band"):
        RasBenefits.validate_terrain_tif(multiband)
    with pytest.raises(ValueError, match="coordinate reference system"):
        RasBenefits.validate_terrain_tif(no_crs)


def test_single_tiff_terrain_must_have_readable_pixel_data(monkeypatch, tmp_path):
    from ras_commander import RasBenefits

    terrain = _write_raster(
        tmp_path / "terrain.tif",
        np.ones((2, 2), dtype=np.float32),
    )

    monkeypatch.setattr(
        RasBenefits,
        "_read_raster_band",
        staticmethod(
            lambda *args, **kwargs: (_ for _ in ()).throw(
                rasterio.errors.RasterioIOError("forced unreadable block")
            )
        ),
    )

    with pytest.raises(ValueError, match="could not be opened or sampled"):
        RasBenefits.validate_terrain_tif(terrain)


def test_registered_terrain_hdf_requires_exactly_the_supplied_single_tiff(tmp_path):
    h5py = pytest.importorskip("h5py")
    from ras_commander import RasBenefits

    terrain = _write_raster(
        tmp_path / "mapping_terrain.tif",
        np.ones((2, 2), dtype=np.float32),
    )
    other = _write_raster(
        tmp_path / "other.tif",
        np.ones((2, 2), dtype=np.float32),
    )
    hdf_path = tmp_path / "mapping_terrain.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        source = hdf.create_group("Terrain/source")
        source.attrs["File"] = terrain.name.encode("utf-8")

    assert RasBenefits.validate_registered_terrain_source(hdf_path, terrain) == terrain
    with pytest.raises(ValueError, match="must be the single GeoTIFF recorded"):
        RasBenefits.validate_registered_terrain_source(hdf_path, other)


def test_registered_terrain_hdf_rejects_multiple_source_rasters(tmp_path):
    h5py = pytest.importorskip("h5py")
    from ras_commander import RasBenefits

    first = _write_raster(
        tmp_path / "first.tif",
        np.ones((2, 2), dtype=np.float32),
    )
    second = _write_raster(
        tmp_path / "second.tif",
        np.ones((2, 2), dtype=np.float32),
    )
    hdf_path = tmp_path / "multi.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_group("Terrain/first").attrs["File"] = first.name.encode("utf-8")
        hdf.create_group("Terrain/second").attrs["File"] = second.name.encode("utf-8")

    with pytest.raises(ValueError, match="records 2 source rasters") as exc_info:
        RasBenefits.validate_registered_terrain_source(hdf_path, first)

    assert "RasTerrain.vrt_to_tiff" in str(exc_info.value)


@pytest.mark.skipif(os.name == "nt", reason="POSIX path interpretation only")
@pytest.mark.parametrize("source_path", ["C:/Terrain/model.tif", "C:\\Terrain\\model.tif"])
def test_registered_terrain_rejects_windows_absolute_paths_on_posix(
    tmp_path,
    source_path,
):
    h5py = pytest.importorskip("h5py")
    from ras_commander import RasBenefits

    hdf_path = tmp_path / "terrain.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_group("Terrain/source").attrs["File"] = source_path

    with pytest.raises(ValueError, match="absolute Windows source path"):
        RasBenefits.get_registered_terrain_source(hdf_path)


def test_create_benefit_area_rejects_misaligned_depth_grids(tmp_path):
    from ras_commander.RasBenefits import RasBenefits

    pre_path = _write_raster(
        tmp_path / "pre.tif", np.ones((2, 2), dtype=np.float32)
    )
    post_path = _write_raster(
        tmp_path / "post.tif",
        np.ones((2, 2), dtype=np.float32),
        transform=Affine(10.0, 0.0, 1005.0, 0.0, -10.0, 2000.0),
    )
    terrain_path = _write_raster(
        tmp_path / "terrain.tif", np.ones((8, 8), dtype=np.float32)
    )

    with pytest.raises(ValueError, match="same grid"):
        RasBenefits.create_benefit_area(
            pre_path,
            post_path,
            terrain_path,
            tmp_path / "benefit.tif",
        )


def test_terrain_must_actually_cover_depth_extent(tmp_path):
    from ras_commander import RasBenefits

    depth_transform = Affine(10.0, 0.0, 1000.0, 0.0, -10.0, 2000.0)
    terrain_transform = Affine(10.0, 0.0, 1005.0, 0.0, -10.0, 2000.0)
    values = np.ones((2, 2), dtype=np.float32)
    pre = _write_raster(
        tmp_path / "pre.tif",
        values,
        transform=depth_transform,
    )
    post = _write_raster(
        tmp_path / "post.tif",
        values,
        transform=depth_transform,
    )
    terrain = _write_raster(
        tmp_path / "terrain.tif",
        values,
        transform=terrain_transform,
    )

    with pytest.raises(ValueError, match="does not cover"):
        RasBenefits.create_benefit_area(
            pre,
            post,
            terrain,
            tmp_path / "benefit.tif",
        )


def test_depth_rasters_require_real_georeferencing(tmp_path):
    from ras_commander import RasBenefits

    values = np.ones((2, 2), dtype=np.float32)
    pre = _write_raster(
        tmp_path / "pre.tif",
        values,
        transform=Affine.identity(),
    )
    post = _write_raster(
        tmp_path / "post.tif",
        values,
        transform=Affine.identity(),
    )
    terrain = _write_raster(
        tmp_path / "terrain.tif",
        np.ones((20, 20), dtype=np.float32),
        transform=Affine(1.0, 0.0, -10.0, 0.0, -1.0, 10.0),
    )

    with pytest.raises(ValueError, match="valid georeferencing"):
        RasBenefits.create_benefit_area(
            pre,
            post,
            terrain,
            tmp_path / "benefit.tif",
        )


@pytest.mark.parametrize("minimum_region_pixels", [None, 5])
def test_windowed_raster_path_matches_global_array_filter_across_windows(
    monkeypatch,
    tmp_path,
    minimum_region_pixels,
):
    from ras_commander import RasBenefits

    pre = np.zeros((8, 8), dtype=np.float32)
    pre[0, 1:7] = 1.0  # six-cell component crossing two vertical windows
    pre[3:6, 0] = 1.0
    pre[5, 1] = 1.0  # four-cell component crossing a horizontal window
    pre[2, 2] = 1.0
    pre[3, 3] = 1.0  # diagonal-only cells across a window corner
    post = np.full(pre.shape, -9999.0, dtype=np.float32)
    expected = RasBenefits.classify_depth_arrays(
        pre,
        np.ma.masked_all(pre.shape, dtype=np.float32),
        minimum_region_pixels=minimum_region_pixels,
    )

    pre_path = _write_raster(tmp_path / "pre.tif", pre)
    post_path = _write_raster(tmp_path / "post.tif", post)
    terrain_path = _write_raster(
        tmp_path / "terrain.tif",
        np.ones(pre.shape, dtype=np.float32),
    )
    original_iter_windows = RasBenefits._iter_windows
    monkeypatch.setattr(
        RasBenefits,
        "_iter_windows",
        staticmethod(
            lambda width, height, window_size=1024: original_iter_windows(
                width,
                height,
                3,
            )
        ),
    )

    result = RasBenefits.create_benefit_area(
        pre_path,
        post_path,
        terrain_path,
        tmp_path / "benefit.tif",
        minimum_region_pixels=minimum_region_pixels,
    )

    with rasterio.open(result.raster_path) as src:
        actual = src.read(1)
    np.testing.assert_array_equal(actual, expected)
    assert not list(tmp_path.glob(".*.unfiltered.tif"))


@pytest.mark.parametrize("threshold", [np.nan, np.inf, -np.inf])
def test_non_finite_depth_thresholds_are_rejected(tmp_path, threshold):
    from ras_commander import BenefitAreaConfig

    with pytest.raises(ValueError, match="finite"):
        BenefitAreaConfig(
            "01",
            tmp_path / "terrain.tif",
            flood_min_depth=threshold,
        )


def test_output_tif_cannot_alias_any_raster_input(tmp_path):
    from ras_commander import RasBenefits

    pre = _write_raster(
        tmp_path / "pre.tif",
        np.ones((2, 2), dtype=np.float32),
    )
    post = _write_raster(
        tmp_path / "post.tif",
        np.zeros((2, 2), dtype=np.float32),
    )
    terrain = _write_raster(
        tmp_path / "terrain.tif",
        np.ones((2, 2), dtype=np.float32),
    )
    original_bytes = pre.read_bytes()

    with pytest.raises(ValueError, match="must not overwrite"):
        RasBenefits.create_benefit_area(pre, post, terrain, pre)

    assert pre.read_bytes() == original_bytes


def test_failed_generation_preserves_existing_output_and_cleans_staging(
    monkeypatch,
    tmp_path,
):
    from ras_commander import RasBenefits

    pre = _write_raster(
        tmp_path / "pre.tif",
        np.ones((2, 2), dtype=np.float32),
    )
    post = _write_raster(
        tmp_path / "post.tif",
        np.zeros((2, 2), dtype=np.float32),
    )
    terrain = _write_raster(
        tmp_path / "terrain.tif",
        np.ones((2, 2), dtype=np.float32),
    )
    output = tmp_path / "benefit.tif"
    output.write_bytes(b"previous-good-output")

    def fail_filter(*args, **kwargs):
        raise RuntimeError("forced filter failure")

    monkeypatch.setattr(
        RasBenefits,
        "_filter_raster_components",
        staticmethod(fail_filter),
    )

    with pytest.raises(RuntimeError, match="forced filter failure"):
        RasBenefits.create_benefit_area(pre, post, terrain, output)

    assert output.read_bytes() == b"previous-good-output"
    assert not list(tmp_path.glob(".*.staged.tif"))
    assert not list(tmp_path.glob(".*.unfiltered.tif"))


def test_failed_polygon_generation_preserves_existing_raster_and_vector(
    monkeypatch,
    tmp_path,
):
    from ras_commander import RasBenefits

    values = np.ones((2, 2), dtype=np.float32)
    pre = _write_raster(tmp_path / "pre.tif", values)
    post = _write_raster(tmp_path / "post.tif", values)
    terrain = _write_raster(tmp_path / "terrain.tif", values)
    output = tmp_path / "benefit.tif"
    polygon = tmp_path / "benefit.gpkg"
    output.write_bytes(b"previous-good-raster")
    polygon.write_bytes(b"previous-good-vector")

    monkeypatch.setattr(
        RasBenefits,
        "_write_polygons",
        staticmethod(
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("forced polygon failure")
            )
        ),
    )

    with pytest.raises(RuntimeError, match="forced polygon failure"):
        RasBenefits.create_benefit_area(
            pre,
            post,
            terrain,
            output,
            minimum_region_pixels=None,
            polygon_output=polygon,
        )

    assert output.read_bytes() == b"previous-good-raster"
    assert polygon.read_bytes() == b"previous-good-vector"
    assert not list(tmp_path.glob(".*.staged*"))


@pytest.mark.parametrize("suffix", [".gpkg", ".shp"])
def test_failed_polygon_publication_rolls_back_raster_and_vector(
    monkeypatch,
    tmp_path,
    suffix,
):
    from ras_commander import RasBenefits

    values = np.ones((2, 2), dtype=np.float32)
    pre = _write_raster(tmp_path / "pre.tif", values)
    post = _write_raster(
        tmp_path / "post.tif",
        np.full(values.shape, -9999.0, dtype=np.float32),
    )
    terrain = _write_raster(tmp_path / "terrain.tif", values)
    output = tmp_path / "benefit.tif"
    polygon = tmp_path / f"benefit{suffix}"
    output.write_bytes(b"previous-good-raster")
    polygon.write_bytes(b"previous-good-vector")
    prior_dbf = polygon.with_suffix(".dbf")
    if suffix == ".shp":
        prior_dbf.write_bytes(b"previous-good-table")

    def fail_after_vector_replace(staged_path, output_path):
        if output_path.suffix.lower() == ".shp":
            staged_files = RasBenefits._polygon_dataset_files(staged_path)
            for staged_file in staged_files[:2]:
                trailing_name = staged_file.name[len(staged_path.stem):]
                destination = output_path.with_name(output_path.stem + trailing_name)
                os.replace(staged_file, destination)
        else:
            os.replace(staged_path, output_path)
        raise RuntimeError("forced publication failure")

    monkeypatch.setattr(
        RasBenefits,
        "_publish_staged_polygon",
        staticmethod(fail_after_vector_replace),
    )

    with pytest.raises(RuntimeError, match="forced publication failure"):
        RasBenefits.create_benefit_area(
            pre,
            post,
            terrain,
            output,
            minimum_region_pixels=None,
            polygon_output=polygon,
        )

    assert output.read_bytes() == b"previous-good-raster"
    assert polygon.read_bytes() == b"previous-good-vector"
    if suffix == ".shp":
        assert prior_dbf.read_bytes() == b"previous-good-table"
    assert not list(tmp_path.glob(".*.rollback"))
    assert not list(tmp_path.glob(".*.staged*"))


def test_direct_writers_to_the_same_output_are_serialized(monkeypatch, tmp_path):
    from ras_commander import RasBenefits

    values = np.ones((3, 3), dtype=np.float32)
    pre = _write_raster(tmp_path / "pre.tif", values)
    post = _write_raster(tmp_path / "post.tif", np.zeros_like(values))
    terrain = _write_raster(tmp_path / "terrain.tif", values)
    output = tmp_path / "benefit.tif"

    original = RasBenefits._classify_to_raster
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def observed_classification(*args, **kwargs):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.1)
            return original(*args, **kwargs)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(
        RasBenefits,
        "_classify_to_raster",
        staticmethod(observed_classification),
    )
    start = threading.Barrier(3)

    def write_same_output():
        start.wait()
        return RasBenefits.create_benefit_area(
            pre,
            post,
            terrain,
            output,
            minimum_region_pixels=None,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write_same_output) for _ in range(2)]
        start.wait()
        results = [future.result(timeout=10) for future in futures]

    assert maximum_active == 1
    assert all(result.raster_path == output for result in results)
    with rasterio.open(output) as src:
        assert np.all(src.read(1) == 3)
    assert not list(tmp_path.glob(".*.staged*"))
