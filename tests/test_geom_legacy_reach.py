from ras_commander.geom.GeomCrossSection import GeomCrossSection
from ras_commander.geom.GeomMetadata import GeomMetadata
from ras_commander.geom.GeomParser import GeomParser


def test_extract_river_reach_supports_modern_and_legacy_headers():
    assert GeomParser.extract_river_reach("River Reach=River A,Reach 1\n") == (
        "River A",
        "Reach 1",
    )
    assert GeomParser.extract_river_reach("Reach=Legacy Reach\n") == (
        "Legacy Reach",
        "Legacy Reach",
    )
    assert GeomParser.extract_river_reach("Reach=\n") is None
    assert GeomParser.extract_river_reach("Storage Area=Reach\n") is None


def test_get_cross_sections_classifies_legacy_reach_without_mutation(tmp_path):
    geometry = tmp_path / "legacy.g01"
    original = (
        "Geom Title=Legacy Geometry\r\n"
        "ViewRect= 0, 1, 1, 0\r\n"
        "Reach=Mixed Reach\r\n"
        "Type RM Length L Ch R =1,0.5682,,100,,0,0,0\r\n"
        "Node Desc=Nineteenth Cross Section\r\n"
        "#Sta/Elev=       4\r\n"
        "       0      80       0      70      20      70      20      80\r\n"
        "Bank Sta=0,20\r\n"
    )
    geometry.write_bytes(original.encode("ascii"))
    before = geometry.read_bytes()

    cross_sections = GeomCrossSection.get_cross_sections(geometry)
    metadata = GeomMetadata.get_geometry_counts(geometry)

    assert geometry.read_bytes() == before
    assert metadata["geometry_metadata_source"] == "text"
    assert metadata["geometry_metadata_valid"] is True
    assert metadata["has_1d_xs"] is True
    assert metadata["has_2d_mesh"] is False
    assert metadata["num_cross_sections"] == 1
    assert cross_sections.to_dict(orient="records") == [
        {
            "River": "Mixed Reach",
            "Reach": "Mixed Reach",
            "RS": "0.5682",
            "Type": 1,
            "Length_Left": 0.0,
            "Length_Channel": 100.0,
            "Length_Right": 0.0,
            "NodeName": "",
        }
    ]
