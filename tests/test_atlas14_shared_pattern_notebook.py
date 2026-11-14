"""Contract tests for notebook 731 (Atlas 14 shared temporal pattern, existing model)."""

from pathlib import Path

import nbformat


NOTEBOOK = Path(__file__).resolve().parents[1] / "examples/731_atlas14_shared_temporal_existing_model.ipynb"


def _code_source(notebook):
    return "\n".join(cell.source for cell in notebook.cells if cell.cell_type == "code")


def test_native_export_states_its_lattice_and_gates_missing_cells():
    source = _code_source(nbformat.read(NOTEBOOK, as_version=4))

    # The native route writes to a stated envelope; align="vortex" moves the grid.
    assert 'align="vortex",' not in source  # the keyword argument, not the explanatory comment
    assert 'DSS_EXPORT_ROUTE = "native"' in source
    for expected in (
        "envelope=envelope",
        "FORCING_MARGIN_CELLS",
        "FORCING_TOLERANCE_IN",
        'raise RuntimeError("Missing DSS cells on the forcing lattice',
        "resampling=Resampling.bilinear, tolerance=0",
        'raise RuntimeError("DSS grids do not match the full-source warp',
        "include_ghost_cells=False",
        'raise RuntimeError("Some mesh cells would sample missing or off-lattice forcing")',
    ):
        assert expected in source
    # Missing cells must never be read as dry rain.
    for hidden in ("np.nansum", "np.nanmin(dss_values", "np.nanmax(np.abs(dss_values"):
        assert hidden not in source


def test_committed_preset_run_passes_missing_cell_full_source_and_mesh_gates():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    assert all(cell.execution_count is not None for cell in code_cells)
    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert not [output for output in outputs if output.output_type == "error"]
    text = "\n".join(
        output.get("text", "")
        if output.output_type == "stream"
        else output.get("data", {}).get("text/plain", "")
        for output in outputs
    )
    for expected in (
        "export route: native",
        "FAST-DSS wrote 144 grid records on envelope",
        "missing cells per record: [0]; missing in every record: 0; in some record: 0",
        "Full-source warp: 0 reference cells outside NOAA coverage",
        "off the lattice or on a missing cell: 0; bilinear stencil touching a missing or off-lattice cell: 0",
        "DSS intervals, missing-cell, full-source and mesh checks passed",
    ):
        assert expected in text
    for private in ("C:\\Users\\", "D:\\", "H:\\", "AppData", "/home/", "/Users/"):
        assert private not in text
