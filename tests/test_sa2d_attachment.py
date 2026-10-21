"""Fail-closed native SA/2D attachment verification and real example coverage."""

import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import HdfStruc, RasExamples


@pytest.fixture
def connection_hdf(tmp_path):
    """Small fixture of the actual 6.6 schema qualified on BaldEagle output."""
    path = tmp_path / "connection.p01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.attrs["File Version"] = np.bytes_("HEC-RAS 6.6 September 2024")
        hdf.attrs["File Type"] = np.bytes_("HEC-RAS Results")
        dtype = [
            ("Type", "S16"),
            ("Connection", "S16"),
            ("US SA/2D", "S16"),
            ("DS SA/2D", "S16"),
        ]
        hdf.create_dataset(
            "Geometry/Structures/Attributes",
            data=np.array([(b"Connection", b"Seam", b"Left", b"Right")], dtype=dtype),
        )
        group = hdf.create_group(HdfStruc.SA_2D_CONN_RESULTS_PATH + "/Seam")
        for area, side in (("Left", "Headwater"), ("Right", "Tailwater")):
            mesh = hdf.create_group(f"Geometry/2D Flow Areas/{area}")
            mesh.create_dataset("Cells Surface Area", data=[10.0, 10.0])
            mesh.create_dataset("Faces FacePoint Indexes", data=[[0, 1]])
            mesh.create_dataset("Faces Cell Indexes", data=[[0, 1]])
            mesh.create_dataset("FacePoints Coordinate", data=[[0.0, 0.0], [1.0, 0.0]])
            group.create_dataset(f"{side} Cells", data=np.array([0], dtype=np.int32))
            group.create_dataset(
                f"Geometric Info/{side} Face Points",
                data=np.array([0, 1], dtype=np.int32),
            )
    return path


def test_native_ids_and_faces_are_verified(connection_hdf):
    row = HdfStruc.get_connection_attachments(str(connection_hdf)).iloc[0]
    assert row.attachment_verified
    assert row.from_cells == (0,) and row.to_cells == (0,)
    assert row.from_faces == (0,) and row.to_faces == (0,)
    assert not row.orientation_verified and not row.flux_sign_verified


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "inactive",
        "range",
        "incidence",
        "schema",
        "ambiguous",
        "version",
        "point_range",
        "fractional_face",
        "adjacency_range",
    ],
)
def test_invalid_native_attachment_fails_closed(connection_hdf, mutation):
    with h5py.File(connection_hdf, "a") as hdf:
        base = HdfStruc.SA_2D_CONN_RESULTS_PATH + "/Seam"
        if mutation == "missing":
            del hdf[base + "/Tailwater Cells"]
        elif mutation == "inactive":
            hdf["Geometry/2D Flow Areas/Left/Cells Surface Area"][0] = 0
        elif mutation == "range":
            hdf[base + "/Headwater Cells"][0] = 99
        elif mutation == "incidence":
            hdf["Geometry/2D Flow Areas/Left/Faces Cell Indexes"][0] = [1, 1]
        elif mutation == "schema":
            del hdf[base + "/Headwater Cells"]
            hdf.create_dataset(base + "/Headwater Cells", data=[0.0])
        elif mutation == "ambiguous":
            hdf.copy(base, HdfStruc.SA_2D_CONN_RESULTS_PATH + "/Left Seam")
        elif mutation == "version":
            hdf.attrs["File Version"] = np.bytes_("HEC-RAS 7.0.1")
        elif mutation == "point_range":
            hdf[base + "/Geometric Info/Headwater Face Points"][0] = 99
        elif mutation == "fractional_face":
            key = "Geometry/2D Flow Areas/Left/Faces FacePoint Indexes"
            del hdf[key]
            hdf.create_dataset(key, data=[[0.0, 1.5]])
        elif mutation == "adjacency_range":
            hdf["Geometry/2D Flow Areas/Left/Faces Cell Indexes"][0] = [0, 99]
    row = HdfStruc.get_connection_attachments(connection_hdf).iloc[0]
    assert not row.attachment_verified
    assert row.reason_code == "CONNECTION_ATTACHMENT_UNVERIFIED"


def test_expected_identity_and_missing_connections(connection_hdf):
    expected = pd.DataFrame(
        [
            {"Name": "Seam", "From": "Other", "To": "Right"},
            {"Name": "Missing", "From": "Left", "To": "Right"},
        ]
    )
    result = HdfStruc.get_connection_attachments(connection_hdf, expected)
    assert result.Name.tolist() == ["Seam", "Missing"]
    assert not result.attachment_verified.any()


def test_empty_geometry_and_invalid_expected_schema(tmp_path):
    path = tmp_path / "empty.hdf"
    with h5py.File(path, "w"):
        pass
    result = HdfStruc.get_connection_attachments(path)
    assert result.empty and "attachment_verified" in result.columns
    from ras_commander.schemas import DATAFRAME_SCHEMAS

    declared = [
        column["name"]
        for column in DATAFRAME_SCHEMAS["sa2d_connection_attachments"]["columns"]
    ]
    assert list(result.columns) == declared
    with pytest.raises(ValueError, match="Name, From, and To"):
        HdfStruc.get_connection_attachments(path, pd.DataFrame({"Name": ["Seam"]}))


def test_real_example_geometry_is_not_native_attachment(tmp_path):
    RasExamples._find_zip_file()
    if RasExamples._zip_file_path is None:
        pytest.skip("Official RasExamples archive unavailable; no download in tests")
    project = RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=tmp_path)
    result = HdfStruc.get_connection_attachments(project / "BaldEagleDamBrk.g13.hdf")
    assert result.Name.tolist() == ["Dam", "Lower Levee", "Middle Levee", "Upper Levee"]
    assert not result.attachment_verified.any()


def test_qualified_native_example_result():
    candidate = os.environ.get("SA2D_NATIVE_RESULT_HDF")
    if not candidate or not Path(candidate).is_file():
        pytest.skip(
            "Set SA2D_NATIVE_RESULT_HDF to native 6.6 BaldEagle plan 04 results; see scripts/qualify_sa2d_attachment.py"
        )
    result = HdfStruc.get_connection_attachments(candidate).set_index("Name")
    for name, segments in (
        ("Lower Levee", 158),
        ("Middle Levee", 104),
        ("Upper Levee", 88),
    ):
        row = result.loc[name]
        assert row.attachment_verified
        assert len(row.from_cells) == len(row.to_cells) == segments
        assert len(row.from_faces) == len(row.to_faces) == segments
    assert not result.loc["Dam", "attachment_verified"]
