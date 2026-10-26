"""Failure/coverage contracts use bounded stand-ins, not hydraulic validation.

Set RAS_MESH_QUALITY_REAL_HDF to an existing public example plan HDF for the
optional read-only integration check (embedded geometry is used).
"""

import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.check import RasCheck
from ras_commander.check.types import CheckResults, Severity
from ras_commander.hdf.HdfMesh import HdfMesh
from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh


def coverage(result):
    assert isinstance(result, CheckResults)
    assert all("no issues detected" not in m.message for m in result.messages)
    return result.statistics["mesh_quality_coverage"]


def test_nonexistent_hdfs_are_failed_not_clean(tmp_path):
    result = RasCheck.check_mesh_quality(tmp_path / "missing.p01.hdf", tmp_path / "missing.g01.hdf")
    statuses = coverage(result)
    assert statuses["cell_area"]["status"] == "failed"
    assert statuses["aspect_ratio"]["status"] == "failed"
    assert statuses["face_velocity"]["status"] == "failed"
    assert result.get_error_count() == 3


def test_corrupt_hdfs_are_failed_not_clean(tmp_path):
    path = tmp_path / "bad.p01.hdf"
    path.write_text("not an HDF")
    result = RasCheck.check_mesh_quality(path, path)
    assert coverage(result)["cell_area"]["status"] == "failed"
    assert coverage(result)["face_velocity"]["status"] == "failed"


def test_confirmed_non_2d_geometry_is_not_applicable(tmp_path):
    geom = tmp_path / "one_dimensional.g01.hdf"
    with h5py.File(geom, "w") as hdf:
        hdf.create_group("Geometry/Cross Sections")
    result = RasCheck.check_mesh_quality(tmp_path / "unused.p01.hdf", geom)
    statuses = coverage(result)
    assert {statuses[k]["status"] for k in ("cell_area", "aspect_ratio", "face_velocity")} == {"not_applicable"}
    assert result.get_error_count() == 0


@pytest.fixture
def mesh_inputs(tmp_path, monkeypatch):
    """Minimal native inventory/unit evidence; readers are controlled separately."""
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    geom = tmp_path / "mesh.g01.hdf"
    plan = tmp_path / "mesh.p01.hdf"
    with h5py.File(geom, "w") as hdf:
        group = hdf.create_group("Geometry/2D Flow Areas")
        group.create_dataset("Attributes", data=np.array([(b"Mesh",)], dtype=[("Name", "S16")]))
        group.create_dataset("Mesh/Faces FacePoint Indexes", data=np.array([[0, 1]], dtype=np.int32))
    with h5py.File(plan, "w") as hdf:
        hdf.create_group("Results")
        hdf.attrs["Units System"] = "SI Units"
    polygons = gpd.GeoDataFrame({"mesh_name": ["Mesh"], "cell_id": [0]}, geometry=[box(0, 0, 4, 4)], crs="EPSG:32615")
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", staticmethod(lambda path, **kw: polygons))
    velocities = pd.DataFrame({"mesh_name": ["Mesh"], "face_id": [0], "maximum_face_velocity": [8.0]})
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_face_v", staticmethod(lambda path, **_: velocities))
    return plan, geom, polygons, velocities


def test_metric_areas_and_native_velocities_are_converted(mesh_inputs):
    plan, geom, polygons, velocities = mesh_inputs
    result = RasCheck.check_mesh_quality(str(plan), str(geom))
    statuses = coverage(result)
    assert statuses["cell_area"]["status"] == "passed"  # 16 m² = 172 ft²
    assert statuses["aspect_ratio"]["status"] == "passed"
    assert statuses["face_velocity"]["status"] == "issues"  # 8 m/s > 25 ft/s
    assert result.mesh_summary.iloc[0].min_area_sqft == pytest.approx(16 / 0.3048 ** 2)
    velocity_message = next(m for m in result.messages if m.message_id == "US_2D_04")
    assert velocity_message.value == pytest.approx(8 / 0.3048)
    assert velocity_message.threshold == 25
    assert not any(m.message_id == "US_2D_01" for m in result.messages)
    assert statuses["connectivity"]["status"] == "unsupported"


def test_survey_foot_crs_and_us_result_units_are_independent(mesh_inputs):
    plan, geom, polygons, velocities = mesh_inputs
    polygons.set_crs("EPSG:2278", allow_override=True, inplace=True)
    with h5py.File(plan, "r+") as hdf:
        hdf.attrs["Units System"] = "US Customary"
    velocities["maximum_face_velocity"] = 20.0
    result = RasCheck.check_mesh_quality(plan, geom)
    assert coverage(result)["face_velocity"]["status"] == "passed"
    assert result.mesh_summary.iloc[0].min_area_sqft == pytest.approx(16 * (1200 / 3937 / 0.3048) ** 2)
    assert any(m.message_id == "US_2D_01" for m in result.messages)


def test_absent_units_prevent_velocity_success(mesh_inputs):
    plan, geom, _, _ = mesh_inputs
    with h5py.File(plan, "r+") as hdf:
        del hdf.attrs["Units System"]
    result = RasCheck.check_mesh_quality(plan, geom)
    assert coverage(result)["face_velocity"]["status"] == "failed"
    assert not any(m.message_id == "US_2D_04" for m in result.messages)


@pytest.mark.parametrize("crs", [None, "EPSG:4326"])
def test_missing_or_geographic_crs_prevents_geometry_success(mesh_inputs, crs):
    plan, geom, polygons, _ = mesh_inputs
    polygons.set_crs(crs, allow_override=True, inplace=True)
    result = RasCheck.check_mesh_quality(plan, geom)
    statuses = coverage(result)
    assert statuses["cell_area"]["status"] == "unavailable"
    assert statuses["aspect_ratio"]["status"] == "unavailable"
    assert result.mesh_summary is None


def test_empty_polygon_reader_is_unavailable_not_passed(mesh_inputs, monkeypatch):
    plan, geom, polygons, _ = mesh_inputs
    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", staticmethod(lambda path, **kw: polygons.iloc[:0]))
    result = RasCheck.check_mesh_quality(plan, geom)
    assert coverage(result)["cell_area"]["status"] == "unavailable"
    assert coverage(result)["face_velocity"]["status"] == "issues"


@pytest.mark.parametrize("values", [[], [np.nan], [np.inf]])
def test_missing_or_nonfinite_velocity_cannot_pass(mesh_inputs, values):
    plan, geom, _, velocities = mesh_inputs
    if not values:
        velocities.drop(velocities.index, inplace=True)
    else:
        velocities["maximum_face_velocity"] = values
    result = RasCheck.check_mesh_quality(plan, geom)
    assert coverage(result)["face_velocity"]["status"] in {"unavailable", "failed"}


def test_time_column_is_not_treated_as_velocity(mesh_inputs):
    plan, geom, _, velocities = mesh_inputs
    velocities.rename(columns={"maximum_face_velocity": "maximum_face_velocity_time"}, inplace=True)
    result = RasCheck.check_mesh_quality(plan, geom)
    assert coverage(result)["face_velocity"]["status"] == "unavailable"


def test_partial_mesh_velocity_inventory_cannot_pass(mesh_inputs):
    plan, geom, _, velocities = mesh_inputs
    velocities["mesh_name"] = "Other mesh"
    result = RasCheck.check_mesh_quality(plan, geom)
    assert coverage(result)["face_velocity"]["status"] == "unavailable"


@pytest.mark.parametrize("ids", [[0], [0, 0], [0, 2], [0, 0.5], [0, np.nan]])
def test_partial_or_invalid_face_velocity_inventory_cannot_pass(mesh_inputs, monkeypatch, ids):
    plan, geom, _, _ = mesh_inputs
    with h5py.File(geom, "r+") as hdf:
        path = "Geometry/2D Flow Areas/Mesh/Faces FacePoint Indexes"
        del hdf[path]
        hdf.create_dataset(path, data=np.array([[0, 1], [1, 2]], dtype=np.int32))
    incomplete = pd.DataFrame({
        "mesh_name": ["Mesh"] * len(ids), "face_id": ids,
        "maximum_face_velocity": [1.0] * len(ids),
    })
    monkeypatch.setattr(HdfResultsMesh, "get_mesh_max_face_v", staticmethod(lambda path, **_: incomplete))
    result = RasCheck.check_mesh_quality(plan, geom)
    assert coverage(result)["face_velocity"]["status"] == "failed"
    assert "every native face exactly once" in coverage(result)["face_velocity"]["reason"]


def test_missing_face_identity_cannot_pass(mesh_inputs):
    plan, geom, _, velocities = mesh_inputs
    velocities.drop(columns="face_id", inplace=True)
    result = RasCheck.check_mesh_quality(plan, geom)
    assert coverage(result)["face_velocity"]["status"] == "unavailable"


def test_real_public_plan_reports_coverage():
    fixture = os.environ.get("RAS_MESH_QUALITY_REAL_HDF")
    if not fixture:
        pytest.skip("Set RAS_MESH_QUALITY_REAL_HDF to an existing public example plan HDF")
    path = Path(fixture)
    assert path.is_file()
    result = RasCheck.check_mesh_quality(path, path)
    statuses = coverage(result)
    assert set(statuses) == {"cell_area", "aspect_ratio", "face_velocity", "connectivity"}
    assert not any(item["status"] == "failed" for item in statuses.values())
    # This is an integration/coverage check, not a hydraulic-quality assertion.
    assert all(m.severity in Severity for m in result.messages)


def test_polygon_reader_failure_is_explicit(mesh_inputs, monkeypatch):
    plan, geom, _, _ = mesh_inputs

    def fail(path, **kwargs):
        raise OSError("simulated read failure")

    monkeypatch.setattr(HdfMesh, "get_mesh_cell_polygons", staticmethod(fail))
    result = RasCheck.check_mesh_quality(plan, geom)
    statuses = coverage(result)
    assert statuses["cell_area"]["status"] == "failed"
    assert "simulated read failure" in statuses["cell_area"]["reason"]
    assert statuses["aspect_ratio"]["status"] == "failed"
    assert statuses["face_velocity"]["status"] == "issues"


def test_run_all_preserves_unsteady_mesh_coverage_and_counts(mesh_inputs, monkeypatch):
    # Test aggregation through the public dispatcher with real HDF flow-type
    # detection. Unrelated domain checks are bounded to empty results here.
    from ras_commander.check.check_nt import CheckNt
    from ras_commander.check.check_unsteady import CheckUnsteady
    from ras_commander.check.types import FlowType

    plan, geom, _, _ = mesh_inputs
    with h5py.File(plan, "r+") as hdf:
        hdf.create_group("Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas")
    monkeypatch.setattr(CheckNt, "check_nt", staticmethod(lambda *args: CheckResults()))
    for name in ("check_mass_balance", "check_computation", "check_peaks", "check_stability"):
        monkeypatch.setattr(CheckUnsteady, name, staticmethod(lambda *args: CheckResults()))

    expected = RasCheck.check_mesh_quality(plan, geom)
    result = RasCheck.run_all(plan)
    assert result.flow_type == FlowType.UNSTEADY
    assert result.statistics["mesh_quality_coverage"] == expected.statistics["mesh_quality_coverage"]
    assert result.statistics["total_messages"] == len(result.messages)
    assert result.statistics["error_count"] == result.get_error_count()
    assert result.statistics["warning_count"] == result.get_warning_count()
    assert result.statistics["warning_count"] > 0  # native 8 m/s exceeds 25 ft/s
    pd.testing.assert_frame_equal(result.mesh_summary, expected.mesh_summary)


def test_real_public_run_all_retains_mesh_coverage():
    fixture = os.environ.get("RAS_MESH_QUALITY_REAL_HDF")
    if not fixture:
        pytest.skip("Set RAS_MESH_QUALITY_REAL_HDF to an existing public example plan HDF")
    path = Path(fixture)
    assert path.is_file()
    result = RasCheck.run_all(path)
    statuses = result.statistics["mesh_quality_coverage"]
    assert set(statuses) == {"cell_area", "aspect_ratio", "face_velocity", "connectivity"}
    assert not any(item["status"] == "failed" for item in statuses.values())
    assert result.statistics["total_messages"] == len(result.messages)
    assert result.statistics["error_count"] == result.get_error_count()
    assert result.statistics["warning_count"] == result.get_warning_count()
