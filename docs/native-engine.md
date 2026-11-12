---
title: Native Rust Engines
description: RAS Commander's native Rust engines for HDF extraction, 2D flood inundation mapping and HEC-DSS reads and writes, their installation, API controls, and measured performance.
social_image: assets/ras-commander-rust-engines-dss_social.png
social_image_alt: "RAS Commander Native Rust Engines: FAST-HDF, FAST-MAP and FAST-DSS"
---
# Native Rust Engines

<p align="center"><img src="../assets/ras-commander-rust-engines-dss_logo.svg" alt="RAS Commander Native Rust Engines: FAST-HDF, FAST-MAP and FAST-DSS" width="450"></p>

RAS Commander uses native Rust engines for three different operations: reading
HEC-RAS HDF data, mapping computed 2D results to depth and water surface
elevation (WSE) rasters, and reading and writing HEC-DSS files. The HDF engine
accelerates existing `Hdf*` calls. The optional Mapping Engine runs through
`RasFim` and uses the HDF engine to read its numeric model inputs. The optional
DSS Engine (FAST-DSS) is a backend of the existing `RasDss` methods, and its
gridded importer replaces HEC-Vortex for gridded data.

| Engine | Operation | Python entry points | Installation and status |
|---|---|---|---|
| **HDF Engine** | Read stored results, geometry, text and attributes; assemble mesh geometry | `Hdf*`, `fast_hdf` | `ras-commander-fast-hdf`; installed with RAS Commander on supported wheel platforms. Default `auto` mode retains h5py fallback. |
| **Mapping Engine** | Map computed physical 2D cells to Depth/WSE rasters using horizontal or sloping interpolation | `RasFim.map_horizontal_profiles`, `RasFim.map_sloping_profiles` | External `ras-commander-fast-map` crate and wheel; the optional Python `fim` extra installs the wheel on supported platforms. Explicit native mapping; no automatic Python fallback. |
| **DSS Engine** (FAST-DSS) | Read and write DSS6 and DSS7 catalogs, time series, paired data and grids without Java; import gridded data to DSS without HEC-Vortex | `RasDss` with `RasDss.backend = "native"` or `"shadow"` | `ras-commander-fast-dss` ([install](#dss-installation)); optional. Opt-in; `java` remains the default backend. |

## Choose an engine workflow

For result extraction, keep using the existing `Hdf*` API. The
[HDF installation](#installation), [mode controls](#engine-modes),
[equivalence contract](#the-equivalence-contract) and [HDF benchmarks](#performance)
below describe the default native reader and its h5py reference path.

For inundation catalogs, use the [Mapping Engine guide](native-mapping-engine.md).
Development mapping builds add bounded shared-timestep/window caches and
optional native terrio GeoTIFF delivery. The
[retained-state measurements](development/fim-mapping-performance.md#retained-state-and-native-output-optimization)
separate complete catalog calls from repeated warm-context requests.
It covers horizontal, cell-corner sloping and depth-weighted cell-face mapping,
bbox/polygon masks, shared terrain, bounded timestep concurrency, and reusable
prepared inputs. `RasFim.map_catalog()` schedules known reach/timestep groups
with shared model state, bounded staging and optional CPU-partitioned workers;
see the [catalog API](api/fim.md#schedule-reachtimestep-catalogs).
These methods map already-computed hydraulics; they do not
run the HEC-RAS hydraulic solver. Models containing 1D river or cross-section
elements are rejected, and standalone storage-area surfaces are outside the
physical-2D mapping scope.

The [mapping comparison tables](native-mapping-engine.md#mapping-time-comparisons)
measure complete mapping calls against native RAS Mapper, separately from HDF
read timings. Matching requires the same interpolation options and effective
terrain. Raw qualification compares complete valid/nodata masks and float32
Depth/WSE values, without an added depth cutoff.

!!! note "Independent engine packages"
    HDF extraction is published as `ras-commander-fast-hdf`; mapping is
    published as `ras-commander-fast-map`. The latter preserves the compatible
    `ras2fim-batch` executable and 0.8 mapping contracts. Weighted mapping needs
    the corner-reader capability included in fast-HDF 0.2.3. Historical 0.2.2
    development wheels and the published 0.2.2 release differ in that capability;
    current installations should use 0.2.3 or newer; ras-commander 0.112.0
    requires 0.2.5, and 0.113.0 requires 0.3.0.

## DSS engine

FAST-DSS is RAS Commander's native HEC-DSS engine, written in Rust. It reads and
writes DSS6 and DSS7 files without Java: no JVM is started and HEC Monolith is
not downloaded. For DSS files it is not a separate API. It is a backend of the
existing `RasDss` methods, which keep their signatures and return types. The same
package also carries a gridded importer and grid tools that replace HEC-Vortex
for precipitation and other gridded data, with no Java, Jython or GDAL.

!!! info "Short version"
    - The engine package is `ras-commander-fast-dss` (import name
      `ras_commander_fast_dss`). It is optional; see [Installation](#dss-installation).
    - `java` (HEC Monolith through pyjnius) remains the default `RasDss` backend,
      and HEC-Vortex remains the default gridded-import route. Nothing switches
      until you choose `native` or `shadow`.
    - `native` uses FAST-DSS only. `shadow` runs both and logs every difference.
    - Native data matches the Java path. The differences are intended changes and
      corrections of Java-path defects, each listed with its evidence in
      [DSS Read and Write Backends](user-guide/dss-native-backend.md).

### Backends and how to choose one

| Backend | Reads and writes through | Returns | Use it to |
|---|---|---|---|
| `java` (default) | HEC Monolith via pyjnius; needs Java 8+ | Java result, unchanged behavior | Keep the current behavior |
| `native` | FAST-DSS; no JVM | Native result | Work without Java |
| `shadow` | Both | Reads: the native result (grids: Java's). Writes: the Java write, repeated natively on a temporary copy for comparison | Check `native` against your own files before switching |

Set `RasDss.backend`, or the environment variable `RAS_COMMANDER_DSS_BACKEND`,
which overrides the attribute:

```python
from ras_commander import RasDss

RasDss.backend = "native"            # "java" (default) | "native" | "shadow"
print(RasDss.get_backend())          # backend the next call will use
caps = RasDss.get_capabilities()     # support matrix per operation
print(caps.attrs)                    # native_installed, native_grid_qualified, native_writes_available
```

```powershell
$env:RAS_COMMANDER_DSS_BACKEND = "native"
```

Under `native`, a missing engine raises `ImportError`, and an operation the
installed engine does not support raises `DssCapabilityError`. `native` never
falls back to Java. Under `shadow` without the engine, `RasDss` uses Java and
logs one warning. The Java backend never imports the engine, so a missing or
broken wheel cannot affect it.

**Choosing.** Start with `shadow` on your own files: it returns the Java result
for writes and grids, and logs each comparison as `identical`, `expected` (an
intended difference, named) or `unexpected`. Move to `native` when the shadow log
shows no `unexpected` outcome for your workflow, or when Java is not available.
Stay on `java` where a workflow depends on a Java-path behavior listed under
[intended differences](#dss-intended-differences).

### Reads and writes

| Area | `RasDss` methods | Native coverage |
|---|---|---|
| Catalog and file version | `get_catalog`, `get_info`, `get_file_version` | DSS6 and DSS7 |
| Time series | `read_timeseries`, `read_multiple_timeseries`, `extract_boundary_timeseries` | Regular and irregular series, `start_date`/`end_date` windows, base dates and sub-minute intervals |
| Paired data | `read_paired_data` | Every curve, labels, units, types and stored precision |
| Grids | `read_grid` | HRAP, Albers (SHG) and specified grids; native once the engine advertises the `grid_srs_monolith_parity` feature (current builds do) |
| Validation | `check_pathname_exists`, `check_data_availability`, `check_pathname`, `is_pathname_available` | Through the catalog and time-series reads above |
| Writes | `write_timeseries`, `write_timeseries_from_dataframe`, `write_paired_data`, `write_grid_timeseries`, `copy_grid_with_zero_tail`, `write_precip_grid_arrays` | DSS6 and DSS7, regular and irregular series, paired data and grids; needs an engine build with writers (`attrs["native_writes_available"]`) |

Native writes keep the existing file's DSS version (new files are DSS7 unless
`dss_version=6`). Java reads native-written records equal to Java-written ones.

### Gridded import and tools (HEC-Vortex replacement) {#gridded-import-and-tools}

`ras_commander_fast_dss.gridded` imports gridded data to DSS grids in the calling
process; in RAS Commander, `RasDssGrid` wraps it (see
[Engine-only operations](user-guide/dss-native-backend.md#engine-only-operations)).
It reads GRIB2, NCEP Stage IV GRIB1 (2002 to July 2020), NetCDF (classic and
NetCDF-4), HDF5, GeoTIFF (with an optional `.aux.xml` that sets only nodata) and
ASCII grids, PRISM BIL files and packages, SNODAS daily files, local Zarr v2
stores, and NumPy arrays; reprojects to SHG, HRAP or a WKT
target with `near`, `bilinear` or `average` resampling; and writes DSS6 or DSS7
through the same writer as `RasDss`. Each run is planned before a cell is read:
every pathname, window and unit is decided first, so a refusal leaves the output
file untouched. It follows HEC-Vortex's importer rules for products, C parts,
units and time windows. From 0.1.2 an import uses every core by default
(`threads=None`); the file it writes is byte-identical to `threads=1`.

SNODAS times come from the checked NOHRSC header by default
(`snodas_times="header"`): a daily total is `PER-CUM` over the 24 hours ending at
06:00 UTC of the file's date. `snodas_times="vortex"` gives HEC-Vortex 1.1.0's
timing and types for compatibility (Vortex puts each daily total one day later and
types it `PER-AVER`). Products without a qualified interpretation (snowpack average
temperature, historical melt and sublimation variants) are refused unless one of
those options is named. Clip SNODAS to the model envelope: the whole grid exceeds
the per-record cell limit.

| Task | Function | HEC-Vortex tool it replaces |
|---|---|---|
| Import files or arrays to DSS grids | `import_gridded`, `import_arrays`, `import_zarr`, `list_variables` | Importer |
| Grid to point or basin time series; zone masks and statistics | `grid_to_point`, `zonal_statistics`, `zone_masks` | Grid-to-point converter |
| Shift times; resample to another time step | `shift_times`, `resample_times` | Time shifter, time-step resampler |
| Arithmetic with a constant or another raster; clean, rescale and clip grids | `calculate`, `calculate_raster`, `sanitize`, `normalize`, `clip` | Calculator, sanitizer, normalizer, clipper |
| Read a window, the nearest grid, or min/max over a grid series | `read_window`, `read_nearest`, `read_min_max`, `series_info` | (inspection) |

RAS Commander routes that use the importer:

- **MRMS QPE.** `PrecipMrms.to_dss(..., backend="native")` (or `"shadow"`, or the
  `RAS_COMMANDER_MRMS_BACKEND` environment variable). The default stays HEC-Vortex.
  See [MRMS hourly QPE](user-guide/gridded-precipitation.md#mrms-hourly-qpe).
- **Atlas 14 design storms.** Notebook 731 sets `DSS_EXPORT_ROUTE = "native"` to
  project its Float32 interval NetCDF to SHG DSS without Vortex.
- **WPC QPF.** The importer reads WPC's published GRIB2 directly; see
  [WPC QPF](user-guide/gridded-precipitation.md#wpc-qpf-to-dss-with-fast-dss).

```python
from ras_commander import RasDssGrid

result = RasDssGrid.import_gridded(
    grib_files, "forcing.dss",
    product="total_precipitation",              # or variable="..." from list_variables()
    envelope=(1494000, 2120000, 1564000, 2188000),  # SHG metres: west, south, east, north
    target_crs="SHG", cell_size=2000, method="bilinear",
    parts={"A": "SHG", "B": "MY_BASIN", "F": "WPC-QPF"},
)
print(len(result.records), result.records[0]["pathname"])
```

**Agreement with HEC-Vortex.** The engine was qualified against HEC-Vortex 0.13.3
and 1.1.0 on 115 GRIB2, GeoTIFF and ASCII grid cases (including MRMS, Stage IV and
AORC) and 252 NetCDF cases. In DSS7, every case that both sides wrote has identical
cell bits, masks and record metadata, with no tolerance, apart from the listed
differences below; the remaining cases are the refusals in that list. The warp
kernels matched both Vortex versions on MRMS, HRRR, Stage IV and WPC samples. These
are measurements on those inputs, not a proof over all inputs. In a run of notebook
731 on the public NewOrleansMetro example with NOAA's Volume 9 100-year 24-hour
grid, the native and HEC-Vortex 0.13.3 routes wrote the same 144 records, equal
cell for cell; the stored null value was the only difference (label W2 below).

### Intended differences {#dss-intended-differences}

**`RasDss` reads and writes.** Under `native`, missing values are `NaN` instead of
HEC's numeric marker, `start_date` and `end_date` are honored, errors are typed,
and several datasets that the Java path misreads are read correctly. The native
writer refuses some input that the Java path truncates or stores as an unreadable
record, and DSS7 SHG grids store a null value of -FLT_MAX where Monolith stores
0.0 (label W2; cells are equal). Each difference, with its evidence, is listed in
[DSS Read and Write Backends](user-guide/dss-native-backend.md#differences-from-the-java-backend)
(reads) and in its [Writes section](user-guide/dss-native-backend.md#intended-differences)
(writes).

**Gridded import.** HEC-Vortex behaviors that move or relabel data are refused by
default, each with an opt-in argument that reproduces Vortex where one exists:

| HEC-Vortex behavior | Native default | Opt-in for Vortex's result |
|---|---|---|
| Rounds an origin that is not on whole cells, moving the grid | Refused, naming the corner | `align="vortex"`, or state an `envelope` and `cell_size` |
| Stores precipitation at an instant as `INST-VAL` with a D part only (HEC-HMS has read this as no rain) | Refused | `data_type="INST-VAL"` |
| Gives a file name's window to a record that states another (e.g. a 24-hour file renamed `01H`) | Refused, naming both windows | `window_rule="vortex"` |
| Writes one pathname twice in a run, keeping the last | Refused | `duplicates="last"` |
| Stores PER-CUM DSS6 grids as PRECIP_2_BYTE, rounding cells to 0.01 (Vortex 0.13.3) | ZLIB, keeping each cell's bits | none |

### Notebook qualification

Every example notebook that reads or writes DSS was run on the `java`, `native`
and `shadow` backends, and its outputs, DSS files and HEC-RAS results were compared.
No notebook behaves differently on `native`; every shadow comparison was
`identical` or `expected`; every HEC-RAS physical-cell result was bit-identical
across backends. Results per notebook are in the
[DSS native backend notebook qualification](development/dss-native-notebook-qualification.md).

Notebooks that teach the native engine directly:

- [321: Native DSS Records, Backends, and Copy-Out Recovery](notebooks/321_native_dss_records_and_recovery.md):
  DSS6/DSS7 round trips and merges, `sync=` policies, a backend comparison, paired data,
  locations and `RasDss.repair`, on public HEC data.
- [732: Native Gridded Import and Grid Tools on Real Precipitation](notebooks/732_native_gridded_import_and_grid_tools.md):
  `RasDssGrid` on AORC Zarr/NetCDF, IMERG HDF5, Stage IV GRIB1/GRIB2 and MRMS GRIB2, every grid tool
  and the zonal statistics.
- [731](notebooks/731_atlas14_shared_temporal_existing_model.md) (Atlas 14 export through
  `RasDssGrid` or HEC-Vortex), [916](notebooks/916_hrrr_precipitation_forecast.md) (native HRRR and
  Stage IV import beside the qpkit route) and [917](notebooks/917_mrms_precipitation_qpe.md) (MRMS
  accumulation windows, overlaps, shapefile clipping and threads).

### HEC-RAS acceptance

`tests/test_rasdss_hecras_acceptance.py` runs public example plans through
`RasCmdr.compute_plan` on grids and boundary series written by each backend:

- boundary time series rewritten by either backend, as DSS6 or DSS7, gave results
  identical to the original example file;
- period grids (`PER-CUM`) are applied evenly over the period ending at part E;
  moving the period one hour moved the results one hour;
- zero-length grids (D = E), which the Java path can write and the native writer
  refuses, gave the same HEC-RAS results as one-hour periods in the tested runs.

Details are under
[HEC-RAS acceptance of written files](user-guide/dss-native-backend.md#hec-ras-acceptance-of-written-files).
HEC-RAS is run only through RAS Commander's APIs.

### Installation {#dss-installation}

!!! note "Published on PyPI"
    The current release of `ras-commander-fast-dss` is **0.1.2**:
    [pypi.org/project/ras-commander-fast-dss](https://pypi.org/project/ras-commander-fast-dss/)
    ([changelog](https://github.com/gpt-cmdr/ras-commander-fast-dss/blob/main/CHANGELOG.md)).
    The source is the public repository
    [gpt-cmdr/ras-commander-fast-dss](https://github.com/gpt-cmdr/ras-commander-fast-dss)
    (licence MIT AND BSD-3-Clause).

```bash
pip install ras-commander-fast-dss
```

or install it with the DSS extras, which request
`ras-commander-fast-dss>=0.1.2,<0.2`:

```bash
pip install "ras-commander[dss]"          # pyjnius (java backend) + FAST-DSS
pip install "ras-commander[dss-native]"   # pydsstools + FAST-DSS
```

Wheels (abi3, CPython 3.10 and later) are published for Windows x64 and for
Linux x86_64 and aarch64 (manylinux and musllinux). The extras request the
engine only on those platforms. There are no macOS wheels: on macOS, and on any
other platform, `pip install ras-commander-fast-dss` builds it from the source
distribution, which needs a Rust toolchain. The extras do not request it there,
so `pip install "ras-commander[dss]"` never starts a Rust build.

Then select the backend as shown above. `ras-commander` itself does not require
the package; `import ras_commander` and the `java` backend work without it. Check
the installed engine with:

```python
import importlib.metadata
import ras_commander_fast_dss as fast_dss

print(importlib.metadata.version("ras-commander-fast-dss"))   # the package has no __version__
print(sorted(fast_dss.FEATURES))   # e.g. grid_srs_monolith_parity, gridded_import
```

Test for a capability with its `FEATURES` flag, not with a version number.

Existing [DSS operations](user-guide/dss-operations.md) work unchanged on the
default `java` backend.

### What 0.1.2 changes for RAS Commander {#dss-0-1-2}

- **`sync=` names three flush policies.** See [below](#dss-repair). `True` now
  means one flush per write call; code that wants the 0.1.1 per-step behaviour
  passes `sync="step"`.
- **A `ras_commander_fast_dss.DssFile` session holds one native handle** after its
  first write, until it is closed. Close the session before renaming, replacing or
  deleting its file; on Windows, `os.replace` onto a file that a session holds
  fails. RasDss opens its own sessions for reading only, and closes them before it
  publishes a file. See [Sessions and file replacement](#dss-sessions).
- **New gridded sources:** NCEP Stage IV GRIB1, PRISM BIL and its zipped and 2025
  packages, SNODAS (header timing by default), and a loose GeoTIFF with an
  `.aux.xml` that sets only nodata. `RasDssGrid.get_features()` reports their
  flags (`gridded_grib1_stage4`, `gridded_prism_bil`, `gridded_snodas`).
- **Gridded import uses every core by default**, with output byte-identical to
  `threads=1`. Kilometre-to-metre axis conversion now matches HEC-Vortex exactly.
- **DSS6.** Regular time-series merge and extend into existing records is now
  qualified against HEC's libraries. Writing a DSS6 *irregular pattern* (an `IR-`
  E part with a `TS-` D part) needs the engine's explicit opt-in
  `allow_unconfirmed_dss6_irregular_pattern=True`, because no HEC reader has
  confirmed such records. No RasDss writer passes that opt-in, so `RasDss` refuses
  those writes with `DssUnsupportedRecordError` and leaves no new file behind.
  Ordinary DSS6 irregular series are unaffected. Pathnames that are not printable
  ASCII are refused for writing (as in 0.1.1; now documented).

### Interrupted writes, `sync=` and `repair` {#dss-repair}

The scope is the engine's, and RAS Commander does not widen it:

- **Interrupted writes.** The engine's guarantee covers **process death**: the
  writing process killed at any point. The next native write reconciles the
  interrupted one when the file was consistent before it. It is not a power-loss
  or operating-system-crash guarantee, and a normal write never repairs damage it
  did not cause.
- **`sync=` (flush policy).** Every public writer of the engine accepts `sync=`,
  and the RasDss writers (`write_timeseries`, `write_timeseries_from_dataframe`,
  `write_paired_data`, `write_grid_timeseries`, `copy_grid_with_zero_tail`,
  `write_precip_grid_arrays`, `write_profile`, `write_location`), `RasDss.repair`
  and the `RasDssGrid` methods that write pass it through unchanged. In
  ras-commander-fast-dss 0.1.2:

    | `sync=` | Flushing |
    |---|---|
    | `"end"` (engine default; `True` means the same) | One `fsync` at the end of each write call. A call that stores several records (gridded import, grid tools, grid-to-point) flushes once, after its last record |
    | `"step"` | An `fsync` at every flush point of the transaction (the 0.1.1 meaning of `True`) |
    | `"none"` (`False` means the same) | No flush; the operating system writes the data later |

    The three policies make the same writes in the same order, so the
    process-death behaviour is the same in each. No policy is a power-loss
    guarantee: after a power loss or an operating-system crash, writes that were
    not flushed may be missing or torn. Use `"none"` only for scratch or
    regenerable files:

    ```python
    from ras_commander import RasDss

    RasDss.backend = "native"
    RasDss.write_timeseries("scratch.dss", "/A/B/FLOW//1HOUR/RUN/", times, values,
                            units="CFS", data_type="INST-VAL", sync="none")
    ```

    Left unstated (`sync=None`), RasDss sends nothing and the installed engine's
    own default applies; that default belongs to the engine, so state a value when
    a workflow depends on one. The `java` backend does not use `sync` (HEC's
    library manages its own flushing), and `shadow` applies it to the native repeat
    only. `RasDss.get_capabilities().attrs` reports
    `native_write_sync_available` (`FEATURES` flag `write_sync_policy`) and
    `native_write_sync_modes_available` (`write_sync_modes`); stating `sync` under
    `native` without the first raises `DssCapabilityError`. An unknown value is
    the engine's `ValueError`, raised before anything is written.

- **`repair(src, dest)`** is the recovery path for a damaged DSS7 file. It opens
  `src` read-only, copies the readable records that its documented discovery
  procedure reaches into a new file `dest`, verifies every copied record against
  its source, and reports what it did not copy. Bytes that no pointer reaches are
  out of scope. **A partial recovery is still published**, so always check
  `complete` and `not_copied`. A complete copy is not an integrity certificate
  for `src`, and copying a healthy file shows the mechanics, not salvage of a
  damaged one. `dest` must not exist. DSS6 files are not supported. In RAS
  Commander, `RasDss.repair` calls it on every backend (there is no Java
  equivalent):

    ```python
    from ras_commander import RasDss

    result = RasDss.repair("damaged.dss", "recovered.dss")
    if not result["complete"]:
        for pathname, reason in result["not_copied"]:
            print(pathname, reason)
    ```

    `ras_commander_fast_dss.repair(src, dest)` returns the same `dict`. The engine
    builds `dest` under a temporary name that no reader sees until it is
    published; `sync="end"` and `"step"` flush it once before it is verified and
    published, and `"none"` does not flush it.
    `RasDss.get_capabilities().attrs["native_repair_available"]` reports
    whether the installed engine has it (`FEATURES` flag `repair_copy_out`).

The engine's README section "Interrupted writes, `sync=` and `repair`" and its
DSS7 format notes give the full crash model and known limitations.

### Sessions and file replacement {#dss-sessions}

Code that uses the engine directly can keep a file open across calls with
`ras_commander_fast_dss.open(path)`, which returns a `DssFile`. From 0.1.2, the
first write through a `DssFile` opens one read+write handle, which the session
keeps until `close()` or the end of its `with` block. Every write still takes and
releases HEC's lock, so other programs see the file unlocked between writes.

**Coordination rule: close the `DssFile` before renaming, replacing or deleting
its file.** On Windows, `os.replace` onto a held file fails. RAS Commander's own
publish steps (`copy_grid_with_zero_tail(overwrite=True)`,
`write_precip_grid_arrays(overwrite=True)`) write to a temporary file, close every
handle they opened and only then replace the destination. If a caller's session
still holds the destination, the replace raises `PermissionError` naming this
rule, and the destination is left unchanged.

```python
import ras_commander_fast_dss as fast_dss

with fast_dss.open("forcing.dss") as session:
    session.write_timeseries(pathname, values, times=times, units="MM",
                             data_type="PER-CUM", sync="none")
# The session is closed here, so RasDss may now replace forcing.dss.
```

### Performance {#dss-performance}

**Which engine your calls use.** `RasDss` calls run on the default `java` backend
(HEC Monolith through pyjnius) unless you select `native` or `shadow`, and
`PrecipMrms.to_dss` runs HEC-Vortex unless you pass `backend="native"`.
`RasDssGrid`, `repair` and the profile and location methods always run on the
native engine. The statements below describe the native engine,
`ras-commander-fast-dss` 0.1.2. Under `shadow` each call runs both paths, so it
is for qualification rather than speed.

Performance of the native engine is qualified internally against HEC's DSS C
library, pydsstools, hecdss, HEC Monolith and HEC-Vortex on a private corpus of
production model files; those files and the detailed results are not published.
The statements below summarize those evaluations. To measure on your own machine,
run `benchmarks/bench_public.py` from the
[engine repository](https://github.com/gpt-cmdr/ras-commander-fast-dss), which
generates its own data and checks every result. Absolute times depend on storage,
antivirus scanning and file layout.

- **Reads and catalogs** are on par with HEC's C library and pydsstools. On very
  large DSS7 catalogs pydsstools is somewhat faster, because FAST-DSS validates
  and normalizes every pathname it returns.
- **Compared with the Java path (HEC Monolith, RAS Commander's default `java`
  backend) and hecdss,** whole-dataset reads are many times faster on the
  `native` backend, because FAST-DSS decodes records directly into NumPy arrays
  without a per-record Python or Java crossing. The `native` backend also starts
  no JVM.
- **Gridded import** (`RasDssGrid.import_gridded`,
  `PrecipMrms.to_dss(backend="native")`) is on par with HEC-Vortex for
  continental grids and faster for smaller imports, with no JVM start-up. The
  grid tools and grid-to-point are slower than Vortex, because each output record
  is written separately.
- **Writes are durable by default and therefore slower.** By default the engine
  flushes to disk at the end of every write call (`sync="end"`), so that a killed
  process leaves a file HEC can read. The other tools, including the `java`
  backend, leave flushing to the operating system. For bulk loads of regenerable
  output, write inside a `DssFile` session with `sync="none"` (or pass
  `sync="none"` to the RasDss writers). Bulk series writes are then on par with
  the C-based tools. Writing many small records or paired-data records one call
  at a time remains noticeably slower than the C libraries, because of per-call
  overhead; reducing it is planned in the engine.

### Attributions and acknowledgments {#dss-attributions}

FAST-DSS is an independent, pure-Rust implementation of the HEC-DSS file format,
versions 6 and 7. It was written from HEC's published, MIT-licensed `hec-dss` C
and Fortran source; each format rule in the engine cites the HEC source file and
routine it follows. No HEC code is copied into the engine, and no HEC library is
linked or bundled.

HEC's software was the reference throughout development: the HEC-DSS C library
(through HEC's `hecdss` Python package) for DSS7, HEC Monolith for DSS6, paired
data, grids and Java-path parity, HEC-Vortex 1.1.0 and 0.13.3 (with their bundled
PROJ and GDAL) for the gridded importer, and public HEC-DSSVue, HEC-RAS and
HEC-HMS example data for the test fixtures. HEC-RAS runs through RAS Commander
confirmed that HEC-RAS reads the files the engine writes.

As a final independent check, the engine's output was compared with
[pydsstools](https://github.com/gyanz/pydsstools) 3.1.0 (MIT), a widely used
third-party Python library for HEC-DSS. The comparison covered 4,727 records
(21.6 million values) in 122 DSS6 and DSS7 files: 4,080 records were identical
bit for bit, 182 more were identical under a documented rule, and 183 of the 196
records that differed differed only in metadata. pydsstools could not read 209
of the records. HEC Monolith was used to break ties.

Thanks to the HEC developers for publishing `hec-dss`, HEC-Vortex and their
example data as open source, and to the pydsstools maintainers. The full
statement is in the engine README's
[Attributions and acknowledgments](https://github.com/gpt-cmdr/ras-commander-fast-dss#attributions-and-acknowledgments).
FAST-DSS is an independent open-source project, not affiliated with, endorsed by
or supported by HEC or USACE.

<a id="native-rust-hdf-engine"></a>

## HDF engine

<p align="center"><img src="../assets/ras-commander-fast-hdf_logo.svg" alt="RAS Commander Fast-HDF: Native Rust HDF Engine" width="450"></p>

RAS Commander reads HEC-RAS HDF files (plan results, geometry, terrain and
land-cover sidecars) through its native HDF engine, written in Rust. h5py
remains the reference implementation and serves every read the engine does
not. This page explains what the engine is, how it is installed and selected,
what "identical results" means and how that was proven, how fast it is, and
what it does not do. The remaining sections retain the detailed HDF guide and
its existing section links.

!!! info "Short version"
    - The native engine is ras-commander's **default HDF engine**. Its
      open-source (MIT) package, `ras-commander-fast-hdf`, is installed
      automatically by `pip install ras-commander` (0.107.1 and later; 0.108.0 and
      later install engine 0.2.x) on
      Windows x64, Linux x64 and macOS arm64. No extra is needed.
    - The default mode, `auto`, reads natively where the native path is
      qualified and uses h5py for any read the engine refuses. **Public
      results are identical to h5py**: same values, dtypes, columns, index,
      CRS, attributes and exceptions.
    - Calls that take noticeable time on large models are much faster than
      before the engine. On the largest test models, against ras-commander
      0.106.1: cell polygons 42×, per-cell and per-face summaries 10–16×,
      mesh time series 7–8×, and the fluvial-pluvial boundary 690× on an
      18,066-cell mesh (ras-commander 0.112.0, October 2026). Small calls stay
      within a few milliseconds (see [Performance](#performance)).
    - Set `RAS_COMMANDER_FAST_HDF=h5py` to switch the engine off. On
      platforms without a wheel the engine is not installed, and every read
      uses h5py automatically.

## What it is and why

For native 2D inundation mapping, the optional FIM engine uses this HDF reader
to stage model inputs, then reconstructs horizontal or sloping surfaces in Rust.
Depth-weighted sloping additionally requires the stored-corner reader capability
added after published fast-HDF 0.2.2. See the
[FIM API](api/fim.md#depth-weighted-sloping-faces-engine-08) and
[five-model RASMapper comparison](development/fim-mapping-performance.md#depth-weighted-sloping-faces-engine-08)
for setup, retained Windows/Linux wheels, exact mask/value qualification, and
mapping times. Those mapping measurements are separate from the HDF-read
benchmarks on this page.

ras-commander's `Hdf*` classes originally read HDF5 only through h5py and the
HDF5 C library. The native engine replaces the *value reads* underneath those
classes, not the classes themselves:

- **Same public API.** No method was renamed or removed, and no positional
  parameter or default changed. Your code does not change.
- **One reader for numbers, text and attributes.** Numeric datasets, compound
  tables, fixed-length text (compute messages, timestamps, profile names) and
  attributes are decoded by the engine, then handed to the same pandas,
  xarray and GeoPandas construction code as before.
- **Mesh geometry in Rust.** 2D cell polygons are assembled natively, with the
  same ring order, vertex order and WKB as the Python polygonizer. Face lines
  are packed natively too, and every mesh's lines become Shapely geometry in
  one vectorized call (see [Geometry: convenient or fast](#geometry-convenient-or-fast)).
- **Hardened against damaged files.** The engine is written in safe Rust
  (`#![forbid(unsafe_code)]`), budgets every read before allocating, and turns
  a panic into a Python exception instead of a process crash. A truncated or
  corrupted HDF gives an ordinary exception; in `auto` mode it gives exactly
  the h5py outcome.

Why: faster bulk and sparse reads of large result datasets (especially
compressed 2D time series), fewer HDF5 C-library failure modes in long batch
jobs, and the same code path on Windows and Linux. The largest measured gains
are in the steps that dominate h5py-based extraction from large 2D models:
building cell polygons and reading time series from compressed meshes. That
makes it practical to extract results from many large models in one study,
for flood science, research and new kinds of analysis, with results that are
identical to the h5py reference.

The engine is not a general HDF5 library. It reads what HEC-RAS writes and
refuses anything it cannot reproduce exactly (see
[Limitations and refusals](#known-limitations-and-refusals)).

<a id="installing-the-extension"></a>

## Installation

The engine and its Python extension are open source (MIT) in their own
repository,
[gpt-cmdr/ras-commander-fast-hdf](https://github.com/gpt-cmdr/ras-commander-fast-hdf),
and published on PyPI as `ras-commander-fast-hdf` (and, from 0.2.0, on
crates.io as a Rust crate of the same name). ras-commander 0.107.1 and later
list it as a core dependency (0.108.0 and later: `>=0.2,<0.3`; 0.109.0 and later: `>=0.2.3,<0.3`; 0.112.0 and later: `>=0.2.5,<0.3`; 0.113.0 and later: `>=0.3.0,<0.4`), limited by an environment marker to the
platforms that have wheels, so the normal install is enough:

```bash
pip install ras-commander
```

Wheels are published for CPython 3.10 and later (`abi3`):

| Platform | Wheel tag | Installed with ras-commander | Status |
|---|---|---|---|
| Windows x64 | `cp310-abi3-win_amd64` | Yes | Qualified |
| Linux x64 (glibc 2.28+, e.g. Rocky/RHEL 9, Ubuntu 20.04+) | `cp310-abi3-manylinux_2_28_x86_64` | Yes | Qualified |
| macOS arm64 (Apple silicon) | `cp310-abi3-macosx_*_arm64` | Yes | Builds and passes its tests, but not yet qualified on the HEC-RAS corpus |

Installing a wheel needs no Rust toolchain and no HDF5 C library.

**Other platforms.** On any other platform or interpreter (for example Linux
aarch64, macOS x86_64, Windows ARM64 or PyPy), pip does not install the
engine, and ras-commander uses h5py for every read with the same public
results. To use the engine there, build it from source, which needs Rust:
`pip install "ras-commander[fast]"` requests the engine without the platform
marker, so pip builds the source distribution. See
[Building](https://github.com/gpt-cmdr/ras-commander-fast-hdf/blob/main/docs/building.md)
in the extension's repository.

**Systems the marker cannot exclude.** The marker cannot test the C library
or the interpreter build. On Linux x64 with glibc older than 2.28 or with musl
(for example Alpine), and on free-threaded CPython builds, the marker matches
but no wheel does, so pip tries to build
the source distribution and fails without Rust. Either install a Rust
toolchain, or install ras-commander without its dependency list and add the
others yourself (`pip install h5py numpy pandas` followed by
`pip install --no-deps ras-commander`); ras-commander then uses h5py.

**The `fast` and `fast-hdf` extras** are no longer needed. They remain so that
existing install commands keep working; on the three wheel platforms they add
nothing. With ras-commander 0.107.0, which does not install the engine
automatically, use `pip install "ras-commander[fast]"` or
`pip install ras-commander-fast-hdf`.

### Verify the installation

```python
import ras_commander_fast_hdf as native
print(native.API_VERSION)      # 12 (legacy mesh metadata compatibility build)
print(native.ENGINE_COMMIT)    # b2ab8280617383519d38aad9bd47b88b654009b1
print(native.ENGINE_FEATURES)  # ('catalog', 'hdf', 'mesh', 'results')

from ras_commander import fast_hdf
print(fast_hdf.available())    # True
```

ras-commander only uses an extension whose `API_VERSION` is exactly the one it
was built against (12 for the legacy mesh metadata compatibility build). An older or newer wheel is ignored
with one logged warning, and every read uses h5py; in `native` mode it raises
`FastHdfError` instead. `fast_hdf.available()` returns `False` in both cases.
If the extension is not installed at all, `available()` returns `False` and
every read uses h5py without a warning.

The legacy metadata compatibility build reads 2D area names from
`Geometry/2D Flow Areas/Names` when `Attributes` is absent. It qualifies the
physical-cell count from contiguous cell-face ranges: polygon cells must
precede the one-face boundary ghosts, with one range per stored cell center.
Ambiguous layouts raise instead of using a stale `Cell Maximum Index` or a
result width to infer the boundary. Both the Python fallback and native engine
apply this rule; a present `Attributes` table continues to take precedence.

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
when `auto` used the Python reference). Native kernel timings and counts
(`attrs["fluvial_native"]`) are attached only with `diagnostics=True`.

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
| `HdfInfiltration` | 14 | 148 | 0 |
| `HdfLandCover` | 15 | 466 | 0 |
| `HdfMesh` | 15 | 168 | 1 |
| `HdfPipe` | 22 | 191 | 0 |
| `HdfPlan` | 12 | 657 | 0 |
| `HdfProject` | 7 | 175 | 0 |
| `HdfPump` | 5 | 33 | 0 |
| `HdfResultsAnalysis` | 2 | 14 | 0 |
| `HdfResultsBreach` | 4 | 92 | 0 |
| `HdfResultsMesh` | 24 | 277 | 0 |
| `HdfResultsPlan` | 15 | 312 | 0 |
| `HdfResultsProducts` | 1 | 13 | 0 |
| `HdfResultsQuery` | 12 | 192 | 0 |
| `HdfResultsSediment` | 6 | 28 | 0 |
| `HdfResultsXsec` | 4 | 24 | 0 |
| `HdfStorageArea` | 6 | 129 | 0 |
| `HdfStruc` | 6 | 214 | 0 |
| `HdfStruc1D` | 1 | 10 | 0 |
| `HdfUtils` | 4 | 248 | 0 |
| `HdfXsec` | 10 | 181 | 0 |
| **Total** | **211** | **4033** | **1** |

Public methods running on h5py in auto mode (no corpus fixture made a native read that could prove them:
their data is absent from every fixture, or they read only metadata):


`HdfMesh.get_mesh_geometry_inventory`, `HdfResultsSediment.is_sediment_plan` and
`HdfResultsSediment.get_sediment_mesh_areas` read only HDF metadata (group membership)
through h5py and have no native read path, so they are not marked.
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
  times, 460 MB), the FEMA eBFE Austin-Oyster HEC-RAS 5.0.7 plan
  `AustinOyster.p03` (1,872,746 cells, 3.2 GB), Homewood (68,743 cells) and the
  Glaise Creek eBFE model (Source: FEMA estimated Base Flood Elevation (eBFE)
  program);
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

Measured on October 30, 2026 on a Windows workstation (CLB01, Intel Core
i7-11700K, 8 logical CPUs) after a quiet-machine check: **ras-commander
0.106.1**, the last release before the native engine and the vectorization
work, installed without the engine (pure h5py), against **ras-commander
0.112.0 with ras-commander-fast-hdf 0.2.5**, measured as the release
candidates the release gate qualified (ras-commander `29a2085ef`, engine wheel
built from `4013987`); 0.112.0 also contains #750, which changes none of the
measured methods. All columns ran on the same Python 3.13.9, numpy 2.3.3,
pandas 2.3.2, h5py 3.14.0 and Shapely 2.1.2, measuring 20 public methods on 9
HEC-RAS result files. Each measurement used a fresh process, with three timed
processes per column. Every result was hashed: in 0.112.0 it was identical in
`h5py`, `auto` and `native` mode, and identical to ras-commander-fast-hdf
0.2.4. The full tables, charts, the load during the run and the method are on
the extension's [Performance](https://rascommander.info/fasthdf/performance/)
page.

**Calls that take 100 ms or more with 0.106.1 on the largest test model**,
repeat calls on that model, ranked by the 0.106.1 time:

| Method | Largest test model | 0.106.1 | 0.112.0 `auto` | Speed-up vs 0.106.1 | Native vs h5py (0.112.0) |
|---|---|---:|---:|---:|---:|
| `HdfFluvialPluvial.calculate_fluvial_pluvial_boundary` | BaldEagleDamBrk.p03 (18,066 cells) | 164,253 ms | 238 ms | **690×** | 7.4× |
| `HdfMesh.get_mesh_cell_polygons` | Glaise Creek (582,931 cells) | 37,853 ms | 906 ms | **41.8×** | 25.9× |
| `HdfResultsMesh.get_mesh_max_face_v` | Glaise Creek (1,393,564 faces) | 16,270 ms | 1,242 ms | **13.1×** | 1.1× |
| `HdfMesh.get_mesh_cell_faces` | JUL2020_D100RAS.p04 (705,332 faces) | 7,713 ms | 403 ms | **19.2×** | 1.1× |
| `HdfResultsMesh.get_mesh_max_ws` | Glaise Creek (582,934 cells) | 4,509 ms | 440 ms | **10.3×** | 1.1× |
| `HdfMesh.get_mesh_cell_points` | Glaise Creek (586,935 cells) | 4,086 ms | 252 ms | **16.2×** | 1.1× |
| `HdfResultsMesh.get_mesh_max_depth` | JUL2020_D100RAS.p04 (340,248 cells) | 3,258 ms | 262 ms | **12.5×** | 2.5× |
| `HdfResultsMesh.get_mesh_summary` (maximum face velocity) | BaldEagleDamBrk.p07 (177,301 faces) | 2,209 ms | 177 ms | **12.5×** | 1.2× |
| `HdfResultsMesh.get_mesh_timeseries` (face velocity) | BaldEagleDamBrk.p07 (865 × 177,301) | 1,521 ms | 187 ms | **8.1×** | 7.7× |
| `HdfResultsMesh.get_mesh_timeseries` (water surface) | BaldEagleDamBrk.p07 (865 × 87,039) | 1,464 ms | 210 ms | **7.0×** | 6.5× |
| `HdfResultsMesh.get_mesh_cells_timeseries` (one cell) | BaldEagleDamBrk.p07 (87,039 cells) | 1,348 ms | 188 ms | **7.2×** | 7.3× |

Glaise Creek is the Glaise Creek–White River model (1101001306.p01) from
FEMA's estimated Base Flood Elevation (eBFE) program; BaldEagleDamBrk.p03 is
the single 2D area plan of HEC's BaldEagleCrkMulti2D example. On
BaldEagleDamBrk.p07 (87,039 cells) the fluvial-pluvial boundary did not finish
with 0.106.1 within 30 minutes; 0.112.0 takes 927 ms in `auto` mode.

- **Speed-up vs 0.106.1** is what you notice after upgrading. **Native vs
  h5py** (0.112.0 in h5py mode ÷ `auto` mode) is the Rust engine's share. Where
  it is about 1.0× but the speed-up is large, the gain is from vectorizing
  ras-commander itself (face lines and points built in one Shapely call,
  geometry joined by position, summary times converted once per distinct
  value), so h5py mode gets it too. The remaining time in those calls is
  mostly building the Shapely geometry, which is the same in both modes.
- **Engine 0.2.5 against 0.2.4:** the same ras-commander with the published
  ras-commander-fast-hdf 0.2.4 in native mode differs from 0.2.5 only in the
  engine. Over the 58 cases, the geometric mean of the 0.2.5 ÷ 0.2.4
  repeat-call ratios is 0.98. Two cases that looked slower were timed again
  in eight alternating rounds and are within noise.
- **Small calls** (under 100 ms even on the largest models: structures,
  boundary lines, run statistics, timestamps and the like) stay within a few
  milliseconds of 0.106.1 either way; opening the file and building the
  result dominate them. Their absolute times are on the
  [Performance](https://rascommander.info/fasthdf/performance/#small-calls-under-100-ms)
  page.
- Timings were taken with the files in the operating system's cache.

### Geometry: convenient or fast

Per-cell and per-face result readers (`get_mesh_max_ws`, `get_mesh_max_face_v`,
`get_mesh_max_depth` and the others listed in [HDF API](api/hdf.md)) have two
outputs:

| Output | Call | Returns | Use it when |
|---|---|---|---|
| **Convenient** (default) | `include_geometry=True` | GeoDataFrame: every row carries its cell-center point or face line, with the CRS | you want a layer to map or export in one call |
| **Fast** | `include_geometry=False` | pandas DataFrame with the same rows, order, values, dtypes and `attrs`, keyed by `mesh_name` plus `cell_id` or `face_id`; no GeoPandas or Shapely needed | you only need the numbers, or you read several results of one model |

For several results of one model, read the geometry **once** and join each
fast table to it. `HdfMesh.get_mesh_cell_faces` (face lines) and
`HdfMesh.get_mesh_cell_points` (cell centers; pass `include_ghost_cells=False`
to match the default ghost-free cell results) return exactly the geometry the
convenient output attaches:

```python
from ras_commander import HdfMesh, HdfResultsMesh

faces = HdfMesh.get_mesh_cell_faces(plan_hdf)                      # once
vmax = HdfResultsMesh.get_mesh_max_face_v(plan_hdf, include_geometry=False)
vmin = HdfResultsMesh.get_mesh_min_face_v(plan_hdf, include_geometry=False)
face_results = (faces.merge(vmax, on=["mesh_name", "face_id"])
                     .merge(vmin, on=["mesh_name", "face_id"]))    # GeoDataFrame

cells = HdfMesh.get_mesh_cell_points(plan_hdf, include_ghost_cells=False)
wse = HdfResultsMesh.get_mesh_max_ws(plan_hdf, include_geometry=False)
cell_results = cells.merge(wse, on=["mesh_name", "cell_id"])
```

**How the convenient output is built.** Geometry is no longer built one
Shapely object per row. Each mesh's face lines are packed into coordinate and
offset buffers and turned into lines by one `shapely.from_ragged_array` call;
cell-center points use one `shapely.points` call. In `auto` and `native`
mode the native engine builds the face-line buffers
(`HdfSession.read_mesh_face_lines`, ras-commander-fast-hdf 0.2.3 and later); with
h5py, or an older extension, NumPy builds the same buffers. A layout that
neither builder can prove identical to the per-face loop (for example a
negative endpoint index, an out-of-range perimeter span or a non-finite
coordinate) keeps the per-face loop; in `native` mode an engine refusal raises
`FastHdfError`. The geometry is identical in every case: WKB, coordinate order
and validity were compared on all 139 release-gate fixtures in `h5py`, `auto`
and `native` mode. The fast output is still the faster of the two, because it
builds no geometry at all.

The convenient output's current timings are in the
[release benchmark](#release-benchmark-public-methods) above
(`get_mesh_max_face_v`, `get_mesh_max_ws`, `get_mesh_summary`,
`get_mesh_cell_points`).

The figures below come from the earlier engine performance work. They measure
the **HDF read layer** (the reads under the public methods), not complete
public calls.

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
  catalogue scan of a 340,000-cell HEC-RAS 5.0.7 plan went from 30.5 s to
  0.21 s during the engine performance work).
- **Equal: most of a public call is not the read.** Public methods build
  pandas, xarray and GeoPandas objects (cell points and polygons, CRS
  resolution, timestamp conversion). That code runs the same in both modes,
  so a method's end-to-end native gain is smaller than its read gain, and on
  small models it can be negligible. ras-commander 0.109.0 and 0.110.1
  vectorized much of it, which made those calls faster in h5py mode too (see
  the [release benchmark](#release-benchmark-public-methods)).
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

**Rewriting an HDF during a public call.** An HDF's size and modification time
identify its cached session and typed results. They are read once per native
read (one `read_typed`, `read_attrs` or typed engine call, which may look them
up several times) and again by the next read. So an HDF rewritten in the middle
of a public call is read anew by every later read of that call. That covers an
in-place `h5py` write, a replacement after `fast_hdf.release_native_sessions(path)`,
and HEC-RAS or RAS Mapper rewriting the file in another process, as
ras-commander's own breakout and remesh workflows do. A writer that replaces or
renames a file must still call `release_native_sessions` first (Windows refuses
to replace a mapped file); ras-commander's own writers do.

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
| **Fluvial/pluvial with `delta_t=0`** | Not supported natively (the native kernel would mark equal-time cell pairs ambiguous; the reference marks nothing). `auto` uses the Python reference. Native is also refused when a mesh lacks `Faces Cell Indexes` or when the cell set differs from the one the reference can polygonize. Cells with invalid geometry (for example cells whose curved faces cross another cell boundary): the boundary runs natively, deciding for each such cell with the reference polygonizer's own rule whether the reference leaves it out (no polygon) and then dropping its cell pairs as the reference does; the polygons are refused. |
| **Mesh polygon diagnostics** | Automatic mode returns the native polygons only when their diagnostic records, warnings and `strict` outcome are provably the Python polygonizer's. Ambiguous or multi-polygon cells and other edge cases use the Python polygonizer. In `native` mode, the diagnostics records of a `no_polygon` cell can carry extra `native_reason_code`/`reason` keys. Diagnostics are attached only with `diagnostics=True`. |
| **Mesh face lines** | `auto`/`native` build face lines from native buffers only when each face table is `(rows, 2)`, the tables have one row per face, every endpoint index and perimeter span is in range, counts are not negative and coordinates are finite. Otherwise `auto` builds them in NumPy or with the per-face loop (same geometry); `native` raises `FastHdfError`. |
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
`ras_commander_fast_hdf.API_VERSION` (must be 12) and the log for "Ignoring
incompatible ras-commander-fast-hdf extension". Also check that
`RAS_COMMANDER_FAST_HDF` is not set to `h5py`/`0`.

**A project folder cannot be renamed or deleted on Windows.** With default
settings no HDF stays open after a call returns. If you set
`RAS_COMMANDER_HDF_SESSION_CACHE=persist`, call `fast_hdf.close_sessions()`
first.

## Versions and licence

| Component | Documented HDF qualification baseline |
|---|---|
| Engine | `ras-commander-fast-hdf` crate 0.2.0 ([crates.io](https://crates.io/crates/ras-commander-fast-hdf); source in [gpt-cmdr/ras-commander-fast-hdf](https://github.com/gpt-cmdr/ras-commander-fast-hdf)), engine API 10 |
| Bridge | Python package `ras-commander-fast-hdf` 0.2.0 (module `ras_commander_fast_hdf`), `API_VERSION` 11, text API 1, features `catalog, hdf, mesh, results`, `ENGINE_COMMIT` = the commit of tag `v0.2.0` |
| ras-commander | 0.108.0 and later require `ras-commander-fast-hdf>=0.2,<0.3` and bridge API 11; 0.109.0 and later require `>=0.2.3,<0.3`; 0.112.0 and later require `>=0.2.5,<0.3`; 0.113.0 and later require `>=0.3.0,<0.4` (bridge API 11 unchanged) |
| Wheels | On PyPI: Windows `cp310-abi3-win_amd64`, Linux `cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64` and `cp310-abi3-musllinux_1_2_x86_64`, macOS `cp310-abi3-macosx_11_0_arm64` (not yet qualified); source distribution |

`ENGINE_COMMIT` is the commit of the ras-commander-fast-hdf repository the
wheel was built from. Internal wheels built before the engine was published
report `0b024adc7857e9fb2d364997ad002e01a939cec1`; their engine source is
identical to 0.1.0.

The engine and extension are released under the MIT licence, copyright CLB
Engineering Corporation. The wheel's `.dist-info/licenses/` folder contains
`THIRD-PARTY-NOTICES.md`, which lists every Rust crate linked into the
extension with its licence text, and the licence files of the engine,
ras-commander (`ras-commander-fast-hdf-LICENSE.txt` is the engine's), the embedded
`hdf5-reader` (MIT), `freestiler` (ISC/MIT) and `i_float`/`i_overlay`. Keep these files with any copy of the wheel you
redistribute.

Report engine problems (a refusal you did not expect, a crash, a difference
from h5py) at
[ras-commander-fast-hdf issues](https://github.com/gpt-cmdr/ras-commander-fast-hdf/issues).
