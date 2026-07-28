"""Tests for deterministic hydraulic product contracts."""

from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander import HdfResultsMesh, HdfResultsProducts


BASE = (
    "Results/Unsteady/Output/Output Blocks/Base Output/"
    "Unsteady Time Series"
)


def _write_product_hdf(
    path: Path,
    *,
    completed: bool = True,
    velocity_time_count: int = 2,
) -> None:
    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = CRS.from_epsg(3451).to_wkt()
        hdf_file.attrs["Units System"] = "English"
        geometry = hdf_file.create_group("Geometry")
        geometry.attrs["SI Units"] = False
        event_conditions = hdf_file.create_group("Event Conditions")
        event_conditions.attrs["Completed Successfully"] = (
            b"True" if completed else b"False"
        )
        attributes = np.asarray(
            [(b"Mesh", 2)],
            dtype=[("Name", "S16"), ("Cell Count", "i4")],
        )
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=attributes,
        )
        hdf_file.create_dataset(
            f"{BASE}/Time Date Stamp (ms)",
            data=np.asarray(
                [
                    b"18Sep2019 13:00:00.000",
                    b"18Sep2019 14:00:00.000",
                ],
                dtype="S24",
            ),
        )
        hdf_file.create_dataset(
            f"{BASE}/2D Flow Areas/Mesh/Water Surface",
            data=np.asarray([[10.0, 20.0], [12.0, 21.0]], dtype=np.float32),
        )
        hdf_file.create_dataset(
            f"{BASE}/2D Flow Areas/Mesh/Face Velocity",
            data=np.ones((velocity_time_count, 3), dtype=np.float32),
        )


def test_inspect_result_requires_completion_marker(tmp_path):
    hdf_path = tmp_path / "incomplete.p01.hdf"
    _write_product_hdf(hdf_path, completed=False)

    with pytest.raises(ValueError, match="Completed Successfully"):
        HdfResultsProducts.inspect_result(hdf_path)


def test_inspect_result_rejects_inconsistent_required_time_axis(tmp_path):
    hdf_path = tmp_path / "mismatch.p01.hdf"
    _write_product_hdf(hdf_path, velocity_time_count=1)

    with pytest.raises(ValueError, match="Time-axis mismatch"):
        HdfResultsProducts.inspect_result(hdf_path)


def test_inspect_result_reports_stac_ready_metadata(tmp_path):
    hdf_path = tmp_path / "complete.p01.hdf"
    _write_product_hdf(hdf_path)

    result = HdfResultsProducts.inspect_result(hdf_path)

    assert result["completed_successfully"] is True
    assert result["time_axis_consistent"] is True
    assert result["time"] == {
        "start": "2019-09-18T13:00:00",
        "end": "2019-09-18T14:00:00",
        "count": 2,
        "regular": True,
        "interval_seconds": 3600.0,
    }
    assert result["mesh_names"] == ["Mesh"]
    assert result["crs"] == "EPSG:3451"
    assert result["unit_system"] == "US Customary"
    assert result["depth_units"] == "ft"


def test_maximum_depth_falls_back_to_wse_minus_minimum_elevation(tmp_path):
    hdf_path = tmp_path / "depth-fallback.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = CRS.from_epsg(3451).to_wkt()
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.asarray(
                [(b"Mesh", 2)],
                dtype=[("Name", "S16"), ("Cell Count", "i4")],
            ),
        )
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Mesh/Cells Center Coordinate",
            data=np.asarray([[0.0, 0.0], [1.0, 1.0]]),
        )
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Mesh/Cells Minimum Elevation",
            data=np.asarray([8.0, 20.0], dtype=np.float32),
        )
        hdf_file.create_dataset(
            f"{BASE}/2D Flow Areas/Mesh/Water Surface",
            data=np.asarray([[10.0, 19.0], [12.0, 21.0]], dtype=np.float32),
        )

    result = HdfResultsMesh.get_mesh_max_depth(hdf_path)

    assert result["maximum_depth"].tolist() == pytest.approx([4.0, 1.0])
    assert result.crs.to_epsg() == 3451


def test_boundary_metadata_does_not_overwrite_hydrograph_variables(tmp_path):
    hdf_path = tmp_path / "boundaries.p01.hdf"
    with h5py.File(hdf_path, "w") as hdf_file:
        plan_information = hdf_file.create_group(
            "Plan Data/Plan Information"
        )
        plan_information.attrs["Simulation Start Time"] = (
            b"18Sep2019 13:00:00"
        )
        hdf_file.create_dataset(
            f"{BASE}/Time",
            data=np.asarray([0.0, 1.0 / 24.0]),
        )
        boundary = hdf_file.create_dataset(
            f"{BASE}/Boundary Conditions/Inflow",
            data=np.asarray([[10.0, 100.0], [11.0, 120.0]]),
        )
        boundary.attrs["Columns"] = np.asarray([b"Stage", b"Flow"])
        boundary.attrs["Stage"] = b"ft"
        boundary.attrs["Flow"] = b"cfs"
        boundary.attrs["2D Area"] = b"Mesh"

    dataset = HdfResultsMesh.get_boundary_conditions_timeseries(hdf_path)

    assert {"stage", "flow"} <= set(dataset.data_vars)
    assert dataset["flow"].values.tolist() == [[100.0], [120.0]]
    assert dataset["stage"].values.tolist() == [[10.0], [11.0]]
    assert dataset["flow_units"].values.tolist() == ["cfs"]
    assert dataset["stage_units"].values.tolist() == ["ft"]
    assert dataset["area_2d"].values.tolist() == ["Mesh"]


def test_product_filenames_and_keys_are_stable():
    assert HdfResultsProducts.FILENAMES == {
        "maximum-wse": "maximum-wse.tif",
        "maximum-depth": "maximum-depth.tif",
        "maximum-velocity": "maximum-velocity.tif",
        "hydraulic-hydrographs": "hydraulic-hydrographs.parquet",
        "result-metadata": "result-metadata.json",
        "numerical-qaqc": "numerical-qaqc.json",
        "result-footprint": "result-footprint.geojson",
        "preview": "maximum-depth-preview.png",
    }
