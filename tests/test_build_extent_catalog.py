from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "example_library" / "build_extent_catalog.py"
SPEC = importlib.util.spec_from_file_location("build_extent_catalog", SCRIPT_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_write_javascript_catalog_assigns_the_feature_collection(tmp_path: Path) -> None:
    output = tmp_path / "ras-example-projects-data.js"
    catalog = {"type": "FeatureCollection", "features": [{"id": "model-1"}]}

    builder._write_javascript_catalog(output, catalog)

    prefix = "window.RAS_EXAMPLE_PROJECTS = "
    contents = output.read_text(encoding="utf-8")
    assert contents.startswith(prefix)
    assert contents.endswith(";\n")
    assert json.loads(contents.removeprefix(prefix).removesuffix(";\n")) == catalog
