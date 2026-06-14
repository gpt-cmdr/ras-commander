import shutil
from pathlib import Path

import pytest

from ras_commander.RasExamples import RasExamples
from ras_commander.geom.GeomLandCover import GeomLandCover

gpd = pytest.importorskip("geopandas")
shapely_geometry = pytest.importorskip("shapely.geometry")
MultiPolygon = shapely_geometry.MultiPolygon
Polygon = shapely_geometry.Polygon


REGION_NAME = "Flat Area"


@pytest.fixture(scope="module")
def muncie_project(tmp_path_factory):
    output_path = tmp_path_factory.mktemp("ras_examples")
    try:
        return RasExamples.extract_project(
            "Muncie",
            output_path=output_path,
            suffix="landcover_region_polygons",
        )
    except Exception as exc:
        pytest.skip(f"Muncie example project unavailable: {exc}")


@pytest.fixture
def muncie_g04(muncie_project, tmp_path):
    source = Path(muncie_project) / "Muncie.g04"
    if not source.exists():
        pytest.skip("Muncie.g04 was not extracted")

    target = tmp_path / "Muncie.g04"
    shutil.copy2(source, target)
    return target


def _region_polygon_coords(geom_file: Path, region_name: str):
    lines = geom_file.read_text(encoding="utf-8", errors="replace").splitlines(True)
    block = GeomLandCover._find_region_block(lines, region_name)
    assert block is not None, f"Region {region_name!r} not found"
    assert block["polygon_idx"] is not None, f"Region {region_name!r} has no polygon"

    polygon_idx = block["polygon_idx"]
    polygon_end_idx = GeomLandCover._region_polygon_data_end(lines, polygon_idx)
    count = GeomLandCover._region_polygon_count(lines[polygon_idx])

    values = []
    for line in lines[polygon_idx + 1:polygon_end_idx]:
        values.extend(GeomLandCover._parse_region_coord_values(line))

    coords = list(zip(values[0::2], values[1::2]))
    assert len(coords) == count
    return count, coords


def _remove_region_polygon_block(geom_file: Path, region_name: str) -> None:
    lines = geom_file.read_text(encoding="utf-8", errors="replace").splitlines(True)
    block = GeomLandCover._find_region_block(lines, region_name)
    assert block is not None
    assert block["polygon_idx"] is not None
    polygon_idx = block["polygon_idx"]
    polygon_end_idx = block["polygon_end_idx"]
    updated = lines[:polygon_idx] + lines[polygon_end_idx:]
    geom_file.write_text("".join(updated), encoding="utf-8")


def _polygon_gdf(name: str, polygon):
    return gpd.GeoDataFrame({"Name": [name], "geometry": [polygon]})


def _flat(coords):
    return [value for xy in coords for value in xy]


def test_set_mannings_region_polygons_replaces_existing_block(muncie_g04):
    polygon = Polygon(
        [
            (407000.123456789, 1803000.987654321),
            (407060.5, 1803005.25),
            (407055.75, 1803060.875),
            (406995.125, 1803052.625),
            (407000.123456789, 1803000.987654321),
        ]
    )

    assert GeomLandCover.set_mannings_region_polygons(
        muncie_g04,
        _polygon_gdf(REGION_NAME, polygon),
    )

    updated_text = muncie_g04.read_text(encoding="utf-8", errors="replace")
    assert "medium density residential,0.072" in updated_text
    assert "LCMann Region Time=" in updated_text
    assert muncie_g04.with_suffix(".g04.bak").exists()

    count, coords = _region_polygon_coords(muncie_g04, REGION_NAME)
    assert count == 4
    assert _flat(coords) == pytest.approx(_flat(list(polygon.exterior.coords)[:-1]))

    lines = updated_text.splitlines()
    polygon_line_idx = lines.index("LCMann Region Polygon=4")
    coord_lines = lines[polygon_line_idx + 1:polygon_line_idx + 3]
    assert all(len(line) <= 64 for line in coord_lines)


def test_set_mannings_region_polygons_adds_missing_block_to_existing_region(muncie_g04):
    _remove_region_polygon_block(muncie_g04, REGION_NAME)

    polygon = Polygon(
        [
            (406800.0, 1802800.0),
            (406900.0, 1802810.0),
            (406860.0, 1802880.0),
            (406800.0, 1802800.0),
        ]
    )

    GeomLandCover.set_mannings_region_polygons(
        muncie_g04,
        _polygon_gdf(REGION_NAME, polygon),
    )

    updated_text = muncie_g04.read_text(encoding="utf-8", errors="replace")
    assert "urban,0.09" in updated_text
    assert updated_text.index("LCMann Region Name=Flat Area") < updated_text.index(
        "LCMann Region Polygon=3"
    )
    assert updated_text.index("LCMann Region Polygon=3") < updated_text.index(
        "Chan Stop Cuts=-1"
    )

    count, coords = _region_polygon_coords(muncie_g04, REGION_NAME)
    assert count == 3
    assert _flat(coords) == pytest.approx(_flat(list(polygon.exterior.coords)[:-1]))


def test_set_mannings_region_polygons_accepts_multipolygon(muncie_g04):
    multipolygon = MultiPolygon(
        [
            Polygon(
                [
                    (406700.0, 1802600.0),
                    (406760.0, 1802600.0),
                    (406730.0, 1802660.0),
                    (406700.0, 1802600.0),
                ]
            ),
            Polygon(
                [
                    (406900.0, 1802700.0),
                    (406960.0, 1802700.0),
                    (406930.0, 1802760.0),
                    (406900.0, 1802700.0),
                ]
            ),
        ]
    )

    GeomLandCover.set_mannings_region_polygons(
        muncie_g04,
        _polygon_gdf(REGION_NAME, multipolygon),
    )

    count, coords = _region_polygon_coords(muncie_g04, REGION_NAME)
    assert count == 8
    assert coords[0] == pytest.approx((406700.0, 1802600.0))
    assert coords[3] == pytest.approx(coords[0])
    assert coords[4] == pytest.approx((406900.0, 1802700.0))
    assert coords[7] == pytest.approx(coords[4])


def test_set_mannings_region_polygons_creates_region_compatible_with_n_writer(muncie_g04):
    region_name = "Added Calibration Area"
    polygon = Polygon(
        [
            (405000.0, 1802000.0),
            (405100.0, 1802000.0),
            (405100.0, 1802100.0),
            (405000.0, 1802100.0),
            (405000.0, 1802000.0),
        ]
    )

    GeomLandCover.set_mannings_region_polygons(
        muncie_g04,
        _polygon_gdf(region_name, polygon),
    )

    region_rows = GeomLandCover.get_region_mannings_n(muncie_g04)
    added_rows = region_rows[region_rows["Region Name"] == region_name].copy()
    assert set(added_rows["Land Cover Name"]) == {
        "building",
        "medium density residential",
        "open space",
        "park",
        "trees",
        "urban",
    }

    added_rows.loc[
        added_rows["Land Cover Name"] == "open space",
        "MainChannel",
    ] = 0.047
    GeomLandCover.set_region_mannings_n(muncie_g04, added_rows)

    after_rows = GeomLandCover.get_region_mannings_n(muncie_g04)
    updated = after_rows[
        (after_rows["Region Name"] == region_name)
        & (after_rows["Land Cover Name"] == "open space")
    ].iloc[0]
    assert updated["MainChannel"] == pytest.approx(0.047)

    count, coords = _region_polygon_coords(muncie_g04, region_name)
    assert count == 4
    assert _flat(coords) == pytest.approx(_flat(list(polygon.exterior.coords)[:-1]))


def test_set_mannings_region_polygons_validates_required_columns(muncie_g04):
    polygon = Polygon(
        [
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.0, 0.0),
        ]
    )
    regions = gpd.GeoDataFrame({"geometry": [polygon]})

    with pytest.raises(ValueError, match="Name and geometry"):
        GeomLandCover.set_mannings_region_polygons(muncie_g04, regions)


@pytest.mark.integration
def test_set_mannings_region_polygons_roundtrips_through_preprocessor(tmp_path):
    from ras_commander import init_ras_project
    from ras_commander.geom.GeomPreprocessor import GeomPreprocessor
    from ras_commander.hdf.HdfLandCover import HdfLandCover

    try:
        project_path = RasExamples.extract_project(
            "Muncie",
            output_path=tmp_path,
            suffix="landcover_region_polygon_preprocess",
        )
    except Exception as exc:
        pytest.skip(f"Muncie example project unavailable: {exc}")

    project_path = Path(project_path)
    geom_file = project_path / "Muncie.g04"
    if not geom_file.exists():
        pytest.skip("Muncie.g04 was not extracted")

    _, coords = _region_polygon_coords(geom_file, REGION_NAME)
    polygon = Polygon(coords)
    GeomLandCover.set_mannings_region_polygons(
        geom_file,
        _polygon_gdf(REGION_NAME, polygon),
    )

    for stale_path in [project_path / "Muncie.g04.hdf", project_path / "Muncie.c04"]:
        if stale_path.exists():
            stale_path.unlink()

    try:
        init_ras_project(project_path, "6.6")
        result = GeomPreprocessor.run_geometry_preprocessor(
            "04",
            max_wait=360,
            force=True,
            clear_geompre=True,
        )
    except Exception as exc:
        pytest.skip(f"HEC-RAS geometry preprocessing unavailable: {exc}")

    if not result:
        if result.error and "executable" in result.error.lower():
            pytest.skip(result.error)
        pytest.fail(
            "HEC-RAS geometry preprocessing failed: "
            f"{result.error or result.first_error_line or result!r}"
        )

    geom_hdf = project_path / "Muncie.g04.hdf"
    assert geom_hdf.exists(), "Geometry HDF was not regenerated by preprocessing"

    regions = HdfLandCover.get_mannings_region_polygons(geom_hdf)
    assert not regions.empty
    region_match = regions[regions["Name"].astype(str).str.strip() == REGION_NAME]
    assert not region_match.empty

    expected = Polygon(coords)
    roundtrip = region_match.iloc[0].geometry
    assert roundtrip.hausdorff_distance(expected) <= 1e-4
    assert roundtrip.area == pytest.approx(expected.area, rel=1e-9, abs=1e-3)
