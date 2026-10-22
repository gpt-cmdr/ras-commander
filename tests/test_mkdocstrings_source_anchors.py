"""Build real mkdocstrings HTML to protect grouped member and source anchors."""
import importlib.util
from pathlib import Path
import re

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
    module.write_text('''from typing import overload

class Example:
    """A class rendered in one or more sections."""
    label: str = "example"

    def __init__(self, value: int = 1):
        self.value = value

    @staticmethod
    def first():
        """First member.

        Examples:
            >>> Example.first()
            1
        """
        return 1

    @staticmethod
    def second():
        """Second member.

        Examples:
            >>> Example.second()
            2
        """
        return 2

@overload
def overloaded(value: int) -> int: ...
@overload
def overloaded(value: str) -> str: ...
def overloaded(value):
    """Return the input."""
    return value
''', encoding="utf-8")
    docs = tmp_path / "docs"
    (docs / "api").mkdir(parents=True)
    (docs / "reference").mkdir()
    (docs / "reference/dataframe-reference.md").write_text("# DataFrames\n", encoding="utf-8")
    if grouped:
        markdown = '# Grouped API\n\n<a id="anchor_example.Example"></a>\n\n' + "\n\n".join(
            f"## {member}\n\n::: anchor_example.Example\n    options:\n      show_root_heading: false\n      show_root_toc_entry: false\n      members:\n        - {member}\n"
            for member in ["first", "second"]
        )
    else:
        markdown = "# Complete class\n\n::: anchor_example.Example\n    options:\n      members:\n        - first\n        - second\n        - label\n"
    markdown += "\n\n::: anchor_example.overloaded\n"
    (docs / "api/index.md").write_text(markdown, encoding="utf-8")
    configuration = {
        "site_name": "Source anchor regression",
        "docs_dir": str(docs), "site_dir": str(tmp_path / "site"),
        "theme": {"name": "material"},
        "plugins": [{"mkdocstrings": {
            "custom_templates": str(ROOT / "docs/overrides/mkdocstrings"),
            "handlers": {"python": {"paths": [str(tmp_path)], "options": {"show_source": True, "show_root_heading": True, "separate_signature": True, "merge_init_into_class": True, "show_overloads": True}}},
        }}],
        "markdown_extensions": [{"pymdownx.highlight": {"anchor_linenums": True, "line_spans": "__span"}}, "pymdownx.superfences"],
    }
    config_path = tmp_path / "mkdocs.yml"
    config_path.write_text(yaml.safe_dump(configuration), encoding="utf-8")
    build(load_config(config_file=str(config_path), strict=True))
    assert validator.validate(docs, tmp_path / "site") == []
    inventory = validator.AnchorInventory()
    html = (tmp_path / "site/api/index.html").read_text(encoding="utf-8")
    inventory.feed(html)
    assert all(count == 1 for count in inventory.ids.values())
    assert any("--signature--" in anchor for anchor in inventory.ids)
    assert any("--overload-1--" in anchor for anchor in inventory.ids)
    assert any("--overload-2--" in anchor for anchor in inventory.ids)
    assert any("--example-" in anchor for anchor in inventory.ids)
    assert "doc-signature" in html and "mkdocstrings-source" in html
    for target in re.findall(r'href="#([^"]+)"', html):
        if any(part in target for part in ["--source--", "--signature--", "--overload-", "--example-"]):
            assert target in inventory.ids
    for member in ["first", "second"]:
        prefix = f"anchor_example.Example.{member}--source--"
        assert any(anchor.startswith(prefix) for anchor in inventory.ids)
    assert any(anchor.startswith("anchor_example.Example--source--") for anchor in inventory.ids) is not grouped


@pytest.mark.parametrize("anchor", ["__span-0-1", "__codelineno-0-1", "example--signature--__span-0-1"])
def test_validator_rejects_duplicate_generated_line_ids(tmp_path, anchor):
    docs, site = tmp_path / "docs", tmp_path / "site"
    (docs / "api").mkdir(parents=True)
    (docs / "reference").mkdir()
    (site / "api").mkdir(parents=True)
    (site / "reference/dataframe-reference").mkdir(parents=True)
    (docs / "api/index.md").write_text('<a id="member"></a>', encoding="utf-8")
    (docs / "reference/dataframe-reference.md").write_text("# DataFrames", encoding="utf-8")
    (site / "reference/dataframe-reference/index.html").write_text("<h1>DataFrames</h1>", encoding="utf-8")
    page = site / "api/index.html"
    page.write_text(f'<a id="member"></a><span id="{anchor}"></span><a id="{anchor}"></a>', encoding="utf-8")
    assert validator.validate(docs, site) == [f"index.md: duplicate HTML ID {anchor}"]
    page.write_text(f'<a id="member"></a><span id="{anchor}"></span>', encoding="utf-8")
    assert validator.validate(docs, site) == []
