import logging
from pathlib import Path

import pytest

pytest.importorskip("geopandas")
pytest.importorskip("shapely")

from ras_commander.geom.GeomParser import GeomParser


LOGGER_NAME = "ras_commander.geom.GeomParser"


def _messages(caplog, level):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno == level
    ]


def _write_geom(tmp_path: Path) -> Path:
    geom_file = tmp_path / "parser_logging.g01"
    geom_file.write_text(
        "\n".join(
            [
                "Geom Title=Parser Logging Test",
                "Program Version=6.50",
                "River Reach=TestRiver    ,TestReach",
                "Reach XY= 2",
                "        0.0000000        0.0000000     1000.0000000        0.0000000",
                "Type RM Length L Ch R = 1 ,5000.000,     0.0,     0.0,     0.0",
                "XS GIS Cut Line= 2",
                "        0.0000000      100.0000000     1000.0000000      100.0000000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return geom_file


def test_backup_creation_is_debug_only(tmp_path, caplog):
    geom_file = _write_geom(tmp_path)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        backup_path = GeomParser.create_backup(geom_file)

    assert backup_path.exists()
    assert _messages(caplog, logging.INFO) == []

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        second_backup = GeomParser.create_backup(geom_file)

    debug_messages = _messages(caplog, logging.DEBUG)
    assert second_backup.exists()
    assert any("Created backup:" in msg and str(geom_file) in msg for msg in debug_messages)


def test_safe_write_success_is_debug_only(tmp_path, caplog):
    geom_file = _write_geom(tmp_path)
    modified_lines = geom_file.read_text(encoding="utf-8").splitlines(keepends=True)
    modified_lines.insert(1, "Geom File=parser_logging.g01\n")

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        backup_path = GeomParser.safe_write_geometry(geom_file, modified_lines)

    assert backup_path is not None
    assert backup_path.exists()
    assert "Geom File=parser_logging.g01" in geom_file.read_text(encoding="utf-8")

    info_messages = _messages(caplog, logging.INFO)
    assert info_messages == []

    debug_messages = _messages(caplog, logging.DEBUG)
    assert any("Created backup:" in msg and str(geom_file) in msg for msg in debug_messages)
    assert any("Successfully wrote geometry file:" in msg and str(geom_file) in msg for msg in debug_messages)


def test_geometry_read_helper_progress_is_debug_only(tmp_path, caplog):
    geom_file = _write_geom(tmp_path)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        xs_cut_lines = GeomParser.get_xs_cut_lines(geom_file)
        centerlines = GeomParser.get_river_centerlines(geom_file)

    assert len(xs_cut_lines) == 1
    assert len(centerlines) == 1
    assert _messages(caplog, logging.INFO) == []

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        GeomParser.get_xs_cut_lines(geom_file)
        GeomParser.get_river_centerlines(geom_file)

    debug_messages = _messages(caplog, logging.DEBUG)
    assert any("Extracting XS cut lines from:" in msg and str(geom_file) in msg for msg in debug_messages)
    assert any("Found 1 XS cut lines" in msg for msg in debug_messages)
    assert any("Extracting river centerlines from:" in msg and str(geom_file) in msg for msg in debug_messages)
    assert any("Found 1 river centerlines" in msg for msg in debug_messages)


def test_rollback_geometry_stays_info(tmp_path, caplog):
    geom_file = _write_geom(tmp_path)
    backup_path = GeomParser.create_backup(geom_file)
    geom_file.write_text("broken\n", encoding="utf-8")

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        GeomParser.rollback_geometry(geom_file, backup_path)

    info_messages = _messages(caplog, logging.INFO)
    assert info_messages == [f"Restored geometry file from backup: {geom_file}"]
    assert "Parser Logging Test" in geom_file.read_text(encoding="utf-8")
