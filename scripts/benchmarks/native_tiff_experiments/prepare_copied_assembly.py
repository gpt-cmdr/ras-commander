"""Build a hash-pinned, opt-in TiffAssist copied-assembly experiment.

The script inventories the installed HEC-RAS mapping runtime, verifies the
known HEC-RAS 7.0 hashes, copies every input into ``working/``, decompiles only
the copied TiffAssist assembly, applies exact source transformations, and
builds a copied replacement. It never opens an installed HEC-RAS file for
writing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT_ROOT = Path(__file__).resolve().parent
PATCH_SOURCE = EXPERIMENT_ROOT / "patches" / "ExperimentalTiffIO.cs"
HARNESS_PROJECT = EXPERIMENT_ROOT / "harness" / "TiffAssistExperimentHarness.csproj"

PATCH_ID = "tiffassist-parallel-tiles-v2"
KNOWN_HEC_RAS_70 = {
    "TiffAssist.dll": "acd6ada0dbaacf5aa314aca9a087fe5c6699ca582afac1c9060c8404f6a254c9",
    "RasMapperLib.dll": "614460c730d83fb0a1e1f98f6c2c6b1ae6b9f14dc228b0706e4517341523dbeb",
    "BitMiracle.LibTiff.NET.dll": "99d4c2698778134d94aa3cc8330a7235cfcbf65a34699c4f0728d75798e9c1f0",
    "Utility.Core.dll": "c3d97a8fca0f0071cd43c8169f4922e1e3b96ae3226cfdd096f3dbc3ecf00edf",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "sha256": sha256(path),
    }


def dotnet_file_identity(path: Path) -> dict[str, str | None]:
    """Read PE file and assembly versions without loading it into Python."""

    script = (
        "$p=$env:RASCOMMANDER_IDENTITY_PATH;"
        "$item=Get-Item -LiteralPath $p;"
        "$asm=[Reflection.AssemblyName]::GetAssemblyName($p);"
        "[pscustomobject]@{"
        "file_version=$item.VersionInfo.FileVersion;"
        "product_version=$item.VersionInfo.ProductVersion;"
        "assembly_name=$asm.Name;"
        "assembly_version=$asm.Version.ToString()"
        "}|ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "RASCOMMANDER_IDENTITY_PATH": str(path)},
    )
    if result.returncode:
        raise RuntimeError(
            f"Could not inspect .NET identity for {path}: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def inventory_install(install_dir: Path) -> dict[str, Any]:
    install_dir = install_dir.resolve()
    files: dict[str, dict[str, Any]] = {}
    for name in KNOWN_HEC_RAS_70:
        path = install_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Required HEC-RAS assembly is missing: {path}")
        files[name] = {**file_identity(path), **dotnet_file_identity(path)}
    return {
        "install_dir": str(install_dir),
        "files": files,
        "known_build": all(
            files[name]["sha256"] == expected
            for name, expected in KNOWN_HEC_RAS_70.items()
        ),
    }


def verify_known_build(inventory: dict[str, Any]) -> None:
    mismatches = []
    for name, expected in KNOWN_HEC_RAS_70.items():
        actual = inventory["files"][name]["sha256"]
        if actual != expected:
            mismatches.append(f"{name}: expected {expected}, found {actual}")
    if mismatches:
        raise RuntimeError(
            "Refusing to patch an unpinned HEC-RAS build:\n  " + "\n  ".join(mismatches)
        )


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Patch anchor {label!r} occurred {count} times; expected exactly once"
        )
    return text.replace(old, new, 1)


def patch_tiff_base(path: Path) -> dict[str, Any]:
    before = path.read_text(encoding="utf-8")
    after = replace_exact(
        before,
        "\t\t_tiffImage = TiffOpenCheckMode(filename, ref mode);",
        '\t\t_tiffImage = ExperimentalTiffSettings.Enabled && mode.Contains("w")\n'
        "\t\t\t? ExperimentalTiffStreamFactory.Open(filename, mode)\n"
        "\t\t\t: TiffOpenCheckMode(filename, ref mode);",
        "TiffBase filename open",
    )
    path.write_text(after, encoding="utf-8", newline="\n")
    return {
        "file": "TiffAssist/TiffBase.cs",
        "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
        "change": "route opt-in filename writes through seek-aware batching client I/O",
    }


def patch_tiff_writer(path: Path) -> dict[str, Any]:
    before = path.read_text(encoding="utf-8")
    old = """\tpublic void WriteRawTile(int tileNumber, byte[] data)
\t{
\t\t_tiffImage.WriteRawTile(tileNumber, data, data.Length);
\t}
"""
    new = """\tprotected virtual void BeforeRawTileWrite()
\t{
\t}

\tprotected int WriteRawTileInternal(int tileNumber, byte[] data, int count)
\t{
\t\treturn _tiffImage.WriteRawTile(tileNumber, data, 0, count);
\t}

\tpublic void WriteRawTile(int tileNumber, byte[] data)
\t{
\t\tBeforeRawTileWrite();
\t\tWriteRawTileInternal(tileNumber, data, data.Length);
\t}
"""
    after = replace_exact(
        before,
        old,
        new,
        "TiffWriter raw tile pipeline completion hook",
    )
    path.write_text(after, encoding="utf-8", newline="\n")
    return {
        "file": "TiffAssist/TiffWriter.cs",
        "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
        "change": (
            "add a pre-raw-write completion hook and a counted protected raw-tile "
            "commit method for the single destination writer"
        ),
    }


def patch_float_writer(path: Path) -> dict[str, Any]:
    before = path.read_text(encoding="utf-8")
    after = replace_exact(
        before,
        "\tprivate Func<float, float> ROUND;",
        "\tprivate Func<float, float> ROUND;\n\n"
        "\tprivate byte[] _reusableByteBuffer;\n\n"
        "\tprivate ExperimentalFloatTilePipeline _parallelPipeline;\n\n"
        "\tprivate bool _parallelPipelineCompleted;",
        "FloatTiffWriter experimental fields",
    )
    after = replace_exact(
        after,
        ": base(tiffFilename, imageWidth, imageHeight, SampleFormat.IEEEFP, ComputeStats, metadata, appendArg, deleteExistingFile)",
        ": base(tiffFilename, imageWidth, imageHeight, SampleFormat.IEEEFP, ExperimentalTiffSettings.ApplyTrackStats(ComputeStats), metadata, appendArg, deleteExistingFile)",
        "FloatTiffWriter filename constructor statistics policy",
    )
    after = replace_exact(
        after,
        ": base(stream, imageWidth, imageHeight, SampleFormat.IEEEFP, computeStats, metadata)",
        ": base(stream, imageWidth, imageHeight, SampleFormat.IEEEFP, ExperimentalTiffSettings.ApplyTrackStats(computeStats), metadata)",
        "FloatTiffWriter stream constructor statistics policy",
    )
    filename_constructor_tail = """\t\telse
\t\t{
\t\t\tInitializeRounding(metadata.Rounding);
\t\t}
\t}

\tpublic FloatTiffWriter(Stream stream, int imageWidth, int imageHeight, bool computeStats, TiffMetadata<float> metadata)
"""
    filename_constructor_tail_patched = """\t\telse
\t\t{
\t\t\tInitializeRounding(metadata.Rounding);
\t\t}
\t\tInitializeExperimentalPipeline();
\t}

\tpublic FloatTiffWriter(Stream stream, int imageWidth, int imageHeight, bool computeStats, TiffMetadata<float> metadata)
"""
    after = replace_exact(
        after,
        filename_constructor_tail,
        filename_constructor_tail_patched,
        "FloatTiffWriter filename pipeline initialization",
    )

    old_methods = """\tpublic override void WriteTile(int TileNumber, float[] data)
\t{
\t\tif (base.TrackStats)
\t\t{
\t\t\tStats value = RoundTileWithStats(data, TileNumber);
\t\t\tbase.TileStats[TileNumber] = value;
\t\t}
\t\telse
\t\t{
\t\t\tRoundTileNoStats(data, TileNumber);
\t\t}
\t\tbyte[] array = new byte[data.Length * base.SizeOfT];
\t\tBuffer.BlockCopy(data, 0, array, 0, array.Length);
\t\tWriteTileInternal(TileNumber, array);
\t}

\tpublic override void WriteTile(int TileNumber, float[,] data)
\t{
\t\tif (base.TrackStats)
\t\t{
\t\t\tStats value = RoundTileWithStats(data, TileNumber);
\t\t\tbase.TileStats[TileNumber] = value;
\t\t}
\t\telse
\t\t{
\t\t\tRoundTileNoStats(data, TileNumber);
\t\t}
\t\tbyte[] array = new byte[data.Length * base.SizeOfT];
\t\tBuffer.BlockCopy(data, 0, array, 0, array.Length);
\t\tWriteTileInternal(TileNumber, array);
\t}
"""
    new_methods = """\tpublic override void WriteTile(int TileNumber, float[] data)
\t{
\t\tif (_parallelPipeline != null && !_parallelPipelineCompleted)
\t\t{
\t\t\t_parallelPipeline.Enqueue(TileNumber, data);
\t\t\treturn;
\t\t}
\t\tif (base.TrackStats)
\t\t{
\t\t\tStats value = ExperimentalTiffSettings.UseSerialStatistics
\t\t\t\t? RoundTileWithStatsSerial(data, TileNumber)
\t\t\t\t: RoundTileWithStats(data, TileNumber);
\t\t\tbase.TileStats[TileNumber] = value;
\t\t}
\t\telse
\t\t{
\t\t\tRoundTileNoStats(data, TileNumber);
\t\t}
\t\tbyte[] bytes = GetTileByteBuffer(data.Length * base.SizeOfT);
\t\tBuffer.BlockCopy(data, 0, bytes, 0, bytes.Length);
\t\tWriteTileInternal(TileNumber, bytes);
\t}

\tpublic override void WriteTile(int TileNumber, float[,] data)
\t{
\t\tif (_parallelPipeline != null && !_parallelPipelineCompleted)
\t\t{
\t\t\t_parallelPipeline.Enqueue(TileNumber, data);
\t\t\treturn;
\t\t}
\t\tif (base.TrackStats)
\t\t{
\t\t\tStats value = ExperimentalTiffSettings.UseSerialStatistics
\t\t\t\t? RoundTileWithStatsSerial(data, TileNumber)
\t\t\t\t: RoundTileWithStats(data, TileNumber);
\t\t\tbase.TileStats[TileNumber] = value;
\t\t}
\t\telse
\t\t{
\t\t\tRoundTileNoStats(data, TileNumber);
\t\t}
\t\tbyte[] bytes = GetTileByteBuffer(data.Length * base.SizeOfT);
\t\tBuffer.BlockCopy(data, 0, bytes, 0, bytes.Length);
\t\tWriteTileInternal(TileNumber, bytes);
\t}

\tprivate byte[] GetTileByteBuffer(int length)
\t{
\t\tif (!ExperimentalTiffSettings.ReuseTileBuffer)
\t\t{
\t\t\treturn new byte[length];
\t\t}
\t\tif (_reusableByteBuffer == null || _reusableByteBuffer.Length != length)
\t\t{
\t\t\t_reusableByteBuffer = new byte[length];
\t\t}
\t\treturn _reusableByteBuffer;
\t}
"""
    after = replace_exact(
        after,
        old_methods,
        new_methods,
        "FloatTiffWriter WriteTile implementations",
    )

    serial_methods = """
\tprivate void InitializeExperimentalPipeline()
\t{
\t\tif (!ExperimentalTiffSettings.PipelineEnabled)
\t\t{
\t\t\treturn;
\t\t}
\t\tif (ExperimentalTiffSettings.StatisticsMode == "native")
\t\t{
\t\t\tthrow new InvalidOperationException(
\t\t\t\t"The parallel TIFF pipeline requires serial or none statistics mode."
\t\t\t);
\t\t}
\t\t_parallelPipeline = new ExperimentalFloatTilePipeline(
\t\t\t_tiffFileName,
\t\t\tbase.Metadata.TileWidth,
\t\t\tbase.Metadata.TileHeight,
\t\t\tPrepareTileForParallelPipeline,
\t\t\tCommitParallelRawTile
\t\t);
\t}

\tprivate Stats PrepareTileForParallelPipeline(int TileNumber, float[] tile)
\t{
\t\tif (base.TrackStats)
\t\t{
\t\t\treturn RoundTileWithStatsSerial(tile, TileNumber);
\t\t}
\t\tRoundTileNoStatsSerial(tile, TileNumber);
\t\treturn null;
\t}

\tprivate void CommitParallelRawTile(
\t\tint TileNumber,
\t\tbyte[] data,
\t\tint count,
\t\tStats statistics)
\t{
\t\t// RASMapper pre-encodes its reusable NoData payload into tile zero.
\t\t// Raw replacement must reset LibTiff's shared append offset just as
\t\t// WriteEncodedTile does when replacing an existing tile.
\t\t_tiffImage.SetWriteOffset(0L);
\t\tint written = WriteRawTileInternal(TileNumber, data, count);
\t\tif (written != count)
\t\t{
\t\t\tthrow new IOException("Could not commit the complete parallel raw TIFF tile.");
\t\t}
\t\tif (base.TrackStats)
\t\t{
\t\t\tif (statistics == null)
\t\t\t{
\t\t\t\tthrow new InvalidOperationException("A parallel TIFF tile is missing statistics.");
\t\t\t}
\t\t\tbase.TileStats[TileNumber] = statistics;
\t\t}
\t}

\tprivate void CompleteExperimentalPipeline()
\t{
\t\tif (_parallelPipeline == null || _parallelPipelineCompleted)
\t\t{
\t\t\treturn;
\t\t}
\t\t_parallelPipeline.Complete();
\t\t_parallelPipelineCompleted = true;
\t}

\tprotected override void BeforeRawTileWrite()
\t{
\t\tCompleteExperimentalPipeline();
\t}

\tprivate void RoundTileNoStatsSerial(float[] tile, int TileNumber)
\t{
\t\tTiffBase.GetValidRegionThreadsafe(
\t\t\tbase.Metadata.TileWidth,
\t\t\tbase.Metadata.TileHeight,
\t\t\tbase.Width,
\t\t\tbase.Height,
\t\t\tTileNumber,
\t\t\tout var validWidth,
\t\t\tout var validHeight
\t\t);
\t\tif (ROUND == null)
\t\t{
\t\t\treturn;
\t\t}
\t\tint actualWidth = base.Metadata.TileWidth;
\t\tfloat noData = base.Metadata.NoDataValue;
\t\tfor (int row = 0; row < validHeight; row++)
\t\t{
\t\t\tint start = row * actualWidth;
\t\t\tfor (int column = 0; column < validWidth; column++)
\t\t\t{
\t\t\t\tint index = start + column;
\t\t\t\tif (tile[index] != noData)
\t\t\t\t{
\t\t\t\t\ttile[index] = ROUND(tile[index]);
\t\t\t\t}
\t\t\t}
\t\t}
\t}

\tprivate Stats RoundTileWithStatsSerial(float[] tile, int TileNumber)
\t{
\t\tTiffBase.GetValidRegionThreadsafe(
\t\t\tbase.Metadata.TileWidth,
\t\t\tbase.Metadata.TileHeight,
\t\t\tbase.Width,
\t\t\tbase.Height,
\t\t\tTileNumber,
\t\t\tout var validWidth,
\t\t\tout var validHeight
\t\t);
\t\tint actualWidth = base.Metadata.TileWidth;
\t\tfloat noData = base.Metadata.NoDataValue;
\t\tStats stats = new Stats(noData);
\t\tfor (int row = 0; row < validHeight; row++)
\t\t{
\t\t\tint start = row * actualWidth;
\t\t\tfor (int column = 0; column < validWidth; column++)
\t\t\t{
\t\t\t\tint index = start + column;
\t\t\t\tif (ROUND != null && tile[index] != noData)
\t\t\t\t{
\t\t\t\t\ttile[index] = ROUND(tile[index]);
\t\t\t\t}
\t\t\t}
\t\t\tstats.InsertRange(tile, start, validWidth);
\t\t}
\t\treturn stats;
\t}

\tprivate Stats RoundTileWithStatsSerial(float[,] tile, int TileNumber)
\t{
\t\tTiffBase.GetValidRegionThreadsafe(
\t\t\tbase.Metadata.TileWidth,
\t\t\tbase.Metadata.TileHeight,
\t\t\tbase.Width,
\t\t\tbase.Height,
\t\t\tTileNumber,
\t\t\tout var validWidth,
\t\t\tout var validHeight
\t\t);
\t\tfloat noData = base.Metadata.NoDataValue;
\t\tStats stats = new Stats(noData);
\t\tfor (int row = 0; row < validHeight; row++)
\t\t{
\t\t\tfor (int column = 0; column < validWidth; column++)
\t\t\t{
\t\t\t\tif (ROUND != null && tile[row, column] != noData)
\t\t\t\t{
\t\t\t\t\ttile[row, column] = ROUND(tile[row, column]);
\t\t\t\t}
\t\t\t\tstats.Insert(tile[row, column]);
\t\t\t}
\t\t}
\t\treturn stats;
\t}

"""
    anchor = "\tprivate Stats RoundTileWithStats(float[] tile, int TileNumber)"
    if after.count(anchor) != 1:
        raise RuntimeError("Serial statistics insertion anchor changed")
    after = after.replace(anchor, serial_methods + anchor, 1)
    after = replace_exact(
        after,
        """\tpublic bool RasterHasData()
\t{
\t\tif (!base.TrackStats)
""",
        """\tpublic bool RasterHasData()
\t{
\t\tCompleteExperimentalPipeline();
\t\tif (!base.TrackStats)
""",
        "FloatTiffWriter RasterHasData pipeline completion",
    )
    after = replace_exact(
        after,
        """\t\tint numDirectories = GetNumDirectories();
\t\tbase.Dispose(isDisposing);
""",
        """\t\tCompleteExperimentalPipeline();
\t\tif (_parallelPipeline != null)
\t\t{
\t\t\t_parallelPipeline.Dispose();
\t\t\t_parallelPipeline = null;
\t\t}
\t\tint numDirectories = GetNumDirectories();
\t\tbase.Dispose(isDisposing);
""",
        "FloatTiffWriter Dispose pipeline completion",
    )
    path.write_text(after, encoding="utf-8", newline="\n")
    return {
        "file": "TiffAssist/FloatTiffWriter.cs",
        "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
        "change": (
            "retain the reusable synchronous tile buffer and add a bounded parallel "
            "round/statistics/copy/Deflate pipeline with one raw-tile commit consumer"
        ),
    }


def rewrite_reference_paths(project: Path, originals: Path) -> None:
    text = project.read_text(encoding="utf-8")
    for name in ("BitMiracle.LibTiff.NET.dll", "Utility.Core.dll"):
        start = text.find("<HintPath>", text.find(f'Include="{Path(name).stem}'))
        end = text.find("</HintPath>", start)
        if start < 0 or end < 0:
            raise RuntimeError(
                f"Could not find decompiled project reference for {name}"
            )
        replacement = f"<HintPath>{originals / name}</HintPath>"
        text = text[:start] + replacement + text[end + len("</HintPath>") :]
    project.write_text(text, encoding="utf-8", newline="\n")


def find_msbuild() -> Path:
    candidates = [
        Path(
            r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
            r"\MSBuild\Current\Bin\MSBuild.exe"
        ),
        Path(
            r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools"
            r"\MSBuild\Current\Bin\MSBuild.exe"
        ),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    resolved = shutil.which("msbuild")
    if resolved:
        return Path(resolved)
    raise FileNotFoundError("MSBuild 2022 was not found")


def run_checked(command: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout + result.stderr


def safe_remove(path: Path) -> None:
    allowed = (ROOT / "working" / "native_tiff_experiments").resolve()
    resolved = path.resolve()
    if resolved == allowed or allowed not in resolved.parents:
        raise RuntimeError(
            f"Refusing to remove path outside experiment working root: {path}"
        )
    if path.exists():
        shutil.rmtree(path)


def copy_runtime(install_dir: Path, runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for source in install_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, runtime_dir / source.name)
    gdal_source = install_dir / "GDAL"
    if gdal_source.is_dir():
        shutil.copytree(gdal_source, runtime_dir / "GDAL", dirs_exist_ok=True)


def build_harness(msbuild: Path, runtime: Path, output: Path) -> str:
    output.mkdir(parents=True, exist_ok=True)
    return run_checked(
        [
            str(msbuild),
            str(HARNESS_PROJECT),
            "/t:Restore,Build",
            "/p:Configuration=Release",
            f"/p:TiffAssistRuntime={runtime}",
            f"/p:OutputPath={output}{os.sep}",
            "/v:minimal",
        ]
    )


def prepare(
    install_dir: Path,
    output_root: Path,
    rebuild: bool = False,
) -> dict[str, Any]:
    install_dir = install_dir.resolve()
    output_root = output_root.resolve()
    inventory_before = inventory_install(install_dir)
    verify_known_build(inventory_before)
    if output_root.exists():
        if not rebuild:
            raise FileExistsError(
                f"Experiment output exists; pass --rebuild to replace it: {output_root}"
            )
        safe_remove(output_root)

    originals = output_root / "assemblies" / "original"
    source_dir = output_root / "source"
    runtime = output_root / "runtime_patched"
    baseline_runtime = output_root / "runtime_original_minimal"
    harness_patched = output_root / "harness_patched"
    harness_baseline = output_root / "harness_original"
    originals.mkdir(parents=True)
    for name in KNOWN_HEC_RAS_70:
        shutil.copy2(install_dir / name, originals / name)

    ilspy = shutil.which("ilspycmd")
    if not ilspy:
        raise FileNotFoundError(
            "ilspycmd is required; install the official ILSpy dotnet tool"
        )
    decompile_output = run_checked(
        [ilspy, "-p", "-o", str(source_dir), str(originals / "TiffAssist.dll")]
    )
    project = source_dir / "TiffAssist.csproj"
    rewrite_reference_paths(project, originals)
    patch_records = [
        patch_tiff_base(source_dir / "TiffAssist" / "TiffBase.cs"),
        patch_tiff_writer(source_dir / "TiffAssist" / "TiffWriter.cs"),
        patch_float_writer(source_dir / "TiffAssist" / "FloatTiffWriter.cs"),
    ]
    copied_patch = source_dir / "TiffAssist" / "ExperimentalTiffIO.cs"
    shutil.copy2(PATCH_SOURCE, copied_patch)
    patch_records.append(
        {
            "file": "TiffAssist/ExperimentalTiffIO.cs",
            "before_sha256": None,
            "after_sha256": sha256(copied_patch),
            "change": (
                "add seek-aware batching I/O, bounded parallel tile workers, "
                "independent in-memory Deflate encoders, buffer pools, and stage profiling"
            ),
        }
    )

    msbuild = find_msbuild()
    # Roslyn can fail to materialize this deep generated path in Windows
    # worktrees before it writes the editorconfig. Creating it is harmless and
    # keeps the copied build reproducible without changing global long-path
    # policy.
    (source_dir / "obj" / "Release" / "net472").mkdir(parents=True, exist_ok=True)
    build_output = run_checked(
        [
            str(msbuild),
            str(project),
            "/t:Restore,Build",
            "/p:Configuration=Release",
            "/v:minimal",
        ]
    )
    patched_assembly = source_dir / "bin" / "Release" / "net472" / "TiffAssist.dll"
    if not patched_assembly.is_file():
        raise FileNotFoundError(
            f"Patched assembly build did not produce {patched_assembly}"
        )

    copy_runtime(install_dir, runtime)
    shutil.copy2(
        runtime / "TiffAssist.dll", runtime / "TiffAssist.installed-original.dll"
    )
    shutil.copy2(patched_assembly, runtime / "TiffAssist.dll")

    baseline_runtime.mkdir(parents=True)
    for name in ("TiffAssist.dll", "BitMiracle.LibTiff.NET.dll", "Utility.Core.dll"):
        shutil.copy2(originals / name, baseline_runtime / name)
    patched_minimal = output_root / "runtime_patched_minimal"
    patched_minimal.mkdir(parents=True)
    shutil.copy2(patched_assembly, patched_minimal / "TiffAssist.dll")
    for name in ("BitMiracle.LibTiff.NET.dll", "Utility.Core.dll"):
        shutil.copy2(originals / name, patched_minimal / name)

    harness_baseline_log = build_harness(msbuild, baseline_runtime, harness_baseline)
    harness_patched_log = build_harness(msbuild, patched_minimal, harness_patched)

    inventory_after = inventory_install(install_dir)
    if inventory_before["files"] != inventory_after["files"]:
        raise RuntimeError("Installed HEC-RAS assembly identity changed during build")

    manifest = {
        "schema": "ras-commander.native-tiff-patch-manifest/1",
        "patch_id": PATCH_ID,
        "safety": {
            "installed_files_opened_for_write": False,
            "installed_hashes_unchanged": True,
            "patched_assembly_enabled_by_default": False,
        },
        "source_inventory": inventory_before,
        "copied_inputs": {
            name: file_identity(originals / name) for name in KNOWN_HEC_RAS_70
        },
        "decompiler": {
            "command": ["ilspycmd", "-p", "-o", "<source>", "<copied TiffAssist.dll>"],
            "output_tail": decompile_output.strip().splitlines()[-3:],
        },
        "decompilation_evidence": [
            {
                "type": "TiffAssist.FloatTiffWriter",
                "method": "WriteTile(int, float[])",
                "behavior": (
                    "RoundTileWithStats uses Parallel.For plus ConcurrentBag<Stats>; "
                    "then allocates byte[data.Length * SizeOfT], BlockCopy, WriteEncodedTile"
                ),
            },
            {
                "type": "TiffAssist.TiffWriter<T>",
                "method": "WriteTileInternal(int, byte[])",
                "behavior": "one _tiffImage.WriteEncodedTile call per non-NoData tile",
            },
            {
                "type": "TiffAssist.TiffBase",
                "method": "TiffBase(string, string, bool)",
                "behavior": "filename writes use Tiff.Open directly; no stream buffer is exposed",
            },
            {
                "type": "RasMapperLib.StoredResultMap",
                "method": "CreateStoredMap",
                "behavior": (
                    "one consumer task invokes FloatTiffWriter.WriteTile from an unordered bag; "
                    "tile producers use Parallel.For with MaxDegreeOfParallelism = 32"
                ),
            },
        ],
        "source_patches": patch_records,
        "build": {
            "msbuild": str(msbuild),
            "assembly": file_identity(patched_assembly),
            "assembly_name": "TiffAssist",
            "assembly_version": "1.0.0.0",
            "build_output_tail": build_output.strip().splitlines()[-8:],
            "harness_original_output_tail": harness_baseline_log.strip().splitlines()[
                -5:
            ],
            "harness_patched_output_tail": harness_patched_log.strip().splitlines()[
                -5:
            ],
        },
        "artifacts": {
            "runtime_patched": str(runtime),
            "runtime_original_minimal": str(baseline_runtime),
            "runtime_patched_minimal": str(patched_minimal),
            "harness_original": str(
                harness_baseline / "TiffAssistExperimentHarness.exe"
            ),
            "harness_patched": str(harness_patched / "TiffAssistExperimentHarness.exe"),
        },
        "artifact_identities": {
            "runtime_patched_tiffassist": file_identity(runtime / "TiffAssist.dll"),
            "runtime_original_tiffassist": file_identity(
                baseline_runtime / "TiffAssist.dll"
            ),
            "runtime_patched_minimal_tiffassist": file_identity(
                patched_minimal / "TiffAssist.dll"
            ),
            "harness_original_exe": file_identity(
                harness_baseline / "TiffAssistExperimentHarness.exe"
            ),
            "harness_patched_exe": file_identity(
                harness_patched / "TiffAssistExperimentHarness.exe"
            ),
        },
        "controls": {
            "RASCOMMANDER_TIFF_EXPERIMENT": "1 enables every patch; absent/false is original behavior",
            "RASCOMMANDER_TIFF_BATCH_BYTES": "65536 through 67108864; default 262144",
            "RASCOMMANDER_TIFF_REUSE_BUFFER": "reuse one exact-size byte buffer; default true",
            "RASCOMMANDER_TIFF_STATS_MODE": "native, serial, or none; default serial",
            "RASCOMMANDER_TIFF_WRITE_PROFILE": "write per-TIFF I/O sidecar; default true",
            "RASCOMMANDER_TIFF_PIPELINE_WORKERS": "0 disables; 1 through 32 enables independent tile preparation and Deflate workers",
            "RASCOMMANDER_TIFF_PIPELINE_QUEUE_DEPTH": "bounded input and encoded queue depth; 1 through 128; default 2",
        },
    }
    manifest_path = output_root / "patch_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install-dir",
        type=Path,
        default=Path(r"C:\Program Files (x86)\HEC\HEC-RAS\7.0"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT
        / "working"
        / "native_tiff_experiments"
        / f"hr70-{KNOWN_HEC_RAS_70['TiffAssist.dll'][:8]}-tiff-parallel-v2",
    )
    parser.add_argument("--rebuild", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = prepare(args.install_dir, args.output_root, rebuild=args.rebuild)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
