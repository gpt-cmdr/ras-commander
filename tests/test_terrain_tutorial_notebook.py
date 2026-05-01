import json
from pathlib import Path


NOTEBOOK_PATH = Path("examples/920_terrain_creation.ipynb")
OFFICIAL_TUTORIAL_URL = (
    "https://www.hec.usace.army.mil/confluence/rasdocs/hgt/latest/"
    "tutorials/terrain/creating-a-ras-terrain"
)


def _notebook_source() -> str:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
    )


def test_terrain_tutorial_notebook_references_official_source():
    source = _notebook_source()

    assert OFFICIAL_TUTORIAL_URL in source
    assert "Official Tutorial Coverage" in source
    assert "CLB-253" in source


def test_terrain_tutorial_notebook_maps_current_api_surface():
    source = _notebook_source()

    for api_name in [
        "RasTerrain.create_terrain_hdf",
        "RasTerrain.create_terrain_from_rasters",
        "Usgs3depAws",
        "RasMap.add_terrain_layer",
        "RasMap.list_terrain_layers",
        "RasMap.associate_geometry_layers",
    ]:
        assert api_name in source

    assert "CLB-270: standalone project projection assignment API" in source
    assert "USGS product type/year filtering" in source
    assert "hillshade, contour, and stitch TIN edge" in source


def test_terrain_tutorial_notebook_keeps_heavy_cells_opt_in():
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    source = _notebook_source()

    assert "RUN_USGS_DOWNLOAD = False" in source
    assert "RUN_TERRAIN_CREATION = False" in source
    assert "RUN_MULTI_SOURCE_TERRAIN_CREATION = False" in source

    for cell in notebook["cells"]:
        if cell.get("cell_type") != "code":
            continue
        assert cell.get("execution_count") is None
        assert cell.get("outputs", []) == []
