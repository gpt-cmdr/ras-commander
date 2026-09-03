from __future__ import annotations

import geopandas as gpd
import pytest
from pyproj import CRS as PyprojCRS
from shapely.geometry import LineString, Point, Polygon

import ras_commander
from ras_commander import (
    ConflationStatus,
    NetworkAdapter,
    NetworkConflationResult,
    NetworkEdgeCoverageResult,
    NetworkEdgeCoveragePlanResult,
    NextGenFlowpathAdapter,
    NHDPlusAdapter,
    NWMHydrofabricAdapter,
    RasNetworkConflation,
)
from ras_commander.schemas import DATAFRAME_SCHEMAS, SCHEMA_VERSION

CRS = "EPSG:3857"


def test_generic_network_public_names_are_canonical():
    assert RasNetworkConflation.__module__ == "ras_commander.RasNetworkConflation"
    assert NetworkConflationResult.__name__ == "NetworkConflationResult"
    assert NetworkAdapter.__name__ == "NetworkAdapter"


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


def test_classify_edges_preserves_one_model_to_many_edge_cardinality():
    footprint = gpd.GeoDataFrame(
        {"geometry_id": ["g01"]},
        geometry=[Polygon([(0, -10), (100, -10), (100, 10), (0, 10)])],
        crs=CRS,
    )
    edges = gpd.GeoDataFrame(
        {
            "feature_id": ["inside-a", "inside-b", "partial", "outside"],
            "toid": ["inside-b", "partial", "outside", None],
        },
        geometry=[
            LineString([(10, 0), (40, 0)]),
            LineString([(40, 0), (80, 0)]),
            LineString([(80, 0), (120, 0)]),
            LineString([(120, 0), (140, 0)]),
        ],
        crs=CRS,
    )

    result = RasNetworkConflation.classify_edges(
        footprint, edges, adapter="nwm"
    )

    assert isinstance(result, NetworkEdgeCoverageResult)
    assert result.adapter == "nwm"
    assert set(result.coverage_df["edge_id"]) == {
        "inside-a", "inside-b", "partial"
    }
    assert result.summary == {
        "inside": 2, "partial": 1, "outside": 0, "total": 3
    }
    partial = result.coverage_df.set_index("edge_id").loc["partial"]
    assert partial["inside_length"] == pytest.approx(20.0)
    assert partial["edge_length"] == pytest.approx(40.0)
    assert partial["inside_fraction"] == pytest.approx(0.5)
    assert partial["extent_status"] == "partial"
    assert list(result.coverage_df.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["network_edge_coverage"]["columns"]
    ]

    with_outside = RasNetworkConflation.classify_edges(
        footprint, edges, adapter="nwm", include_outside=True
    )
    assert with_outside.summary["outside"] == 1


def test_classify_edges_reports_directed_parts_and_multi_model_overlap():
    footprints = gpd.GeoDataFrame(
        {"geometry_id": ["upstream", "downstream"]},
        geometry=[
            Polygon([(-5, -10), (65, -10), (65, 10), (-5, 10)]),
            Polygon([(45, -10), (105, -10), (105, 10), (45, 10)]),
        ],
        crs=CRS,
    )
    edges = gpd.GeoDataFrame(
        {"feature_id": ["target"], "toid": [None]},
        geometry=[LineString([(0, 0), (100, 0)])],
        crs=CRS,
    )

    result = RasNetworkConflation.classify_edges(
        footprints, edges, adapter="nwm"
    )

    parts = result.coverage_parts_df.sort_values("coverage_start")
    assert list(parts["geometry_id"]) == ["upstream", "downstream"]
    assert list(parts["coverage_start"]) == pytest.approx([0.0, 45.0])
    assert list(parts["coverage_end"]) == pytest.approx([65.0, 100.0])
    assert list(parts["coverage_start_fraction"]) == pytest.approx([0.0, 0.45])
    assert list(parts["coverage_end_fraction"]) == pytest.approx([0.65, 1.0])

    summary = result.edge_summary_df.iloc[0]
    assert summary["model_count"] == 2
    assert summary["coverage_part_count"] == 2
    assert summary["union_length"] == pytest.approx(100.0)
    assert summary["union_fraction"] == pytest.approx(1.0)
    assert summary["overlap_length"] == pytest.approx(20.0)
    assert summary["gap_length"] == pytest.approx(0.0)
    assert bool(summary["fully_covered"])

    overlap = result.model_overlap_df.iloc[0]
    assert overlap["geometry_id_a"] == "downstream"
    assert overlap["geometry_id_b"] == "upstream"
    assert overlap["overlap_start"] == pytest.approx(45.0)
    assert overlap["overlap_end"] == pytest.approx(65.0)
    assert overlap["overlap_length"] == pytest.approx(20.0)
    assert list(result.coverage_parts_df.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["network_edge_coverage_parts"]["columns"]
    ]
    assert list(result.edge_summary_df.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["network_edge_coverage_summary"]["columns"]
    ]
    assert list(result.model_overlap_df.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["network_model_overlap"]["columns"]
    ]


def test_classify_edges_preserves_disjoint_coverage_parts():
    footprint = gpd.GeoDataFrame(
        {"geometry_id": ["split"]},
        geometry=[
            Polygon([(-5, -5), (25, -5), (25, 5), (-5, 5)]).union(
                Polygon([(75, -5), (105, -5), (105, 5), (75, 5)])
            )
        ],
        crs=CRS,
    )
    edges = gpd.GeoDataFrame(
        {"feature_id": ["target"]},
        geometry=[LineString([(0, 0), (100, 0)])],
        crs=CRS,
    )

    result = RasNetworkConflation.classify_edges(
        footprint, edges, adapter="nwm"
    )

    parts = result.coverage_parts_df.sort_values("part_index")
    assert len(parts) == 2
    assert list(parts["coverage_start"]) == pytest.approx([0.0, 75.0])
    assert list(parts["coverage_end"]) == pytest.approx([25.0, 100.0])
    summary = result.edge_summary_df.iloc[0]
    assert summary["union_fraction"] == pytest.approx(0.5)
    assert summary["gap_length"] == pytest.approx(50.0)


def test_plan_edge_coverage_selects_minimal_multi_model_chain_and_seam():
    footprints = gpd.GeoDataFrame(
        {"geometry_id": ["upstream", "contained", "downstream"]},
        geometry=[
            Polygon([(-5, -10), (65, -10), (65, 10), (-5, 10)]),
            Polygon([(10, -10), (35, -10), (35, 10), (10, 10)]),
            Polygon([(45, -10), (105, -10), (105, 10), (45, 10)]),
        ],
        crs=CRS,
    )
    edges = gpd.GeoDataFrame(
        {"feature_id": ["target"]},
        geometry=[LineString([(0, 0), (100, 0)])],
        crs=CRS,
    )
    coverage = RasNetworkConflation.classify_edges(
        footprints, edges, adapter="nwm"
    )

    result = RasNetworkConflation.plan_edge_coverage(coverage)

    assert isinstance(result, NetworkEdgeCoveragePlanResult)
    plan = result.plans_df.iloc[0]
    assert plan["status"] == "multi_source_ready"
    assert bool(plan["fully_covered"])
    assert plan["selected_model_count"] == 2
    assert plan["selected_slice_count"] == 2
    assert plan["source_geometry_ids"] == ("upstream", "downstream")
    assert plan["source_slice_geometry_ids"] == (
        "upstream", "downstream"
    )
    assert plan["coverage_fraction"] == pytest.approx(1.0)

    slices = result.source_slices_df.sort_values("source_order")
    assert list(slices["geometry_id"]) == ["upstream", "downstream"]
    assert list(slices["retained_start"]) == pytest.approx([0.0, 55.0])
    assert list(slices["retained_end"]) == pytest.approx([55.0, 100.0])

    seam = result.seams_df.iloc[0]
    assert seam["upstream_geometry_id"] == "upstream"
    assert seam["downstream_geometry_id"] == "downstream"
    assert seam["relationship"] == "overlap"
    assert seam["overlap_length"] == pytest.approx(20.0)
    assert seam["gap_length"] == pytest.approx(0.0)
    assert seam["seam_measure"] == pytest.approx(55.0)
    assert seam.geometry.distance(Point(55.0, 0.0)) == pytest.approx(0.0)
    assert list(result.plans_df.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["network_edge_coverage_plans"]["columns"]
    ]
    assert list(result.source_slices_df.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["network_edge_source_slices"]["columns"]
    ]
    assert list(result.seams_df.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["network_edge_seams"]["columns"]
    ]


def test_plan_edge_coverage_reports_gap_without_extending_source_ownership():
    footprints = gpd.GeoDataFrame(
        {"geometry_id": ["upstream", "downstream"]},
        geometry=[
            Polygon([(-5, -10), (45, -10), (45, 10), (-5, 10)]),
            Polygon([(52, -10), (105, -10), (105, 10), (52, 10)]),
        ],
        crs=CRS,
    )
    edges = gpd.GeoDataFrame(
        {"feature_id": ["target"]},
        geometry=[LineString([(0, 0), (100, 0)])],
        crs=CRS,
    )
    coverage = RasNetworkConflation.classify_edges(
        footprints, edges, adapter="nwm"
    )

    result = RasNetworkConflation.plan_edge_coverage(
        coverage, gap_tolerance=1.0
    )

    plan = result.plans_df.iloc[0]
    assert plan["status"] == "coverage_gap"
    assert not bool(plan["fully_covered"])
    assert plan["total_gap_length"] == pytest.approx(7.0)
    assert plan["maximum_gap_length"] == pytest.approx(7.0)
    slices = result.source_slices_df.sort_values("source_order")
    assert list(slices["retained_start"]) == pytest.approx([0.0, 52.0])
    assert list(slices["retained_end"]) == pytest.approx([45.0, 100.0])
    seam = result.seams_df.iloc[0]
    assert seam["relationship"] == "gap"
    assert seam["gap_length"] == pytest.approx(7.0)
    assert seam["seam_measure"] == pytest.approx(48.5)


def test_plan_edge_coverage_keeps_one_complete_source_over_contained_model():
    footprints = gpd.GeoDataFrame(
        {"geometry_id": ["complete", "contained"]},
        geometry=[
            Polygon([(-5, -10), (105, -10), (105, 10), (-5, 10)]),
            Polygon([(25, -10), (75, -10), (75, 10), (25, 10)]),
        ],
        crs=CRS,
    )
    edges = gpd.GeoDataFrame(
        {"feature_id": ["target"]},
        geometry=[LineString([(0, 0), (100, 0)])],
        crs=CRS,
    )
    coverage = RasNetworkConflation.classify_edges(
        footprints, edges, adapter="nwm"
    )

    result = RasNetworkConflation.plan_edge_coverage(coverage)

    plan = result.plans_df.iloc[0]
    assert plan["status"] == "single_source_ready"
    assert plan["source_geometry_ids"] == ("complete",)
    assert result.seams_df.empty


def test_plan_edge_coverage_accepts_scalar_integer_edge_id():
    footprints = gpd.GeoDataFrame(
        {"geometry_id": ["complete"]},
        geometry=[Polygon([(-5, -5), (105, -5), (105, 5), (-5, 5)])],
        crs=CRS,
    )
    edges = gpd.GeoDataFrame(
        {"feature_id": [123]},
        geometry=[LineString([(0, 0), (100, 0)])],
        crs=CRS,
    )
    coverage = RasNetworkConflation.classify_edges(
        footprints, edges, adapter="nwm"
    )

    result = RasNetworkConflation.plan_edge_coverage(
        coverage, edge_ids=123
    )

    assert list(result.plans_df["edge_id"]) == ["123"]


def test_plan_edge_coverage_distinguishes_models_from_disjoint_slices():
    footprint = gpd.GeoDataFrame(
        {"geometry_id": ["split"]},
        geometry=[
            Polygon([(-5, -5), (45, -5), (45, 5), (-5, 5)]).union(
                Polygon([(55, -5), (105, -5), (105, 5), (55, 5)])
            )
        ],
        crs=CRS,
    )
    edges = gpd.GeoDataFrame(
        {"feature_id": ["target"]},
        geometry=[LineString([(0, 0), (100, 0)])],
        crs=CRS,
    )
    coverage = RasNetworkConflation.classify_edges(
        footprint, edges, adapter="nwm"
    )

    result = RasNetworkConflation.plan_edge_coverage(
        coverage, gap_tolerance=10.0
    )

    plan = result.plans_df.iloc[0]
    assert plan["status"] == "single_source_ready"
    assert plan["selected_model_count"] == 1
    assert plan["selected_slice_count"] == 2
    assert plan["source_geometry_ids"] == ("split",)
    assert plan["source_slice_geometry_ids"] == ("split", "split")
    assert len(result.source_slices_df) == 2
    assert result.seams_df.iloc[0]["relationship"] == "gap"


def test_conflate_scores_and_maps_geometry_reach_and_cross_sections():
    footprints, reaches, cross_sections = _model_inputs()
    thalwegs = gpd.GeoDataFrame(
        {
            "reach_id": ["river-a", "river-a", "river-a"],
            "xs_id": ["80", "50", "20"],
        },
        geometry=[Point(20, 3), Point(50, 3), Point(80, 3)],
        crs=CRS,
    )
    hucs = gpd.GeoDataFrame(
        {"HUC12": ["010101010101", "010101010102"]},
        geometry=[
            Polygon([(-10, -20), (50, -20), (50, 20), (-10, 20)]),
            Polygon([(50, -20), (110, -20), (110, 20), (50, 20)]),
        ],
        crs=CRS,
    )

    result = RasNetworkConflation.conflate(
        footprints,
        reaches,
        cross_sections,
        _nhdplus_flowpaths(),
        thalweg_points=thalwegs,
        adapter="auto",
        hucs=hucs,
        min_confidence=0.5,
        ambiguity_margin=0.02,
        search_distance=25.0,
    )

    assert isinstance(result, NetworkConflationResult)
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
    metrics = result.reach_metrics.iloc[0]
    assert metrics["feature_id"] == "101"
    assert metrics["upstream_xs_id"] == "80"
    assert metrics["downstream_xs_id"] == "20"
    assert metrics["xs_intersection_count"] == 3
    assert metrics["coverage_start"] == pytest.approx(0.2)
    assert metrics["coverage_end"] == pytest.approx(0.8)
    assert metrics["coverage_ratio"] == pytest.approx(0.6)
    assert metrics["ras_length"] == pytest.approx(60.0)
    assert metrics["network_length"] == pytest.approx(60.0)
    assert metrics["network_to_ras_ratio"] == pytest.approx(1.0)
    assert metrics["centerline_offset_mean"] == pytest.approx(1.0)
    assert metrics["thalweg_offset_mean"] == pytest.approx(2.0)
    assert not metrics["flagged"]
    assert list(result.matches.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["hydrofabric_matches"]["columns"]
    ]
    assert list(result.candidates.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["hydrofabric_candidates"]["columns"]
    ]
    assert list(result.reach_metrics.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS["hydrofabric_reach_metrics"]["columns"]
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

    result = RasNetworkConflation.conflate(
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
    assert result.reach_metrics.iloc[0]["ambiguous"]
    assert result.reach_metrics.iloc[0]["flagged"]
    assert result.reach_metrics.iloc[0]["feature_id"] is None


def test_unmatched_results_use_null_ids_not_numeric_failure_sentinels():
    footprints, reaches, cross_sections = _model_inputs()
    distant = gpd.GeoDataFrame(
        {"COMID": [999], "StreamOrde": [1], "TotDASqKm": [1.0]},
        geometry=[LineString([(1000, 1000), (1100, 1000)])],
        crs=CRS,
    )

    result = RasNetworkConflation.conflate(
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
    assert result.reach_metrics.iloc[0]["flagged"]
    assert "UNMATCHED_ASSOCIATION" in result.reach_metrics.iloc[0]["reason_codes"]


def test_reach_metrics_flag_eclipsed_and_insufficient_xs_coverage():
    footprints, reaches, cross_sections = _model_inputs()
    result = RasNetworkConflation.conflate(
        footprints,
        reaches,
        cross_sections.iloc[[0]].copy(),
        _nhdplus_flowpaths(),
        search_distance=25.0,
        min_confidence=0.5,
        ambiguity_margin=0.02,
    )

    metrics = result.reach_metrics.iloc[0]
    assert metrics["upstream_xs_id"] == "80"
    assert metrics["downstream_xs_id"] == "80"
    assert metrics["eclipsed"]
    assert metrics["insufficient_coverage"]
    assert metrics["flagged"]
    assert "ECLIPSED_NO_DISTINCT_XS_LIMITS" in metrics["reason_codes"]
    assert "INSUFFICIENT_COVERAGE" in metrics["reason_codes"]


def test_reach_metrics_detect_network_divergence_from_generic_node_fields():
    footprints, reaches, cross_sections = _model_inputs()
    flowpaths = gpd.GeoDataFrame(
        {
            "COMID": [101, 111, 112],
            "FromNode": ["a", "b", "b"],
            "ToNode": ["b", "c", "d"],
            "StreamOrde": [4, 3, 3],
            "TotDASqKm": [50.0, 25.0, 25.0],
        },
        geometry=[
            LineString([(0, 1), (100, 1)]),
            LineString([(100, 1), (180, 1)]),
            LineString([(100, 1), (180, 30)]),
        ],
        crs=CRS,
    )

    result = RasNetworkConflation.conflate(
        footprints,
        reaches,
        cross_sections,
        flowpaths,
        search_distance=25.0,
        min_confidence=0.5,
        ambiguity_margin=0.02,
    )

    metrics = result.reach_metrics.iloc[0]
    assert metrics["feature_id"] == "101"
    assert metrics["connectivity_evaluable"]
    assert metrics["divergent"]
    assert metrics["flagged"]
    assert "DIVERGENT_NETWORK" in metrics["reason_codes"]


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

    result = RasNetworkConflation.conflate(
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


@pytest.mark.parametrize("adapter", [NWMHydrofabricAdapter(), NextGenFlowpathAdapter()])
def test_wb_nexus_adapters_normalize_total_area_and_native_topology(adapter):
    flowpaths = gpd.GeoDataFrame(
        {
            "id": ["wb-10", "wb-20", "wb-30", "wb-40"],
            "toid": ["nex-20", "nex-30", "tnx-1", "cnx-1"],
            "order": [2, 3, 3, 3],
            "areasqkm": [1.0, 2.0, 3.0, 4.0],
            "tot_drainage_areasqkm": [11.0, 22.0, 33.0, 44.0],
        },
        geometry=[
            LineString([(0, 0), (10, 0)]),
            LineString([(10, 0), (20, 0)]),
            LineString([(20, 0), (30, 0)]),
            LineString([(30, 0), (40, 0)]),
        ],
        crs=CRS,
    )

    normalized = adapter.normalize(flowpaths)

    assert normalized["drainage_area"].tolist() == [11.0, 22.0, 33.0, 44.0]
    assert normalized["from_node"].tolist() == [
        "nex-10",
        "nex-20",
        "nex-30",
        "nex-40",
    ]
    assert normalized["to_node"].tolist() == [
        "nex-20",
        "nex-30",
        "tnx-1",
        "cnx-1",
    ]
    assert normalized["to_feature_id"].iloc[:2].tolist() == [
        "wb-20",
        "wb-30",
    ]
    assert normalized["to_feature_id"].iloc[2:].isna().all()


def test_nextgen_native_ids_drive_topology_beyond_endpoint_tolerance():
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
            "id": ["wb-11", "wb-12"],
            "toid": ["nex-12", "nex-out"],
            "order": [3, 3],
            "areasqkm": [2.0, 3.0],
            "tot_drainage_areasqkm": [20.0, 25.0],
        },
        geometry=[
            LineString([(0, 1), (90, 1)]),
            LineString([(110, 1), (200, 1)]),
        ],
        crs=CRS,
    )

    result = RasNetworkConflation.conflate(
        footprints,
        reaches,
        None,
        flowpaths,
        adapter="nextgen",
        search_distance=8.0,
        topology_tolerance=5.0,
        max_candidates=2,
        ambiguity_margin=0.01,
    )

    reach_candidates = result.candidates.loc[
        (result.candidates["element_type"] == "reach")
        & (result.candidates["candidate_rank"] == 1)
    ]
    assert set(reach_candidates["feature_id"]) == {"wb-11", "wb-12"}
    assert set(reach_candidates["topological_continuity_score"]) == {1.0}
    assert all(
        "TOPOLOGY_CONTINUOUS" in codes
        for codes in reach_candidates["reason_codes"]
    )

    disconnected_flowpaths = flowpaths.copy()
    disconnected_flowpaths.loc[0, "toid"] = "nex-99"
    disconnected = RasNetworkConflation.conflate(
        footprints,
        reaches,
        None,
        disconnected_flowpaths,
        adapter="nextgen",
        search_distance=8.0,
        topology_tolerance=5.0,
        max_candidates=2,
        ambiguity_margin=0.01,
    )
    disconnected_rank_one = disconnected.candidates.loc[
        (disconnected.candidates["element_type"] == "reach")
        & (disconnected.candidates["candidate_rank"] == 1)
    ]
    assert set(disconnected_rank_one["topological_continuity_score"]) == {0.0}
    assert all(
        "TOPOLOGY_CONTINUOUS" not in codes
        for codes in disconnected_rank_one["reason_codes"]
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

    result = RasNetworkConflation.conflate(
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
        "RasNetworkConflation",
        "NetworkConflationResult",
        "NetworkEdgeCoverageResult",
        "NetworkEdgeCoveragePlanResult",
        "ConflationStatus",
        "NetworkAdapter",
        "NHDPlusAdapter",
        "NWMHydrofabricAdapter",
        "NextGenFlowpathAdapter",
    }
    assert expected_exports <= set(ras_commander.__all__)
    assert "RasHydrofabric" not in ras_commander.__all__
    assert "HydrofabricConflationResult" not in ras_commander.__all__
    assert "HydrofabricAdapter" not in ras_commander.__all__
    assert not hasattr(ras_commander, "RasHydrofabric")
    assert not hasattr(ras_commander, "HydrofabricConflationResult")
    assert not hasattr(ras_commander, "HydrofabricAdapter")
    assert SCHEMA_VERSION == "1.10"
    assert {
        "network_edge_coverage",
        "network_edge_coverage_parts",
        "network_edge_coverage_summary",
        "network_model_overlap",
        "network_edge_coverage_plans",
        "network_edge_source_slices",
        "network_edge_seams",
        "breakout_1d_source_models",
        "breakout_1d_source_footprints",
        "breakout_1d_source_centerlines",
        "breakout_1d_source_cross_sections",
        "breakout_1d_reach_assignments",
        "hydrofabric_matches",
        "hydrofabric_candidates",
        "hydrofabric_huc_intersections",
    } <= set(DATAFRAME_SCHEMAS)
