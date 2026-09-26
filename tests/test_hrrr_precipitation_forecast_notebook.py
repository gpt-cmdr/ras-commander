"""Contract tests for the executed HRRR-to-DSS HEC-RAS qualification."""

from pathlib import Path

import nbformat


NOTEBOOK = Path("examples/916_hrrr_precipitation_forecast.ipynb")


def test_hrrr_notebook_covers_source_dss_precompute_and_final_results():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(cell.source for cell in notebook.cells)

    required_source = [
        "Herbie(",
        "kit.hrrr_dss.write(",
        "RasDss.read_grid(",
        "RasUnsteady.configure_gridded_dss_precipitation(",
        "ratio=1.0",
        "RasPreprocess.preprocess_plan(",
        "np.flipud(dss_total).reshape(-1)",
        "RasCmdr.compute_plan(",
        '"Cell Cumulative Precipitation Depth"',
        "DSS-to-final RMSE (in)",
        "diagnostic_pattern = re.compile(",
        "Manual review of HEC-RAS Mapper",
    ]
    for expected in required_source:
        assert expected in source


def test_hrrr_notebook_is_fully_executed_clean_and_visual():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert code_cells
    assert all(cell.execution_count is not None for cell in code_cells)

    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert len(outputs) >= 25
    assert sum("image/png" in output.get("data", {}) for output in outputs) >= 6
    assert not [output for output in outputs if output.output_type == "error"]
    assert not [
        output
        for output in outputs
        if output.output_type == "stream" and output.get("name") == "stderr"
    ]

    rendered_text = "\n".join(
        output.get("text", "")
        if output.output_type == "stream"
        else output.get("data", {}).get("text/plain", "")
        for output in outputs
    )
    assert "HRRR rain-on-grid qualification complete" in rendered_text
    assert "maximum DSS-to-precompute error (in)" in rendered_text
    assert "DSS-to-final RMSE (in)" in rendered_text
    assert "Localized WSEL convergence outliers remain" in rendered_text
    assert "Manual review of HEC-RAS Mapper" in rendered_text
    assert "C:\\Users\\" not in rendered_text
