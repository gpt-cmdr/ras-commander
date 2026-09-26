"""Contract tests for the executed gridded-DSS window-extension example."""

from pathlib import Path

import nbformat


NOTEBOOK = Path("examples/728_extend_gridded_dss_forcing_window.ipynb")


def test_dss_window_notebook_covers_derivative_precompute_and_final_results():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(cell.source for cell in notebook.cells)

    required_source = [
        "RasDss.copy_grid_with_zero_tail(",
        "source_sha_before == source_sha_after",
        "RasUnsteady.configure_gridded_dss_precipitation(",
        "ratio=1.0",
        "RasPreprocess.preprocess_plan(",
        "solver_window[-TAIL_INTERVALS:]",
        "RasCmdr.compute_plan(",
        "HdfResultsPlan.get_compute_messages_hdf_only(",
        '"Cell Cumulative Precipitation Depth"',
        "active_mask",
        "RAS_COMMANDER_EXAMPLE_RUN_ROOT",
        "Review all HEC-RAS runtime and BCO messages",
    ]
    for expected in required_source:
        assert expected in source


def test_dss_window_notebook_is_fully_executed_clean_and_visual():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert len(code_cells) == 9
    assert all(cell.execution_count is not None for cell in code_cells)

    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert len(outputs) >= 14
    assert sum("image/png" in output.get("data", {}) for output in outputs) >= 4
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
    assert "UserWarning" not in rendered_text

    required_evidence = [
        "source SHA unchanged",
        "appended dry records",
        "maximum DSS-to-precompute error (in)",
        "BCO diagnostic lines",
        "DSS-to-final RMSE (in)",
        "active cells",
        "tail maximum rain rate",
        "DSS forcing-window extension qualification complete.",
        "Review all HEC-RAS runtime and BCO messages",
    ]
    for expected in required_evidence:
        assert expected in rendered_text

    assert "C:\\Users\\" not in rendered_text
    assert "Z:\\" not in rendered_text
