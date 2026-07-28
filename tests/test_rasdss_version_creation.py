"""HEC-DSS major-version creation coverage."""

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasDss


def _configure_dss_or_skip():
    try:
        RasDss._configure_jvm()
    except Exception as exc:
        pytest.skip(f"HEC-DSS Java bridge unavailable: {exc}")
    return RasDss


def test_write_timeseries_can_create_version_6_file(tmp_path):
    dss = _configure_dss_or_skip()
    output = tmp_path / "boundary-v6.dss"
    pathname = "/BASIN/UPSTREAM/FLOW//5MIN/QUALIFICATION/"
    times = pd.date_range("2019-09-18 13:00", periods=5, freq="5min")
    values = np.array([100.0, 110.0, 125.0, 120.0, 115.0])

    dss.write_timeseries(
        output,
        pathname,
        times,
        values,
        units="CFS",
        data_type="INST-VAL",
        dss_version=6,
    )

    assert dss.get_file_version(output) == 6
    reread = dss.read_timeseries(output, pathname)
    assert reread.index.equals(times.rename("datetime"))
    np.testing.assert_array_equal(reread["value"].to_numpy(), values)


@pytest.mark.parametrize("version", [0, 5, 8])
def test_write_timeseries_rejects_unsupported_version(tmp_path, version):
    dss = _configure_dss_or_skip()

    with pytest.raises(ValueError, match="dss_version"):
        dss.write_timeseries(
            tmp_path / "invalid.dss",
            "/BASIN/UPSTREAM/FLOW//5MIN/QUALIFICATION/",
            pd.date_range("2019-09-18", periods=2, freq="5min"),
            [1.0, 2.0],
            dss_version=version,
        )
