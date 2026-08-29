"""Source-contract checks for the native RAS Mapper terrain export example."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import yaml


NOTEBOOK_PATH = Path("examples/931_native_rasmapper_terrain_export.ipynb")
METADATA_PATH = Path("examples/notebooks.yml")
DOCS_SCRIPTS = Path(".claude/scripts").resolve()
if str(DOCS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DOCS_SCRIPTS))

from _docs_notebook_common import section_for  # noqa: E402


def _notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _source() -> str:
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in _notebook()["cells"]
    )


def test_native_terrain_export_notebook_has_clean_executable_source():
    notebook = _notebook()

    assert "".join(notebook["cells"][0]["source"]).startswith(
        "# Native RAS Mapper Terrain Export"
    )
    for index, cell in enumerate(notebook["cells"]):
        if cell.get("cell_type") != "code":
            continue
        assert cell.get("execution_count") is None
        assert cell.get("outputs", []) == []
        ast.parse(
            "".join(cell.get("source", [])),
            filename=f"{NOTEBOOK_PATH.name}:cell-{index}",
        )


def test_native_terrain_export_notebook_keeps_native_work_opt_in_and_bounded():
    source = _source()

    assert "RUN_NATIVE_EXPORT = False" in source
    assert "OVERWRITE_EXISTING = False" in source
    assert 'RAS_VERSION = "6.6"' in source
    assert 'TERRAIN_NAME = "TerrainWithChannel"' in source
    assert "DOWNSAMPLE_FACTOR = 2" in source
    assert "RASTERIZE_MODIFICATIONS = True" in source
    for coordinate in (
        "404147.258781418",
        "1801881.85296284",
        "404307.258781418",
        "1802111.85296284",
    ):
        assert coordinate in source


def test_native_terrain_export_notebook_covers_public_contract_and_evidence():
    source = _source()

    for required in (
        "RasMap.list_terrain_layers",
        "RasTerrain.export_rasmapper_terrain",
        "TerrainExportResult",
        "result.source_inventory",
        "result.validation",
        "result.receipt_path",
        "pd.testing.assert_frame_equal",
        "fig.savefig",
        "Requested extent",
        "Snapped output grid",
    ):
        assert required in source

    for release_statement in (
        "6.3 / 6.3.1",
        "6.4.1, 6.5, 6.6",
        "7.0.0",
        "7.0.1",
        "7.1 | Forward-open, not pre-qualified",
    ):
        assert release_statement in source

    assert "H:\\" not in source
    assert "C:\\GH" not in source


def test_native_terrain_export_notebook_is_registered_for_the_gallery():
    metadata = yaml.safe_load(METADATA_PATH.read_text(encoding="utf-8"))
    entries = {
        entry["id"]: entry
        for entry in metadata["notebooks"]
    }
    entry = entries["931_native_rasmapper_terrain_export"]

    assert entry["filename"] == NOTEBOOK_PATH.name
    assert entry["data_project"] == "Muncie"
    assert entry["executed_cells"] == 0
    assert "RasTerrain.export_rasmapper_terrain" in entry["functions_used"]
    assert {"terrain", "rasmapper"}.issubset(entry["tags"])


def test_native_terrain_export_notebook_uses_terrain_docs_section():
    assert section_for("931_native_rasmapper_terrain_export") == (
        920,
        "920s - Terrain & Surfaces",
    )
