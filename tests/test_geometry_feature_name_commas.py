"""Name delimiters and lossless replacement of reference-line text records."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import GeomBcLines, GeomMesh, GeomReferenceFeatures, GeomStorage
from ras_commander.geom.GeomReferenceFeatures import _reference_line_blocks
from ras_commander.hdf import HdfBndry, HdfResultsMesh

FIXTURE = Path(__file__).parent / "fixtures/reference_lines/comma_name.g01"
NAME = "Guadalupe Rv at Hunt, TX (USGS)"
AREA = "UPGU1_2DArea"


def _geometry(tmp_path, newline=b"\r\n"):
    block = FIXTURE.read_bytes().replace(b"\r\n", newline)
    header = (
        b"Geom Title=Name delimiter regression"
        + newline
        + b"Storage Area=UPGU1_2DArea,0,0"
        + newline
        + b"Storage Area Is2D=-1"
        + newline
    )
    path = tmp_path / "model.g01"
    path.write_bytes(header + block)
    return path, block


def test_delivered_reference_line_strict_parser():
    lines = FIXTURE.read_bytes().decode("utf-8").splitlines(keepends=True)
    blocks = _reference_line_blocks(lines)
    assert len(blocks) == 1
    assert blocks[0]["name"] == NAME
    assert blocks[0]["storage_area"] == AREA
    assert blocks[0]["coordinates"] == [
        (1866677.83585679, 13937402.4664374),
        (1865101.91370431, 13935115.3088576),
    ]
    assert (blocks[0]["start"], blocks[0]["end"]) == (0, 8)


@pytest.mark.parametrize("newline", [b"\r\n", b"\n"])
def test_delivered_reference_line_round_trip_is_byte_identical(tmp_path, newline):
    path, _ = _geometry(tmp_path, newline)
    before = path.read_bytes()
    parsed = GeomReferenceFeatures.get_reference_lines(path)
    backup = GeomReferenceFeatures.replace_reference_lines(
        path, AREA, parsed, expected_existing_names=[NAME]
    )
    assert path.read_bytes() == before
    assert backup.read_bytes() == before
    assert GeomReferenceFeatures.get_reference_lines(path) == parsed


def test_retained_reference_line_preserves_records_when_collection_changes(tmp_path):
    path, original_block = _geometry(tmp_path)
    parsed = GeomReferenceFeatures.get_reference_lines(path)
    new_line = {"name": "Tributary, West (gage)", "coordinates": [(0, 0), (1, 1)]}
    GeomReferenceFeatures.replace_reference_lines(path, AREA, [new_line, *parsed])
    assert original_block in path.read_bytes()
    assert [
        line["name"] for line in GeomReferenceFeatures.get_reference_lines(path)
    ] == [new_line["name"], NAME]


def test_unchanged_collection_keeps_interleaved_records_without_backup(tmp_path):
    path, original_block = _geometry(tmp_path, b"\n")
    second_block = original_block.replace(NAME.encode(), b"Tributary, West (gage)")
    path.write_bytes(path.read_bytes() + b"\n" + second_block + b"\n")
    before = path.read_bytes()
    parsed = GeomReferenceFeatures.get_reference_lines(path)
    backup = GeomReferenceFeatures.replace_reference_lines(
        str(path), AREA, parsed, create_backup=False
    )
    assert backup is None
    assert path.read_bytes() == before
    assert not path.with_suffix(".g01.bak").exists()


def test_changed_coordinates_are_written_for_comma_name(tmp_path):
    path, original_block = _geometry(tmp_path)
    new_line = {"name": NAME, "coordinates": [(0, 0), (10, 20)]}
    GeomReferenceFeatures.replace_reference_lines(path, AREA, [new_line])
    assert original_block not in path.read_bytes()
    assert GeomReferenceFeatures.get_reference_lines(path)[0]["coordinates"] == [
        (0.0, 0.0),
        (10.0, 20.0),
    ]


def test_add_reference_line_retains_comma_name(tmp_path):
    path, original_block = _geometry(tmp_path)
    name = "Tributary, West (gage)"
    GeomReferenceFeatures.add_reference_lines(
        path, [{"name": name, "coordinates": [(0, 0), (1, 1)]}], AREA
    )
    assert original_block in path.read_bytes()
    assert GeomReferenceFeatures.get_reference_lines(path)[0]["name"] == name


@pytest.mark.parametrize(
    "old,new",
    [
        (b"Reference Line Arc= 2 ", b"Reference Line Arc= 3 "),
        (b"Reference Line Arc= 2 ", b"Reference Line Arc= invalid "),
        (b"Reference Line Storage Area=", b"Missing Storage Area="),
        (b"Reference Line Text Position=", b"Missing Text Position="),
        (b"1866677.83585679", b"not-a-coordinate"),
        (b"Guadalupe Rv at Hunt, TX (USGS)", b"Bad=Name"),
        (b"Guadalupe Rv at Hunt, TX (USGS)", b"Bad\x01Name"),
        (b"Guadalupe Rv at Hunt, TX (USGS)", b"N" * 41),
        (b"UPGU1_2DArea    ", b"Bad,Area        "),
    ],
)
def test_malformed_comma_reference_line_fails_before_write(tmp_path, old, new):
    path, _ = _geometry(tmp_path)
    path.write_bytes(path.read_bytes().replace(old, new))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        GeomReferenceFeatures.replace_reference_lines(path, AREA, [])
    assert path.read_bytes() == before
    assert not path.with_suffix(".g01.bak").exists()


def test_reference_point_name_is_delimited_by_record_end(tmp_path):
    path, _ = _geometry(tmp_path)
    name = "Reference Point Gage, East (1)"
    GeomReferenceFeatures.add_reference_points(path, [{"name": name, "x": 1, "y": 2}])
    assert GeomReferenceFeatures.get_reference_points(path) == [
        {"name": name, "x": 1.0, "y": 2.0}
    ]


def test_breakline_name_is_delimited_by_record_end(tmp_path):
    path, _ = _geometry(tmp_path)
    name = "Levee, East (1)"
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(f"BreakLine Name={name}\r\nBreakLine CellSize Min=10\r\n")
    assert GeomMesh.get_breakline_names(path) == [(0, name)]
    assert GeomMesh.get_breakline_spacing(path)[0][1:3] == (name, 10.0)


def test_bc_line_text_name_is_delimited_by_record_end(tmp_path):
    path, original_block = _geometry(tmp_path)
    name = "Outflow, East (1)"
    result = GeomBcLines.add_bc_lines(
        path, [{"name": name, "storage_area": AREA, "coordinates": [(0, 0), (1, 1)]}]
    )
    assert result["inserted"] == [name]
    GeomBcLines.rename_bc_line(path, name, "Outflow, West (2)")
    GeomBcLines.delete_bc_line(path, "Outflow, West (2)")
    assert original_block in path.read_bytes()
    assert b"BC Line Name=" not in path.read_bytes()


def test_storage_area_header_keeps_comma_delimiters():
    header = GeomStorage._extract_storage_area_header("Storage Area=Area (1),10,20")
    assert header == {"name": "Area (1)", "centroid_x": 10.0, "centroid_y": 20.0}
    with pytest.raises(ValueError):
        GeomStorage._validate_flow_area_name("Area, East")


def test_profile_line_feature_name_keeps_commas(tmp_path):
    import geopandas as gpd
    from shapely.geometry import LineString

    geometry = LineString([(0, 0), (1, 1)])
    path = tmp_path / "profile_lines.geojson"
    gpd.GeoDataFrame({"Name": [NAME]}, geometry=[geometry], crs="EPSG:4326").to_file(
        path
    )
    assert HdfResultsMesh._read_profile_line_geometry(path, NAME).equals(geometry)


def test_native_hdf_reference_point_attribute_name_keeps_commas(tmp_path):
    path = tmp_path / "model.g01.hdf"
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group("Geometry/Reference Points")
        group.create_dataset(
            "Attributes",
            data=np.array(
                [(NAME.encode(), AREA.encode(), 0)],
                dtype=[("Name", "S40"), ("SA/2D", "S16"), ("Cell Index", "i4")],
            ),
        )
        group.create_dataset("Points", data=np.array([(0.0, 0.0)]))
    assert HdfBndry.get_reference_points(path, mesh_name=AREA)["Name"].tolist() == [
        NAME
    ]


@pytest.mark.parametrize("line_type", ["Reference Line", "Profile Line"])
def test_hdf_line_attribute_names_keep_commas(tmp_path, line_type):
    path = tmp_path / "model.g01.hdf"
    with h5py.File(path, "w") as hdf:
        group = hdf.create_group("Geometry/Reference Lines")
        group.create_dataset(
            "Attributes",
            data=np.array(
                [(NAME.encode(), AREA.encode(), line_type.encode())],
                dtype=[("Name", "S40"), ("SA-2D", "S16"), ("Type", "S24")],
            ),
        )
        group.create_dataset("Polyline Info", data=np.array([(0, 2, 0, 1)]))
        group.create_dataset("Polyline Parts", data=np.array([(0, 2)]))
        group.create_dataset("Polyline Points", data=np.array([(0.0, 0.0), (1.0, 1.0)]))
    result = HdfBndry.get_reference_lines(path, mesh_name=AREA)
    assert result["Name"].tolist() == [NAME]
    assert result["Type"].tolist() == [line_type]
