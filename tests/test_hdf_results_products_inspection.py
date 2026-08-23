"""C06a inspection tests.

The small HDFs created here are synthetic pytest artifacts, not HEC-RAS model
output. The opt-in integration test only reads pre-existing producer HDFs and
verifies their bytes are unchanged.
"""

import hashlib
import logging
import os
from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander import HdfResultsProducts

SERIES_BASE = (
    "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
)
SUMMARY_BASE = (
    "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_inspection_hdf(
    path: Path,
    *,
    completion_attribute: bool | None = True,
    complete_messages: bool = True,
    stored_depth: bool = False,
    velocity_time_count: int = 2,
    plain_time_offset_hours: int = 0,
    contradictory_units: bool = False,
) -> None:
    """Write a minimal synthetic contract fixture in a pytest temp folder."""
    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = CRS.from_epsg(3451).to_wkt()
        hdf_file.attrs["Units System"] = "US Customary"
        hdf_file.attrs["File Version"] = "synthetic-test-fixture"
        geometry = hdf_file.create_group("Geometry")
        geometry.attrs["SI Units"] = contradictory_units
        if completion_attribute is not None:
            event = hdf_file.create_group("Event Conditions")
            event.attrs["Completed Successfully"] = completion_attribute
        messages = (
            "Synthetic test messages\nComplete Process\n"
            if complete_messages
            else "Synthetic test messages\n"
        )
        hdf_file.create_dataset(
            "Results/Summary/Compute Messages (text)",
            data=np.bytes_(messages),
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
            "Geometry/2D Flow Areas/Mesh/Cells Center Coordinate",
            data=np.asarray([[0.0, 0.0], [1.0, 1.0]], dtype=np.float64),
        )
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Mesh/Cells Face and Orientation Info",
            data=np.asarray([[0, 2], [2, 2]], dtype=np.int32),
        )
        hdf_file.create_dataset(
            "Geometry/2D Flow Areas/Mesh/Cells Face and Orientation Values",
            data=np.asarray(
                [[0, 1], [1, 1], [1, -1], [2, 1]],
                dtype=np.int32,
            ),
        )
        hdf_file.create_dataset(
            f"{SERIES_BASE}/Time Date Stamp (ms)",
            data=np.asarray(
                [b"18Sep2019 13:00:00.000", b"18Sep2019 14:00:00.000"],
                dtype="S24",
            ),
        )
        plain_second_hour = 14 + plain_time_offset_hours
        hdf_file.create_dataset(
            f"{SERIES_BASE}/Time Date Stamp",
            data=np.asarray(
                [
                    b"18Sep2019 13:00:00",
                    f"18Sep2019 {plain_second_hour:02d}:00:00".encode(),
                ],
                dtype="S24",
            ),
        )
        hdf_file.create_dataset(
            f"{SERIES_BASE}/2D Flow Areas/Mesh/Water Surface",
            data=np.asarray([[10.0, 20.0], [12.0, 21.0]], dtype=np.float32),
        )
        hdf_file.create_dataset(
            f"{SERIES_BASE}/2D Flow Areas/Mesh/Face Velocity",
            data=np.ones((velocity_time_count, 3), dtype=np.float32),
        )
        if stored_depth:
            hdf_file.create_dataset(
                f"{SERIES_BASE}/2D Flow Areas/Mesh/Depth",
                data=np.asarray([[2.0, 0.0], [4.0, 1.0]], dtype=np.float32),
            )
        else:
            hdf_file.create_dataset(
                "Geometry/2D Flow Areas/Mesh/Cells Minimum Elevation",
                data=np.asarray([8.0, 20.0], dtype=np.float32),
            )
        maximum_wse = hdf_file.create_dataset(
            f"{SUMMARY_BASE}/2D Flow Areas/Mesh/Maximum Water Surface",
            data=np.asarray([[12.0, 21.0], [1.0 / 24.0, 1.0 / 24.0]]),
        )
        maximum_wse.attrs["Row Variables"] = np.asarray(
            [b"Value", b"Time"]
        )


def test_inspect_result_reports_current_completion_and_inputs(
    tmp_path,
    caplog,
):
    hdf_path = tmp_path / "current.p01.hdf"
    _write_inspection_hdf(hdf_path)

    with caplog.at_level(logging.INFO):
        result = HdfResultsProducts.inspect_result(hdf_path)

    assert result["schema"] == HdfResultsProducts.INSPECTION_SCHEMA
    assert result["completed_successfully"] is True
    assert result["hydraulic_qaqc"] == "not_evaluated"
    assert result["completion_evidence"] == {
        "event_conditions_completed_successfully": True,
        "embedded_compute_messages_complete_process": True,
        "accepted_sources": [
            "event_conditions_attribute",
            "embedded_compute_messages",
        ],
    }
    assert result["time"] == {
        "start": "2019-09-18T13:00:00",
        "end": "2019-09-18T14:00:00",
        "count": 2,
        "regular": True,
        "interval_seconds": 3600.0,
        "datasets": [
            f"{SERIES_BASE}/Time Date Stamp (ms)",
            f"{SERIES_BASE}/Time Date Stamp",
        ],
    }
    assert result["mesh_names"] == ["Mesh"]
    assert result["meshes"] == [
        {
            "mesh_name": "Mesh",
            "cell_count": 2,
            "declared_cell_count": 2,
            "face_count": 3,
            "depth_source": "derived_water_surface_minus_minimum_elevation",
        }
    ]
    assert result["crs"] == "EPSG:3451"
    assert result["unit_system"] == "US Customary"
    assert result["source"]["access"] == "read_only"
    assert "hydraulic QA/QC not evaluated" in caplog.text


def test_inspect_result_accepts_legacy_embedded_completion(tmp_path):
    hdf_path = tmp_path / "legacy.p01.hdf"
    _write_inspection_hdf(
        hdf_path,
        completion_attribute=None,
        stored_depth=True,
    )

    result = HdfResultsProducts.inspect_result(hdf_path)

    assert result["completion_evidence"] == {
        "event_conditions_completed_successfully": None,
        "embedded_compute_messages_complete_process": True,
        "accepted_sources": ["embedded_compute_messages"],
    }
    assert result["meshes"][0]["depth_source"] == "stored_depth"


def test_inspect_result_rejects_conflicting_completion(tmp_path):
    hdf_path = tmp_path / "conflict.p01.hdf"
    _write_inspection_hdf(hdf_path, completion_attribute=False)

    with pytest.raises(ValueError, match="conflicting completion evidence"):
        HdfResultsProducts.inspect_result(hdf_path)


def test_inspect_result_rejects_missing_completion(tmp_path):
    hdf_path = tmp_path / "incomplete.p01.hdf"
    _write_inspection_hdf(
        hdf_path,
        completion_attribute=None,
        complete_messages=False,
    )

    with pytest.raises(ValueError, match="no accepted completion evidence"):
        HdfResultsProducts.inspect_result(hdf_path)


def test_inspect_result_rejects_disagreeing_timestamp_datasets(tmp_path):
    hdf_path = tmp_path / "time-conflict.p01.hdf"
    _write_inspection_hdf(hdf_path, plain_time_offset_hours=1)

    with pytest.raises(ValueError, match="timestamp datasets disagree"):
        HdfResultsProducts.inspect_result(hdf_path)


def test_inspect_result_rejects_result_time_axis_mismatch(tmp_path):
    hdf_path = tmp_path / "velocity-conflict.p01.hdf"
    _write_inspection_hdf(hdf_path, velocity_time_count=1)

    with pytest.raises(ValueError, match="positive face count"):
        HdfResultsProducts.inspect_result(hdf_path)


def test_inspect_result_rejects_missing_topology(tmp_path):
    hdf_path = tmp_path / "missing-topology.p01.hdf"
    _write_inspection_hdf(hdf_path)
    with h5py.File(hdf_path, "r+") as hdf_file:
        del hdf_file[
            "Geometry/2D Flow Areas/Mesh/Cells Face and Orientation Values"
        ]

    with pytest.raises(ValueError, match="Orientation Values"):
        HdfResultsProducts.inspect_result(hdf_path)


def test_inspect_result_rejects_contradictory_units(tmp_path):
    hdf_path = tmp_path / "unit-conflict.p01.hdf"
    _write_inspection_hdf(hdf_path, contradictory_units=True)

    with pytest.raises(ValueError, match="unit-system metadata is contradictory"):
        HdfResultsProducts.inspect_result(hdf_path)


def test_product_contract_names_are_stable():
    assert HdfResultsProducts.SCHEMA == (
        "ras-commander/hydraulic-product-manifest/1.0"
    )
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
    assert HdfResultsProducts.MANIFEST_FILENAME == "hydraulic-products.json"


@pytest.mark.integration
def test_inspect_existing_producer_hdfs_read_only():
    configured = os.environ.get("RAS_COMMANDER_PRODUCTS_TEST_HDFS", "")
    paths = [Path(value) for value in configured.split(os.pathsep) if value]
    if not paths:
        pytest.skip("Set RAS_COMMANDER_PRODUCTS_TEST_HDFS for real HDF coverage")

    for path in paths:
        before = _sha256(path)
        result = HdfResultsProducts.inspect_result(path)
        after = _sha256(path)
        assert result["source"]["access"] == "read_only"
        assert result["completed_successfully"] is True
        assert result["time_axis_consistent"] is True
        assert result["hydraulic_qaqc"] == "not_evaluated"
        assert before == after
