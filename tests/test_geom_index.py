from ras_commander.geom.GeomIndex import GeomIndex
from ras_commander.geom.GeomBridge import GeomBridge
from ras_commander.geom.GeomCulvert import GeomCulvert
from ras_commander.geom.GeomCrossSection import GeomCrossSection
from ras_commander.geom.GeomInlineWeir import GeomInlineWeir


def _sample_lines():
    return [
        "River Reach=River A,Reach 1\n",
        "Type RM Length L Ch R = 1,100.0,0,0,0\n",
        "#Sta/Elev= 2\n",
        "       0      10      1      11\n",
        "Type RM Length L Ch R = 3,90.0,0,0,0\n",
        "Bridge Culvert- 0,0,0,0,0\n",
        "Deck Dist Width WeirC= 1,2,3\n",
        "Type RM Length L Ch R = 4,80.0,0,0,0\n",
        "IW Pilot Flow= 0\n",
        "River Reach=River B,Reach 2\n",
        "Lat Struct=Lat A,0,0\n",
        "#Lat Struct Sta/Elev= 2\n",
        "       0      10      1      11\n",
        "Storage Area=Storage A\n",
        "SA/2D Area Conn=Conn A,Storage A,Area A\n",
    ]


def test_geom_index_finds_core_record_types():
    index = GeomIndex.from_lines(_sample_lines())

    xs = GeomIndex.find(
        index,
        "cross_section",
        river="River A",
        reach="Reach 1",
        rs="100.0",
    )
    bridge = GeomIndex.find(
        index,
        "bridge_culvert",
        river="River A",
        reach="Reach 1",
        rs="90.0",
    )
    inline = GeomIndex.find(
        index,
        "inline_weir",
        river="River A",
        reach="Reach 1",
        rs="80.0",
    )
    lateral = GeomIndex.find(index, "lateral_structure", name="Lat A")
    storage = GeomIndex.find(index, "storage_area", name="Storage A")
    connection = GeomIndex.find(index, "sa_2d_connection", name="Conn A")

    assert xs.start_idx == 1
    assert xs.end_idx == 4
    assert bridge.marker_idx == 5
    assert inline.marker_idx == 8
    assert lateral.start_idx == 10
    assert storage.start_idx == 13
    assert connection.start_idx == 14


def test_geom_index_helpers_find_keywords_and_data_sections():
    index = GeomIndex.from_lines(_sample_lines())
    xs = GeomIndex.find(index, "cross_section", rs="100.0")
    keyword_idx = GeomIndex.find_keyword(index, xs, "#Sta/Elev")

    assert keyword_idx == 2
    assert GeomIndex.data_section(index, keyword_idx) == (3, 4)


def test_existing_private_finders_can_delegate_to_index():
    lines = _sample_lines()

    assert GeomCrossSection._find_cross_section(
        lines, "River A", "Reach 1", "100.0"
    ) == 1
    assert GeomCrossSection._find_xs_section_end(lines, 1) == 4
    assert GeomBridge._find_bridge(lines, "River A", "Reach 1", "90.0") == 5
    assert GeomCulvert._find_bridge(lines, "River A", "Reach 1", "90.0") == 5
    assert GeomInlineWeir._find_inline_weir(
        lines, "River A", "Reach 1", "80.0"
    ) == 8
