"""Integration tests for HEC-DSS grid writing through RasDss."""

from datetime import datetime
import hashlib
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest


pytestmark = pytest.mark.integration


def _configure_dss_or_skip():
    from ras_commander import RasDss

    try:
        RasDss._configure_jvm()
    except (ImportError, RuntimeError) as exc:
        pytest.skip(f"HEC Monolith/pyjnius unavailable: {exc}")
    return RasDss


def test_write_grid_timeseries_round_trips_synthetic_shg_grid(tmp_path):
    RasDss = _configure_dss_or_skip()

    dss_file = tmp_path / "synthetic_grid.dss"
    data = np.arange(5 * 10 * 10, dtype=np.float32).reshape(5, 10, 10)
    times = [datetime(2020, 1, 1, hour) for hour in range(1, 6)]

    written = RasDss.write_grid_timeseries(
        dss_file=dss_file,
        pathname="/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/RC_TEST/",
        data=data,
        times=times,
        grid_info={
            "cellsize": 2000,
            "origin": (1096000, 1516000),
            "crs": "SHG",
            "units": "mm",
            "data_type": "PER-CUM",
        },
    )

    assert written == [
        "/SHG/TEST/PRECIP/01JAN2020:0000/01JAN2020:0100/RC_TEST/",
        "/SHG/TEST/PRECIP/01JAN2020:0100/01JAN2020:0200/RC_TEST/",
        "/SHG/TEST/PRECIP/01JAN2020:0200/01JAN2020:0300/RC_TEST/",
        "/SHG/TEST/PRECIP/01JAN2020:0300/01JAN2020:0400/RC_TEST/",
        "/SHG/TEST/PRECIP/01JAN2020:0400/01JAN2020:0500/RC_TEST/",
    ]

    catalog = RasDss.get_catalog(dss_file)
    assert sorted(catalog["pathname"].tolist()) == sorted(written)

    result = RasDss.read_grid(dss_file, written[2])

    assert result["dss_file"] == str(dss_file.resolve())
    assert result["pathname"] == written[2]
    assert result["shape"] == (10, 10)
    assert result["data"].dtype == np.float32
    assert np.allclose(result["data"], data[2])
    assert result["units"] == "mm"
    assert result["data_type"] == "PER-CUM"
    assert result["grid_type"] == "albers"
    assert "Albers_Equal_Area" in result["crs"]
    assert result["cell_size"] == 2000.0
    assert result["start_time"] == pd.Timestamp("2020-01-01 02:00")
    assert result["end_time"] == pd.Timestamp("2020-01-01 03:00")

    metadata = result["metadata"]
    assert metadata["grid_class"] == "hec.heclib.grid.AlbersInfo"
    assert metadata["pathname_parts"] == {
        "A": "SHG",
        "B": "TEST",
        "C": "PRECIP",
        "D": "01JAN2020:0200",
        "E": "01JAN2020:0300",
        "F": "RC_TEST",
    }
    assert metadata["grid_type_code"] == 420
    assert metadata["data_type_code"] == 1
    assert metadata["shape"] == (10, 10)
    assert metadata["lower_left_cell"] == (548, 758)
    assert metadata["origin"] == (1096000.0, 1516000.0)
    assert metadata["number_missing"] == 0
    assert metadata["projection"]["units"] == "Meter"
    assert metadata["projection"]["central_meridian"] == -96.0
    assert metadata["timing"]["period"] == (
        "1 January 2020, 02:00 to 1 January 2020, 03:00"
    )

    from jnius import autoclass, cast

    HecDss = autoclass("hec.heclib.dss.HecDss")
    dss = HecDss.open(str(dss_file))
    try:
        container = cast("hec.io.GridContainer", dss.get(written[2]))
        grid_data = container.getGridData()
        grid_info = cast("hec.heclib.grid.AlbersInfo", grid_data.getGridInfo())
        values = np.asarray(grid_data.getData(), dtype=np.float32)
    finally:
        dss.done()

    assert grid_info.getNumberOfCellsX() == 10
    assert grid_info.getNumberOfCellsY() == 10
    assert grid_info.getLowerLeftCellX() == 548
    assert grid_info.getLowerLeftCellY() == 758
    assert grid_info.getCellSize() == 2000
    assert grid_info.getDataUnits() == "mm"
    assert grid_info.getDataTypeName() == "PER-CUM"
    assert grid_info.getGridType() == 420
    assert np.allclose(values, data[2].ravel())


def test_read_grid_round_trips_specified_grid_and_missing_values(tmp_path):
    RasDss = _configure_dss_or_skip()

    dss_file = tmp_path / "specified_grid.dss"
    data = np.array([[[1.25, np.nan], [3.5, 4.75]]], dtype=np.float32)
    written = RasDss.write_grid_timeseries(
        dss_file=dss_file,
        pathname="/SPECIFIED/TEST/PRECIP/01JUN2024:1200/01JUN2024:1230/RC_TEST/",
        data=data,
        times=[datetime(2024, 6, 1, 12, 30)],
        grid_info={
            "cellsize": 0.01,
            "origin": (-95.5, 29.5),
            "x_coord_cell_zero": -180.0,
            "y_coord_cell_zero": -90.0,
            "crs": "EPSG:4326",
            "crs_name": "WGS 84",
            "units": "INCHES",
            "data_type": "PER-CUM",
            "interval_minutes": 30,
            "compression": "ZLIB",
        },
    )

    result = RasDss.read_grid(str(dss_file), written[0])

    assert result["pathname"] == written[0]
    assert result["grid_type"] == "specified"
    assert result["crs"] == "EPSG:4326"
    assert result["cell_size"] == pytest.approx(0.01)
    assert result["start_time"] == pd.Timestamp("2024-06-01 12:00")
    assert result["end_time"] == pd.Timestamp("2024-06-01 12:30")
    np.testing.assert_allclose(result["data"], data[0], equal_nan=True)

    metadata = result["metadata"]
    assert metadata["grid_class"] == "hec.heclib.grid.SpecifiedGridInfo"
    assert metadata["number_missing"] == 1
    assert metadata["projection"]["x_coord_cell_zero"] == -180.0
    assert metadata["projection"]["y_coord_cell_zero"] == -90.0
    assert metadata["origin"] == pytest.approx((-95.5, 29.5))


def test_read_grid_reports_exact_path_errors(tmp_path):
    RasDss = _configure_dss_or_skip()

    missing_file = tmp_path / "missing.dss"
    pathname = "/BASIN/LOCATION/PRECIP/01JAN2020:0000/01JAN2020:0100/TEST/"
    with pytest.raises(FileNotFoundError, match="DSS file not found"):
        RasDss.read_grid(missing_file, pathname)

    dss_file = tmp_path / "exact_path.dss"
    written = RasDss.write_grid_timeseries(
        dss_file=dss_file,
        pathname=pathname,
        data=np.ones((1, 1, 1), dtype=np.float32),
        times=[datetime(2020, 1, 1, 1)],
        grid_info={"cellsize": 2000, "crs": "SHG"},
    )

    with pytest.raises(ValueError, match="exact pathname"):
        RasDss.read_grid(dss_file, written[0].replace("PRECIP", "TEMPERATURE"))
    with pytest.raises(ValueError, match="without wildcard"):
        RasDss.read_grid(Path(dss_file), written[0].replace("PRECIP", "P*"))
    with pytest.raises(ValueError, match="must have 6 parts"):
        RasDss.read_grid(dss_file, "/TOO/FEW/PARTS/")


def test_parse_grid_dss_datetime_normalizes_2400():
    RasDss = _configure_dss_or_skip()

    assert RasDss._parse_grid_dss_datetime("31DEC2022:2400") == pd.Timestamp(
        "2023-01-01 00:00"
    )


def test_datetimes_to_hec_times_returns_int32_minutes():
    RasDss = _configure_dss_or_skip()
    times = pd.DatetimeIndex(
        ["1899-12-31 00:00", "1900-01-01 00:00", "2019-09-18 13:00"]
    )

    result = RasDss._datetimes_to_hec_times(times)

    assert result.dtype == np.int32
    assert result.tolist() == [0, 1440, 62964780]


def test_write_timeseries_round_trips_modern_dates(tmp_path):
    RasDss = _configure_dss_or_skip()
    dss_file = tmp_path / "modern-timeseries.dss"
    pathname = "/BASIN/UPSTREAM/FLOW//1HOUR/QUALIFICATION/"
    times = pd.date_range("2019-09-18 13:00", periods=4, freq="h")
    values = np.array(
        [52700.41850796765, 52752.45784599134, 52802.061108445996, 52849.18364664102]
    )

    RasDss.write_timeseries(
        dss_file,
        pathname,
        times,
        values,
        units="CFS",
        data_type="INST-VAL",
    )
    reread = RasDss.read_timeseries(dss_file, pathname)

    assert reread.index.equals(times.rename("datetime"))
    np.testing.assert_array_equal(reread["value"].to_numpy(), values)
    assert reread.attrs["units"] == "CFS"
    assert reread.attrs["type"] == "INST-VAL"


def test_copy_grid_with_zero_tail_preserves_source_and_nodata(tmp_path):
    RasDss = _configure_dss_or_skip()

    source = tmp_path / "source.dss"
    output = tmp_path / "padded.dss"
    pathname = "/SHG/TEST/PRECIPITATION///AORC-TRANSPOSED/"
    fixture_script = """
from datetime import datetime
from pathlib import Path
import numpy as np
from ras_commander import RasDss

RasDss.write_grid_timeseries(
    dss_file=Path(__import__("sys").argv[1]),
    pathname="/SHG/TEST/PRECIPITATION///AORC-TRANSPOSED/",
    data=np.array(
        [
            [[1.0, np.nan], [2.0, 3.0]],
            [[4.0, np.nan], [5.0, 6.0]],
        ],
        dtype=np.float32,
    ),
    times=[
        datetime(2020, 1, 1, 0),
        datetime(2020, 1, 1, 1),
        datetime(2020, 1, 1, 2),
    ],
    grid_info={
        "cellsize": 1000,
        "origin": (259000, 1024000),
        "crs": "SHG",
        "units": "MM",
        "data_type": "PER-CUM",
    },
)
"""
    completed = subprocess.run(
        [sys.executable, "-c", fixture_script, str(source)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    original_paths = [
        "/SHG/TEST/PRECIPITATION/01JAN2020:0000/01JAN2020:0100/AORC-TRANSPOSED/",
        "/SHG/TEST/PRECIPITATION/01JAN2020:0100/01JAN2020:0200/AORC-TRANSPOSED/",
    ]

    result = RasDss.copy_grid_with_zero_tail(
        source,
        output,
        pathname,
        tail_intervals=3,
    )

    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256
    assert result["source_record_count"] == 2
    assert result["appended_record_count"] == 3
    assert result["interval_minutes"] == 60
    assert result["time_shift_minutes"] == 0
    assert result["source_start"] == "2020-01-01T00:00:00"
    assert result["source_end"] == "2020-01-01T02:00:00"
    assert result["output_start"] == "2020-01-01T00:00:00"
    assert result["output_source_end"] == "2020-01-01T02:00:00"
    assert result["padded_end"] == "2020-01-01T05:00:00"
    assert result["shifted_pathnames"] == []

    output_paths = RasDss.get_catalog(output)["pathname"].tolist()
    assert sorted(output_paths) == sorted(
        original_paths + result["appended_pathnames"]
    )
    first_tail = RasDss.read_grid(output, result["appended_pathnames"][0])
    np.testing.assert_allclose(
        first_tail["data"],
        np.array([[0.0, np.nan], [0.0, 0.0]], dtype=np.float32),
        equal_nan=True,
    )
    assert first_tail["units"] == "MM"
    assert first_tail["data_type"] == "PER-CUM"
    assert first_tail["cell_size"] == 1000.0


def test_copy_grid_with_zero_tail_shifts_pathname_windows(tmp_path):
    RasDss = _configure_dss_or_skip()

    source = tmp_path / "source.dss"
    output = tmp_path / "shifted.dss"
    fixture_script = """
from datetime import datetime
from pathlib import Path
import numpy as np
from ras_commander import RasDss

RasDss.write_grid_timeseries(
    dss_file=Path(__import__("sys").argv[1]),
    pathname="/SHG/TEST/PRECIPITATION///AORC-TRANSPOSED/",
    data=np.array(
        [
            [[1.0, np.nan], [2.0, 3.0]],
            [[4.0, np.nan], [5.0, 6.0]],
        ],
        dtype=np.float32,
    ),
    times=[
        datetime(2020, 1, 1, 0),
        datetime(2020, 1, 1, 1),
        datetime(2020, 1, 1, 2),
    ],
    grid_info={
        "cellsize": 1000,
        "origin": (259000, 1024000),
        "crs": "SHG",
        "units": "MM",
        "data_type": "PER-CUM",
    },
)
"""
    completed = subprocess.run(
        [sys.executable, "-c", fixture_script, str(source)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    transform_script = """
from pathlib import Path
from ras_commander import RasDss

RasDss.copy_grid_with_zero_tail(
    Path(__import__("sys").argv[1]),
    Path(__import__("sys").argv[2]),
    "/SHG/TEST/PRECIPITATION///AORC-TRANSPOSED/",
    tail_intervals=1,
    time_shift_minutes=-300,
)
"""
    completed = subprocess.run(
        [sys.executable, "-c", transform_script, str(source), str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256

    output_paths = sorted(RasDss.get_catalog(output)["pathname"].tolist())
    assert output_paths == [
        "/SHG/TEST/PRECIPITATION/31DEC2019:1900/31DEC2019:2000/AORC-TRANSPOSED/",
        "/SHG/TEST/PRECIPITATION/31DEC2019:2000/31DEC2019:2100/AORC-TRANSPOSED/",
        "/SHG/TEST/PRECIPITATION/31DEC2019:2100/31DEC2019:2200/AORC-TRANSPOSED/",
    ]
    shifted_first = RasDss.read_grid(output, output_paths[0])
    shifted_tail = RasDss.read_grid(output, output_paths[-1])
    np.testing.assert_allclose(
        shifted_first["data"],
        np.array([[1.0, np.nan], [2.0, 3.0]], dtype=np.float32),
        equal_nan=True,
    )
    np.testing.assert_allclose(
        shifted_tail["data"],
        np.array([[0.0, np.nan], [0.0, 0.0]], dtype=np.float32),
        equal_nan=True,
    )


def test_copy_grid_with_zero_tail_translates_grid_without_resampling(tmp_path):
    RasDss = _configure_dss_or_skip()

    source = tmp_path / "source.dss"
    output = tmp_path / "translated.dss"
    fixture_script = """
from datetime import datetime
from pathlib import Path
import numpy as np
from ras_commander import RasDss

RasDss.write_grid_timeseries(
    dss_file=Path(__import__("sys").argv[1]),
    pathname="/SHG/TEST/PRECIPITATION///AORC/",
    data=np.array(
        [
            [[1.0, np.nan], [2.0, 3.0]],
            [[4.0, np.nan], [5.0, 6.0]],
        ],
        dtype=np.float32,
    ),
    times=[
        datetime(2020, 1, 1, 0),
        datetime(2020, 1, 1, 1),
        datetime(2020, 1, 1, 2),
    ],
    grid_info={
        "cellsize": 1000,
        "origin": (259000, 1024000),
        "crs": "SHG",
        "units": "MM",
        "data_type": "PER-CUM",
    },
)
"""
    completed = subprocess.run(
        [sys.executable, "-c", fixture_script, str(source)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    transform_script = """
from pathlib import Path
from ras_commander import RasDss

result = RasDss.copy_grid_with_zero_tail(
    Path(__import__("sys").argv[1]),
    Path(__import__("sys").argv[2]),
    "/SHG/TEST/PRECIPITATION///AORC/",
    tail_intervals=1,
    time_shift_minutes=-300,
    output_pathname="/SHG/TEST/PRECIPITATION///AORC-TRANSPOSED/",
    x_shift=2000,
    y_shift=3000,
)
assert result["output_lower_left_cell"] == (261, 1027)
"""
    completed = subprocess.run(
        [sys.executable, "-c", transform_script, str(source), str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256

    output_paths = sorted(RasDss.get_catalog(output)["pathname"].tolist())
    assert output_paths == [
        "/SHG/TEST/PRECIPITATION/31DEC2019:1900/31DEC2019:2000/AORC-TRANSPOSED/",
        "/SHG/TEST/PRECIPITATION/31DEC2019:2000/31DEC2019:2100/AORC-TRANSPOSED/",
        "/SHG/TEST/PRECIPITATION/31DEC2019:2100/31DEC2019:2200/AORC-TRANSPOSED/",
    ]
    translated = RasDss.read_grid(output, output_paths[0])
    np.testing.assert_allclose(
        translated["data"],
        np.array([[1.0, np.nan], [2.0, 3.0]], dtype=np.float32),
        equal_nan=True,
    )
    assert translated["metadata"]["lower_left_cell"] == (261, 1027)
    assert translated["metadata"]["origin"] == (261000.0, 1027000.0)


def test_copy_grid_with_zero_tail_refuses_unsafe_targets(tmp_path):
    RasDss = _configure_dss_or_skip()

    source = tmp_path / "source.dss"
    source.write_bytes(b"placeholder")

    with pytest.raises(ValueError, match="must differ"):
        RasDss.copy_grid_with_zero_tail(
            source,
            source,
            "/SHG/TEST/PRECIPITATION///TEST/",
            1,
        )

    existing = tmp_path / "existing.dss"
    existing.write_bytes(b"do not replace")
    with pytest.raises(FileExistsError, match="already exists"):
        RasDss.copy_grid_with_zero_tail(
            source,
            existing,
            "/SHG/TEST/PRECIPITATION///TEST/",
            1,
        )
    assert existing.read_bytes() == b"do not replace"
