"""Legacy 2D ``Log Hydraulics`` diagnostic table (HEC-RAS 6.0-6.3.x).

All fixtures are synthetic temporary HDFs that copy the producer's dataset
layout and ``Column N`` label strings; they are not HEC-RAS output.
"""

import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh as Mesh


BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
AREA = "Area"
SERIES = f"{BASE}/2D Flow Areas/{AREA}"
LOG = f"{SERIES}/Log Hydraulics"

US_LABELS = [
    "Total iterations",
    "Outer-loop iterations",
    "Inner-loop iterations",
    "Outer-loop max water surface correction (ft)",
    "Cell location of max water surface correction",
    "Inner-loop max volume residual divided by wet area (ft)",
    "Cell location of max volume residual divided by wet area",
    "Total volume balance (ft^3)",
    "Max water surface elevation (ft)",
    "Min water surface elevation (m)",  # producer has no "(ft)" variant
]
SI_LABELS = [
    label.replace("(ft^3)", "(m^3)").replace("(ft)", "(m)")
    if i in (3, 7, 8) else label
    for i, label in enumerate(US_LABELS)
]
FIELDS = [
    "total_iterations",
    "outer_loop_iterations",
    "inner_loop_iterations",
    "outer_loop_max_water_surface_correction",
    "max_water_surface_correction_cell_location",
    "inner_loop_max_volume_residual_per_wet_area",
    "max_volume_residual_cell_location",
    "total_volume_balance",
    "max_water_surface_elevation",
    "min_water_surface_elevation",
]
VALUES = np.array([
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [2, 0, 2, 0, 0, 4e-6, 7, 0, 12.5, 3.25],
    [5, 1, 4, 0.01, 3, 2e-3, 1, -1.5, 12.75, 3.25],
], dtype=np.float32)


def write_source(path, *, version="HEC-RAS 6.3.1 September 2022",
                 units="US Customary", labels=US_LABELS, values=VALUES):
    with h5py.File(path, "w") as hdf:
        if version is not None:
            hdf.attrs["File Version"] = np.bytes_(version)
        if units is not None:
            hdf.attrs["Units System"] = np.bytes_(units)
        time = hdf.create_dataset(f"{BASE}/Time", data=np.array([0.0, 0.25, 0.5]))
        time.attrs["Time"] = np.bytes_("days")
        hdf.create_dataset(
            f"{BASE}/Time Date Stamp (ms)",
            data=np.array([b"01JAN2030 00:00:00:000", b"01JAN2030 06:00:00:000",
                           b"01JAN2030 12:00:00:000"]),
        )
        hdf.create_dataset(
            f"{BASE}/Time Date Stamp",
            data=np.array([b"01JAN2030 00:00:00", b"01JAN2030 06:00:00", b"01JAN2030 12:00:00"]),
        )
        log = hdf.create_dataset(LOG, data=values)
        log.attrs["Can Plot"] = np.bytes_("False")
        for index, label in enumerate(labels):
            log.attrs[f"Column {index}"] = np.bytes_(label)
    return path


@pytest.fixture
def source(tmp_path):
    return write_source(tmp_path / "log.p01.hdf")


def test_reads_named_fields_with_time_provenance(source):
    frame = Mesh.get_mesh_log_hydraulics(source, AREA)
    assert list(frame.columns) == ["time_index", "time", "timestamp", *FIELDS]
    assert frame["time_index"].tolist() == [0, 1, 2]
    assert frame["time"].tolist() == [0.0, 0.25, 0.5]
    assert frame["timestamp"].tolist() == list(pd.to_datetime(
        ["2030-01-01 00:00", "2030-01-01 06:00", "2030-01-01 12:00"]))
    for index, field in enumerate(FIELDS):
        assert frame[field].dtype == np.float32
        assert frame[field].to_numpy().tobytes() == VALUES[:, index].tobytes()
    attrs = frame.attrs
    assert attrs["diagnostic"] is True
    assert attrs["dataset_path"] == "/" + LOG
    assert attrs["clock"] == "Base Output"
    assert attrs["time_source"] == f"/{BASE}/Time"
    assert attrs["timestamp_source"] == f"/{BASE}/Time Date Stamp (ms)"
    assert attrs["time_units"] == "days"
    assert attrs["file_version"] == "HEC-RAS 6.3.1 September 2022"
    assert attrs["version_bounds"] == "HEC-RAS >=6.0,<6.4"
    assert [c["label"] for c in attrs["columns"]] == US_LABELS
    assert [c["column_index"] for c in attrs["columns"]] == list(range(10))
    # No column is ever relabelled as a cell or face identifier.
    assert not {"cell_id", "face_id"} & set(frame.columns)


def test_units_only_from_unit_system_specific_labels(source):
    statuses = {c["field"]: (c["units"], c["units_status"])
                for c in Mesh.get_mesh_log_hydraulics(source, AREA).attrs["columns"]}
    assert statuses == {
        "total_iterations": ("count", "dimensionless_count"),
        "outer_loop_iterations": ("count", "dimensionless_count"),
        "inner_loop_iterations": ("count", "dimensionless_count"),
        "outer_loop_max_water_surface_correction": ("ft", "label_matches_units_system"),
        "max_water_surface_correction_cell_location": (None, "cell_location_index_base_unqualified"),
        "inner_loop_max_volume_residual_per_wet_area": (None, "fixed_producer_label_not_unit_evidence"),
        "max_volume_residual_cell_location": (None, "cell_location_index_base_unqualified"),
        "total_volume_balance": ("ft^3", "label_matches_units_system"),
        "max_water_surface_elevation": ("ft", "label_matches_units_system"),
        "min_water_surface_elevation": (None, "fixed_producer_label_not_unit_evidence"),
    }


def test_si_labels_and_conflicting_or_missing_unit_system(tmp_path):
    si = Mesh.get_mesh_log_hydraulics(
        write_source(tmp_path / "si.p01.hdf", units="SI Units", labels=SI_LABELS), AREA)
    assert {k: si.attrs["units"][k] for k in (FIELDS[3], FIELDS[7], FIELDS[8])} == {
        FIELDS[3]: "m", FIELDS[7]: "m^3", FIELDS[8]: "m"}
    assert si.attrs["units"][FIELDS[5]] is None

    conflict = Mesh.get_mesh_log_hydraulics(
        write_source(tmp_path / "conflict.p01.hdf", units="US Customary", labels=SI_LABELS), AREA)
    assert conflict.attrs["units"][FIELDS[8]] is None
    assert conflict.attrs["columns"][8]["units_status"] == "label_conflicts_units_system"
    assert conflict[FIELDS[8]].to_numpy().tobytes() == VALUES[:, 8].tobytes()  # never converted

    unknown = Mesh.get_mesh_log_hydraulics(
        write_source(tmp_path / "nounits.p01.hdf", units=None), AREA)
    assert unknown.attrs["columns"][3]["units_status"] == "units_system_unavailable"


def test_open_handle_and_second_based_timestamp_fallback(source):
    with h5py.File(source, "r+") as hdf:
        del hdf[f"{BASE}/Time Date Stamp (ms)"]
    with h5py.File(source, "r") as hdf:
        frame = Mesh.get_mesh_log_hydraulics(hdf, AREA)
    assert frame.attrs["timestamp_source"] == f"/{BASE}/Time Date Stamp"
    assert frame["timestamp"].iloc[-1] == pd.Timestamp("2030-01-01 12:00")


@pytest.mark.parametrize("version", ["HEC-RAS 6.0.0 June 2021", "HEC-RAS 6.3 Beta 2 Development"])
def test_accepts_versions_inside_producer_bounds(tmp_path, version):
    frame = Mesh.get_mesh_log_hydraulics(write_source(tmp_path / "v.p01.hdf", version=version), AREA)
    assert len(frame) == 3


@pytest.mark.parametrize("version", [
    None, "", "HEC-RAS 5.0.7 March 2019", "HEC-RAS 6.4.1 June 2023",
    "HEC-RAS 6.6 September 2024", "HEC-RAS 7.0 April 2026", "HEC-RAS 6.30",
])
def test_refuses_versions_outside_producer_bounds(tmp_path, version):
    path = write_source(tmp_path / "v.p01.hdf", version=version)
    with pytest.raises(ValueError, match="qualified only for HEC-RAS 6.0-6.3.x"):
        Mesh.get_mesh_log_hydraulics(path, AREA)


def _relabel(labels, index, value):
    labels = list(labels)
    labels[index] = value
    return labels


@pytest.mark.parametrize("labels,values,match", [
    (_relabel(US_LABELS, 9, "Min water surface elevation (ft)"), VALUES, "Column 9 label"),
    (_relabel(US_LABELS, 4, "Cell"), VALUES, "Column 4 label"),
    (US_LABELS[:9], VALUES, "requires 10 columns"),
    (US_LABELS[:9], VALUES[:, :9], "requires 10 columns"),
    (US_LABELS + ["Extra"], np.hstack([VALUES, VALUES[:, :1]]), "requires 10 columns"),
    (list(reversed(US_LABELS)), VALUES, "Column 0 label"),
])
def test_refuses_unqualified_labels_or_widths(tmp_path, labels, values, match):
    path = write_source(tmp_path / "bad.p01.hdf", labels=labels, values=values)
    with pytest.raises(ValueError, match=match):
        Mesh.get_mesh_log_hydraulics(path, AREA)


@pytest.mark.parametrize("mutation,match", [
    ("location", "stored Location"),
    ("rank1", "rank-2 numeric"),
    ("time_rows", "Base Output Time axis"),
    ("stamp_rows", "Time Date Stamp"),
    ("no_stamps", "No Base Output Time Date Stamp"),
    ("no_time", "Base Output Time axis"),
])
def test_refuses_location_shape_and_clock_mismatch(source, mutation, match):
    with h5py.File(source, "r+") as hdf:
        if mutation == "location":
            hdf[LOG].attrs["Location"] = np.bytes_("Cells")
        elif mutation == "rank1":
            del hdf[LOG]
            hdf.create_dataset(LOG, data=VALUES[:, 0])
        elif mutation == "time_rows":
            del hdf[f"{BASE}/Time"]
            hdf.create_dataset(f"{BASE}/Time", data=np.array([0.0, 0.25]))
        elif mutation == "stamp_rows":
            del hdf[f"{BASE}/Time Date Stamp (ms)"]
            hdf.create_dataset(f"{BASE}/Time Date Stamp (ms)", data=np.array([b"01JAN2030 00:00:00:000"]))
        elif mutation == "no_stamps":
            del hdf[f"{BASE}/Time Date Stamp (ms)"]
            del hdf[f"{BASE}/Time Date Stamp"]
        elif mutation == "no_time":
            del hdf[f"{BASE}/Time"]
    with pytest.raises(ValueError, match=match):
        Mesh.get_mesh_log_hydraulics(source, AREA)


def test_missing_dataset_raises_key_error(source):
    with pytest.raises(KeyError, match="No Log Hydraulics"):
        Mesh.get_mesh_log_hydraulics(source, "Other Area")


def _read_series(path, mode):
    if mode == "eager":
        return Mesh.get_mesh_timeseries(path, AREA, "Log Hydraulics", truncate=False)
    if mode == "lazy":
        return Mesh.get_mesh_timeseries(
            path, AREA, "Log Hydraulics", truncate=False, return_type="view").to_xarray()
    return list(Mesh.iter_mesh_timeseries(path, AREA, "Log Hydraulics", batch_size=2))


@pytest.mark.synthetic_hdf_layout
@pytest.mark.parametrize("mode", ["eager", "lazy", "stream"])
def test_mesh_timeseries_reader_still_refuses_log_hydraulics(source, mode):
    """The ten fields must never become a cell or face domain."""
    with pytest.raises(ValueError, match="no qualified legacy schema"):
        _read_series(source, mode)
    with h5py.File(source, "r") as hdf:
        assert "Log Hydraulics" not in Mesh._discover_mesh_series(hdf, AREA)


def test_retained_authentic_log_hydraulics():
    """Private qualification; set RAS_LOG_HYDRAULICS_HDF to a retained 6.0-6.3.x plan HDF."""
    value = os.environ.get("RAS_LOG_HYDRAULICS_HDF")
    if not value:
        pytest.skip("Set RAS_LOG_HYDRAULICS_HDF to a retained authentic plan HDF")
    path = Path(value)
    before = path.stat()
    with h5py.File(path, "r") as hdf:
        areas = hdf[f"{BASE}/2D Flow Areas"]
        meshes = [name for name in areas if "Log Hydraulics" in areas[name]]
        assert meshes
        time_count = len(hdf[f"{BASE}/Time"])
    for mesh in meshes:
        frame = Mesh.get_mesh_log_hydraulics(path, mesh)
        assert list(frame.columns)[3:] == FIELDS
        assert len(frame) == time_count
        with h5py.File(path, "r") as hdf:
            stored = hdf[f"{BASE}/2D Flow Areas/{mesh}/Log Hydraulics"][()]
        assert np.column_stack([frame[f].to_numpy() for f in FIELDS]).tobytes() == stored.tobytes()
        with pytest.raises(ValueError, match="no qualified legacy schema"):
            Mesh.get_mesh_timeseries(path, mesh, "Log Hydraulics")
    assert (path.stat().st_size, path.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns)
