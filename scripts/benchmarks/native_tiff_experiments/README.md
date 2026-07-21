# Copied TiffAssist parallel-tile experiment

This directory contains a research-only, version-pinned experiment for the
HEC-RAS 7.0 stored-map TIFF writer. It never modifies the installed HEC-RAS
directory. The builder verifies the installed DLL hashes, copies the runtime
into ignored `working/`, decompiles the copied `TiffAssist.dll`, applies
anchor-checked source changes, rebuilds it with the original assembly identity,
and verifies the installed hashes again.

The copied assembly is inert unless `RASCOMMANDER_TIFF_EXPERIMENT=1` is set in
the helper process. It is not a supported runtime override or redistributable
HEC-RAS replacement.

## What the decompiled code shows

For the pinned HEC-RAS 7.0 build:

- `StoredResultMap` uses `Parallel.For` producers with a hard-coded maximum of
  32 workers;
- one consumer drains completed tiles from a `ConcurrentBag` and calls
  `FloatTiffWriter.WriteTile()`; this is serialized but not tile-number ordered;
- each data tile performs rounding/statistics, allocates and copies a Float32
  byte buffer, initializes Deflate, and calls `WriteEncodedTile()`;
- BitMiracle's destination `Tiff` handle owns mutable current-tile, offset,
  raw-buffer, and codec state, so concurrent calls on one handle are unsafe;
- TiffAssist exposes `GetRawTile()` and `WriteRawTile()`, allowing compression
  to be separated from a single destination commit;
- RASMapper later rereads the TIFF for a histogram and runs a separate
  `gdaladdo` overview process.

## Experimental architecture

The opt-in pipeline snapshots each incoming tile into a bounded pool. Independent
worker tasks perform serial-within-tile rounding/statistics, copy to bytes, and
Deflate-compress through one private in-memory LibTiff context per worker. A
single commit task writes the encoded payloads to the destination TIFF and owns
all destination statistics/directory state.

Commit order follows worker completion, just as the original `ConcurrentBag`
consumer does not guarantee tile-number order. Each payload retains its tile
number. Validation requires layout-independent decoded pixels, dimensions,
types, CRS, transform, NoData, required overview levels, and all exposed TIFF
metadata domains/tags. Block layout and compression are recorded separately so
future experiments may intentionally vary them.
Raw writes reset the destination write offset so a later tile-zero commit can
replace RASMapper's pre-encoded NoData seed correctly.

Both input and encoded queues are bounded. The default depth is 2 because the
measured raw commit is much faster than tile preparation/compression; larger
queues retained more buffers without improving throughput. The observed Spring
River maximum was 12 owned tiles with eight workers and depth 2.

## Controls

| Environment variable | Values | Default |
|---|---|---|
| `RASCOMMANDER_TIFF_EXPERIMENT` | true/false | false |
| `RASCOMMANDER_TIFF_BATCH_BYTES` | 65,536 through 67,108,864 | 262,144 assembly fallback; 2,097,152 benchmark CLI |
| `RASCOMMANDER_TIFF_REUSE_BUFFER` | true/false | true |
| `RASCOMMANDER_TIFF_STATS_MODE` | `native`, `serial`, `none` | `serial` |
| `RASCOMMANDER_TIFF_WRITE_PROFILE` | true/false | true |
| `RASCOMMANDER_TIFF_PIPELINE_WORKERS` | 0 through 32 | 0 |
| `RASCOMMANDER_TIFF_PIPELINE_QUEUE_DEPTH` | 1 through 128 | 2 |

Workers greater than zero require `serial` or `none` statistics. `none` is a
microbenchmark control only because the normal StoreMap histogram path expects
embedded statistics.

The JSON sidecar reports logical and physical writes, stage seconds, queue wait
seconds, tile/byte counts, pool allocations, queue high-water marks, and maximum
owned tiles. The benchmark adds process-tree CPU, memory, throughput, IOPS,
mean operation size, phase summaries, and raster equivalence.

## Build the owned runtime

From the repository root:

```powershell
.venv\Scripts\python.exe `
  scripts\benchmarks\native_tiff_experiments\prepare_copied_assembly.py `
  --rebuild
```

The generated manifest is:

```text
working/native_tiff_experiments/
  hr70-acd6ada0-tiff-parallel-v2/
    patch_manifest.json
```

The hash gate recognizes only these inputs:

| File | SHA-256 |
|---|---|
| `TiffAssist.dll` | `acd6ada0dbaacf5aa314aca9a087fe5c6699ca582afac1c9060c8404f6a254c9` |
| `RasMapperLib.dll` | `614460c730d83fb0a1e1f98f6c2c6b1ae6b9f14dc228b0706e4517341523dbeb` |
| `BitMiracle.LibTiff.NET.dll` | `99d4c2698778134d94aa3cc8330a7235cfcbf65a34699c4f0728d75798e9c1f0` |
| `Utility.Core.dll` | `c3d97a8fca0f0071cd43c8169f4922e1e3b96ae3226cfdd096f3dbc3ecf00edf` |

Any mismatch fails closed before source patching.

## Synthetic writer matrix

Use template tiles to isolate writer throughput from foreground fixture
generation. Queue depth `0` means the copied assembly default.

```powershell
$experiment = 'working\native_tiff_experiments\hr70-acd6ada0-tiff-parallel-v2'

.venv\Scripts\python.exe `
  scripts\benchmarks\native_tiff_experiments\benchmark_copied_tiffassist.py `
  synthetic `
  --manifest "$experiment\patch_manifest.json" `
  --output-root working\native_tiff_experiments\writer-matrix `
  --width 8192 --height 8192 --repeats 1 `
  --template-tile-count 16 `
  --batch-bytes 65536,262144,1048576,2097152,8388608,16777216,67108864 `
  --statistics-modes serial `
  --pipeline-workers 0,1,2,4,8 `
  --pipeline-queue-depths 0
```

Add `--nodata-tile-interval 5` and odd dimensions such as 1000 by 777 to
exercise edge and raw-NoData tile paths.

## Real Spring River StoreMap matrix

Use a disposable computed project copy. This calls
`ras_commander._native_helper.run_store_map_helper()` and never invokes
`Ras.exe` directly.

```powershell
.venv\Scripts\python.exe `
  scripts\benchmarks\native_tiff_experiments\benchmark_copied_tiffassist.py `
  store-map `
  --manifest "$experiment\patch_manifest.json" `
  --project-folder working\raster_profile_matrix_20260719\fixtures\spring_river_project `
  --plan-number 02 --ras-version 7.0 `
  --map-type Depth --profile Max `
  --store-map-batch-bytes 2097152 `
  --store-map-statistics-modes serial `
  --store-map-pipeline-workers 0,1,8 `
  --store-map-pipeline-queue-depth 0 `
  --output-root working\native_tiff_experiments\spring-river-parallel-v2 `
  --timeout 7200
```

The benchmark hashes the source HDF before and after, uses unique output roots,
and requires HDF preservation plus decoded-pixel and geospatial/metadata
equivalence. "Histogram equivalence" means equality of histogram/statistics
metadata exposed through TIFF tags/domains; the benchmark does not claim access
to an unexposed RASMapper in-memory histogram. Detailed
measurements are in [RESULTS.md](RESULTS.md).

The 2 MiB runner default is a measured candidate, not a claim that larger
buffers always win. A five-repeat isolated sweep found no latency benefit from
4–64 MiB, even though raw SMB storage throughput continued improving at larger
request sizes. TIFF seeks and directory updates force early buffer flushes.

## Release boundary

Do not distribute or auto-enable the rebuilt assembly. Promotion would require
HEC permission/licensing review, version coverage, repeated warm/cold trials,
cancellation and partial-output tests, BigTIFF beyond 4 GiB, multi-part terrain,
and GUI reopen validation. The safe supported feature remains map-level helper
parallelism, memory admission, GDAL controls, and profiling.
