from pathlib import Path

import nbformat


NOTEBOOK = Path("examples/900_aorc_precipitation.ipynb")


def test_aorc_notebook_is_executed_end_to_end_qualification():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(cell.source for cell in notebook.cells)

    required_source = [
        "PrecipAorc.get_storm_catalog(",
        "FIRST_VALID_TIME = SIM_START + pd.Timedelta(hours=1)",
        "start_time=FIRST_VALID_TIME",
        "PrecipAorc.create_storm_plans(",
        "RasPreprocess.preprocess_plan(",
        "RasCmdr.compute_plan(",
        "comparison_error_in",
        "manual HEC-RAS diagnostics remain required",
    ]
    for expected in required_source:
        assert expected in source

    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert code_cells
    assert all(cell.execution_count is not None for cell in code_cells)

    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert len(outputs) >= 40
    assert sum("image/png" in output.get("data", {}) for output in outputs) >= 6
    assert not [output for output in outputs if output.output_type == "error"]

    rendered_text = "\n".join(
        output.get("text", "")
        if output.output_type == "stream"
        else output.get("data", {}).get("text/plain", "")
        for output in outputs
    )
    assert "AORC rain-on-grid QA complete" in rendered_text
    assert "maximum source-vs-HDF error (in)" in rendered_text
    assert "BCO diagnostic scan: no warning/error/fatal/failed/missing messages found" in rendered_text
