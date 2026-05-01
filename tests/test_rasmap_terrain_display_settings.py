import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ras_commander import RasMap


def _make_project(tmp_path: Path, rasmap_body: str, name: str = "TerrainDisplay") -> Path:
    project_dir = tmp_path / name
    project_dir.mkdir()
    (project_dir / f"{name}.prj").write_text(
        "Proj Title=Terrain Display\nCurrent Plan=\n",
        encoding="utf-8",
    )
    (project_dir / f"{name}.rasmap").write_text(rasmap_body, encoding="utf-8")
    return project_dir


def _display_project(tmp_path: Path) -> Path:
    return _make_project(
        tmp_path,
        (
            "<RASMapper>\n"
            "  <Terrains Checked=\"True\" Expanded=\"True\">\n"
            "    <Layer Name=\"Existing Terrain\" Type=\"TerrainLayer\" Checked=\"True\" "
            "Filename=\".\\Terrain\\Existing.hdf\">\n"
            "      <Symbology>\n"
            "        <HillShade On=\"True\" ZFactor=\"1.5\" />\n"
            "        <Contour Checked=\"False\" ContourInterval=\"10\" />\n"
            "      </Symbology>\n"
            "      <Surface On=\"True\" />\n"
            "      <PlotOption>Plot stitch TIN edges</PlotOption>\n"
            "      <PlotOptionOff>Plot Level0 stitch TIN edges</PlotOptionOff>\n"
            "      <PlotOptionOff>Remove Stitch Rendering</PlotOptionOff>\n"
            "    </Layer>\n"
            "    <Layer Name=\"Terrain With Channel\" Type=\"TerrainLayer\" Checked=\"False\" "
            "Filename=\".\\Terrain\\Channel.hdf\">\n"
            "      <Symbology>\n"
            "        <HillShade Checked=\"False\" Z_Factor=\"2\" />\n"
            "        <Contour On=\"True\" Interval=\"2.5\" />\n"
            "      </Symbology>\n"
            "      <Surface On=\"False\" />\n"
            "      <PlotOptionOff Name=\"Plot stitch TIN edges\" />\n"
            "      <PlotOption Name=\"Plot Level0 stitch TIN edges\" />\n"
            "    </Layer>\n"
            "  </Terrains>\n"
            "</RASMapper>\n"
        ),
    )


def _layer_by_name(root: ET.Element, name: str) -> ET.Element:
    layer = root.find(f"./Terrains/Layer[@Name='{name}']")
    assert layer is not None
    return layer


def _plot_option_tags(layer: ET.Element) -> dict[str, str]:
    result = {}
    for option in layer:
        if option.tag not in {"PlotOption", "PlotOptionOff"}:
            continue
        name = option.attrib.get("Name") or (option.text or "").strip()
        result[name] = option.tag
    return result


def test_list_terrain_display_settings_reads_hillshade_contours_and_stitches(tmp_path):
    project_dir = _display_project(tmp_path)

    settings = RasMap.list_terrain_display_settings(project_dir)

    assert settings["name"].tolist() == ["Existing Terrain", "Terrain With Channel"]
    existing = settings.loc[settings["name"] == "Existing Terrain"].iloc[0]
    assert bool(existing["hillshade_enabled"]) is True
    assert existing["hillshade_z_factor"] == 1.5
    assert bool(existing["contour_enabled"]) is False
    assert existing["contour_interval"] == 10.0
    assert bool(existing["stitch_edges_enabled"]) is True
    assert bool(existing["stitch_tin_edges_enabled"]) is True
    assert bool(existing["level0_stitch_edges_enabled"]) is False
    assert bool(existing["remove_stitch_rendering_enabled"]) is False

    channel = RasMap.get_terrain_display_settings(
        project_dir,
        terrain_name="terrain with channel",
    )
    assert channel["name"] == "Terrain With Channel"
    assert channel["hillshade_enabled"] is False
    assert channel["hillshade_z_factor"] == 2.0
    assert channel["contour_enabled"] is True
    assert channel["contour_interval"] == 2.5
    assert channel["stitch_edges_enabled"] is False
    assert channel["level0_stitch_tin_edges_enabled"] is True


def test_get_terrain_display_settings_reports_ambiguous_and_unknown_names(tmp_path):
    project_dir = _display_project(tmp_path)

    with pytest.raises(ValueError, match="Multiple terrain layers"):
        RasMap.get_terrain_display_settings(project_dir)

    with pytest.raises(ValueError, match="not found"):
        RasMap.get_terrain_display_settings(project_dir, terrain_name="Missing")


def test_set_terrain_display_settings_preserves_existing_attribute_names(tmp_path):
    project_dir = _display_project(tmp_path)

    modified = RasMap.set_terrain_display_settings(
        project_dir,
        terrain_name="Terrain With Channel",
        hillshade_enabled=True,
        hillshade_z_factor=3.25,
        contour_enabled=False,
        contour_interval=6.5,
        stitch_edges_enabled=True,
        level0_stitch_edges_enabled=False,
        remove_stitch_rendering_enabled=True,
    )

    assert modified > 0
    root = ET.parse(project_dir / "TerrainDisplay.rasmap").getroot()
    layer = _layer_by_name(root, "Terrain With Channel")
    hillshade = layer.find("./Symbology/HillShade")
    contour = layer.find("./Symbology/Contour")
    assert hillshade is not None
    assert hillshade.attrib["Checked"] == "True"
    assert hillshade.attrib["Z_Factor"] == "3.25"
    assert "On" not in hillshade.attrib
    assert contour is not None
    assert contour.attrib["On"] == "False"
    assert contour.attrib["Interval"] == "6.5"

    option_tags = _plot_option_tags(layer)
    assert option_tags["Plot stitch TIN edges"] == "PlotOption"
    assert option_tags["Plot Level0 stitch TIN edges"] == "PlotOptionOff"
    assert option_tags["Remove Stitch Rendering"] == "PlotOption"

    updated = RasMap.get_terrain_display_settings(
        project_dir,
        terrain_name="Terrain With Channel",
    )
    assert updated["hillshade_enabled"] is True
    assert updated["hillshade_z_factor"] == 3.25
    assert updated["contour_enabled"] is False
    assert updated["contour_interval"] == 6.5
    assert updated["stitch_edges_enabled"] is True
    assert updated["level0_stitch_edges_enabled"] is False
    assert updated["remove_stitch_rendering_enabled"] is True


def test_set_terrain_display_settings_creates_missing_symbology(tmp_path):
    project_dir = _make_project(
        tmp_path,
        (
            "<RASMapper>\n"
            "  <Terrains>\n"
            "    <Layer Name=\"Bare Terrain\" Type=\"TerrainLayer\" "
            "Filename=\".\\Terrain\\Bare.hdf\" />\n"
            "  </Terrains>\n"
            "</RASMapper>\n"
        ),
    )

    modified = RasMap.set_terrain_display_settings(
        project_dir,
        terrain_name="Bare Terrain",
        hillshade_enabled=False,
        hillshade_z_factor=1.75,
        contour_enabled=True,
        contour_interval=5.0,
        stitch_tin_edges_enabled=False,
    )

    assert modified == 5
    root = ET.parse(project_dir / "TerrainDisplay.rasmap").getroot()
    layer = _layer_by_name(root, "Bare Terrain")
    assert layer.find("./Symbology/HillShade").attrib == {
        "On": "False",
        "ZFactor": "1.75",
    }
    assert layer.find("./Symbology/Contour").attrib == {
        "On": "True",
        "Interval": "5",
    }
    assert _plot_option_tags(layer)["Plot stitch TIN edges"] == "PlotOptionOff"


def test_set_terrain_display_settings_validates_empty_update_and_alias_conflicts(tmp_path):
    project_dir = _display_project(tmp_path)

    with pytest.raises(ValueError, match="At least one"):
        RasMap.set_terrain_display_settings(
            project_dir,
            terrain_name="Existing Terrain",
        )

    with pytest.raises(ValueError, match="disagree"):
        RasMap.set_terrain_display_settings(
            project_dir,
            terrain_name="Existing Terrain",
            stitch_edges_enabled=True,
            stitch_tin_edges_enabled=False,
        )


def test_set_terrain_display_settings_unknown_name_returns_zero(tmp_path):
    project_dir = _display_project(tmp_path)

    modified = RasMap.set_terrain_display_settings(
        project_dir,
        terrain_name="Missing",
        contour_enabled=True,
    )

    assert modified == 0


def test_existing_terrain_visibility_api_still_operates(tmp_path):
    project_dir = _display_project(tmp_path)

    modified = RasMap.set_terrain_layer_visibility(
        project_dir,
        terrain_name="Terrain With Channel",
        checked=True,
        exclusive=True,
    )

    assert modified > 0
    layers = RasMap.list_terrain_layers(project_dir)
    visible = layers.loc[layers["checked"] == True, "name"].tolist()
    assert visible == ["Terrain With Channel"]
