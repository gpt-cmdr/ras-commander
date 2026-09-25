"""Source contract for the direct GeoTIFF rain-on-grid notebook."""

import json
from pathlib import Path


NOTEBOOK_PATH = Path("examples/729_direct_geotiff_gridded_rain_on_grid.ipynb")


def _notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _code_source() -> str:
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in _notebook()["cells"]
        if cell.get("cell_type") == "code"
    )


def test_notebook_covers_direct_geotiff_precompute_compute_and_figures():
    source = _code_source()

    assert "RasExamples.extract_project(" in source
    assert "RasUnsteady.get_gridded_precipitation_capabilities(" in source
    assert "RasUnsteady.set_gridded_precipitation_geotiff(" in source
    assert 'units="mm"' in source
    assert 'value_type="amount"' in source
    assert "first_timestep_hours=1.0" in source
    assert "ratio=1.0" in source
    assert 'nodata_policy="error"' in source
    assert "RasPreprocess.preprocess_plan(" in source
    assert "Event Conditions/Meteorology/Precipitation/Values" in source
    assert "RasCmdr.compute_plan(" in source
    assert '"Cell Cumulative Precipitation Depth"' in source
    assert '"Cell Hydraulic Depth"' in source
    assert "Manual review of the full HEC-RAS runtime messages" in source
    assert source.count("plt.subplots(") >= 3


def test_notebook_code_compiles_and_outputs_are_stripped():
    for index, cell in enumerate(_notebook()["cells"]):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        compile(source, f"{NOTEBOOK_PATH.name}:cell-{index}", "exec")
        assert cell.get("execution_count") is None
        assert not cell.get("outputs")
