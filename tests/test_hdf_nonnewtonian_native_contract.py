"""Read-only contracts from retained HEC-RAS 7.0.1 Ether Hollow output.

Set RAS_NN_FIXTURE_ROOT to the retained ``full_2core`` directory. These tests
never execute HEC-RAS or manufacture/modify HDF data. Native completion does
not establish hydraulic convergence: the fixtures retain iteration warnings.
Viscosity's contradictory native label/width must remain an explicit refusal;
its raw diagnostic must preserve stored identity without relabelling.
"""

from datetime import datetime
import os
from pathlib import Path

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
pytest.importorskip("xarray")

from ras_commander import HdfResultsMesh


pytestmark = [pytest.mark.integration, pytest.mark.offline_evidence]

MESH = "DebrisFlowArea"
TIME_BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
SERIES = f"{TIME_BASE}/2D Flow Areas/{MESH}"
GEOMETRY = f"Geometry/2D Flow Areas/{MESH}"
VARIANTS = ("bingham_ty700", "bingham_ty2500")
STRESSES = ("Face Yield Stress", "Face Viscous Stress")
VISCOSITY = "Face Mixture Dynamic Viscosity"
MODES = ("eager", "view", "stream")


def _text(value):
    return value.decode("utf-8") if isinstance(value, (bytes, np.bytes_)) else str(value)


@pytest.fixture(scope="module")
def native_paths():
    configured = os.environ.get("RAS_NN_FIXTURE_ROOT")
    if not configured:
        pytest.skip("Set RAS_NN_FIXTURE_ROOT to the retained full_2core directory")
    root = Path(configured)
    paths = {
        variant: root / variant / f"result_{variant}.p01.hdf"
        for variant in ("clear", *VARIANTS)
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        pytest.skip(f"External non-Newtonian fixtures unavailable: {missing}")
    return paths


def _oracle(path, variable):
    """Read expected arrays, axes and labels directly, independently of readers."""
    with h5py.File(path, "r") as hdf:
        assert "7.0.1" in _text(hdf.attrs["File Version"])
        assert _text(hdf.attrs["Units System"]) == "US Customary"
        dataset = hdf[f"{SERIES}/{variable}"]
        values = dataset[:]
        attrs = {key: _text(value) for key, value in dataset.attrs.items()}
        face_count = hdf[f"{GEOMETRY}/Faces Cell Indexes"].shape[0]
        cell_count = hdf[f"{GEOMETRY}/Cells Center Coordinate"].shape[0]
        stamps = hdf[f"{TIME_BASE}/Time Date Stamp (ms)"][:]
        times = np.asarray([
            np.datetime64(datetime.strptime(_text(stamp), "%d%b%Y %H:%M:%S:%f"))
            for stamp in stamps
        ], dtype="datetime64[ns]")
    assert face_count == 20797
    assert cell_count == 10647
    assert len(times) == 361
    assert times[0] == np.datetime64("2000-01-01T00:00:00", "ns")
    assert times[-1] == np.datetime64("2000-01-01T06:00:00", "ns")
    np.testing.assert_array_equal(np.diff(times), np.timedelta64(60, "s"))
    return values, attrs, times, np.arange(face_count), cell_count


def _assert_face_read(actual, expected, times, face_ids, units):
    assert actual.dims == ("time", "face_id")
    assert actual.dtype == expected.dtype
    assert actual.attrs["units"] == units
    assert actual.attrs["mesh_name"] == MESH
    np.testing.assert_array_equal(actual.face_id.values, face_ids)
    np.testing.assert_array_equal(actual.time.values, times)
    np.testing.assert_array_equal(actual.values, expected)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("variable", STRESSES)
@pytest.mark.parametrize("mode", MODES)
def test_native_stress_values_axes_units_exact(native_paths, variant, variable, mode):
    path = native_paths[variant]
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    values, attrs, times, face_ids, _ = _oracle(path, variable)
    assert values.shape == (361, 20797)
    assert attrs["Location"] == attrs["Columns"] == "Faces"
    assert attrs["Rows"] == "Times"
    assert attrs["Orientation"] == "Scalar"
    assert attrs["Units"] == "lb/ft^2"

    if mode == "stream":
        offset = batches = 0
        for batch in HdfResultsMesh.iter_mesh_timeseries(
            path, MESH, variable, batch_size=64
        ):
            end = offset + batch.shape[0]
            assert 0 < batch.shape[0] <= 64
            _assert_face_read(batch, values[offset:end], times[offset:end], face_ids, attrs["Units"])
            offset, batches = end, batches + 1
        assert offset == len(times)
        assert batches == 6
    else:
        result = HdfResultsMesh.get_mesh_timeseries(
            path, MESH, variable, truncate=False,
            return_type="view" if mode == "view" else "xarray",
        )
        actual = result.to_xarray() if mode == "view" else result
        _assert_face_read(actual, values, times, face_ids, attrs["Units"])
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("mode", MODES)
def test_native_viscosity_contradiction_is_refused(native_paths, variant, mode):
    path = native_paths[variant]
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    values, attrs, times, face_ids, cell_count = _oracle(path, VISCOSITY)
    # These are independent observations, not authority to reinterpret as cells.
    assert values.shape == (len(times), cell_count) == (361, 10647)
    assert values.shape[1] != len(face_ids)
    assert attrs["Location"] == attrs["Columns"] == "Faces"
    assert attrs["Rows"] == "Times"
    assert attrs["Name"] == "Mixture Dynamic Viscosity"
    assert attrs["Orientation"] == "Scalar"
    assert attrs["Coverage"] == "Wet"
    assert attrs["Units"] == "lb/ft^2*s"
    assert np.all(values == np.float32(4788.02490234375))
    with pytest.raises(ValueError, match="Qualified series domain contradicts geometry count"):
        if mode == "stream":
            list(HdfResultsMesh.iter_mesh_timeseries(path, MESH, VISCOSITY, batch_size=64))
        else:
            result = HdfResultsMesh.get_mesh_timeseries(
                path, MESH, VISCOSITY, truncate=False,
                return_type="view" if mode == "view" else "xarray",
            )
            if mode == "view":
                result.to_numpy()
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before


def test_clear_water_control_has_no_rheology_datasets(native_paths):
    path = native_paths["clear"]
    with h5py.File(path, "r") as hdf:
        assert all(variable not in hdf[SERIES] for variable in (*STRESSES, VISCOSITY))


@pytest.mark.parametrize("variant", VARIANTS)
def test_native_viscosity_raw_diagnostic_preserves_stored_identity(native_paths, variant):
    path = native_paths[variant]
    before = (path.stat().st_size, path.stat().st_mtime_ns)
    values, attrs, times, face_ids, cell_count = _oracle(path, VISCOSITY)
    report = HdfResultsMesh.inspect_mesh_series_raw(path, MESH, VISCOSITY, include_values=True)
    assert report["dataset_path"] == f"/{SERIES}/{VISCOSITY}"
    assert "7.0.1" in report["file_version"]
    assert report["shape"] == values.shape == (len(times), cell_count)
    assert report["axes"] == ("raw_row", "raw_column")
    assert set(report["attrs"]) == set(attrs)
    # The oracle stringifies attributes; the stored NaN maximum stays numeric.
    assert all(report["attrs"][key] == value for key, value in attrs.items()
               if key != "Maximum Value of Data Set")
    assert report["stored_location"] == "Faces" and report["stored_units"] == "lb/ft^2*s"
    assert report["time_axis"]["rows"] == len(times) and report["time_axis"]["matches_rows"]
    assert report["geometry_counts"] == {
        "stored_cells": cell_count, "physical_cells": 10201, "faces": len(face_ids),
    }
    assert report["typed_status"] == "refused" and report["typed_domain"] is None
    assert "Qualified series domain contradicts geometry count" in report["refusal_reason"]
    assert report["physical_domain"] == report["units_interpretation"] == "unqualified"
    assert report["values"].tobytes() == values.tobytes()
    assert (path.stat().st_size, path.stat().st_mtime_ns) == before
