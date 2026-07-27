"""Regression tests for HEC-RAS project text mutation safety."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from ras_commander import RasPlan, RasPrj
from ras_commander.RasUtils import RasUtils


def _has_crlf_only(path: Path) -> bool:
    content = path.read_bytes()
    return b"\r\n" in content and b"\n" not in content.replace(b"\r\n", b"")


def test_set_current_plan_preserves_crlf(tmp_path):
    project_file = tmp_path / "Example.prj"
    project_file.write_bytes(
        b"Proj Title=Example\r\nCurrent Plan=p01\r\nPlan File=p01\r\n"
        b"Plan File=p02\r\n"
    )
    project = RasPrj()
    project.prj_file = project_file
    project.plan_df = pd.DataFrame({"plan_number": ["01", "02"]})
    project.check_initialized = lambda: None

    project.set_current_plan("02")

    assert _has_crlf_only(project_file)
    assert b"Current Plan=p02\r\n" in project_file.read_bytes()


@pytest.mark.parametrize(
    ("source_time", "expected_time"),
    [
        (
            "01JAN2020,0000,02JAN2020,0000",
            "18SEP2019,1300,22SEP2019,1300",
        ),
        (
            "01JAN2020,00:00,02JAN2020,00:00",
            "18SEP2019,13:00,22SEP2019,13:00",
        ),
    ],
)
def test_update_simulation_date_preserves_crlf_and_time_style(
    tmp_path, source_time, expected_time
):
    plan_file = tmp_path / "Example.p01"
    plan_file.write_bytes(
        (
            "Plan Title=Example\r\n"
            f"Simulation Date={source_time}\r\n"
            "Geom File=g01\r\n"
        ).encode("utf-8")
    )

    RasPlan.update_simulation_date(
        plan_file,
        datetime(2019, 9, 18, 13),
        datetime(2019, 9, 22, 13),
    )

    assert _has_crlf_only(plan_file)
    assert (
        f"Simulation Date={expected_time}\r\n".encode("utf-8")
        in plan_file.read_bytes()
    )


def test_mutators_reject_mixed_newlines(tmp_path):
    project_file = tmp_path / "mixed.prj"
    project_file.write_bytes(
        b"Proj Title=Example\r\nCurrent Plan=p01\nPlan File=p01\r\n"
    )
    project = RasPrj()
    project.prj_file = project_file
    project.plan_df = pd.DataFrame({"plan_number": ["01"]})
    project.check_initialized = lambda: None

    with pytest.raises(ValueError, match="Mixed newline conventions"):
        project.set_current_plan("01")


def test_update_file_preserves_lf_for_linux_projects(tmp_path):
    text_file = tmp_path / "Example.p01"
    text_file.write_text("Plan Title=Old\nGeom File=g01\n", newline="\n")

    def update(lines):
        lines[0] = "Plan Title=New\n"
        return lines

    RasUtils.update_file(text_file, update)

    assert b"\r\n" not in text_file.read_bytes()
    assert text_file.read_bytes() == b"Plan Title=New\nGeom File=g01\n"
