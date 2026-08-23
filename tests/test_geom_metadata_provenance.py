from pathlib import Path

import h5py
import numpy as np

from ras_commander.geom.GeomMetadata import GeomMetadata
from ras_commander.RasPrj import RasPrj


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


def test_geometry_metadata_prefers_hdf_and_records_provenance(tmp_path):
    geom_path = tmp_path / "Model.g01"
    hdf_path = tmp_path / "Model.g01.hdf"
    geom_path.write_text("2D Flow Area=Text Mesh,\n", encoding="utf-8")
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
    geom_path.write_text("Geom Title=Fallback\n2D Flow Area=Fallback Mesh,\n", encoding="utf-8")
    hdf_path.write_bytes(b"not an hdf file")

    metadata = GeomMetadata.get_geometry_counts(geom_path, hdf_path)

    assert metadata["geometry_metadata_source"] == "text"
    assert metadata["geometry_metadata_valid"] is True
    assert "HDF inspection failed" in metadata["geometry_metadata_error"]
    assert metadata["has_1d_xs"] is False
    assert metadata["has_2d_mesh"] is True
    assert metadata["mesh_area_names"] == ["Fallback Mesh"]


def test_geometry_metadata_is_unknown_when_no_source_is_available(tmp_path):
    metadata = GeomMetadata.get_geometry_counts(
        tmp_path / "Missing.g03",
        tmp_path / "Missing.g03.hdf",
    )

    assert metadata["geometry_metadata_source"] == "unavailable"
    assert metadata["geometry_metadata_valid"] is False
    assert metadata["geometry_metadata_error"] == "Neither HDF nor geometry file exists"
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
