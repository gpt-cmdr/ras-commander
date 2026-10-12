"""Complete-record replay of native constant-elevation polygon edits."""

import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pytest

from ras_commander.terrain import RasTerrainModWriter


@pytest.fixture
def polygons(tmp_path):
    source, target = tmp_path / "source.hdf", tmp_path / "target.hdf"
    mapper, child = tmp_path / "source.rasmap", tmp_path / "target.rasmap"
    dtype = np.dtype(
        [
            ("Name", "S1"),
            ("Elevation Value", "<f4"),
            ("Elevation Type", "S11"),
            ("Elev Pt Tolerance", "<f4"),
            ("Generate Boundary Elevations", "u1"),
            ("Use ShapeFile Z Elevations", "u1"),
        ]
    )
    exterior = np.array([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], dtype="float64")
    hole = np.array([[2, 2], [2, 4], [4, 4], [4, 2], [2, 2]], dtype="float64")
    with h5py.File(source, "w") as f:
        g = f.create_group("Modifications/Polygons")
        g.attrs.update(Type=np.bytes_("Polygon"), Priority=0)
        g.create_dataset(
            "Attributes",
            data=np.array(
                [(b"", 100, b"SetValue", 20, 0, 0), (b"", 99, b"SetValue", 20, 0, 0)],
                dtype=dtype,
            ),
        )
        g.create_dataset(
            "Polygon Info", data=np.array([[0, 5, 0, 1], [5, 10, 1, 2]], dtype="int32")
        )
        g.create_dataset(
            "Polygon Parts", data=np.array([[0, 5], [0, 5], [5, 5]], dtype="int32")
        )
        g.create_dataset(
            "Polygon Points", data=np.vstack([exterior + 20, exterior, hole])
        )
        g["Polygon Points"].attrs["Column"] = np.array([b"X", b"Y"])
    with h5py.File(target, "w") as f:
        f.create_group("Terrain")
    mapper.write_text(
        '<RASMapper><Terrains><Layer Name="Source" Type="TerrainLayer" Filename="source.hdf"><Layer Name="Modifications" Type="ElevationModificationGroup" Checked="True"><Layer Name="Polygons" Type="PolygonElevationModificationLayer" Checked="True"><Layer Name="Control Points" Type="ElevationControlPointLayer" /></Layer></Layer></Layer></Terrains></RASMapper>'
    )
    child.write_text(
        '<RASMapper><Terrains><Layer Name="Child" Type="TerrainLayer" Filename="target.hdf" /></Terrains></RASMapper>'
    )
    return source, target, mapper, child


def test_polygon_holes_and_complete_chunked_replay(polygons):
    source, target, mapper, child = polygons
    before = source.read_bytes(), mapper.read_bytes()
    frame = RasTerrainModWriter.get_modification_features(source, "EPSG:2278")
    assert frame.support_distance.tolist() == [0.0, 0.0]
    assert len(frame.geometry.iloc[1].interiors) == 1
    assert frame.geometry.iloc[1].area == 96
    RasTerrainModWriter.copy_modification_features(*polygons, {"Polygons": [1]})
    with h5py.File(source) as s, h5py.File(target) as t:
        original = s["Modifications/Polygons"]
        copied = t["Modifications/Polygons"]
        assert dict(original.attrs) == dict(copied.attrs)
        assert copied["Attributes"][:].tobytes() == original["Attributes"][1:].tobytes()
        assert (
            copied["Polygon Points"][:].tobytes()
            == original["Polygon Points"][5:].tobytes()
        )
        assert copied["Polygon Info"][:].tolist() == [[0, 10, 0, 2]]
        assert copied["Polygon Parts"][:].tolist() == [[0, 5], [5, 5]]
        assert all(d.chunks is not None for d in copied.values())
    assert (
        ET.parse(child)
        .find('.//Layer[@Type="PolygonElevationModificationLayer"]')
        .get("Checked")
        == "True"
    )
    assert before == (source.read_bytes(), mapper.read_bytes())


@pytest.mark.parametrize(
    "invalid",
    ["unclosed", "nonfinite", "profile_method", "boundary_generation", "bad_index"],
)
def test_unsupported_polygon_is_atomic(polygons, invalid):
    with h5py.File(polygons[0], "r+") as f:
        g = f["Modifications/Polygons"]
        if invalid == "unclosed":
            g["Polygon Points"][4] = [1, 1]
        elif invalid == "nonfinite":
            g["Polygon Points"][0] = [np.nan, 0]
        elif invalid == "bad_index":
            g["Polygon Parts"][0] = [0, 500]
        else:
            rows = g["Attributes"][:]
            rows[
                "Elevation Type"
                if invalid == "profile_method"
                else "Generate Boundary Elevations"
            ][0] = b"Multipoint" if invalid == "profile_method" else 1
            g["Attributes"][:] = rows
    before = polygons[1].read_bytes(), polygons[3].read_bytes()
    with pytest.raises(ValueError):
        RasTerrainModWriter.get_modification_features(polygons[0], "EPSG:2278")
    with pytest.raises(ValueError):
        RasTerrainModWriter.copy_modification_features(*polygons, {"Polygons": [0]})
    assert before == (polygons[1].read_bytes(), polygons[3].read_bytes())
