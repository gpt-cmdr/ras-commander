import logging
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from ras_commander.dss.RasDss import RasDss


LOGGER_NAME = "ras_commander.dss.RasDss"


@pytest.fixture(autouse=True)
def reset_ras_dss_state():
    old_monolith = RasDss._monolith
    old_jvm_configured = RasDss._jvm_configured
    RasDss._monolith = None
    RasDss._jvm_configured = False
    yield
    RasDss._monolith = old_monolith
    RasDss._jvm_configured = old_jvm_configured


def test_ensure_monolith_uses_concise_log_instead_of_stdout(
    monkeypatch, caplog, capsys
):
    from ras_commander.dss import _hec_monolith

    instances = []

    class FakeDownloader:
        def __init__(self):
            self.install_called = False
            instances.append(self)

        def is_installed(self):
            return False

        def install(self):
            self.install_called = True

    monkeypatch.setattr(_hec_monolith, "HecMonolithDownloader", FakeDownloader)
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    monolith = RasDss._ensure_monolith()

    assert monolith is instances[0]
    assert instances[0].install_called
    assert capsys.readouterr().out == ""
    assert any(
        "Installing HEC Monolith libraries for DSS operations" in record.getMessage()
        for record in caplog.records
    )


def test_configure_jvm_success_is_debug_only(monkeypatch, caplog, capsys, tmp_path):
    add_classpath_calls = []

    def add_classpath(*classpath):
        add_classpath_calls.append(classpath)

    fake_jnius_config = types.SimpleNamespace(
        vm_running=False,
        add_classpath=add_classpath,
    )
    monkeypatch.setitem(sys.modules, "jnius_config", fake_jnius_config)

    class FakeMonolith:
        def get_classpath(self):
            return ["hec-monolith.jar", "hecnf.jar"]

        def get_library_path(self):
            return str(tmp_path / "lib")

    monkeypatch.setattr(
        RasDss,
        "_ensure_monolith",
        staticmethod(lambda: FakeMonolith()),
    )
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "java"))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    RasDss._configure_jvm()

    assert capsys.readouterr().out == ""
    assert RasDss._jvm_configured is True
    assert add_classpath_calls == [("hec-monolith.jar", "hecnf.jar")]
    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == logging.DEBUG
    ]
    assert info_messages == []
    assert "Configuring Java VM for DSS operations" in debug_messages
    assert "Java VM configured for DSS operations" in debug_messages


def test_extract_boundary_timeseries_has_one_concise_info_summary(
    monkeypatch, caplog, tmp_path
):
    dss_file = tmp_path / "boundary.dss"
    dss_file.write_bytes(b"DSS")

    boundaries = pd.DataFrame(
        [
            {
                "Use DSS": "True",
                "DSS File": dss_file.name,
                "DSS Path": "/BASIN/LOC/FLOW//1HOUR/RUN/",
            },
            {
                "Use DSS": "False",
                "DSS File": "",
                "DSS Path": "",
            },
        ]
    )
    ts = pd.DataFrame(
        {"value": [1.0, 2.0]},
        index=pd.date_range("2020-01-01", periods=2, freq="h"),
    )
    monkeypatch.setattr(
        RasDss,
        "read_timeseries",
        staticmethod(lambda *_args, **_kwargs: ts),
    )
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    result = RasDss.extract_boundary_timeseries(boundaries, project_dir=tmp_path)

    assert result.loc[0, "dss_timeseries"] is ts
    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == logging.DEBUG
    ]
    assert info_messages == [
        "DSS boundary extraction complete: 1 found, 1 read, 0 failed"
    ]
    assert "Found 1 DSS-defined boundaries" in debug_messages
    assert any(
        "Row 0: Extracted 2 points from boundary.dss" in message
        for message in debug_messages
    )


def test_write_timeseries_info_is_concise_and_debug_keeps_details(
    monkeypatch, caplog, tmp_path
):
    from ras_commander.RasUtils import RasUtils

    output_dss = tmp_path / "output.dss"
    pathname = "/BASIN/LOC/FLOW//1HOUR/FORECAST/"
    written_containers = []

    class FakeTimeSeriesContainer:
        pass

    class FakeDssFile:
        def put(self, container):
            written_containers.append(container)

        def done(self):
            pass

    class FakeHecDss:
        @staticmethod
        def open(_path):
            return FakeDssFile()

    def autoclass(name):
        if name == "hec.heclib.dss.HecDss":
            return FakeHecDss
        if name == "hec.io.TimeSeriesContainer":
            return FakeTimeSeriesContainer
        raise AssertionError(f"Unexpected Java class requested: {name}")

    monkeypatch.setattr(RasDss, "_configure_jvm", staticmethod(lambda: None))
    monkeypatch.setitem(
        sys.modules,
        "jnius",
        types.SimpleNamespace(autoclass=autoclass),
    )
    monkeypatch.setattr(RasUtils, "safe_resolve", staticmethod(lambda path: Path(path)))
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    RasDss.write_timeseries(
        output_dss,
        pathname,
        pd.date_range("2020-01-01", periods=2, freq="h"),
        [10.0, 11.0],
        units="CFS",
        data_type="INST-VAL",
    )

    assert len(written_containers) == 1
    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == logging.DEBUG
    ]
    assert info_messages == [
        "DSS file will be created: output.dss",
        "Wrote 2 values to output.dss",
    ]
    assert all(str(output_dss) not in message for message in info_messages)
    assert all(pathname not in message for message in info_messages)
    assert any(str(output_dss) in message for message in debug_messages)
    assert any(pathname in message for message in debug_messages)
    assert any("units=CFS" in message for message in debug_messages)
