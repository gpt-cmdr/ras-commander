"""Unit gates for native RASMapper land-cover contracts."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander._landcover_native import (
    _native_extent,
    validate_native_landcover,
)
from ras_commander.geom import GeomLandCover, GeomPreprocessor
from ras_commander.hdf import HdfLandCover


class _Extent:
    def __init__(self, *values):
        self.values = values


def test_native_extent_uses_rasmapper_constructor_order():
    extent = _native_extent(
        (1.0, 2.0, 11.0, 22.0),
        buffer_distance=3.0,
        extent_cls=_Extent,
    )

    assert extent.values == (14.0, -2.0, 25.0, -1.0)


@pytest.mark.parametrize("legacy", [True, False])
def test_validate_native_landcover_accepts_native_layout(
    tmp_path: Path,
    legacy: bool,
):
    rasterio = pytest.importorskip("rasterio")
    hdf_path = tmp_path / "LandCover.hdf"
    tif_path = hdf_path.with_suffix(".tif")

    with h5py.File(hdf_path, "w") as hdf:
        if legacy:
            hdf.create_dataset("IDs", data=np.array([0, 1, 2], dtype=np.uint8))
            hdf.create_dataset("Names", data=np.array([b"NoData", b"A", b"B"]))
            hdf.create_dataset(
                "ManningsN",
                data=np.array([np.finfo(np.float32).max, 0.03, 0.08]),
            )
        else:
            dtype = np.dtype([("ID", "<i4"), ("Name", "S16")])
            hdf.create_dataset(
                "Raster Map",
                data=np.array([(0, b"NoData"), (1, b"A"), (2, b"B")], dtype=dtype),
            )
            variables_dtype = np.dtype(
                [("Name", "S16"), ("ManningsN", "<f4")]
            )
            hdf.create_dataset(
                "Variables",
                data=np.array(
                    [(b"NoData", np.finfo(np.float32).max), (b"A", 0.03), (b"B", 0.08)],
                    dtype=variables_dtype,
                ),
            )

    data = np.tile(np.array([0, 1, 2, 1], dtype=np.uint8), (32, 8))
    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        width=32,
        height=32,
        count=1,
        dtype=data.dtype,
        transform=rasterio.transform.from_origin(0, 32, 1, 1),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="deflate",
    ) as raster:
        raster.write(data, 1)

    report = validate_native_landcover(
        hdf_path,
        expected_class_ids={1, 2},
        legacy=legacy,
    )

    assert report["raster_class_ids"] == [0, 1, 2]
    assert report["legacy_schema"] is legacy


def _write_result_hdf(
    path: Path,
    face_values: list[float],
    *,
    cell_values: list[float] | None = None,
    complete: bool = True,
) -> None:
    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Complete Geometry"] = "True" if complete else "False"
        geometry.attrs["Land Cover Filename"] = r".\LandCover\Native.hdf"
        geometry.attrs["Land Cover Layername"] = "Native"
        area = geometry.create_group("2D Flow Areas").create_group("Mesh")
        faces = np.zeros((len(face_values), 4), dtype=np.float64)
        faces[:, 3] = face_values
        area.create_dataset("Faces Area Elevation Values", data=faces)
        if cell_values is not None:
            area.create_dataset(
                "Cells Center Manning's n",
                data=np.asarray(cell_values, dtype=np.float64),
            )


def test_final_mannings_audit_rejects_floating_noise(tmp_path: Path):
    result = tmp_path / "noise.p01.hdf"
    _write_result_hdf(result, [0.035000, 0.035003])

    with pytest.raises(RuntimeError, match="not materially diverse"):
        HdfLandCover.audit_final_mannings_n(result, tolerance=1.0e-4)


def test_final_mannings_audit_accepts_ras5_face_values(tmp_path: Path):
    result = tmp_path / "legacy.p01.hdf"
    _write_result_hdf(result, [0.03, 0.04, 0.08])

    report = HdfLandCover.audit_final_mannings_n(
        result,
        expected_values=[0.03, 0.08],
    )

    assert bool(report.loc[0, "passed"])
    assert report.loc[0, "cell_value_count"] == 0
    assert report.loc[0, "face_distinct_count"] == 3


def test_final_mannings_audit_accepts_ras6_cell_and_face_values(tmp_path: Path):
    result = tmp_path / "modern.p01.hdf"
    _write_result_hdf(
        result,
        [0.03, 0.04, 0.08],
        cell_values=[0.03, 0.04, 0.08],
    )

    report = HdfLandCover.audit_final_mannings_n(result)

    assert bool(report.loc[0, "passed"])
    assert report.loc[0, "cell_distinct_count"] == 3


def test_final_mannings_audit_requires_complete_geometry(tmp_path: Path):
    result = tmp_path / "incomplete.p01.hdf"
    _write_result_hdf(result, [0.03, 0.08], complete=False)

    with pytest.raises(RuntimeError, match="does not mark geometry complete"):
        HdfLandCover.audit_final_mannings_n(result)


def test_solver_owned_hdf_mutation_apis_fail_closed(tmp_path: Path):
    with pytest.raises(NotImplementedError, match="Direct writes"):
        GeomLandCover.override_2d_mannings_n(
            tmp_path / "model.g01.hdf",
            0.04,
        )
    with pytest.raises(NotImplementedError, match="Selective deletion"):
        GeomPreprocessor.clear_geompre_hdf(tmp_path / "model.g01.hdf")


def test_native_sidecar_edit_requires_selected_hecras_version(tmp_path: Path):
    sidecar = tmp_path / "LandCover.hdf"
    sidecar.touch()

    with pytest.raises(ValueError, match="hecras_version is required"):
        HdfLandCover.set_landcover_raster_map(
            sidecar,
            {"Open Water": 0.04},
        )
