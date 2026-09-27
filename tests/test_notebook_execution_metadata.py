"""Execution metadata counts silent cells without treating outputs as proof."""

import importlib.util
from pathlib import Path

import nbformat
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / ".claude/scripts/generate_notebooks_metadata.py"
SPEC = importlib.util.spec_from_file_location("notebook_execution_metadata", SCRIPT)
metadata_generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metadata_generator)


def test_silent_definition_cell_counts_as_executed():
    cell = nbformat.v4.new_code_cell("def identity(value):\n    return value", execution_count=4)
    notebook = nbformat.v4.new_notebook(cells=[cell])
    assert cell.outputs == []
    assert metadata_generator.count_cells(notebook) == (1, 1)


@pytest.mark.parametrize("missing_count", [False, True])
def test_retained_output_without_execution_count_is_not_execution(missing_count):
    cell = nbformat.v4.new_code_cell(
        "print('retained output')",
        outputs=[nbformat.v4.new_output("stream", name="stdout", text="retained output\n")],
    )
    notebook = nbformat.v4.new_notebook(cells=[cell])
    if missing_count:
        del notebook.cells[0]["execution_count"]
    assert metadata_generator.count_cells(notebook) == (1, 0)


def test_execution_count_is_presence_not_order_or_success():
    notebook = nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_code_cell("value = 1", execution_count=0),
        nbformat.v4.new_code_cell(
            "raise ValueError('review required')", execution_count=7,
            outputs=[nbformat.v4.new_output(
                "error", ename="ValueError", evalue="review required", traceback=[],
            )],
        ),
    ])
    assert metadata_generator.count_cells(notebook) == (2, 2)


def test_unexecuted_code_and_noncode_cells_are_counted_separately():
    notebook = nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_markdown_cell("# Example"),
        nbformat.v4.new_raw_cell("Retained explanatory material"),
        nbformat.v4.new_code_cell("value = 1"),
        nbformat.v4.new_code_cell("other = 2", execution_count=3),
    ])
    assert metadata_generator.count_cells(notebook) == (2, 1)
