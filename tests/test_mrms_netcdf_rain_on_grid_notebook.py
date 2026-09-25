"""Contract tests for the focused MRMS rain-on-grid example notebook."""

import json
from pathlib import Path


NOTEBOOK_PATH = Path("examples/924_mrms_netcdf_rain_on_grid.ipynb")


def _code_source() -> str:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )


def test_notebook_covers_native_authoring_precompute_and_final_results():
    source = _code_source()

    assert "RasUnsteady.set_gridded_precipitation(" in source
    assert 'units="mm"' in source
    assert 'value_type="amount"' in source
    assert "first_timestep_hours=1.0" in source
    assert "ratio=1.0" in source

    assert "RasPreprocess.preprocess_plan(" in source
    assert "Event Conditions/Meteorology/Precipitation/Values" in source
    assert "Event Conditions/Meteorology/Precipitation/Timestamp" in source
    assert "np.nanmax(solver_values)" in source

    assert "RasCmdr.compute_plan(" in source
    assert "HdfResultsPlan.get_compute_messages_hdf_only(" in source
    assert '"Processing Precipitation data" in compute_messages' in source
    assert "Manual review of the full runtime messages" in source
    assert '"Cell Precipitation Rate"' in source
    assert '"Cell Cumulative Precipitation Depth"' in source
    assert '"Cell Hydraulic Depth"' in source
    assert source.count("plt.subplots(") >= 4


def test_committed_notebook_remains_output_stripped():
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    code_cells = [
        cell for cell in notebook["cells"] if cell.get("cell_type") == "code"
    ]

    assert all(cell.get("execution_count") is None for cell in code_cells)
    assert all(not cell.get("outputs") for cell in code_cells)
