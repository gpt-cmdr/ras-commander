"""Source and retained-evidence contracts for notebook 236."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


NOTEBOOK_PATH = Path(
    "examples/236_multi_model_1d_breakout_planning.ipynb"
)
ASSET_ROOT = Path(
    "examples/assets/236_multi_model_1d_breakout_planning"
)


def _notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _source() -> str:
    return "\n".join(
        "".join(cell.get("source", [])) for cell in _notebook()["cells"]
    )


def test_notebook_236_uses_real_multi_model_texas_workflow():
    source = _source()

    assert "ALUM CREEK TRIBUTARY 9" in source
    assert "ALUM CREEK" in source
    assert 'TARGET_EDGE_ID = "5789096"' in source
    assert "RasBreakout1D.catalog_sources(" in source
    assert "RasBreakout1D.plan_network_edge(" in source
    assert "MAX_CENTERLINE_OFFSET_FT = 500.0" in source
    assert "GeoParquet" in source
    assert "provisional" in source
    assert "Notebook 235" in source


def test_notebook_236_retains_executed_visual_evidence():
    notebook = _notebook()
    code_cells = [
        cell for cell in notebook["cells"] if cell.get("cell_type") == "code"
    ]

    assert code_cells
    assert all(cell.get("execution_count") is not None for cell in code_cells)
    assert all(
        output.get("output_type") != "error"
        for cell in code_cells
        for output in cell.get("outputs", [])
    )
    assert any(
        output.get("output_type") == "display_data"
        and "image/png" in output.get("data", {})
        for cell in code_cells
        for output in cell.get("outputs", [])
    )
    for name in (
        "01_extent_and_geometry_confirmation.png",
        "02_directed_coverage_chain.png",
        "03_cross_section_ownership.png",
    ):
        path = ASSET_ROOT / name
        assert path.is_file()
        assert path.stat().st_size > 50_000


def test_notebook_236_code_cells_compile_and_gallery_entry_exists():
    notebook = _notebook()
    for index, cell in enumerate(notebook["cells"]):
        if cell.get("cell_type") == "code":
            compile(
                "".join(cell.get("source", [])),
                f"{NOTEBOOK_PATH}::cell-{index}",
                "exec",
            )

    metadata = yaml.safe_load(
        Path("examples/notebooks.yml").read_text(encoding="utf-8")
    )
    entry = next(
        item
        for item in metadata["notebooks"]
        if item["id"] == "236_multi_model_1d_breakout_planning"
    )
    assert entry["executed_cells"] == entry["code_cells"] == 6
    assert {"1d", "breakout", "ebfe", "nwm", "multi-model"} <= set(
        entry["tags"]
    )
