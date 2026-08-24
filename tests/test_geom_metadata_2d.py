"""Regression tests for 2D topology metadata from plain geometry text."""

from pathlib import Path

import pytest

from ras_commander.geom.GeomMetadata import GeomMetadata


def _write_geometry(path: Path, is_2d_value: str) -> Path:
    path.write_text(
        "".join(
            [
                "Geom Title=2D metadata fixture\n",
                "Storage Area=Mesh Area,100,200\n",
                f"Storage Area Is2D={is_2d_value}\n",
                "Storage Area 2D Points= 0\n",
                "Storage Area=Reservoir Pool,300,400\n",
                "Storage Area Is2D=0\n",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_geometry_counts_recognizes_canonical_2d_storage_area(tmp_path: Path) -> None:
    geom_path = _write_geometry(tmp_path / "Model.g01", "-1")

    counts = GeomMetadata.get_geometry_counts(geom_path, hdf_path=None)

    assert counts["has_2d_mesh"] is True
    assert counts["mesh_area_names"] == ["Mesh Area"]
    assert counts["mesh_cell_count"] is None
    assert counts["geometry_metadata_source"] == "text"
    assert counts["geometry_metadata_valid"] is True


def test_geometry_counts_ignores_non_hecras_2d_flow_area_record(tmp_path: Path) -> None:
    geom_path = tmp_path / "Legacy.g01"
    geom_path.write_text(
        "Geom Title=Legacy 2D metadata fixture\n"
        "2D Flow Area=Legacy Mesh,100,200\n",
        encoding="utf-8",
    )

    counts = GeomMetadata.get_geometry_counts(geom_path, hdf_path=None)

    assert counts["has_2d_mesh"] is False
    assert counts["mesh_area_names"] == []


@pytest.mark.parametrize("is_2d_value", ["0", "1"])
def test_geometry_counts_treats_non_2d_flags_as_storage_areas(
    tmp_path: Path,
    is_2d_value: str,
) -> None:
    geom_path = _write_geometry(tmp_path / "Model.g01", is_2d_value)

    counts = GeomMetadata.get_geometry_counts(geom_path, hdf_path=None)

    assert counts["has_2d_mesh"] is False
    assert counts["mesh_area_names"] == []


@pytest.mark.parametrize("is_2d_value", ["-1.0", "unknown", ""])
def test_geometry_counts_fails_closed_for_malformed_2d_values(
    tmp_path: Path,
    is_2d_value: str,
) -> None:
    geom_path = _write_geometry(tmp_path / "Model.g01", is_2d_value)

    counts = GeomMetadata.get_geometry_counts(geom_path, hdf_path=None)

    assert counts["has_2d_mesh"] is None
    assert counts["geometry_metadata_source"] == "unavailable"
    assert counts["geometry_metadata_valid"] is False
    assert "Invalid Storage Area Is2D flag" in counts["geometry_metadata_error"]


def test_plain_text_only_counts_do_not_mutate_hdf_mesh_metadata(tmp_path: Path) -> None:
    geom_path = _write_geometry(tmp_path / "Model.g01", "-1")
    counts = GeomMetadata.DEFAULT_COUNTS.copy()
    counts["mesh_area_names"] = ["HDF Area"]
    counts["mesh_cell_count"] = 123

    result = GeomMetadata._add_text_only_counts(geom_path, counts)

    assert result["mesh_area_names"] == ["HDF Area"]
    assert result["mesh_cell_count"] == 123
