"""HdfPump.get_pump_station_summary derives its table from stored pump results.

HEC-RAS writes no pump station summary dataset; the reader summarizes the
``DSS Hydrograph Output`` ``Pumping Stations/<station>/Structure Variables``
time series. Expected values here come from plain h5py reads, never from the
code under test.

Real fixtures: set ``RAS_ROUTE2_FIXTURES`` to the PY-ROUTE-2 JSON manifest
(``{"fixtures": [{"name", "path"}]}``); plans with pump results are checked
and the native engine output must equal the h5py output. Without it only the
synthetic cases run.
"""
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import fast_hdf
from ras_commander.hdf import HdfPump

BLOCK = "Results/Unsteady/Output/Output Blocks/DSS Hydrograph Output/Unsteady Time Series"
STATIONS = f"{BLOCK}/Pumping Stations"


def _units(rows):
    return np.array([[label.encode(), unit.encode()] for label, unit in rows], dtype="S32")


def _write(path, stations, stamps=None, days=None):
    with h5py.File(path, "w") as hdf:
        block = hdf.require_group(BLOCK)
        if stamps is not None:
            block.create_dataset("Time Date Stamp (ms)", data=np.array(stamps, dtype="S24"))
        if days is not None:
            ds = block.create_dataset("Time", data=np.asarray(days, dtype=np.float64))
            ds.attrs["Time"] = b"Days"
        for name, (data, rows, highest) in stations.items():
            group = block.require_group(f"Pumping Stations/{name}")
            if highest is not None:
                group.attrs["Highest Elev Pump Line"] = np.float32(highest)
            dataset = group.create_dataset("Structure Variables", data=np.asarray(data, np.float32))
            if rows is not None:
                dataset.attrs["Variable_Unit"] = _units(rows)
        # Other blocks must not be consulted.
        hdf.require_group(
            "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
            "Pumping Stations/Ignored"
        )
    return path


SIMPLE = [("Flow", "cfs"), ("Stage HW", "ft"), ("Stage TW", "ft"),
          ("Group #1", "cfs"), ("Group #1", "Pumps on")]
TWO_GROUPS = SIMPLE + [("Group #2", "cfs"), ("Group #2", "Pumps on")]
STAMPS = [b"10APR2024 00:00:00:000", b"10APR2024 00:05:00:000", b"10APR2024 00:10:00:000"]


def test_synthetic_two_stations_multi_group(tmp_path):
    a = [[1.0, 10.0, 5.0, 1.0, 1.0],
         [4.0, 12.0, 4.0, 4.0, 2.0],
         [4.0, 11.0, 6.0, 4.0, 2.0]]
    b = [[0.0, 3.0, 2.0, 0.0, 0.0, 0.0, 0.0],
         [np.nan, 2.0, 2.5, 5.0, 1.0, 7.0, 2.0],
         [9.0, 1.0, 3.0, 4.0, 2.0, 5.0, 1.0]]
    path = _write(tmp_path / "s.p01.hdf",
                  {"A": (a, SIMPLE, 220.0), "B": (b, TWO_GROUPS, None)}, stamps=STAMPS)

    df = HdfPump.get_pump_station_summary(path)

    assert list(df["Pump Station"]) == ["A", "B"]
    assert list(df["Output Block"]) == ["DSS Hydrograph Output"] * 2
    assert list(df["Time Steps"]) == [3, 3]
    t = pd.to_datetime(["2024-04-10 00:00", "2024-04-10 00:05", "2024-04-10 00:10"])
    a_row, b_row = df.iloc[0], df.iloc[1]
    # first occurrence of the stored maximum
    assert a_row["Max Flow"] == 4.0 and a_row["Max Flow Time"] == t[1]
    assert a_row["Min Flow"] == 1.0 and a_row["Min Flow Time"] == t[0]
    assert a_row["Max Stage HW"] == 12.0 and a_row["Min Stage TW Time"] == t[1]
    assert a_row["Max Pumps On"] == 2.0 and a_row["Max Pumps On Time"] == t[1]
    assert a_row["Highest Elev Pump Line"] == 220.0
    # NaN samples are ignored; pumps on is the per-step sum over groups
    assert b_row["Max Flow"] == 9.0 and b_row["Max Flow Time"] == t[2]
    assert b_row["Min Flow"] == 0.0
    assert b_row["Max Pumps On"] == 3.0 and b_row["Max Pumps On Time"] == t[1]
    assert np.isnan(b_row["Highest Elev Pump Line"])
    assert df["Start Time"].tolist() == [t[0]] * 2 and df["End Time"].tolist() == [t[2]] * 2
    assert df.attrs["units"] == {"Flow": "cfs", "Stage HW": "ft", "Stage TW": "ft",
                                 "Pumps On": "Pumps on"}
    assert "time_units" not in df.attrs


@pytest.mark.synthetic_hdf_layout
def test_synthetic_days_axis_and_no_pump_columns(tmp_path):
    data = [[1.0, 2.0, 3.0], [2.0, 1.0, 3.0]]
    path = _write(tmp_path / "d.p01.hdf", {"P": (data, SIMPLE[:3], None)}, days=[0.0, 0.5])

    df = HdfPump.get_pump_station_summary(path)

    assert df.attrs["time_units"] == "days"
    assert df.loc[0, "Max Flow Time"] == 0.5 and df.loc[0, "Min Stage HW Time"] == 0.5
    assert np.isnan(df.loc[0, "Max Pumps On"])


def test_unrecognized_layout_is_refused(tmp_path):
    bad = [("Stage HW", "ft"), ("Flow", "cfs"), ("Stage TW", "ft")]
    path = _write(tmp_path / "b.p01.hdf", {"P": ([[1.0, 2.0, 3.0]], bad, None)}, stamps=STAMPS[:1])
    with pytest.raises(ValueError, match="layout not recognized"):
        HdfPump.get_pump_station_summary(path)

    path = _write(tmp_path / "n.p01.hdf", {"P": ([[1.0, 2.0, 3.0]], None, None)}, stamps=STAMPS[:1])
    with pytest.raises(ValueError, match="Variable_Unit"):
        HdfPump.get_pump_station_summary(path)


def test_no_dss_hydrograph_pump_results_is_empty(tmp_path):
    path = tmp_path / "e.p01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.require_group(
            "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/"
            "Pumping Stations/Only Base"
        )
    assert HdfPump.get_pump_station_summary(path).empty


def _real_pump_plans():
    manifest = os.environ.get("RAS_ROUTE2_FIXTURES")
    if not manifest:
        return []
    plans = []
    for fixture in json.loads(Path(manifest).read_text())["fixtures"]:
        path = Path(fixture["path"])
        if not path.is_file():
            continue
        with h5py.File(path, "r") as hdf:
            if isinstance(hdf.get(STATIONS), h5py.Group) and len(hdf[STATIONS]):
                plans.append(pytest.param(path, id=fixture["name"]))
    return plans


@pytest.mark.skipif(not os.environ.get("RAS_ROUTE2_FIXTURES"),
                    reason="Set RAS_ROUTE2_FIXTURES to a real-fixture JSON manifest")
@pytest.mark.parametrize("path", _real_pump_plans())
def test_real_plan_matches_independent_h5py(path):
    with fast_hdf.backend_scope("h5py"):
        df = HdfPump.get_pump_station_summary(path)

    with h5py.File(path, "r") as hdf:
        block = hdf[BLOCK]
        stamps = [s.decode().strip() for s in block["Time Date Stamp (ms)"][()]]
        times = pd.to_datetime(stamps, format="%d%b%Y %H:%M:%S:%f")
        names = list(hdf[STATIONS].keys())
        assert list(df["Pump Station"]) == names
        for (_, got), name in zip(df.iterrows(), names):
            group = hdf[STATIONS][name]
            values = group["Structure Variables"][()].astype(np.float64)
            labels = [(lab.decode().strip(), unit.decode().strip())
                      for lab, unit in group["Structure Variables"].attrs["Variable_Unit"]]
            assert got["Time Steps"] == len(values) == len(times)
            assert got["Start Time"] == times[0] and got["End Time"] == times[-1]
            for idx, var in enumerate(["Flow", "Stage HW", "Stage TW"]):
                assert labels[idx][0] == var
                col = values[:, idx]
                assert got[f"Max {var}"] == np.nanmax(col)
                assert got[f"Max {var} Time"] == times[int(np.nanargmax(col))]
                assert got[f"Min {var}"] == np.nanmin(col)
                assert got[f"Min {var} Time"] == times[int(np.nanargmin(col))]
            pumps = [i for i, (_, unit) in enumerate(labels) if i >= 3 and unit == "Pumps on"]
            total = values[:, pumps].sum(axis=1)
            assert got["Max Pumps On"] == total.max()
            assert got["Max Pumps On Time"] == times[int(total.argmax())]
            highest = group.attrs.get("Highest Elev Pump Line")
            if highest is None:
                assert np.isnan(got["Highest Elev Pump Line"])
            else:
                assert got["Highest Elev Pump Line"] == float(highest)

    if fast_hdf.available():
        with fast_hdf.trace_reads() as trace:
            with fast_hdf.backend_scope("native"):
                native = HdfPump.get_pump_station_summary(path)
        assert any(r["backend"] == "native-typed" for r in trace)
        pd.testing.assert_frame_equal(df, native, check_exact=True)
        assert df.attrs == native.attrs
