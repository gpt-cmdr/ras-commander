"""Example-project downloads use HEC's actual release tag and asset per version."""

import pytest

from ras_commander import RasExamples
import importlib

examples_module = importlib.import_module("ras_commander.RasExamples")


@pytest.mark.parametrize("version, suffix", [
    ("6.1", "1.0.21/Example_Projects.zip"),
    ("6.3.1", "1.0.25/HEC-RAS_63_Example_Projects.zip"),
    ("6.4.1", "1.0.28/HEC-RAS_64_Example_Projects.zip"),
    ("6.6", "1.0.33/Example_Projects_6_6.zip"),
    ("7.0", "1.0.45/Example_Projects_7_0.zip"),
])
def test_hosted_versions_download_their_own_asset(tmp_path, monkeypatch, version, suffix):
    requested = []

    class Stop(Exception):
        pass

    def get(url, stream=False):
        requested.append(url)
        raise Stop

    monkeypatch.setattr(RasExamples, "_user_data_dir", tmp_path)
    monkeypatch.setattr(examples_module, "_require_requests", lambda: None)
    monkeypatch.setattr(examples_module.requests, "get", get)
    with pytest.raises(Stop):
        RasExamples.get_example_projects(version)
    assert requested == [RasExamples.base_url + suffix]


@pytest.mark.parametrize("version", ["5.0.7", "4.1", "6.0"])
def test_installer_only_versions_explain_where_examples_are(version):
    with pytest.raises(ValueError, match="ship inside the installer"):
        RasExamples.get_example_projects(version)
