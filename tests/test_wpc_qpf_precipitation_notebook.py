"""Contract tests for the executed WPC QPF DSS rain-on-grid qualification."""

from pathlib import Path

import nbformat


NOTEBOOK = Path("examples/926_wpc_qpf_precipitation_forecast.ipynb")


def test_wpc_notebook_covers_source_dss_precompute_and_final_results():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(cell.source for cell in notebook.cells)

    required_source = [
        "WPC QPF DSS-to-HEC-RAS Rain-on-Grid Qualification",
        "QPFRequest(",
        "kit.download_qpf(",
        'driver="GRIB"',
        "kit.qpf_dss.write(",
        "RasDss.read_grid(",
        "RasUnsteady.configure_gridded_dss_precipitation(",
        "ratio=1.0",
        "RasPreprocess.preprocess_plan(",
        "solver_window_mask",
        "RasCmdr.compute_plan(",
        "HdfResultsPlan.get_compute_messages_hdf_only(",
        '"Cell Cumulative Precipitation Depth"',
        "active_mesh_mask",
        "RAS_COMMANDER_EXAMPLE_RUN_ROOT",
        "Review all HEC-RAS runtime and BCO messages",
    ]
    for expected in required_source:
        assert expected in source

    assert "extents=WPC_BBOX" not in source
    assert "download_to_dss(" not in source


def test_wpc_notebook_is_fully_executed_clean_and_visual():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert len(code_cells) == 11
    assert all(cell.execution_count is not None for cell in code_cells)

    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert len(outputs) >= 25
    assert sum("image/png" in output.get("data", {}) for output in outputs) >= 5
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
    assert " - WARNING - " not in stderr_text
    assert " - ERROR - " not in stderr_text
    assert "UserWarning" not in rendered_text

    required_evidence = [
        "Downloaded GRIB files: 28",
        "Native-projection cropped GRIB files: 28",
        "Written DSS grids: 28",
        "Selected DSS mean total: 0.1491 inches",
        "maximum DSS-to-precompute error (in)",
        "Localized WSEL convergence outliers remain",
        "DSS-to-final RMSE (in)",
        "active positive-rain mesh cells",
        "WPC QPF DSS-to-HEC-RAS rain-on-grid qualification complete.",
        "Localized WSEL convergence exceptions are mapped",
        "Review all HEC-RAS runtime and BCO messages",
    ]
    for expected in required_evidence:
        assert expected in rendered_text

    assert "C:\\Users\\" not in rendered_text
    assert "Z:\\" not in rendered_text
