"""Contracts for unrounded native creation; native qualification is separate."""

import json
import subprocess
from pathlib import Path

import h5py
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ras_commander.terrain import RasTerrain
from ras_commander.terrain import _lossless_create as lossless


def raster(path, values, *, transform=None, crs="EPSG:2278", nodata=-9999):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        transform=transform or from_origin(100, 120, 1, 1),
        crs=crs,
        nodata=nodata,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as grid:
        grid.write(values.astype("float32"), 1)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.tif"
    values = np.full((16, 16), 1201.1756591796875, dtype="float32")
    raster(path, values)
    projection = tmp_path / "projection.prj"
    projection.write_text(rasterio.crs.CRS.from_epsg(2278).to_wkt())
    return path, projection, values


def test_input_inspection_is_read_only_and_rejects_unit_crs_mismatch(source, tmp_path):
    path, projection, _ = source
    before = path.read_bytes()
    assert lossless.inspect_source(path, projection)["width"] == 16
    assert path.read_bytes() == before
    projection.write_text(rasterio.crs.CRS.from_epsg(32614).to_wkt())
    with pytest.raises(ValueError, match="same projected foot CRS"):
        lossless.inspect_source(path, projection)


@pytest.mark.parametrize("change", ["rounding", "grid", "signed_zero"])
def test_native_precision_or_grid_loss_fails_instead_of_tolerance(
    source, tmp_path, change
):
    path, _, values = source
    transform = from_origin(100, 120, 1, 1)
    if change == "rounding":
        values = np.round(values * 32) / 32
    elif change == "grid":
        transform = from_origin(100 + 1e-7, 120, 1, 1)
    else:
        values[0, 0] = -0.0
        raster(path, values)
        values[0, 0] = 0.0
    target = tmp_path / "created.tif"
    raster(target, values, transform=transform)
    with pytest.raises(RuntimeError, match="changed|grid"):
        lossless.validate_pixels(path, target)


def test_complete_pixel_bits_have_equal_hashes(source, tmp_path):
    path, _, values = source
    target = tmp_path / "created.tif"
    raster(target, values)
    result = lossless.validate_pixels(path, target)
    assert result["pixel_count"] == 256
    assert result["source_pixel_sha256"] == result["created_pixel_sha256"]


def test_explicit_validity_mask_is_outside_lossless_creation_contract(source):
    path, projection, values = source
    with rasterio.open(path, "r+") as grid:
        mask = np.full(values.shape, 255, dtype="uint8")
        mask[0, 0] = 0
        grid.write_mask(mask)
    with pytest.raises(ValueError, match="without an explicit mask"):
        lossless.inspect_source(path, projection)


@pytest.mark.parametrize("name", ["existing", "native[1]"])
@pytest.mark.parametrize("suffix", [".hdf", ".creation.json", ".creation.log"])
def test_existing_output_prefix_never_launches_or_overwrites(
    source, tmp_path, monkeypatch, name, suffix
):
    path, projection, _ = source
    output = tmp_path / (name + ".hdf")
    retained = tmp_path / (name + suffix)
    retained.write_bytes(b"keep")
    monkeypatch.setattr(
        lossless.subprocess, "Popen", lambda *a, **k: pytest.fail("launched")
    )
    with pytest.raises(ValueError, match="new .hdf"):
        lossless.create_lossless(path, output, projection, tmp_path, {}, 10)
    assert retained.read_bytes() == b"keep"


@pytest.mark.parametrize(
    "fault",
    [
        "native_error",
        "rounding",
        "missing_runtime",
        "input_changed",
        "missing_vrt",
        "wrong_hdf",
        "external_vrt",
        "none",
    ],
)
def test_process_exit_is_not_pixel_or_native_acceptance(
    source, tmp_path, monkeypatch, fault
):
    path, projection, values = source
    output = tmp_path / "new.hdf"

    class Process:
        returncode = 0

        def __init__(self, command, **kwargs):
            request = json.loads(Path(command[-2]).read_text())
            assert command[1] == "-I" and request["input_raster"] == str(path)
            created = tmp_path / "new.source.tif"
            raster(
                created, np.round(values * 32) / 32 if fault == "rounding" else values
            )
            with h5py.File(output, "w") as hdf:
                record = hdf.create_group("Terrain/new.source")
                record.attrs["File"] = (
                    "external.tif" if fault == "wrong_hdf" else created.name
                )
                record.attrs["Priority"] = 0
            if fault != "missing_vrt":
                value = "../new.source.tif" if fault == "external_vrt" else created.name
                output.with_suffix(".vrt").write_text(
                    '<VRTDataset><VRTRasterBand><SimpleSource><SourceFilename relativeToVRT="1">'
                    + value
                    + "</SourceFilename></SimpleSource></VRTRasterBand></VRTDataset>"
                )
            runtime = {
                "status": "completed",
                "dll_identity_verified": True,
                "python_gis_hdf_imported": False,
                "rounding": "None",
                "data_type": "Elevation",
                "force_warp": False,
                "stitch": False,
            }
            if fault == "missing_runtime":
                runtime["status"] = "initialized"
            Path(command[-1]).write_text(
                json.dumps(
                    {"status": "completed", "runtime": runtime, "raster": str(created)}
                )
            )
            if fault == "native_error":
                kwargs["stdout"].write(
                    "Error creating Terrain: caught native failure\n"
                )

            if fault == "input_changed":
                raster(path, values + 1)

        def wait(self, timeout):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(lossless.subprocess, "Popen", Process)
    monkeypatch.setattr(RasTerrain, "_validate_terrain_hdf", lambda p: {"datasets": 21})
    if fault == "none":
        assert (
            lossless.create_lossless(path, output, projection, tmp_path, {}, 10)
            == output
        )
    else:
        with pytest.raises(RuntimeError):
            lossless.create_lossless(path, output, projection, tmp_path, {}, 10)
    receipt = json.loads(output.with_suffix(".creation.json").read_text())
    assert receipt["status"] == ("completed" if fault == "none" else "failed")
    assert receipt["native"]["raster"].endswith("new.source.tif")


def test_timeout_cleans_only_launched_tree_and_records_failed_attempt(
    source, tmp_path, monkeypatch
):
    from ras_commander.RasProcess import RasProcess

    path, projection, _ = source
    output = tmp_path / "timed.hdf"
    owned = []

    class Process:
        pid = 12345

        def __init__(self, *a, **k):
            pass

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("owned", timeout)

        def poll(self):
            return None

    monkeypatch.setattr(lossless.subprocess, "Popen", Process)
    monkeypatch.setattr(
        RasProcess,
        "_terminate_owned_process_tree",
        lambda p: owned.append(p.pid) or {"survivor_pids": []},
    )
    with pytest.raises(subprocess.TimeoutExpired):
        lossless.create_lossless(path, output, projection, tmp_path, {}, 1)
    assert owned == [12345]
    assert (
        json.loads(output.with_suffix(".creation.json").read_text())["status"]
        == "failed"
    )


@pytest.mark.parametrize(
    "options",
    [
        {"units": "Meters"},
        {"hecras_version": "6.7"},
        {"timeout_seconds": float("inf")},
        {"gdal_num_threads": True},
    ],
)
def test_unqualified_creation_options_fail_before_native_launch(options):
    with pytest.raises(ValueError):
        RasTerrain.create_terrain_hdf_lossless(
            "missing.tif", "new.hdf", "missing.prj", **options
        )
