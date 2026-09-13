"""Regression tests for plain-text model extent fallbacks."""

import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pyproj import CRS

gpd = pytest.importorskip("geopandas")
pytest.importorskip("shapely")
h5py = pytest.importorskip("h5py")

from shapely.geometry import LineString, Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from ras_commander import RasExamples, RasPrj, init_ras_project  # noqa: E402
from ras_commander.RasBreakout1D import RasBreakout1D  # noqa: E402
from ras_commander.geom import GeomParser  # noqa: E402
from ras_commander.hdf import HdfMesh, HdfProject, HdfStruc, HdfXsec  # noqa: E402


def _format_cut_line(points):
    values = [value for point in points for value in point]
    return "\n".join(
        "".join(f"{value:16.7f}" for value in values[index:index + 4])
        for index in range(0, len(values), 4)
    )


def _format_area(name, points, is_2d):
    coordinates = "\n".join(f"{x:16.7f}{y:16.7f}" for x, y in points)
    return [
        f"Storage Area={name},0,0",
        f"Storage Area Surface Line= {len(points)}",
        coordinates,
        f"Storage Area Is2D={-1 if is_2d else 0}",
    ]


def _write_text_geometry(path: Path, reaches=None, areas=None):
    reaches = reaches or [
        (
            "Test River",
            "Test Reach",
            [
                ("1000", [(0, 10), (5, 12), (10, 10)]),
                ("900", [(0, 0), (5, -2), (10, 0)]),
            ],
        )
    ]
    lines = ["Geom Title=Text Footprint Test", "Program Version=6.50"]
    for river, reach, cross_sections in reaches:
        lines.append(f"River Reach={river},{reach}")
        for station, points in cross_sections:
            lines.extend([
                f"Type RM Length L Ch R = 1 ,{station},0,0,0",
                f"XS GIS Cut Line= {len(points)}",
                _format_cut_line(points),
                "Node Name=",
            ])
    for name, points, is_2d in areas or []:
        lines.extend(_format_area(name, points, is_2d))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_text_footprint_uses_endpoints_and_bent_end_caps(tmp_path):
    geom_path = _write_text_geometry(tmp_path / "model.g01")

    footprint = GeomParser.get_1d_footprint(geom_path, crs="EPSG:3857")

    assert list(footprint.columns) == ["River", "Reach", "source", "geometry"]
    assert len(footprint) == 1
    assert footprint.crs.to_string() == "EPSG:3857"
    assert footprint.iloc[0]["source"] == "text_xs_endpoints"
    assert footprint.geometry.is_valid.all()
    assert tuple(footprint.total_bounds) == pytest.approx((0, -2, 10, 12))
    boundary = footprint.iloc[0].geometry.boundary
    assert boundary.distance(gpd.points_from_xy([5], [12])[0]) == pytest.approx(0)
    assert boundary.distance(gpd.points_from_xy([5], [-2])[0]) == pytest.approx(0)


def test_text_footprint_keeps_fan_with_shared_bank_endpoint(tmp_path):
    reaches = [("River", "Fan", [
        ("20", [(0, 10), (10, 10)]),
        ("10", [(0, 10), (10, -10)]),
    ])]
    geom_path = _write_text_geometry(tmp_path / "fan.g01", reaches)

    footprint = GeomParser.get_1d_footprint(geom_path)

    assert len(footprint) == 1
    assert footprint.iloc[0].geometry.is_valid
    assert footprint.iloc[0].geometry.area == pytest.approx(100)


def test_text_footprint_preserves_reaches_and_dissolves(tmp_path):
    reaches = [
        ("River A", "Reach 1", [
            ("20", [(0, 10), (10, 10)]),
            ("10", [(0, 0), (10, 0)]),
        ]),
        ("River B", "Reach 2", [
            ("20", [(20, 10), (30, 10)]),
            ("10", [(20, 0), (30, 0)]),
        ]),
    ]
    geom_path = _write_text_geometry(tmp_path / "multi.g01", reaches)

    per_reach = GeomParser.get_1d_footprint(geom_path)
    dissolved = GeomParser.get_1d_footprint(geom_path, dissolve=True)

    assert list(zip(per_reach["River"], per_reach["Reach"])) == [
        ("River A", "Reach 1"),
        ("River B", "Reach 2"),
    ]
    assert len(dissolved) == 1
    assert dissolved.iloc[0].geometry.geom_type == "MultiPolygon"
    assert dissolved.iloc[0].geometry.area == pytest.approx(200)


def test_project_extent_falls_back_when_geometry_hdf_is_missing(tmp_path):
    geom_path = _write_text_geometry(tmp_path / "fallback.g01")
    missing_hdf = Path(str(geom_path) + ".hdf")

    extent, bounds = HdfProject.get_project_extent(
        missing_hdf,
        include_2d=False,
        include_storage=False,
        buffer_percent=0,
    )

    expected = GeomParser.get_1d_footprint(geom_path, dissolve=True)
    assert not extent.empty
    assert extent.iloc[0]["source"] == "plaintext"
    assert extent.iloc[0].geometry.equals(expected.iloc[0].geometry)
    assert bounds == pytest.approx((0, -2, 10, 12))


def test_project_extent_can_disable_plaintext_fallback(tmp_path):
    geom_path = _write_text_geometry(tmp_path / "strict.g01")

    with pytest.raises(FileNotFoundError, match="plain-text fallback is disabled"):
        HdfProject.get_project_extent(
            geom_path,
            include_2d=False,
            include_storage=False,
            buffer_percent=0,
            fallback_to_plaintext=False,
        )


def test_text_only_extent_includes_2d_and_storage_perimeters(tmp_path):
    areas = [
        ("Two D", [(20, 0), (30, 0), (30, 10), (20, 10)], True),
        ("Storage", [(40, 0), (50, 0), (50, 10), (40, 10)], False),
    ]
    geom_path = _write_text_geometry(tmp_path / "mixed.g01", areas=areas)

    extent, bounds = HdfProject.get_project_extent(
        geom_path,
        buffer_percent=0,
        fill_holes=False,
    )

    assert extent.iloc[0].geometry.geom_type == "MultiPolygon"
    assert extent.iloc[0].geometry.area == pytest.approx(320)
    assert bounds == pytest.approx((0, -2, 50, 12))


def test_bbox_plaintext_fallback_is_guarded_for_malformed_xs(tmp_path):
    geom_path = tmp_path / "malformed.g01"
    geom_path.write_text(
        "River Reach=River,Reach\n"
        "Type RM Length L Ch R = 1 ,10,0,0,0\n"
        "XS GIS Cut Line=not-a-count\n",
        encoding="utf-8",
    )

    extent, bounds = HdfProject.get_project_extent(
        geom_path,
        include_2d=False,
        include_storage=False,
        geometry_type="bbox",
        buffer_percent=0,
    )

    assert extent.empty
    assert bounds == (0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    "plan_number",
    ["01", "p01", 1.0, np.int64(1), np.float64(1)],
)
def test_project_extent_preserves_numeric_plan_resolution(tmp_path, plan_number):
    geom_path = _write_text_geometry(tmp_path / "numeric.g01")
    project = SimpleNamespace(
        plan_df=pd.DataFrame({
            "plan_number": ["01"],
            "Geom Path": [str(geom_path)],
        }),
        project_crs="EPSG:3857",
    )

    extent, bounds = HdfProject.get_project_extent(
        plan_number,
        ras_object=project,
        include_2d=False,
        include_storage=False,
        buffer_percent=0,
    )

    assert len(extent) == 1
    assert extent.crs.to_string() == "EPSG:3857"
    assert bounds == pytest.approx((0, -2, 10, 12))


def test_bounds_latlon_forwards_text_fallback_and_project_crs(tmp_path):
    geom_path = _write_text_geometry(tmp_path / "latlon.g01")
    project = SimpleNamespace(project_crs="EPSG:3857")

    bounds = HdfProject.get_project_bounds_latlon(
        geom_path=geom_path,
        ras_object=project,
        include_2d=False,
        include_storage=False,
        buffer_percent=0,
    )

    assert bounds == pytest.approx(
        (0, -0.00001797, 0.00008983, 0.00010780),
        abs=1e-8,
    )


def test_bounds_latlon_can_disable_plaintext_fallback(tmp_path):
    geom_path = _write_text_geometry(tmp_path / "strict-latlon.g01")

    with pytest.raises(FileNotFoundError, match="plain-text fallback is disabled"):
        HdfProject.get_project_bounds_latlon(
            geom_path,
            fallback_to_plaintext=False,
            project_crs="EPSG:3857",
        )


def test_project_extent_prefers_usable_hdf_1d_footprint(tmp_path, monkeypatch):
    geom_path = _write_text_geometry(tmp_path / "preferred.g01")
    hdf_path = Path(str(geom_path) + ".hdf")
    with h5py.File(hdf_path, "w"):
        pass

    hdf_polygon = Polygon([(20, 20), (30, 20), (30, 30), (20, 30)])
    hdf_footprint = gpd.GeoDataFrame(
        {"source": ["generated_edge_lines"]},
        geometry=[hdf_polygon],
    )
    monkeypatch.setattr(HdfXsec, "get_1d_footprint", lambda *_a, **_k: hdf_footprint)

    def unexpected_text_fallback(*_args, **_kwargs):
        pytest.fail("Text fallback should not run for a usable HDF footprint")

    monkeypatch.setattr(HdfProject, "_get_text_1d_footprint", unexpected_text_fallback)

    extent, bounds = HdfProject.get_project_extent(
        hdf_path,
        include_2d=False,
        include_storage=False,
        buffer_percent=0,
    )

    assert extent.iloc[0].geometry.equals(hdf_polygon)
    assert extent.iloc[0]["source"] == "hdf"
    assert bounds == pytest.approx((20, 20, 30, 30))


def test_text_1d_fallback_is_not_suppressed_by_hdf_2d_polygon(
    tmp_path,
    monkeypatch,
):
    geom_path = _write_text_geometry(tmp_path / "hdf-mixed.g01")
    hdf_path = Path(str(geom_path) + ".hdf")
    with h5py.File(hdf_path, "w"):
        pass

    mesh = gpd.GeoDataFrame(
        geometry=[Polygon([(100, 100), (110, 100), (110, 110), (100, 110)])]
    )
    monkeypatch.setattr(HdfMesh, "get_mesh_areas", lambda _path: mesh)
    monkeypatch.setattr(
        HdfXsec,
        "get_1d_footprint",
        lambda *_args, **_kwargs: gpd.GeoDataFrame(geometry=[]),
    )

    extent, bounds = HdfProject.get_project_extent(
        hdf_path,
        include_storage=False,
        buffer_percent=0,
    )

    assert extent.iloc[0].geometry.geom_type == "MultiPolygon"
    assert extent.iloc[0]["source"] == "hdf_and_plaintext"
    assert extent.iloc[0].geometry.area == pytest.approx(220)
    assert bounds == pytest.approx((0, -2, 110, 110))


def test_hdf_only_mode_never_calls_plaintext_getters(tmp_path, monkeypatch):
    geom_path = _write_text_geometry(tmp_path / "hdf-only.g01")
    hdf_path = Path(str(geom_path) + ".hdf")
    with h5py.File(hdf_path, "w"):
        pass

    empty = gpd.GeoDataFrame(geometry=[])
    hdf_polygon = Polygon([(20, 20), (30, 20), (30, 30), (20, 30)])
    monkeypatch.setattr(
        HdfXsec,
        "get_1d_footprint",
        lambda *_args, **_kwargs: gpd.GeoDataFrame(geometry=[hdf_polygon]),
    )
    monkeypatch.setattr(HdfMesh, "get_mesh_areas", lambda *_args, **_kwargs: empty)
    monkeypatch.setattr(
        HdfStruc,
        "get_storage_area_polygons",
        lambda *_args, **_kwargs: empty,
    )

    def unexpected_text(*_args, **_kwargs):
        pytest.fail("Plain-text getter called with fallback_to_plaintext=False")

    monkeypatch.setattr(HdfProject, "_get_text_1d_footprint", unexpected_text)
    monkeypatch.setattr(HdfProject, "_get_text_area_polygons", unexpected_text)

    extent, bounds = HdfProject.get_project_extent(
        hdf_path,
        buffer_percent=0,
        fallback_to_plaintext=False,
    )

    assert extent.iloc[0].geometry.equals(hdf_polygon)
    assert bounds == pytest.approx((20, 20, 30, 30))


def test_hdf_storage_polygon_is_preferred_in_hdf_only_mode(tmp_path, monkeypatch):
    hdf_path = tmp_path / "storage.g01.hdf"
    with h5py.File(hdf_path, "w"):
        pass

    storage_polygon = Polygon([(40, 0), (50, 0), (50, 10), (40, 10)])
    storage = gpd.GeoDataFrame(geometry=[storage_polygon])
    monkeypatch.setattr(
        HdfStruc,
        "get_storage_area_polygons",
        lambda *_args, **_kwargs: storage,
    )

    extent, bounds = HdfProject.get_project_extent(
        hdf_path,
        include_1d=False,
        include_2d=False,
        include_storage=True,
        buffer_percent=0,
        fallback_to_plaintext=False,
    )

    assert extent.iloc[0].geometry.equals(storage_polygon)
    assert bounds == pytest.approx((40, 0, 50, 10))


def test_export_extent_geojson_forwards_plaintext_toggle(tmp_path, monkeypatch):
    calls = {}
    extent = gpd.GeoDataFrame(
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        crs="EPSG:4326",
    )

    def fake_extent(*_args, **kwargs):
        calls.update(kwargs)
        return extent, (0, 0, 1, 1)

    monkeypatch.setattr(HdfProject, "get_project_extent", fake_extent)
    monkeypatch.setattr(gpd.GeoDataFrame, "to_file", lambda *_args, **_kwargs: None)

    project = SimpleNamespace(project_crs="EPSG:3857")
    geom_path = tmp_path / "model.g01"
    HdfProject.export_extent_geojson(
        tmp_path / "model.g01.hdf",
        tmp_path / "extent.geojson",
        geom_path=geom_path,
        fallback_to_plaintext=False,
        ras_object=project,
    )

    assert calls["fallback_to_plaintext"] is False
    assert calls["geom_path"] == geom_path
    assert calls["ras_object"] is project


def test_non_geometry_text_path_is_rejected(tmp_path):
    project_path = tmp_path / "model.prj"
    project_path.write_text("Proj Title=Not geometry\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Geometry HDF or text file"):
        HdfProject.get_project_extent(project_path)


def test_breakout_catalog_uses_text_endpoint_footprint(tmp_path):
    geom_path = _write_text_geometry(tmp_path / "catalog.g01")
    centerlines = gpd.GeoDataFrame(
        geometry=[LineString([(5, -2), (5, 12)])],
        crs="EPSG:3857",
    )
    cross_sections = GeomParser.get_xs_cut_lines(geom_path).set_crs("EPSG:3857")

    geometry, source = RasBreakout1D._catalog_footprint(
        geom_path,
        centerlines,
        cross_sections,
        source_crs=CRS.from_epsg(3857),
        target_crs=CRS.from_epsg(3857),
    )

    expected = GeomParser.get_1d_footprint(geom_path, dissolve=True)
    assert source == "geometry_text_footprint"
    assert geometry.equals(expected.iloc[0].geometry)


def test_bald_eagle_text_footprint_matches_generated_hdf_footprint(tmp_path):
    try:
        project_path = RasExamples.extract_project(
            "BaldEagleCrkMulti2D",
            output_path=tmp_path,
            suffix="text_extent",
        )
    except Exception as exc:
        pytest.skip(f"BaldEagleCrkMulti2D unavailable: {exc}")

    ras = RasPrj()
    init_ras_project(
        project_path,
        "6.6",
        ras_object=ras,
        load_results_summary=False,
        hide_intro=True,
    )
    rows = ras.geom_df.loc[ras.geom_df["geom_file"].eq("g06")]
    if rows.empty:
        pytest.skip("BaldEagleCrkMulti2D g06 is unavailable")
    row = rows.iloc[0]
    geom_path = Path(row["full_path"])
    hdf_path = Path(row["hdf_path"])

    cut_lines = GeomParser.get_xs_cut_lines(geom_path)
    text_footprint = GeomParser.get_1d_footprint(
        geom_path,
        crs=ras.project_crs,
        dissolve=True,
    )
    hdf_footprint = HdfXsec.get_1d_footprint(
        hdf_path,
        edge_source="generate",
        dissolve=True,
        ras_object=ras,
    )

    assert len(cut_lines) == 192
    assert text_footprint.iloc[0].geometry.symmetric_difference(
        hdf_footprint.iloc[0].geometry
    ).area == pytest.approx(0, abs=1e-6)

    text_only_dir = tmp_path / "text_only"
    text_only_dir.mkdir()
    text_only_path = text_only_dir / geom_path.name
    shutil.copy2(geom_path, text_only_path)
    extent, bounds = HdfProject.get_project_extent(
        text_only_path,
        include_2d=False,
        include_storage=False,
        buffer_percent=0,
        ras_object=ras,
    )

    assert extent.crs.to_epsg() == 2271
    assert extent.iloc[0].geometry.equals(text_footprint.iloc[0].geometry)
    assert bounds == pytest.approx(tuple(text_footprint.total_bounds))

    storage = HdfStruc.get_storage_area_polygons(hdf_path, ras_object=ras)
    storage_extent, _ = HdfProject.get_project_extent(
        hdf_path,
        include_1d=False,
        include_2d=False,
        include_storage=True,
        buffer_percent=0,
        fallback_to_plaintext=False,
        ras_object=ras,
    )
    assert len(storage) == 3
    assert storage_extent.iloc[0]["source"] == "hdf"
    assert storage_extent.iloc[0].geometry.symmetric_difference(
        unary_union(storage.geometry.tolist())
    ).area == pytest.approx(0, abs=1e-6)


def test_ebfe_rabbs_text_footprint_matches_only_compiled_geometry():
    configured_root = os.environ.get("RAS_COMMANDER_EBFE_ROOT")
    if not configured_root:
        pytest.skip("Set RAS_COMMANDER_EBFE_ROOT to run the eBFE corpus parity test")

    root = Path(configured_root)
    model_roots = [
        root,
        root / "12090301_Models_extracted" / "Model",
        root / "Model",
    ]
    relative = Path("Rabbs Creek-Colorado River") / "RABBS 0312"
    project_dir = next(
        (candidate / relative for candidate in model_roots if (candidate / relative).is_dir()),
        None,
    )
    if project_dir is None:
        pytest.skip("RABBS 0312 is unavailable under RAS_COMMANDER_EBFE_ROOT")

    geom_path = project_dir / "RABBS 0312.g01"
    hdf_path = project_dir / "RABBS 0312.g01.hdf"
    if not geom_path.is_file() or not hdf_path.is_file():
        pytest.skip("RABBS 0312 text/HDF geometry pair is incomplete")

    cut_lines = GeomParser.get_xs_cut_lines(geom_path)
    text_footprint = GeomParser.get_1d_footprint(geom_path, dissolve=True)
    hdf_footprint = HdfXsec.get_1d_footprint(
        hdf_path,
        edge_source="generate",
        dissolve=True,
    )

    assert len(cut_lines) == 17
    assert text_footprint.iloc[0].geometry.symmetric_difference(
        hdf_footprint.iloc[0].geometry
    ).area == pytest.approx(0, abs=1e-6)
    assert tuple(text_footprint.total_bounds) == pytest.approx(
        (3348593.86, 9957330.38, 3355339.92, 9966412.71)
    )
