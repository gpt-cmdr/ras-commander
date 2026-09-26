"""Source and retained-output checks for the Austin Bayou breakout example."""

from pathlib import Path

import nbformat


NOTEBOOK = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "959_ebfe_2d_breakout_geometry_preparation.ipynb"
)


def test_austin_bayou_breakout_notebook_covers_complete_workflow():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(cell.source for cell in notebook.cells)

    required_calls = (
        'RasExamples.extract_project(',
        'HdfBndry.get_bc_external_faces(',
        'GeomBcLines.delete_bc_line(',
        'GeomBcLines.add_bc_lines(',
        'RasUnsteady.replace_2d_boundary_locations(',
        'RasUnsteady.set_boundary_inline_hydrograph(',
        'RasUnsteady.set_normal_depth_boundary(',
        'RasNetworkConflation.classify_edges(',
        'RasBreakout2D.preflight(',
        'HdfResultsMesh.get_mesh_max_ws(',
    )
    assert all(call in source for call in required_calls)
    assert "AustinBayouSH35Firehose" in source
    assert "USGS_08078400.shp" in source
    assert "Inflow_US" in source
    assert 'bc_line="Emitter1"' not in source
    assert "David Maidement" not in source
    assert "Andy Carter" not in source
    assert "Jacob" not in source
    assert "manual diagnostics" in source


def test_austin_bayou_breakout_notebook_is_executed_clean_and_visual():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]

    assert all(cell.execution_count is not None for cell in code_cells)
    assert not any(output.output_type == "error" for output in outputs)
    assert sum(
        output.output_type == "display_data"
        and "image/png" in output.get("data", {})
        for output in outputs
    ) >= 3
