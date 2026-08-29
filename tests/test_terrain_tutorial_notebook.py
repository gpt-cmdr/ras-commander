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
        "RasTerrain.export_rasmapper_terrain",
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
    assert "RUN_REGISTERED_TERRAIN_EXPORT = False" in source

    native_export_cells = [
        cell
        for cell in notebook["cells"]
        if cell.get("id") == "registered-terrain-export-example"
    ]
    assert len(native_export_cells) == 1
    assert native_export_cells[0].get("execution_count") is None
    assert native_export_cells[0].get("outputs", []) == []


def test_registered_terrain_export_is_distinct_from_terrain_creation():
    source = _notebook_source()

    assert "Export an Already Registered Terrain" in source
    assert "different source resolutions" in source
    assert "source ordering" in source
    assert "stitches, masks, and optional vector modifications" in source
    assert "REGISTERED_TERRAIN_EXPORT_RAS_VERSION = \"6.6\"" in source
    assert "REGISTERED_TERRAIN_EXPORT_DOWNSAMPLE_FACTOR = 2" in source
    assert "rasterize_modifications=True" in source
    assert "overwrite=False" in source
    assert "931_native_rasmapper_terrain_export.ipynb" in source
    assert "316_terrain_modifications.ipynb" in source
    assert "does not replace the loose-raster creation APIs" in source
    assert "does not create the cross-section channel bathymetry raster" in source
