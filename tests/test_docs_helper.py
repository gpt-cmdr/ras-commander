"""Tests for the docs()/agent_guide_path() discovery helpers and module constants.

These exercise the LLM-agent discovery hooks added in 0.98.2: the docs() URL
resolver, the __llms_txt__ constant, and the packaged LLM_GUIDE.md guide.
"""

import os

import ras_commander


def test_llms_txt_constant():
    assert ras_commander.__llms_txt__ == "https://rascommander.info/llms.txt"


def test_docs_base_url():
    assert ras_commander.docs() == "https://rascommander.info"


def test_docs_llms_topic():
    assert ras_commander.docs("llms") == "https://rascommander.info/llms.txt"


def test_docs_dataframes_topic():
    assert ras_commander.docs("dataframes") == (
        "https://rascommander.info/reference/dataframe-reference/"
    )


def test_docs_user_guide_topic():
    assert ras_commander.docs("plan-execution") == (
        "https://rascommander.info/user-guide/plan-execution/"
    )


def test_agent_guide_path_exists():
    guide = ras_commander.agent_guide_path()
    # importlib.resources Traversable -> resolvable filesystem path with content
    text = guide.read_text(encoding="utf-8")
    assert "ras-commander" in text
    assert "rascommander.info/llms.txt" in text
    # The on-disk file should exist (package data shipped in the wheel)
    assert os.path.exists(str(guide))


def test_docs_and_guide_exported():
    assert "docs" in ras_commander.__all__
    assert "agent_guide_path" in ras_commander.__all__
