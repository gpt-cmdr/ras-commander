"""Optional real-HDF coverage for the 2D reference-line QAQC workflow."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfMesh, HdfResultsMesh, HdfResultsXsec


def _decode_attr(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _chippewa_2d_paths():
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        repo_root / "examples" / "example_projects" / "Chippewa_2D_13",
        repo_root / "example_projects" / "Chippewa_2D_13",
    ]

    for project_dir in candidates:
        plan_hdf = project_dir / "Chippewa_2D.p02.hdf"
        geom_hdf = project_dir / "Chippewa_2D.g01.hdf"
        if plan_hdf.exists() and geom_hdf.exists():
            return plan_hdf, geom_hdf

    pytest.skip("Chippewa_2D_13 real HDF files are not available locally")


def test_chippewa_2d_reference_line_workflow_real_hdf():
    """Exercise the notebook's native 2D reference-line extraction path."""
    plan_hdf, geom_hdf = _chippewa_2d_paths()

    with h5py.File(plan_hdf, "r") as hdf:
        file_version = _decode_attr(hdf.attrs.get("File Version", ""))
    assert "HEC-RAS 7.0" in file_version

    mesh_name = HdfMesh.get_mesh_area_names(geom_hdf)[0]
    reference_ds = HdfResultsXsec.get_ref_lines_timeseries(plan_hdf)
    face_ds = HdfResultsMesh.get_mesh_faces_timeseries(
        plan_hdf,
        mesh_name,
        truncate=False,
    )
    internal_faces = HdfMesh.get_reference_line_internal_faces(
        geom_hdf,
        mesh_name=mesh_name,
    )

    assert {"Flow", "Velocity", "Water Surface", "Area"}.issubset(reference_ds.data_vars)
    assert {"face_flow", "face_velocity", "face_water_surface"}.issubset(face_ds.data_vars)
    assert not internal_faces.empty

    profile_name = str(reference_ds["refln_name"].values[0])
    profile_faces = internal_faces[
        internal_faces["profile_name"] == profile_name
    ].reset_index(drop=True)
    face_ids = profile_faces["face_id"].astype(int).tolist()

    face_water_surface = (
        face_ds["face_water_surface"]
        .sel(face_id=face_ids)
        .isel(time=slice(0, 10))
        .values
        .astype(float)
    )
    hydraulic_ds = HdfMesh.get_mesh_face_hydraulic_properties_at_stage(
        geom_hdf,
        mesh_name,
        face_ids,
        face_water_surface,
        unit_system="us",
    )

    assert {"area", "wetted_perimeter", "mannings_n", "hydraulic_radius", "conveyance"}.issubset(
        hydraulic_ds.data_vars
    )
    assert hydraulic_ds.sizes["time"] == 10
    assert hydraulic_ds.sizes["face_id"] == len(face_ids)

    profile_ref = reference_ds.sel(refln_name=profile_name)
    native_flow = profile_ref["Flow"].values.astype(float)
    native_area = profile_ref["Area"].values.astype(float)
    native_velocity = profile_ref["Velocity"].values.astype(float)
    velocity_from_area = np.divide(
        native_flow,
        native_area,
        out=np.full(native_flow.shape, np.nan),
        where=np.abs(native_area) > 0,
    )

    assert np.nanmean(np.abs(native_velocity - velocity_from_area)) < 1e-4
