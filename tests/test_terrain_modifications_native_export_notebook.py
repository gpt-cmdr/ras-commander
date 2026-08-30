"""Source-contract checks for notebook 316 native terrain export evidence."""

from __future__ import annotations

import ast
import base64
import json
from pathlib import Path


NOTEBOOK_PATH = Path("examples/316_terrain_modifications.ipynb")


def _notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _source() -> str:
    return "\n".join("".join(cell.get("source", [])) for cell in _notebook()["cells"])


def _native_cells() -> list[dict]:
    markers = (
        "# Opt-in native RAS Mapper exports",
        "# Semantic off/on checks and review figure",
    )
    return [
        cell
        for cell in _notebook()["cells"]
        if any(marker in "".join(cell.get("source", [])) for marker in markers)
    ]


def _output_text(cell: dict) -> str:
    parts = []
    for output in cell.get("outputs", []):
        if output.get("output_type") == "stream":
            stream_text = output.get("text", "")
            parts.append(
                "".join(stream_text)
                if isinstance(stream_text, list)
                else stream_text
            )
        plain_text = output.get("data", {}).get("text/plain", "")
        parts.append(
            "".join(plain_text) if isinstance(plain_text, list) else plain_text
        )
    return "\n".join(parts)


def test_notebook_316_native_cells_are_default_safe_parseable_and_executed():
    source = _source()
    native_cells = _native_cells()

    assert "RUN_NATIVE_TERRAIN_EXPORT = False" in source
    assert "RAS_COMMANDER_RUN_NATIVE_TERRAIN_EXPORT" in source
    assert "RAS_COMMANDER_EXAMPLE_RUN_ROOT" in source
    assert "OVERWRITE_NATIVE_TERRAIN_EXPORT = False" in source
    assert len(native_cells) == 2
    for index, cell in enumerate(native_cells):
        assert cell["cell_type"] == "code"
        assert cell["execution_count"] == index + 6
        assert cell["outputs"]
        assert "execution" in cell["metadata"]
        assert not any(
            output.get("output_type") == "error" for output in cell["outputs"]
        )
        ast.parse("".join(cell["source"]), filename=f"native-cell-{index}")


def test_notebook_316_commits_real_portable_native_outputs_and_figure():
    export_cell, evidence_cell = _native_cells()
    export_text = _output_text(export_cell)
    evidence_text = _output_text(evidence_cell)

    for expected in (
        "Terrain50.baldeagledem.tif",
        "Terrain50.dtm_20ft.tif",
        "36.504512049933",
        "[20, 40, 80, 160, 320, 640]",
        "modifications_off",
        "modifications_on",
        "49168",
        "48517",
        "terrain50_modifications_off_2x.tif.receipt.json",
        "terrain50_modifications_on_2x.tif.receipt.json",
    ):
        assert expected in export_text

    for expected in (
        "3721",
        "264",
        "0.15625",
        "9.625",
        "1769",
        "terrain50_native_modification_evidence.png",
    ):
        assert expected in evidence_text

    for output_text in (export_text, evidence_text):
        assert "C:\\" not in output_text
        assert "C:/" not in output_text
        assert "G:\\" not in output_text
        assert "H:\\" not in output_text
        assert "billk_clb" not in output_text

    png_outputs = [
        output["data"]["image/png"]
        for output in evidence_cell["outputs"]
        if "image/png" in output.get("data", {})
    ]
    assert len(png_outputs) == 1
    png_bytes = base64.b64decode(png_outputs[0])
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png_bytes) > 50_000


def test_notebook_316_exports_original_mixed_source_terrain50_only():
    source = _source()
    native_source = "\n".join("".join(cell["source"]) for cell in _native_cells())

    for required in (
        "RasMap.list_terrain_layers",
        "RasTerrain.export_rasmapper_terrain",
        "TerrainExportResult",
        "terrain_layers_before['name'].eq('Terrain50')",
        "[36.504512049933, 20.0]",
        "source_inventory['authoritative_grid'].tolist() == [False, True]",
        "downsample_factor=2",
        "result.native_cell_size == 20.0",
        "result.output_cell_size == 40.0",
        "(result.validation['columns'], result.validation['rows']) == (61, 61)",
        "receipt['native_helper']['resample_to_one_rfi'] is True",
        "receipt['native_helper']['resample_method'] == 'near'",
        "pd.testing.assert_frame_equal(terrain_layers_before, terrain_layers_after)",
    ):
        assert required in native_source

    assert "Notebook316Export" not in source
    assert "create_terrain_hdf" not in native_source
    assert "create_terrain_from_rasters" not in native_source


def test_notebook_316_keeps_export_bounded_and_semantically_evidenced():
    source = _source()

    for coordinate in (
        "2041660.41918676",
        "347030.9951331958",
        "2044060.41918676",
        "349430.9951331958",
    ):
        assert coordinate in source

    for evidence in (
        "valid_cell_count == 3721",
        "affected_cell_count == 264",
        "[0.15625, 9.625]",
        "control_cell_count == 1769",
        "control_max_abs_delta_ft == 0.0",
        "take_higher must not lower terrain cells",
        "Modification-on minus modification-off",
        "Unchanged control cells",
        "fig.savefig(native_export_review_png",
    ):
        assert evidence in source
