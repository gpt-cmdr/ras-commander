# eBFE Validation Matrix Completion Plan

Date: 2026-04-29

Source of truth: `VALIDATION_MATRIX.md`

Physical workspace: `H:\Testing\eBFE Model Organization`

## Objective

Complete the validation matrix by converting each actionable gap into canonical
evidence, and by explicitly documenting the gaps that cannot be resolved from
the delivered eBFE data without manual repair, full hydraulic recomputation, or
new source data.

The matrix is allowed to contain non-checkmark statuses when they are precise:
`N/A` for not-delivered/not-applicable HMS, `Not Provided in Source` for missing
full hydraulic outputs, and `Blocked` for known manual/model repair items.

## Decisions Now Encoded In The Matrix

1. HMS gaps for RAS-only deliveries are `N/A`, not `-`.
2. Missing hydraulic result HDFs are `Not Provided in Source`, not a failed
   organization state.
3. If geometry-preprocessor evidence is clean and outputs are missing, the
   model should be called `Ready for Re-Run`.
4. Amite WA4 is omitted from current demos/notebooks and remains `Blocked`
   until a manual terrain rebuild in HEC-RAS 5.0.7/RASMapper or a 6.x mesh
   upgrade is completed.
5. Do not run full unsteady/steady hydraulic computations as part of this
   matrix cleanup unless explicitly approved; geometry preprocessor validation
   remains the required execution gate.

## HMS Evidence

A subagent report review confirmed the RAS-only classification for:

| Project | HUC8 | HMS Matrix Status | Evidence Basis |
|---|---:|:---:|---|
| Spring Creek | 12040102 | `N/A` | `audit_summary.json/md` and README report no delivered `.hms` project. |
| Lower Colorado-Cummins sample | 12090301 | `N/A` | `audit_summary.json/md` and README report no delivered `.hms` project. |
| Rio Hondo | 13060008 | `N/A` | `audit_summary.json/md` reports `not_delivered`; flow data is in RAS steady flow files. |
| Upper Guadalupe | 12100201 | `N/A` | `audit_summary.json/md` reports `not_delivered`; meteorology/losses are handled in RAS `.u##` files. |
| Eleven Point | 11010011 | `N/A` | `e2e_delivery_audit_20260427_151734.md/json` reports `not_delivered`. |
| Spring River | 11010010 | `N/A` | `e2e_delivery_audit_20260427_181627.md/json` reports `not_delivered`. |
| Lower Brazos | 12070104 | `N/A` | `audit_summary.json` and clean cached E2E audit report `not_delivered`; README wording is weaker but not contradictory. |
| Amite | 08070202 | `N/A` | README/audit report HMS boundary conditions are delivered as DSS inputs, not a separate HMS project. |
| Tickfaw | 08070203 | `N/A` | `audit_summary.json/md` reports no delivered `.hms` project. |

Common audit phrase to preserve in notes:

```text
HMS Status: not_delivered (0 project file(s), 1 file(s))
No .hms project was delivered; HMS Model/ contains documentation only.
```

North Galveston Bay and Lake Maurepas remain `✓` for HMS because real `.hms`
projects were organized and loaded through hms-commander.

## Current Gap Inventory

| Project | Remaining Gap | Disposition | Completion Plan |
|---|---|---|---|
| Spring Creek | Precomputed result preservation follow-up | Actionable | Verify organized `Spring.p02.hdf` against source archive if exact source-equivalent output preservation is required. |
| Lower Colorado-Cummins sample | Notebook Updated | Actionable | Re-run `examples/430_1d_channel_capacity_analysis.ipynb` against `RAS_COMMANDER_EBFE_ROOT`, or create a compact dedicated validation notebook if `430` is not the canonical evidence notebook. |
| Upper Guadalupe | UPGU4 geometry preprocessor | Actionable but long-running | Re-run UPGU4 from the preserved `H:\` path with detailed ras-commander logging and at least a 4-hour timeout. |
| Eleven Point | Notebook Updated | Actionable | Add and execute a small 2D, HEC-RAS >6.2 validation notebook. |
| Spring River | Notebook Updated | Actionable | Add and execute a Spring River notebook that clearly differentiates it from Spring Creek and documents the legacy `Land Classification` compatibility copy. |
| Lower Brazos | Results Resolved, Notebook Updated | Results not provided; notebook actionable | Keep results `Not Provided in Source`; add a gap-aware notebook validating organization, MA03 mesh repair, CRS/path audit, and geometry-preprocessor evidence. |
| Amite | Path Audit, Geometry Preprocessor, Results Resolved, Notebook Updated | WA4 blocked; non-WA4 models actionable | Keep WA4 `Blocked`; mark outputs `Not Provided in Source`; create a notebook using WA1, WA2, WA3, and WA5 only after confirming the non-WA4 audit path status. |
| Lake Maurepas | Results Resolved | Not provided in source | Keep `Not Provided in Source`; existing notebook already documents preprocessor-only HDF and Ready for Re-Run status. |

## Workstream 1: Refresh Canonical Audit

Run the HMS-aware delivery audit after the latest matrix/organizer updates:

```powershell
$env:PYTHONPATH=(Get-Location).Path
C:\GH\ras-commander\.venv\Scripts\python.exe scripts\ebfe_delivery_audit.py --report-root "H:\Testing\eBFE Model Organization\Validation\ebfe_delivery"
```

Acceptance criteria:

| Check | Expected |
|---|---|
| `audit_summary.json` includes every matrix project | Yes |
| RAS-only projects have explicit `hms_status: not_delivered` | Yes |
| North Galveston Bay and Lake Maurepas have `hms_status: validated` | Yes |
| Spring River still shows 1 preprocessor pass and 0 failures | Yes |
| Lower Brazos still shows 3 preprocessor passes and 0 failures | Yes |
| Amite non-WA4 projects have no unresolved local path/DSS issues | Yes, before notebook publication |

Matrix action:

1. Refresh exact evidence paths and timestamps.
2. Keep HMS statuses as `N/A` for confirmed RAS-only deliveries.
3. Promote Amite Path Audit to `✓` only if the latest audit proves non-WA4
   runnable projects are clean and WA4 is clearly isolated as the blocked item.

## Workstream 2: Geometry Preprocessor Gaps

### Upper Guadalupe UPGU4

Run only UPGU4 from the preserved `H:\` path with detailed logging:

```powershell
$env:PYTHONPATH=(Get-Location).Path
C:\GH\ras-commander\.venv\Scripts\python.exe scripts\ebfe_geometry_preprocessor_batch.py --study upper-guadalupe --project-filter UPGU4 --max-wait 14400 --clear-geompre --output-dir "H:\Testing\eBFE Model Organization\Validation\ebfe_delivery\preprocessor_validation\upper_guadalupe_upgu4_retry" --verbose
```

If it is still making progress near 4 hours, rerun with a longer timeout rather
than declaring failure.

Acceptance criteria:

| Check | Expected |
|---|---|
| UPGU4 geometry preprocessor report exists | Yes |
| Compute messages parsed from ras-commander log/report | Yes |
| Errors | 0 |
| Blocking warnings | None, or documented as non-blocking |
| Matrix update | Upper Guadalupe Geometry Preprocessor `✓` |

### Amite WA4

WA4 is not part of the current runnable notebook/demo set.

Known blocking message:

```text
RasGeomWriter
ERROR: Incorrect Type in ./Projection. (Expected String)
```

Required future repair:

1. Open WA4 in HEC-RAS 5.0.7/RASMapper and manually rebuild/repair terrain, or
   upgrade/repair the mesh so it runs in 6.x.
2. Confirm terrain and projection are linked locally in the WA4 RAS project.
3. Save the project and rasmap.
4. Run targeted WA4 preprocessor through ras-commander with detailed logging:

```powershell
$env:PYTHONPATH=(Get-Location).Path
C:\GH\ras-commander\.venv\Scripts\python.exe scripts\ebfe_geometry_preprocessor_batch.py --study amite --project-filter WA4 --plan 08 --max-wait 7200 --clear-geompre --output-dir "H:\Testing\eBFE Model Organization\Validation\ebfe_delivery\preprocessor_validation\amite_wa4_manual_terrain_rebuild" --verbose
```

Until this happens, keep Amite Geometry Preprocessor as `Blocked` and make all
Amite notebooks explicitly omit WA4.

## Workstream 3: Results And Ready-For-Re-Run Status

### Lower Brazos

Current state: LB_MA01, LB_MA02, and LB_MA03 pass the geometry preprocessor.
MA03 is missing at least the referenced `MA_3.p01.hdf`.

Plan:

1. Keep Results Resolved as `Not Provided in Source`.
2. Do not recompute full hydraulic plans in this pass.
3. Document that the organized projects are Ready for Re-Run because
   geometry-preprocessor evidence is clean.
4. Ensure the Lower Brazos notebook does not advertise results-ready status.

### Lake Maurepas

Current state: the source archive scan found 0 RAS plan-result HDFs, and the
local `Lake_Maurepas.p02.hdf` is compute-message/preprocessor-only.

Plan:

1. Keep Results Resolved as `Not Provided in Source`.
2. Keep the existing notebook statement that full hydraulic outputs are absent.
3. Document Ready for Re-Run because the geometry preprocessor passed.

### Amite

Current state: WA1, WA2, WA3, and WA5 have clean preprocessor evidence; WA4 is
blocked; outputs should not be treated as source-provided full results.

Plan:

1. Keep Results Resolved as `Not Provided in Source`.
2. Document Ready for Re-Run only for the non-WA4 models with clean
   preprocessor evidence.
3. Do not run full hydraulic plans in this pass.

## Workstream 4: Notebook Completion

Create or update notebooks so demonstrations use the upgraded delivery format
and do not depend on stale local folder assumptions.

| Notebook | Purpose | Depends On |
|---|---|---|
| `examples/430_1d_channel_capacity_analysis.ipynb` or `examples/956_ebfe_lower_colorado_validation.ipynb` | Close Lower Colorado-Cummins notebook evidence | Existing Lower Colorado organized delivery and preprocessor evidence |
| `examples/956_ebfe_eleven_point_validation.ipynb` | Small 2D HEC-RAS >6.2 example | Existing Eleven Point audit and preprocessor evidence |
| `examples/957_ebfe_spring_river_validation.ipynb` | Spring River validation and naming distinction from Spring Creek | Existing Spring River audit and 6.1 preprocessor evidence |
| `examples/958_ebfe_lower_brazos_validation.ipynb` | Lower Brazos organization, MA03 mesh repair, CRS/path audit, and preprocessor evidence | Existing Lower Brazos clean E2E evidence |
| `examples/959_ebfe_amite_validation.ipynb` | Amite non-WA4 validation with WA4 explicitly blocked | Clean non-WA4 audit/path status and existing WA1/WA2/WA3/WA5 preprocessor evidence |

Notebook acceptance criteria:

1. Use `RAS_COMMANDER_EBFE_ROOT`, defaulting to
   `H:\Testing\eBFE Model Organization`.
2. Call `RasEbfeModels.organize_model(...)` rather than manually constructing
   delivery paths.
3. Verify local RAS/HMS folders, rasmap, projection, DSS inputs, terrain, land
   cover, and result HDF status as applicable.
4. Point to canonical audit/preprocessor evidence instead of rerunning long
   model computations during normal notebook execution.
5. Be executed and committed with outputs included.
6. Clearly label `Not Provided in Source`, `Ready for Re-Run`, and `Blocked`
   statuses where applicable.

## Workstream 5: Spring Creek Result Preservation

Goal: close the remaining Spring Creek follow-up if exact original output
preservation is needed.

Steps:

1. Locate the source Spring Creek result HDF in `Downloads`.
2. Compare size, modified time, and preferably hash against the organized
   `Organized\SpringCreek_12040102\RAS Model\Spring.p02.hdf`.
3. If the organized file is preprocessor-only or differs without explanation,
   restore the source result HDF.
4. Re-run the delivery audit for Spring Creek.
5. Update the Critical Data Gaps row to `✓` if preservation is confirmed.

## Workstream 6: Verification And Commit

After each evidence-producing task:

1. Update `VALIDATION_MATRIX.md` with exact report paths.
2. Refresh `Last updated`.
3. Keep non-checkmark cells only where Evidence / Notes explains why.
4. Run targeted tests:

```powershell
$env:PYTHONPATH=(Get-Location).Path
C:\GH\ras-commander\.venv\Scripts\python.exe -m pytest tests\test_ebfe_amite.py tests\test_ebfe_spring_river.py tests\test_ebfe_lower_brazos.py tests\test_ebfe_tickfaw.py tests\test_geom_preprocessor.py -q
```

5. Run `git diff --check`.
6. Commit in small batches:
   - Matrix/audit bookkeeping.
   - UPGU4 and Amite non-WA4 validation repairs.
   - Notebook updates.

## Proposed Execution Order

1. Refresh the delivery audit and confirm matrix statuses still match evidence.
2. Complete Spring Creek result preservation check.
3. Validate Lower Colorado notebook status.
4. Run Upper Guadalupe UPGU4 preprocessor with a 4-hour timeout.
5. Confirm Amite non-WA4 path/DSS audit status.
6. Create and execute Eleven Point and Spring River notebooks.
7. Create and execute Lower Brazos notebook as gap-aware for missing results.
8. Create and execute Amite notebook using WA1, WA2, WA3, and WA5 only, with
   WA4 marked `Blocked`.
9. Final audit refresh, final matrix update, targeted tests, commit, push.

## Final Acceptance Criteria

The validation matrix is complete when:

1. Every actionable cell is `✓` with an evidence path.
2. Every `N/A` cell cites source/audit evidence that the item was not delivered
   or is not applicable.
3. Every `Not Provided in Source` cell identifies the missing outputs and says
   whether the project is Ready for Re-Run.
4. Every `Blocked` cell identifies the required manual repair or model upgrade.
5. Current audit summary has no unexpected issues.
6. All eBFE notebooks intended as canonical examples execute with the upgraded
   delivery format and committed outputs.
7. Targeted eBFE tests pass.
