"""Integration tests for HEC-DSS grid writing through RasDss."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from ras_commander import RasDss

pytestmark = pytest.mark.integration

_BRIDGE_WORKER = Path(__file__).with_name("_rasdss_grid_bridge_worker.py")


def _run_bridge_scenario(scenario: str, output_dir: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(_BRIDGE_WORKER), scenario, str(output_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    combined_output = completed.stdout + completed.stderr

    if completed.returncode == 77 and "C03C_BRIDGE_UNAVAILABLE:" in completed.stdout:
        pytest.skip(completed.stdout.strip())

    assert "Windows fatal exception: access violation" not in combined_output
    assert completed.returncode == 0, combined_output
    assert f"C03C_SCENARIO_OK:{scenario}" in completed.stdout


def test_write_grid_timeseries_round_trips_synthetic_shg_grid(tmp_path):
    _run_bridge_scenario("shg_round_trip", tmp_path)


def test_read_grid_round_trips_specified_grid_and_missing_values(tmp_path):
    _run_bridge_scenario("specified_grid_round_trip", tmp_path)


def test_read_grid_reports_exact_path_errors(tmp_path):
    missing_file = tmp_path / "missing.dss"
    pathname = "/BASIN/LOCATION/PRECIP/01JAN2020:0000/01JAN2020:0100/TEST/"
    with pytest.raises(FileNotFoundError, match="DSS file not found"):
        RasDss.read_grid(missing_file, pathname)

    with pytest.raises(ValueError, match="without wildcard"):
        RasDss.read_grid(Path(missing_file), pathname.replace("PRECIP", "P*"))
    with pytest.raises(ValueError, match="must have 6 parts"):
        RasDss.read_grid(missing_file, "/TOO/FEW/PARTS/")

    _run_bridge_scenario("exact_path_error", tmp_path)


def test_parse_grid_dss_datetime_normalizes_2400():
    assert RasDss._parse_grid_dss_datetime("31DEC2022:2400") == pd.Timestamp(
        "2023-01-01 00:00"
    )


def test_write_grid_rejects_timezone_aware_times_before_jvm_or_output(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        RasDss,
        "_configure_jvm",
        staticmethod(
            lambda: pytest.fail("timezone rejection must precede JVM setup")
        ),
    )
    output = tmp_path / "missing-parent" / "aware-grid.dss"

    with pytest.raises(ValueError, match="timezone-naive"):
        RasDss.write_grid_timeseries(
            output,
            "/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/TZ/",
            data=[[[1.0]]],
            times=pd.date_range(
                "2020-01-01 01:00",
                periods=1,
                freq="h",
                tz="UTC",
            ),
            grid_info={"cellsize": 2000, "crs": "SHG"},
        )

    assert not output.parent.exists()
