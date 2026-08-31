"""Focused tests for generic cross-section/terrain agreement math."""

import math

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasTerrainAgreement, TerrainAgreementResult
from ras_commander.RasTerrainAgreement import STAGE_METRICS_COLUMNS, XS_METRICS_COLUMNS
from ras_commander.schemas import DATAFRAME_SCHEMAS


def _profiles(source, terrain=None):
    terrain = source if terrain is None else terrain
    return {"River|Reach|100": np.asarray(source, dtype=float)}, {
        "River|Reach|100": np.asarray(terrain, dtype=float)
    }


def test_identical_profiles_have_perfect_agreement_and_stable_contracts():
    source, terrain = _profiles([[0, 10], [5, 0], [10, 10]])

    result = RasTerrainAgreement.compare_profiles(
        source,
        terrain,
        stages=[5],
        flag_thresholds={},
    )

    assert isinstance(result, TerrainAgreementResult)
    assert result.xs_metrics_df.columns.tolist() == XS_METRICS_COLUMNS
    assert result.stage_metrics_df.columns.tolist() == STAGE_METRICS_COLUMNS
    xs = result.xs_metrics_df.iloc[0]
    stage = result.stage_metrics_df.iloc[0]
    assert xs["rmse"] == pytest.approx(0.0)
    assert xs["nrmse"] == pytest.approx(0.0)
    assert xs["pearson_correlation"] == pytest.approx(1.0)
    assert xs["max_shifted_correlation"] == pytest.approx(1.0)
    assert xs["shift_distance"] == pytest.approx(0.0)
    assert stage["inundation_overlap"] == pytest.approx(1.0)
    assert stage["flow_area_overlap"] == pytest.approx(1.0)
    assert stage["hydraulic_radius_agreement"] == pytest.approx(1.0)
    assert result.flagged_xs.empty
    assert result.model_summary["valid_cross_section_count"] == 1
    assert [
        column["name"]
        for column in DATAFRAME_SCHEMAS["terrain_agreement_xs_metrics"]["columns"]
    ] == XS_METRICS_COLUMNS
    assert [
        column["name"]
        for column in DATAFRAME_SCHEMAS["terrain_agreement_stage_metrics"]["columns"]
    ] == STAGE_METRICS_COLUMNS


def test_residual_statistics_use_elevations_not_station_columns():
    """Regression: Ripple1D subtracts the full Nx2 arrays and dilutes RMSE."""
    source, terrain = _profiles(
        [[0, 10], [5, 0], [10, 10]],
        [[0, 11], [5, 1], [10, 11]],
    )

    result = RasTerrainAgreement.compare_profiles(
        source,
        terrain,
        stages=[5],
        flag_thresholds={},
    )

    xs = result.xs_metrics_df.iloc[0]
    assert xs["residual_mean"] == pytest.approx(-1.0)
    assert xs["residual_std"] == pytest.approx(0.0)
    assert xs["rmse"] == pytest.approx(1.0)
    assert xs["nrmse"] == pytest.approx(0.1)


def test_disconnected_wet_components_do_not_bridge_wetted_perimeter():
    """Regression: dropping dry vertices creates a false bridge between pools."""
    profile = [[0, 10], [1, 0], [2, 10], [3, 10], [4, 0], [5, 10]]
    source, terrain = _profiles(profile)

    result = RasTerrainAgreement.compare_profiles(
        source,
        terrain,
        stages=[5],
        flag_thresholds={},
    )

    stage = result.stage_metrics_df.iloc[0]
    # Four half-submerged sqrt(1^2 + 10^2) slopes; no x=1 to x=4 bridge.
    assert stage["source_wetted_perimeter"] == pytest.approx(2 * math.sqrt(101))
    assert stage["source_top_width"] == pytest.approx(2.0)
    assert stage["source_flow_area"] == pytest.approx(5.0)
    assert stage["source_hydraulic_radius"] == pytest.approx(
        5.0 / (2 * math.sqrt(101))
    )


def test_partial_submergence_uses_only_the_clipped_triangle_area():
    source, terrain = _profiles([[0, 10], [10, 0], [20, 10]])

    result = RasTerrainAgreement.compare_profiles(
        source,
        terrain,
        stages=[5],
        flag_thresholds={},
    )

    stage = result.stage_metrics_df.iloc[0]
    # Wet from station 5 through 15: two triangles, each base 5 and height 5.
    assert stage["source_top_width"] == pytest.approx(10.0)
    assert stage["source_flow_area"] == pytest.approx(25.0)


def test_inundation_overlap_uses_exact_partial_crossings():
    source, terrain = _profiles(
        [[0, 10], [10, 0], [20, 10]],
        [[0, 10], [12, 0], [20, 10]],
    )

    result = RasTerrainAgreement.compare_profiles(
        source,
        terrain,
        stages=[5],
        flag_thresholds={},
    )

    stage = result.stage_metrics_df.iloc[0]
    # Source is wet on [5, 15], terrain on [6, 16].
    assert stage["source_top_width"] == pytest.approx(10.0)
    assert stage["terrain_top_width"] == pytest.approx(10.0)
    assert stage["inundation_overlap"] == pytest.approx(9.0 / 11.0)


def test_flow_area_overlap_integrates_piecewise_linear_depth_exactly():
    source, terrain = _profiles(
        [[0, 1], [1, 0], [2, 1]],
        [[0, 1], [1, 0.5], [2, 1]],
    )

    result = RasTerrainAgreement.compare_profiles(
        source,
        terrain,
        stages=[1],
        comparison_interval=0.37,  # Deliberately does not land on the thalweg.
        flag_thresholds={},
    )

    stage = result.stage_metrics_df.iloc[0]
    assert stage["source_flow_area"] == pytest.approx(1.0)
    assert stage["terrain_flow_area"] == pytest.approx(0.5)
    assert stage["flow_area_overlap"] == pytest.approx(0.5)
    assert stage["flow_area_agreement"] == pytest.approx(2.0 / 3.0)


def test_shifted_correlation_reports_signed_station_shift():
    stations = np.arange(0.0, 21.0)
    source_elevation = (stations - 8.0) ** 2
    terrain_elevation = (stations - 10.0) ** 2
    source, terrain = _profiles(
        np.column_stack((stations, source_elevation)),
        np.column_stack((stations, terrain_elevation)),
    )

    result = RasTerrainAgreement.compare_profiles(
        source,
        terrain,
        stages=[20],
        comparison_interval=1.0,
        max_shift=4.0,
        flag_thresholds={},
    )

    xs = result.xs_metrics_df.iloc[0]
    assert xs["max_shifted_correlation"] == pytest.approx(1.0)
    # Terrain valley is two station units right of source and must move left.
    assert xs["shift_distance"] == pytest.approx(-2.0)


def test_nonoverlapping_profiles_are_invalid_and_flagged():
    source, terrain = _profiles(
        [[0, 2], [1, 0], [2, 2]],
        [[10, 2], [11, 0], [12, 2]],
    )

    result = RasTerrainAgreement.compare_profiles(source, terrain, flag_thresholds={})

    xs = result.xs_metrics_df.iloc[0]
    assert not bool(xs["valid"])
    assert bool(xs["flagged"])
    assert xs["reason_codes"] == "NO_STATION_OVERLAP"
    assert result.stage_metrics_df.empty
    assert result.flagged_xs["xs_id"].tolist() == ["River|Reach|100"]


def test_nonfinite_and_duplicate_values_have_deterministic_reason_codes():
    source, terrain = _profiles(
        [[0, 5], [1, np.nan], [2, 0], [2, 1], [4, 5]],
        [[0, 5], [2, 0], [4, 5]],
    )

    result = RasTerrainAgreement.compare_profiles(
        source,
        terrain,
        stages=[2],
        flag_thresholds={},
    )

    xs = result.xs_metrics_df.iloc[0]
    assert xs["valid"]
    assert xs["reason_codes"] == (
        "DUPLICATE_SOURCE_STATIONS;NONFINITE_SOURCE_VALUES_DROPPED"
    )
    assert xs["flag_reasons"] == "NONFINITE_SOURCE_VALUES_DROPPED"


def test_constant_profiles_handle_zero_normalization_without_inf():
    source, terrain = _profiles([[0, 1], [5, 1], [10, 1]])

    result = RasTerrainAgreement.compare_profiles(
        source,
        terrain,
        stages=[2],
        flag_thresholds={},
    )

    xs = result.xs_metrics_df.iloc[0]
    assert xs["rmse"] == pytest.approx(0.0)
    assert np.isnan(xs["nrmse"])
    assert xs["pearson_correlation"] == pytest.approx(1.0)
    assert "ZERO_SOURCE_ELEVATION_RANGE" in xs["reason_codes"]
    assert np.isfinite(result.stage_metrics_df.iloc[0]["hydraulic_radius_agreement"])


def test_threshold_flags_are_configurable():
    source, terrain = _profiles(
        [[0, 10], [5, 0], [10, 10]],
        [[0, 10], [5, 4], [10, 10]],
    )

    result = RasTerrainAgreement.compare_profiles(
        source,
        terrain,
        stages=[5],
        flag_thresholds={"max_nrmse": 0.1},
    )

    xs = result.xs_metrics_df.iloc[0]
    assert xs["nrmse"] > 0.1
    assert xs["flag_reasons"] == "NRMSE_HIGH"


def test_mapping_and_dataframe_inputs_are_sorted_by_cross_section_id():
    profile = np.asarray([[0, 2], [1, 0], [2, 2]], dtype=float)
    source_df = pd.DataFrame(
        {
            "xs_id": ["b", "a"],
            "station_elevation": [profile, profile],
            "River": ["R", "R"],
            "Reach": ["Reach", "Reach"],
            "RS": ["2", "1"],
        }
    )
    terrain = {"b": profile, "a": profile}

    result = RasTerrainAgreement.compare_profiles(
        source_df,
        terrain,
        stages=[1],
        flag_thresholds={},
    )

    assert result.xs_metrics_df["xs_id"].tolist() == ["a", "b"]
    assert result.stage_metrics_df["xs_id"].tolist() == ["a", "b"]


def test_analyze_samples_an_arbitrary_raster(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    geopandas = pytest.importorskip("geopandas")
    shapely_geometry = pytest.importorskip("shapely.geometry")
    from rasterio.transform import from_origin

    raster = tmp_path / "terrain.tif"
    values = np.arange(10, dtype=np.float32).reshape(1, 10)
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=10,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0, 1, 1, 1),
        nodata=-9999,
    ) as dataset:
        dataset.write(values, 1)

    profile = np.column_stack((np.arange(10, dtype=float), np.arange(10, dtype=float)))
    cross_sections = geopandas.GeoDataFrame(
        {
            "xs_id": ["xs"],
            "station_elevation": [profile],
            "geometry": [shapely_geometry.LineString([(0.5, 0.5), (9.5, 0.5)])],
        },
        crs="EPSG:3857",
    )

    result = RasTerrainAgreement.analyze(
        cross_sections,
        terrain_raster=raster,
        sample_interval=1.0,
        stages=[8.5],
        flag_thresholds={},
    )

    assert result.xs_metrics_df.iloc[0]["rmse"] == pytest.approx(0.0)
    assert result.xs_metrics_df.iloc[0]["n_terrain_points"] == 10


def test_raster_sampling_without_profile_crs_retains_invalid_xs(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    raster = tmp_path / "terrain.tif"
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=3,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0, 1, 1, 1),
    ) as dataset:
        dataset.write(np.asarray([[0, 1, 2]], dtype=np.float32), 1)

    source = {
        "xs": {
            "station_elevation": [[0, 0], [2, 2]],
            "geometry": [(0.5, 0.5), (2.5, 0.5)],
        }
    }
    # Use a real geometry, but deliberately omit profile_crs.
    source["xs"]["geometry"] = pytest.importorskip("shapely.geometry").LineString(
        source["xs"]["geometry"]
    )

    result = RasTerrainAgreement.analyze(
        source,
        terrain_raster=raster,
        stages=[1],
        flag_thresholds={},
    )

    xs = result.xs_metrics_df.iloc[0]
    assert not xs["valid"]
    assert xs["reason_codes"] == "MISSING_PROFILE_CRS"


def test_raster_sampling_rejects_out_of_bounds_even_without_raster_nodata(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    shapely_geometry = pytest.importorskip("shapely.geometry")
    from rasterio.transform import from_origin

    raster = tmp_path / "terrain.tif"
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=3,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0, 1, 1, 1),
        nodata=None,
    ) as dataset:
        dataset.write(np.asarray([[0, 1, 2]], dtype=np.float32), 1)

    source = {
        "xs": {
            "station_elevation": [[0, 0], [4, 4]],
            "geometry": shapely_geometry.LineString([(-0.5, 0.5), (3.5, 0.5)]),
        }
    }
    result = RasTerrainAgreement.analyze(
        source,
        terrain_raster=raster,
        profile_crs="EPSG:3857",
        sample_interval=1,
        stages=[1],
        flag_thresholds={},
    )

    xs = result.xs_metrics_df.iloc[0]
    assert not xs["valid"]
    assert "RASTER_OUT_OF_BOUNDS_SAMPLES" in xs["reason_codes"]


def test_internal_raster_nodata_gap_is_not_interpolated_across(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    shapely_geometry = pytest.importorskip("shapely.geometry")
    from rasterio.transform import from_origin

    raster = tmp_path / "terrain.tif"
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=5,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0, 1, 1, 1),
        nodata=-9999,
    ) as dataset:
        dataset.write(np.asarray([[0, 1, -9999, 3, 4]], dtype=np.float32), 1)

    source = {
        "xs": {
            "station_elevation": [[0, 0], [4, 4]],
            "geometry": shapely_geometry.LineString([(0.5, 0.5), (4.5, 0.5)]),
        }
    }
    result = RasTerrainAgreement.analyze(
        source,
        terrain_raster=raster,
        profile_crs="EPSG:3857",
        sample_interval=1,
        stages=[3],
        flag_thresholds={},
    )

    xs = result.xs_metrics_df.iloc[0]
    assert not xs["valid"]
    assert "RASTER_INTERNAL_NODATA_GAP" in xs["reason_codes"]
    assert result.stage_metrics_df.empty


def test_registered_sampling_rejects_multiple_terrain_layers(tmp_path):
    geopandas = pytest.importorskip("geopandas")
    shapely_geometry = pytest.importorskip("shapely.geometry")

    project = tmp_path / "Model.prj"
    project.write_text("Proj Title=Model\n", encoding="utf-8")
    rasmap = tmp_path / "Model.rasmap"
    rasmap.write_text(
        """<RASMapper><Terrains>
        <Layer Name="Terrain A" Type="TerrainLayer" Filename=".\\Terrain\\A.hdf" />
        <Layer Name="Terrain B" Type="TerrainLayer" Filename=".\\Terrain\\B.hdf" />
        </Terrains></RASMapper>""",
        encoding="utf-8",
    )
    geom_hdf = tmp_path / "Model.g01.hdf"
    geom_hdf.write_bytes(b"exists")
    source = geopandas.GeoDataFrame(
        {
            "xs_id": ["xs"],
            "station_elevation": [np.asarray([[0, 1], [1, 0], [2, 1]])],
            "geometry": [shapely_geometry.LineString([(0, 0), (2, 0)])],
        },
        crs="EPSG:3857",
    )

    with pytest.raises(ValueError, match="sampling is ambiguous"):
        RasTerrainAgreement.analyze(
            source,
            ras_project_path=project,
            geom_hdf_path=geom_hdf,
            stages=[1],
        )


def test_analyze_requires_exactly_one_terrain_source():
    source = {"xs": np.asarray([[0, 1], [1, 0], [2, 1]], dtype=float)}

    with pytest.raises(ValueError, match="exactly one"):
        RasTerrainAgreement.analyze(source)
    with pytest.raises(ValueError, match="exactly one"):
        RasTerrainAgreement.analyze(
            source,
            terrain_profiles=source,
            terrain_raster="terrain.tif",
        )
