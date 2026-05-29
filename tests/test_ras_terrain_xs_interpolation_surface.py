"""Tests for RasTerrain.compute_xs_interpolation_surface using real HEC-RAS projects."""
import pytest
from pathlib import Path

from ras_commander import RasExamples, init_ras_project
from ras_commander.terrain import RasTerrain


@pytest.fixture(scope="module", autouse=True)
def _load_examples():
    RasExamples.get_example_projects()


@pytest.fixture
def muncie_geom_hdf(tmp_path):
    proj = RasExamples.extract_project("Muncie", output_path=tmp_path, suffix="xs_surf")
    ras = init_ras_project(proj, "6.5")
    for _, row in ras.geom_df.iterrows():
        hdf_path = Path(f"{row['full_path']}.hdf")
        if hdf_path.exists():
            return hdf_path
    pytest.skip("No geometry HDF found in Muncie project")


def test_xs_surface_hdf_channel_only(muncie_geom_hdf, tmp_path):
    result = RasTerrain.compute_xs_interpolation_surface(
        muncie_geom_hdf,
        channel_only=True,
    )

    meta = result["metadata"]
    assert meta["source_type"] == "geometry_hdf"
    assert meta["channel_only"] is True
    assert meta["cross_section_count"] > 0
    assert meta["interpolation_point_count"] > 0
    assert meta["triangle_count"] > 0
    assert not result["points"].empty
    assert not result["triangles"].empty
    assert not result["cross_sections"].empty


def test_xs_surface_hdf_full_extents(muncie_geom_hdf):
    result = RasTerrain.compute_xs_interpolation_surface(
        muncie_geom_hdf,
        channel_only=False,
    )

    meta = result["metadata"]
    assert meta["channel_only"] is False
    assert meta["footprint_source"] == "xs_extents"
    assert meta["interpolation_point_count"] > 0
    assert not result["triangles"].empty
    assert result["channel_polygon"].geometry.iloc[0].area > 0


def test_xs_surface_gpkg_output(muncie_geom_hdf, tmp_path):
    gpkg_path = tmp_path / "xs_review.gpkg"
    result = RasTerrain.compute_xs_interpolation_surface(
        muncie_geom_hdf,
        output_gpkg=gpkg_path,
    )

    assert gpkg_path.exists()
    assert result["metadata"]["output_gpkg"] == str(gpkg_path)


def test_xs_surface_raster_output(muncie_geom_hdf, tmp_path):
    rasterio = pytest.importorskip("rasterio")
    raster_path = tmp_path / "xs_surface.tif"
    result = RasTerrain.compute_xs_interpolation_surface(
        muncie_geom_hdf,
        output_raster=raster_path,
        raster_cell_size=10.0,
    )

    assert raster_path.exists()
    assert result["raster"] is not None
    assert result["raster"]["valid_cell_count"] > 0

    with rasterio.open(raster_path) as src:
        array = src.read(1)
        valid = array[array != src.nodata]
        assert valid.size > 0


def test_xs_surface_channel_has_fewer_points_than_full(muncie_geom_hdf):
    channel = RasTerrain.compute_xs_interpolation_surface(
        muncie_geom_hdf,
        channel_only=True,
    )
    full = RasTerrain.compute_xs_interpolation_surface(
        muncie_geom_hdf,
        channel_only=False,
    )

    assert (
        full["metadata"]["interpolation_point_count"]
        >= channel["metadata"]["interpolation_point_count"]
    )


def test_xs_surface_file_not_found():
    with pytest.raises(FileNotFoundError):
        RasTerrain.compute_xs_interpolation_surface(Path("nonexistent.g01.hdf"))


def test_xs_surface_raster_requires_cell_size(muncie_geom_hdf, tmp_path):
    with pytest.raises(ValueError, match="raster_cell_size is required"):
        RasTerrain.compute_xs_interpolation_surface(
            muncie_geom_hdf,
            output_raster=tmp_path / "out.tif",
        )
