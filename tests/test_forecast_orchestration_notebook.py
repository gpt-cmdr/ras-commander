"""Contract tests for the executed forecast-orchestration overview."""

from pathlib import Path

import nbformat


NOTEBOOK = Path("examples/915_realtime_forecast_workflow.ipynb")


def test_forecast_overview_is_honest_and_uses_current_api_contracts():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(cell.source for cell in notebook.cells)

    required_source = [
        "Operational Forecast Orchestration and Readiness",
        "does **not** duplicate their expensive downloads",
        "not independent format",
        "PrecipHrrr.check_availability",
        "CoastalBoundary.check_availability",
        "RasPlan.update_simulation_date",
        '("plan_number_or_path", "start_date", "end_date")',
        'model_timezone="America/New_York"',
        "temporary plan HDF",
        "completed plan HDF",
        "Review product completeness",
    ]
    for expected in required_source:
        assert expected in source

    stale_or_misleading_source = [
        "PrecipHrrr.to_spatially_varied",
        "RasUsgsBoundaryGeneration.generate_bc_from_gauge",
        "new_start_date=",
        "Example output:",
        "datetime.now()",
        "shutil.rmtree",
    ]
    for forbidden in stale_or_misleading_source:
        assert forbidden not in source


def test_forecast_overview_is_fully_executed_clean_and_visual():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert len(code_cells) == 6
    assert all(cell.execution_count is not None for cell in code_cells)

    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert len(outputs) >= 10
    assert sum("image/png" in output.get("data", {}) for output in outputs) >= 2
    assert not [output for output in outputs if output.output_type == "error"]

    rendered_text = "\n".join(
        output.get("text", "")
        if output.output_type == "stream"
        else output.get("data", {}).get("text/plain", "")
        for output in outputs
    )
    stderr_text = "\n".join(
        output.get("text", "")
        for output in outputs
        if output.output_type == "stream" and output.get("name") == "stderr"
    )
    assert not stderr_text
    assert "C:\\Users\\" not in rendered_text
    assert "Z:\\" not in rendered_text
    assert "component notebooks are fully executed" in rendered_text
    assert "Operational forecast orchestration/readiness audit complete." in rendered_text
    assert "not format or HEC-RAS version qualification" in rendered_text
