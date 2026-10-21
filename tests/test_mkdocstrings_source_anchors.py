"""Build real mkdocstrings HTML to protect grouped member and source anchors."""
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("mkdocs")
pytest.importorskip("mkdocstrings_handlers.python")
from mkdocs.config import load_config
from mkdocs.commands.build import build
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("render_validator", ROOT / ".claude/scripts/validate_rasmapper_api_rendering.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


@pytest.mark.parametrize("grouped", [True, False])
def test_class_source_anchors_are_unique_and_method_sources_remain(tmp_path, grouped):
    module = tmp_path / "anchor_example.py"
    module.write_text('''class Example:
    """A class rendered in one or more sections."""
    @staticmethod
    def first():
        """First member."""
        return 1

    @staticmethod
    def second():
        """Second member."""
        return 2
''', encoding="utf-8")
    docs = tmp_path / "docs"
    (docs / "api").mkdir(parents=True)
    (docs / "reference").mkdir()
    (docs / "reference/dataframe-reference.md").write_text("# DataFrames\n", encoding="utf-8")
    if grouped:
        markdown = "# Grouped API\n\n" + "\n\n".join(
            f"## {member}\n\n::: anchor_example.Example\n    options:\n      show_root_heading: false\n      members:\n        - {member}\n"
            for member in ["first", "second"]
        )
    else:
        markdown = "# Complete class\n\n::: anchor_example.Example\n    options:\n      members:\n        - first\n        - second\n"
    (docs / "api/index.md").write_text(markdown, encoding="utf-8")
    configuration = {
        "site_name": "Source anchor regression",
        "docs_dir": str(docs), "site_dir": str(tmp_path / "site"),
        "theme": {"name": "material"},
        "plugins": [{"mkdocstrings": {
            "custom_templates": str(ROOT / "docs/overrides/mkdocstrings"),
            "handlers": {"python": {"paths": [str(tmp_path)], "options": {"show_source": True, "show_root_heading": True}}},
        }}],
        "markdown_extensions": [{"pymdownx.highlight": {"anchor_linenums": True, "line_spans": "__span"}}, "pymdownx.superfences"],
    }
    config_path = tmp_path / "mkdocs.yml"
    config_path.write_text(yaml.safe_dump(configuration), encoding="utf-8")
    build(load_config(config_file=str(config_path), strict=True))
    assert validator.validate(docs, tmp_path / "site") == []
    inventory = validator.AnchorInventory()
    inventory.feed((tmp_path / "site/api/index.html").read_text(encoding="utf-8"))
    assert all(count == 1 for anchor, count in inventory.ids.items() if "--source--" in anchor)
    for member in ["first", "second"]:
        prefix = f"anchor_example.Example.{member}--source--"
        assert any(anchor.startswith(prefix) for anchor in inventory.ids)
    assert any(anchor.startswith("anchor_example.Example--source--") for anchor in inventory.ids) is not grouped
