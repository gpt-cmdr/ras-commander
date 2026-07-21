# Copied TiffAssist parallel-tile results

## Outcome

The copied-assembly experiment proves that steps 4–5 of the native writer can
be reimplemented safely as parallel tile preparation/Deflate plus one raw-tile
commit owner. It also identifies when that change matters:

- a continuously fed isolated writer scaled from a 2.435-second original median
  to 0.815 seconds at eight workers, a 66.5 percent reduction;
- Spring River did not scale beyond one worker because RASMapper's terrain/HDF/
  map-value producers, not Deflate or raw commit, paced the 84-second tile
  pipeline;
- batching remains useful: Spring's 256 KiB case changed StoreMap process writes from
  about 50.7 IOPS at 22.4 KiB to 5.2 IOPS at about 224 KiB;
- decoded pixels, dimensions/types, CRS, transform, NoData, required overview
  levels, and exposed TIFF metadata/statistics remained equivalent in every
  reported case. Layout and compression were also unchanged in the reported v2
  cases, but are recorded rather than required by the general semantic check.

The experiment remains opt-in and research-only. The installed HEC-RAS files
were never opened for write, and post-build hashes still match the pinned
inputs.

## Version and build proof

| Item | Value |
|---|---|
| Patch ID | `tiffassist-parallel-tiles-v2` |
| Installed `TiffAssist.dll` SHA-256 | `acd6ada0dbaacf5aa314aca9a087fe5c6699ca582afac1c9060c8404f6a254c9` |
| Current copied patched DLL SHA-256 | `8c856be47b7bce5829d05da1dee8077d3e8a2f6af7231b9b0dfa180bef4c2c6a` |
| Assembly name/version | `TiffAssist`, 1.0.0.0 |
| Installed hashes unchanged | true |
| Enabled by default | false |

Authoritative manifest:

```text
working/native_tiff_experiments/hr70-acd6ada0-tiff-parallel-v2/patch_manifest.json
```

The manifest records and revalidates five generated artifact identities: both
copied runtimes, the second minimal patched runtime, and both harness
executables. It also verifies every pinned installed input before and after a
benchmark run and rejects artifacts outside the prepared root.

## Final manifest/equivalence smoke

The final 4096 by 4096 gate used the rebuilt manifest, eight workers, queue
depth 2, and 256 KiB batches. The original took 1.880 seconds and 263 process
writes; the serial-statistics parallel path took 1.175 seconds and 45 writes,
a 37.5 percent wall reduction. The parallel output matched decoded pixels,
dimensions/types, NoData, transform, dataset tags, and numeric band statistics.
Its different physical file hash is expected from raw tile placement.

The synthetic-only `none` statistics control retained identical pixels and
raster structure but correctly failed semantic equivalence because statistics
tags were absent. Path-generated `DERIVED_SUBDATASETS` and physical-layout
`IMAGE_STRUCTURE` namespaces are deliberately excluded from semantic equality;
arbitrary application metadata domains remain exact-match requirements.

```text
working/native_tiff_experiments/manifest-gate-smoke-v4/summary.json
```

## Isolated writer scaling

Fixture: 8192 by 8192 Float32, 1024 native 256 by 256 tiles, 16 reusable input
templates, serial-within-tile statistics, 256 KiB client-I/O batch. Medians or
representative values are shown; all outputs were semantically equivalent.

| Case | Wall seconds | Change from original |
|---|---:|---:|
| Installed original, median of 3 | 2.435 | baseline |
| Parallel pipeline, 1 worker | 3.394 | 39.4% slower |
| Parallel pipeline, 2 workers | 1.832 | 24.8% faster |
| Parallel pipeline, 4 workers | 1.095 | 55.0% faster |
| Parallel pipeline, 8 workers, median of 3 | 0.815 | 66.5% faster |

One worker pays snapshot/queue/private-encoder overhead without compression
parallelism. At eight workers, one run occupied 4.64 logical CPUs and used
roughly 75–92 MiB private memory versus about 42 MiB for the original. This is
real multicore compression, but it requires a producer capable of keeping the
input queue populated.

Raw data:

```text
working/native_tiff_experiments/parallel_writer_only_8192/
working/native_tiff_experiments/parallel_writer_only_8192_trial2/
working/native_tiff_experiments/parallel_writer_only_8192_trial3/
```

## Queue and batch bounds

Eight-worker writer-only queue trials showed no benefit from retaining large
backlogs:

| Queue depth | Wall seconds | Peak private MiB | Maximum owned tiles |
|---:|---:|---:|---:|
| 1 | 0.782 | 73.5 | 11 |
| 2 | 0.776 | 75.7 | 13 |
| 4 | 0.820 | 80.6 | 17 |
| 8 | 0.786 | 79.7 | 25 |
| 16 | 0.832 | 82.0 | 41 |
| 32 | 0.813 | 82.4 | 73 |

Depth 2 is therefore the copied assembly default. A new five-repeat sweep
extended the legal range through 64 MiB:

| Requested batch | Median s | Range s | Median process writes | Median mean write | Median peak RSS MiB |
|---:|---:|---:|---:|---:|---:|
| 64 KiB | 0.803 | 0.768–0.816 | 644 | 48.0 KiB | 73.6 |
| 256 KiB | 0.786 | 0.773–0.900 | 135 | 228.9 KiB | 73.1 |
| 1 MiB | 0.797 | 0.777–0.868 | 42 | 736.2 KiB | 70.7 |
| 2 MiB | **0.747** | 0.728–0.842 | 21 | 1,471.7 KiB | 71.8 |
| 4 MiB | 0.847 | 0.757–0.943 | 19 | 1,627.5 KiB | 76.8 |
| 8 MiB | 0.818 | 0.779–0.904 | 15 | 2,061.5 KiB | 77.4 |
| 16 MiB | 0.833 | 0.744–0.902 | 7 | 4,415.1 KiB | 87.4 |
| 32 MiB | 0.835 | 0.795–0.925 | 21 | 1,473.3 KiB | 102.1 |
| 64 MiB | 0.854 | 0.819–0.913 | 11 | 2,811.1 KiB | 100.0 |

The benchmark CLI now proposes 2 MiB. The copied assembly fallback stays at
256 KiB so opt-in behavior does not change merely from rebuilding. Larger
requests can reduce calls but do not guarantee large contiguous commits:
LibTiff seeks and directory updates flush the client buffer early. At 64 MiB,
median latency was 14.3 percent slower and RSS about 28 MiB higher than 2 MiB.

Raw data:

```text
working/native_tiff_experiments/parallel_writer_queue_8192/
working/native_tiff_experiments/parallel_writer_batch_8192/
working/native_tiff_experiments/extended_batch_8192_r1/ through r5/
```

## Spring River Depth Max

Fixture: local disposable Spring River BLE project, plan 02, HEC-RAS 7.0, one
Depth Max map, 28,916 by 26,316 terrain, 4,825 data tiles passed through the
parallel pipeline. Each row is one sequential sample.

| Case | Total s | StoreMap s | StoreMap cores | Store write IOPS | Mean store write | Overview s | Overview cores | Peak private GiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Installed original | 112.21 | 95.62 | 2.84 | 50.7 | 22.4 KiB | 16.17 | 1.36 | 9.32 |
| Batched, pipeline off | 110.31 | 93.90 | 2.91 | 5.4 | 224.5 KiB | 15.64 | 1.35 | 10.68 |
| Batched, 1 worker | 108.78 | 92.38 | 2.91 | 5.2 | 224.6 KiB | 15.78 | 1.36 | 6.86 |
| Batched, 8 workers | 109.64 | 93.24 | 2.87 | 5.2 | 223.5 KiB | 15.87 | 1.34 | 9.51 |

All four outputs have the same decoded pixel SHA-256:
`aa74abd3e99871adf9ec2c945460ef290dd0c6ed7ad80d51c9fee84f65fc61e1`.
The source plan HDF was unchanged.

The 11,715 logical LibTiff writes were coalesced into 494 underlying writes in
the one-worker case. The detailed pipeline measurements explain the worker
plateau:

| Metric | 1 worker | 8 workers |
|---|---:|---:|
| Pipeline wall seconds | 84.283 | 84.917 |
| Snapshot seconds | 0.325 | 0.413 |
| Input-queue wait seconds | 12.534 | 2.553 |
| Prepare/statistics seconds | 3.184 | 2.630 |
| Aggregate Deflate-call seconds | 26.596 | 24.980 |
| Encoded-queue wait seconds | 0.311 | 1.349 |
| Raw destination commit seconds | 0.661 | 0.487 |
| Maximum owned tiles | 6 | 12 |

Eight workers relieved burst-time producer blocking, but total pipeline time did
not fall because tile production arrived over roughly 84 seconds. Raw commit
consumed under 0.8 percent of pipeline wall time. Additional TIFF workers cannot
accelerate locked terrain/HDF reads, map-value computation, histogram reread,
or the mostly 1.35-core overview phase.

The peak-private variation is too large to attribute to the small pipeline in a
single run. The pipeline owned at most 12 tiles (only tens of MiB including its
float, byte, compressed, and codec buffers), while the helper tree varied from
6.86 to 10.68 GiB. Spring memory is dominated by RASMapper terrain, mesh, HDF,
CLR, and intermediate state.

Raw data:

```text
working/native_tiff_experiments/spring-river-parallel-v2/summary.json
working/native_tiff_experiments/spring-river-parallel-v2/summary.csv
working/native_tiff_experiments/spring-river-parallel-v2/summary.md
```

### Final fixed compressed-buffer pool rerun

The final rebuilt DLL rents fixed-capacity compressed buffers instead of
allocating one exact-sized array per variable compressed tile. A fresh
sequential original/one-worker/eight-worker Spring run produced:

| Case | Total s | Native map/write s | Native cores | Store write IOPS | Mean store write | Overview s | Overview cores | Peak private GiB | Compressed buffers allocated |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Installed original | 112.747 | 96.610 | 2.80 | 50.5 | 22.4 KiB | 16.077 | 1.29 | 10.95 | n/a |
| Batched, 1 worker | 112.354 | 96.191 | 2.77 | 5.1 | 224.4 KiB | 16.029 | 1.37 | 9.21 | 4 |
| Batched, 8 workers | 110.432 | 94.596 | 2.87 | 5.2 | 224.0 KiB | 15.747 | 1.33 | 11.25 | 9 |

The eight-worker sample was 2.1 percent faster end to end than its sequential
installed baseline, but the important repeatable result is the roughly tenfold
IOPS reduction and bounded allocation count. Its pipeline still spanned 86.00
seconds; aggregate Deflate time was 27.67 seconds and raw commits only 0.69
seconds. The producer remained the controlling cadence. All three source-HDF
checks passed, and both patched outputs matched the installed output's decoded
pixels, required overviews, and exposed TIFF metadata.

```text
working/native_tiff_experiments/spring-river-final-pool-v2/summary.json
working/native_tiff_experiments/spring-river-final-pool-v2/summary.csv
working/native_tiff_experiments/spring-river-final-pool-v2/summary.md
```

## Bald Eagle real StoreMap

The small Bald Eagle fixture remained pixel-equivalent. Batching reduced 589
logical writes to about 22 physical writes, but total runs remained around
3.2–3.4 seconds because the test is dominated by RAS production and overview
startup. This is consistent with Spring: TiffAssist parallelism helps only when
tile input is sufficiently dense.

Earlier three-pair SMB batching tests had a 14.5 percent faster median but one
severe outlier. They remain storage evidence, not a release-quality performance
claim.

The expanded local batch comparison used three paired original/patched runs at
256 KiB, 2 MiB, and 16 MiB. Median paired changes were +0.7, -2.7, and +2.7
percent respectively, with ranges crossing zero for every size. The TIFF
writer's underlying calls fell from 21 at 256 KiB to 6 at 2 MiB and 5 at
16 MiB, but this small product is dominated by producer and overview startup.
The honest conclusion is fewer writer calls with end-to-end differences inside
run noise, not a universal whole-pipeline speedup.

## Correctness coverage

The benchmark verifies:

- full-width row-strip decoded Float32 hashes, independent of tile layout;
- width, height, band count, dtype, native 256 by 256 blocks, compression,
  NoData, CRS, and transform;
- dataset and band metadata, with only `1e-12` relative tolerance for serial
  statistics reduction-order differences;
- odd raster dimensions and partial edge tiles;
- RASMapper's raw-NoData tile path, including replacement of seeded tile zero;
- source HDF hashes before and after real StoreMap runs;
- copied-runtime identity and installed-DLL immutability.

Physical TIFF bytes can differ because independently compressed tiles commit in
worker-completion order and offsets change. The decoded raster and exposed TIFF
contract remain equivalent.

"Histogram" in this acceptance record means histogram/statistics metadata
exposed through TIFF tags/domains. It does not assert access to an unexposed
RASMapper in-memory histogram representation.

## Recommendation

Keep native TIFF workers opt-in in the copied research harness. The benchmark
candidate is 2 MiB, queue depth 2, serial-within-tile statistics, and zero
workers unless profiling demonstrates a dense writer-fed workload; retain
256 KiB as the inert assembly fallback. For
Spring-like projects, prioritize memory-aware map-level scheduling, terrain/HDF
producer investigation, histogram avoidance, and overview strategy; more
Deflate workers alone are not the end-to-end answer.
