# HDF Results Query Architecture

This decision resolves the exploratory work tracked in #306–#309.

## Decision

`ras-commander` remains the semantic HEC-RAS layer and provides three levels of
result access:

1. Existing eager pandas, xarray, and GeoPandas APIs remain the default.
2. Direct selections, geometry-free summaries, and public batch iterators
   support bounded extraction without a new dependency.
3. `HdfResultView` is an opt-in, source-backed query object for deferred
   selection, batching, reduction, and conversion to established containers.

DuckDB is not a core dependency and a raw `DuckDBPyRelation` is not a core
return type. Database/session ownership, SQL schema evolution, durable
materialization, and cross-product RAS/HMS relations belong in a separate
connector or the existing `ras2cng` integration. That connector should consume
`get_mesh_summary_values()`, `iter_mesh_timeseries()`, or
`HdfResultView.to_arrow()` rather than duplicate HEC-RAS paths and version
semantics.

## File lifetime and consistency

An `HdfResultView` owns no live HDF handle. It stores a resolved source path,
dataset path, shape, dtype, selection, and a size/mtime fingerprint. Every
operation reopens the file read-only and checks that fingerprint before and
after reading, failing if the source moved or ordinarily changed.
This makes views pickleable and safe to pass between ordinary processes while
preventing a long-lived object from silently mixing two result-file states.

An iterator keeps one read-only handle open only while it is being consumed.
Callers should finish or close an iterator before replacing a result HDF.

## Selection and batching

Time and spatial integer/forward-slice selections are applied directly to the
`h5py.Dataset`. Integer indexes remain length-one slices so xarray schemas are
stable. Batches are time-major because HEC-RAS commonly stores 2D results as
`(time, spatial_element)` with one-timestep chunks.

The default batch target is 16 MiB of values. Callers can set an explicit row
count or byte target. Materialization preserves the source dtype unless a
conversion is requested. Full-period max, min, mean, and argmax reductions use
the same bounded iterator and ignore NaN/infinite samples. Integer source data
is promoted to Float64 for value reductions; an explicit reduction dtype must
be floating point so nonfinite filtering cannot be corrupted by an integer
cast. Argmax always returns source time indexes as Int64.

Eager conversion reads the selected slab once and trims it in memory.
Streaming, reductions, and `shape` use a bounded active-window scan when
`truncate=True`; all-zero selections keep their full selected time extent.
The public `iter_mesh_timeseries()` convenience iterator is deliberately
untruncated so it emits every selected source timestep exactly once.

## Representative qualification

A read-only Windows qualification used a 482.6 MB computed Bald Eagle example
plan. Its `Water Surface` dataset contains 865 timesteps by 89,879 cells as
Float32, chunked `(1, 89879)`. Each scenario ran in a fresh process. The first
pass is only a cold-cache candidate—the operating-system cache was not flushed.

| Scenario | Cold candidate | Warm | Peak RSS delta (cold / warm) |
|---|---:|---:|---:|
| Lazy view creation | 0.0022 s | 0.0025 s | 1.5 / 1.5 MiB |
| Direct one-timestep slice | 0.0099 s | 0.0094 s | 3.5 / 3.5 MiB |
| Eager whole-array then slice | 1.284 s | 1.306 s | 315 / 318 MiB |
| Bounded raw maximum | 1.360 s | 1.358 s | 51.7 / 51.2 MiB |
| Eager raw maximum | 1.380 s | 1.351 s | 403 / 374 MiB |

A post-review rerun added the public default eager `truncate=True` scenario
after restoring its single-read implementation. It completed in 1.318/1.323 s
with 371/365 MiB peak RSS delta, eliminating the 2.95 s double-read regression
identified during independent QAQC. Direct/eager slice checksums and
bounded/eager maximum checksums remained identical.

The direct and eager timestep checksums matched. The bounded and eager raw
maximum checksums also matched. These timings are directional rather than a
cross-machine performance guarantee; rerun
`scripts/benchmarks/benchmark_hdf_result_reads.py` on representative local
plans.

A 5-by-4 synthetic benchmark also exercised cold-candidate and warm passes. At
that scale eager reads were faster because file-open and labeling overhead
dominates; this is why the established eager API remains the default and the
view/iterator are opt-in tools for large or selectively queried results.

## Geometry boundary

`get_mesh_summary_values()` returns identifiers, values, times, and HDF
metadata only. Existing `get_mesh_summary()` adds geometry once per call, after
the values have been assembled. SQL ingestion and aggregate analytics should
use the geometry-free form; map production can opt into the spatial form.

## DuckDB and HDF extensions

The production connector boundary is a separate optional package or `ras2cng`:

- Arrow batches are the preferred in-process interchange when PyArrow is
  installed.
- Parquet/DuckDB materialization is preferred for repeated queries.
- A direct community HDF extension such as `h5db` remains experimental until
  its dependency/supply-chain posture, compound-type behavior, HEC null-value
  handling, and numerical equivalence are independently audited.
- The connector must retain source fingerprints, plan/mesh identifiers, units,
  timestamps, and the distinction between native summaries and raw reductions.

This boundary keeps `ras-commander` lightweight while giving RAS and HMS tools
a reusable semantic input surface for a future shared SQL schema.
