# 710 Manning's Sensitivity Follow-Up

Date: 2026-07-07

Status: **Closed as of 2026-07-10.** PR #272 repaired the land-cover
association, reran notebook 710, and demonstrated a nonzero hydraulic response.
The findings below describe the pre-fix run and are retained as validation
history, not as an open work item.

## Context

Notebook `examples/710_mannings_sensitivity_bulk_analysis.ipynb` was included in
the merged sensitivity notebook refresh (`997d5ca3`, PR #265). During independent
notebook review, the executed notebook was marked **REVISE** because the min,
current, and max Manning's n scenarios did not show a measurable hydraulic
response at the selected point.

This document records the issue so it can be addressed in a focused follow-up
instead of being lost in the PR 260 cleanup stream.

## Evidence From Review

The notebook successfully:

- migrated deprecated `RasGeo` Manning's n calls to `GeomLandCover` APIs;
- cloned the current plan/geometry into min and max roughness scenarios;
- wrote distinct base and regional Manning's n tables for current, minimum,
  and maximum scenarios;
- reran the baseline and min/max plans; and
- suppressed noisy INFO logging in committed notebook output.

However, the hydraulic result comparison did not demonstrate sensitivity:

- selected-cell maximum WSE was `945.89 ft` for current, minimum, and maximum
  scenarios;
- full-domain `HdfResultsMesh.get_mesh_max_ws()` comparison across all 5,765
  mesh cells showed `0.0 ft` max-minus-min difference;
- `HdfResultsMesh.get_mesh_max_face_v()` comparison across 11,164 faces also
  showed zero difference; and
- geometry HDF calibration tables differed, but the `Cells Center Manning's n`
  dataset remained uniformly `0.06` across current, min, and max geometry HDFs.

## Recommended Follow-Up

Do not treat notebook 710 as a completed hydraulic sensitivity example until a
follow-up proves a measurable model response.

Preferred options:

1. Update the workflow so geometry preprocessing propagates the changed land
   cover calibration values into the 2D-cell Manning's n data used by the run,
   then rerun and independently review the notebook.
2. If the Muncie plan is genuinely insensitive to the demonstrated roughness
   edits, switch to a project/plan/output location where the sensitivity is
   hydraulically visible.
3. If the example is intended only to demonstrate input editing mechanics,
   retitle/rewrite it as a Manning's n bulk-edit verification notebook rather
   than a hydraulic sensitivity notebook.

## Validation Needed For Closure

A closure PR should include:

- executed notebook outputs with no tracebacks or warning spam;
- a quantitative comparison showing a nonzero hydraulic response, such as max
  WSE, depth, velocity, or another defensible quantity;
- a map or table identifying where the response occurs; and
- independent notebook-review PASS.
