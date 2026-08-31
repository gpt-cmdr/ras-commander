from __future__ import annotations

import geopandas as gpd
import pytest
from pyproj import CRS as PyprojCRS
from shapely.geometry import LineString, Polygon

import ras_commander
from ras_commander import (
    ConflationStatus,
    HydrofabricConflationResult,
    NextGenFlowpathAdapter,
    NHDPlusAdapter,
    NWMHydrofabricAdapter,
    RasHydrofabric,
)
from ras_commander.schemas import DATAFRAME_SCHEMAS, SCHEMA_VERSION

CRS = "EPSG:3857"


def _model_inputs():
    footprints = gpd.GeoDataFrame(
        {"geometry_id": ["g01"]},
        geometry=[Polygon([(-10, -20), (110, -20), (110, 20), (-10, 20)])],
        crs=CRS,
    )
    reaches = gpd.GeoDataFrame(
        {
            "geometry_id": ["g01"],
            "reach_id": ["river-a"],
            "stream_order": [4],
            "drainage_area": [50.0],
        },
        geometry=[LineString([(0, 0), (100, 0)])],
        crs=CRS,
    )
    cross_sections = gpd.GeoDataFrame(
        {
            "reach_id": ["river-a", "river-a", "river-a"],
            "xs_id": ["80", "50", "20"],
        },
        geometry=[
            LineString([(20, -10), (20, 10)]),
            LineString([(50, -10), (50, 10)]),
            LineString([(80, -10), (80, 10)]),
        ],
        crs=CRS,
    )
    return footprints, reaches, cross_sections


def _nhdplus_flowpaths():
    return gpd.GeoDataFrame(
        {
            "COMID": [101, 202, 303],
            "StreamOrde": [4, 2, 5],
            "TotDASqKm": [50.0, 10.0, 80.0],
            "FromNode": ["a", "c", "e"],
            "ToNode": ["b", "d", "f"],
            "Hydroseq": [30, 20, 10],
        },
        geometry=[
            LineString([(0, 1), (100, 1)]),
            LineString([(0, 15), (100, 15)]),
            LineString([(100, 4), (0, 4)]),
        ],
        crs=CRS,
    )


def test_conflate_scores_and_maps_geometry_reach_and_cross_sections():
    footprints, reaches, cross_sections = _model_inputs()
    hucs = gpd.GeoDataFrame(
        {"HUC12": ["010101010101", "010101010102"]},
        geometry=[
            Polygon([(-10, -20), (50, -20), (50, 20), (-10, 20)]),
            Polygon([(50, -20), (110, -20), (110, 20), (50, 20)]),
        ],
        crs=CRS,
    )

    result = RasHydrofabric.conflate(
        footprints,
        reaches,
        cross_sections,
        _nhdplus_flowpaths(),
        adapter="auto",
        hucs=hucs,
        min_confidence=0.5,
        ambiguity_margin=0.02,
        search_distance=25.0,
    )

    assert isinstance(result, HydrofabricConflationResult)
    assert result.adapter == "nhdplus"
    assert set(result.matches["element_type"]) == {
        "geometry",
        "reach",
        "cross_section",
    }
    assert set(result.matches["status"]) == {ConflationStatus.MATCHED.value}
    assert set(result.matches["feature_id"]) == {"101"}
    assert result.summary == {
        "matched": 5,
        "ambiguous": 0,
        "unmatched": 0,
        "total": 5,
    }

    reach_candidates = result.candidates.loc[
        result.candidates["element_type"] == "reach"
    ]
    assert reach_candidates.iloc[0]["feature_id"] == "101"
    assert reach_candidates.iloc[0]["candidate_rank"] == 1
    assert reach_candidates.iloc[0]["xs_intersection_count"] == 3
    assert reach_candidates.iloc[0]["sequence_consistency_score"] == pytest.approx(1.0)
    assert "DIRECTION_ALIGNED" in reach_candidates.iloc[0]["reason_codes"]

    xs_matches = result.matches.loc[
        result.matches["element_type"] == "cross_section"
    ].sort_values("flowpath_measure")
    assert xs_matches["flowpath_measure"].tolist() == pytest.approx([20, 50, 80])
    assert xs_matches["flowpath_measure_fraction"].tolist() == pytest.approx(
        [0.2, 0.5, 0.8]
    )
    assert set(xs_matches["measure_method"]) == {"intersection"}
    assert set(result.huc_intersections["huc_id"]) == {
        "010101010101",
        "010101010102",
    }
    assert result.huc_intersections["geometry_area_fraction"].sum() == pytest.approx(1.0)
    assert list(result.matches.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["hydrofabric_matches"]["columns"]
    ]
    assert list(result.candidates.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["hydrofabric_candidates"]["columns"]
    ]
    assert list(result.huc_intersections.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS[
            "hydrofabric_huc_intersections"
        ]["columns"]
    ]


def test_ambiguous_results_do_not_encode_a_candidate_as_a_match():
    footprints, reaches, cross_sections = _model_inputs()
    flowpaths = gpd.GeoDataFrame(
        {
            "COMID": [101, 102],
            "StreamOrde": [4, 4],
            "TotDASqKm": [50.0, 50.0],
        },
        geometry=[
            LineString([(0, 1), (100, 1)]),
            LineString([(0, 1), (100, 1)]),
        ],
        crs=CRS,
    )

    result = RasHydrofabric.conflate(
        footprints,
        reaches,
        cross_sections,
        flowpaths,
        search_distance=25.0,
        ambiguity_margin=0.01,
    )

    assert set(result.matches["status"]) == {"ambiguous"}
    assert result.matches["feature_id"].isna().all()
    assert set(result.matches["best_candidate_feature_id"]) == {"101"}
    assert all(
        "CLOSE_CANDIDATE_SCORES" in codes
        for codes in result.matches["reason_codes"]
    )
    assert set(result.candidates["feature_id"]) == {"101", "102"}


def test_unmatched_results_use_null_ids_not_numeric_failure_sentinels():
    footprints, reaches, cross_sections = _model_inputs()
    distant = gpd.GeoDataFrame(
        {"COMID": [999], "StreamOrde": [1], "TotDASqKm": [1.0]},
        geometry=[LineString([(1000, 1000), (1100, 1000)])],
        crs=CRS,
    )

    result = RasHydrofabric.conflate(
        footprints,
        reaches,
        cross_sections,
        distant,
        search_distance=5.0,
    )

    assert set(result.matches["status"]) == {"unmatched"}
    assert result.matches["feature_id"].isna().all()
    assert result.matches["best_candidate_feature_id"].isna().all()
    assert set(result.matches["match_method"]) == {"no_spatial_candidate"}
    assert result.candidates.empty


def test_topological_continuity_uses_adjacent_reaches_and_flowpath_nodes():
    footprints = gpd.GeoDataFrame(
        {"geometry_id": ["g01"]},
        geometry=[Polygon([(-10, -20), (210, -20), (210, 20), (-10, 20)])],
        crs=CRS,
    )
    reaches = gpd.GeoDataFrame(
        {"geometry_id": ["g01", "g01"], "reach_id": ["r1", "r2"]},
        geometry=[
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
        ],
        crs=CRS,
    )
    flowpaths = gpd.GeoDataFrame(
        {
            "COMID": [11, 12],
            "FromNode": ["n0", "n1"],
            "ToNode": ["n1", "n2"],
            "StreamOrde": [3, 3],
            "TotDASqKm": [20.0, 25.0],
        },
        geometry=[
            LineString([(0, 1), (100, 1)]),
            LineString([(100, 1), (200, 1)]),
        ],
        crs=CRS,
    )

    result = RasHydrofabric.conflate(
        footprints,
        reaches,
        None,
        flowpaths,
        search_distance=30.0,
        topology_tolerance=5.0,
        max_candidates=2,
        ambiguity_margin=0.01,
    )

    reach_candidates = result.candidates.loc[
        (result.candidates["element_type"] == "reach")
        & (result.candidates["candidate_rank"] == 1)
    ]
    assert set(reach_candidates["feature_id"]) == {"11", "12"}
    assert set(reach_candidates["topological_continuity_score"]) == {1.0}
    assert all(
        "TOPOLOGY_CONTINUOUS" in codes
        for codes in reach_candidates["reason_codes"]
    )


def test_duplicate_source_parts_are_dissolved_before_candidate_ranking():
    frame = gpd.GeoDataFrame(
        {"COMID": [7, 7], "StreamOrde": [3, 3]},
        geometry=[
            LineString([(0, 0), (1, 0)]),
            LineString([(1, 0), (2, 0)]),
        ],
        crs=CRS,
    )

    normalized = NHDPlusAdapter().normalize(frame)

    assert normalized["feature_id"].tolist() == ["7"]
    assert normalized.geometry.iloc[0].length == pytest.approx(2.0)


def test_geographic_inputs_use_an_estimated_projected_analysis_crs():
    geographic_crs = "EPSG:4326"
    footprints = gpd.GeoDataFrame(
        {"geometry_id": ["g01"]},
        geometry=[
            Polygon(
                [
                    (-95.01, 28.99),
                    (-94.99, 28.99),
                    (-94.99, 29.01),
                    (-95.01, 29.01),
                ]
            )
        ],
        crs=geographic_crs,
    )
    reaches = gpd.GeoDataFrame(
        {"geometry_id": ["g01"], "reach_id": ["r1"]},
        geometry=[LineString([(-95.005, 29.0), (-94.995, 29.0)])],
        crs=geographic_crs,
    )
    flowpaths = gpd.GeoDataFrame(
        {"id": ["wb-1"], "order": [2], "areasqkm": [5.0]},
        geometry=[LineString([(-95.005, 29.0001), (-94.995, 29.0001)])],
        crs=geographic_crs,
    )

    result = RasHydrofabric.conflate(
        footprints,
        reaches,
        None,
        flowpaths,
        adapter="nwm",
    )

    assert PyprojCRS.from_user_input(result.analysis_crs).is_projected
    assert set(result.matches["status"]) == {"matched"}
    assert set(result.matches["feature_id"]) == {"wb-1"}


@pytest.mark.parametrize(
    ("adapter", "columns", "expected_id"),
    [
        (
            NHDPlusAdapter(),
            {"COMID": [7], "StreamOrde": [3], "TotDASqKm": [12.5]},
            "7",
        ),
        (
            NWMHydrofabricAdapter(),
            {"id": ["wb-7"], "toid": ["nex-8"], "order": [3], "areasqkm": [12.5]},
            "wb-7",
        ),
        (
            NextGenFlowpathAdapter(),
            {
                "feature_id": ["flowpath-7"],
                "to_feature_id": ["flowpath-8"],
                "stream_order": [3],
                "drainage_area": [12.5],
            },
            "flowpath-7",
        ),
    ],
)
def test_builtin_adapters_normalize_flowpath_contract(adapter, columns, expected_id):
    frame = gpd.GeoDataFrame(
        columns,
        geometry=[LineString([(0, 0), (1, 0)])],
        crs=CRS,
    )
    normalized = adapter.normalize(frame)

    assert normalized.iloc[0]["feature_id"] == expected_id
    assert normalized.iloc[0]["adapter"] == adapter.name
    assert "stream_order" in normalized
    assert "drainage_area" in normalized
    assert "to_feature_id" in normalized


def test_public_exports_and_dataframe_schemas_are_registered():
    expected_exports = {
        "RasHydrofabric",
        "HydrofabricConflationResult",
        "ConflationStatus",
        "HydrofabricAdapter",
        "NHDPlusAdapter",
        "NWMHydrofabricAdapter",
        "NextGenFlowpathAdapter",
    }
    assert expected_exports <= set(ras_commander.__all__)
    assert SCHEMA_VERSION == "1.6"
    assert {
        "hydrofabric_matches",
        "hydrofabric_candidates",
        "hydrofabric_huc_intersections",
    } <= set(DATAFRAME_SCHEMAS)
