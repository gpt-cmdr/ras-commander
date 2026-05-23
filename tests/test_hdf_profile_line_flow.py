"""Real-HDF coverage for profile/reference-line flow extraction."""

from pathlib import Path
import shutil

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import HdfResultsMesh, init_ras_project


VALIDATION_ROOT = Path(
    r"H:/Symphony/ras-commander/CLB-214/profile_line_flow_validation"
)
DATA_DIR = Path(__file__).parent / "data"
CANONICAL_ABSOLUTE_CSV = (
    DATA_DIR / "chippewa_profile_line_flow_rasmapper_upstream_absolute.csv"
)
CANONICAL_SIGNED_CSV = (
    DATA_DIR / "chippewa_profile_line_flow_rasmapper_upstream_signed.csv"
)
LINE_NAME = "Upstream"
MESH_NAME = "Perimeter 1"


@pytest.fixture(scope="module")
def validation_paths():
    project_dir = VALIDATION_ROOT / "project" / "Chippewa_2D_profile_line_flow"
    paths = {
        "project_dir": project_dir,
        "plan_hdf": project_dir / "Chippewa_2D.p02.hdf",
        "profile_lines_dir": VALIDATION_ROOT / "profile_line_input",
        "selected_faces_csv": VALIDATION_ROOT / "selected_faces.csv",
        "absolute_csv": VALIDATION_ROOT / "flow_timeseries_absolute.csv",
        "signed_csv": VALIDATION_ROOT / "flow_timeseries_signed.csv",
        "manual_csv": VALIDATION_ROOT / "manual_face_flow_validation.csv",
        "peak_csv": VALIDATION_ROOT / "peak_flow.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        pytest.skip(
            "CLB-214 Chippewa profile-line validation artifacts are not available: "
            + ", ".join(missing)
        )
    return paths


@pytest.fixture(scope="module")
def absolute_flow_df(validation_paths):
    return HdfResultsMesh.get_profile_line_flow_timeseries(
        validation_paths["plan_hdf"],
        LINE_NAME,
        mesh_name=MESH_NAME,
        profile_lines_path=validation_paths["profile_lines_dir"],
        direction="absolute",
    )


def test_profile_line_flow_timeseries_matches_validation_csv(
    validation_paths,
    absolute_flow_df,
):
    expected = pd.read_csv(CANONICAL_ABSOLUTE_CSV, parse_dates=["time"])

    assert list(absolute_flow_df.columns) == [
        "time",
        "flow",
        "line_name",
        "mesh_name",
        "direction",
        "face_count",
        "selection_source",
    ]
    assert len(absolute_flow_df) == len(expected) == 1633
    assert absolute_flow_df["line_name"].unique().tolist() == [LINE_NAME]
    assert absolute_flow_df["mesh_name"].unique().tolist() == [MESH_NAME]
    assert absolute_flow_df["direction"].unique().tolist() == ["absolute"]
    assert absolute_flow_df["selection_source"].unique().tolist() == [
        "rasmapper_perimeter_faces"
    ]
    assert absolute_flow_df["face_count"].unique().tolist() == [7]
    assert absolute_flow_df["time"].tolist() == expected["time"].tolist()
    np.testing.assert_allclose(absolute_flow_df["flow"], expected["flow"])

    assert absolute_flow_df.attrs["face_ids"] == [68, 813, 65, 777, 773, 756, 811]
    assert absolute_flow_df.attrs["units"] == "cfs"


def test_profile_line_peak_flow_matches_validation_csv(
    validation_paths,
    absolute_flow_df,
):
    peak = HdfResultsMesh.get_profile_line_peak_flow(
        validation_paths["plan_hdf"],
        LINE_NAME,
        mesh_name=MESH_NAME,
        profile_lines_path=validation_paths["profile_lines_dir"],
    )

    assert list(peak.columns) == [
        "line_name",
        "mesh_name",
        "peak_time",
        "peak_flow",
        "direction",
        "face_count",
        "selection_source",
    ]
    assert len(peak) == 1
    assert peak.loc[0, "line_name"] == LINE_NAME
    assert peak.loc[0, "mesh_name"] == MESH_NAME
    assert peak.loc[0, "peak_flow"] == absolute_flow_df["flow"].max()
    expected_peak = absolute_flow_df.loc[absolute_flow_df["flow"].idxmax()]
    assert peak.loc[0, "peak_time"] == expected_peak["time"]
    np.testing.assert_allclose(peak.loc[0, "peak_flow"], expected_peak["flow"])


def test_profile_line_signed_direction_matches_rasmapper_fixture(validation_paths):
    signed = HdfResultsMesh.get_profile_line_flow_timeseries(
        validation_paths["plan_hdf"],
        LINE_NAME,
        mesh_name=MESH_NAME,
        profile_lines_path=validation_paths["profile_lines_dir"],
        direction="signed",
    )
    expected_signed = pd.read_csv(CANONICAL_SIGNED_CSV, parse_dates=["time"])

    assert signed["direction"].unique().tolist() == ["signed"]
    assert signed["selection_source"].unique().tolist() == ["rasmapper_perimeter_faces"]
    assert signed["time"].tolist() == expected_signed["time"].tolist()
    np.testing.assert_allclose(signed["flow"], expected_signed["flow"])


def test_profile_line_missing_name_raises(validation_paths):
    with pytest.raises(ValueError, match="Profile line 'Definitely Missing' not found"):
        HdfResultsMesh.get_profile_line_flow_timeseries(
            validation_paths["plan_hdf"],
            "Definitely Missing",
            mesh_name=MESH_NAME,
            profile_lines_path=validation_paths["profile_lines_dir"],
        )


def test_profile_line_plan_number_preserves_ras_object(validation_paths):
    ras_object = init_ras_project(
        validation_paths["project_dir"],
        "7.0",
        ras_object="new",
        load_results_summary=False,
    )
    ras_object.rasmap_df.at[0, "profile_lines_path"] = [
        str(validation_paths["profile_lines_dir"] / "Profile Lines.shp")
    ]

    result = HdfResultsMesh.get_profile_line_flow_timeseries(
        "02",
        LINE_NAME,
        mesh_name=MESH_NAME,
        ras_object=ras_object,
    )

    assert len(result) == 1633
    assert result["selection_source"].unique().tolist() == ["rasmapper_perimeter_faces"]
    np.testing.assert_allclose(result["flow"].max(), 38000.6282043457)


def test_profile_line_legacy_matches_pre_clb852_validation(validation_paths):
    legacy = HdfResultsMesh.get_profile_line_flow_timeseries_legacy(
        validation_paths["plan_hdf"],
        LINE_NAME,
        mesh_name=MESH_NAME,
        profile_lines_path=validation_paths["profile_lines_dir"],
        direction="absolute",
    )
    expected = pd.read_csv(validation_paths["absolute_csv"], parse_dates=["time"])

    assert legacy["selection_source"].unique().tolist() == ["profile_lines_geometry"]
    assert legacy["face_count"].unique().tolist() == [6]
    assert legacy["time"].tolist() == expected["time"].tolist()
    np.testing.assert_allclose(legacy["flow"], expected["flow"])


def test_profile_line_uses_native_reference_faces_when_present(
    tmp_path_factory,
    validation_paths,
):
    native_hdf = tmp_path_factory.mktemp("profile_line_native") / "Chippewa_2D.p02.hdf"
    shutil.copy2(validation_paths["plan_hdf"], native_hdf)
    selected_faces = pd.read_csv(validation_paths["selected_faces_csv"])

    attr_dtype = np.dtype([("Name", "S64"), ("SA-2D", "S64")])
    face_dtype = np.dtype([
        ("Reference Line ID", "<i4"),
        ("Face Index", "<i4"),
        ("FP Start Index", "<i4"),
        ("FP End Index", "<i4"),
        ("Station Start", "<f8"),
        ("Station End", "<f8"),
    ])
    face_rows = []
    for station, face_id in enumerate(selected_faces["face_id"].astype(int).tolist()):
        face_rows.append((0, face_id, 0, 0, float(station), float(station + 1)))

    with h5py.File(native_hdf, "a") as hdf:
        reference_group = hdf.require_group("Geometry/Reference Lines")
        for dataset_name in ("Attributes", "Internal Faces"):
            if dataset_name in reference_group:
                del reference_group[dataset_name]
        reference_group.create_dataset(
            "Attributes",
            data=np.array([(b"Native Upstream", b"Perimeter 1")], dtype=attr_dtype),
        )
        reference_group.create_dataset(
            "Internal Faces",
            data=np.array(face_rows, dtype=face_dtype),
        )

    native = HdfResultsMesh.get_profile_line_flow_timeseries(
        native_hdf,
        "Native Upstream",
        direction="absolute",
    )
    expected = pd.read_csv(validation_paths["absolute_csv"], parse_dates=["time"])

    assert native["mesh_name"].unique().tolist() == [MESH_NAME]
    assert native["selection_source"].unique().tolist() == [
        "reference_line_internal_faces"
    ]
    assert native["face_count"].unique().tolist() == [6]
    assert native["time"].tolist() == expected["time"].tolist()
    np.testing.assert_allclose(native["flow"], expected["flow"])
