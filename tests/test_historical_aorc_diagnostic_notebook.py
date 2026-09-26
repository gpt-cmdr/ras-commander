"""Contract tests for the executed historical AORC diagnostic notebook."""

from pathlib import Path

import nbformat


NOTEBOOK = Path("examples/914_historical_event_validation.ipynb")


def test_historical_aorc_notebook_states_and_implements_qualified_scope():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(cell.source for cell in notebook.cells)

    required_source = [
        "Historical AORC Event Diagnostic Comparison with USGS Stage",
        "diagnostic comparison, not a calibration validation",
        "PrecipAorc.download(",
        "RasUnsteady.set_gridded_precipitation(",
        "RasPreprocess.preprocess_plan(",
        "RasCmdr.compute_plan(",
        "Cell Cumulative Precipitation Depth",
        '.dt.tz_convert("America/New_York")',
        'dtype="datetime64[ns]"',
        "historical boundary hydrographs and gate operations were not supplied",
        "Review all HEC-RAS runtime and BCO messages",
    ]
    for expected in required_source:
        assert expected in source


def test_historical_aorc_notebook_is_fully_executed_clean_and_visual():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert len(code_cells) == 9
    assert all(cell.execution_count is not None for cell in code_cells)

    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert len(outputs) >= 16
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
    assert not stderr_text
    assert "C:\\Users\\" not in rendered_text
    assert "Z:\\" not in rendered_text

    required_evidence = [
        "valid precipitation positions",
        "maximum source-to-precompute error (in)",
        "maximum source-to-final error (in)",
        "BCO diagnostic lines",
        "observed peak WSE (ft)",
        "modeled peak WSE (ft)",
        "Historical AORC event forcing and diagnostic comparison complete.",
        "The USGS comparison is not a calibration validation",
    ]
    for expected in required_evidence:
        assert expected in rendered_text
