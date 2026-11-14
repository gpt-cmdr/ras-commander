# DSS Native Backend: Example Notebook Qualification

This report records the final round of tests for the native DSS backend in draft PR #794
(`dss-native-writes`). We re-ran every example notebook that reads or writes DSS three times,
once per `RasDss` backend: `java`, `native` and `shadow`. We then compared the outputs, the DSS
files, and the HEC-RAS results.

**Outcome:**
- No notebook behaves differently on the native backend than on Java.
- Every shadow comparison was `identical` or `expected`. There were no `unexpected` outcomes.
- Every DSS file written or read matched record for record across the backends.
- Every HEC-RAS physical-cell result is bit-identical across the backends.
- The notebooks that fail, fail at the same cell with the same error on all three backends.
  Those failures do not involve DSS (see "Pre-existing failures").
- With that failure bypassed in a scratch copy, 916 and 917 run to completion on all three
  backends, with the same results.
- No integration defect was found, so this branch makes no library change.
- **Final round (2026-11-07):** 916, 917 and 926 are fixed for #534, 926 gains a fixed-cycle
  mode, 318 no longer deletes the shared example-project folder, and 731 has a native export route.
  All five fixed notebooks pass on all three backends; see "Final round" below.

!!! warning "Correction (2026-11-12): 916 forcing before the review-1 fix"
    Every 916 run recorded in this report before the 2026-11-12 review-1 fix drove the
    forecast plan with the `qpkit` route (GDAL crops of the HRRR running accumulations,
    differenced, reprojected and written by `qpkit` 0.1.0). Those runs are **execution
    and DSS read-back evidence only; their forcing failed source-spatial qualification.**
    For cycle 2024-08-08 15Z the qpkit grids leave 69 lattice cells missing in every hour
    (71 in one hour), which the notebook's `np.nansum` and finite filters turned into zero
    rain, and against an independent full-source GDAL bilinear warp of the same HRRR
    message the 18-hour total has an RMSE of 14.4 mm (the native import: 0.00024 mm).
    "Identical across backends" for those runs means the backends read the same defective
    grids identically; it says nothing about their spatial correctness. From the review-1
    fix, 916 drives its runs with native hourly forcing validated against a full-source
    warp; see "ras-commander-fast-dss 0.1.2 notebooks".

    Notebook 926 also writes its forcing with `qpkit` (WPC QPF). Its retained grids from
    the qualified fixed cycle 2026-11-05 00Z have 126 cells missing in every one of the
    28 frames. 926 has not yet been assessed against a full-source warp; until it is,
    treat its runs in this report as execution and read-back evidence only.

**Counts.** These are the unmodified notebooks run on each backend: 9 run in full, plus a
partial DSS check of 952.

| Backend | Pass | Fail (pre-existing, identical on all backends) | Partial | Skip |
|---|---|---|---|---|
| java | 6 (310, 312, 313, 318, 728, 918) | 3 (916, 917, 926) | 1 (952 DSS calls) | 12 (731, 237, 430, 950, 951, 953, 954, 955, 956, 957, 958, 959) |
| native | 6 | 3 | 1 | same |
| shadow | 6 | 3 | 1 | same |

In the patched reruns, 916 and 917 pass on all three backends; the 926 rerun is inconclusive.
Shadow totals over all runs: no `unexpected` outcomes.
- `expected`: 2 in the notebooks' own summaries (312 D3, 728 W2), plus 1 W2 in the 728 writer
  re-run in a separate process (note 3).
- `identical`: every other comparison.

## Environment

| Item | Value |
|---|---|
| Branch | `dss-native-writes` at `a3b6fa897` |
| Engine | Pre-release build of the engine that became `ras-commander-fast-dss` 0.1.0 |
| Wheel | `ras_commander_fast_dss-0.0.1-cp310-abi3-win_amd64.whl`, SHA-256 `30523d158e3b1b6aef18c113fa4e76e34f7da7b46e9cef90f0ad4781c6dededb`. `FEATURES` includes `grid_srs_monolith_parity`, so native grid reads are enabled. |
| Python | CPython 3.12.11 (numpy 2.5.4, pandas 3.0.6, h5py 3.16.0) for every notebook except 916 and 926. Those two need `qpkit` 0.1.0, which imports `pydsstools`; pydsstools needs numpy<2 on 3.12, so they ran on CPython 3.13.9 (numpy 2.5.4). |
| Java backend | HEC Monolith 3.3.27 through pyjnius 1.9.0, JDK 17.0.20.1+1 |
| HEC-RAS | 7.0, run only through `RasCmdr.compute_plan` |
| Other HEC tools | HEC-Vortex 0.13.3, used by 917 (`PrecipMrms.to_dss`) |
| Host | One Windows 11 workstation |

## Method

- **Runs.** Each notebook ran under nbclient, unmodified, in a separate run root for each backend.
  - The backend was selected with `RAS_COMMANDER_DSS_BACKEND`.
  - Each run root links to this branch's `ras_commander/` and `examples/data/`.
  - Each run extracted its own `RasExamples` projects, from the HEC-RAS 7.0 example archive.
  - `PYTHONHASHSEED=0` keeps the notebooks' own `set()` printing stable.
- **Captured state.** An extra cell, run after the notebook's last cell, recorded:
  - the shadow summary `_backend.summary()`;
  - every shadow record that was not `identical`;
  - whether `jnius` and `ras_commander_fast_dss` were loaded.

  In every native run, `jnius` was not loaded. The native backend never started a JVM.
- **Compared.**
  - Cell text outputs, with run-root paths, timestamps and kernel PIDs normalized.
  - Image hashes.
  - Each DSS file, record by record, with the native reader in `raw=True` mode, so stored bits
    are compared. The comparison covers the catalog, values, times, units, data type, and grid
    cells and extent. File bytes are not compared, because a DSS header carries write times.
  - Every numeric dataset under `Results/` in each HEC-RAS plan HDF.
- **Evidence.** The harness scripts and raw evidence (executed notebooks and comparison JSON)
  are kept on the qualification host, outside the repository.

## Inventory

We scanned the code cells of all example notebooks. Nineteen notebooks read or write DSS, or
call a helper that does (`RasDss`, `RasEbfeModels._validate_dss_files`, Vortex, `qpkit`):
310, 312, 313, 318, 728, 731, 916, 917, 918, 926, 237, 430, 950–959.

Ten more notebooks only parse DSS pathname text from `boundaries_df`, or mention DSS in prose:
230, 300, 301, 319, 320, 700, 722, 913, 915, 919. They never open a DSS file, so the backend
setting cannot change them. They were not run.

## Per-notebook results

Wall times are single incidental observations, not benchmarks.

| NB | java | native | shadow | DSS operations exercised | Shadow summary | Differences | Wall time j / n / s (s) |
|---|---|---|---|---|---|---|---|
| 310 DSS boundary extraction | pass | pass | pass | `get_info`, `get_catalog`, `read_timeseries`, `extract_boundary_timeseries` (BaldEagleCrkMulti2D) | catalog 2, read_timeseries 8: all identical | None | 35 / 42 / 37 |
| 312 QMult and DSS paths | pass | pass | pass | `write_timeseries` (new DSS7 file), `read_timeseries` round trip, `get_file_version`, DSS link edits; 3 Muncie HEC-RAS runs | file_version 1, write_timeseries 1: identical. read_timeseries 1: **expected D3** | See note 1. DSS: 4 files, all records equal. HDF: 3 plans, 253/253 datasets bit-equal | 198 / 187 / 173 |
| 313 HMS-to-RAS boundary matching | pass | pass | pass | `get_catalog`, `read_timeseries`, `extract_boundary_timeseries` | catalog 1, read_timeseries 59: all identical | None | 31 / 27 / 26 |
| 318 Validating DSS paths | pass | pass | pass | `check_file_exists`, `check_pathname*`, `check_data_availability`, `is_pathname_available`, `is_valid_pathname`, `get_catalog`, `read_timeseries` | catalog 9, read_timeseries 5: all identical | None, after rerun with a fixed hash seed (note 2) | 4.5 / 4.6 / 4.3 |
| 728 Extend gridded DSS forcing window | pass | pass | pass | `write_timeseries` and `write_grid_timeseries` (DSS7, SHG, in a child process), `get_catalog`, `read_grid`, `copy_grid_with_zero_tail`, `get_file_version`, `configure_gridded_dss_precipitation`; HEC-RAS run | catalog 4, file_version 1, read_grid 17: identical. copy_grid_with_zero_tail 1: **expected W2**. Child-process writes: write_timeseries identical, write_grid_timeseries **expected W2** (note 3) | 5 DSS files: all records equal. HDF: every physical cell bit-equal (note 4) | 219 / 219 / 157 |
| 916 HRRR forecast (qpkit forcing; see correction) | fail @17 | fail @17 | fail @17 | `qpkit` writes HRRR grids; `RasDss.get_catalog`, `read_grid`; HEC-RAS runs | catalog 1, read_grid 18: all identical | DSS: 18 grid records equal. HDF: every physical cell bit-equal (note 4). Same failure on all backends (note 5) | 305 / 452 / 340 |
| 917 MRMS QPE | fail @10 | fail @10 | fail @10 | Vortex writes 37 MRMS grids; `RasDss.get_catalog`, `read_grid`; HEC-RAS run | catalog 1, read_grid 37: all identical | DSS: 37 grid records equal; catalog row order follows each Vortex run. Same failure on all backends (note 5) | 160 / 141 / 121 |
| 918 HMS-RAS coupled forecast | pass | pass | pass | None executed. The DSS calls appear only in printed patterns. | none | None | 2 / 2 / 2 |
| 926 WPC QPF | fail @15 | fail @15 | fail @15 | `qpkit` writes WPC grids; `RasDss.get_catalog`, `read_grid`; HEC-RAS runs | catalog 1, read_grid 28: all identical | DSS: 28 grid records equal. HDF: every physical cell bit-equal (note 4). Same failure on all backends (note 5) | 343 / 313 / 381 |
| 952 eBFE Upper Guadalupe, partial | partial | partial | partial | `get_catalog`, `check_pathname` (first 10 per file), `RasEbfeModels._validate_dss_files` on the 3 unique delivery DSS files (504, 532 and 1,680 records, including the gridded precipitation file), copied to a private workspace | catalog 36: all identical | Identical catalogs, checks and validation. The copies were unchanged after Java reads. | 1.1 / 0.3 / 1.5 |

### Supplementary reruns past the pre-existing failure (916, 917, 926)

916, 917 and 926 stop at a pre-existing failure (note 5) before their final DSS-versus-HDF checks. To
cover those checks, we ran them again from a scratch copy, with one edit:
`truncate=False` became `truncate=False, include_ghost_cells=True` in every
`get_mesh_timeseries` call. This restores the cell support the notebooks were written for.
The edit is not committed.

| NB | java | native | shadow | Shadow summary | Differences | Wall time j / n / s (s) |
|---|---|---|---|---|---|---|
| 917 MRMS QPE (Davis and NewOrleansMetro) | pass | pass | pass | catalog 4, read_grid 122: all identical | DSS: Davis 37 and NOLA 24 grid records, equal. Text: only Vortex catalog row order, run timestamps, and file sizes that carry write times. Images: identical. HDF: all float result datasets bit-equal except `Minimum Link DS Velocity` (Davis) and `Main Gates` (NOLA). Both also differ in the no-rain baseline runs, which use no DSS, so they are HEC-RAS run-to-run variation. | 2011 / 1888 / 2052 |
| 916 HRRR forecast (qpkit forcing; execution/read-back evidence only, failed spatial qualification) | pass | pass | pass | catalog 1, read_grid 18: all identical | No text or image differences | 346 / 334 / 304 |
| 926 WPC QPF | fail @15 | fail @7 | fail @15 | Inconclusive (see below) | | 347 / 8 / 315 |

**Why the 926 rerun is inconclusive.** 926 downloads the *current-day* WPC QPF cycle. The rerun
started after the UTC date changed, so each backend saw a different set of published cycles:
- the native run rejected the 06Z cycle, which had an unexpected forecast hour (174), and
  stopped at cell 7;
- the shadow run computed on different forcing and failed the notebook's WSEL-error tolerance
  (1.04 ft in 3 cells);
- the java run overlapped a HEC-RAS process left behind by an earlier rerun that was stopped at
  its time limit, and failed the `.bco` existence check.

None of these failures involves the DSS backend. The valid 926 comparison is the unmodified run
in the main table: all three backends used the same cycle there, and the records, shadow reads
and physical-cell HDF results were equal.

### Notes

1. **312, D3.** On the Java backend, reading back the series that the notebook has just written
   raises `No data found` (the known D3 Java whole-read defect). The notebook prints "DSS
   round-trip unavailable" and restores the inline data. The native and shadow runs read the
   65 points back and run the DSS→inline conversion. Shadow classifies the case as `expected`
   (D3) after verifying the window. Both paths leave the same inline hydrograph, and the
   HEC-RAS results are bit-identical. The remaining text differences are only logging order
   between stdout and stderr, and how much of a path the DataFrame display truncates (the run
   root name lengths differ).
2. **318.** The first run printed the set of D-parts in a different order on each backend,
   because the notebook iterates over a Python `set` and each kernel had its own hash seed. A
   rerun with `PYTHONHASHSEED=0` produced identical outputs.
3. **728, W2.** For DSS7 Albers/SHG grids, Monolith writes a null value of 0.0 in the grid
   header, while the native writer writes -FLT_MAX. Cell values are identical; this is the
   expected label W2. Notebook 728 writes its source file in a child process, which keeps its
   own shadow counters. We re-ran that writer script on its own under `shadow` to collect them.
4. **HEC-RAS results.** In 728, 916 and 926, every per-cell dataset (water surface, depth,
   precipitation) and every face velocity over the physical cells is bit-identical across the
   backends. A few datasets differ between runs:
   - cell velocity and eddy viscosity, in the ghost cells only (index ≥ `Cell Count`), where
     HEC-RAS writes uninitialized values;
   - denormal values (about 1e-43) in `Gate #1`;
   - the calibration-region aggregates `Volume Error`, `WSE Avg` and `WSE Min`.

   In 916 and 926, `qpkit` writes the DSS forcing whatever the backend, so the HEC-RAS inputs
   are identical, yet the differences appear there too. In 728, shadow's forcing file is
   written by Java and also differs from the Java run. The differences are therefore HEC-RAS
   run-to-run variation, not DSS effects.
5. **Pre-existing failure, 916, 917 and 926.** Upstream #534 (2026-10-16, "Exclude 2D ghost
   cells by default") made `HdfResultsMesh.get_mesh_timeseries` drop ghost cells by default.
   These notebooks were last executed on 2026-09-26. Each notebook then fails at the same cell
   on all three backends:
   - 917 builds its cell support with ghost cells (2,705 physical + 236 boundary) and asserts
     exact coverage, so it fails at cell 10;
   - 916 and 926 assert that `get_mesh_cell_points()` (ghost cells included by default) has
     the size of a results row, so they fail at the comparison cell.

   All DSS operations finish before the failing cells, and their shadow comparisons are all
   identical. This branch does not change these notebooks; see "Open items".

## Final round: fixed notebooks (2026-11-07)

The notebooks that failed above, and 318's clean-up, were fixed on `dss-native-writes`, then
each was run again on `java`, `native` and `shadow` with the same harness and method.

| Item | Value |
|---|---|
| Branch | `dss-native-writes`, after merging `origin/main` (with #801) |
| Engine | `ras-commander-fast-dss` 0.0.1, the same wheel as above (engine `5af800d`; engine `main` `088668c` differs only in `docs/project/OPEN_QUESTIONS.md`) |
| HEC-RAS | 7.0, through `RasCmdr.compute_plan` only |
| Other | HEC-Vortex 0.13.3 (917's MRMS import, and 731's `vortex` route); `qpkit` 0.1.0 (916, 926) |

| NB | Change | java | native | shadow | Differences | Wall time j / n / s (s) |
|---|---|---|---|---|---|---|
| 318 | Clean-up removes only `BaldEagleCrkMulti2D_311`, not the shared `example_projects` folder | pass | pass | pass | None | 6 / 4 / 4 |
| 916 (qpkit forcing; execution/read-back evidence only, failed spatial qualification) | `get_mesh_cell_points(..., include_ghost_cells=False)` to match the ghost-free result rows | pass | pass | pass | No text or image differences. DSS: every record of the 4 DSS files equal, including the 18 HRRR grids. HDF: every physical-cell and face dataset bit-equal (note 4 classes only) | 350 / 350 / 428 |
| 917 | `include_ghost_cells=True` in every `get_mesh_timeseries(..., truncate=False)` call, because the notebook checks that boundary cells receive no rain | pass | pass (note A) | pass (note A) | Shadow: catalog 4, read_grid 122, all identical. DSS: 37 Davis and 24 NOLA grids equal. Text: run-folder timestamps, Vortex catalog row order, file sizes and the NOLA volume-accounting value only | 1886 / 2323 / 2052 |
| 926 | Fixed-cycle mode (`RAS_COMMANDER_WPC_QPF_CYCLE`, `RAS_COMMANDER_WPC_QPF_GRIB_DIR`); physical cell centers as 916 | pass | pass | pass | Cycle 2026-11-05 00Z. No text or image differences. DSS: every record equal, including the 28 WPC grids. HDF: every physical-cell and face dataset bit-equal (note 4 classes only) | 437 / 775 / 552 |
| 731 | `DSS_EXPORT_ROUTE = "native"` beside the default `"vortex"`; `SOURCE_BUFFER_PERCENT` | — | — | — | See note B | — |

**Note A.** The first native and shadow runs of 917 stopped in cell 11, before any DSS step, when
the NOLA no-rain baseline reached the notebook's `max_runtime` of 2,400 s. Another HEC-RAS
notebook was running at the same time on this host. Each was run again alone, and passed.

**Note B, 731.** The notebook is a template for a user's model, so its committed state has no
outputs. Its export cells were run with the configuration cell set to the public
`NewOrleansMetro` example (plan 01, 72 hours, `PAD_DRY_TAIL=True`), NOAA Atlas 14 Volume 9
100-year 24-hour depths (`se100yr24ha`, NAD83) and Volume 9 temporal region 1 (a mechanics choice,
not checked against NOAA's region map), with `SOURCE_BUFFER_PERCENT = 50`:

- the `vortex` route (HEC-Vortex 0.13.3, `java` reads) and the `native` route (`native` reads, no
  JVM loaded) both passed the notebook's read-back checks;
- they wrote the same 144 records, with identical cell values, extents, units (`IN`) and type
  (`PER-CUM`); the stored null value differs (0.0 against -FLT_MAX, label W2);
- with the template's 10% buffer, both routes failed the notebook's "no missing rainfall over
  model cells" check in the same way: the crop was too small for 2,000 m bilinear cells on this
  10 km model, which is why the buffer became a setting;
- the optional attachment step stopped in `RasUnsteady.inspect_boundary_blocks` with
  `ambiguous_location_kind` for block 4 of `NewOrleansMetro.u01`, a limit of that API unrelated
  to DSS, so the precompute qualification was not reached.

`tests/test_atlas14_native_dss_export.py` runs the notebook's native call on a NetCDF built
from NOAA's committed Texas region 3 curve and reads every record back on the native backend.

**926 cycles.** WPC keeps about a week of cycles online. On java, cycle 2026-11-07 00Z (0.02 in
over the selected day) failed the notebook's 1.0 ft maximum-WSEL-error gate at cell 15 with
1.0375 ft in 3 cells, identically on all three backends; 2026-11-06 12Z (0.86 ft) and
2026-11-05 00Z (0.85 ft) passed; 2026-11-03 12Z stopped at cell 9, where one `qpkit` DSS grid's
regional mean differed from its source GRIB by more than the notebook's 0.30 mm. 2026-11-05 00Z,
the wettest passing cycle, is the committed run. Its 28 GRIB files are kept with their SHA-256
sums on the qualification host.

**Committed outputs.** 916, 917 and 926 carry the outputs of their `java` (default backend)
runs. 318 keeps its earlier outputs, except the changed clean-up cell, whose output comes from
the `java` run. 917's committed outputs come from a full `java` rerun on 2026-11-09 (ras-commander
0.113.0 with `ras-commander-fast-dss` 0.1.1 installed; 2,107 s; every cell passed). Before that rerun,
its diagnostic cell was changed to print the interpreter name and repository-relative source paths, the
`matplotlib.animation` logger was set to WARNING, and the `PrecipMrms` and `RasUnsteady` INFO messages
were changed to give file names (full paths moved to DEBUG), so the outputs carry no host paths.

## ras-commander-fast-dss 0.1.2 notebooks (2026-11-12)

Two new notebooks teach the native engine, and three existing ones were revised.
Each was run with the same harness as above on `ras-commander-fast-dss` 0.1.2 from
PyPI (CPython 3.12.11; 916 on CPython 3.13.5 for `qpkit`), HEC-RAS 7.0 through
`RasCmdr` only, and HEC-Vortex 0.13.3 for the Vortex routes. "default" means
`RAS_COMMANDER_DSS_BACKEND` unset, so `RasDss` uses `java`; notebooks 322, 731 and
732 select the native engine explicitly where they teach it. Committed outputs are
the default-lane runs.

| NB | Change | default | native | shadow | Wall time (s) |
|---|---|---|---|---|---|
| 322 Native DSS Records, Backends, and Copy-Out Recovery (new) | Records, backends, `sync=`, paired data, locations and `repair` on public HEC files; no HEC-RAS | pass | pass | in-notebook (note C) | 28 / 30 / — |
| 732 Native Gridded Import and Grid Tools on Real Precipitation (new) | `RasDssGrid` on AORC Zarr/NetCDF, IMERG HDF5, Stage IV GRIB1/GRIB2 and MRMS GRIB2; every grid tool; no HEC-RAS | pass | pass | not applicable (note D) | 43 / 53 / — |
| 731 Atlas 14 shared temporal pattern | Public preset (NewOrleansMetro, NOAA `se100yr24ha`); native export through `RasDssGrid.import_gridded` | pass (native export route) | pass | — | 115 / 54; Vortex route 39 (note E) |
| 916 HRRR forecast | Review 1: the HEC-RAS runs are driven by native hourly forcing (HRRR one-hour APCP messages through `RasDssGrid`), validated against a full-source GDAL warp with a coverage gate; qpkit kept as a disclosed comparison that fails spatial qualification | pass | pass | pass | 371 / 405 / 330 (note G) |
| 917 MRMS QPE | Visible backend selectors; native preprocessing (1-72 h windows, overlap/gap reports, shapefile clip, threads) | pass | pass (`RAS_COMMANDER_MRMS_BACKEND=native`) | pass (`...=shadow`) | 2910 / 2351 / 3507 (note F) |

**Note C, 322.** This notebook was added as 321 and renumbered 322 on 2026-11-13, when `main` gained its own notebook 321 (terrain modification layer writers); its cells and outputs are unchanged. The notebook's own comparison cell runs `native`, `java` and
`shadow` in one kernel. In the default lane every series was equal to the native
read on all three, and the shadow summary was `read_timeseries|identical|identical: 2`.
With `RAS_COMMANDER_DSS_BACKEND` set, the environment overrides the attribute, so
the cell compares one backend with itself; the notebook says to run it without
the variable.

**Note D, 732.** Every operation runs on the engine whatever the backend; the only
backend-dependent calls are `RasDss.read_grid` read-backs, which the notebook pins
to `native`. Findings: Zarr and NetCDF imports of the same AORC hours are identical
with `near`; with `bilinear`/`average` up to 20 cells, all within 2.6 km of the source
chunk's edge differ, where each route resamples from beyond its own extent. A
Lambert conformal US-foot target (EPSG:2276) is refused while planning (the engine
supports foot targets on Transverse Mercator); EPSG:2257 is used. `threads=1` and
the all-cores default store identical cells. The MRMS 24H Pass 2 product equals
the sum of the 24 hourly grids; the Stage IV 24-hour analysis over the same period
is about 64 % higher over the envelope, and the normalizer imposes it exactly.

**Note E, 731.** The `native` and `vortex` export routes wrote the same 144
records with identical cell values. Before the committed run, hms-commander's Atlas
14 helper logged its cache file's full path at INFO; the notebook now sets that
logger to WARNING and was rerun. The attachment and precompute steps stay off in
the preset (see note B).

**Note F, 917.** The first default run stopped when the Davis event plan reached
its 1,200 s `max_runtime` on a shared, loaded host. The notebook now reads
`RAS_COMMANDER_917_MAX_RUNTIME_SCALE` (default 1); all three lanes ran with 3. A
second default run stopped in the new preprocessing cell (the New Orleans case has
no fixed MRMS box); the cell now derives the bounds as the case runner does, was
checked in isolation, and all three lanes were rerun. Results: the 37 Davis and 24
New Orleans MRMS grids are equal cell for cell on all three lanes (HEC-Vortex on
default, the native importer on native, both on shadow); the event plans' water
surface and cumulative precipitation are bit-identical across lanes; shadow
recorded 151 comparisons (`catalog` 4, `read_grid` 147), all `identical`; the native
lane loaded no JVM. After review 1, the scale variable is validated (a non-numeric, non-finite or non-positive value raises `ValueError`) and the default lane was rerun with that code (2,910 s, pass); the committed outputs come from that rerun. The native and shadow figures are from the run before this validation-only change.

**Note G, 916 (review 1).** The independent review of `2f9431eef` found that the qpkit
route used until then is spatially wrong for this cycle (see the correction at the top).
The notebook now downloads the one-hour APCP message of each forecast hour, imports the
18 messages with `RasDssGrid.import_gridded` onto a 3,000 m SHG lattice covering the
buffered model footprint, and stops if any forcing cell is missing. Each hourly record is
compared with a Rasterio/GDAL bilinear warp of its complete source message onto the stored
lattice (gate: no missing cell in either, at most 0.01 mm difference): no missing cell in any of the 18 hours, RMSE at most 1.9e-4 mm and maximum difference at most 0.00077 mm; the sum of the 18 hours differs from the warped 0-18 h running accumulation by at most 0.015 mm. The three lanes wrote identical forcing records, the forecast plan's water surface and cumulative rainfall are bit-identical across lanes, shadow recorded 79 comparisons (catalog 2, read_grid 77), all `identical`, and the native lane loaded no JVM.
The temporary and final plan HDFs are checked against that forcing, and every mesh cell
must sample a valid forcing cell. The qpkit route still runs, into a separate file no plan
uses; its missing cells are counted and kept missing: 69 cells missing in every hour (71 in one), and over the 527 cells valid in every hour an RMSE of 4.8 mm against a bilinear and 5.0 mm against a nearest-neighbour full-source warp on qpkit's own lattice; the notebook reports it as not spatially qualified. Both GRIB decodes
match GDAL to 1.5e-5 mm. `qpkit` is a third-party package (Gyan Basyal, WEST Consultants,
Inc.; Apache-2.0; source `github.com/gyanz/qpkit`, 0.1.0 built from commit `64455cb9efad`);
it is not a gpt-cmdr or CLB package. Nothing was reported upstream from this work.

## Skipped notebooks

A skip is not a pass. Each reason below was checked on this host.

| Notebook | Reason |
|---|---|
| 731 Atlas 14 shared temporal, existing model (before 2026-11-12) | This is a template for a user's model. It needs `SOURCE_PROJECT = C:/Models/MyModel` and a NOAA Atlas 14 ASC grid, neither of which exists here. All three backends stop at cell 5 with `FileNotFoundError`. Its DSS export runs only when `RUN_DSS_EXPORT = True`; the default is False. |
| 950, 951, 953, 954, 955, 957 eBFE deliveries | These notebooks organize into `RAS_COMMANDER_EBFE_ROOT`, a shared workspace that this qualification was not permitted to write to. The organized deliveries already present there contain no DSS files (checked: Spring Creek, North Galveston Bay, Rio Hondo, Lake Maurepas, Tickfaw, Spring River), so `_validate_dss_files` and the notebooks' `RasDss` calls have nothing to read. Running them in a private workspace would mean downloading the FEMA archives again. |
| 952 eBFE Upper Guadalupe, full notebook | The organized delivery is 56 GB in the shared workspace. Only its DSS operations were run, on copies of its 3 unique DSS files in a private workspace (table row "952 partial"). |
| 956 hydrofabric conflation, 959 2D breakout geometry, 430 channel capacity, 237 subdomain breakout | These call eBFE organizers only to stage geometry. The deliveries are in the shared workspace or need an external `EBFE_SOURCE` download, and the notebooks perform no `RasDss` read or write of their own. |
| 958 model sources showcase | Its DSS path is `UsgsScienceBase` model repair, which needs the Kalamazoo ScienceBase download (about 3 GB). Not run. |

## Fixes made

None. No integration defect in ras-commander's DSS backends was found, and the engine needed no
change.

## Open items

1. **Resolved 2026-11-07: notebooks 916, 917, 926 needed a refresh** after upstream #534. Their
   `get_mesh_timeseries(..., truncate=False)` calls need `include_ghost_cells=True`, or their
   `get_mesh_cell_points()` calls need `include_ghost_cells=False`, to match the cell support
   they assert. This is notebook maintenance, separate from the DSS backend.
2. **Resolved 2026-11-07: notebook 318 deleted the shared example-project folder.** Its last cell runs
   `shutil.rmtree(project_path.parent)`, which removes the whole `example_projects` folder,
   including other notebooks' projects. `examples/AGENTS.md` forbids this cleanup pattern.
   It should remove only `project_path`.
3. **Child-process shadow counts.** Shadow counters live in each process. When a notebook
   writes DSS in a child process, as 728 does, the notebook's shadow summary does not include
   those writes. An `unexpected` outcome would still be logged at WARNING in the child's
   stderr. 728 checks that stderr only for access violations.
4. **Resolved 2026-11-07 (fixed-cycle mode): 926 could not be reproduced across days.** It downloads the current-day WPC cycle, so its
   forcing, and its pass/fail against the notebook's WSEL tolerance, depend on when it runs.
   A fixed-cycle mode would make this notebook usable as a regression test.
5. **Host environment (not repository issues).** Two settings specific to the qualification host
   (a stale examples cache link and a stale `SSL_CERT_FILE`) were worked around in the runner.
