"""Contract tests for the executed MRMS boundary-hyetograph comparison."""

from pathlib import Path

import nbformat


NOTEBOOK = Path("examples/917_mrms_precipitation_qpe.ipynb")


def test_mrms_boundary_notebook_states_and_implements_its_actual_scope():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(cell.source for cell in notebook.cells)

    required_source = [
        "MRMS QPE Boundary-Hyetograph Hydraulic Comparison",
        "uniform precipitation-boundary",
        "PrecipMrms.to_dss(",
        "PrecipMrms.to_hyetograph(",
        "RasUnsteady.set_precipitation_hyetograph(",
        "HdfResultsPlan.get_compute_messages_hdf_only(",
        "audit_runtime_messages(",
        "RAS_COMMANDER_EXAMPLE_RUN_ROOT",
        "Review all BCO/runtime diagnostics",
        "Use notebook 924 when spatial MRMS variability must be consumed by the solver.",
    ]
    for expected in required_source:
        assert expected in source

    assert "RasUnsteady.configure_gridded_dss_precipitation(" not in source
    assert "RasUnsteady.set_gridded_precipitation(" not in source
    assert "qpkit" not in source


def test_mrms_boundary_notebook_is_fully_executed_clean_and_visual():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert len(code_cells) == 7
    assert all(cell.execution_count is not None for cell in code_cells)

    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert len(outputs) >= 100
    assert sum("image/png" in output.get("data", {}) for output in outputs) >= 8
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

    required_evidence = [
        "Spatial-mean event depth: 1.745 inches",
        "Serialized event depth: 1.730 inches",
        "Spatial-mean event depth: 4.096 inches",
        "Serialized event depth: 4.100 inches",
        "QA/QC reminder: these runs use an intentionally uniform precipitation boundary.",
        "Use notebook 924 when spatial MRMS variability must be consumed by the solver.",
    ]
    for expected in required_evidence:
        assert expected in rendered_text

    assert "C:\\Users\\" not in rendered_text
    assert "Z:\\" not in rendered_text
