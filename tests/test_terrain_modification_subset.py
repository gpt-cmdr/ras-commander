"""Lossless native channel-modification subset contracts."""

import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pytest

from ras_commander.terrain import RasTerrainModWriter


@pytest.fixture
def terrains(tmp_path):
    source = tmp_path / "source.hdf"
    destination = tmp_path / "destination.hdf"
    source_mapper = tmp_path / "source.rasmap"
    destination_mapper = tmp_path / "destination.rasmap"
    dtype = np.dtype(
        [("Max Extent", "<f8"), ("Top Width", "<f8"), ("Elevation Type", "<i4")]
    )
    with h5py.File(source, "w") as file:
        group = file.create_group("Modifications/Channels")
        group.attrs.update(Type="Levee", Subtype="Channel", Priority=3)
        group.create_dataset(
            "Attributes", data=np.array([(10, 5, 2), (20, 8, 1)], dtype=dtype)
        )
        group.create_dataset(
            "Polyline Info", data=np.array([[0, 2, 0, 1], [2, 4, 1, 2]], dtype="int32")
        )
        group.create_dataset(
            "Polyline Parts", data=np.array([[0, 2], [0, 2], [2, 2]], dtype="int32")
        )
        group.create_dataset(
            "Polyline Points",
            data=np.array(
                [[0, 0], [10, 10], [30, 0], [40, 10], [50, 20], [60, 0]],
                dtype="float64",
            ),
        )
        group.create_dataset(
            "Profile Info", data=np.array([[0, 2], [2, 3]], dtype="int32")
        )
        group.create_dataset(
            "Profile Values",
            data=np.array(
                [[0, 100], [1, 99], [0, 10.01], [1, 9.25], [2, 8.125]], dtype="float64"
            ),
        )
        group["Polyline Points"].attrs["Column"] = ["X", "Y"]
    with h5py.File(destination, "w") as file:
        file.create_group("Terrain").attrs["Priority"] = 0
    source_mapper.write_text(
        '<RASMapper><Terrains><Layer Name="Source" Type="TerrainLayer" Filename="source.hdf"><Layer Name="Modified" Type="ElevationModificationGroup" Checked="False"><Layer Name="Channels" Type="ElevationChannel"><DefaultModificationType Value="2" /></Layer></Layer></Layer></Terrains></RASMapper>'
    )
    destination_mapper.write_text(
        '<RASMapper><Terrains><Layer Name="Child" Type="TerrainLayer" Filename="destination.hdf" /></Terrains></RASMapper>'
    )
    return source, destination, source_mapper, destination_mapper


def test_complete_multipart_geometry_and_support(terrains):
    features = RasTerrainModWriter.get_modification_features(terrains[0], "EPSG:2278")
    assert str(features.crs) == "EPSG:2278"
    assert features.feature_index.tolist() == [0, 1]
    assert features.support_distance.tolist() == [10.0, 20.0]
    assert features.geometry.iloc[1].geom_type == "MultiLineString"
    assert features.geometry.iloc[1].bounds == (30, 0, 60, 20)


def test_copy_preserves_parameters_coordinates_profiles_and_mapper(terrains):
    source, destination, mapper, child_mapper = terrains
    before = (source.read_bytes(), mapper.read_bytes())
    result = RasTerrainModWriter.copy_modification_features(
        *terrains, {"Channels": [1]}
    )
    assert result[0]["retained_feature_indexes"] == [1]
    with h5py.File(source) as original, h5py.File(destination) as child:
        a = original["Modifications/Channels"]
        b = child["Modifications/Channels"]
        assert dict(a.attrs) == dict(b.attrs)
        assert b["Attributes"][:].tobytes() == a["Attributes"][1:2].tobytes()
        assert b["Polyline Points"][:].tobytes() == a["Polyline Points"][2:].tobytes()
        assert b["Profile Values"][:].tobytes() == a["Profile Values"][2:].tobytes()
        assert b["Polyline Info"][:].tolist() == [[0, 4, 0, 2]]
        assert b["Polyline Parts"][:].tolist() == [[0, 2], [2, 2]]
        assert b["Profile Info"][:].tolist() == [[0, 3]]
        assert b["Polyline Points"].attrs["Column"].tolist() == ["X", "Y"]
        assert "Terrain" in child
    xml = ET.parse(child_mapper)
    group = xml.find('.//Layer[@Type="ElevationModificationGroup"]')
    assert group.get("Checked") == "False"
    assert group.find("Layer/DefaultModificationType").get("Value") == "2"
    assert before == (source.read_bytes(), mapper.read_bytes())
    copied = RasTerrainModWriter.get_modification_features(destination, "EPSG:2278")
    assert copied.geometry.iloc[0].equals_exact(
        RasTerrainModWriter.get_modification_features(
            source, "EPSG:2278"
        ).geometry.iloc[1],
        0,
    )


@pytest.mark.parametrize(
    "selection",
    [
        {"Channels": [2]},
        {"Channels": [-1]},
        {"Channels": [1, 1]},
        {"Channels": [True]},
        {"Absent": [0]},
    ],
)
def test_bad_selection_does_not_mutate_destination(terrains, selection):
    before = (terrains[1].read_bytes(), terrains[3].read_bytes())
    with pytest.raises(ValueError):
        RasTerrainModWriter.copy_modification_features(*terrains, selection)
    assert before == (terrains[1].read_bytes(), terrains[3].read_bytes())


def test_unknown_table_and_missing_support_rejected(terrains):
    with h5py.File(terrains[0], "r+") as file:
        file["Modifications/Channels"].create_dataset("Unknown", data=[1])
    with pytest.raises(ValueError, match="Unsupported"):
        RasTerrainModWriter.get_modification_features(terrains[0], "EPSG:2278")
    before = terrains[1].read_bytes()
    with pytest.raises(ValueError, match="Unsupported"):
        RasTerrainModWriter.copy_modification_features(*terrains, {"Channels": [0]})
    assert terrains[1].read_bytes() == before


def test_empty_subset_omits_native_modifications(terrains):
    RasTerrainModWriter.copy_modification_features(*terrains, {"Channels": []})
    with h5py.File(terrains[1]) as file:
        assert "Modifications" not in file
    assert (
        ET.parse(terrains[3]).find('.//Layer[@Type="ElevationModificationGroup"]')
        is None
    )


def test_source_destination_identity_is_refused(terrains):
    with pytest.raises(ValueError, match="distinct"):
        RasTerrainModWriter.copy_modification_features(
            terrains[0], terrains[0], terrains[2], terrains[3], {"Channels": [0]}
        )


def test_export_has_no_terrain_and_rebinds_nested_mapper(terrains, tmp_path):
    source, _, mapper, _ = terrains
    tree = ET.parse(mapper)
    group = tree.find('.//Layer[@Type="ElevationModificationGroup"]')
    group.set("Filename", "source.hdf")
    group.find("Layer").set("Filename", "source.hdf")
    ET.SubElement(
        group.find("Layer"), "Layer", Name="Control Points", Filename="source.hdf"
    )
    tree.write(mapper)
    before = (source.read_bytes(), mapper.read_bytes())
    folder = tmp_path / "bundle"
    RasTerrainModWriter.export_modification_features(
        source, mapper, folder, {"Channels": [1]}
    )
    with h5py.File(folder / "modifications.hdf") as file:
        assert set(file) == {"Modifications"}
        assert len(file["Modifications/Channels/Attributes"]) == 1
    root = ET.parse(folder / "modifications.rasmap")
    assert all(
        x.get("Filename") == "modifications.hdf"
        for x in root.iter()
        if "Filename" in x.attrib
    )
    assert before == (source.read_bytes(), mapper.read_bytes())
    with pytest.raises(ValueError, match="already exists"):
        RasTerrainModWriter.export_modification_features(
            source, mapper, folder, {"Channels": [0]}
        )


def test_duplicate_mapper_registration_is_rejected(terrains):
    import copy

    tree = ET.parse(terrains[2])
    group = tree.find('.//Layer[@Type="ElevationModificationGroup"]')
    group.append(copy.deepcopy(group.find("Layer")))
    tree.write(terrains[2])
    before = (terrains[1].read_bytes(), terrains[3].read_bytes())
    with pytest.raises(ValueError, match="unique"):
        RasTerrainModWriter.copy_modification_features(*terrains, {"Channels": [0]})
    assert before == (terrains[1].read_bytes(), terrains[3].read_bytes())


def test_pair_rollback_on_mapper_replacement_failure(terrains, monkeypatch):
    from ras_commander import _terrain_modification_subset as subset

    original = subset.os.replace

    def fail_mapper(source, destination):
        if destination == terrains[3]:
            raise OSError("injected mapper replacement failure")
        return original(source, destination)

    monkeypatch.setattr(subset.os, "replace", fail_mapper)
    before = (terrains[1].read_bytes(), terrains[3].read_bytes())
    with pytest.raises(OSError, match="injected"):
        RasTerrainModWriter.copy_modification_features(*terrains, {"Channels": [0]})
    assert before == (terrains[1].read_bytes(), terrains[3].read_bytes())


def test_terrain_removal_preserves_other_layers(tmp_path):
    from ras_commander import RasMap

    mapper = tmp_path / "clone.rasmap"
    mapper.write_text(
        '<RASMapper><Terrains><Layer Name="A"/><Layer Name="B"/></Terrains><Geometries><Layer Name="Geometry"/></Geometries><Results><Layer Name="Plan"/></Results></RASMapper>'
    )
    assert RasMap.remove_terrain_layers(mapper) == ["A", "B"]
    root = ET.parse(mapper)
    assert root.find("Terrains").findall("Layer") == []
    assert root.find("Geometries/Layer").get("Name") == "Geometry"
    assert root.find("Results/Layer").get("Name") == "Plan"
    assert RasMap.remove_terrain_layers(mapper) == []


def test_schema_matches_public_frame(terrains):
    from ras_commander.schemas import DATAFRAME_SCHEMAS

    frame = RasTerrainModWriter.get_modification_features(terrains[0], "EPSG:2278")
    assert frame.columns.tolist() == [
        c["name"] for c in DATAFRAME_SCHEMAS["terrain_modification_features"]["columns"]
    ]
    with pytest.raises(ValueError, match="CRS"):
        RasTerrainModWriter.get_modification_features(terrains[0], None)


def test_exact_registration_precedes_same_basename_and_ambiguous_fails(terrains):
    tree = ET.parse(terrains[2])
    terrains_node = tree.find("Terrains")
    wrong = ET.Element("Layer", Name="Wrong", Filename="other/source.hdf")
    terrains_node.insert(0, wrong)
    tree.write(terrains[2])
    result = RasTerrainModWriter.copy_modification_features(
        *terrains, {"Channels": [0]}
    )
    assert result[0]["source_registration_name"] == "Source"
    assert result[0]["source_registration_basis"] == "resolved_path"


def test_ambiguous_stale_source_and_inexact_destination_refused(terrains):
    tree = ET.parse(terrains[2])
    layers = tree.find("Terrains")
    layers.find("Layer").set("Filename", "stale/source.hdf")
    ET.SubElement(layers, "Layer", Name="Other", Filename="other/source.hdf")
    tree.write(terrains[2])
    before = (terrains[1].read_bytes(), terrains[3].read_bytes())
    with pytest.raises(ValueError, match="ambiguous"):
        RasTerrainModWriter.copy_modification_features(*terrains, {"Channels": [0]})
    assert before == (terrains[1].read_bytes(), terrains[3].read_bytes())
    tree = ET.parse(terrains[3])
    tree.find("Terrains/Layer").set("Filename", "wrong/destination.hdf")
    tree.write(terrains[3])
    with pytest.raises(ValueError, match="ambiguous"):
        RasTerrainModWriter.copy_modification_features(*terrains, {"Channels": [0]})


def test_empty_frame_contract_and_missing_support(terrains, tmp_path):
    empty = tmp_path / "empty.hdf"
    with h5py.File(empty, "w"):
        pass
    frame = RasTerrainModWriter.get_modification_features(empty, "EPSG:2278")
    assert frame.empty and str(frame.crs) == "EPSG:2278"
    assert str(frame.feature_index.dtype) == "int64"
    assert str(frame.support_distance.dtype) == "float64"
    with h5py.File(terrains[0], "r+") as file:
        group = file["Modifications/Channels"]
        del group["Attributes"]
        group.create_dataset(
            "Attributes", data=np.array([(5,), (8,)], dtype=[("Top Width", "<f8")])
        )
    with pytest.raises(ValueError, match="support distance"):
        RasTerrainModWriter.get_modification_features(terrains[0], "EPSG:2278")


def test_unique_stale_source_fallback_and_destination_exactness(terrains):
    tree = ET.parse(terrains[2])
    tree.find("Terrains/Layer").set("Filename", "stale/source.hdf")
    tree.write(terrains[2])
    child = ET.parse(terrains[3])
    child.find("Terrains/Layer").set("Filename", "other/destination.hdf")
    child.write(terrains[3])
    with pytest.raises(ValueError, match="ambiguous"):
        RasTerrainModWriter.copy_modification_features(*terrains, {"Channels": [0]})
    child.find("Terrains/Layer").set("Filename", "destination.hdf")
    child.write(terrains[3])
    result = RasTerrainModWriter.copy_modification_features(
        *terrains, {"Channels": [0]}
    )
    assert result[0]["source_registration_basis"] == "unique_source_basename"


def test_duplicate_exact_source_registration_refused(terrains):
    tree = ET.parse(terrains[2])
    ET.SubElement(
        tree.find("Terrains"), "Layer", Name="Duplicate", Filename="source.hdf"
    )
    tree.write(terrains[2])
    with pytest.raises(ValueError, match="ambiguous"):
        RasTerrainModWriter.copy_modification_features(*terrains, {"Channels": [0]})


def test_native_single_vertex_and_empty_profile_are_preserved(terrains):
    with h5py.File(terrains[0], "r+") as file:
        group = file["Modifications/Channels"]
        group["Polyline Info"][1] = [2, 1, 1, 1]
        group["Polyline Parts"][1] = [0, 1]
        group["Profile Info"][1] = [2, 0]
    frame = RasTerrainModWriter.get_modification_features(terrains[0], "EPSG:2278")
    assert frame.geometry.iloc[1].geom_type == "Point"
    assert frame.geometry.iloc[1].coords[0] == (30.0, 0.0)
    RasTerrainModWriter.copy_modification_features(*terrains, {"Channels": [1]})
    with h5py.File(terrains[1]) as file:
        group = file["Modifications/Channels"]
        assert group["Polyline Info"][:].tolist() == [[0, 1, 0, 1]]
        assert group["Polyline Parts"][:].tolist() == [[0, 1]]
        assert group["Polyline Points"][:].tolist() == [[30, 0]]
        assert group["Profile Info"][:].tolist() == [[0, 0]]
        assert group["Profile Values"].shape == (0, 2)


@pytest.mark.parametrize("parts", [[[0, 1], [1, 3]], [[0, 1], [2, 2]]])
def test_mixed_degenerate_parts_rejected_before_read_copy_export(
    terrains, tmp_path, parts
):
    with h5py.File(terrains[0], "r+") as file:
        file["Modifications/Channels/Polyline Parts"][1:] = parts
    before = (terrains[1].read_bytes(), terrains[3].read_bytes())
    with pytest.raises(ValueError, match="mixed degenerate"):
        RasTerrainModWriter.get_modification_features(terrains[0], "EPSG:2278")
    with pytest.raises(ValueError, match="mixed degenerate"):
        RasTerrainModWriter.copy_modification_features(*terrains, {"Channels": [1]})
    output = tmp_path / "bundle"
    with pytest.raises(ValueError, match="mixed degenerate"):
        RasTerrainModWriter.export_modification_features(
            terrains[0], terrains[2], output, {"Channels": [1]}
        )
    assert before == (terrains[1].read_bytes(), terrains[3].read_bytes())
    assert not output.exists()
