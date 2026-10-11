"""Result-map terrain migration preserves all other XML semantics."""

import xml.etree.ElementTree as ET

import pytest
from ras_commander import RasMap


def mapper(tmp_path):
    path = tmp_path / "child.rasmap"
    path.write_text("""<RASMapper><Terrains><Layer Name="Packed" Filename="Packed.hdf" /></Terrains>
    <Results><Layer Name="Event"><Layer Name="Depth" Filename="Depth.vrt">
    <MapParameters MapType="depth" ProfileIndex="7" Terrain="Terrain.Hydroenforced" />
    </Layer><Layer Name="Difference"><Terrain Name="Terrain" />
    <Terrain Name="Other" /><Formula Value="a - b" /></Layer></Layer></Results>
    <Geometries><Layer Terrain="Terrain" /></Geometries></RASMapper>""")
    return path


def test_reassign_references_and_preserve_other_settings(tmp_path):
    path = mapper(tmp_path)
    before = ET.parse(path)
    changes = RasMap.reassign_result_map_terrains(
        path, {"Terrain.Hydroenforced": "Packed", "Terrain": "Packed"}
    )
    assert len(changes) == 2
    after = ET.parse(path)
    assert after.find(".//MapParameters").attrib == {
        "MapType": "depth",
        "ProfileIndex": "7",
        "Terrain": "Packed",
    }
    assert [e.get("Name") for e in after.findall(".//Results//Terrain")] == ["Packed", "Other"]
    # Reverse only the declared replacements; all other structure/data must match.
    after.find(".//MapParameters").set("Terrain", "Terrain.Hydroenforced")
    after.find(".//Results//Terrain").set("Name", "Terrain")
    assert ET.tostring(after.getroot()) == ET.tostring(before.getroot())


@pytest.mark.parametrize("mapping", [{"Terrain": "Absent"}, {"": "Packed"}, {"Terrain": None}, []])
def test_validation_precedes_mutation(tmp_path, mapping):
    path = mapper(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        RasMap.reassign_result_map_terrains(path, mapping)
    assert path.read_bytes() == before


def test_noop_is_byte_preserving_and_idempotent(tmp_path):
    path = mapper(tmp_path)
    RasMap.reassign_result_map_terrains(path, {"Terrain": "Packed"})
    before = path.read_bytes()
    assert RasMap.reassign_result_map_terrains(path, {"Terrain": "Packed"}) == []
    assert path.read_bytes() == before
