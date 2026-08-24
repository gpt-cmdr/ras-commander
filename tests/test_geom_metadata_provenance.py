from pathlib import Path

import h5py
import numpy as np

from ras_commander.RasPrj import RasPrj
from ras_commander.geom.GeomMetadata import GeomMetadata


def _write_geometry_hdf(path: Path) -> None:
    xs_attributes = np.array(
        [(b"River A",), (b"River A",)],
        dtype=np.dtype([("River", "S32")]),
    )
    mesh_attributes = np.array(
        [(b"Mesh A",)],
        dtype=np.dtype([("Name", "S32")]),
    )

    with h5py.File(path, "w") as hdf:
        hdf.create_dataset("Geometry/Cross Sections/Attributes", data=xs_attributes)
        hdf.create_dataset("Geometry/2D Flow Areas/Attributes", data=mesh_attributes)
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Cell Info",
            data=np.array([[0, 4]], dtype=np.int64),
        )


def _text_2d_area(name: str, flag: int = -1) -> str:
    return (
        f"Storage Area={name},0,0\n"
        "Storage Area Surface Line= 4\n"
        f"Storage Area Is2D={flag}\n"
    )


def test_geometry_metadata_prefers_hdf_and_records_provenance(tmp_path):
    geom_path = tmp_path / "Model.g01"
    hdf_path = tmp_path / "Model.g01.hdf"
    geom_path.write_text(_text_2d_area("Text Mesh"), encoding="utf-8")
    _write_geometry_hdf(hdf_path)

    metadata = GeomMetadata.get_geometry_counts(geom_path, hdf_path)

    assert metadata["geometry_metadata_source"] == "hdf"
    assert metadata["geometry_metadata_valid"] is True
    assert metadata["geometry_metadata_error"] is None
    assert metadata["has_1d_xs"] is True
    assert metadata["has_2d_mesh"] is True
    assert metadata["num_cross_sections"] == 2
    assert metadata["mesh_area_names"] == ["Mesh A"]
    assert metadata["mesh_cell_count"] == 4


def test_geometry_metadata_falls_back_to_text_after_corrupt_hdf(tmp_path):
    geom_path = tmp_path / "Model.g02"
    hdf_path = tmp_path / "Model.g02.hdf"
    geom_path.write_text(
        "Geom Title=Fallback\n" + _text_2d_area("Fallback Mesh"),
        encoding="utf-8",
    )
    hdf_path.write_bytes(b"not an hdf file")

    metadata = GeomMetadata.get_geometry_counts(geom_path, hdf_path)

    assert metadata["geometry_metadata_source"] == "text"
    assert metadata["geometry_metadata_valid"] is True
    assert "HDF inspection failed" in metadata["geometry_metadata_error"]
    assert metadata["has_1d_xs"] is False
    assert metadata["has_2d_mesh"] is True
    assert metadata["mesh_area_names"] == ["Fallback Mesh"]
    assert metadata["mesh_cell_count"] is None


def test_text_parser_pairs_storage_area_name_with_is2d_flag(tmp_path):
    geom_path = tmp_path / "Model.g03"
    geom_path.write_text(
        "2D Flow Area=Fictional Marker,\n"
        + _text_2d_area("Reservoir", flag=0)
        + "From Storage Area=Not A Geometry Block\n"
        + _text_2d_area("Interior Mesh", flag=-1),
        encoding="utf-8",
    )

    metadata = GeomMetadata.get_geometry_counts(geom_path)

    assert metadata["geometry_metadata_source"] == "text"
    assert metadata["geometry_metadata_valid"] is True
    assert metadata["has_2d_mesh"] is True
    assert metadata["mesh_area_names"] == ["Interior Mesh"]
    assert metadata["mesh_cell_count"] is None


def test_hdf_cell_info_proves_2d_when_attributes_are_absent(tmp_path):
    hdf_path = tmp_path / "Model.g04.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Cell Info",
            data=np.array([[0, 12]], dtype=np.int64),
        )

    metadata = GeomMetadata.get_geometry_counts(None, hdf_path)

    assert metadata["geometry_metadata_source"] == "hdf"
    assert metadata["geometry_metadata_valid"] is True
    assert metadata["has_2d_mesh"] is True
    assert metadata["mesh_area_names"] == []
    assert metadata["mesh_cell_count"] == 12


def test_malformed_2d_attributes_fail_closed(tmp_path):
    hdf_path = tmp_path / "Model.g05.hdf"
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(
            "Geometry/2D Flow Areas/Attributes",
            data=np.array([(1,)], dtype=np.dtype([("Unexpected", "i4")])),
        )

    metadata = GeomMetadata.get_geometry_counts(None, hdf_path)

    assert metadata["geometry_metadata_source"] == "unavailable"
    assert metadata["geometry_metadata_valid"] is False
    assert "has no Name field" in metadata["geometry_metadata_error"]
    assert metadata["has_1d_xs"] is None
    assert metadata["has_2d_mesh"] is None


def test_geometry_metadata_is_unknown_when_no_source_is_available(tmp_path):
    metadata = GeomMetadata.get_geometry_counts(
        tmp_path / "Missing.g06",
        tmp_path / "Missing.g06.hdf",
    )

    assert metadata["geometry_metadata_source"] == "unavailable"
    assert metadata["geometry_metadata_valid"] is False
    assert metadata["geometry_metadata_error"] == (
        "Neither HDF nor geometry file exists"
    )
    assert metadata["has_1d_xs"] is None
    assert metadata["has_2d_mesh"] is None


def test_geom_df_exposes_derived_geometry_type(tmp_path):
    prj_path = tmp_path / "Model.prj"
    geom_path = tmp_path / "Model.g01"
    hdf_path = tmp_path / "Model.g01.hdf"
    prj_path.write_text("Proj Title=Model\nGeom File=g01\n", encoding="utf-8")
    geom_path.write_text("Geom Title=Mixed Geometry\n", encoding="utf-8")
    _write_geometry_hdf(hdf_path)

    project = RasPrj()
    project.initialized = True
    project.prj_file = prj_path
    project.project_folder = tmp_path
    project.project_name = "Model"
    project.suppress_logging = True

    geom_df = project.get_geom_entries()

    assert geom_df.loc[0, "geometry_type"] == "1D/2D"
    assert geom_df.loc[0, "geometry_metadata_source"] == "hdf"
    assert bool(geom_df.loc[0, "geometry_metadata_valid"])
    assert str(geom_df["has_2d_mesh"].dtype) == "boolean"
    assert str(geom_df["mesh_cell_count"].dtype) == "Int64"
