import logging
from pathlib import Path

import pytest

from ras_commander.hdf.HdfFluvialPluvial import HdfFluvialPluvial


LOGGER_NAME = "ras_commander.hdf.HdfFluvialPluvial"


@pytest.fixture(scope="module")
def bald_eagle_2d_plan_hdf() -> Path:
    candidates = [
        Path("examples/example_projects/BaldEagleCrkMulti2D_11/BaldEagleDamBrk.p06.hdf"),
        Path("examples/example_projects/BaldEagleCrkMulti2D_14/BaldEagleDamBrk.p06.hdf"),
        Path("examples/example_projects/BaldEagleCrkMulti2D_415/BaldEagleDamBrk.p06.hdf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    pytest.skip("Bald Eagle 2D plan HDF example is not available")


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == LOGGER_NAME]


def test_fluvial_pluvial_default_info_logs_are_concise(
    bald_eagle_2d_plan_hdf: Path,
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        boundary_gdf = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
            bald_eagle_2d_plan_hdf,
            delta_t=72,
        )
        polygon_gdf = HdfFluvialPluvial.generate_fluvial_pluvial_polygons(
            bald_eagle_2d_plan_hdf,
            delta_t=12,
            temporal_tolerance_hours=1.0,
            min_polygon_area_acres=200,
        )

    assert not boundary_gdf.empty
    assert not polygon_gdf.empty

    messages = _messages(caplog)
    assert len(messages) == 2
    assert messages[0].startswith("Fluvial/pluvial boundary: ")
    assert "line(s), delta_t=72 hr." in messages[0]
    assert messages[1].startswith("Fluvial/pluvial polygons: ")
    assert "dissolved class(es)" in messages[1]
    assert "iterations=" in messages[1]
    assert "components=" in messages[1]

    noisy_fragments = [
        "Getting cell polygons",
        "Loading mesh and results data",
        "Processing cell adjacencies",
        "Final validated file path",
        "Using HDF file",
        str(bald_eagle_2d_plan_hdf),
    ]
    for message in messages:
        assert not any(fragment in message for fragment in noisy_fragments)


def test_fluvial_pluvial_debug_logs_include_call_and_processing_context(
    bald_eagle_2d_plan_hdf: Path,
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        boundary_gdf = HdfFluvialPluvial.calculate_fluvial_pluvial_boundary(
            bald_eagle_2d_plan_hdf,
            delta_t=72,
            min_line_length=3000,
        )

    assert boundary_gdf.empty

    messages = _messages(caplog)
    assert "Calling calculate_fluvial_pluvial_boundary" in messages
    assert "Finished calculate_fluvial_pluvial_boundary" in messages
    assert "Getting cell polygons from HDF file..." in messages
    assert "Identifying boundary edges..." in messages
    assert any("boundary line(s) shorter than 3000 units were dropped" in message for message in messages)
    assert any("Final validated file path" in message for message in messages)
