"""Logging regressions for RasCheck helper modules."""

import logging

from ras_commander.check import _utils
from ras_commander.check.check_floodways import CheckFloodways
from ras_commander.check.check_nt import CheckNt
from ras_commander.check.check_profiles import CheckProfiles
from ras_commander.check.check_structures import CheckStructures
from ras_commander.check.check_unsteady import CheckUnsteady
from ras_commander.check.check_xs import CheckXs
from ras_commander.check.types import FlowType


def _messages(caplog, logger_name, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == logger_name and record.levelno == level
    ]


def test_detect_flow_type_fallback_warning_is_concise(tmp_path, caplog):
    plan_hdf = tmp_path / "invalid.p01.hdf"
    plan_hdf.write_text("not an hdf file", encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger="ras_commander.check._utils"):
        flow_type = _utils.detect_flow_type(plan_hdf)

    assert flow_type is FlowType.GEOMETRY_ONLY
    warnings = _messages(caplog, "ras_commander.check._utils", logging.WARNING)
    debug = _messages(caplog, "ras_commander.check._utils", logging.DEBUG)

    assert warnings == ["Could not detect flow type; assuming geometry-only checks"]
    assert str(tmp_path) not in warnings[0]
    assert any(str(plan_hdf) in message for message in debug)


def test_check_nt_missing_subgrid_geometry_warning_uses_filename(tmp_path, caplog):
    geom_file = tmp_path / "missing.g01"

    with caplog.at_level(logging.DEBUG, logger="ras_commander.check.check_nt"):
        results = CheckNt.check_subgrid_sampling(geom_file)

    assert results.messages == []
    warnings = _messages(caplog, "ras_commander.check.check_nt", logging.WARNING)
    debug = _messages(caplog, "ras_commander.check.check_nt", logging.DEBUG)

    assert warnings == ["Geometry file not found for subgrid check: missing.g01"]
    assert str(tmp_path) not in warnings[0]
    assert any(str(geom_file) in message for message in debug)


def test_check_structures_read_failure_keeps_exception_debug(
    tmp_path, monkeypatch, caplog
):
    from ras_commander.hdf.HdfStruc import HdfStruc

    monkeypatch.setattr(
        HdfStruc,
        "get_structures",
        staticmethod(lambda geom_hdf: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.check.check_structures"):
        results = CheckStructures.check_structures(
            tmp_path / "plan.p01.hdf",
            tmp_path / "geom.g01.hdf",
            profiles=[],
        )

    assert results.messages == []
    warnings = _messages(
        caplog,
        "ras_commander.check.check_structures",
        logging.WARNING,
    )
    debug = _messages(caplog, "ras_commander.check.check_structures", logging.DEBUG)

    assert warnings == ["Could not read structures; structure checks will be skipped"]
    assert "boom" not in warnings[0]
    assert any("boom" in message for message in debug)


def test_check_unsteady_computation_failure_keeps_exception_debug(
    tmp_path, monkeypatch, caplog
):
    from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan

    monkeypatch.setattr(
        HdfResultsPlan,
        "get_compute_messages",
        staticmethod(lambda plan_hdf: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.check.check_unsteady"):
        results = CheckUnsteady.check_computation(tmp_path / "plan.p01.hdf")

    assert results.messages == []
    warnings = _messages(
        caplog,
        "ras_commander.check.check_unsteady",
        logging.WARNING,
    )
    debug = _messages(caplog, "ras_commander.check.check_unsteady", logging.DEBUG)

    assert warnings == ["Could not check computation messages"]
    assert "boom" not in warnings[0]
    assert any("boom" in message for message in debug)


def test_check_xs_geometry_failure_keeps_exception_debug(
    tmp_path, monkeypatch, caplog
):
    from ras_commander.hdf.HdfXsec import HdfXsec

    monkeypatch.setattr(
        HdfXsec,
        "get_cross_sections",
        staticmethod(lambda geom_hdf: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.check.check_xs"):
        results = CheckXs.check_xs(
            tmp_path / "plan.p01.hdf",
            tmp_path / "geom.g01.hdf",
            profiles=[],
        )

    assert len(results.messages) == 1
    errors = _messages(caplog, "ras_commander.check.check_xs", logging.ERROR)
    debug = _messages(caplog, "ras_commander.check.check_xs", logging.DEBUG)

    assert errors == ["Failed to read geometry HDF for cross-section checks"]
    assert "boom" not in errors[0]
    assert any("boom" in message for message in debug)


def test_check_floodways_steady_failure_keeps_exception_debug(
    tmp_path, monkeypatch, caplog
):
    from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan

    monkeypatch.setattr(
        HdfResultsPlan,
        "get_steady_results",
        staticmethod(lambda plan_hdf: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.check.check_floodways"):
        results = CheckFloodways.check_floodways(
            tmp_path / "plan.p01.hdf",
            tmp_path / "geom.g01.hdf",
            base_profile="Base",
            floodway_profile="Floodway",
        )

    assert results.messages == []
    warnings = _messages(
        caplog,
        "ras_commander.check.check_floodways",
        logging.WARNING,
    )
    debug = _messages(caplog, "ras_commander.check.check_floodways", logging.DEBUG)

    assert warnings == ["Could not read steady results for floodway checks"]
    assert "boom" not in warnings[0]
    assert any("boom" in message for message in debug)


def test_check_profiles_steady_failure_keeps_exception_debug(
    tmp_path, monkeypatch, caplog
):
    from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan

    monkeypatch.setattr(
        HdfResultsPlan,
        "get_steady_results",
        staticmethod(lambda plan_hdf: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.check.check_profiles"):
        results = CheckProfiles.check_profiles(
            tmp_path / "plan.p01.hdf",
            profiles=["Base", "Floodway"],
        )

    assert len(results.messages) == 1
    errors = _messages(caplog, "ras_commander.check.check_profiles", logging.ERROR)
    debug = _messages(caplog, "ras_commander.check.check_profiles", logging.DEBUG)

    assert errors == ["Failed to read steady results for profile checks"]
    assert "boom" not in errors[0]
    assert any("boom" in message for message in debug)
