"""Coverage-aware USGS 3DEP project selection.

The legacy selection kept exactly one project (the newest) whenever several
intersected the bbox, so every sub-area that project did not cover was silently
dropped from the mosaic. These tests pin the newest-per-sub-area behavior, the
unchanged default, and the coverage reporting. All network access is mocked.
"""

from importlib import import_module

import geopandas as gpd
import pytest
from shapely.geometry import box


usgs_module = import_module("ras_commander.terrain.Usgs3depAws")
Usgs3depAws = usgs_module.Usgs3depAws


BBOX = (-77.2, 40.6, -77.0, 40.8)

# Newest project covers only the western 40% of the bbox.
WEST_TILE = "USGS_1M_18_x01y01_PA_West_2020_A20.tif"
# Newest project also publishes a tile in the far east of the bbox, but there is
# a hole between them that only the older project fills.
FAR_EAST_TILE = "USGS_1M_18_x09y01_PA_West_2020_A20.tif"
EAST_TILE = "USGS_1M_18_x05y01_PA_East_2018_B18.tif"

TILE_BOUNDS = {
    WEST_TILE: (-77.2, 40.6, -77.13, 40.8),
    FAR_EAST_TILE: (-77.05, 40.6, -77.0, 40.8),
    EAST_TILE: (-77.12, 40.6, -77.0, 40.8),
}

PROJECT_TILES = {
    "PA_West_2020_A20": [
        f"https://example.com/{WEST_TILE}",
        f"https://example.com/{FAR_EAST_TILE}",
    ],
    "PA_East_2018_B18": [f"https://example.com/{EAST_TILE}"],
}


def _two_projects():
    """Two adjacent projects: newest covers the west, older covers the east."""
    return gpd.GeoDataFrame(
        {"proj_name": ["PA_West_2020_A20", "PA_East_2018_B18"]},
        geometry=[
            box(-77.2, 40.6, -77.12, 40.8),
            box(-77.12, 40.6, -77.0, 40.8),
        ],
        crs="EPSG:4326",
    )


def _partial_projects():
    """Two projects that together leave the eastern third of the bbox bare."""
    return gpd.GeoDataFrame(
        {"proj_name": ["PA_West_2020_A20", "PA_Middle_2018_B18"]},
        geometry=[
            box(-77.2, 40.6, -77.15, 40.8),
            box(-77.15, 40.6, -77.07, 40.8),
        ],
        crs="EPSG:4326",
    )


def _stub_download(monkeypatch, projects):
    """Wire up the network-touching helpers with deterministic fakes."""
    monkeypatch.setattr(
        Usgs3depAws,
        "find_tiles_for_bbox",
        staticmethod(lambda bbox, resolution, cache_folder=None: projects.copy()),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_project_tile_urls",
        staticmethod(lambda project_name: list(PROJECT_TILES.get(project_name, []))),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_parse_tile_bounds_from_filename",
        staticmethod(lambda filename: TILE_BOUNDS[filename]),
    )
    monkeypatch.setattr(
        Usgs3depAws,
        "_download_single_tile",
        staticmethod(
            lambda tile_url, output_folder, overwrite_dest: output_folder
            / tile_url.rsplit("/", 1)[-1]
        ),
    )


def test_select_projects_for_coverage_uses_newest_project_per_sub_area():
    selected, report = Usgs3depAws.select_projects_for_coverage(
        _two_projects(), BBOX
    )

    assert list(selected["proj_name"]) == ["PA_West_2020_A20", "PA_East_2018_B18"]
    assert [entry["year"] for entry in report["projects"]] == [2020, 2018]
    assert report["projects"][0]["area_fraction"] == pytest.approx(0.4, abs=1e-6)
    assert report["projects"][1]["area_fraction"] == pytest.approx(0.6, abs=1e-6)
    assert report["covered_fraction"] == pytest.approx(1.0, abs=1e-9)
    assert report["uncovered_fraction"] == pytest.approx(0.0, abs=1e-9)
    assert report["uncovered_geometry"] is None

    # Each project carries the sub-area it was selected to cover.
    west_region = selected.iloc[0]["_coverage_region"]
    assert west_region.bounds == pytest.approx((-77.2, 40.6, -77.12, 40.8))


def test_select_projects_for_coverage_reports_residual_gap():
    selected, report = Usgs3depAws.select_projects_for_coverage(
        _partial_projects(), BBOX
    )

    assert len(selected) == 2
    assert report["uncovered_fraction"] == pytest.approx(0.35, abs=1e-6)
    assert report["covered_fraction"] == pytest.approx(0.65, abs=1e-6)
    assert report["uncovered_geometry"] is not None
    assert report["uncovered_geometry"].bounds == pytest.approx((-77.07, 40.6, -77.0, 40.8))


def test_select_projects_for_coverage_falls_back_to_single_project():
    projects = gpd.GeoDataFrame(
        {"proj_name": ["PA_Only_2020_A20"]},
        geometry=[box(-77.3, 40.5, -76.9, 40.9)],
        crs="EPSG:4326",
    )

    selected, report = Usgs3depAws.select_projects_for_coverage(projects, BBOX)

    assert list(selected["proj_name"]) == ["PA_Only_2020_A20"]
    assert report["covered_fraction"] == pytest.approx(1.0, abs=1e-9)
    assert len(report["projects"]) == 1


def test_select_projects_for_coverage_skips_projects_below_minimum_contribution():
    projects = gpd.GeoDataFrame(
        {"proj_name": ["PA_West_2020_A20", "PA_Sliver_2018_B18"]},
        geometry=[
            box(-77.2, 40.6, -77.02, 40.8),
            box(-77.02, 40.6, -77.0, 40.8),
        ],
        crs="EPSG:4326",
    )

    selected, report = Usgs3depAws.select_projects_for_coverage(
        projects,
        BBOX,
        min_project_area_fraction=0.25,
    )

    assert list(selected["proj_name"]) == ["PA_West_2020_A20"]
    assert report["uncovered_fraction"] == pytest.approx(0.1, abs=1e-6)


def test_select_projects_for_coverage_handles_empty_candidates():
    empty = gpd.GeoDataFrame({"proj_name": []}, geometry=[], crs="EPSG:4326")

    selected, report = Usgs3depAws.select_projects_for_coverage(empty, BBOX)

    assert len(selected) == 0
    assert report["projects"] == []
    assert report["covered_fraction"] == 0.0
    assert report["uncovered_geometry"] is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_coverage_fraction": 0.0},
        {"min_coverage_fraction": 1.5},
        {"min_project_area_fraction": -0.1},
        {"min_project_area_fraction": 1.0},
    ],
)
def test_select_projects_for_coverage_validates_fractions(kwargs):
    with pytest.raises(ValueError):
        Usgs3depAws.select_projects_for_coverage(_two_projects(), BBOX, **kwargs)


def test_download_tiles_defaults_to_single_newest_project(monkeypatch, tmp_path):
    """Default behavior is unchanged: newest project only, gap included."""
    _stub_download(monkeypatch, _two_projects())

    result = Usgs3depAws.download_tiles(
        bbox=BBOX,
        resolution=1,
        output_folder=tmp_path,
        max_workers=1,
    )

    assert [path.name for path in result] == [WEST_TILE, FAR_EAST_TILE]


def test_download_tiles_coverage_mode_fills_the_gap(monkeypatch, tmp_path):
    _stub_download(monkeypatch, _two_projects())

    result = Usgs3depAws.download_tiles(
        bbox=BBOX,
        resolution=1,
        output_folder=tmp_path,
        max_workers=1,
        project_selection="coverage",
    )

    # The older project supplies the eastern sub-area the newest project misses,
    # and tiles are ordered oldest project first so the newest wins on overlap.
    assert [path.name for path in result] == [EAST_TILE, WEST_TILE]


def test_download_tiles_coverage_mode_warns_about_residual_gap(
    monkeypatch, tmp_path, caplog
):
    import logging

    _stub_download(monkeypatch, _partial_projects())
    monkeypatch.setattr(
        Usgs3depAws,
        "_get_project_tile_urls",
        staticmethod(lambda project_name: []),
    )
    caplog.set_level(logging.WARNING, logger=usgs_module.logger.name)

    result = Usgs3depAws.download_tiles(
        bbox=BBOX,
        resolution=1,
        output_folder=tmp_path,
        max_workers=1,
        project_selection="coverage",
    )

    assert result == []
    warnings = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
    )
    assert "USGS 3DEP coverage gap" in warnings


def test_download_tiles_coverage_mode_with_one_project_matches_newest(
    monkeypatch, tmp_path
):
    projects = gpd.GeoDataFrame(
        {"proj_name": ["PA_West_2020_A20"]},
        geometry=[box(-77.3, 40.5, -76.9, 40.9)],
        crs="EPSG:4326",
    )
    _stub_download(monkeypatch, projects)

    newest = Usgs3depAws.download_tiles(
        bbox=BBOX,
        resolution=1,
        output_folder=tmp_path,
        max_workers=1,
    )
    coverage = Usgs3depAws.download_tiles(
        bbox=BBOX,
        resolution=1,
        output_folder=tmp_path,
        max_workers=1,
        project_selection="coverage",
    )

    assert sorted(path.name for path in newest) == sorted(
        path.name for path in coverage
    )


def test_download_tiles_rejects_unknown_project_selection(tmp_path):
    with pytest.raises(ValueError, match="project_selection must be one of"):
        Usgs3depAws.download_tiles(
            bbox=BBOX,
            resolution=1,
            output_folder=tmp_path,
            project_selection="latest",
        )
