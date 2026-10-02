"""Logging behavior tests for HdfBndry geometry extraction APIs."""

from pathlib import Path

import h5py
import numpy as np
import pytest
from pyproj import CRS

from ras_commander.hdf import HdfBndry


LOGGER_NAME = "ras_commander.hdf.HdfBndry"


def _hdf_bndry_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME
    ]


def _write_empty_geometry_hdf(path: Path) -> None:
    with h5py.File(path, "w") as hdf_file:
        hdf_file.create_group("Geometry")


def _write_invalid_breaklines_hdf(path: Path) -> None:
    attributes_dtype = np.dtype([("Name", "S32")])
    attributes = np.array(
        [(b"ZeroLength",), (b"SinglePoint",), (b"MultipartInvalid",)],
        dtype=attributes_dtype,
    )

    with h5py.File(path, "w") as hdf_file:
        group = hdf_file.create_group("Geometry/2D Flow Area Break Lines")
        group.create_dataset("Attributes", data=attributes)
        group.create_dataset(
            "Polyline Info",
            data=np.array(
                [
                    (0, 0, 0, 1),
                    (0, 1, 0, 1),
                    (0, 2, 0, 2),
                ],
                dtype=np.int32,
            ),
        )
        group.create_dataset(
            "Polyline Parts",
            data=np.array([(0, 1), (1, 1)], dtype=np.int32),
        )
        group.create_dataset(
            "Polyline Points",
            data=np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float64),
        )


def _write_reference_lines_without_type_hdf(path: Path) -> None:
    attributes_dtype = np.dtype([("Name", "S32"), ("SA-2D", "S32")])
    attributes = np.array([(b"Line A", b"Mesh 1")], dtype=attributes_dtype)

    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["Projection"] = CRS.from_epsg(4326).to_wkt()
        group = hdf_file.create_group("Geometry/Reference Lines")
        group.create_dataset("Attributes", data=attributes)
        group.create_dataset(
            "Polyline Info",
            data=np.array([(0, 2, 0, 1)], dtype=np.int32),
        )
        group.create_dataset("Polyline Parts", data=np.array([(0, 2)], dtype=np.int32))
        group.create_dataset(
            "Polyline Points",
            data=np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float64),
        )


def _write_valid_breakline_attributes_hdf(path: Path) -> None:
    attributes_dtype = np.dtype(
        [
            ("Name", "S32"),
            ("Cell Spacing Near", "<f4"),
            ("Cell Spacing Far", "<f4"),
            ("Near Repeats", "u1"),
            ("Protection Radius", "u1"),
        ]
    )
    attributes = np.array(
        [(b"Channel", 20.0, 40.0, 2, 1)],
        dtype=attributes_dtype,
    )
    with h5py.File(path, "w") as hdf_file:
        group = hdf_file.create_group("Geometry/2D Flow Area Break Lines")
        group.create_dataset("Attributes", data=attributes)
        group.create_dataset(
            "Polyline Info", data=np.array([(0, 2, 0, 1)], dtype=np.int32)
        )
        group.create_dataset(
            "Polyline Parts", data=np.array([(0, 2)], dtype=np.int32)
        )
        group.create_dataset(
            "Polyline Points",
            data=np.array([[0.0, 0.0], [1.0, 1.0]], dtype=np.float64),
        )


def test_breakline_reader_exposes_mesh_generation_attributes(tmp_path: Path):
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_valid_breakline_attributes_hdf(geom_hdf)

    result = HdfBndry.get_breaklines(geom_hdf)

    assert result["Name"].tolist() == ["Channel"]
    assert result["cell_spacing_near"].tolist() == [20.0]
    assert result["cell_spacing_far"].tolist() == [40.0]
    assert result["near_repeats"].tolist() == [2]
    assert result["protection_radius"].tolist() == [1]


def test_optional_missing_boundary_groups_are_quiet_by_default(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_empty_geometry_hdf(geom_hdf)

    with caplog.at_level("WARNING", logger=LOGGER_NAME):
        assert HdfBndry.get_bc_lines(geom_hdf).empty
        assert HdfBndry.get_breaklines(geom_hdf).empty
        assert HdfBndry.get_refinement_regions(geom_hdf).empty
        assert HdfBndry.get_reference_lines(geom_hdf).empty
        assert HdfBndry.get_reference_points(geom_hdf).empty

    assert _hdf_bndry_messages(caplog) == []


def test_optional_missing_boundary_groups_log_debug_context(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_empty_geometry_hdf(geom_hdf)

    with caplog.at_level("DEBUG", logger=LOGGER_NAME):
        HdfBndry.get_breaklines(geom_hdf)
        HdfBndry.get_reference_lines(geom_hdf)

    messages = _hdf_bndry_messages(caplog)
    assert any("Breaklines group" in message for message in messages)
    assert any("Reference lines attributes group" in message for message in messages)
    optional_group_messages = [
        message
        for message in messages
        if "Breaklines group" in message
        or "Reference lines attributes group" in message
    ]
    assert all(str(tmp_path) not in message for message in optional_group_messages)


@pytest.mark.parametrize("invalid_record", [2])
def test_invalid_breaklines_raise_and_log_full_context(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    invalid_record: int,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_invalid_breaklines_hdf(geom_hdf)
    # Isolate the malformed multipart record; degenerate records are diagnostics.
    with h5py.File(geom_hdf, "r+") as hdf_file:
        group = hdf_file["Geometry/2D Flow Area Break Lines"]
        attributes = group["Attributes"][()][invalid_record:invalid_record + 1]
        info = group["Polyline Info"][()][invalid_record:invalid_record + 1]
        del group["Attributes"]
        del group["Polyline Info"]
        group.create_dataset("Attributes", data=attributes)
        group.create_dataset("Polyline Info", data=info)

    with caplog.at_level("ERROR", logger=LOGGER_NAME), pytest.raises(ValueError):
        HdfBndry.get_breaklines(geom_hdf)

    messages = _hdf_bndry_messages(caplog)
    assert messages
    assert any(str(geom_hdf) in message and "Geometry/2D Flow Area Break Lines" in message
               for message in messages)


def test_boundary_parse_errors_include_hdf_path_and_group(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    with h5py.File(geom_hdf, "w") as hdf_file:
        hdf_file.create_group("Geometry/Boundary Condition Lines")

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = HdfBndry.get_bc_lines(geom_hdf)

    assert result.empty
    messages = _hdf_bndry_messages(caplog)
    assert len(messages) == 1
    assert str(geom_hdf) in messages[0]
    assert "Geometry/Boundary Condition Lines" in messages[0]


def test_reference_line_missing_type_logs_debug_fallback(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_reference_lines_without_type_hdf(geom_hdf)

    with caplog.at_level("DEBUG", logger=LOGGER_NAME):
        result = HdfBndry.get_reference_lines(geom_hdf)

    assert len(result) == 1
    assert result["Type"].tolist() == [""]
    messages = _hdf_bndry_messages(caplog)
    assert any("using blank Type values" in message for message in messages)


@pytest.mark.parametrize("point_count", [0, 1])
@pytest.mark.parametrize("valid_line", [False, True])
def test_degenerate_breaklines_keep_native_diagnostics(tmp_path, point_count, valid_line):
    import json

    path = tmp_path / "model.g01.hdf"
    _write_valid_breakline_attributes_hdf(path)
    with h5py.File(path, "r+") as hdf_file:
        group = hdf_file["Geometry/2D Flow Area Break Lines"]
        attributes = group["Attributes"][()]
        row = attributes.copy()
        row["Name"] = b"Pankratz Rd (3)"
        attributes = np.concatenate([attributes, row]) if valid_line else row
        info = [(0, 2, 0, 1), (1, point_count, 0, 1)] if valid_line else [(1, point_count, 0, 1)]
        del group["Attributes"]
        del group["Polyline Info"]
        group.create_dataset("Attributes", data=attributes)
        group.create_dataset("Polyline Info", data=np.array(info, dtype=np.int32))
    result = HdfBndry.get_breaklines(str(path))
    assert len(result) == int(valid_line)
    diagnostics = result.attrs["breakline_diagnostics"]
    assert len(diagnostics) == 1
    record = diagnostics[0]
    assert record == {
        "bl_id": int(valid_line), "Name": "Pankratz Rd (3)",
        "attributes": {"Name": "Pankratz Rd (3)", "Cell Spacing Near": 20.0,
                       "Cell Spacing Far": 40.0, "Near Repeats": 2, "Protection Radius": 1},
        "point_start": 1, "point_count": point_count, "point_end": 1 + point_count,
        "part_start": 0, "part_count": 1, "reason_code": "BREAKLINE_TOO_FEW_POINTS",
    }
    json.dumps(diagnostics)
    if valid_line:
        assert result["bl_id"].tolist() == [0]
        assert list(result.geometry.iloc[0].coords) == [(0.0, 0.0), (1.0, 1.0)]


@pytest.mark.parametrize("span", [(-1, 1, 0, 1), (0, -1, 0, 1), (3, 0, 0, 1),
                                  (2, 1, 0, 1), (1, 2, 0, 1), (0, 1, -1, 1),
                                  (0, 1, 0, -1), (0, 1, 1, 1)])
def test_corrupt_degenerate_or_truncated_spans_remain_hard_errors(tmp_path, span):
    path = tmp_path / "model.g01.hdf"
    _write_valid_breakline_attributes_hdf(path)
    with h5py.File(path, "r+") as hdf_file:
        dataset = hdf_file["Geometry/2D Flow Area Break Lines/Polyline Info"]
        dataset[0] = span
    with pytest.raises(ValueError):
        HdfBndry.get_breaklines(path)


def test_clean_and_missing_breaklines_have_empty_diagnostics(tmp_path):
    path = tmp_path / "model.g01.hdf"
    _write_valid_breakline_attributes_hdf(path)
    assert HdfBndry.get_breaklines(path).attrs["breakline_diagnostics"] == []
    _write_empty_geometry_hdf(path)
    assert HdfBndry.get_breaklines(path).attrs["breakline_diagnostics"] == []


def test_degenerate_breakline_does_not_renumber_following_native_ids(tmp_path):
    path = tmp_path / "model.g01.hdf"
    _write_valid_breakline_attributes_hdf(path)
    with h5py.File(path, "r+") as hdf_file:
        group = hdf_file["Geometry/2D Flow Area Break Lines"]
        attributes = np.repeat(group["Attributes"][()], 3)
        attributes["Name"] = [b"First", b"SinglePoint", b"Last"]
        del group["Attributes"]
        del group["Polyline Info"]
        group.create_dataset("Attributes", data=attributes)
        group.create_dataset("Polyline Info", data=np.array(
            [(0, 2, 0, 1), (1, 1, 0, 1), (0, 2, 0, 1)], dtype=np.int32))
    result = HdfBndry.get_breaklines(path)
    assert result["bl_id"].tolist() == [0, 2]
    assert result["Name"].tolist() == ["First", "Last"]
    assert result.attrs["breakline_diagnostics"][0]["bl_id"] == 1
