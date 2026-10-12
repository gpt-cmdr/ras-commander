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


def test_namespaced_append_preserves_records_priorities_and_mapper_order(polygons):
    RasTerrainModWriter.copy_modification_features(
        *polygons, {"Polygons": [0]}, group_prefix="owner_"
    )
    RasTerrainModWriter.copy_modification_features(
        *polygons, {"Polygons": [1]}, group_prefix="contributor_", append=True
    )
    with h5py.File(polygons[0]) as original, h5py.File(polygons[1]) as copied:
        for prefix, index in (("owner_", 0), ("contributor_", 1)):
            group = copied["Modifications/" + prefix + "Polygons"]
            assert (
                group["Attributes"][:].tobytes()
                == original["Modifications/Polygons/Attributes"][
                    index : index + 1
                ].tobytes()
            )
            assert dict(group.attrs) == dict(original["Modifications/Polygons"].attrs)
            assert all(dataset.chunks is not None for dataset in group.values())
    group = ET.parse(polygons[3]).find('.//Layer[@Type="ElevationModificationGroup"]')
    assert [layer.get("Name") for layer in group.findall("Layer")] == [
        "owner_Polygons",
        "contributor_Polygons",
    ]
    before = polygons[1].read_bytes(), polygons[3].read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        RasTerrainModWriter.copy_modification_features(
            *polygons, {"Polygons": [0]}, group_prefix="owner_", append=True
        )
    assert before == (polygons[1].read_bytes(), polygons[3].read_bytes())


def test_incompatible_collection_append_is_atomic(polygons):
    RasTerrainModWriter.copy_modification_features(
        *polygons, {"Polygons": [0]}, group_prefix="owner_"
    )
    tree = ET.parse(polygons[2])
    tree.find('.//Layer[@Type="ElevationModificationGroup"]').set("Checked", "False")
    tree.write(polygons[2])
    before = polygons[1].read_bytes(), polygons[3].read_bytes()
    with pytest.raises(ValueError, match="settings differ"):
        RasTerrainModWriter.copy_modification_features(
            *polygons, {"Polygons": [1]}, group_prefix="contributor_", append=True
        )
    assert before == (polygons[1].read_bytes(), polygons[3].read_bytes())


@pytest.mark.parametrize(
    "change", ["control", "mapper_collision", "missing_collection"]
)
def test_append_rejects_incompatible_existing_pair_atomically(polygons, change):
    RasTerrainModWriter.copy_modification_features(
        *polygons, {"Polygons": [0]}, group_prefix="owner_"
    )
    tree = ET.parse(polygons[3])
    group = tree.find('.//Layer[@Type="ElevationModificationGroup"]')
    if change == "control":
        ET.SubElement(group, "DefaultModificationType", Value="SetIfHigher")
    elif change == "mapper_collision":
        ET.SubElement(group, "Layer", Name="contributor_Polygons")
    else:
        tree.find('.//Layer[@Type="TerrainLayer"]').remove(group)
    tree.write(polygons[3])
    before = polygons[1].read_bytes(), polygons[3].read_bytes()
    with pytest.raises(ValueError):
        RasTerrainModWriter.copy_modification_features(
            *polygons, {"Polygons": [1]}, group_prefix="contributor_", append=True
        )
    assert before == (polygons[1].read_bytes(), polygons[3].read_bytes())
