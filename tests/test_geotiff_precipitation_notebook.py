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


def test_notebook_is_fully_executed_clean_and_visual():
    code_cells = []
    for index, cell in enumerate(_notebook()["cells"]):
        if cell.get("cell_type") != "code":
            continue
        code_cells.append(cell)
        source = "".join(cell.get("source", []))
        compile(source, f"{NOTEBOOK_PATH.name}:cell-{index}", "exec")
        assert cell.get("execution_count") is not None

    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert len(code_cells) == 9
    assert len(outputs) >= 28
    assert sum("image/png" in output.get("data", {}) for output in outputs) >= 3
    assert not [output for output in outputs if output.get("output_type") == "error"]

    def output_text(output: dict) -> str:
        if output.get("output_type") == "stream":
            value = output.get("text", "")
        else:
            value = output.get("data", {}).get("text/plain", "")
        return "".join(value) if isinstance(value, list) else value

    rendered_text = "\n".join(output_text(output) for output in outputs)
    assert "HEC-RAS version" in rendered_text
    assert "6.6" in rendered_text
    assert "maximum source-vs-HDF error (in)" in rendered_text
    assert "Manual review of the full HEC-RAS runtime messages" in rendered_text
    assert "C:\\Users\\" not in rendered_text
    assert "Z:\\" not in rendered_text
