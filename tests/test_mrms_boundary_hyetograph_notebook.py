"""Contract tests for the executed MRMS boundary-hyetograph comparison."""

import ast
import json
import math
from pathlib import Path
import re

import nbformat


NOTEBOOK = Path("examples/917_mrms_precipitation_qpe.ipynb")
QUALIFICATION_PREFIX = "MRMS_ABSOLUTE_TIME_QUALIFICATION="


def test_mrms_boundary_notebook_states_and_implements_its_actual_scope():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    source = "\n".join(cell.source for cell in notebook.cells)

    assert "MRMS QPE Boundary-Hyetograph Hydraulic Comparison" in source
    assert "RAS_COMMANDER_EXAMPLE_RUN_ROOT" in source
    tree = ast.parse("\n".join(cell.source for cell in notebook.cells if cell.cell_type == "code"))
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert {
        "PrecipMrms.to_dss", "PrecipMrms.to_hyetograph",
        "RasUnsteady.set_precipitation_hyetograph",
        "HdfResultsPlan.get_compute_messages_hdf_only",
        "HdfResultsMesh.get_mesh_timeseries", "audit_runtime_messages",
        "validate_source_hyetograph", "align_animation_precipitation", "summarize_runtime_messages",
    } <= calls
    assert not {
        "RasUnsteady.configure_gridded_dss_precipitation",
        "RasUnsteady.set_gridded_precipitation",
    } & calls


def test_mrms_boundary_notebook_is_fully_executed_with_preserved_diagnostics_and_visuals():
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code" and cell.source.strip()]
    assert code_cells
    assert all(cell.execution_count is not None for cell in code_cells)

    outputs = [output for cell in code_cells for output in cell.get("outputs", [])]
    assert any("image/png" in output.get("data", {}) for output in outputs)
    assert not [output for output in outputs if output.output_type == "error"]

    # Read the computed audit result, not a source-code literal or displayed
    # True column. Saved output may inspect genuine retained runs without
    # relaunching them, so terminal compute strings are not required here.
    stream_text = "".join(output.get("text", "") for output in outputs if output.output_type == "stream")
    summaries = [json.loads(line.removeprefix(QUALIFICATION_PREFIX))
                 for line in stream_text.splitlines() if line.startswith(QUALIFICATION_PREFIX)]
    assert len(summaries) == 1, "Expected one emitted machine-readable qualification summary"
    qualification = summaries[0]
    assert qualification == notebook.metadata["mrms_absolute_time_qualification"]
    assert qualification["mode"] == "inspect_retained"
    assert qualification["clock"] == "UTC-equivalent naive HEC-RAS model labels"
    assert re.fullmatch(r"[0-9a-f]{9,40}", qualification["source_base"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", qualification["execution_date"])

    rows = qualification["runs"]
    assert len(rows) == 4
    assert {(row["project"], row["condition"]) for row in rows} == {
        (project, condition) for project in ("Davis", "NewOrleansMetro") for condition in ("baseline", "event")
    }
    for row in rows:
        assert row["hydraulic_acceptance"] == "not_established"
        for field in ("iteration_diagnostic_lines", "volume_accounting_lines"):
            assert isinstance(row[field], list) and all(isinstance(line, str) for line in row[field])
        for field in ("native_hdf_sha256", "native_executable_sha256"):
            assert re.fullmatch(r"[0-9a-f]{64}", row[field]), (row["project"], field)
        assert math.isfinite(row["native_runtime_seconds"]) and row["native_runtime_seconds"] > 0
        for field in ("timestamps", "physical_cells_checked", "boundary_cells_zero"):
            assert isinstance(row[field], int) and row[field] > 0, (row["project"], field)
        for field in ("expected_total_in", "hdf_final_total_in", "max_all_time_cell_error_in", "native_tolerance_in"):
            assert math.isfinite(row[field]) and row[field] >= 0, (row["project"], field)
        assert row["native_tolerance_in"] > 0
        assert row["max_all_time_cell_error_in"] <= row["native_tolerance_in"]
        assert abs(row["hdf_final_total_in"] - row["expected_total_in"]) <= row["native_tolerance_in"]
        assert row["absolute_time_qualified"] is True
        if row["condition"] == "baseline":
            assert row["expected_total_in"] == row["hdf_final_total_in"] == row["max_all_time_cell_error_in"] == 0
        else:
            assert row["expected_total_in"] > 0

    for project in ("Davis", "NewOrleansMetro"):
        baseline, event = sorted((row for row in rows if row["project"] == project), key=lambda row: row["condition"])
        for field in ("timestamps", "physical_cells_checked", "boundary_cells_zero"):
            assert baseline[field] == event[field], (project, field)
        if project == "NewOrleansMetro":
            # Native endpoint topology includes cell 16058 even though the
            # detailed-perimeter polygon reader cannot reconstruct its ring.
            assert baseline["physical_cells_checked"] == 19711
            assert baseline["boundary_cells_zero"] == 775
            # This native diagnostic row has no ERROR token. Qualification of
            # precipitation timing must not suppress its numerical context.
            pipe_row = "10APR2024 14:32:28 Base\tNode\t       426\t   0.450\tMine Blvd - Node 1"
            assert pipe_row in event["iteration_diagnostic_lines"]
            assert pipe_row not in baseline["iteration_diagnostic_lines"]
        assert baseline["native_executable_sha256"] == event["native_executable_sha256"]
        assert baseline["native_hdf_sha256"] != event["native_hdf_sha256"]
