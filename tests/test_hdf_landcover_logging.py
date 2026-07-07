"""Logging behavior tests for HdfLandCover notebook-facing APIs."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfLandCover


LOGGER_NAME = "ras_commander.hdf.HdfLandCover"


def _write_empty_geom_hdf(path: Path) -> None:
    with h5py.File(path, "w") as hdf_file:
        hdf_file.create_group("Geometry")


def _write_geom_hdf_with_landcover_attr(path: Path, landcover_attr: str) -> None:
    with h5py.File(path, "w") as hdf_file:
        geometry = hdf_file.create_group("Geometry")
        geometry.attrs["Land Cover Filename"] = landcover_attr


def _write_landcover_sidecar(path: Path) -> None:
    raster_map_dtype = np.dtype([("ID", "<i4"), ("Name", "S64")])
    raster_map = np.array(
        [
            (11, b"Open Water"),
            (31, b"Barren Land"),
        ],
        dtype=raster_map_dtype,
    )
    variables_dtype = np.dtype(
        [
            ("Name", "S64"),
            ("ManningsN", "<f8"),
            ("Percent Impervious", "<f8"),
        ]
    )
    variables = np.array(
        [
            (b"Open Water", 0.03, 0.0),
            (b"Barren Land", 0.12, 0.0),
        ],
        dtype=variables_dtype,
    )

    with h5py.File(path, "w") as hdf_file:
        hdf_file.create_dataset("Raster Map", data=raster_map)
        hdf_file.create_dataset("Variables", data=variables)


def _write_sidecar_without_raster_map(path: Path) -> None:
    variables_dtype = np.dtype(
        [
            ("Name", "S64"),
            ("ManningsN", "<f8"),
        ]
    )
    variables = np.array([(b"Open Water", 0.03)], dtype=variables_dtype)

    with h5py.File(path, "w") as hdf_file:
        hdf_file.create_dataset("Variables", data=variables)


def _write_multipart_regions_without_parts(path: Path) -> None:
    attrs_dtype = np.dtype([("Name", "S64")])
    attrs = np.array([(b"Region A",), (b"Region B",)], dtype=attrs_dtype)
    polygon_info = np.array(
        [
            (0, 5, 0, 2),
            (5, 5, 0, 2),
        ],
        dtype=np.int32,
    )
    points = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
            [0.0, 0.0],
            [2.0, 2.0],
            [3.0, 2.0],
            [3.0, 3.0],
            [2.0, 3.0],
            [2.0, 2.0],
        ],
        dtype=np.float64,
    )

    with h5py.File(path, "w") as hdf_file:
        landcover = hdf_file.create_group("Geometry/Land Cover (Manning's n)")
        landcover.create_dataset("Attributes", data=attrs)
        landcover.create_dataset("Polygon Info", data=polygon_info)
        landcover.create_dataset("Polygon Points", data=points)


def _write_landcover_tif(path: Path) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype=np.int16,
        crs="EPSG:5070",
        transform=from_origin(0.0, 20.0, 10.0, 10.0),
        nodata=-9999,
    ) as dst:
        dst.write(np.array([[11, 31], [31, 11]], dtype=np.int16), 1)


def _hdf_landcover_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == LOGGER_NAME
    ]


def test_missing_optional_landcover_metadata_does_not_warn(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Absent optional Manning's n metadata should not appear in default output."""
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_empty_geom_hdf(geom_hdf)

    pytest.importorskip("geopandas")
    with caplog.at_level("WARNING", logger=LOGGER_NAME):
        mannings = HdfLandCover.get_preprocessed_mannings_n(geom_hdf)
        calibration = HdfLandCover.get_mannings_calibration_table(geom_hdf)
        regions = HdfLandCover.get_mannings_region_polygons(geom_hdf)

    assert mannings.empty
    assert calibration is None
    assert regions.empty
    assert _hdf_landcover_messages(caplog) == []


def test_missing_landcover_association_target_warns_concisely(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Missing associated sidecars should name the files without full paths."""
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_geom_hdf_with_landcover_attr(geom_hdf, "LandCover_missing.hdf")

    with caplog.at_level("WARNING", logger=LOGGER_NAME):
        result = HdfLandCover.get_landcover_association(geom_hdf)

    assert result is None
    messages = _hdf_landcover_messages(caplog)
    assert messages == [
        "Land cover sidecar LandCover_missing.hdf referenced by "
        "model.g01.hdf was not found"
    ]
    assert str(tmp_path) not in "\n".join(messages)


def test_missing_raster_map_warning_is_concise(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Required sidecar datasets should be identified without full paths."""
    sidecar = tmp_path / "LandCover.hdf"
    _write_sidecar_without_raster_map(sidecar)

    with caplog.at_level("WARNING", logger=LOGGER_NAME):
        result = HdfLandCover.get_landcover_raster_map(sidecar)

    assert result is None
    messages = _hdf_landcover_messages(caplog)
    assert messages == [
        "No Raster Map dataset found in land cover sidecar LandCover.hdf"
    ]
    assert str(tmp_path) not in "\n".join(messages)


def test_missing_final_raster_dependencies_log_concisely(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Final-raster failures should be actionable without full paths by default."""
    pytest.importorskip("rasterio")
    geom_hdf = tmp_path / "model.g01.hdf"
    sidecar = tmp_path / "LandCover.hdf"
    _write_empty_geom_hdf(geom_hdf)
    _write_landcover_sidecar(sidecar)

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        no_association = HdfLandCover.compute_final_mannings_raster(geom_hdf)
        missing_tif = HdfLandCover.compute_final_mannings_raster(
            geom_hdf,
            landcover_hdf_path=sidecar,
        )

    assert no_association is None
    assert missing_tif is None
    messages = _hdf_landcover_messages(caplog)
    assert messages == [
        "No land cover sidecar association found in model.g01.hdf; assign one "
        "in RASMapper Manage Associations before computing final Manning's n raster",
        "Land cover TIF not found for sidecar LandCover.hdf",
    ]
    assert str(tmp_path) not in "\n".join(messages)


def test_missing_polygon_parts_warning_is_collapsed(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """A malformed polygon-parts dataset should warn once, not once per polygon."""
    pytest.importorskip("geopandas")
    geom_hdf = tmp_path / "model.g01.hdf"
    _write_multipart_regions_without_parts(geom_hdf)

    with caplog.at_level("WARNING", logger=LOGGER_NAME):
        regions = HdfLandCover.get_mannings_region_polygons(geom_hdf)

    assert len(regions) == 2
    messages = _hdf_landcover_messages(caplog)
    assert messages == [
        "'Polygon Parts' dataset missing for 2 multi-part Manning's n "
        "calibration polygon(s); using raw point order as polygon shells"
    ]


def test_set_landcover_raster_map_info_is_concise(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Successful sidecar writes should summarize without full paths at INFO."""
    sidecar = tmp_path / "LandCover.hdf"
    _write_landcover_sidecar(sidecar)

    with caplog.at_level("INFO", logger=LOGGER_NAME):
        result = HdfLandCover.set_landcover_raster_map(
            sidecar,
            {"Open Water": 0.04},
        )

    assert result["changed"] == 1
    assert Path(result["backup_path"]).exists()
    messages = _hdf_landcover_messages(caplog)
    assert messages == [
        "Updated land cover sidecar LandCover.hdf: "
        "format=v6_modern, changed=1, unchanged=1"
    ]
    assert str(tmp_path) not in "\n".join(messages)


def test_compute_final_mannings_raster_info_is_concise(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    """Raster computation should leave one concise INFO summary plus output name."""
    geom_hdf = tmp_path / "model.g01.hdf"
    sidecar = tmp_path / "LandCover.hdf"
    output_tif = tmp_path / "final_n.tif"
    _write_empty_geom_hdf(geom_hdf)
    _write_landcover_sidecar(sidecar)
    _write_landcover_tif(sidecar.with_suffix(".tif"))

    with caplog.at_level("INFO", logger=LOGGER_NAME):
        final_raster = HdfLandCover.compute_final_mannings_raster(
            geom_hdf,
            landcover_hdf_path=sidecar,
            output_tif_path=output_tif,
        )

    assert final_raster is not None
    assert final_raster.shape == (2, 2)
    assert output_tif.exists()
    messages = _hdf_landcover_messages(caplog)
    assert messages == [
        "Final Manning's n: shape=(2, 2), range=0.0300-0.1200, mean=0.0750",
        "Wrote final Manning's n raster: final_n.tif",
    ]
    assert "Reading land cover TIF" not in "\n".join(messages)
    assert str(tmp_path) not in "\n".join(messages)
