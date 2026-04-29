from pathlib import Path

import h5py
import numpy as np

from ras_commander.sources.federal.ebfe_models import RasEbfeModels


def _write_geom_hdf(path: Path, land_cover_filename: str) -> None:
    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Land Cover Filename"] = np.bytes_(land_cover_filename)


def _read_land_cover_attr(path: Path) -> str:
    with h5py.File(path, "r") as hdf:
        return hdf["Geometry"].attrs["Land Cover Filename"].decode("utf-8")


def test_spring_river_legacy_land_classification_copy_is_preserved(tmp_path):
    project = tmp_path
    land_cover = project / "Land Cover"
    land_cover.mkdir()
    (land_cover / "LandCover (1).hdf").write_bytes(b"hdf")
    (land_cover / "LandCover (1).tif").write_bytes(b"tif")
    geom_hdf = project / "Spring_BLE.g01.hdf"
    _write_geom_hdf(
        geom_hdf,
        r".\Land Classification\LandCover (1).hdf",
    )

    copied = RasEbfeModels._standardize_legacy_land_classification_assets(project)
    updated = RasEbfeModels._standardize_hdf_asset_references(project)

    assert copied["legacy_land_classification_assets_copied"] == 2
    assert (project / "Land Classification" / "LandCover (1).hdf").exists()
    assert (project / "Land Classification" / "LandCover (1).tif").exists()
    assert updated["hdf_asset_references_updated"] == 0
    assert (
        _read_land_cover_attr(geom_hdf)
        == r".\Land Classification\LandCover (1).hdf"
    )
