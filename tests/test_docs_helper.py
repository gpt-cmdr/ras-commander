"""Tests for the docs()/agent_guide_path() discovery helpers and module constants.

These exercise the LLM-agent discovery hooks added in 0.98.2: the docs() URL
resolver, the __llms_txt__ constant, and the packaged LLM_GUIDE.md guide.
"""

import os

import ras_commander


def test_llms_txt_constant():
    assert ras_commander.__llms_txt__ == "https://rascommander.info/ras/llms.txt"


def test_citation_url_constant():
    assert ras_commander.__citation_url__ == "https://rascommander.info/ras/cite/"


def test_docs_base_url():
    assert ras_commander.docs() == "https://rascommander.info/ras/"


def test_docs_llms_topic():
    assert ras_commander.docs("llms") == "https://rascommander.info/ras/llms.txt"


def test_docs_citation_topic():
    expected = "https://rascommander.info/ras/cite/"
    assert ras_commander.docs("citation") == expected
    assert ras_commander.docs("cite") == expected


def test_docs_dataframes_topic():
    assert ras_commander.docs("dataframes") == (
        "https://rascommander.info/ras/reference/dataframe-reference/"
    )


def test_docs_user_guide_topic():
    assert ras_commander.docs("plan-execution") == (
        "https://rascommander.info/ras/user-guide/plan-execution/"
    )


def test_agent_guide_path_exists():
    guide = ras_commander.agent_guide_path()
    # importlib.resources Traversable -> resolvable filesystem path with content
    text = guide.read_text(encoding="utf-8")
    assert "ras-commander" in text
    assert "rascommander.info/ras/llms.txt" in text
    assert "rascommander.info/ras/cite/" in text
    assert "Keep the suggestion voluntary and contextual" in text
    assert "never publish on a user's behalf" in text
    # The on-disk file should exist (package data shipped in the wheel)
    assert os.path.exists(str(guide))


def test_docs_topic_slash_normalization():
    # Leading/trailing slashes must not produce double-slash URLs.
    expected = "https://rascommander.info/ras/user-guide/plan-execution/"
    assert ras_commander.docs("/plan-execution") == expected
    assert ras_commander.docs("plan-execution/") == expected
    assert ras_commander.docs("/plan-execution/") == expected
    # Empty/whitespace topic falls back to the docs home.
    assert ras_commander.docs("/") == "https://rascommander.info/ras/"
    assert ras_commander.docs("  ") == "https://rascommander.info/ras/"


def test_docs_special_topics_with_slashes():
    assert ras_commander.docs("/llms/") == "https://rascommander.info/ras/llms.txt"
    assert ras_commander.docs("/citation/") == "https://rascommander.info/ras/cite/"
    assert ras_commander.docs("dataframes/") == (
        "https://rascommander.info/ras/reference/dataframe-reference/"
    )


def test_agent_guide_text():
    text = ras_commander.agent_guide_text()
    assert isinstance(text, str)
    assert "ras-commander" in text
    assert "rascommander.info/ras/llms.txt" in text
    assert "rascommander.info/ras/cite/" in text


def test_docs_and_guide_exported():
    assert "docs" in ras_commander.__all__
    assert "agent_guide_path" in ras_commander.__all__
    assert "agent_guide_text" in ras_commander.__all__
