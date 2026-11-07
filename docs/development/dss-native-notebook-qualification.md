# DSS Native Backend: Example Notebook Qualification

This report records the final round of tests for the native DSS backend in draft PR #794
(`dss-native-writes`). We re-ran every example notebook that reads or writes DSS three times,
once per `RasDss` backend: `java`, `native` and `shadow`. We then compared the results.

**Status:** IN PROGRESS. The tables are filled in as runs complete.

## Environment

| Item | Value |
|---|---|
| Branch | `dss-native-notebooks`, from `dss-native-writes` at `a3b6fa897` |
| Engine | `CLB-Engineering-Corporation/dss-commander-rust` `main` at `5af800d` |
| Wheel | `ras_commander_fast_dss-0.0.1-cp310-abi3-win_amd64.whl`, SHA-256 `30523d158e3b1b6aef18c113fa4e76e34f7da7b46e9cef90f0ad4781c6dededb` (FEATURES include `grid_srs_monolith_parity`, so native grid reads are enabled) |
| Python | CPython 3.12.11 (numpy 2.5.4, pandas 3.0.6, h5py 3.16.0) for all notebooks except 916 and 926. 916 and 926 ran on CPython 3.13.9 with numpy 2.5.4, because `qpkit` 0.1.0 imports `pydsstools`, which needs numpy<2 on Python 3.12. |
| Java path | HEC Monolith 3.3.27 through pyjnius 1.9.0 on JDK 17.0.20.1+1 |
| HEC-RAS | 7.0 (installed under `C:\Program Files (x86)\HEC\HEC-RAS\7.0`), run only through `RasCmdr.compute_plan` |
| HEC-Vortex | 0.13.3 (gridded imports in 917/926) |
| Host | CLB01, Windows 11 |

## Method

- Each notebook ran with nbclient in its own run root, one per backend. Every run root
  links back to this branch's `ras_commander/` and `examples/data/`, so `RasExamples` extracted
  a fresh project for every backend run. The backend was selected with `RAS_COMMANDER_DSS_BACKEND`.
  `PYTHONHASHSEED=0` was set so that the notebooks' own `set()` printing is stable.
- After the last cell, an extra cell recorded the live process state:
  - `_backend.summary()`;
  - every shadow record whose outcome was not `identical`;
  - whether `jnius` and `ras_commander_fast_dss` were loaded.
- Comparisons:
  - cell text outputs, with run-root paths, timestamps and kernel PIDs normalized;
  - image hashes;
  - every DSS file, record by record. The native reader runs with `raw=True` (stored bits),
    on the catalog, values, times, units and data type. File bytes are not compared, because
    DSS headers carry write times.
  - for notebooks that run HEC-RAS, every numeric dataset under `Results/` in each plan HDF.
- The harness scripts and raw evidence are kept outside the repository, on the qualification
  host under `D:\dss-commander-oracle\work\R-NB\`.

## Results

(See the per-notebook table below.)
