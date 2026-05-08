from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import HdfStorageArea, RasExamples


pytest.importorskip("rasterio")


@pytest.fixture(scope="module")
def bald_eagle_project(tmp_path_factory) -> Path:
    output_root = tmp_path_factory.mktemp("hdf_storage_area")
    return RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=output_root)


@pytest.fixture(scope="module")
def storage_geom_hdf(bald_eagle_project: Path) -> Path:
    geom_hdf = bald_eagle_project / "BaldEagleDamBrk.g06.hdf"
    if not geom_hdf.exists():
        pytest.skip(f"Expected storage-area geometry HDF not available: {geom_hdf}")
    return geom_hdf


def _hdf_storage_volume_elevation_row(
    geom_hdf: Path,
    storage_area_name: str,
) -> tuple[float, float]:
    with h5py.File(geom_hdf, "r") as hdf_file:
        sa_group = hdf_file["Geometry/Storage Areas"]
        attrs = sa_group["Attributes"][()]
        names = [row["Name"].decode("utf-8").strip() for row in attrs]
        index = names.index(storage_area_name)

        start, count = sa_group["Volume Elevation Info"][index]
        table = sa_group["Volume Elevation Values"][start:start + count]
        max_elevation_idx = int(np.nanargmax(table[:, 1]))
        volume, elevation = table[max_elevation_idx]
        return float(volume), float(elevation)


def test_storage_area_names_perimeter_properties_and_terrain(storage_geom_hdf: Path):
    names = HdfStorageArea.get_storage_area_names(storage_geom_hdf)
    assert names == ["190", "195", "255"]

    polygon = HdfStorageArea._get_perimeter_polygon(storage_geom_hdf, "190")
    assert polygon is not None
    assert polygon.is_valid
    assert polygon.area > 0

    properties = HdfStorageArea.get_storage_area_properties(storage_geom_hdf, "190")
    assert properties["Name"] == "190"
    assert properties["mode"] == "Elev Vol RC"
    assert properties["elev_vol_count"] == 22

    terrain_path = HdfStorageArea.get_terrain_path_from_geom_hdf(storage_geom_hdf)
    assert terrain_path is not None
    assert terrain_path.name == "Terrain50.vrt"
    assert terrain_path.exists()


def test_compute_stage_storage_curve_returns_dataframe_and_metadata(
    storage_geom_hdf: Path,
):
    curve, metadata = HdfStorageArea.compute_stage_storage_curve(
        storage_geom_hdf,
        "190",
        elevation_interval=5.0,
        min_elevation=590.0,
        max_elevation=600.0,
    )

    assert isinstance(curve, pd.DataFrame)
    assert list(curve.columns) == ["stage", "storage"]
    assert curve["stage"].tolist() == [590.0, 595.0, 600.0]
    assert curve["storage"].is_monotonic_increasing
    assert metadata["storage_area_name"] == "190"
    assert curve.attrs["storage_area"] == "190"
    assert metadata["storage_units"] == "cubic project units"


def test_get_volume_elevation_curve_matches_raw_hdf(storage_geom_hdf: Path):
    df = HdfStorageArea.get_volume_elevation_curve(storage_geom_hdf, "190")
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["elevation", "volume"]
    assert len(df) > 0

    raw_volume, raw_elevation = _hdf_storage_volume_elevation_row(storage_geom_hdf, "190")
    max_row = df.loc[df["elevation"].idxmax()]
    assert max_row["elevation"] == pytest.approx(raw_elevation, abs=1e-6)
    assert max_row["volume"] == pytest.approx(raw_volume, abs=1e-6)


def test_computed_volume_matches_hdf_storage_curve_with_unit_conversion(
    storage_geom_hdf: Path,
):
    terrain_path = HdfStorageArea.get_terrain_path_from_geom_hdf(storage_geom_hdf)
    polygon = HdfStorageArea._get_perimeter_polygon(storage_geom_hdf, "190")
    hdf_volume_acre_ft, hdf_elevation = _hdf_storage_volume_elevation_row(
        storage_geom_hdf,
        "190",
    )

    computed_cubic_ft = HdfStorageArea.compute_volume_below_elevation(
        terrain_path,
        polygon,
        hdf_elevation,
    )
    computed_acre_ft = computed_cubic_ft / 43560.0

    assert computed_acre_ft == pytest.approx(hdf_volume_acre_ft, rel=0.05)


def test_storage_area_for_structure_matches_structure_attributes(
    storage_geom_hdf: Path,
):
    assert (
        HdfStorageArea.get_storage_area_for_breach_structure(
            storage_geom_hdf,
            "Bald Eagle Cr., Lock Haven (5999)",
        )
        == "190"
    )

