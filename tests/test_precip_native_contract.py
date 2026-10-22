"""Source/table/native forcing controls, separate from hydraulic acceptance."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

h5py = pytest.importorskip("h5py")
xr = pytest.importorskip("xarray")

from ras_commander import HdfResultsMesh, RasPrj


pytestmark = [pytest.mark.integration, pytest.mark.offline_evidence]
MANIFEST = json.loads((Path(__file__).parent / "data/precip_native_manifest.json").read_text(encoding="utf-8"))
BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"


def _text(value):
    return value.decode("utf-8").strip() if isinstance(value, (bytes, np.bytes_)) else str(value).strip()


@pytest.fixture(scope="module")
def fixture_root():
    configured = os.environ.get("RAS_PRECIP_NATIVE_FIXTURE_ROOT")
    if not configured:
        pytest.skip("Set RAS_PRECIP_NATIVE_FIXTURE_ROOT to retained native precipitation controls")
    root = Path(configured)
    assert root.is_dir(), f"Configured fixture root unavailable: {root}"
    return root


@pytest.fixture(params=MANIFEST["cases"], ids=lambda case: case["case_id"])
def case(request):
    return request.param


def _table_and_clock(root, case):
    """Parse the known producer records directly, independent of public writers."""
    source = pd.read_csv(root / case["source_csv"])
    lines = (root / case["flow"]).read_text().splitlines()
    starts = [index for index, line in enumerate(lines) if line.startswith("Boundary Location=")]
    selected = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        parts = [field.strip() for field in lines[start].split("=", 1)[1].split(",")]
        if len(parts) >= 8 and parts[5] == case["mesh"] and not parts[7]:
            selected.append(lines[start:end])
    assert len(selected) == 1
    block = selected[0]
    assert "Interval=5MIN" in block
    header = next(index for index, line in enumerate(block) if line.startswith("Precipitation Hydrograph="))
    count = int(block[header].split("=", 1)[1])
    values = []
    for record in block[header + 1:]:
        if "=" in record:
            break
        assert len(record) % 8 == 0
        values.extend(float(record[index:index + 8]) for index in range(0, len(record), 8))
    assert len(values) == count
    np.testing.assert_allclose(values, np.r_[0, source.incremental_depth], rtol=0, atol=1e-12)
    np.testing.assert_allclose(source.cumulative_depth, np.cumsum(source.incremental_depth), rtol=0, atol=1e-12)
    np.testing.assert_allclose(source.hour, np.arange(1, len(source) + 1) / 12, rtol=0, atol=1e-12)
    plan = (root / case["plan"]).read_text().splitlines()
    window = next(line.split("=", 1)[1].split(",") for line in plan if line.startswith("Simulation Date="))
    simulation_start = datetime.strptime(",".join(window[:2]), "%d%b%Y,%H%M")
    flags = [line.split("=", 1)[1].strip() for line in block if line.startswith("Use Fixed Start Time=")]
    assert flags == ["True" if case["fixed_start"] else "False"]
    origin = simulation_start
    if case["fixed_start"]:
        fixed = next(line.split("=", 1)[1] for line in block if line.startswith("Fixed Start Date/Time="))
        origin = datetime.strptime(fixed, "%d%b%Y,%H%M")
        assert (simulation_start - origin).total_seconds() == 300
    return np.asarray(values), origin


def test_pinned_native_result_and_producer_inputs(fixture_root, case):
    for entry in case["files"]:
        path = fixture_root / entry["path"]
        assert path.stat().st_size == entry["bytes"]
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        assert digest.hexdigest() == entry["sha256"], f"Changed fixture: {entry['path']}"


def test_every_physical_native_cumulative_value_matches_source_clock(fixture_root, case):
    values, origin = _table_and_clock(fixture_root, case)
    assert RasPrj.get_project_units(fixture_root / case["project"]) == ("m" if case["depth_units"] == "mm" else "ft")
    with h5py.File(fixture_root / case["result"], "r") as hdf:
        assert case["runtime_version"] in _text(hdf.attrs["File Version"])
        assert _text(hdf.attrs["Units System"]) == ("SI Units" if case["depth_units"] == "mm" else "US Customary")
        stamps = [datetime.strptime(_text(value), "%d%b%Y %H:%M:%S") for value in hdf[f"{BASE}/Time Date Stamp"][:]]
        window = next(line.split("=", 1)[1].split(",") for line in
                      (fixture_root / case["plan"]).read_text().splitlines()
                      if line.startswith("Simulation Date="))
        start = datetime.strptime(",".join(window[:2]), "%d%b%Y,%H%M")
        end = datetime.strptime(",".join(window[2:]), "%d%b%Y,%H%M")
        assert stamps == list(pd.date_range(start, end, freq="5min").to_pydatetime())
        rows = hdf["Geometry/2D Flow Areas/Attributes"][:]
        area = [row for row in rows if _text(row["Name"]) == case["mesh"]]
        assert len(area) == 1
        count = int(area[0]["Cell Count"])
        assert count > 0
        mesh = hdf[f"{BASE}/2D Flow Areas/{case['mesh']}"]
        cumulative = mesh["Cell Cumulative Precipitation Depth"]
        rate = mesh["Cell Precipitation Rate"]
        assert _text(cumulative.attrs["Units"]) == case["depth_units"]
        assert _text(rate.attrs["Units"]) == case["rate_units"]
        curve, rates = cumulative[:, :count], rate[:, :count]
        assert curve.shape[0] == len(stamps) == (5 if case["depth_units"] == "mm" else 7)
        elapsed = np.asarray([(stamp - origin).total_seconds() / 300 for stamp in stamps])
        indexes = np.rint(elapsed).astype(int)
        np.testing.assert_allclose(elapsed, indexes, rtol=0, atol=1e-10)
        assert indexes.min() >= 0 and indexes.max() < len(values)
        expected = np.cumsum(values)[indexes]
        tolerance = 8 * np.finfo(np.float32).eps * max(1, np.max(expected))
        np.testing.assert_allclose(curve, np.broadcast_to(expected[:, None], curve.shape), rtol=0, atol=tolerance)
        np.testing.assert_allclose(np.diff(curve, axis=0), rates[1:] / 12, rtol=0, atol=tolerance)
        # An instantaneous initial rate can be positive while accumulated
        # rainfall remains zero. Never integrate that initial row twice.
        assert np.all(curve[0] == 0)
        assert np.all(rates[0] > 0)


@pytest.mark.parametrize("variable", ["Cell Precipitation Rate", "Cell Cumulative Precipitation Depth"])
@pytest.mark.parametrize("mode", ["eager", "view", "stream"])
def test_public_precip_readers_match_native_values_axes_and_units(fixture_root, case, variable, mode):
    path = fixture_root / case["result"]
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    with h5py.File(path, "r") as hdf:
        row = next(row for row in hdf["Geometry/2D Flow Areas/Attributes"][:] if _text(row["Name"]) == case["mesh"])
        count = int(row["Cell Count"])
        ds = hdf[f"{BASE}/2D Flow Areas/{case['mesh']}/{variable}"]
        expected, units = ds[:, :count], _text(ds.attrs["Units"])
        times = np.asarray([
            np.datetime64(datetime.strptime(_text(value), "%d%b%Y %H:%M:%S"), "ns")
            for value in hdf[f"{BASE}/Time Date Stamp"][:]
        ])
    if mode == "stream":
        batches = list(HdfResultsMesh.iter_mesh_timeseries(path, case["mesh"], variable, batch_size=2))
        actual = xr.concat(batches, dim="time")
    else:
        result = HdfResultsMesh.get_mesh_timeseries(
            path, case["mesh"], variable, truncate=False,
            return_type="view" if mode == "view" else "xarray",
        )
        actual = result.to_xarray() if mode == "view" else result
    assert actual.dims == ("time", "cell_id")
    assert actual.dtype == expected.dtype
    assert actual.attrs["units"] == units
    np.testing.assert_array_equal(actual.values, expected)
    np.testing.assert_array_equal(actual.time.values, times)
    np.testing.assert_array_equal(actual.cell_id.values, np.arange(count))
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before
