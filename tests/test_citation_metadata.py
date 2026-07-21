"""Contract checks for RAS Commander citation metadata and guidance."""

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_citation_cff_has_required_project_metadata():
    text = (REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")

    assert "cff-version: 1.2.0" in text
    assert "title: RAS Commander" in text
    assert "license: MIT" in text
    assert "repository-code: https://github.com/gpt-cmdr/ras-commander" in text
    assert "recognize RAS Commander and its contributors" in text


def test_citation_version_matches_package_version():
    citation = (REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    setup_text = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")

    citation_version = re.search(r"^version:\s*([^\s]+)$", citation, re.MULTILINE)
    package_version = re.search(r'^\s*version="([^"]+)"', setup_text, re.MULTILINE)

    assert citation_version is not None
    assert package_version is not None
    assert citation_version.group(1) == package_version.group(1)


def test_citation_page_keeps_recognition_voluntary_and_library_centered():
    text = (REPO_ROOT / "docs" / "cite.md").read_text(encoding="utf-8")

    assert "please consider citing the library" in text
    assert "RAS Commander and its contributors" in text
    assert "appreciated and voluntary" in text
    assert "never publish" in text
    assert "without explicit authorization" in text


def test_docs_footer_and_llms_config_expose_citation_guidance():
    footer = (REPO_ROOT / "docs" / "overrides" / "main.html").read_text(
        encoding="utf-8"
    )
    mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    assert 'data-software-citation="ras-commander"' in footer
    assert "https://rascommander.info/ras/cite/" in footer
    assert "Contribute upstream" in footer
    assert "markdown_description:" in mkdocs
    assert "Citation and Support:" in mkdocs
    assert "- cite.md" in mkdocs
