"""Opt-in public-model acceptance tests for raster BenefitArea analysis."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import geopandas as gpd
import pytest
import rasterio
from rasterio.windows import Window
from shapely.geometry import Polygon, box


PROVENANCE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "benefit_area_sciencebase_kalamazoo.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _array_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with rasterio.open(path) as source:
        for row_offset in range(0, source.height, 256):
            values = source.read(
                1,
                window=Window(
                    0,
                    row_offset,
                    source.width,
                    min(256, source.height - row_offset),
                ),
            )
            digest.update(values.tobytes(order="C"))
    return digest.hexdigest()


def _cell_counts(path: Path) -> dict[str, int]:
    with rasterio.open(path) as source:
        statistics = json.loads(source.tags()["benefit_statistics"])
    return {
        str(values["code"]): int(values["cell_count"])
        for values in statistics.values()
    }


def _project_path(provenance: dict) -> Path:
    if os.environ.get("RAS_COMMANDER_RUN_BENEFITS_INTEGRATION") != "1":
        pytest.skip(
            "Set RAS_COMMANDER_RUN_BENEFITS_INTEGRATION=1 and "
            "RAS_COMMANDER_BENEFITS_PUBLIC_PROJECT to run the public USGS "
            "ScienceBase acceptance fixture (DOI 10.5066/P13CPA5B). It can "
            "be downloaded with UsgsScienceBase.download_kalamazoo()."
        )
    configured = os.environ.get("RAS_COMMANDER_BENEFITS_PUBLIC_PROJECT")
    if not configured:
        pytest.fail("RAS_COMMANDER_BENEFITS_PUBLIC_PROJECT is required when enabled")
    candidate = Path(configured).expanduser().resolve()
    if candidate.is_dir():
        candidate = candidate / f"{provenance['model']['project_name']}.prj"
    if not candidate.is_file():
        pytest.fail(f"Public BenefitArea fixture project was not found: {candidate}")
    return candidate


def _assert_polygon_edges_on_grid(polygon_path: Path, raster_path: Path) -> None:
    frame = gpd.read_file(polygon_path, layer="benefit_area")
    assert set(frame["benefit_code"].astype(int)) == {1, 2, 3}
    assert frame.geometry.is_valid.all()

    with rasterio.open(raster_path) as source:
        inverse = ~source.transform
        pixel_area = abs(source.transform.determinant)
        counts = _cell_counts(raster_path)
    for row in frame.itertuples():
        code = str(int(row.benefit_code))
        assert row.geometry.area == pytest.approx(counts[code] * pixel_area)
        polygons = (
            [row.geometry]
            if isinstance(row.geometry, Polygon)
            else list(row.geometry.geoms)
        )
        assert all(isinstance(item, Polygon) for item in polygons)
        for polygon in polygons:
            rings = [polygon.exterior, *polygon.interiors]
            for ring in rings:
                for x_coordinate, y_coordinate in ring.coords:
                    column, raster_row = inverse * (x_coordinate, y_coordinate)
                    assert column == pytest.approx(round(column), abs=1.0e-7)
                    assert raster_row == pytest.approx(round(raster_row), abs=1.0e-7)


@pytest.mark.integration
def test_public_sciencebase_benefit_area_option_matrix(tmp_path):
    from ras_commander import BenefitAreaConfig, RasBenefits, RasProcess, init_ras_project

    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    project = _project_path(provenance)
    project_root = project.parent
    terrain = project_root / provenance["terrain"]["tif_relative_path"]
    terrain_hdf = project_root / provenance["terrain"]["hdf_relative_path"]
    rasmap = project.with_suffix(".rasmap")
    pre_hdf = project.with_suffix(".p01.hdf")
    post_hdf = project.with_suffix(".p33.hdf")

    assert _sha256(project) == provenance["model"]["project_sha256"]
    assert _sha256(rasmap) == provenance["model"]["rasmap_sha256"]
    assert _sha256(pre_hdf) == provenance["comparison"]["pre_plan_hdf_sha256"]
    assert _sha256(post_hdf) == provenance["comparison"]["post_plan_hdf_sha256"]
    assert _sha256(terrain_hdf) == provenance["terrain"]["hdf_sha256"]
    assert _sha256(terrain) == provenance["terrain"]["tif_sha256"]
    RasBenefits.validate_registered_terrain_source(terrain_hdf, terrain)

    configured_output = os.environ.get("RAS_COMMANDER_BENEFITS_OUTPUT_ROOT")
    output_root = (
        Path(configured_output).expanduser().resolve()
        if configured_output
        else tmp_path
    )
    default_root = output_root / "default"
    before_rasmap = _sha256(rasmap)
    ras = init_ras_project(
        project,
        ras_object="new",
        ras_version=provenance["model"]["ras_version"],
        load_results_summary=True,
    )
    outputs = RasProcess.store_maps(
        plan_number=provenance["comparison"]["post_plan"],
        output_path=default_root,
        profile="Max",
        render_mode=provenance["algorithm"]["render_mode"],
        wse=False,
        depth=True,
        velocity=False,
        terrain_name=provenance["terrain"]["name"],
        benefit_area=BenefitAreaConfig(
            pre_plan_number=provenance["comparison"]["pre_plan"],
            terrain_tif=terrain,
            terrain_name=provenance["terrain"]["name"],
            minimum_region_pixels=provenance["algorithm"][
                "minimum_region_pixels"
            ],
            polygon_output=Path("benefit_area.gpkg"),
        ),
        ras_object=ras,
        ras_version=provenance["model"]["ras_version"],
        timeout=10800,
    )
    assert _sha256(rasmap) == before_rasmap
    assert "benefit_source_pre_wse" not in outputs
    assert "benefit_source_post_wse" not in outputs

    default_raster = Path(outputs["benefit_area"][0])
    default_polygon = Path(outputs["benefit_area_polygon"][0])
    expected_default = provenance["expected"]["default"]
    assert _cell_counts(default_raster) == expected_default["cell_counts"]
    assert _array_sha256(default_raster) == expected_default["array_sha256"]
    _assert_polygon_edges_on_grid(default_polygon, default_raster)

    pre_depth = Path(outputs["benefit_source_pre_depth"][0])
    post_depth = Path(outputs["benefit_source_post_depth"][0])
    with rasterio.open(pre_depth) as source:
        bounds = source.bounds
    middle_x = (bounds.left + bounds.right) / 2.0
    middle_y = (bounds.bottom + bounds.top) / 2.0
    analysis = box(bounds.left, bounds.bottom, middle_x, bounds.top)
    improvement = box(
        bounds.left,
        middle_y,
        (bounds.left + middle_x) / 2.0,
        bounds.top,
    )
    cases = {
        "no_filter": {"minimum_region_pixels": None},
        "filter_100": {"minimum_region_pixels": 100},
        "custom_thresholds": {
            "flood_min_depth": 0.10,
            "benefit_min_depth": 0.50,
            "minimum_region_pixels": None,
        },
        "analysis_boundary": {
            "minimum_region_pixels": None,
            "analysis_boundary": analysis,
        },
        "analysis_minus_improvement": {
            "minimum_region_pixels": None,
            "analysis_boundary": analysis,
            "improvement_boundary": improvement,
        },
    }
    for name, options in cases.items():
        result = RasBenefits.create_benefit_area(
            pre_depth,
            post_depth,
            terrain,
            output_root / "matrix" / f"{name}.tif",
            **options,
        )
        expected = provenance["expected"][name]
        assert _cell_counts(result.raster_path) == expected["cell_counts"]
        assert _array_sha256(result.raster_path) == expected["array_sha256"]


@pytest.mark.integration
def test_public_sciencebase_optional_wse_outputs_are_aligned(tmp_path):
    if os.environ.get("RAS_COMMANDER_RUN_BENEFITS_WSE_INTEGRATION") != "1":
        pytest.skip(
            "Set RAS_COMMANDER_RUN_BENEFITS_WSE_INTEGRATION=1 in addition to "
            "the base integration opt-in to run the slower WSE acceptance case."
        )

    from ras_commander import BenefitAreaConfig, RasProcess, init_ras_project

    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    project = _project_path(provenance)
    terrain = project.parent / provenance["terrain"]["tif_relative_path"]
    rasmap = project.with_suffix(".rasmap")
    before_rasmap = _sha256(rasmap)
    ras = init_ras_project(
        project,
        ras_object="new",
        ras_version=provenance["model"]["ras_version"],
        load_results_summary=True,
    )
    outputs = RasProcess.store_maps(
        plan_number=provenance["comparison"]["post_plan"],
        output_path=tmp_path / "wse",
        profile="Max",
        render_mode=provenance["algorithm"]["render_mode"],
        wse=True,
        depth=True,
        velocity=False,
        terrain_name=provenance["terrain"]["name"],
        benefit_area=BenefitAreaConfig(
            pre_plan_number=provenance["comparison"]["pre_plan"],
            terrain_tif=terrain,
            terrain_name=provenance["terrain"]["name"],
            include_wse=True,
        ),
        ras_object=ras,
        ras_version=provenance["model"]["ras_version"],
        timeout=10800,
    )
    assert _sha256(rasmap) == before_rasmap
    for condition in ("pre", "post"):
        depth_path = Path(outputs[f"benefit_source_{condition}_depth"][0])
        wse_path = Path(outputs[f"benefit_source_{condition}_wse"][0])
        with rasterio.open(depth_path) as depth, rasterio.open(wse_path) as wse:
            assert (wse.width, wse.height) == (depth.width, depth.height)
            assert wse.crs == depth.crs
            assert wse.transform.almost_equals(depth.transform)
