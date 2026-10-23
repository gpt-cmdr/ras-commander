"""Narrow lossless native terrain registration; no package-time GIS imports."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def validate_registration(output: Path, raster: Path) -> dict[str, Any]:
    """Require a self-contained native HDF and VRT binding to the owned TIFF."""
    import h5py

    from ..fast_hdf import read_attr

    def owned_reference(value: str) -> str:
        # Native registration uses leaf filenames, so relocations remain safe.
        if not value or "/" in value or "\\" in value or ":" in value:
            raise RuntimeError(
                "Native terrain registration has an external raster reference"
            )
        if (
            output.parent / value
        ).resolve() != raster.resolve() or not raster.is_file():
            raise RuntimeError(
                "Native terrain registration points to an unexpected raster"
            )
        return value

    with h5py.File(output, "r") as hdf:
        terrain = hdf.get("Terrain")
        records = (
            []
            if terrain is None
            else [
                group
                for group in terrain.values()
                if isinstance(group, h5py.Group) and "File" in group.attrs
            ]
        )
        if len(records) != 1 or read_attr(records[0], "Priority", None) != 0:
            raise RuntimeError(
                "Native terrain registration requires one priority-zero raster"
            )
        value = read_attr(records[0], "File")
        file = owned_reference(
            value.decode("utf-8") if isinstance(value, bytes) else str(value)
        )
    vrt = output.with_suffix(".vrt")
    if not vrt.is_file():
        raise RuntimeError("Native terrain registration is missing its VRT")
    references = ET.parse(vrt).getroot().findall(".//SourceFilename")
    if not references or any(ref.get("relativeToVRT") != "1" for ref in references):
        raise RuntimeError("Native terrain VRT requires relative raster references")
    files = sorted({owned_reference(ref.text or "") for ref in references})
    return {
        "hdf_raster_file": file,
        "vrt_raster_files": files,
        "relative_owned_binding": True,
    }


def inspect_source(source: Path, projection: Path) -> dict[str, Any]:
    import rasterio

    with rasterio.open(source) as grid:
        expected = rasterio.crs.CRS.from_wkt(projection.read_text(encoding="utf-8-sig"))
        transform = grid.transform
        if (
            grid.driver != "GTiff"
            or grid.count != 1
            or grid.dtypes != ("float32",)
            or grid.nodata != -9999
            or grid.crs != expected
            or not grid.crs.is_projected
            or "foot" not in grid.crs.linear_units.lower()
            or transform.b
            or transform.d
            or transform.a <= 0
            or transform.e != -transform.a
            or grid.mask_flag_enums[0] != [rasterio.enums.MaskFlags.nodata]
        ):
            raise ValueError(
                "Lossless creation requires one north-up square Float32 GeoTIFF, "
                "nodata=-9999 without an explicit mask, and the same projected foot CRS as the PRJ"
            )
        return {
            "transform": list(transform),
            "width": grid.width,
            "height": grid.height,
            "crs_wkt": grid.crs.to_wkt(),
            "nodata": grid.nodata,
        }


def validate_pixels(source: Path, created: Path) -> dict[str, Any]:
    import numpy as np
    import rasterio

    hashes = [hashlib.sha256(), hashlib.sha256()]
    count = 0
    with rasterio.open(source) as a, rasterio.open(created) as b:
        if (
            a.transform != b.transform
            or a.shape != b.shape
            or a.crs != b.crs
            or a.nodata != b.nodata
            or b.count != 1
            or b.dtypes != ("float32",)
            or b.block_shapes != [(256, 256)]
        ):
            raise RuntimeError(
                "Native lossless terrain grid, CRS, type or nodata changed"
            )
        for _, window in a.block_windows():
            values = [
                grid.read(1, window=window).astype("<f4", copy=False) for grid in (a, b)
            ]
            if not np.array_equal(values[0].view("<u4"), values[1].view("<u4")):
                raise RuntimeError("Native lossless terrain changed input pixel bits")
            for digest, array in zip(hashes, values):
                digest.update(array.tobytes())
            count += values[0].size
    return {
        "pixel_count": count,
        "different_pixel_count": 0,
        "source_pixel_sha256": hashes[0].hexdigest(),
        "created_pixel_sha256": hashes[1].hexdigest(),
        "pixel_encoding": "little-endian Float32, input block/row/column order",
    }


def create_lossless(
    source: Path,
    output: Path,
    projection: Path,
    install: Path,
    env: dict[str, str],
    timeout: float,
) -> Path:
    """Run the native creator, then validate stored bits and native HDF structure."""
    from ..RasProcess import RasProcess
    from .RasTerrain import RasTerrain

    descriptor = inspect_source(source, projection)

    def file_digest() -> str:
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    source_sha256 = file_digest()
    prefix = output.stem.casefold() + "."
    if (
        output.suffix.lower() != ".hdf"
        or output.exists()
        or (
            output.parent.exists()
            and any(
                item.name.casefold().startswith(prefix)
                for item in output.parent.iterdir()
            )
        )
    ):
        raise ValueError("Lossless terrain creation requires a new .hdf output prefix")
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt = output.with_suffix(".creation.json")
    result: dict[str, Any] = {
        "schema": "ras-commander-lossless-terrain-creation/v1",
        "status": "failed",
        "source_grid": descriptor,
        "source": str(source),
        "source_file_sha256": source_sha256,
        "output_hdf": str(output),
    }
    log_path = output.with_suffix(".creation.log")
    try:
        with tempfile.TemporaryDirectory(prefix="ras-lossless-terrain-") as folder:
            request, response = (
                Path(folder) / "request.json",
                Path(folder) / "response.json",
            )
            request.write_text(
                json.dumps(
                    {
                        "install": str(install),
                        "input_raster": str(source),
                        "output_hdf": str(output),
                        "projection_prj": str(projection),
                    }
                ),
                encoding="utf-8",
            )
            worker = Path(__file__).resolve().parents[1] / "_terrain_create_worker.py"
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [sys.executable, "-I", str(worker), str(request), str(response)],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                try:
                    process.wait(timeout=timeout)
                finally:
                    if process.poll() is None:
                        result["cleanup"] = RasProcess._terminate_owned_process_tree(
                            process
                        )
            if response.is_file():
                result["native"] = json.loads(response.read_text(encoding="utf-8"))
            if process.returncode or not response.is_file():
                raise RuntimeError(
                    "Isolated native terrain creation failed; see creation log"
                )
            native = result["native"]
            if (
                native.get("status") != "completed"
                or native["runtime"].get("status") != "completed"
                or native["runtime"].get("dll_identity_verified") is not True
                or native["runtime"].get("python_gis_hdf_imported") is not False
                or native["runtime"].get("rounding") != "None"
                or native["runtime"].get("data_type") != "Elevation"
                or native["runtime"].get("force_warp") is not False
                or native["runtime"].get("stitch") is not False
            ):
                raise RuntimeError(
                    "Native lossless terrain runtime evidence is incomplete"
                )
            if "Error creating Terrain:" in log_path.read_text(
                encoding="utf-8", errors="replace"
            ):
                raise RuntimeError(
                    "Native terrain builder reported an error; see creation log"
                )
            expected_raster = output.parent / f"{output.stem}.{source.stem}.tif"
            if Path(native["raster"]).resolve() != expected_raster.resolve():
                raise RuntimeError(
                    "Native creator returned an unexpected raster registration"
                )
            if file_digest() != source_sha256:
                raise RuntimeError("Native terrain creation changed the input file")
            result.update(
                native=native,
                registration=validate_registration(output, expected_raster),
                pixels=validate_pixels(source, expected_raster),
                hdf=RasTerrain._validate_terrain_hdf(output),
                status="completed",
                native_centre_qualification="not_performed",
            )
    except BaseException as exc:
        result["message"] = str(exc)
        raise
    finally:
        receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return output
