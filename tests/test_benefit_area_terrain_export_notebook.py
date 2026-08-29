"""Source-contract checks for notebook 612 terrain preparation guidance."""

from __future__ import annotations

import json
from pathlib import Path


NOTEBOOK_PATH = Path("examples/612_benefit_area_analysis.ipynb")


def _notebook_source() -> str:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell.get("source", [])) for cell in notebook["cells"]
    )


def test_benefit_area_notebook_prefers_native_registered_terrain_export():
    source = _notebook_source()

    for required in (
        "RasMap.list_terrain_layers(project_path)",
        "RasTerrain.export_rasmapper_terrain()",
        "registered source order, stitches, masks",
        "machine-readable receipt",
        "not registered back into the project",
    ):
        assert required in source


def test_benefit_area_notebook_preserves_creation_path_for_loose_rasters():
    source = _notebook_source()

    for required in (
        "RasTerrain.vrt_to_tiff()",
        "RasTerrain.create_terrain_from_rasters()",
        "RasTerrain.create_terrain_hdf()",
        "RasMap.add_terrain_layer()",
        "RasMap.associate_geometry_layers()",
        "new loose rasters",
    ):
        assert required in source


def test_benefit_area_notebook_separates_hydraulic_and_export_versions():
    source = _notebook_source()

    assert 'RAS_VERSION = "7.0"' in source
    assert 'TERRAIN_EXPORT_RAS_VERSION = "7.0.1"' in source
    assert "Do not select 7.0.0 for modification-aware terrain export" in source
    assert "7.0.1 contains the fix" in source
