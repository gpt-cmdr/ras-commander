import logging
from pathlib import Path

import pytest

from ras_commander.RasBreach import RasBreach


BREACH_LOGGER = "ras_commander.RasBreach"


def _breach_records(caplog):
    return [record for record in caplog.records if record.name == BREACH_LOGGER]


def _write_plan_with_breach(tmp_path: Path) -> Path:
    plan_path = tmp_path / "BreachProject.p01"
    plan_lines = [
        "Plan Title=Breach Logging Test",
        "Breach Loc=           River,           Reach,  1000.0,True,Dam             ",
        "Breach Method= 0",
        "Breach Geom= 5700,200,595,0.5,0.5,True,2.6,630,1,2.6",
        "Breach Start= 0,",
        "Breach Progression= 0",
        "Breach Calculator Data= 0,0,0,0,0,0,0",
        "",
        "Simulation Date=01JAN2000,0000,02JAN2000,0000",
    ]
    plan_path.write_text("\r\n".join(plan_lines) + "\r\n", encoding="utf-8", newline="")
    return plan_path


def test_list_breach_structures_is_quiet_at_info_and_detailed_at_debug(tmp_path, caplog):
    plan_path = _write_plan_with_breach(tmp_path)
    caplog.set_level(logging.INFO, logger=BREACH_LOGGER)

    structures = RasBreach.list_breach_structures_plan(plan_path)

    assert [item["structure"] for item in structures] == ["Dam"]
    assert _breach_records(caplog) == []

    caplog.clear()
    caplog.set_level(logging.DEBUG, logger=BREACH_LOGGER)

    structures = RasBreach.list_breach_structures_plan(plan_path)

    assert len(structures) == 1
    messages = [record.getMessage() for record in _breach_records(caplog)]
    assert any("Found 1 breach structures in BreachProject.p01" in message for message in messages)


def test_set_breach_geom_logs_concise_info_and_debug_details(tmp_path, caplog):
    plan_path = _write_plan_with_breach(tmp_path)
    caplog.set_level(logging.DEBUG, logger=BREACH_LOGGER)

    updated = RasBreach.set_breach_geom(
        plan_path,
        "Dam",
        initial_width=300,
        formation_time=1.5,
    )

    assert updated["values"]["Breach Geom"] == "5700,300,595,0.5,0.5,True,2.6,630,1,1.5"
    records = _breach_records(caplog)
    info_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    ]

    assert info_messages == ["Updating breach geometry for 'Dam' (2 field changes)"]
    assert any("initial_width: 200 -> 300" in message for message in debug_messages)
    assert any("formation_time: 2.6 -> 1.5" in message for message in debug_messages)
    assert any("Created backup: BreachProject_backup_" in message for message in debug_messages)
    assert all("Created backup" not in message for message in info_messages)


def test_update_breach_block_backup_is_debug_only(tmp_path, caplog):
    plan_path = _write_plan_with_breach(tmp_path)
    caplog.set_level(logging.DEBUG, logger=BREACH_LOGGER)

    updated = RasBreach.update_breach_block(
        plan_path,
        "Dam",
        method=9,
    )

    assert updated["values"]["Breach Method"] == " 9"
    records = _breach_records(caplog)
    info_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    ]

    assert info_messages == []
    assert any("Created backup: BreachProject_backup_" in message for message in debug_messages)
    assert any("Updated breach block for Dam in BreachProject.p01" in message for message in debug_messages)


def test_create_breach_block_backup_is_debug_only(tmp_path, caplog):
    plan_path = tmp_path / "CreateBreach.p01"
    plan_path.write_text(
        "Plan Title=Create Breach Test\r\nSimulation Date=01JAN2000,0000,02JAN2000,0000\r\n",
        encoding="utf-8",
        newline="",
    )
    caplog.set_level(logging.DEBUG, logger=BREACH_LOGGER)

    created = RasBreach.create_breach_block(
        plan_path,
        "NewDam",
        river="River",
        reach="Reach",
        station="1000.0",
    )

    assert created["structure_name"] == "NewDam"
    records = _breach_records(caplog)
    info_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.INFO
    ]
    debug_messages = [
        record.getMessage()
        for record in records
        if record.levelno == logging.DEBUG
    ]

    assert info_messages == []
    assert any("Created backup: CreateBreach_backup_" in message for message in debug_messages)
    assert any("Created breach block for NewDam in CreateBreach.p01" in message for message in debug_messages)


def test_failure_paths_raise_without_extra_error_log(tmp_path, caplog):
    plan_path = _write_plan_with_breach(tmp_path)
    caplog.set_level(logging.DEBUG, logger=BREACH_LOGGER)

    with pytest.raises(ValueError, match="Structure 'MissingDam' not found"):
        RasBreach.read_breach_block(plan_path, "MissingDam")

    records = _breach_records(caplog)
    assert all(record.levelno < logging.ERROR for record in records)
    assert any(
        record.levelno == logging.DEBUG
        and record.getMessage() == "Error reading breach block"
        and record.exc_info
        for record in records
    )
