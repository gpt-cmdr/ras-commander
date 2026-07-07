"""Logging regressions for geometry land-cover and metadata helpers."""

import logging
from pathlib import Path

from ras_commander.geom.GeomLandCover import GeomLandCover
from ras_commander.geom.GeomMetadata import GeomMetadata


def test_landcover_parse_errors_are_aggregated_at_warning(tmp_path, caplog):
    geom_file = tmp_path / "landcover.g01"
    geom_file.write_text(
        "Geom Title=Landcover Logging Test\n"
        "LCMann Table=16\n"
        "Open Water,0.025\n"
        "Bad Base,not-a-number\n"
        "LCMann Time=Dec/30/1899 00:00:00\n"
        "LCMann Region Name=Main Channel\n"
        "LCMann Region Table=16\n"
        "Open Water,0.030\n"
        "Bad Region,not-a-number\n"
        "LCMann Region Polygon=0\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.DEBUG, logger="ras_commander.geom.GeomLandCover"):
        base_df = GeomLandCover.get_base_mannings_n(geom_file)
        region_df = GeomLandCover.get_region_mannings_n(geom_file)

    assert len(base_df) == 1
    assert len(region_df) == 1

    records = [
        record
        for record in caplog.records
        if record.name == "ras_commander.geom.GeomLandCover"
    ]
    warning_messages = [
        record.getMessage() for record in records if record.levelno == logging.WARNING
    ]
    debug_messages = [
        record.getMessage() for record in records if record.levelno == logging.DEBUG
    ]

    assert warning_messages == [
        "Skipped 1 malformed base Manning's n line(s) in landcover.g01",
        "Skipped 1 malformed regional Manning's n line(s) in landcover.g01",
    ]
    assert any("Bad Base,not-a-number" in message for message in debug_messages)
    assert any("Bad Region,not-a-number" in message for message in debug_messages)


def test_metadata_hdf_warning_uses_filename_and_debug_keeps_path(tmp_path, caplog):
    hdf_path = tmp_path / "invalid.g01.hdf"
    hdf_path.write_text("not an hdf file", encoding="utf-8")
    counts = GeomMetadata.DEFAULT_COUNTS.copy()

    with caplog.at_level(logging.DEBUG, logger="ras_commander.geom.GeomMetadata"):
        result = GeomMetadata._get_counts_from_hdf(hdf_path, counts)

    assert result is counts
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING
        and record.name == "ras_commander.geom.GeomMetadata"
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
        and record.name == "ras_commander.geom.GeomMetadata"
    ]

    assert warning_messages == [
        "HDF geometry metadata extraction failed for invalid.g01.hdf"
    ]
    assert str(tmp_path) not in warning_messages[0]
    assert any(str(hdf_path) in message for message in debug_messages)
