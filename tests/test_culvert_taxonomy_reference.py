import json
from importlib import resources

from ras_commander.geom.GeomCulvert import GeomCulvert


def _load_taxonomy():
    path = resources.files("ras_commander.resources").joinpath("culvert_taxonomy.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_culvert_taxonomy_shape_codes_match_geom_culvert_parser():
    taxonomy = _load_taxonomy()
    shapes = {shape["code"]: shape for shape in taxonomy["shapes"]}

    assert sorted(shapes) == list(range(1, 10))
    assert {
        code: shape["ras_commander_shape_name"]
        for code, shape in shapes.items()
    } == GeomCulvert.CULVERT_SHAPES

    for shape in shapes.values():
        assert shape["hec_ras_gui_label"]
        assert shape["rasmapper_enum"]
        assert shape["allowed_charts"]
        for chart in shape["allowed_charts"]:
            assert chart["chart_id"] > 0
            assert chart["hec_ras_gui_label"]
            assert chart["allowed_scales"]
            assert all(scale["scale_id"] > 0 for scale in chart["allowed_scales"])


def test_culvert_taxonomy_constraints_and_hdf_mapping_are_present():
    taxonomy = _load_taxonomy()

    assert taxonomy["global_constraints"]["culvert_groups_per_crossing"]["maximum"] == 10
    assert taxonomy["global_constraints"]["identical_barrels_per_group"]["maximum"] == 25
    assert "No user-defined shape code" in taxonomy["global_constraints"]["user_defined_shape_code"]

    geometry_hdf = taxonomy["hdf_mapping"]["geometry_hdf"]
    assert geometry_hdf["culvert_group_dataset"] == "Geometry/Structures/Culvert Groups"
    assert geometry_hdf["culvert_barrel_dataset"] == "Geometry/Structures/Culvert Groups/Barrels"

    group_labels = {
        column["value"]
        for column in taxonomy["gui_nomenclature"]["rasmapper_culvert_group_columns"]
    }
    assert {"Shape ID", "Chart ID", "Scale ID", "Use Momentum"} <= group_labels


def test_culvert_taxonomy_known_chart_scale_catalog_entries():
    taxonomy = _load_taxonomy()
    by_code = {shape["code"]: shape for shape in taxonomy["shapes"]}

    discrepancies = taxonomy["evidence"]["known_reflection_discrepancies"]
    assert any("ConSpan chart 60/61" in item["item"] for item in discrepancies)

    conspan = by_code[9]
    assert conspan["hec_ras_gui_label"] == "Conspan Arch"
    assert [chart["chart_id"] for chart in conspan["allowed_charts"]] == [60, 61]
    assert all(
        [scale["scale_id"] for scale in chart["allowed_scales"]] == [1, 2, 3]
        for chart in conspan["allowed_charts"]
    )

    circular = by_code[1]
    assert circular["dimension_model"]["gui_mode"] == "diameter"
    assert [chart["chart_id"] for chart in circular["allowed_charts"]] == [1, 2, 3, 55, 56]

    box = by_code[2]
    assert len(box["allowed_charts"]) == 13
