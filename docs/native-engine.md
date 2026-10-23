# Native Rust HDF Engine

ras-commander can read HEC-RAS HDF files (plan results, geometry, terrain and
land-cover sidecars) through an optional native engine written in Rust, instead
of through h5py. This page explains what the engine is, how to install and
select it, what "identical results" means and how that was proven, how fast it
is, and what it does not do.

!!! info "Short version"
    - The engine is an **optional, internally distributed** Python wheel,
      `ras-commander-fast-hdf`. Without it, ras-commander works exactly as
      before, on h5py.
    - With it installed, the default mode `auto` reads natively where the
      native path is qualified and falls back to h5py on any refusal. **Public
      results are identical to h5py**: same values, dtypes, columns, index,
      CRS, attributes and exceptions.
    - Set `RAS_COMMANDER_FAST_HDF=h5py` to switch the engine off completely.

## What it is and why

ras-commander's `Hdf*` classes have always read HDF5 through h5py and the HDF5
C library. The native engine replaces the *value reads* underneath those
classes, not the classes themselves:

- **Same public API.** No method was renamed or removed, and no positional
  parameter or default changed. Your code does not change.
- **One reader for numbers, text and attributes.** Numeric datasets, compound
  tables, fixed-length text (compute messages, timestamps, profile names) and
  attributes are decoded by the engine, then handed to the same pandas,
  xarray and GeoPandas construction code as before.
- **Mesh geometry in Rust.** 2D cell polygons are assembled natively, with the
  same ring order, vertex order and WKB as the Python polygonizer.
- **Hardened against damaged files.** The engine is written in safe Rust
  (`#![forbid(unsafe_code)]`), budgets every read before allocating, and turns
  a panic into a Python exception instead of a process crash. A truncated or
  corrupted HDF gives an ordinary exception; in `auto` mode it gives exactly
  the h5py outcome.

Why: faster bulk and sparse reads of large result datasets (especially
compressed 2D time series), fewer HDF5 C-library failure modes in long batch
jobs, and the same code path on Windows and Linux.

The engine is not a general HDF5 library. It reads what HEC-RAS writes and
refuses anything it cannot reproduce exactly (see
[Limitations and refusals](#known-limitations-and-refusals)).

## Installing the wheel

The wheel is **distributed internally by CLB Engineering Corporation**. It
contains private engine code; do not upload it to PyPI or share it outside
CLB. Two builds exist, both for CPython 3.10 and later (`abi3`):

| Platform | Wheel |
|---|---|
| Windows x64 | `ras_commander_fast_hdf-0.1.0-cp310-abi3-win_amd64.whl` |
| Linux x64 (glibc 2.28+, e.g. Rocky/RHEL 9, Ubuntu 20.04+) | `ras_commander_fast_hdf-0.1.0-cp310-abi3-manylinux_2_28_x86_64.whl` |

Install it into the same environment as ras-commander:

```powershell
pip install path\to\ras_commander_fast_hdf-0.1.0-cp310-abi3-win_amd64.whl
```

No Rust toolchain is needed to install a wheel. Building from source needs
access to the private engine repository; see `rust/fast-hdf` in the
ras-commander repository.

### Verify the installation

```python
import ras_commander_fast_hdf as native
print(native.API_VERSION)      # 11
print(native.ENGINE_COMMIT)    # 3c2d4799ffdad01452682b82ca64305279ecc679
print(native.ENGINE_FEATURES)  # ('catalog', 'hdf', 'mesh', 'results')

from ras_commander import fast_hdf
print(fast_hdf.available())    # True
```

ras-commander only uses an extension whose `API_VERSION` is exactly the one it
was built against (11 for this release). An older or newer wheel is ignored
with one logged warning, and every read uses h5py; in `native` mode it raises
`FastHdfError` instead. `fast_hdf.available()` returns `False` in both cases.

## Engine modes

There are three modes. The environment variable selects the mode for every
routed read in the process; methods that take an `engine=` argument let you
choose per call.

| Mode | Behaviour | Use it for |
|---|---|---|
| `auto` (default) | Native first. **Any** native refusal or failure (unsupported layout, over-budget read, corrupt data, checksum error, contained panic) falls back to h5py for that read, so the public result or exception is the h5py one. Methods whose native path is not yet qualified run on h5py. | Normal use. |
| `h5py` | Never touches the native extension. Exactly the pre-engine behaviour. | Comparison, troubleshooting, or if you do not want native code in the process. |
| `native` | Native or fail: a refusal raises `FastHdfError` instead of falling back. | Qualification and testing; proving that a workflow really ran natively. |

### Environment variable

```powershell
$env:RAS_COMMANDER_FAST_HDF = "h5py"    # auto | h5py | native
```

```bash
export RAS_COMMANDER_FAST_HDF=h5py
```

| Value | Mode |
|---|---|
| unset, empty, `auto` (also `1`, `on`, `true`) | `auto` |
| `h5py` (legacy aliases `0`, `off`, `false`, `python`) | `h5py` |
| `native` (legacy aliases `required`, `rust`) | `native` |

An unrecognised value (for example a typo) is treated as `auto` and logged
once; it can never turn reads into empty results. Set the variable before the
first read; the value is read on each routed call.

### Per-call `engine=` argument

The methods that historically had their own backend switch take `engine=`
with the same three values, default `"auto"`:

- `HdfMesh.get_mesh_cell_polygons` and `HdfMesh.diagnose_mesh_cell_polygons`
- `HdfFluvialPluvial.calculate_fluvial_pluvial_boundary` and
  `HdfFluvialPluvial.generate_fluvial_pluvial_polygons`

```python
from ras_commander import HdfMesh
cells = HdfMesh.get_mesh_cell_polygons("model.p01.hdf")                   # auto
cells = HdfMesh.get_mesh_cell_polygons("model.p01.hdf", engine="h5py")    # reference path
```

An explicit `engine="h5py"` or `engine="native"` overrides the environment
variable for that call. `engine="auto"` follows the environment variable, so
`RAS_COMMANDER_FAST_HDF=h5py` turns native off everywhere.

The fluvial/pluvial methods record what ran in
`result.attrs["fluvial_engine"]` (`requested`, `used`, and the fallback reason
when `auto` used the Python reference).

**Mesh polygon diagnostics are opt-in.** `get_mesh_cell_polygons` attaches the
per-cell `cell_polygon_diagnostics` records only with `diagnostics=True`
(default `False`). Geometry, `mesh_name` and `cell_id` do not depend on this
flag.

## What is identical, and how it was proven

### The equivalence contract

In `auto` mode, every public `Hdf*` method returns what it returns in `h5py`
mode:

- the same values, bit for bit (floating-point values are not recomputed;
  they are the stored bytes);
- the same dtypes, including `datetime64[ns]` timestamps (and `[us]` beyond
  2262), stored byte order and fixed-string types;
- the same columns, index, row order, CRS and `attrs`;
- the same geometry, compared as WKB (ring orientation, ring start vertex and
  vertex order included);
- the same exception type and message when the h5py path raises.

The engine never "repairs" data that h5py would return differently. When it
cannot reproduce the h5py result exactly, it refuses, and `auto` uses h5py.

### Qualified methods

A method runs natively in `auto` mode only when the test corpus has shown that
its native output is identical to h5py. Methods that are not yet qualified run
on h5py in `auto` mode (they still work; they are just not faster). The table
below lists each public method and its status in this release.

<!-- QUALIFIED_METHODS_TABLE -->

Evidence: the release gate route suites on the final branch (route-1 and extents: gate1; route-2: the
requalification run on the full corpus manifest, 137 fixtures).
A *case* is one public method or one parameterised variant of it. *Qualified* means at
least one real fixture made a native read and returned a result identical to h5py
(values, dtypes, columns, index, attrs, CRS, exceptions). Cases with no native-identical
fixture run on h5py in auto mode until a fixture proves them
(`ras_commander.fast_hdf.UNQUALIFIED_NATIVE`, decorator `h5py_until_qualified`).

| Class | Cases qualified native | Native-identical method x fixture pairs | Cases running on h5py in auto |
|---|---:|---:|---:|
| `HdfBase` | 11 | 244 | 0 |
| `HdfBndry` | 7 | 40 | 0 |
| `HdfChannelCapacity` | 4 | 58 | 0 |
| `HdfCompletion` | 1 | 53 | 0 |
| `HdfHydraulicTables` | 3 | 66 | 0 |
| `HdfInfiltration` | 12 | 140 | 2 |
| `HdfLandCover` | 11 | 338 | 2 |
| `HdfMesh` | 15 | 168 | 1 |
| `HdfPipe` | 22 | 191 | 0 |
| `HdfPlan` | 11 | 584 | 1 |
| `HdfProject` | 7 | 175 | 0 |
| `HdfPump` | 4 | 23 | 1 |
| `HdfResultsAnalysis` | 2 | 14 | 0 |
| `HdfResultsBreach` | 4 | 92 | 0 |
| `HdfResultsMesh` | 24 | 277 | 0 |
| `HdfResultsPlan` | 13 | 298 | 2 |
| `HdfResultsProducts` | 1 | 13 | 0 |
| `HdfResultsQuery` | 12 | 192 | 0 |
| `HdfResultsSediment` | 6 | 28 | 2 |
| `HdfResultsXsec` | 4 | 24 | 0 |
| `HdfStorageArea` | 6 | 129 | 0 |
| `HdfStruc` | 6 | 214 | 0 |
| `HdfStruc1D` | 1 | 10 | 0 |
| `HdfUtils` | 4 | 248 | 0 |
| `HdfXsec` | 10 | 181 | 0 |
| **Total** | **201** | **3800** | **11** |

Public methods running on h5py in auto mode (their data is absent from every corpus fixture):

- `HdfInfiltration.get_infiltration_parameters`
- `HdfInfiltration.get_soils_raster_stats`
- `HdfLandCover.compute_final_mannings_raster`
- `HdfLandCover.estimate_final_mannings_raster`
- `HdfPlan.get_starting_wse_method`
- `HdfPump.get_pump_station_summary`
- `HdfResultsPlan.get_reference_summary[lines]`
- `HdfResultsPlan.get_reference_summary[points]`
- `HdfResultsSediment.get_sediment_mesh_areas`
- `HdfResultsSediment.is_sediment_plan`

`HdfMesh.get_mesh_geometry_inventory` reads only metadata through h5py and is unaffected.
Internal helpers outside `ras_commander/hdf` are marked the same way (see
`UNQUALIFIED_NATIVE`).
<!-- /QUALIFIED_METHODS_TABLE -->

### How it was proven

The release gate (engine `3c2d479`, bridge API 11, pandas 2.3.2, numpy 2.3.3,
h5py 3.14.0, Windows) ran these equivalence suites. Each routed case is run in
`h5py`, `auto` and `native` mode and compared; a case passes only if the
native read was actually made *and* its public result equals the h5py result.

| Suite | What it covers | Result |
|---|---|---|
| Existing native contract tests | bridge, sessions, conservatism | 178 passed, 84 skipped |
| Quarantine | mesh-result layouts held back from earlier releases | 51 passed |
| Route 1 | 2D mesh geometry and results, 1D geometry, cross-section results, structures | 2,119 passed, 3 skipped |
| Route 2 | pipes, pumps, reference lines/points, breach, plan metadata, land cover, infiltration, terrain, sediment, encroachments, steady output | 5,635 passed |
| Route 3 | 2D mesh series domains (`Location` rule, legacy layouts) | 100 passed, 159 skipped |
| Extents | project extents, point/profile queries, max depth, raster products | 1,220 passed, 12 skipped |
| Non-HDF modules | HDF reads made outside `ras_commander.hdf` (131 call sites in 60 modules) | 3,868 passed, 510 skipped |
| Fluvial/pluvial | native classification and boundary lines vs the order-invariant reference | 98 passed, 22 skipped |

Skips are fixtures that do not contain the data a case needs (for example a
1D-only geometry for a 2D method). In total 4,415 (method, fixture) pairs were
recorded as "native read made and identical to h5py", and every injected
native failure was confirmed to give the h5py outcome in `auto` and
`FastHdfError` in `native`.

**Fixture corpus.** About 65 real HEC-RAS HDF files plus 8 crafted excerpts:

- HEC-RAS example projects computed with HEC-RAS 6.6 and 7.0.1 (Bald Eagle
  Creek, Muncie, Davis storm system, Baxter, Beaver bridge, ConSpan culvert,
  Orleans urban model, inline gated spillways, junctions, lateral structures,
  encroachments, water quality, Weise and MBex sediment, Chippewa 2D);
- reference-line and reference-point variants of Bald Eagle dam break;
- geometry, terrain, land-cover, soils and infiltration sidecar HDFs;
- large production models: `BaldEagleDamBrk.p07` (87,039 cells, 865 output
  times, 460 MB), `JUL2020_D100RAS.p04` (340,248 cells, 597 MB), Homewood
  (68,743 cells) and the Glaise Creek eBFE model;
- crafted excerpts with invalid `Location` attributes, missing time axes, wrong
  counts and missing geometry, to prove that error behaviour is identical.

**Damaged and hostile files.** An independent QA re-check of the engine ran
265 public-API calls on crafted malformed files (each in its own process), a
fuzzing pass, and about 1.16 million concurrent native calls, including files
being corrupted and truncated while they were read. No call aborted the
process; every one returned a value or raised an ordinary Python exception.

**Notebooks.** The 31 Tier 1A example notebooks ran in `h5py`, `auto` and
`native` mode with zero errors in every mode. The remaining output differences
were traced to a harness artifact (an extra internal call shifting the call
log) and to polygon ring order, which was fixed in engine API 10 and confirmed
identical on 87,039 / 28,449 / 5,391 / 2,716-cell meshes. A re-run of Tier 1A
on the final combined release, and the Tier 1B and Tier 2 notebooks, are
pending.

## Performance

### Release benchmark (public methods)

<!-- PERF_RELEASE_TABLE: pending approved quiet-machine benchmark -->

A wall-time comparison of commonly used public methods (`h5py` vs `auto`, each
measurement in a fresh process, on small, medium and large fixtures, with
result hashes checked for identity) will be published here once it has been
run on a quiet machine. Until then, the figures below come from the earlier
engine performance work. They measure the **HDF read layer** (the reads under
the public methods), not complete public calls.

### Earlier evidence: read layer, Linux

Measured on `clb12-fim-hpc` (Rocky Linux 9, 8 vCPU Xeon W-1370P, 24 GiB, local
XFS), as an exclusive Slurm job, October 2026, with an earlier engine build
(bridge API 8). Each value is the median of 7 interleaved rounds; every output
hash was identical between native and h5py. "Fresh" opens the file for the
read; "reused" reads again through an open handle.

| Fixture | Read pattern | h5py fresh ms | native fresh ms | Native faster by |
|---|---|---:|---:|---:|
| BaldEagleDamBrk.p07 (87k cells) | whole 2D series (Water Surface) | 2,527 | 389 | 6.5x |
| BaldEagleDamBrk.p07 | whole dataset | 1,293 | 125 | 10.4x |
| BaldEagleDamBrk.p07 | 500 cells x 24 times, 10 repeats | 385 | 55 | 6.9x |
| BaldEagleDamBrk.p07 | one cell, full history | 1,265 | 851 | 1.5x |
| BaldEagleDamBrk.p07 | maximum WSE summary | 8.3 | 5.3 | 1.6x |
| Glaise Creek eBFE model | face area tables | 514 | 67 | 7.7x |
| Glaise Creek eBFE model | 500 cells x 24 times, 10 repeats | 1,947 | 255 | 7.6x |
| BaldEagleDamBrk.p18 (5k cells) | whole 2D series | 187 | 262 | 0.7x (slower) |
| BaldEagleDamBrk.p18 | one boundary-condition series | 3.1 | 14.9 | 0.2x (slower) |
| AustinOyster.p01 (3.6k cells) | maximum WSE summary | 2.1 | 3.3 | 0.6x (slower) |

Across all 45 measured patterns (9 workloads on 5 fixtures):

- **fresh reads:** native had the lower median in 36 of 45 patterns against
  default h5py, and in 35 of 45 against h5py with a 64 MiB chunk cache;
- **reused handles:** native had the lower median in 29 of 45 against default
  h5py, but only 21 of 45 against h5py with a 64 MiB chunk cache.

### Earlier evidence: reads above 2 GiB, Windows

Whole-dataset reads on this release's engine (`3c2d479`), one process per run;
cold = first run (OS file cache cold), warm = second run. SHA-256 of every
result was identical between h5py and native.

| Dataset | Storage | Size | h5py s cold / warm | native s cold / warm |
|---|---|---|---|---|
| synthetic 288 x 2,097,152 float32 | gzip, chunked | 2.25 GiB | 9.04 / 6.24 | 2.58 / 2.48 |
| synthetic 640 x 2,097,152 float32 | gzip, chunked | 5.0 GiB | 20.61 / 13.62 | 5.15 / 4.80 |
| BaldEagleDamBrk.p07 Face Velocity (865 x 177,301) | gzip, chunked | 0.57 GiB | 1.54 / 1.53 | 0.88 / 0.96 |
| synthetic 288 x 2,097,152 float32 | contiguous | 2.25 GiB | 5.87 / 0.67 | 3.84 / 3.75 |
| synthetic 640 x 2,097,152 float32 | contiguous | 5.0 GiB | 13.41 / 1.82 | 7.64 / 8.04 |

### Where native is faster, equal or slower, and why

- **Faster: bulk and sparse reads of compressed result data.** HEC-RAS stores
  2D time series gzip-compressed in chunks. The engine decompresses chunks in
  parallel and gathers only the requested cells from each decoded chunk, where
  h5py decompresses chunk by chunk on one thread. This is where the 6-10x
  read-layer gains above come from, and it grows with model size.
- **Faster: first read of a large file.** The engine caches the file's layout
  (group names, heaps, dataset descriptors) per session, so metadata-heavy
  operations on large models are much cheaper on first touch (an internal
  catalogue scan of `JUL2020_D100RAS.p04` went from 30.5 s to 0.21 s during
  the engine performance work).
- **Equal: most of a public call is not the read.** Public methods build
  pandas, xarray and GeoPandas objects (cell points and polygons, CRS
  resolution, timestamp conversion). That code is unchanged and runs the same
  in both modes, so a method's end-to-end gain is smaller than its read gain,
  and on small models it can be negligible.
- **Slower: very small reads, and reused h5py handles.** For reads of a few
  milliseconds (single boundary-condition series, small summaries on
  3-5k-cell models), the engine's fixed per-read cost (selection checks,
  typed-layout validation, session setup) can exceed h5py's. With a handle
  held open and a large chunk cache, h5py serves sub-millisecond repeat reads
  from memory, and native has no advantage there.
- **Slower: uncompressed (contiguous) data from a warm OS cache.** h5py copies
  contiguous data straight from the page cache (0.67 s for 2.25 GiB warm),
  while the native block path takes about 3.8 s. Native is still faster cold.
  For this reason contiguous reads above the 2 GiB budget go to h5py in
  `auto` mode.

## Sessions and open files

The engine reads through a session that holds the HDF file open. By default:

- a session opens inside the first public `Hdf*` call that needs it, is shared
  by every read of that call, and **closes when the call returns** (also when
  it raises);
- a read outside any public call (direct use of `fast_hdf`, or a lazy iterator
  such as `HdfResultsMesh.iter_mesh_timeseries` or `HdfResultView.iter_batches`
  consumed after its call returned) opens and closes its own session.

So no HDF stays open after an `Hdf*` method returns. Renaming, deleting,
replacing or re-extracting a project folder works exactly as without the
engine, which matters on Windows and on network shares, where an open file
blocks these operations.

`RAS_COMMANDER_HDF_SESSION_CACHE` changes the trade-off:

| Value | Behaviour |
|---|---|
| unset or `1` (default) | One session per public call, as above. |
| `0` | Open and close the file around every individual native read (slowest). |
| `persist` | Keep up to four sessions open across public calls (fastest for many repeated calls on the same files). Call `fast_hdf.close_sessions()` (or `close_sessions(path)`) before moving, replacing or deleting the files and before running HEC-RAS. `RasCmdr.compute_plan()` already does this. |

Keeping sessions across calls (`persist`) saves a few percent on repeated
reads of one file; the default favours never holding a file open.

## Large reads

- **Per-call budget.** The engine refuses any single read larger than 2 GiB
  *before allocating*, so a damaged or crafted header cannot make it reserve
  memory the file does not hold.
- **Chunked, compressed datasets above 2 GiB** (the usual layout of large 2D
  time series) are read natively as bounded 256 MiB hyperslab blocks, aligned
  to the stored chunks, into one NumPy array. The result is the array h5py
  returns.
- **Plausibility check.** Before the output is allocated, the declared size is
  checked against the storage the file really holds: contiguous data must be
  allocated and inside the file; chunked data must not decode to more than its
  stored bytes allow for its filters (deflate at most 1,100x, LZ4 256x, n-bit
  64x; scale-offset, szip and unknown filters cannot be bounded and are
  refused); at most 2 GiB may come from the fill value of unallocated chunks.
- **Contiguous (uncompressed) datasets above 2 GiB** go to h5py in `auto`
  mode, because h5py's direct copy from the OS page cache is faster for them
  (see [Performance](#performance)). In `native` mode they raise
  `FastHdfError`.
- **Memory.** A native read above the budget peaks about 0.4 GiB (compressed)
  to 0.8 GiB (contiguous) above h5py: the output array plus block buffers in
  flight.

No HEC-RAS model in the test corpus comes close to the budget: the largest
single dataset is 585 MiB (`BaldEagleDamBrk.p07` face velocity).

## Known limitations and refusals

The engine refuses, rather than approximates, anything it cannot reproduce
exactly. In `auto` mode each of these reads uses h5py; in `native` mode it
raises `FastHdfError`.

| Case | Behaviour |
|---|---|
| **Variable-length strings** (datasets and attributes) | Not decoded natively. Variable-length text datasets and all-text identity tables (for example cross-section River/Reach/RS rows) are read through h5py in every mode, as metadata. Variable-length, compound and enum *attributes* fall back. |
| **Big-endian datasets** | Keep their h5py path at any size. |
| **Virtual, external and SWMR datasets** | Refused. |
| **2 GiB per-call budget** | See [Large reads](#large-reads). The budget cannot be changed from Python in this release. |
| **Unsupported selections** | Basic slices and single increasing integer index vectors are read natively. Field names, boolean masks and other fancy indexing stay on h5py. Invalid selections raise h5py's own exception in every mode. |
| **Group walks, `in` checks, shape probes** | Always h5py. `native` mode guarantees native *value and attribute* reads, not that h5py is never opened. |
| **Fluvial/pluvial with `delta_t=0`** | Not supported natively (the native kernel would mark equal-time cell pairs ambiguous; the reference marks nothing). `auto` uses the Python reference. Native is also refused when a mesh lacks `Faces Cell Indexes`, when the cell set differs from the one the reference can polygonize, or when cells have invalid geometry (for example 2 cells in `JUL2020_D100RAS.p04`). |
| **Mesh polygon diagnostics** | Automatic mode returns the native polygons only when their diagnostic records, warnings and `strict` outcome are provably the Python polygonizer's. Ambiguous or multi-polygon cells and other edge cases use the Python polygonizer. In `native` mode, the diagnostics records of a `no_polygon` cell can carry extra `native_reason_code`/`reason` keys. Diagnostics are attached only with `diagnostics=True`. |
| **Methods not yet qualified** | Run on h5py in `auto` mode; see the [qualified-methods table](#qualified-methods). |

Other notes:

- A panic inside the extension is contained and raised as `FastHdfPanicError`,
  but Rust still prints its default "thread ... panicked at ..." line to
  stderr. In `auto` mode the read then completes on h5py.
- The engine only reads. Every HDF write in ras-commander still uses h5py.

## Troubleshooting

**`FastHdfError: Native read failed ...`** You are in `native` mode (through
`RAS_COMMANDER_FAST_HDF=native`/`required` or `engine="native"`) and the engine
refused a read. The message names the dataset and the reason (over budget,
unsupported layout, corrupt data). Use `auto` to fall back to h5py, or report
the file if you expected it to be supported. `FastHdfError` is importable from
`ras_commander.fast_hdf`.

**`FastHdfPanicError`** (a subclass of `FastHdfError`) means the extension hit
an internal error and contained it. The session survives, and in `auto` mode
the read is served by h5py. In `native` mode it is raised. Please report it
with the file and the call.

**Force h5py.** To rule the engine out of any problem:

```powershell
$env:RAS_COMMANDER_FAST_HDF = "h5py"
```

or pass `engine="h5py"` to the methods that take it. If the problem persists
in `h5py` mode, it is not an engine problem.

**See which backend served a read.** `fast_hdf.trace_reads()` is a context
manager that records the backend of each routed read (`native-typed`,
`native-generic`, `h5py`, `h5py-fallback`, ...). It is a diagnostic aid, not a
complete I/O audit:

```python
from ras_commander import HdfResultsMesh, fast_hdf
with fast_hdf.trace_reads() as records:
    HdfResultsMesh.get_mesh_max_ws("model.p01.hdf")
print({r["backend"] for r in records})
```

**The extension is installed but not used.** Check
`ras_commander_fast_hdf.API_VERSION` (must be 11) and the log for "Ignoring
incompatible ras-commander-fast-hdf extension". Also check that
`RAS_COMMANDER_FAST_HDF` is not set to `h5py`/`0`.

**A project folder cannot be renamed or deleted on Windows.** With default
settings no HDF stays open after a call returns. If you set
`RAS_COMMANDER_HDF_SESSION_CACHE=persist`, call `fast_hdf.close_sessions()`
first.

## Versions and licence

| Component | This release |
|---|---|
| Engine | `ras-commander-rust` (private repository of CLB Engineering Corporation), commit `3c2d4799ffdad01452682b82ca64305279ecc679`, engine API 10 |
| Bridge | Python package `ras_commander_fast_hdf` 0.1.0, `API_VERSION` 11, text API 1, features `catalog, hdf, mesh, results` |
| ras-commander | requires bridge API 11 |
| Wheels | Windows `cp310-abi3-win_amd64`, Linux `cp310-abi3-manylinux_2_28_x86_64`; internal distribution only |

The engine is copyright CLB Engineering Corporation. The wheel's
`.dist-info/licenses/` folder contains `THIRD-PARTY-NOTICES.md`, which lists
every Rust crate linked into the extension with its licence text, and the
licence files of the engine, ras-commander, the vendored `hdf5-reader`
(MIT), `freestiler` (ISC/MIT) and `i_float`/`i_overlay`. Keep these files with
any internal copy of the wheel.
