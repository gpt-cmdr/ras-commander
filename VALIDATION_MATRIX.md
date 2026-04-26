# eBFE Model Organization Validation Matrix

Canonical repository record for eBFE projects that can be relied upon for
functional HEC-RAS examples, studies, demonstrations, and regression testing.

Physical data workspace: `H:\Testing\eBFE Model Organization`

Last updated: 2026-04-26 13:56:59 -04:00

Legend: `✓` = canonical evidence exists; `-` = not yet completed or not applicable.

| eBFE Project | HUC8 | Retrieved | Extracted | Organized | Path Audit | Geometry Preprocessor | Results Resolved | Notebook Updated | Evidence / Notes |
|---|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| Spring Creek | 12040102 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Organized at `Organized\SpringCreek_12040102`; preprocessor report `Validation\ebfe_delivery\preprocessor_validation\geometry_preprocessor_validation_20260424_092433.json`. |
| Lower Colorado-Cummins sample | 12090301 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | - | Organized at `Organized\LowerColoradoCummins_12090301`; sample reach preprocessor included in `geometry_preprocessor_validation_20260424_074233.json`. |
| Rio Hondo | 13060008 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Organized at `Organized\RioHondo_13060008`; 253 1D steady projects passed preprocessor in `geometry_preprocessor_validation_20260424_074233.json`; 253/253 steady plans computed successfully in `steady_plan_validation_20260424_160022.json`; notebook `examples/953_ebfe_rio_hondo_steady_collection.ipynb` added. |
| North Galveston Bay | 12040203 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Organized at `Organized\NorthGalvestonBay_12040203`; latest E2E preprocessor report `geometry_preprocessor_validation_20260424_144208.json`. |
| Upper Guadalupe | 12100201 | ✓ | ✓ | ✓ | ✓ | - | ✓ | ✓ | Organized at `Organized\UpperGuadalupe_12100201`; UPGU1-3 passed under 3600s in working E2E evidence. UPGU4 background rerun `geometry_preprocessor_validation_20260424_155633.json` timed out after 7200 seconds from a UNC-expanded path with no compute messages, so UPGU4 still needs a clean `H:\` path rerun and possibly a longer timeout. |
| Lower Brazos | 12070104 | ✓ | - | - | - | - | - | - | Deferred; inventory/manifest shell created in `Working\ebfe_e2e\LowerBrazos_12070104`; full LB_MA01/LB_MA02/LB_MA03 component downloads remain pending. |
| Amite | 08070202 | ✓ | ✓ | ✓ | - | - | - | - | Organized at `Organized\Amite_08070202`; E2E audit `e2e_delivery_audit_20260424_175716.json` found 5 RAS projects. WA1, WA2, and WA3 passed clean `H:\` ras-commander geometry-preprocessor confirmation in `geometry_preprocessor_validation_20260425_205058.json`, `geometry_preprocessor_validation_20260425_205124.json`, and `geometry_preprocessor_validation_20260425_205142.json`. WA5 was repaired by assigning EPSG:3452 / LA South projection and rebuilding terrain with ras-commander; it passed HEC-RAS 5.0.7 preprocessor on plan 01 in `geometry_preprocessor_validation_20260426_130123.json`. WA4 remains blocked: ras-commander and GUI preprocessor attempts still fail with `RasGeomWriter` / `ERROR: Incorrect Type in ./Projection. (Expected String)` after terrain rebuild attempts, so WA4 requires manual terrain rebuild inside RASMapper before preprocessor validation can complete. |
| Tickfaw | 08070203 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | - | Organized at `Organized\Tickfaw_08070203`; E2E audit `e2e_delivery_audit_20260424_190917.json` found 1 project, 0 issues, and 7 plan HDFs. Preprocessor report `geometry_preprocessor_validation_20260424_185812.json` passed plan 13 / geometry 05 in 662.9 seconds with 0 errors and 0 warnings. HUC is listed as `Tickpaw` in EPA NHDPlus/WBD references. |
| Lake Maurepas | 08070204 | ✓ | ✓ | ✓ | ✓ | ✓ | - | - | Organized at `Organized\LakeMaurepas_08070204`; E2E audit `e2e_delivery_audit_20260425_205227.json` found 1 Hydraulics RAS project, 7 plans, rasmap present, 7 documentation files, and 0 audit issues. HEC-RAS 5.0.7 geometry preprocessor passed plan 02 / geometry 01 in 256.1 seconds through ras-commander; evidence `Validation\ebfe_delivery\preprocessor_validation\lake_maurepas\geometry_preprocessor_validation_20260426_134751.json`. The preprocessor wrote local geometry artifacts and `Lake_Maurepas.p02.hdf` compute messages, but full hydraulic result HDF validation remains unresolved. |

## Critical Data Gaps / Follow-Up Items

| Item | Status | Required Action |
|---|:---:|---|
| Upper Guadalupe UPGU4 preprocessor evidence | - | Re-run geometry preprocessor from the preserved `H:\` path. The previous background run used a UNC-expanded path and timed out after `max_wait=7200` with no compute messages, so consider a longer controlled timeout if the confirmed successful GUI run exceeds two hours. |
| Lower Brazos component archives | - | Download and extract LB_MA01, LB_MA02, and LB_MA03 to `Downloads`, then organize and validate each project. |
| Amite WA4 terrain/coverage gap | - | WA4 no longer fails due to missing land cover or missing plan 01, and independent diagnostics found the LA South terrain source overlaps the WA4 2D mesh. However, controlled ras-commander and GUI preprocessor attempts still fail with `RasGeomWriter` / `ERROR: Incorrect Type in ./Projection. (Expected String)` after automated terrain rebuild attempts. Mark WA4 as requiring a manual terrain rebuild/repair inside RASMapper before preprocessor validation can complete. |
| Tickfaw validation queue | ✓ | Completed download, extraction, organization, audit, and ras-commander geometry preprocessor validation. Notebook/demo updates remain pending. |
| Lake Maurepas validation queue | ✓ | Download, extraction, organization, path audit, and ras-commander geometry preprocessor validation completed. Full hydraulic result HDF validation remains separate from the delivery-format preprocessor gate. |
| Spring Creek precomputed result preservation | - | Verify `Spring.p02.hdf` against the source archive if exact original precomputed outputs must be preserved. |
| Notebook default paths | ✓ | Updated eBFE notebooks 950-953 and eBFE validation docs to use `RAS_COMMANDER_EBFE_ROOT` with default `H:\Testing\eBFE Model Organization`; preprocessor notebook gates now use a 7200-second timeout. |

## Current Workspace Layout

| Folder | Purpose |
|---|---|
| `Downloads` | Raw downloaded archives, extracted source deliveries, and URL manifests. |
| `Organized` | Delivery-format RAS/HMS projects intended for demos and notebooks. |
| `Validation` | Audit summaries, geometry preprocessor reports, and delivery-format evidence. |
| `Working` | E2E scratch outputs and comparison runs retained for traceability. |
