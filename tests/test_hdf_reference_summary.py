"""HdfResultsPlan.get_reference_summary derives its table from stored time series.

HEC-RAS writes no ``Summary Output/Reference Lines|Points`` group; the reader
summarizes ``Base Output/Unsteady Time Series/Reference Lines|Points``.
Expected values here come from plain h5py reads, never from the code under test.

Real fixtures: set ``RAS_ROUTE2_FIXTURES`` to the PY-ROUTE-2 JSON manifest
(``{"fixtures": [{"name", "path"}]}``); plans with reference output are checked
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
from ras_commander.hdf import HdfResultsPlan

BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
GROUPS = {"lines": "Reference Lines", "points": "Reference Points"}
STAMPS = [b"01JAN2000 00:00:00:000", b"01JAN2000 01:00:00:000", b"01JAN2000 02:00:00:000"]
T = pd.to_datetime(["2000-01-01 00:00", "2000-01-01 01:00", "2000-01-01 02:00"])


def _write(path):
    with h5py.File(path, "w") as hdf:
        base = hdf.require_group(BASE)
        base.create_dataset("Time Date Stamp (ms)", data=np.array(STAMPS, dtype="S24"))
        lines = base.require_group("Reference Lines")
        lines.create_dataset("Name", data=np.array([b"L1|Area A", b"L2|Area B"], dtype="S16"))
        flow = lines.create_dataset("Flow", data=np.array(
            [[1.0, np.nan], [5.0, np.nan], [5.0, np.nan]], dtype=np.float32))
        flow.attrs["Units"] = b"cfs"
        lines.create_dataset("Water Surface", data=np.array(
            [[10.0, 3.0], [9.0, np.nan], [12.0, -1.0]], dtype=np.float32))
        # Not a (time, feature) series: ignored, as get_reference_timeseries does.
        lines.create_dataset("Depth Unit", data=np.ones((3, 2), dtype=np.float32))
        # Per-area copy (subset of the global group) must not add rows.
        area = base.require_group("2D Flow Areas/Area A/Reference Lines")
        area.create_dataset("Name", data=np.array([b"L1"], dtype="S8"))
        area.create_dataset("Flow", data=np.array([[1.0], [5.0], [5.0]], dtype=np.float32))
    return path


def test_synthetic_lines_summary(tmp_path):
    df = HdfResultsPlan.get_reference_summary(_write(tmp_path / "s.p01.hdf"), "lines")

    assert list(df.columns) == ["Reference", "Mesh Name", "Variable", "Statistic",
                                "Value", "Time", "Units"]
    assert len(df) == 2 * 2 * 2
    rows = {(r.Reference, r.Variable, r.Statistic): r for r in df.itertuples()}
    assert rows[("L1", "Flow", "Maximum")].Value == 5.0
    assert rows[("L1", "Flow", "Maximum")].Time == T[1]  # first occurrence
    assert rows[("L1", "Flow", "Minimum")].Value == 1.0
    assert rows[("L1", "Flow", "Maximum")].Units == "cfs"
    assert rows[("L1", "Flow", "Maximum")]._2 == "Area A"
    assert np.isnan(rows[("L2", "Flow", "Maximum")].Value)
    assert pd.isna(rows[("L2", "Flow", "Maximum")].Time)
    assert rows[("L2", "Water Surface", "Minimum")].Value == -1.0  # NaN skipped
    assert rows[("L2", "Water Surface", "Minimum")].Time == T[2]
    assert rows[("L2", "Water Surface", "Maximum")].Units == ""
    assert list(df["Reference"].unique()) == ["L1", "L2"]
    assert not (df["Variable"] == "Depth Unit").any()


def test_missing_reference_type_or_bad_reftype_is_empty(tmp_path):
    path = _write(tmp_path / "s.p01.hdf")
    assert HdfResultsPlan.get_reference_summary(path, "points").empty
    assert HdfResultsPlan.get_reference_summary(path, "polygons").empty


def _real_reference_plans():
    manifest = os.environ.get("RAS_ROUTE2_FIXTURES")
    if not manifest:
        return []
    plans = []
    for fixture in json.loads(Path(manifest).read_text())["fixtures"]:
        path = Path(fixture["path"])
        if not path.is_file():
            continue
        with h5py.File(path, "r") as hdf:
            if f"{BASE}/Time Date Stamp (ms)" not in hdf:
                continue
            for reftype, group in GROUPS.items():
                if f"{BASE}/{group}/Name" in hdf:
                    plans.append(pytest.param(path, reftype, id=f"{fixture['name']}-{reftype}"))
    return plans


def _expected(path, reftype):
    """Independent h5py computation of the documented summary."""
    with h5py.File(path, "r") as hdf:
        base = hdf[BASE]
        times = pd.to_datetime([s.decode() for s in base["Time Date Stamp (ms)"][()]],
                               format="%d%b%Y %H:%M:%S:%f")
        group = base[GROUPS[reftype]]
        names = [n.decode().strip() for n in group["Name"][()]]
        variables = [
            k for k, d in group.items()
            if isinstance(d, h5py.Dataset) and k != "Name"
            and not any(w in k.lower() for w in ("unit", "index", "string"))
            and d.shape == (len(times), len(names)) and d.dtype.kind in "iuf"
        ]
        rows = []
        for j, full in enumerate(names):
            name, _, mesh = full.partition("|")
            for var in variables:
                col = group[var][:, j].astype(np.float64)
                units = group[var].attrs.get("Units", b"")
                units = units.decode() if isinstance(units, bytes) else str(units)
                for stat, func, argf in (("Maximum", np.nanmax, np.nanargmax),
                                         ("Minimum", np.nanmin, np.nanargmin)):
                    if np.isfinite(col).any():
                        value, when = func(col), times[int(argf(col))]
                    else:
                        value, when = np.nan, pd.NaT
                    rows.append((name.strip(), mesh.strip(), var, stat, value, when, units))
    return pd.DataFrame(rows, columns=["Reference", "Mesh Name", "Variable", "Statistic",
                                       "Value", "Time", "Units"])


@pytest.mark.skipif(not os.environ.get("RAS_ROUTE2_FIXTURES"),
                    reason="Set RAS_ROUTE2_FIXTURES to a real-fixture JSON manifest")
@pytest.mark.parametrize("path,reftype", _real_reference_plans())
def test_real_plan_matches_independent_h5py(path, reftype):
    with fast_hdf.backend_scope("h5py"):
        df = HdfResultsPlan.get_reference_summary(path, reftype)

    expected = _expected(path, reftype)
    assert not df.empty
    pd.testing.assert_frame_equal(df, expected, check_exact=True, check_dtype=False)
    assert df["Value"].dtype == np.float64

    if fast_hdf.available():
        with fast_hdf.trace_reads() as trace:
            with fast_hdf.backend_scope("native"):
                native = HdfResultsPlan.get_reference_summary(path, reftype)
        assert any(r["backend"] == "native-typed" for r in trace)
        pd.testing.assert_frame_equal(df, native, check_exact=True)
