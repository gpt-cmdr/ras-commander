"""Focused real-format contracts for the one-reach RasBreakout1D MVP."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import h5py
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon

import ras_commander
from ras_commander import (
    Breakout1DDomainSelection,
    Breakout1DPlan,
    Breakout1DSourceCatalog,
    GeomParser,
    RasBreakout1D,
    RasPrj,
)
from ras_commander.schemas import DATAFRAME_SCHEMAS


def _xs_block(station: int, downstream_length: int, y: int) -> str:
    return f"""Type RM Length L Ch R = 1 ,{station},{downstream_length},{downstream_length},{downstream_length}
BEGIN DESCRIPTION:
XS {station}
END DESCRIPTION:
XS GIS Cut Line= 2
               0{y:16d}             100{y:16d}
#Sta/Elev= 5
       0     110      25     105      50     100      75     105     100     110
#Mann= 3 , 0 , 0
       0    .06       0      25    .035       0      75    .055       0
Bank Sta=25,75
Levee= 1 , 20 , 108 , 1 , 80 , 108
#XS Ineff= 2 , 0
       0     106      15     106      85     106     100     106
Permanent Ineff=
       F       F
XS HTab Starting El and Incr=100,0.5,40
XS HTab Horizontal Distribution= 0

"""


def _structure_block(type_code: int, station: int, label: str) -> str:
    marker = "IW Pilot Flow=0" if type_code == 4 else "Bridge Culvert-0,0,1,-1, 0"
    return f"""Type RM Length L Ch R = {type_code} ,{station},,,
BEGIN DESCRIPTION:
{label}
END DESCRIPTION:
{marker}
#Inline Weir SE= 2
       0     106     100     106
BC HTab HWMax=120
"""


def _write_project(root: Path) -> RasPrj:
    root.mkdir()
    base = "Source"
    (root / f"{base}.prj").write_text(
        "Proj Title=Source\n"
        "Current Plan=p01\n"
        "Default Exp/Contr=0.3,0.1\n"
        "English Units\n"
        "Geom File=g01\n"
        "Flow File=f01\n"
        "Plan File=p01\n",
        encoding="utf-8",
    )
    (root / f"{base}.p01").write_text(
        "Plan Title=Base Plan\n"
        "Program Version=6.60\n"
        "Short Identifier=Base\n"
        "Geom File=g01\n"
        "Flow File=f01\n"
        "Run HTab= 1\n",
        encoding="utf-8",
    )
    geom = (
        "Geom Title=Source Geometry\n"
        "Program Version=6.60\n"
        "Viewing Rectangle= 0 , 100 , 100 , 0\n"
        "Use User Specified Reach Order=0\n"
        "River Reach=Other River,Other Reach\n"
        "Reach XY= 2\n"
        "               0               0             100               0\n"
        + _xs_block(50, 0, -10)
        + "River Reach=Main River,Main Reach\n"
        "Reach XY= 2\n"
        "              50             100              50               0\n"
        + _xs_block(500, 100, 90)
        + _xs_block(400, 100, 80)
        + _structure_block(4, 350, "Inline structure")
        + _xs_block(300, 100, 70)
        + _structure_block(2, 250, "Culvert")
        + _xs_block(200, 100, 60)
        + _xs_block(100, 0, 50)
        + "Junct Name=Removed Junction\n"
        "Junct X Y & Text X Y=0,0,0,0\n"
    )
    (root / f"{base}.g01").write_text(geom, encoding="utf-8")
    (root / f"{base}.f01").write_text(
        "Flow Title=Source Flow\n"
        "Program Version=6.60\n"
        "Number of Profiles= 2\n"
        "Profile Names=Low,High\n"
        "River Rch & RM=Main River,Main Reach,500\n"
        "     100     200\n"
        "River Rch & RM=Main River,Main Reach,300\n"
        "     120     220\n"
        "River Rch & RM=Main River,Main Reach,100\n"
        "     140     240\n"
        "Boundary for River Rch & Prof#=Main River,Main Reach, 1\n"
        "Up Type= 0\n"
        "Dn Type= 3\n"
        "Dn Slope=   0.001\n"
        "Boundary for River Rch & Prof#=Main River,Main Reach, 2\n"
        "Up Type= 0\n"
        "Dn Type= 3\n"
        "Dn Slope=   0.002\n",
        encoding="utf-8",
    )
    ras = RasPrj()
    ras.initialize(
        root,
        "Ras.exe",
        suppress_logging=True,
        load_results_summary=False,
        load_hdf_metadata=False,
    )
    return ras


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_multi_model_breakout_public_names_are_exported():
    assert {
        "RasBreakout1D",
        "Breakout1DSourceCatalog",
        "Breakout1DPlan",
    } <= set(ras_commander.__all__)


def test_catalog_sources_deduplicates_geometry_and_round_trips_geoparquet(
    tmp_path: Path,
):
    first = _write_project(tmp_path / "first")
    duplicate = _write_project(tmp_path / "duplicate")
    footprints = gpd.GeoDataFrame(
        {"geometry_id": ["first", "duplicate"]},
        geometry=[
            Polygon([(-10, -20), (110, -20), (110, 120), (-10, 120)]),
            Polygon([(-10, -20), (110, -20), (110, 120), (-10, 120)]),
        ],
        crs="EPSG:3857",
    )

    catalog = RasBreakout1D.catalog_sources(
        {"first": first, "duplicate": duplicate},
        model_footprints=footprints,
        analysis_crs="EPSG:3857",
    )

    assert isinstance(catalog, Breakout1DSourceCatalog)
    assert catalog.summary == {
        "source_models": 2,
        "included_models": 1,
        "duplicate_models": 1,
        "reaches": 2,
        "cross_sections": 6,
    }
    models = catalog.models_df.set_index("geometry_id")
    assert bool(models.loc["duplicate", "included"])
    assert models.loc["first", "duplicate_of"] == "duplicate"
    assert not bool(models.loc["first", "included"])
    assert models.loc["duplicate", "profile_names"] == ("Low", "High")
    assert list(catalog.footprints_gdf["geometry_id"]) == ["duplicate"]
    assert catalog.centerlines_gdf["reach_id"].str.startswith(
        "duplicate::"
    ).all()
    assert catalog.cross_sections_gdf["xs_id"].is_unique
    for frame, schema_name in (
        (catalog.models_df, "breakout_1d_source_models"),
        (catalog.footprints_gdf, "breakout_1d_source_footprints"),
        (catalog.centerlines_gdf, "breakout_1d_source_centerlines"),
        (catalog.cross_sections_gdf, "breakout_1d_source_cross_sections"),
    ):
        assert list(frame.columns) == [
            column["name"] for column in DATAFRAME_SCHEMAS[schema_name]["columns"]
        ]

    destination = catalog.write(tmp_path / "catalog")
    loaded = Breakout1DSourceCatalog.read(destination)
    assert loaded.summary == catalog.summary
    assert loaded.analysis_crs == catalog.analysis_crs
    assert loaded.footprints_gdf.geometry.equals(catalog.footprints_gdf.geometry)


def test_catalog_sources_requires_projected_crs(tmp_path: Path):
    source = _write_project(tmp_path / "source")

    with pytest.raises(ValueError, match="must be projected"):
        RasBreakout1D.catalog_sources(
            {"source": source}, analysis_crs="EPSG:4326"
        )


def test_catalog_sources_rejects_unknown_plan_number_model_id(tmp_path: Path):
    source = _write_project(tmp_path / "source")

    with pytest.raises(ValueError, match="unknown source model IDs"):
        RasBreakout1D.catalog_sources(
            {"source": source},
            plan_numbers={"different-source": "01"},
            analysis_crs="EPSG:3857",
        )


def test_plan_network_edge_filters_footprint_only_models_and_orders_sources():
    crs = "EPSG:3857"
    models = pd.DataFrame(
        {
            "geometry_id": ["upstream", "downstream", "false-positive"],
            "included": [True, True, True],
        }
    )
    footprints = gpd.GeoDataFrame(
        {"geometry_id": ["upstream", "downstream", "false-positive"]},
        geometry=[
            Polygon([(-5, -10), (65, -10), (65, 10), (-5, 10)]),
            Polygon([(45, -10), (105, -10), (105, 10), (45, 10)]),
            Polygon([(-5, -30), (105, -30), (105, 30), (-5, 30)]),
        ],
        crs=crs,
    )
    centerlines = gpd.GeoDataFrame(
        {
            "geometry_id": ["upstream", "downstream", "false-positive"],
            "reach_id": ["upstream::R::1", "downstream::R::1", "false::R::1"],
            "river": ["R", "R", "Other"],
            "reach": ["1", "1", "1"],
        },
        geometry=[
            LineString([(0, 0), (65, 0)]),
            LineString([(45, 0), (100, 0)]),
            LineString([(0, 20), (100, 20)]),
        ],
        crs=crs,
    )
    xs_rows = []
    for geometry_id, reach_id, y0, y1, measures in (
        ("upstream", "upstream::R::1", -10, 10, (10, 35, 60)),
        ("downstream", "downstream::R::1", -10, 10, (50, 70, 90)),
        ("false-positive", "false::R::1", 15, 25, (20, 40, 80)),
    ):
        for station, measure in zip((300, 200, 100), measures):
            xs_rows.append(
                {
                    "geometry_id": geometry_id,
                    "reach_id": reach_id,
                    "xs_id": f"{reach_id}::{station}",
                    "river": "R" if geometry_id != "false-positive" else "Other",
                    "reach": "1",
                    "station": str(station),
                    "geometry": LineString([(measure, y0), (measure, y1)]),
                }
            )
    cross_sections = gpd.GeoDataFrame(xs_rows, geometry="geometry", crs=crs)
    catalog = Breakout1DSourceCatalog(
        models_df=models,
        footprints_gdf=footprints,
        centerlines_gdf=centerlines,
        cross_sections_gdf=cross_sections,
        analysis_crs=crs,
        parameters={},
    )
    edges = gpd.GeoDataFrame(
        {"feature_id": ["target"]},
        geometry=[LineString([(0, 0), (100, 0)])],
        crs=crs,
    )

    plan = RasBreakout1D.plan_network_edge(
        catalog,
        edges,
        adapter="nwm",
        edge_id="target",
        max_centerline_offset=5.0,
    )

    assert isinstance(plan, Breakout1DPlan)
    assert plan.status == "multi_source_ready"
    assert list(plan.source_slices_df["geometry_id"]) == [
        "upstream",
        "downstream",
    ]
    assert list(plan.source_models_df["geometry_id"]) == [
        "upstream",
        "downstream",
    ]
    assignments = plan.reach_assignments_df.set_index("geometry_id")
    assert assignments.loc["upstream", "status"] == "confirmed"
    assert assignments.loc["downstream", "status"] == "confirmed"
    assert assignments.loc["false-positive", "status"] == "unmatched"
    assert assignments.loc["false-positive", "reason_codes"] == (
        "INSUFFICIENT_XS_INTERSECTIONS",
    )
    assert list(plan.reach_assignments_df.columns) == [
        column["name"]
        for column in DATAFRAME_SCHEMAS[
            "breakout_1d_reach_assignments"
        ]["columns"]
    ]
    assert plan.seams_df.iloc[0]["seam_measure"] == pytest.approx(55.0)


def _write_steady_hdf(
    path: Path,
    stations: list[int],
    *,
    wse_offset: float = 0.0,
) -> None:
    attributes_dtype = np.dtype(
        [
            ("River", "S32"),
            ("Reach", "S32"),
            ("RS", "S32"),
            ("Len Channel", "f4"),
        ]
    )
    base = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
    attributes = np.array(
        [
            (
                b"Main River",
                b"Main Reach",
                str(station).encode(),
                0.0 if index == len(stations) - 1 else 100.0,
            )
            for index, station in enumerate(stations)
        ],
        dtype=attributes_dtype,
    )
    low_wse = np.array([100.0 + index + wse_offset for index in range(len(stations))])
    high_wse = low_wse + 2.0
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("Geometry/Cross Sections/Attributes", data=attributes)
        hdf.create_dataset(f"{base}/Profile Names", data=np.array([b"Low", b"High"]))
        hdf.create_dataset(
            f"{base}/Cross Sections/Water Surface",
            data=np.vstack([low_wse, high_wse]),
        )
        hdf.create_dataset(
            f"{base}/Cross Sections/Flow",
            data=np.vstack(
                [np.full(len(stations), 100.0), np.full(len(stations), 200.0)]
            ),
        )
        hdf.create_dataset(
            f"{base}/Cross Sections/Additional Variables/Maximum Depth Total",
            data=np.vstack([np.full(len(stations), 5.0), np.full(len(stations), 7.0)]),
        )
        hdf.create_dataset(
            f"{base}/Cross Sections/Additional Variables/Hydraulic Depth Channel",
            data=np.vstack([np.full(len(stations), 3.0), np.full(len(stations), 4.0)]),
        )


def test_extract_reach_preserves_blocks_relationships_and_flow_changes(tmp_path: Path):
    source = _write_project(tmp_path / "source")
    source_geom = Path(source.geom_df.iloc[0]["full_path"])
    before = _digest(source_geom)

    result = RasBreakout1D.extract_reach(
        source,
        tmp_path / "breakout",
        "Main River",
        "Main Reach",
        upstream_station=425,
        downstream_station=175,
        boundary_mode="preserve",
    )

    assert result.selection.stations == ("400", "300", "200")
    assert result.validation.is_valid
    assert _digest(source_geom) == before
    assert result.destination_ras.plan_df.iloc[0]["flow_type"] == "Steady"
    assert (
        Path(result.destination_ras.plan_df.iloc[0]["Geom Path"])
        == result.geometry_file
    )
    assert Path(result.destination_ras.plan_df.iloc[0]["Flow Path"]) == result.flow_file

    project_lines = result.project_file.read_text(encoding="utf-8").splitlines()
    assert project_lines.index("English Units") < project_lines.index("Geom File=g01")
    assert project_lines.index("Geom File=g01") < project_lines.index("Plan File=p01")
    assert b"\r\n" in result.project_file.read_bytes()
    assert b"\r\n" in result.plan_file.read_bytes()
    assert b"\r\n" in result.geometry_file.read_bytes()

    geometry_text = result.geometry_file.read_text(encoding="utf-8")
    assert "River Reach=Other River,Other Reach" not in geometry_text
    assert "Junct Name=" not in geometry_text
    assert "Type RM Length L Ch R = 1 ,500" not in geometry_text
    assert "Type RM Length L Ch R = 1 ,100" not in geometry_text
    assert "Inline structure" in geometry_text
    assert "Culvert" in geometry_text
    assert "#Mann= 3" in geometry_text
    assert "Levee= 1" in geometry_text
    assert "#XS Ineff= 2" in geometry_text
    assert "XS HTab Starting El and Incr=" in geometry_text
    assert "Type RM Length L Ch R = 1 ,200,0,0,0" in geometry_text
    centerline = GeomParser.get_river_centerlines(result.geometry_file).iloc[0].geometry
    assert list(centerline.coords) == [(50.0, 80.0), (50.0, 60.0)]

    from ras_commander import RasSteady

    flow = RasSteady.read_flow_file(result.flow_file)
    assert [(item["station"], item["flows"]) for item in flow["flow_changes"]] == [
        ("400", [100.0, 200.0]),
        ("300", [120.0, 220.0]),
    ]
    comparison = RasBreakout1D.compare_geometry(
        source_geom, result.geometry_file, result.selection
    )
    assert comparison["content_equal"].all()
    assert comparison.attrs["structure_blocks_equal"] is True
    assert comparison.attrs["source_structure_count"] == 2


def test_supplied_xs_selector_requires_a_continuous_source_slice(tmp_path: Path):
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])

    selection = RasBreakout1D.select_by_cross_sections(
        geom, "Main River", "Main Reach", [400, 300, 200]
    )
    assert selection.stations == ("400", "300", "200")
    assert selection.selector == "cross_sections"

    with pytest.raises(ValueError, match="contiguous"):
        RasBreakout1D.select_by_cross_sections(
            geom, "Main River", "Main Reach", [400, 200]
        )


def test_polygon_selector_resolves_one_reach_and_fills_intervening_xs(tmp_path: Path):
    shapely = pytest.importorskip("shapely.geometry")
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])
    polygon = shapely.box(-1, 55, 101, 85)

    selection = RasBreakout1D.select_by_polygon(
        geom, polygon, river="Main River", reach="Main Reach"
    )

    assert selection.selector == "polygon"
    assert selection.stations == ("400", "300", "200")

    network_selection = RasBreakout1D.select_by_network_edge(
        geom,
        shapely.LineString([(50, 55), (50, 85)]),
        river="Main River",
        reach="Main Reach",
    )
    assert network_selection.selector == "network_edge"
    assert network_selection.stations == ("400", "300", "200", "100")

    direct_only = RasBreakout1D.select_by_network_edge(
        geom,
        shapely.LineString([(50, 55), (50, 85)]),
        river="Main River",
        reach="Main Reach",
        downstream_overlap_xs=0,
    )
    assert direct_only.stations == selection.stations


def test_network_selector_validates_downstream_overlap(tmp_path: Path):
    shapely = pytest.importorskip("shapely.geometry")
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])
    segment = shapely.LineString([(50, 55), (50, 85)])

    with pytest.raises(TypeError, match="must be an integer"):
        RasBreakout1D.select_by_network_edge(
            geom, segment, downstream_overlap_xs=1.5
        )
    with pytest.raises(ValueError, match="must be non-negative"):
        RasBreakout1D.select_by_network_edge(
            geom, segment, downstream_overlap_xs=-1
        )

    alias = RasBreakout1D.select_by_network_segment(
        geom, segment, downstream_overlap_xs=0
    )
    assert alias.selector == "network_edge"


def test_network_selector_adds_overlap_after_one_xs_intersection(tmp_path: Path):
    shapely = pytest.importorskip("shapely.geometry")
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])
    one_xs_edge = shapely.LineString([(50, 79), (50, 81)])

    selection = RasBreakout1D.select_by_network_edge(
        geom,
        one_xs_edge,
        river="Main River",
        reach="Main Reach",
    )

    assert selection.stations == ("400", "300")


def test_network_selector_applies_explicit_channel_distance_buffers(tmp_path: Path):
    shapely = pytest.importorskip("shapely.geometry")
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])
    segment = shapely.LineString([(50, 55), (50, 85)])

    selection = RasBreakout1D.select_by_network_edge(
        geom,
        segment,
        river="Main River",
        reach="Main Reach",
        downstream_overlap_xs=0,
        upstream_buffer_distance=50,
        downstream_buffer_distance=50,
    )

    assert selection.stations == ("500", "400", "300", "200", "100")

    with pytest.raises(ValueError, match="upstream_buffer_distance"):
        RasBreakout1D.select_by_network_edge(
            geom, segment, upstream_buffer_distance=-1
        )
    with pytest.raises(ValueError, match="downstream_buffer_distance"):
        RasBreakout1D.select_by_network_edge(
            geom, segment, downstream_buffer_distance=float("nan")
        )


def test_network_edge_domains_use_full_inside_defaults_and_strict_overlap(
    tmp_path: Path,
):
    shapely = pytest.importorskip("shapely.geometry")
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])
    segment = shapely.LineString([(50, 65), (50, 85)])

    domains = RasBreakout1D.select_domains_by_network_edge(
        geom,
        segment,
        river="Main River",
        reach="Main Reach",
        inside_fraction=1.0,
    )

    assert isinstance(domains, Breakout1DDomainSelection)
    assert domains.direct_selection.stations == ("400", "300")
    assert domains.inundation_selection.stations == ("400", "300", "200")
    assert domains.computation_selection.stations == (
        "500", "400", "300", "200"
    )
    assert domains.main_channel_length == pytest.approx(400.0)
    assert domains.upstream_buffer_distance == pytest.approx(40.0)
    assert domains.downstream_buffer_distance == pytest.approx(100.0)
    assert domains.upstream_buffer_applied == pytest.approx(100.0)
    assert domains.downstream_buffer_applied == pytest.approx(100.0)
    assert domains.automatic_upstream_buffer is True
    assert domains.automatic_downstream_buffer is True
    assert domains.inundation_overlap_xs == 1
    assert domains.inundation_overlap_xs_applied == 1

    partial = RasBreakout1D.select_domains_by_network_edge(
        geom,
        segment,
        inside_fraction=0.75,
    )
    assert (
        partial.computation_selection.stations
        == partial.inundation_selection.stations
    )
    assert partial.upstream_buffer_distance == 0.0
    assert partial.downstream_buffer_distance == 0.0
    assert partial.downstream_buffer_applied == 0.0
    assert partial.automatic_upstream_buffer is False
    assert partial.automatic_downstream_buffer is False


def test_network_edge_domains_accept_independent_explicit_overrides(tmp_path: Path):
    shapely = pytest.importorskip("shapely.geometry")
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])
    segment = shapely.LineString([(50, 65), (50, 85)])

    domains = RasBreakout1D.select_domains_by_network_edge(
        geom,
        segment,
        inside_fraction=1.0,
        upstream_buffer_distance=0,
        downstream_buffer_distance=150,
    )
    assert domains.computation_selection.stations == (
        "400", "300", "200", "100"
    )
    assert domains.automatic_upstream_buffer is False
    assert domains.automatic_downstream_buffer is False
    assert domains.upstream_buffer_applied == 0.0
    assert domains.downstream_buffer_applied == pytest.approx(200.0)

    terminated = RasBreakout1D.select_domains_by_network_edge(
        geom,
        segment,
        inside_fraction=1.0,
        upstream_buffer_distance=0,
        downstream_buffer_distance=10_000,
    )
    assert terminated.computation_selection.stations == (
        "400", "300", "200", "100"
    )
    assert terminated.downstream_buffer_distance == pytest.approx(10_000.0)
    assert terminated.downstream_buffer_applied == pytest.approx(200.0)

    terminus_edge = shapely.LineString([(50, 49), (50, 51)])
    terminus = RasBreakout1D.select_domains_by_network_edge(
        geom,
        terminus_edge,
        inside_fraction=1.0,
        upstream_buffer_distance=50,
        downstream_buffer_distance=0,
    )
    assert terminus.direct_selection.stations == ("100",)
    assert terminus.inundation_selection.stations == ("100",)
    assert terminus.computation_selection.stations == ("200", "100")
    assert terminus.inundation_overlap_xs == 1
    assert terminus.inundation_overlap_xs_applied == 0

    alias = RasBreakout1D.select_network_edge_domains(
        geom,
        segment,
        inside_fraction=0.75,
    )
    assert (
        alias.computation_selection.stations
        == alias.inundation_selection.stations
    )

    with pytest.raises(ValueError, match="inside_fraction"):
        RasBreakout1D.select_domains_by_network_edge(
            geom, segment, inside_fraction=1.01
        )
    with pytest.raises(TypeError, match="inundation_overlap_xs"):
        RasBreakout1D.select_domains_by_network_edge(
            geom, segment, inundation_overlap_xs=True
        )
    with pytest.raises(ValueError, match="upstream_buffer_fraction"):
        RasBreakout1D.select_domains_by_network_edge(
            geom, segment, upstream_buffer_fraction=1.01
        )


def test_run_is_explicit_and_delegates_to_rascmdr(tmp_path: Path, monkeypatch):
    source = _write_project(tmp_path / "source")
    result = RasBreakout1D.extract_reach(
        source,
        tmp_path / "breakout",
        "Main River",
        "Main Reach",
        400,
        200,
        boundary_mode="preserve",
    )
    observed = {}

    def fake_compute(plan_number, **kwargs):
        observed["plan_number"] = plan_number
        observed.update(kwargs)
        return "computed"

    rascmdr_module = importlib.import_module("ras_commander.RasCmdr")
    monkeypatch.setattr(
        rascmdr_module.RasCmdr, "compute_plan", staticmethod(fake_compute)
    )

    assert RasBreakout1D.run(result, verify=False, num_cores=2) == "computed"
    assert observed["plan_number"] == "01"
    assert observed["ras_object"] is result.destination_ras
    assert observed["verify"] is False
    assert observed["clear_geompre"] is True
    assert observed["num_cores"] == 2


def test_internal_cut_uses_source_result_wse_and_compares_retained_results(
    tmp_path: Path,
):
    source = _write_project(tmp_path / "source")
    source_hdf = tmp_path / "source" / "Source.p01.hdf"
    _write_steady_hdf(source_hdf, [500, 400, 300, 200, 100])

    result = RasBreakout1D.extract_reach(
        source,
        tmp_path / "breakout",
        "Main River",
        "Main Reach",
        400,
        200,
        boundary_mode="source_results",
        source_plan_hdf=source_hdf,
    )

    from ras_commander import RasSteady

    flow = RasSteady.read_flow_file(result.flow_file)
    assert result.boundary_provenance == "source_results"
    assert [item["downstream"]["known_ws"] for item in flow["boundaries"]] == [
        pytest.approx(103.0),
        pytest.approx(105.0),
    ]

    destination_hdf = tmp_path / "breakout" / "breakout.p01.hdf"
    _write_steady_hdf(destination_hdf, [400, 300, 200], wse_offset=0.25)
    comparison = RasBreakout1D.compare_results(
        source_hdf, destination_hdf, result.selection
    )
    assert set(comparison["_merge"].astype(str)) == {"both"}
    assert len(comparison) == 6
    assert "wsel_delta" in comparison.columns


def test_selected_lateral_structure_fails_closed(tmp_path: Path):
    source = _write_project(tmp_path / "source")
    geom = Path(source.geom_df.iloc[0]["full_path"])
    text = geom.read_text(encoding="utf-8").replace(
        "Junct Name=Removed Junction",
        "Lat Struct=Side Weir\n"
        "Lat Struct RS=350,250\n"
        "#Lat Struct Sta/Elev= 2\n"
        "       0     105     100     105\n"
        "Junct Name=Removed Junction",
    )
    geom.write_text(text, encoding="utf-8")

    with pytest.raises(NotImplementedError, match="Lateral structures"):
        RasBreakout1D.extract_reach(
            source,
            tmp_path / "breakout",
            "Main River",
            "Main Reach",
            400,
            200,
            boundary_mode="preserve",
        )
