from datetime import datetime

import pytest

from ras_commander import RasPlan


@pytest.mark.parametrize(
    ("existing_times", "expected_times"),
    [
        (("0000", "2359"), ("0715", "1845")),
        (("00:00", "23:59"), ("07:15", "18:45")),
        (("0000", "23:59"), ("0715", "18:45")),
        (("00:00", "2359"), ("07:15", "1845")),
    ],
)
def test_update_simulation_date_preserves_each_time_token_style(
    tmp_path,
    existing_times,
    expected_times,
):
    plan_file = tmp_path / "project.p01"
    plan_file.write_text(
        "Plan Title=Test\n"
        f"Simulation Date=01JAN2000,{existing_times[0]},"
        f"02JAN2000,{existing_times[1]}\n",
        encoding="utf-8",
    )

    RasPlan.update_simulation_date(
        plan_file,
        datetime(2026, 8, 22, 7, 15),
        datetime(2026, 8, 23, 18, 45),
    )

    simulation_date = next(
        line
        for line in plan_file.read_text(encoding="utf-8").splitlines()
        if line.startswith("Simulation Date=")
    )
    assert simulation_date == (
        f"Simulation Date=22AUG2026,{expected_times[0]},"
        f"23AUG2026,{expected_times[1]}"
    )


@pytest.mark.parametrize(
    "simulation_date",
    [
        "Simulation Date=01JAN2000,0000,02JAN2000",
        "Simulation Date=01JAN2000,00:000,02JAN2000,2359",
        "Simulation Date=01JAN2000,0000,02JAN2000,23.59",
    ],
)
def test_update_simulation_date_rejects_malformed_record_without_writing(
    tmp_path,
    simulation_date,
):
    plan_file = tmp_path / "project.p01"
    original = f"Plan Title=Test\r\n{simulation_date}\r\n".encode()
    plan_file.write_bytes(original)

    with pytest.raises(ValueError, match="Malformed"):
        RasPlan.update_simulation_date(
            plan_file,
            datetime(2026, 8, 22, 7, 15),
            datetime(2026, 8, 23, 18, 45),
        )

    assert plan_file.read_bytes() == original


def test_update_simulation_date_retains_missing_record_failure(tmp_path):
    plan_file = tmp_path / "project.p01"
    original = b"Plan Title=Test\n"
    plan_file.write_bytes(original)

    with pytest.raises(ValueError, match="line not found"):
        RasPlan.update_simulation_date(
            plan_file,
            datetime(2026, 8, 22, 7, 15),
            datetime(2026, 8, 23, 18, 45),
        )

    assert plan_file.read_bytes() == original
