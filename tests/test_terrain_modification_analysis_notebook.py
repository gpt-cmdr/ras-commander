"""Execution-evidence checks for the terrain modification analysis example."""

from __future__ import annotations

import ast
import json
from pathlib import Path


NOTEBOOK_PATH = Path("examples/930_terrain_modification_analysis.ipynb")


def _notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _source() -> str:
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in _notebook()["cells"]
    )


def _output_text(notebook: dict) -> str:
    return "\n".join(
        "".join(output.get("text", []))
        for cell in notebook["cells"]
        for output in cell.get("outputs", [])
        if output.get("output_type") == "stream"
    )


def test_terrain_modification_analysis_notebook_is_portable_and_analytical():
    source = _source()

    assert "RAS_COMMANDER_EXAMPLE_RUN_ROOT" in source
    assert "EXAMPLE_PROJECTS_ROOT" in source
    assert "run_path(project_path)" in source
    assert "RasTerrainModWriter.add_channel_modification" in source
    assert "RasTerrainMod.get_terrain_profile" in source
    assert "RasTerrainMod.get_terrain_volume_elevation" in source
    assert "compute_plan" not in source
    assert "compute_parallel" not in source
    assert "RasControl" not in source
    assert "C:\\GH" not in source
    assert "H:\\" not in source


def test_terrain_modification_analysis_notebook_commits_fresh_evidence():
    notebook = _notebook()
    code_cells = [
        cell for cell in notebook["cells"] if cell.get("cell_type") == "code"
    ]

    assert len(code_cells) == 10
    assert [cell.get("execution_count") for cell in code_cells] == list(range(1, 11))
    assert all("execution" in cell.get("metadata", {}) for cell in code_cells)
    assert all(
        output.get("output_type") != "error"
        for cell in code_cells
        for output in cell.get("outputs", [])
    )

    images = [
        output["data"]["image/png"]
        for cell in code_cells
        for output in cell.get("outputs", [])
        if output.get("output_type") in {"display_data", "execute_result"}
        and "image/png" in output.get("data", {})
    ]
    assert len(images) == 2

    output_text = _output_text(notebook)
    for evidence in (
        "Project: run\\example_projects\\BaldEagleCrkMulti2D_930_terrainmod",
        "Modification: River Channel",
        "Alignment: 100 points",
        "Profile: 2961 points sampled",
        "Volume-elevation: 42 points",
    ):
        assert evidence in output_text

    serialized = json.dumps(notebook)
    assert "Documents\\\\Codex" not in serialized
    assert "ras-commander-native-terrain-export" not in serialized


def test_terrain_modification_analysis_notebook_code_cells_compile():
    for index, cell in enumerate(_notebook()["cells"]):
        if cell.get("cell_type") != "code":
            continue
        ast.parse(
            "".join(cell.get("source", [])),
            filename=f"{NOTEBOOK_PATH.name}:cell-{index}",
        )
