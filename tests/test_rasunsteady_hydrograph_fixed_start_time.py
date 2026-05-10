"""Tests for hydrograph fixed-start timing in unsteady flow files."""

from datetime import datetime

import pytest

from ras_commander import RasUnsteady


class _DummyRas:
    def check_initialized(self):
        return None


def _write_unsteady_file(tmp_path, lines):
    unsteady_file = tmp_path / "model.u01"
    unsteady_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return unsteady_file


def _read_lines(unsteady_file):
    return unsteady_file.read_text(encoding="utf-8").splitlines()


def test_set_hydrograph_fixed_start_time_enables_existing_lines(tmp_path):
    unsteady_file = _write_unsteady_file(
        tmp_path,
        [
            "Flow Title=Test Flow",
            "Program Version=6.60",
            "Boundary Location=White,Muncie,15696.24",
            "Interval=1HOUR",
            "Flow Hydrograph= 2 ",
            "   100.0   200.0",
            "Use Fixed Start Time=False",
            "Fixed Start Date/Time=,",
        ],
    )

    result = RasUnsteady.set_hydrograph_fixed_start_time(
        unsteady_file,
        use_fixed_start_time=True,
        fixed_start_datetime=datetime(1900, 1, 2, 0, 0),
        ras_object=_DummyRas(),
    )

    lines = _read_lines(unsteady_file)
    assert "Use Fixed Start Time=True" in lines
    assert "Fixed Start Date/Time=02JAN1900,0000" in lines
    assert result["updated_use_fixed_start_time_lines"] == 1
    assert result["updated_fixed_start_datetime_lines"] == 1
    assert result["inserted_fixed_start_datetime_lines"] == 0


def test_set_hydrograph_fixed_start_time_inserts_missing_datetime_line(tmp_path):
    unsteady_file = _write_unsteady_file(
        tmp_path,
        [
            "Flow Title=Test Flow",
            "Program Version=6.60",
            "Boundary Location=White,Muncie,15696.24",
            "Flow Hydrograph= 2 ",
            "   100.0   200.0",
            "Use Fixed Start Time=False",
            "Use DSS=False",
        ],
    )

    result = RasUnsteady.set_hydrograph_fixed_start_time(
        unsteady_file,
        use_fixed_start_time=True,
        fixed_start_datetime=("02JAN1900", "0000"),
        ras_object=_DummyRas(),
    )

    lines = _read_lines(unsteady_file)
    use_index = lines.index("Use Fixed Start Time=True")
    assert lines[use_index + 1] == "Fixed Start Date/Time=02JAN1900,0000"
    assert result["inserted_fixed_start_datetime_lines"] == 1


def test_set_hydrograph_fixed_start_time_disables_and_clears_datetime(tmp_path):
    unsteady_file = _write_unsteady_file(
        tmp_path,
        [
            "Flow Title=Test Flow",
            "Program Version=6.60",
            "Boundary Location=White,Muncie,15696.24",
            "Flow Hydrograph= 2 ",
            "   100.0   200.0",
            "Use Fixed Start Time=True",
            "Fixed Start Date/Time=02JAN1900,0000",
        ],
    )

    result = RasUnsteady.set_hydrograph_fixed_start_time(
        unsteady_file,
        use_fixed_start_time=False,
        ras_object=_DummyRas(),
    )

    lines = _read_lines(unsteady_file)
    assert "Use Fixed Start Time=False" in lines
    assert "Fixed Start Date/Time=," in lines
    assert result["fixed_start_datetime"] == ","


def test_set_hydrograph_fixed_start_time_requires_datetime_when_enabled(tmp_path):
    unsteady_file = _write_unsteady_file(
        tmp_path,
        [
            "Flow Title=Test Flow",
            "Program Version=6.60",
            "Boundary Location=White,Muncie,15696.24",
            "Use Fixed Start Time=False",
            "Fixed Start Date/Time=,",
        ],
    )

    with pytest.raises(ValueError, match="fixed_start_datetime is required"):
        RasUnsteady.set_hydrograph_fixed_start_time(
            unsteady_file,
            use_fixed_start_time=True,
            ras_object=_DummyRas(),
        )
