"""Explicit duplicate ownership diagnostics retain native associations."""

import hashlib
from pathlib import Path

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import HdfBndry, HdfMesh


@pytest.fixture
def ownership_hdf(tmp_path):
    path = tmp_path / "ownership.g01.hdf"
    with h5py.File(path, "w") as hdf:
        areas = hdf.create_group("Geometry/2D Flow Areas")
        areas.create_dataset(
            "Attributes",
            data=np.array(
                [(b"Mesh", 2)], dtype=[("Name", "S16"), ("Cell Count", "i4")]
            ),
        )
        mesh = areas.create_group("Mesh")
        mesh.create_dataset(
            "Cells Center Coordinate", data=[[0.25, 0.25], [0.75, 0.75]]
        )
        mesh.create_dataset(
            "FacePoints Coordinate",
            data=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        )
        mesh.create_dataset(
            "Faces FacePoint Indexes", data=[[0, 1], [1, 2], [2, 3], [0, 2]]
        )
        mesh.create_dataset(
            "Faces Cell Indexes", data=[[0, -1], [1, -1], [1, -1], [0, 1]]
        )
        bc = hdf.create_group("Geometry/Boundary Condition Lines")
        bc.create_dataset(
            "Attributes",
            data=np.array(
                [(b"Inflow", b"Mesh", b"Flow"), (b"Outflow", b"Mesh", b"Stage")],
                dtype=[("Name", "S16"), ("SA-2D", "S16"), ("Type", "S16")],
            ),
        )
        bc.create_dataset(
            "External Faces",
            data=np.array(
                [(0, 0, 0, 1), (1, 0, 0, 1), (0, 1, 1, 2)],
                dtype=[
                    ("BC Line ID", "i4"),
                    ("Face Index", "i4"),
                    ("FP Start Index", "i4"),
                    ("FP End Index", "i4"),
                ],
            ),
        )
    return path


def test_default_raises_and_legacy_diagnostic_retains_columns(ownership_hdf):
    for reader, args in [
        (HdfBndry.get_bc_external_faces, ()),
        (HdfMesh.get_mesh_perimeter_faces, ("Mesh",)),
    ]:
        with pytest.raises(ValueError, match="unique face ownership"):
            reader(ownership_hdf, *args)
    legacy = HdfBndry.get_bc_external_faces(ownership_hdf, validate_unique_faces=False)
    assert len(legacy) == 3
    assert "duplicate_ownership" not in legacy.columns
    assert legacy.attrs["duplicate_face_count"] == 1
    assert legacy.attrs["duplicate_face_row_count"] == 2


@pytest.mark.parametrize("include_geometry", [False, True])
def test_report_preserves_each_association(ownership_hdf, include_geometry):
    before = hashlib.sha256(ownership_hdf.read_bytes()).hexdigest()
    result = HdfBndry.get_bc_external_faces(
        ownership_hdf,
        include_geometry=include_geometry,
        on_duplicate_ownership="report",
    )
    assert result.face_id.tolist() == [0, 0, 1]
    assert result.bc_line_id.tolist() == [0, 1, 0]
    assert result.duplicate_ownership.tolist() == [True, True, False]
    assert result.owning_bc_line_ids.tolist() == [[0, 1], [0, 1], [0]]
    assert result.owning_bc_line_names.tolist() == [
        ["Inflow", "Outflow"],
        ["Inflow", "Outflow"],
        ["Inflow"],
    ]
    assert result.attrs["duplicate_ownership"] == [
        {
            "mesh_name": "Mesh",
            "face_id": 0,
            "owning_bc_line_ids": [0, 1],
            "owning_bc_line_names": ["Inflow", "Outflow"],
        }
    ]
    assert result.attrs["duplicate_face_count"] == 1
    assert result.attrs["duplicate_face_row_count"] == 2
    assert result.attrs["face_ownership_unique"] is False
    if include_geometry:
        assert isinstance(result, gpd.GeoDataFrame)
        assert result.geometry.length.tolist() == [1.0, 1.0, 1.0]
    assert hashlib.sha256(ownership_hdf.read_bytes()).hexdigest() == before


def test_perimeter_report_has_one_row_per_face_and_ambiguous_scalars(ownership_hdf):
    result = HdfMesh.get_mesh_perimeter_faces(
        ownership_hdf, "Mesh", on_duplicate_ownership="report"
    )
    assert result.face_id.tolist() == [0, 1, 2]
    assert result.duplicate_ownership.tolist() == [True, False, False]
    assert result.owning_bc_line_ids.tolist() == [[0, 1], [0], []]
    assert result.owning_bc_line_names.tolist() == [
        ["Inflow", "Outflow"],
        ["Inflow"],
        [],
    ]
    for field in ["bc_line_id", "bc_line_name", "bc_line_type"]:
        assert pd.isna(result.iloc[0][field])
        assert pd.isna(result.iloc[2][field])
    assert result.iloc[1].bc_line_id == 0
    assert result.bc_line_id.dtype == pd.Int64Dtype()
    assert result.attrs["duplicate_ownership"][0]["face_id"] == 0


@pytest.mark.parametrize("status", ["empty", "absent"])
def test_report_empty_or_absent_has_diagnostic_columns(ownership_hdf, status):
    with h5py.File(ownership_hdf, "r+") as hdf:
        bc = hdf["Geometry/Boundary Condition Lines"]
        dtype = bc["External Faces"].dtype
        del bc["External Faces"]
        if status == "empty":
            bc.create_dataset("External Faces", data=np.empty(0, dtype=dtype))
        else:
            del hdf["Geometry/Boundary Condition Lines"]
    result = HdfBndry.get_bc_external_faces(
        ownership_hdf, on_duplicate_ownership="report"
    )
    assert result.empty
    assert result.attrs["association_status"] == status
    assert result.attrs["duplicate_ownership"] == []
    assert result.duplicate_ownership.dtype == bool
    assert {"owning_bc_line_ids", "owning_bc_line_names"}.issubset(result.columns)
    perimeter = HdfMesh.get_mesh_perimeter_faces(
        ownership_hdf, "Mesh", on_duplicate_ownership="report"
    )
    assert perimeter.owning_bc_line_ids.tolist() == [[], [], []]
    assert not perimeter.duplicate_ownership.any()
    assert perimeter.attrs["duplicate_ownership"] == []


@pytest.mark.parametrize("option", ["ignore", "REPORT", None])
def test_invalid_duplicate_option_fails(ownership_hdf, option):
    with pytest.raises(ValueError, match="on_duplicate_ownership"):
        HdfBndry.get_bc_external_faces(ownership_hdf, on_duplicate_ownership=option)
    with pytest.raises(ValueError, match="on_duplicate_ownership"):
        HdfMesh.get_mesh_perimeter_faces(
            ownership_hdf, "Mesh", on_duplicate_ownership=option
        )


@pytest.mark.parametrize(
    "mutation", ["stale", "interior", "invalid_bc", "invalid_cell", "missing"]
)
def test_report_does_not_relax_other_perimeter_checks(ownership_hdf, mutation):
    with h5py.File(ownership_hdf, "r+") as hdf:
        rows = hdf["Geometry/Boundary Condition Lines/External Faces"]
        if mutation == "missing":
            del hdf["Geometry/Boundary Condition Lines/External Faces"]
        elif mutation == "invalid_cell":
            hdf["Geometry/2D Flow Areas/Mesh/Faces Cell Indexes"][0] = [-2, 0]
        else:
            values = rows[:]
            if mutation == "stale":
                values[0]["FP End Index"] = 2
            elif mutation == "interior":
                values[0]["Face Index"] = 3
            else:
                values[0]["BC Line ID"] = 2
            rows[:] = values
    with pytest.raises(ValueError):
        HdfMesh.get_mesh_perimeter_faces(
            ownership_hdf, "Mesh", on_duplicate_ownership="report"
        )


def test_unique_default_columns_remain_unchanged(ownership_hdf):
    with h5py.File(ownership_hdf, "r+") as hdf:
        bc = hdf["Geometry/Boundary Condition Lines"]
        rows = bc["External Faces"][:][[0, 2]]
        del bc["External Faces"]
        bc.create_dataset("External Faces", data=rows)
    default = HdfBndry.get_bc_external_faces(ownership_hdf)
    report = HdfBndry.get_bc_external_faces(
        ownership_hdf, on_duplicate_ownership="report"
    )
    assert "duplicate_ownership" not in default.columns
    assert not report.duplicate_ownership.any()
    assert report.attrs["duplicate_ownership"] == []
    pd.testing.assert_frame_equal(default, report[default.columns])


def test_repeated_same_owner_remains_explicit_and_ambiguous(ownership_hdf):
    with h5py.File(ownership_hdf, "r+") as hdf:
        rows = hdf["Geometry/Boundary Condition Lines/External Faces"]
        values = rows[:]
        values[1]["BC Line ID"] = 0
        rows[:] = values
    with pytest.raises(ValueError, match="unique face ownership"):
        HdfBndry.get_bc_external_faces(ownership_hdf)
    associations = HdfBndry.get_bc_external_faces(
        ownership_hdf, on_duplicate_ownership="report"
    )
    assert len(associations) == 3
    assert associations.duplicate_ownership.tolist() == [True, True, False]
    assert associations.owning_bc_line_ids.tolist() == [[0], [0], [0]]
    perimeter = HdfMesh.get_mesh_perimeter_faces(
        ownership_hdf, "Mesh", on_duplicate_ownership="report"
    )
    assert perimeter.iloc[0].duplicate_ownership
    assert pd.isna(perimeter.iloc[0].bc_line_id)
    assert perimeter.iloc[0].owning_bc_line_ids == [0]


def test_delivered_salt_draw_parent_read_only_when_available():
    path = Path(
        "I:/FIM-Commander-Data/fixtures/ebfe_2d_sldr/source/13070004_Models_20250416/"
        "Hydraulic Models/RAS_Submittal/Input/SLDR_004.g02.hdf"
    )
    if not path.exists():
        pytest.skip("Delivered Salt Draw parent fixture is unavailable locally")

    def digest():
        checksum = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                checksum.update(chunk)
        return checksum.hexdigest()

    before = digest()
    with pytest.raises(ValueError, match="unique face ownership"):
        HdfBndry.get_bc_external_faces(path)
    result = HdfBndry.get_bc_external_faces(path, on_duplicate_ownership="report")
    assert len(result) == 22836
    assert result.attrs["duplicate_face_count"] == 4583
    assert result.attrs["duplicate_face_row_count"] == 22836
    assert len(result.attrs["duplicate_ownership"]) == 4583
    selected = result.loc[result.face_id == 648870]
    assert len(selected) == 5
    assert selected.owning_bc_line_ids.tolist() == [[0, 15, 30, 37, 46]] * 5
    assert digest() == before


@pytest.mark.parametrize("other_duplicate", [False, True])
def test_mesh_local_face_keys_and_perimeter_summary_scope(
    ownership_hdf, other_duplicate
):
    with h5py.File(ownership_hdf, "r+") as hdf:
        areas = hdf["Geometry/2D Flow Areas"]
        attributes_dtype = areas["Attributes"].dtype
        del areas["Attributes"]
        areas.create_dataset(
            "Attributes",
            data=np.array([(b"Mesh", 2), (b"Other", 2)], dtype=attributes_dtype),
        )
        hdf.copy(areas["Mesh"], areas, name="Other")
        bc = hdf["Geometry/Boundary Condition Lines"]
        bc_dtype = bc["Attributes"].dtype
        del bc["Attributes"]
        bc.create_dataset(
            "Attributes",
            data=np.array(
                [
                    (b"Inflow", b"Mesh", b"Flow"),
                    (b"Outflow", b"Other", b"Stage"),
                    (b"Second", b"Other", b"Flow"),
                ],
                dtype=bc_dtype,
            ),
        )
        face_dtype = bc["External Faces"].dtype
        del bc["External Faces"]
        rows = [(0, 0, 0, 1), (1, 0, 0, 1)]
        if other_duplicate:
            rows.append((2, 0, 0, 1))
        bc.create_dataset("External Faces", data=np.array(rows, dtype=face_dtype))
    associations = HdfBndry.get_bc_external_faces(
        ownership_hdf, on_duplicate_ownership="report"
    )
    assert associations.attrs["unique_face_count"] == 2
    assert not associations.iloc[0].duplicate_ownership
    assert associations.iloc[0].owning_bc_line_ids == [0]
    assert associations.attrs["duplicate_face_count"] == int(other_duplicate)
    if not other_duplicate:
        assert len(HdfBndry.get_bc_external_faces(ownership_hdf)) == 2
    selected = HdfMesh.get_mesh_perimeter_faces(
        ownership_hdf, "Mesh", on_duplicate_ownership="report"
    )
    assert selected.attrs["duplicate_ownership"] == []
    assert selected.attrs["duplicate_face_count"] == 0
    assert selected.attrs["duplicate_face_row_count"] == 0
    assert selected.attrs["face_ownership_unique"] is True
    assert selected.iloc[0].bc_line_id == 0
    other = HdfMesh.get_mesh_perimeter_faces(
        ownership_hdf, "Other", on_duplicate_ownership="report"
    )
    assert other.attrs["duplicate_face_count"] == int(other_duplicate)
    assert other.attrs["duplicate_face_row_count"] == (2 if other_duplicate else 0)
    assert other.attrs["face_ownership_unique"] is (not other_duplicate)
    assert other.iloc[0].owning_bc_line_ids == ([1, 2] if other_duplicate else [1])
    if other_duplicate:
        assert other.attrs["duplicate_ownership"] == [
            {
                "mesh_name": "Other",
                "face_id": 0,
                "owning_bc_line_ids": [1, 2],
                "owning_bc_line_names": ["Outflow", "Second"],
            }
        ]


@pytest.mark.parametrize("missing", ["attributes", "bc_id", "both"])
def test_missing_metadata_reports_unknown_owners_without_losing_associations(
    ownership_hdf, missing
):
    with h5py.File(ownership_hdf, "r+") as hdf:
        bc = hdf["Geometry/Boundary Condition Lines"]
        if missing in ("attributes", "both"):
            del bc["Attributes"]
        if missing in ("bc_id", "both"):
            rows = bc["External Faces"][:]
            fields = [name for name in rows.dtype.names if name != "BC Line ID"]
            reduced = np.empty(
                len(rows), dtype=[(name, rows.dtype[name]) for name in fields]
            )
            for name in fields:
                reduced[name] = rows[name]
            del bc["External Faces"]
            bc.create_dataset("External Faces", data=reduced)
    with pytest.raises(ValueError, match="unique face ownership"):
        HdfBndry.get_bc_external_faces(ownership_hdf)
    result = HdfBndry.get_bc_external_faces(
        ownership_hdf, on_duplicate_ownership="report"
    )
    assert result.face_id.tolist() == [0, 0, 1]
    assert result.duplicate_ownership.tolist() == [True, True, False]
    assert result.mesh_name.isna().all()
    assert result.attrs["duplicate_ownership"][0]["mesh_name"] is None
    if missing == "attributes":
        assert result.owning_bc_line_ids.tolist() == [[0, 1], [0, 1], [0]]
        assert result.owning_bc_line_names.tolist() == [
            [None, None],
            [None, None],
            [None],
        ]
    else:
        assert result.bc_line_id.isna().all()
        assert result.owning_bc_line_ids.tolist() == [[None], [None], [None]]
        assert result.owning_bc_line_names.tolist() == [[None], [None], [None]]


@pytest.mark.parametrize("status", ["empty", "absent"])
def test_invalid_option_rejected_before_native_early_return(ownership_hdf, status):
    with h5py.File(ownership_hdf, "r+") as hdf:
        bc = hdf["Geometry/Boundary Condition Lines"]
        dtype = bc["External Faces"].dtype
        del bc["External Faces"]
        if status == "empty":
            bc.create_dataset("External Faces", data=np.empty(0, dtype=dtype))
        else:
            del hdf["Geometry/Boundary Condition Lines"]
    with pytest.raises(ValueError, match="on_duplicate_ownership"):
        HdfBndry.get_bc_external_faces(ownership_hdf, on_duplicate_ownership="ignore")
    with pytest.raises(ValueError, match="on_duplicate_ownership"):
        HdfMesh.get_mesh_perimeter_faces(
            ownership_hdf, "Mesh", on_duplicate_ownership="ignore"
        )
