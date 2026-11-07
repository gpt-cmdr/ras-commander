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
| Branch | `dss-native-notebooks`, from `dss-native-writes` at `a3b6fa897` |
| Engine | `CLB-Engineering-Corporation/dss-commander-rust` `main` at `5af800d` |
| Wheel | `ras_commander_fast_dss-0.0.1-cp310-abi3-win_amd64.whl`, SHA-256 `30523d158e3b1b6aef18c113fa4e76e34f7da7b46e9cef90f0ad4781c6dededb`. `FEATURES` includes `grid_srs_monolith_parity`, so native grid reads are enabled. |
| Python | CPython 3.12.11 (numpy 2.5.4, pandas 3.0.6, h5py 3.16.0) for every notebook except 916 and 926. Those two need `qpkit` 0.1.0, which imports `pydsstools`; pydsstools needs numpy<2 on 3.12, so they ran on CPython 3.13.9 (numpy 2.5.4). |
| Java backend | HEC Monolith 3.3.27 through pyjnius 1.9.0, JDK 17.0.20.1+1 |
| HEC-RAS | 7.0, run only through `RasCmdr.compute_plan` |
| Other HEC tools | HEC-Vortex 0.13.3, used by 917 (`PrecipMrms.to_dss`) |
| Host | CLB01, Windows 11 |

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
  are kept on the qualification host under `D:\dss-commander-oracle\work\R-NB\`.

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
| 916 HRRR forecast | fail @17 | fail @17 | fail @17 | `qpkit` writes HRRR grids; `RasDss.get_catalog`, `read_grid`; HEC-RAS runs | catalog 1, read_grid 18: all identical | DSS: 18 grid records equal. HDF: every physical cell bit-equal (note 4). Same failure on all backends (note 5) | 305 / 452 / 340 |
| 917 MRMS QPE | fail @10 | fail @10 | fail @10 | Vortex writes 37 MRMS grids; `RasDss.get_catalog`, `read_grid`; HEC-RAS run | catalog 1, read_grid 37: all identical | DSS: 37 grid records equal; catalog row order follows each Vortex run. Same failure on all backends (note 5) | 160 / 141 / 121 |
| 918 HMS-RAS coupled forecast | pass | pass | pass | None executed. The DSS calls appear only in printed patterns. | none | None | 2 / 2 / 2 |
| 926 WPC QPF | fail @15 | fail @15 | fail @15 | `qpkit` writes WPC grids; `RasDss.get_catalog`, `read_grid`; HEC-RAS runs | catalog 1, read_grid 28: all identical | DSS: 28 grid records equal. HDF: every physical cell bit-equal (note 4). Same failure on all backends (note 5) | 343 / 313 / 381 |
| 952 eBFE Upper Guadalupe, partial | partial | partial | partial | `get_catalog`, `check_pathname` (first 10 per file), `RasEbfeModels._validate_dss_files` on the 3 unique delivery DSS files (504, 532 and 1,680 records, including the gridded precipitation file), copied to D: | catalog 36: all identical | Identical catalogs, checks and validation. The copies were unchanged after Java reads. | 1.1 / 0.3 / 1.5 |

### Supplementary reruns past the pre-existing failure (916, 917, 926)

916, 917 and 926 stop at a pre-existing failure (note 5) before their final DSS-versus-HDF checks. To
cover those checks, we ran them again from a scratch copy, with one edit:
`truncate=False` became `truncate=False, include_ghost_cells=True` in every
`get_mesh_timeseries` call. This restores the cell support the notebooks were written for.
The edit is not committed.

| NB | java | native | shadow | Shadow summary | Differences | Wall time j / n / s (s) |
|---|---|---|---|---|---|---|
| 917 MRMS QPE (Davis and NewOrleansMetro) | pass | pass | pass | catalog 4, read_grid 122: all identical | DSS: Davis 37 and NOLA 24 grid records, equal. Text: only Vortex catalog row order, run timestamps, and file sizes that carry write times. Images: identical. HDF: all float result datasets bit-equal except `Minimum Link DS Velocity` (Davis) and `Main Gates` (NOLA). Both also differ in the no-rain baseline runs, which use no DSS, so they are HEC-RAS run-to-run variation. | 2011 / 1888 / 2052 |
| 916 HRRR forecast | pass | pass | pass | catalog 1, read_grid 18: all identical | No text or image differences | 346 / 334 / 304 |
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

## Skipped notebooks

A skip is not a pass. Each reason below was checked on this host.

| Notebook | Reason |
|---|---|
| 731 Atlas 14 shared temporal, existing model | This is a template for a user's model. It needs `SOURCE_PROJECT = C:/Models/MyModel` and a NOAA Atlas 14 ASC grid, neither of which exists here. All three backends stop at cell 5 with `FileNotFoundError`. Its DSS export runs only when `RUN_DSS_EXPORT = True`; the default is False. |
| 950, 951, 953, 954, 955, 957 eBFE deliveries | These notebooks organize into `RAS_COMMANDER_EBFE_ROOT`, which defaults to the shared workspace `H:\Testing\eBFE Model Organization`, and the rules forbid writing to H:. Their organized deliveries on H: contain no DSS files (checked: Spring Creek, North Galveston Bay, Rio Hondo, Lake Maurepas, Tickfaw, Spring River), so `_validate_dss_files` and the notebooks' `RasDss` calls have nothing to read. Moving them to D: would mean downloading the FEMA archives again. |
| 952 eBFE Upper Guadalupe, full notebook | The organized delivery is 56 GB on H:. Only its DSS operations were run, on the 3 unique DSS files copied to D: (table row "952 partial"). |
| 956 hydrofabric conflation, 959 2D breakout geometry, 430 channel capacity, 237 subdomain breakout | These call eBFE organizers only to stage geometry. The deliveries are on H: or need an external `EBFE_SOURCE` download, and the notebooks perform no `RasDss` read or write of their own. |
| 958 model sources showcase | Its DSS path is `UsgsScienceBase` model repair, which needs the Kalamazoo ScienceBase download (about 3 GB). Not run. |

## Fixes made

None. No integration defect in ras-commander's DSS backends was found, and the engine needed no
change.

## Open items

1. **Notebooks 916, 917, 926 need a refresh** after upstream #534. Their
   `get_mesh_timeseries(..., truncate=False)` calls need `include_ghost_cells=True`, or their
   `get_mesh_cell_points()` calls need `include_ghost_cells=False`, to match the cell support
   they assert. This is notebook maintenance, separate from the DSS backend.
2. **Notebook 318 deletes the shared example-project folder.** Its last cell runs
   `shutil.rmtree(project_path.parent)`, which removes the whole `example_projects` folder,
   including other notebooks' projects. `examples/AGENTS.md` forbids this cleanup pattern.
   It should remove only `project_path`.
3. **Child-process shadow counts.** Shadow counters live in each process. When a notebook
   writes DSS in a child process, as 728 does, the notebook's shadow summary does not include
   those writes. An `unexpected` outcome would still be logged at WARNING in the child's
   stderr. 728 checks that stderr only for access violations.
4. **926 cannot be reproduced across days.** It downloads the current-day WPC cycle, so its
   forcing, and its pass/fail against the notebook's WSEL tolerance, depend on when it runs.
   A fixed-cycle mode would make this notebook usable as a regression test.
5. **Host environment (not repository issues).**
   - `%LOCALAPPDATA%\ras-commander\examples` on CLB01 is a junction to a missing
     `D:\Archive` folder. The runs used a scratch `LOCALAPPDATA` that held the HEC-RAS 7.0
     example archive.
   - The user-level `SSL_CERT_FILE` points to a missing Anaconda bundle, which broke the
     HTTPS downloads in 916 and 926 until the runner pointed it at certifi.
