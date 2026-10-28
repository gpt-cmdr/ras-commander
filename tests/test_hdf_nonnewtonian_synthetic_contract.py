"""Public contract for non-Newtonian mesh series (synthetic h5py boundary fixture).

The fixture mirrors the stored schema that native HEC-RAS 6.6 and 7.0.1 Bingham
runs write for three optional rheology outputs: ``Face Yield Stress`` and
``Face Viscous Stress`` are ``Location=Faces`` series whose width equals the
face count; ``Face Mixture Dynamic Viscosity`` is also labelled
``Location=Faces``/``Columns=Faces`` but its width equals the stored cell count
(physical plus ghost cells). No producer contract establishes that dataset's
physical domain or unit meaning, so the typed readers must keep refusing it and
the raw diagnostic must never relabel it. Values here are synthetic; they are
not model results and say nothing about hydraulic convergence.

Authentic retained-file checks live in test_hdf_nonnewtonian_native_contract.py
and test_hdf_followup_native_contract.py (external fixtures, skipped by default).
"""

import h5py
import numpy as np
import pytest

xr = pytest.importorskip("xarray")

from ras_commander import HdfResultsMesh


BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
AREA = "DebrisArea"
GEOMETRY = f"Geometry/2D Flow Areas/{AREA}"
SERIES = f"{BASE}/2D Flow Areas/{AREA}"
ROWS, PHYSICAL_CELLS, STORED_CELLS, FACES = 5, 4, 6, 9
STRESSES = ("Face Yield Stress", "Face Viscous Stress")
VISCOSITY = "Face Mixture Dynamic Viscosity"
MODES = ("eager", "lazy", "stream")
REFUSAL = "Qualified series domain contradicts geometry count"


def _attrs(name, units):
    return {
        "Can Interpolate": b"True", "Can Plot": b"True", "Columns": b"Faces",
        "Coverage": b"Wet", "Location": b"Faces", "Maximum Value of Data Set": np.float32(np.nan),
        "Name": name.encode(), "Orientation": b"Scalar", "Rows": b"Times", "Units": units.encode(),
    }


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "rheology.p01.hdf"
    rng = np.random.default_rng(465)
    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Version"] = b"HEC-RAS synthetic boundary fixture"
        hdf.attrs["Units System"] = b"US Customary"
        hdf.require_group("Plan Data/Plan Information").attrs[
            "Simulation Start Time"
        ] = "01Jan2000 00:00:00"
        hdf.create_dataset(f"{BASE}/Time", data=np.arange(ROWS) / 1440.0)
        hdf.create_dataset(
            f"{BASE}/Time Date Stamp (ms)",
            data=np.array([f"01Jan2000 00:0{minute}:00.000".encode() for minute in range(ROWS)]),
        )
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array([(AREA.encode(), PHYSICAL_CELLS)], dtype=[("Name", "S16"), ("Cell Count", "i4")]),
        )
        hdf.create_dataset(f"{GEOMETRY}/Cells Center Coordinate", data=np.zeros((STORED_CELLS, 2)))
        hdf.create_dataset(f"{GEOMETRY}/Faces FacePoint Indexes", data=np.zeros((FACES, 2), dtype=np.int32))
        group = hdf.require_group(SERIES)
        stresses = {
            "Face Yield Stress": np.full((ROWS, FACES), 14.619806, dtype=np.float32),
            # Signed values must survive unchanged.
            "Face Viscous Stress": rng.uniform(-50, 50, (ROWS, FACES)).astype(np.float32),
        }
        for name, values in stresses.items():
            dataset = group.create_dataset(name, data=values)
            dataset.attrs.update(_attrs(name.removeprefix("Face "), "lb/ft^2"))
        dataset = group.create_dataset(
            VISCOSITY, data=np.full((ROWS, STORED_CELLS), 4788.0249, dtype=np.float32)
        )
        dataset.attrs.update(_attrs("Mixture Dynamic Viscosity", "lb/ft^2*s"))
    return path


def _fingerprint(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _read(path, name, mode, **kwargs):
    if mode == "eager":
        return HdfResultsMesh.get_mesh_timeseries(path, AREA, name, truncate=False, **kwargs)
    if mode == "lazy":
        return HdfResultsMesh.get_mesh_timeseries(
            path, AREA, name, truncate=False, return_type="view", **kwargs
        ).to_xarray()
    return xr.concat(list(HdfResultsMesh.iter_mesh_timeseries(path, AREA, name, batch_size=2, **kwargs)), dim="time")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", STRESSES)
def test_stress_series_read_exactly_as_faces(source, name, mode):
    before = _fingerprint(source)
    with h5py.File(source, "r") as hdf:
        expected = hdf[f"{SERIES}/{name}"][:]
    result = _read(source, name, mode)
    assert result.dims == ("time", "face_id")
    assert result.dtype == expected.dtype
    assert result.values.tobytes() == expected.tobytes()
    assert result.attrs["units"] == "lb/ft^2"
    np.testing.assert_array_equal(result.face_id.values, np.arange(FACES))
    np.testing.assert_array_equal(
        result.time.values,
        np.datetime64("2000-01-01T00:00", "ns") + np.arange(ROWS) * np.timedelta64(1, "m"),
    )
    assert "is_ghost_cell" not in result.coords
    assert _fingerprint(source) == before


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kwargs", [
    {}, {"include_ghost_cells": True}, {"spatial_selection": slice(0, 2)}, {"time_selection": 0},
])
def test_viscosity_label_width_contradiction_is_refused(source, mode, kwargs):
    before = _fingerprint(source)
    with pytest.raises(ValueError, match=REFUSAL):
        _read(source, VISCOSITY, mode, **kwargs)
    assert _fingerprint(source) == before


def test_face_discovery_keeps_stresses_and_skips_viscosity(source, caplog):
    result = HdfResultsMesh.get_mesh_faces_timeseries(source, AREA, truncate=False)
    assert set(result.data_vars) == {"face_yield_stress", "face_viscous_stress"}
    assert REFUSAL in caplog.text and VISCOSITY in caplog.text
    cells = HdfResultsMesh.get_mesh_cells_timeseries(source, AREA, truncate=False)
    assert all(
        VISCOSITY not in dataset.data_vars and "face_mixture_dynamic_viscosity" not in dataset.data_vars
        for dataset in cells.values()
    )


def test_raw_diagnostic_reports_viscosity_without_relabelling(source):
    before = _fingerprint(source)
    report = HdfResultsMesh.inspect_mesh_series_raw(source, AREA, VISCOSITY, include_values=True)
    assert report["dataset_path"] == f"/{SERIES}/{VISCOSITY}"
    assert report["file_version"] == "HEC-RAS synthetic boundary fixture"
    assert report["shape"] == (ROWS, STORED_CELLS)
    assert report["dtype"] == "float32"
    assert report["axes"] == ("raw_row", "raw_column")
    assert report["stored_location"] == "Faces"
    assert report["stored_units"] == "lb/ft^2*s"
    assert report["attrs"]["Columns"] == "Faces"
    assert report["attrs"]["Name"] == "Mixture Dynamic Viscosity"
    assert np.isnan(report["attrs"]["Maximum Value of Data Set"])
    assert report["time_axis"] == {"path": f"/{BASE}/Time", "rows": ROWS, "matches_rows": True}
    assert report["geometry_counts"] == {
        "stored_cells": STORED_CELLS, "physical_cells": PHYSICAL_CELLS, "faces": FACES,
    }
    assert report["typed_status"] == "refused"
    assert report["typed_domain"] is None
    assert REFUSAL in report["refusal_reason"]
    assert report["physical_domain"] == "unqualified"
    assert report["units_interpretation"] == "unqualified"
    with h5py.File(source, "r") as hdf:
        stored = hdf[f"{SERIES}/{VISCOSITY}"][:]
    assert report["values"].dtype == stored.dtype
    assert report["values"].tobytes() == stored.tobytes()
    # The diagnostic returns no cell/face identifiers or timestamps.
    assert not {"cell_id", "face_id", "time", "is_ghost_cell"} & set(report)
    assert _fingerprint(source) == before


def test_raw_diagnostic_keeps_qualified_stress_unqualified_physically(source):
    report = HdfResultsMesh.inspect_mesh_series_raw(source, AREA, "Face Yield Stress")
    assert report["typed_status"] == "qualified"
    assert report["typed_domain"] == "face_id"
    assert report["refusal_reason"] is None
    assert report["physical_domain"] == report["units_interpretation"] == "unqualified"
    assert report["values"] is None
    assert report["shape"] == (ROWS, FACES)


def test_raw_diagnostic_requires_the_exact_stored_dataset(source):
    with pytest.raises(ValueError, match="not found"):
        HdfResultsMesh.inspect_mesh_series_raw(source, AREA, "Face Mixture Viscosity")
    with pytest.raises(ValueError, match="not found"):
        HdfResultsMesh.inspect_mesh_series_raw(source, "Missing Area", VISCOSITY)


def test_raw_diagnostic_reports_row_mismatch_without_borrowing_time(source):
    with h5py.File(source, "r+") as hdf:
        del hdf[f"{SERIES}/{VISCOSITY}"]
        dataset = hdf.create_dataset(f"{SERIES}/{VISCOSITY}", data=np.zeros((1, STORED_CELLS), np.float32))
        dataset.attrs.update(_attrs("Mixture Dynamic Viscosity", "lb/ft^2*s"))
    report = HdfResultsMesh.inspect_mesh_series_raw(source, AREA, VISCOSITY, include_values=True)
    assert report["time_axis"]["matches_rows"] is False
    assert report["typed_status"] == "refused"
    assert "Time axis" in report["refusal_reason"]
    assert report["values"].shape == (1, STORED_CELLS)
