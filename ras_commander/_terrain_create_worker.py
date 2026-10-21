"""Native-only, HEC-RAS 6.6 unrounded terrain creation. Launch with -I."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def create(request: dict) -> dict:
    """Create a new native raster registration and caches without rounding."""
    helper = Path(__file__).with_name("_terrain_query_worker.py")
    spec = importlib.util.spec_from_file_location("native_query_runtime", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    install = Path(request["install"])
    handles, libraries, runtime = module._load_runtime(install)

    import clr

    for name in ("Geospatial.GDALAssist.dll", "TiffAssist.dll"):
        clr.AddReference(str(install / name))
    from Geospatial.GDALAssist import GDALSetup, Projection
    from RasMapperLib import SharedData, TerrainComputable
    from RasMapperLib.Progress import ConsoleDisplayProgress
    from System import Single, String
    from System.Collections.Generic import List
    from System.Diagnostics import FileVersionInfo
    from TiffAssist import FloatTiffWriter, RoundTo, TiffMetadata
    from Utility.Progress import ProgressReporter

    expected = [
        "md",
        "writeStitchInformation",
        "projectProjection",
        "filenames",
        "baseFolder",
        "name",
        "tileWriteOperationParam",
        "mergeAllToSingleVRT",
        "forceReprocessRASTiffs",
        "forceWarp",
        "tileWriteOperation",
    ]
    constructors = clr.GetClrType(TerrainComputable).GetConstructors()
    types = [
        "TiffAssist.TiffMetadata`1[System.Single]",
        "System.Boolean",
        "Geospatial.GDALAssist.Projection",
        "System.Collections.Generic.List`1[System.String]",
        "System.String",
        "System.String",
        "System.Single",
        "System.Boolean",
        "System.Boolean",
        "System.Boolean",
        "TiffAssist.FloatTiffWriter+TileWriteOperations",
    ]
    if (
        len(constructors) != 1
        or [str(p.Name) for p in constructors[0].GetParameters()] != expected
        or [str(p.ParameterType) for p in constructors[0].GetParameters()] != types
    ):
        raise RuntimeError(
            "The expected HEC-RAS 6.6 terrain creation signature changed"
        )
    version = FileVersionInfo.GetVersionInfo(str(install / "Ras.exe"))
    if version.FileMajorPart != 6 or version.FileMinorPart != 6:
        raise RuntimeError("Lossless native terrain creation requires HEC-RAS 6.6")
    GDALSetup.Initialize(
        str(install / "GDAL/bin64"),
        str(install / "GDAL/common/data"),
        str(install / "GDAL/bin64/gdalplugins"),
        str(install / "GDAL/common/WMS"),
    )
    GDALSetup.EnsureInitialized()
    metadata = TiffMetadata[Single](Single(-9999), getattr(RoundTo, "None"))
    metadata.TileWidth = metadata.TileHeight = 256
    metadata.Software = "HEC-RAS"
    metadata.Artist = "USACE HEC"
    metadata.ImageDescription = "HEC-RAS Terrain"
    metadata.DataType = "Elevation"
    metadata.DataUnits = "Feet"
    metadata.CompressionUsed = "Deflate"
    SharedData.SetUnitsSystem("English")
    SharedData.SRSFilename = request["projection_prj"]
    sources = List[String]()
    sources.Add(request["input_raster"])
    output = Path(request["output_hdf"])
    if (
        output.exists()
        or output.with_suffix(".vrt").exists()
        or any(
            item.name.casefold().startswith(output.stem.casefold() + ".")
            and item.suffix.lower() == ".tif"
            for item in output.parent.iterdir()
        )
    ):
        raise ValueError(
            "Native lossless creator refuses existing terrain output files"
        )
    builder = TerrainComputable(
        metadata,
        False,
        Projection.FromFile(request["projection_prj"]),
        sources,
        str(output.parent),
        output.stem,
        Single(0),
        False,
        True,
        False,
        getattr(FloatTiffWriter.TileWriteOperations, "None"),
    )
    display = ConsoleDisplayProgress()
    builder.Initialize(display)
    builder.Run(ProgressReporter.ConsoleWrite())
    builder.Complete()
    raster = output.parent / f"{output.stem}.{Path(request['input_raster']).stem}.tif"
    if (
        not output.is_file()
        or not raster.is_file()
        or not output.with_suffix(".vrt").is_file()
    ):
        raise RuntimeError(
            "Native creation did not produce a complete terrain registration"
        )
    module._check_python_imports()
    extra_handles, extra_libraries, verified = module._load_runtime(install)
    handles += extra_handles
    libraries += extra_libraries
    runtime.update(verified)
    runtime.update(
        schema="ras-commander-native-terrain-creation-runtime/v1",
        status="completed",
        rounding="None",
        tile_size=256,
        stitch=False,
        force_warp=False,
        tile_write_operation="None",
        data_units="Feet",
        data_type="Elevation",
        mode="isolated-native-terrain-create-v1",
        hecras_file_version=str(version.FileVersion),
        constructor_parameter_types=types,
    )
    # Keep absolute loader handles alive until all managed writes complete.
    assert handles is not None and libraries
    return {"status": "completed", "runtime": runtime, "raster": str(raster)}


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result_path = Path(sys.argv[2])
    try:
        result = create(request)
    except BaseException as exc:
        result_path.write_text(
            json.dumps({"status": "failed", "message": str(exc)}), encoding="utf-8"
        )
        raise
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
