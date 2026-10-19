# Native HDF sessions

Bridge API 7 pins engine `dbb0e52e0965a463b9c730b843bd0e3a2a2b9f6c`.
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
