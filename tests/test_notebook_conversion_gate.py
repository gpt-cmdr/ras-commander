"""A broken notebook must not be hidden by a previous rendered file."""
import importlib.util
from pathlib import Path

import nbformat
import pytest


SCRIPT = Path(__file__).parents[1] / ".claude/scripts/prepare_notebooks_for_docs.py"
spec = importlib.util.spec_from_file_location("notebook_conversion", SCRIPT)
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)


def test_corrupt_notebook_rejects_stale_output(tmp_path):
    source, output = tmp_path / "examples", tmp_path / "rendered"
    source.mkdir()
    output.mkdir()
    (source / "100_example.ipynb").write_text("not valid JSON", encoding="utf-8")
    (output / "100_example.md").write_text("stale success", encoding="utf-8")
    with pytest.raises(RuntimeError, match="refusing to publish"):
        converter.convert_notebooks(source, output)


def test_conversion_preserves_recorded_output(tmp_path):
    source, output = tmp_path / "examples", tmp_path / "rendered"
    source.mkdir()
    output.mkdir()
    (output / "223_withdrawn.md").write_text("old example", encoding="utf-8")
    (output / "README.md").write_text("keep supporting page", encoding="utf-8")
    cell = nbformat.v4.new_code_cell("print('retained evidence')", execution_count=1)
    cell.outputs = [nbformat.v4.new_output("stream", name="stdout", text="retained evidence\n")]
    notebook = nbformat.v4.new_notebook(cells=[cell])
    nbformat.write(notebook, source / "100_example.ipynb")
    assert converter.convert_notebooks(source, output) == 1
    assert "retained evidence" in (output / "100_example.md").read_text(encoding="utf-8")

    assert not (output / "223_withdrawn.md").exists()
    assert (output / "README.md").read_text(encoding="utf-8") == "keep supporting page"


def test_markdown_links_change_but_recorded_output_and_source_do_not(tmp_path):
    import base64
    source, output = tmp_path / "examples", tmp_path / "rendered"
    source.mkdir()
    (source / "out").mkdir()
    asset = source / "out/figure.png"
    asset.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf9sAAAAASUVORK5CYII="))
    cell = nbformat.v4.new_code_cell("print('[reference](200_other.ipynb)')", execution_count=1)
    cell.outputs = [nbformat.v4.new_output('stream', name='stdout', text='[reference](200_other.ipynb)\n')]
    notebook = nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_markdown_cell('[Reference](200_other.ipynb#section)\n![Figure](out/figure.png)\n[External](https://example.org/200_other.ipynb)'),
        cell,
    ])
    path = source / '100_example.ipynb'
    nbformat.write(notebook, path)
    before = path.read_bytes()
    converter.convert_notebooks(source, output)
    rendered = (output / '100_example.md').read_text(encoding='utf-8')
    assert '[Reference](200_other.md#section)' in rendered
    assert '[reference](200_other.ipynb)' in rendered
    assert 'https://example.org/200_other.ipynb' in rendered
    assert (output / 'out/figure.png').read_bytes() == asset.read_bytes()
    assert path.read_bytes() == before
