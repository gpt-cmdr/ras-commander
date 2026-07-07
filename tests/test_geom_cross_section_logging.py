import logging
from pathlib import Path

from ras_commander.geom.GeomCrossSection import GeomCrossSection


LOGGER_NAME = "ras_commander.geom.GeomCrossSection"
RIVER = "TestRiver"
REACH = "TestReach"


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


def _fixed(values):
    return "".join(f"{value:8.2f}" for value in values)


def _xs_block(rs: str, invert: float) -> str:
    return "".join(
        [
            f"Type RM Length L Ch R = 1 ,{rs},     0.0,     0.0,     0.0\n",
            "Node Last Edited Time=Jan/01/2025 00:00:00\n",
            f"HTAB Starting El and Incr={invert:10.1f},{0.5:10.4f}\n",
            "HTAB Number of Points= 100\n",
            "#Sta/Elev= 3\n",
            _fixed([0.0, invert + 10.0, 500.0, invert, 1000.0, invert + 10.0]) + "\n",
            "#Mann= 2 , 0 , 0\n",
            _fixed([0.0, 0.04, 0.0, 1000.0, 0.04, 0.0]) + "\n",
        ]
    )


def _write_htab_geom(tmp_path: Path) -> Path:
    text = (
        "Geom Title=HTAB Logging Test\n"
        "Program Version=6.50\n"
        f"River Reach={RIVER}    ,{REACH}\n"
        "Reach XY= 2\n"
        "         0.00         0.00\n"
        "     10000.00         0.00\n"
        + _xs_block("1000", 90.0)
        + _xs_block("2000", 92.0)
    )
    geom_file = tmp_path / "logging.g01"
    geom_file.write_text(text, encoding="utf-8")
    return geom_file


def test_get_xs_htab_params_is_debug_only(tmp_path, caplog):
    geom_file = _write_htab_geom(tmp_path)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        params = GeomCrossSection.get_xs_htab_params(
            geom_file,
            RIVER,
            REACH,
            "1000",
        )

    assert params["has_htab_lines"] is True
    assert params["starting_el"] == 90.0
    assert _messages(caplog, logging.INFO) == []

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        GeomCrossSection.get_xs_htab_params(geom_file, RIVER, REACH, "1000")

    debug_messages = _messages(caplog, logging.DEBUG)
    assert any("Extracted HTAB params for TestRiver/TestReach/RS 1000" in msg for msg in debug_messages)
    assert any("starting_el=90.0" in msg for msg in debug_messages)


def test_set_xs_htab_params_keeps_backup_path_debug_and_summary_info(tmp_path, caplog):
    geom_file = _write_htab_geom(tmp_path)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        GeomCrossSection.set_xs_htab_params(
            geom_file,
            RIVER,
            REACH,
            "1000",
            starting_el=90.0,
            increment=0.25,
            num_points=120,
        )

    info_messages = _messages(caplog, logging.INFO)
    assert info_messages == [
        "Updated HTAB params for TestRiver/TestReach/RS 1000: "
        "starting_el=90.0, increment=0.25, num_points=120"
    ]
    assert not any("Created backup:" in msg for msg in info_messages)

    debug_messages = _messages(caplog, logging.DEBUG)
    assert any("Created backup:" in msg and str(geom_file) in msg for msg in debug_messages)


def test_set_all_xs_htab_params_batch_mechanics_are_debug(tmp_path, caplog):
    geom_file = _write_htab_geom(tmp_path)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        result = GeomCrossSection.set_all_xs_htab_params(
            geom_file,
            starting_el="invert",
            increment=0.1,
            num_points=500,
            create_backup=False,
        )

    assert result["modified"] == 2
    info_messages = _messages(caplog, logging.INFO)
    assert len(info_messages) == 1
    assert info_messages[0].startswith("set_all_xs_htab_params complete: 2 modified, 0 skipped, ")
    assert not any("Indexed" in msg for msg in info_messages)

    debug_messages = _messages(caplog, logging.DEBUG)
    assert any("Indexed 2 cross sections with location data" in msg for msg in debug_messages)


def test_htab_validation_warnings_stay_visible(tmp_path, caplog):
    geom_file = _write_htab_geom(tmp_path)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        GeomCrossSection.set_xs_htab_params(
            geom_file,
            RIVER,
            REACH,
            "1000",
            starting_el=90.6,
            increment=0.25,
            num_points=120,
        )

    warning_messages = _messages(caplog, logging.WARNING)
    assert any("HTAB validation warning:" in msg for msg in warning_messages)
    assert any("above invert + 0.5" in msg for msg in warning_messages)
