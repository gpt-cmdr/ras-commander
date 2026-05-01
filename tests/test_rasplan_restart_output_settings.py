"""Tests for HEC-RAS restart output settings in plan files."""

from pathlib import Path

from ras_commander.RasPlan import RasPlan
from ras_commander.RasPrj import RasPrj


class _DummyRas:
    def check_initialized(self):
        return None


def _write_plan(path: Path, lines=None) -> None:
    if lines is None:
        lines = [
            "Plan Title=Restart Output Test",
            "Program Version=6.60",
            "Geom File=g01",
            "Flow File=u01",
            "DSS File=dss",
            "Write IC File= 0 ",
            "Write IC File at Fixed DateTime=0",
            "IC Time=,,",
            "Write IC File Reoccurance=",
            "Write IC File at Sim End=0",
            "Echo Input=False",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_set_restart_output_settings_fixed_datetime_round_trips(tmp_path):
    plan_path = tmp_path / "Project.p02"
    _write_plan(plan_path)

    assert RasPlan.set_restart_output_settings(
        plan_path,
        save_datetime=("03JAN1999", "1200"),
        recurrence_interval_hours=6,
        write_at_sim_end=True,
        ras_object=_DummyRas(),
    )

    content = plan_path.read_text(encoding="utf-8")
    assert "Write IC File= 1 \n" in content
    assert "Write IC File at Fixed DateTime=-1\n" in content
    assert "IC Time=,03JAN1999,1200\n" in content
    assert "Write IC File Reoccurance=6\n" in content
    assert "Write IC File at Sim End=-1\n" in content

    settings = RasPlan.get_restart_output_settings(plan_path, ras_object=_DummyRas())
    assert settings["enabled"] is True
    assert settings["save_at_fixed_datetime"] is True
    assert settings["save_datetime"] == "03JAN1999,1200"
    assert settings["recurrence_interval_hours"] == 6
    assert settings["write_at_sim_end"] is True
    assert settings["expected_filename"] == "Project.p02.03JAN1999 1200.rst"


def test_set_restart_output_settings_relative_hours_and_disable(tmp_path):
    plan_path = tmp_path / "Project.p03"
    _write_plan(plan_path)
    ras_obj = _DummyRas()

    assert RasPlan.set_restart_output_settings(
        plan_path,
        save_time_hours=12.5,
        ras_object=ras_obj,
    )

    settings = RasPlan.get_restart_output_settings(plan_path, ras_object=ras_obj)
    assert settings["enabled"] is True
    assert settings["save_at_fixed_datetime"] is False
    assert settings["save_time_hours"] == 12.5
    assert settings["save_datetime"] is None

    assert RasPlan.set_restart_output_settings(
        plan_path,
        enabled=False,
        ras_object=ras_obj,
    )

    disabled = RasPlan.get_restart_output_settings(plan_path, ras_object=ras_obj)
    assert disabled["enabled"] is False
    assert disabled["save_time_hours"] is None
    assert disabled["recurrence_interval_hours"] is None
    assert disabled["write_at_sim_end"] is False
    assert "IC Time=,,\n" in plan_path.read_text(encoding="utf-8")


def test_restart_output_settings_insert_missing_block_after_dss_file(tmp_path):
    plan_path = tmp_path / "Project.p04"
    _write_plan(
        plan_path,
        [
            "Plan Title=Restart Output Test",
            "Program Version=6.60",
            "DSS File=dss",
            "Echo Input=False",
        ],
    )

    assert RasPlan.set_restart_output_settings(
        plan_path,
        save_time_hours=3,
        ras_object=_DummyRas(),
    )

    lines = plan_path.read_text(encoding="utf-8").splitlines()
    assert lines[lines.index("DSS File=dss") + 1] == "Write IC File= 1 "
    assert lines[lines.index("Write IC File= 1 ") + 1] == (
        "Write IC File at Fixed DateTime=0"
    )
    assert lines[lines.index("IC Time=3,,") + 1] == "Write IC File Reoccurance="


def test_rasprj_parse_plan_file_includes_restart_output_keys(tmp_path):
    plan_path = tmp_path / "Project.p05"
    _write_plan(plan_path)

    parser = RasPrj.__new__(RasPrj)
    plan_info = parser._parse_plan_file(plan_path)

    assert plan_info["Write IC File"] == "0"
    assert plan_info["Write IC File at Fixed DateTime"] == "0"
    assert plan_info["IC Time"] == ",,"
    assert plan_info["Write IC File Reoccurance"] == ""
    assert plan_info["Write IC File at Sim End"] == "0"
