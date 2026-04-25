# Session State — 2026-04-19

**Project**: ras-commander (G:\GH\ras-commander)
**Session summary**: Fixed notebook 917 HEC-RAS execution failures — three root causes identified and resolved. Model now computing with 5.0.7.

## Files Modified

| File | Change |
|------|--------|
| `examples/917_stofs3d_coastal_boundary.ipynb` cell `e53da651` | Changed `init_ras_project(path, "6.5")` → `"5.0.7"` |
| `examples/917_stofs3d_coastal_boundary.ipynb` cell `acf6476f` | Added `Run HTab= 0` plan file modification + `p_file` variable |
| `examples/917_stofs3d_coastal_boundary.ipynb` cell `70c0ca83` | Changed re-init from `"6.5"` → `"5.0.7"` |
| `examples/917_stofs3d_coastal_boundary.ipynb` cell `980d6d3d` | Updated markdown with version note explaining 5.07 requirement |

## Key Decisions

- **Use HEC-RAS 5.0.7 not 6.5**: The eBFE .g01.hdf was preprocessed with 5.07. HEC-RAS 6.x crashes with "Unexpected error; quitting" on 5.07-era geometry tables. Non-negotiable.
- **Skip geometry preprocessor (Run HTab=0)**: Reuse existing .g01.hdf from eBFE delivery. Regenerating takes 30+ min and terrain paths are fragile.
- **Disable DSS precipitation (Use DSS=False)**: eBFE references Jan 2000 HMS precip DSS; our sim dates are Apr 2026. Demo is coastal-only.
- **USE_LOCAL_SOURCE = True**: Still set for dev testing. Must toggle to False before committing.

## Open Items

- [ ] HEC-RAS 5.0.7 simulation running (~568K cells, 48hr sim) — ETA 2-6 hours from 16:48 CDT
- [ ] Once complete: verify Steps 9-11 produce results (boundary verification, interior, AEP comparison)
- [ ] Toggle `USE_LOCAL_SOURCE = False` in cell `a1000001-0001-0001-0001-000000000002` before commit
- [ ] Commit notebook changes to `feat/ras-calibrate` branch

## Next Steps (in order)

1. Check `working/notebook_runs/917_stofs3d_507_20260419/917_executed.ipynb` for results
2. If Steps 9-11 show "skipped": check if HDF path issue (eBFE Output/Output/ vs Input/Input/)
3. Set `USE_LOCAL_SOURCE = False`, clear outputs, commit

## Constraints Discovered

- HEC-RAS 6.x CANNOT use .g01.hdf preprocessed with 5.07 — crashes on load
- HEC-RAS 6.5 touches ALL plan files on project open (version migration) — corrupts files for 5.07
- eBFE terrain HDF is 3.6 MB (tiled format, not raw DEM) — sufficient for computation but not for re-preprocessing
- .blf files are binary; old content persists if HEC-RAS doesn't overwrite (misleading timestamps)
- `RasPlan.update_simulation_date()` writes `HHMM` format (no colon); original eBFE used `HH:MM`

## Context Clues for Future Sessions

- eBFE project path: `examples/example_projects/ebfe/NorthGalvestonBay_12040203/RAS Model/RAS_Submittal/Input/Input/`
- Terrain at: `...RAS_Submittal/Terrain/Terrain/Terrain.hdf` (3.6 MB)
- Pre-run AEP results at: `...RAS_Submittal/Output/Output/NGB.p01.hdf` (1.23 GB, from FEMA delivery)
- ras-commander may not find HDF results for eBFE models — `plan_df` scans Input/Input/ not Output/Output/
- Notebook runner artifacts at: `examples/working/notebook_runs/917_stofs3d_507_20260419/`
- HEC-RAS versions installed: 4.1.0, 5.0-5.0.7, 6.0-6.6, 7.0
