"""Regression tests for the user-facing ``init_ras_project`` intro."""

from importlib import import_module
import logging
from pathlib import Path
from types import SimpleNamespace

import ras_commander
from ras_commander import RasPrj, init_ras_project
from ras_commander.RasTcu import RasTcu


rasprj_module = import_module("ras_commander.RasPrj")


def _stub_initialization(monkeypatch):
    def fake_initialize(
        self,
        project_folder,
        ras_exe_path,
        prj_file=None,
        load_results_summary=True,
    ):
        self.project_folder = Path(project_folder)
        self.project_name = "Citation Test Project"
        self.prj_file = prj_file
        self.ras_exe_path = ras_exe_path

    monkeypatch.setattr(RasPrj, "initialize", fake_initialize)
    monkeypatch.setattr(
        rasprj_module,
        "get_ras_exe",
        lambda _version: "C:/Program Files/HEC/HEC-RAS/7.0/Ras.exe",
    )
    monkeypatch.setattr(
        RasTcu,
        "status",
        staticmethod(lambda **_kwargs: SimpleNamespace(accepted=True, version="7.0")),
    )


def test_default_intro_encourages_citation(monkeypatch, tmp_path, caplog):
    _stub_initialization(monkeypatch)

    with caplog.at_level(logging.INFO, logger=rasprj_module.logger.name):
        init_ras_project(
            tmp_path,
            "7.0",
            ras_object=RasPrj(),
            load_results_summary=False,
        )

    text = caplog.text
    assert "SUPPORT OPEN-SOURCE DEVELOPMENT" in text
    assert "Please consider citing the library" in text
    assert f"RAS Commander v{ras_commander.__version__}" in text
    assert "RAS Commander and its contributors" in text
    assert "https://rascommander.info/ras/cite/" in text


def test_hide_intro_suppresses_citation_reminder(monkeypatch, tmp_path, caplog):
    _stub_initialization(monkeypatch)

    with caplog.at_level(logging.INFO, logger=rasprj_module.logger.name):
        init_ras_project(
            tmp_path,
            "7.0",
            ras_object=RasPrj(),
            load_results_summary=False,
            hide_intro=True,
        )

    assert "SUPPORT OPEN-SOURCE DEVELOPMENT" not in caplog.text
    assert "https://rascommander.info/ras/cite/" not in caplog.text
