# Native HDF sessions

Bridge API 8 pins engine `b2fe41d2b93f0c678b7fba47601c103677566866`.
`ras_commander_fast_hdf.HdfSession(path, threads=None, parallel=True)` keeps
one read-only engine session open. Use it as a context manager or call `close()`.
Closing is idempotent, waits for active native reads and releases file mappings.
Reading after close raises `ValueError`; returned NumPy buffers remain valid.
Methods include numeric/batch reads and mesh summary, series and boundary reads,
their inventories, and series reduction. Typed element selections take contiguous
`numpy.uint64` arrays; elements and extrema indices return NumPy arrays. Existing
module-level functions remain available and retain list inputs. API 7 changes
their element/index outputs to NumPy arrays too.

`fast_hdf.read_dataset()` and `read_datasets()` reuse at most four sessions in an
LRU cache. Keys contain resolved path, size and nanosecond modification time.
Changing explicit thread settings replaces that path's cached session.
Set `RAS_COMMANDER_HDF_SESSION_CACHE=0` to open and close per operation.
`fast_hdf.close_sessions(path=None)` closes one path or all cached sessions.
Windows `RasCmdr.compute_plan()` closes this cache before preparing execution;
parallel and test-mode paths delegate there. Explicit native sessions are caller
owned and must be closed before execution or source mutation. Do not read the
same files concurrently with HEC-RAS or another writer. Stat invalidation cannot
detect a same-size edit whose modification time is deliberately restored.

The four-file bound limits handles, not total memory. Engine metadata and chunk
caches retain their own budgets and documented limitations. Cached reads are
serialized with cache eviction; native session methods serialize against close.
Public pandas/xarray construction and automatic unsupported-layout fallback are
unchanged. A read-only h5py handle used by the caller must also be closed before
replacing a file on Windows.


API 8 adds keyword-only `cache_bytes` (default 64 MiB) and `cache_slots`
(default 521) to `HdfSession`, plus `cache_stats()`. Full reads above that byte
limit bypass retention. `read_mesh_summary_values` returns the same numeric array
without allocating element identities or a result dictionary. Existing summary
methods keep their return contract. `read_mesh_boundary_batch(area, rows,
names=None)` returns a name-keyed dictionary of existing selection results for
all lines or a named subset; its output budget is shared across the batch.
`fast_hdf.read_datasets` groups canonical per-area BC paths into these calls.
Legacy non-area BC paths retain the generic numeric batch. Decoder scratch
remains additional to the configured retained cache and result-byte budgets.


PERF-2 review fixes: engine API6. Auto-mode BC batch dispatch retries typed
qualification refusals through the generic batch reader, preserving API7/h5py
values and ordering. Required/rust mode stays strict; host I/O, closed-session
and internal failures are not retried. Requested-only BC reads and named subsets
ignore corrupt unrequested siblings; inventories and all-lines batches report
them. Cache defaults derive from the engine/vendor constants. Zero bytes disables
both decoded-chunk retention and the optional 32 MiB hot-array copy deliberately,
so zero means no data retention. Non-inline EA indexes now refuse explicitly
instead of silently returning zeros. No local timing is authorized for this fix.
