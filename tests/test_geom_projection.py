"""Focused tests for HEC-RAS model geometry reprojection."""

from pathlib import Path
import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pytest
from pyproj import CRS, Transformer

from ras_commander.geom import GeomParser, GeomProjection


SOURCE_CRS = CRS.from_epsg(5070)
DEST_CRS = CRS.from_epsg(26915)


def _format_xy(points, *, values_per_line=4):
    values = []
    for x_coord, y_coord in points:
        values.extend([x_coord, y_coord])
    return GeomParser.format_fixed_width(
        values,
        column_width=16,
        values_per_line=values_per_line,
        precision=7,
    )


def _write_geometry(path: Path) -> Path:
    path.write_text(
        "".join(
            [
                "Geom Title=Projection Test\n",
                "Program Version=6.60\n",
                "River Reach=Test River,Main\n",
                "Reach XY= 2\n",
                *_format_xy([(0.0, 0.0), (1000.0, 1000.0)]),
                "Type RM Length L Ch R = 1000,1000,0,0,0\n",
                "Bank Sta=1,2\n",
                "XS GIS Cut Line= 2\n",
                *_format_xy([(10.0, 10.0), (20.0, 20.0)]),
                "Storage Area=Area 1,100.0000000,200.0000000\n",
                "Storage Area Surface Line= 5\n",
                *_format_xy(
                    [
                        (0.0, 0.0),
                        (100.0, 0.0),
                        (100.0, 100.0),
                        (0.0, 100.0),
                        (0.0, 0.0),
                    ],
                    values_per_line=2,
                ),
                "Storage Area Type= 0\n",
                "Storage Area Area=\n",
                "Storage Area Min Elev=\n",
                "Storage Area Is2D=-1\n",
                "Storage Area 2D Points= 2\n",
                *_format_xy([(25.0, 25.0), (75.0, 75.0)]),
                "Storage Area 2D PointsPerimeterTime=01Jan2026 00:00:00\n",
                "BreakLine Name=Road\n",
                "BreakLine CellSize Min=10\n",
                "BreakLine CellSize Max=50\n",
                "BreakLine Near Repeats=0\n",
                "BreakLine Protection Radius=0\n",
                "BreakLine Polyline= 2\n",
                *_format_xy([(0.0, 50.0), (100.0, 50.0)]),
                "BC Line Name=Upstream\n",
                "BC Line Storage Area=Area 1\n",
                "BC Line Start Position= 0.0 , 0.0 \n",
                "BC Line Middle Position= 50.0 , 0.0 \n",
                "BC Line End Position= 100.0 , 0.0 \n",
                "BC Line Arc= 2\n",
                *_format_xy([(0.0, 0.0), (100.0, 0.0)]),
                "BC Line Text Position= 1.79769313486232E+308 , 1.79769313486232E+308 \n",
                "Reference Line Name=Gauge\n",
                "Reference Line Storage Area=Area 1\n",
                "Reference Line Start Position= 0.0 , 10.0 \n",
                "Reference Line Middle Position= 50.0 , 10.0 \n",
                "Reference Line End Position= 100.0 , 10.0 \n",
                "Reference Line Arc= 2\n",
                *_format_xy([(0.0, 10.0), (100.0, 10.0)]),
                "Reference Line Text Position= 1.79769313486232E+308 , 1.79769313486232E+308 \n",
                "IC Point Name=Reference Point Gauge\n",
                "IC Point Position=50.0,50.0\n",
                "Connection=SA Link\n",
                "Connection Line=2\n",
                *_format_xy([(0.0, 100.0), (100.0, 100.0)]),
            ]
        ),
        encoding="utf-8",
    )
    return path


def _values_after(lines, keyword, count):
    for index, line in enumerate(lines):
        if line.lstrip().startswith(f"{keyword}="):
            values, _ = GeomProjection._read_coord_block_values(lines, index + 1, count)
            return values
    raise AssertionError(f"{keyword} block not found")


def _xy_from_values(values):
    return [(values[i], values[i + 1]) for i in range(0, len(values), 2)]


def _expected(point):
    return Transformer.from_crs(SOURCE_CRS, DEST_CRS, always_xy=True).transform(*point)


def _assert_xy(actual, expected):
    assert actual[0] == pytest.approx(expected[0], abs=1e-6)
    assert actual[1] == pytest.approx(expected[1], abs=1e-6)


def _position(text, keyword):
    for line in text.splitlines():
        if line.startswith(f"{keyword}="):
            value = GeomParser.extract_keyword_value(line, keyword)
            parts = [float(part.strip()) for part in value.split(",")[:2]]
            return tuple(parts)
    raise AssertionError(f"{keyword} line not found")


def test_reproject_geometry_transforms_1d_2d_and_line_features(tmp_path):
    geom = _write_geometry(tmp_path / "Model.g01")

    result = GeomProjection.reproject_geometry(
        geom,
        SOURCE_CRS,
        DEST_CRS,
    )

    output = Path(result["output_geometry"])
    text = output.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    reach_points = _xy_from_values(_values_after(lines, "Reach XY", 2))
    xs_points = _xy_from_values(_values_after(lines, "XS GIS Cut Line", 2))
    surface_points = _xy_from_values(_values_after(lines, "Storage Area Surface Line", 5))
    seed_points = _xy_from_values(_values_after(lines, "Storage Area 2D Points", 2))
    breakline_points = _xy_from_values(_values_after(lines, "BreakLine Polyline", 2))
    bc_points = _xy_from_values(_values_after(lines, "BC Line Arc", 2))
    ref_points = _xy_from_values(_values_after(lines, "Reference Line Arc", 2))
    connection_points = _xy_from_values(_values_after(lines, "Connection Line", 2))

    _assert_xy(reach_points[0], _expected((0.0, 0.0)))
    _assert_xy(xs_points[0], _expected((10.0, 10.0)))
    _assert_xy(surface_points[1], _expected((100.0, 0.0)))
    _assert_xy(seed_points[0], _expected((25.0, 25.0)))
    _assert_xy(breakline_points[0], _expected((0.0, 50.0)))
    _assert_xy(bc_points[1], _expected((100.0, 0.0)))
    _assert_xy(ref_points[1], _expected((100.0, 10.0)))
    _assert_xy(connection_points[0], _expected((0.0, 100.0)))
    _assert_xy(_position(text, "BC Line Start Position"), _expected((0.0, 0.0)))
    _assert_xy(_position(text, "Reference Line End Position"), _expected((100.0, 10.0)))
    _assert_xy(_position(text, "IC Point Position"), _expected((50.0, 50.0)))

    assert "Bank Sta=1,2" in text
    assert result["transformed"]["xs_gis_cut_lines_points"] == 2
    assert result["transformed"]["storage_area_surface_lines_points"] == 5
    assert result["qa"]["storage_areas"]["invalid_perimeters"] == []
    assert result["qa"]["breaklines"]["invalid"] == []


def test_reproject_geometry_preserves_crlf_line_endings(tmp_path):
    geom = _write_geometry(tmp_path / "Model.g01")
    lf_text = geom.read_text(encoding="utf-8")
    geom.write_bytes(lf_text.replace("\n", "\r\n").encode("utf-8"))

    result = GeomProjection.reproject_geometry(
        geom,
        SOURCE_CRS,
        DEST_CRS,
    )

    output_bytes = Path(result["output_geometry"]).read_bytes()
    assert b"\r\r\n" not in output_bytes
    assert b"\n" not in output_bytes.replace(b"\r\n", b"")


def test_reproject_model_geometry_copies_project_updates_rasmap_and_reports_terrain(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    project_name = "Model"
    geom = _write_geometry(project / f"{project_name}.g01")
    original_geom_text = geom.read_text(encoding="utf-8")

    (project / f"{project_name}.prj").write_text(
        "Proj Title=Model\nGeom File=g01\n",
        encoding="utf-8",
    )

    projection_dir = project / "Projection"
    projection_dir.mkdir()
    source_prj = projection_dir / "source.prj"
    destination_prj = tmp_path / "destination.prj"
    source_prj.write_text(SOURCE_CRS.to_wkt(version="WKT1_ESRI"), encoding="utf-8")
    destination_prj.write_text(DEST_CRS.to_wkt(version="WKT1_ESRI"), encoding="utf-8")

    terrain_dir = project / "Terrain"
    terrain_dir.mkdir()
    terrain_hdf = terrain_dir / "Terrain.hdf"
    with h5py.File(terrain_hdf, "w") as hdf:
        hdf.attrs["Projection"] = SOURCE_CRS.to_wkt()

    with h5py.File(project / f"{project_name}.g01.hdf", "w") as hdf:
        rr = hdf.create_group("Geometry/2D Flow Area Refinement Regions")
        rr.create_dataset("Attributes", data=np.array([(b"Region 1",)], dtype=[("Name", "S32")]))
        rr.create_dataset("Polygon Info", data=np.array([[0, 5, 0, 1]], dtype=np.int32))
        rr.create_dataset("Polygon Parts", data=np.array([[0, 5]], dtype=np.int32))
        rr.create_dataset(
            "Polygon Points",
            data=np.array(
                [
                    [0.0, 0.0],
                    [100.0, 0.0],
                    [100.0, 100.0],
                    [0.0, 100.0],
                    [0.0, 0.0],
                ],
                dtype=np.float64,
            ),
        )

    (project / f"{project_name}.rasmap").write_text(
        (
            "<RASMapper>\n"
            '  <RASProjectionFilename Filename=".\\Projection\\source.prj" />\n'
            "  <Terrains>\n"
            '    <Layer Name="Terrain" Type="TerrainLayer" Filename=".\\Terrain\\Terrain.hdf" />\n'
            "  </Terrains>\n"
            "</RASMapper>\n"
        ),
        encoding="utf-8",
    )

    result = GeomProjection.reproject_model_geometry(
        project,
        source_prj,
        destination_prj,
    )

    assert geom.read_text(encoding="utf-8") == original_geom_text
    dest_folder = project.with_name("project_reprojected")
    assert Path(result["destination_project_folder"]) == dest_folder
    assert Path(result["projection_file"]).exists()
    assert CRS.from_wkt(Path(result["projection_file"]).read_text(encoding="utf-8")).equals(DEST_CRS)

    rasmap_root = ET.parse(dest_folder / f"{project_name}.rasmap").getroot()
    projection_ref = rasmap_root.find(".//RASProjectionFilename").get("Filename")
    assert projection_ref == f".\\Projection\\{project_name}_Projection.prj"

    dest_text = (dest_folder / f"{project_name}.g01").read_text(encoding="utf-8")
    assert dest_text != original_geom_text
    assert result["terrain_requirements"][0]["requires_reprojection"] is True
    assert result["terrain_requirements"][0]["terrain_crs"] == "EPSG:5070"
    assert result["compiled_geometry"][0]["compiled_hdf_exists"] is True
    assert result["compiled_geometry"][0]["refinement_region_count"] == 1
    assert result["compiled_geometry"][0]["refinement_region_integrity"]["is_valid"] is True


def test_reproject_model_geometry_remaps_absolute_source_geometry_to_copy(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    project_name = "Model"
    geom = _write_geometry(project / f"{project_name}.g01")
    original_geom_text = geom.read_text(encoding="utf-8")
    (project / f"{project_name}.prj").write_text(
        "Proj Title=Model\nGeom File=g01\n",
        encoding="utf-8",
    )

    result = GeomProjection.reproject_model_geometry(
        project,
        SOURCE_CRS,
        DEST_CRS,
        geometry_files=[geom.resolve()],
    )

    dest_geom = project.with_name("project_reprojected") / f"{project_name}.g01"
    assert geom.read_text(encoding="utf-8") == original_geom_text
    assert dest_geom.read_text(encoding="utf-8") != original_geom_text
    assert (
        Path(result["geometry_results"][0]["source_geometry"]).resolve()
        == dest_geom.resolve()
    )


def test_reproject_model_geometry_rejects_absolute_geometry_outside_project_copy(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    _write_geometry(project / "Model.g01")
    outside_geom = _write_geometry(tmp_path / "Outside.g01")
    (project / "Model.prj").write_text(
        "Proj Title=Model\nGeom File=g01\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Absolute geometry_files entries"):
        GeomProjection.reproject_model_geometry(
            project,
            SOURCE_CRS,
            DEST_CRS,
            geometry_files=[outside_geom.resolve()],
        )


def test_reproject_geometry_rejects_datum_shift_by_default(tmp_path):
    geom = _write_geometry(tmp_path / "Model.g01")

    with pytest.raises(ValueError, match="datum shift"):
        GeomProjection.reproject_geometry(
            geom,
            CRS.from_epsg(26915),
            CRS.from_epsg(32615),
        )


def test_reproject_geometry_reports_duplicate_perimeter_points(tmp_path):
    geom = tmp_path / "duplicate.g01"
    geom.write_text(
        "".join(
            [
                "Geom Title=Duplicate Perimeter\n",
                "Storage Area=Area 1,0.0000000,0.0000000\n",
                "Storage Area Surface Line= 6\n",
                *_format_xy(
                    [
                        (0.0, 0.0),
                        (100.0, 0.0),
                        (50.0, 50.0),
                        (100.0, 0.0),
                        (0.0, 100.0),
                        (0.0, 0.0),
                    ],
                    values_per_line=2,
                ),
                "Storage Area Is2D=-1\n",
            ]
        ),
        encoding="utf-8",
    )

    result = GeomProjection.reproject_geometry(
        geom,
        SOURCE_CRS,
        SOURCE_CRS,
    )

    duplicates = result["qa"]["storage_areas"]["duplicate_perimeter_points"]
    assert len(duplicates) == 1
    assert duplicates[0]["name"] == "Area 1"
    assert duplicates[0]["duplicate_vertices"][0]["first_index"] == 1
    assert duplicates[0]["duplicate_vertices"][0]["duplicate_index"] == 3


def test_reproject_model_geometry_rejects_source_destination_folder(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    _write_geometry(project / "Model.g01")
    (project / "Model.prj").write_text(
        "Proj Title=Model\nGeom File=g01\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="different from the source project"):
        GeomProjection.reproject_model_geometry(
            project,
            SOURCE_CRS,
            DEST_CRS,
            dest_folder=project,
            overwrite=True,
        )

    with pytest.raises(ValueError, match="must not be inside"):
        GeomProjection.reproject_model_geometry(
            project,
            SOURCE_CRS,
            DEST_CRS,
            dest_folder=project / "nested_copy",
        )


def test_compiled_geometry_reports_invalid_refinement_region_integrity(tmp_path):
    geom = _write_geometry(tmp_path / "Model.g01")
    with h5py.File(tmp_path / "Model.g01.hdf", "w") as hdf:
        rr = hdf.create_group("Geometry/2D Flow Area Refinement Regions")
        rr.create_dataset("Attributes", data=np.array([(b"Region 1",)], dtype=[("Name", "S32")]))

    result = GeomProjection._inspect_compiled_geometry_hdfs([geom])
    integrity = result[0]["refinement_region_integrity"]

    assert result[0]["refinement_region_count"] == 1
    assert integrity["checked"] is True
    assert integrity["is_valid"] is False
    assert "Missing refinement region dataset: Polygon Points" in integrity["issues"]
