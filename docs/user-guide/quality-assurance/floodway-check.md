# Floodway Check: Experimental Steady-Flow Diagnostics

`RasCheck.check_floodways()` compares two computed steady profiles and returns
`CheckResults.messages` plus a per-section `floodway_summary`. It does not
establish regulatory compliance or hydraulic acceptance. Supply profiles from
the same model with compatible discharge, geometry, units, and boundary assumptions.
The current checker assumes **feet**; it does not convert SI results.

## Qualification and coverage

**The floodway authoring and check workflow is experimental.** Notebook 223 was
withdrawn from the example gallery pending qualification. Its historical outputs
are not evidence that the complete workflow is correct. The API remains available
for development on disposable copies, with these known limitations:

- `RasFloodway.parse_encroachments()` collapses blank fixed-width fields in legacy
  multi-profile encroachment records. Reproducing the parse on the untouched
  official Example 6 plan 02 shifts methods and target values; round-tripping
  records through the same parser is not sufficient validation.
- The checker's encroachment accessor does not read the separate `Encroachment
  Station Left` and `Encroachment Station Right` datasets under `Additional
  Variables` in the inspected Example 6 plan HDF. Width and associated structure
  checks therefore do not run for that layout.
- That accessor does not supply an `encr_method` column. Method-specific diagnostics
  listed below are implemented branches, but their detection path is unqualified;
  absence of those messages does not confirm method suitability.
- Missing results, missing profile names, unsupported datasets, and some helper
  failures can return empty or partial results. There is no complete coverage
  receipt. Verify the summary is populated and contains every expected section.
- Starting-WSE checks infer a downstream section by sorting station identifiers;
  they are screening heuristics for compatible subcritical reaches, not a general
  boundary-condition audit. Review station order and hydraulic regime explicitly.

The retained Example 6 HDF was inspected for two profiles and 24 steady result
rows during the September 2026 review. No new solver run or successful authoring
qualification is claimed by this repair. Restoring the notebook requires independent
input-record readback, complete section/profile matching, fresh solver evidence,
and review of WSE, energy, flow regime, and structure behavior. Keep source models
immutable and retain both diagnostics and the actual executed notebook outputs.

### Separate 2D authoring status

Notebook 311 was also withdrawn. Its `RasEncroachments` GIS authoring route is
separate from the steady-flow parser above. The retained HEC-RAS 6.6 run reported
completion booleans, but no native unsteady encroachment result arrays and zero
maximum-WSE differences for all 13,093 compared rows. This evidence does not
establish that the solver applied the authored regions/zones. The APIs remain
available as experimental input-authoring helpers; file/layer readback and a
completed base simulation do not qualify the hydraulic encroachment workflow.

## HEC-RAS method reference

| Method | Input / meaning | Review context |
|--------|-----------------|----------------|
| 1 | User-specified left and right encroachment stations | Used for final refinement in USACE Example 6 after trial methods; use alone is not a warning |
| 2 | Fixed top width | Review the resulting stations and hydraulic response |
| 3 | Specified percentage reduction in conveyance | Review conveyance distribution and the resulting hydraulic response |
| 4 | Target increase in water surface elevation (WSE) | Determines stations using conveyance at the raised WSE; computed rise may differ from the input target, so the user reviews successive trials |
| 5 | Target WSE increase plus maximum energy change | Iterative search; review both targets, convergence, and computed WSE/energy changes |

The method definitions follow the
[USACE Steady Flow Floodway Encroachment Analysis manual](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.3/performing-a-floodplain-encroachment-analysis/steady-flow-floodway-encroachment-analysis).
The trial-to-final Method 1 sequence is demonstrated in
[USACE Floodway Determination, Example 6](https://www.hec.usace.army.mil/confluence/rasdocs/rasappguide/latest/floodway-determination-example-6).
In particular, Method 5 is not a width-reduction target. A Method 4 target is not
itself a guaranteed computed surcharge. Method selection, target values, and
acceptance criteria remain study-specific engineering decisions.

## Configured thresholds

The public wrapper defaults to `surcharge=1.0` ft. This is a **software default**,
not a determination of the applicable limit. The legacy
`get_state_surcharge_limit()` helper returns a stored lookup (for example, `IL`
returns `0.1` and `TX` returns `1.0`); those entries have not been audited against
current state or local requirements. This page does not prescribe state limits.
Obtain the study's governing criterion and record its source before running checks.

Several fields in `ValidationThresholds.floodway` are not wired into these
predicates: `surcharge_max_ft`, `surcharge_warning_percent`,
`discharge_tolerance_percent`, `min_floodway_width_ft`, and
`acceptable_encroachment_methods`. Changing them does not change the corresponding
hard-coded screening rules below. Use the explicit surcharge argument for the
surcharge comparison. The starting-WSE difference thresholds are used.

## Message reference

The following table records the IDs and severities constructed by the public
checker's helpers, with predicates summarized from `check_floodways.py`. It is
checked against the code and `messages.py` by a focused regression test. **A listed
branch does not imply that its required input was found or the branch ran.**
`SC` uses `s = floodway WSE - base WSE` and the explicitly supplied `limit`.
All length/elevation thresholds in this table are in feet.

| ID | Severity | Implemented condition / meaning |
|----|----------|---------------------------------|
| FW_SC_01 | ERROR | `s > limit` |
| FW_SC_02 | WARNING | `s < -0.01`; negative surcharge |
| FW_SC_03 | INFO | `abs(s) < 0.005`; near-zero surcharge |
| FW_SC_04 | INFO | `s > 0` and `abs(s - limit) < 0.01`; includes either side of limit and can coexist with FW_SC_01 |
| FW_Q_01 | WARNING | Absolute discharge difference exceeds 1% of a positive base discharge |
| FW_Q_02 | WARNING | Floodway discharge exceeds 1.01 times base discharge |
| FW_Q_03 | WARNING | Adjacent sorted-section discharge change exceeds both 2% of previous positive flow and 50 cfs; inspect tributaries and losses |
| FW_EM_01 | INFO | Method 1 detected; fixed stations are not inherently unsuitable |
| FW_EM_02 | WARNING | Method is zero and both encroachment stations are missing at a non-structure section |
| FW_EM_03 | INFO | Multiple positive methods detected within a reach |
| FW_EM_04 | WARNING | No encroachment at a non-structure section; same missing-input predicate as FW_EM_02 |
| FW_EM_05 | INFO | Method 5 detected; targets are not verified by this message |
| FW_EM_06 | WARNING | Encroachment method detected at a structure; review treatment |
| FW_EM_07 | WARNING | Detected Method 4/5 inward encroachment distances beyond positive banks have an asymmetry ratio greater than 5:1 |
| FW_EM_08 | WARNING | Method 5 is detected and a read iteration limit is below 10; heuristic, not observed nonconvergence |
| FW_WD_01 | ERROR | Right minus left encroachment station is zero or negative |
| FW_WD_02 | WARNING | Left encroachment is right of a positive left bank station |
| FW_WD_03 | WARNING | Right encroachment is left of a positive right bank station |
| FW_WD_04 | WARNING | Encroachment width is less than a positive channel width |
| FW_WD_05 | WARNING | Lateral station change divided by station-identifier difference exceeds 0.10 (fallback length if parsing fails); review units/order before interpretation |
| FW_ST_01 | WARNING | Structure encroachment differs from adjacent section encroachment |
| FW_ST_02 | ERROR | Encroachment lies inside positive bridge abutment stations |
| FW_ST_03 | WARNING | Both encroachment stations are missing at a structure |
| FW_BC_02 | INFO | Slope boundary type detected |
| FW_BC_03 | INFO | Known-WSE boundary type detected |
| FW_SW_01 | INFO | Computed WSE reported at the inferred downstream section |
| FW_SW_02 | WARNING | Absolute base/floodway WSE difference exceeds `starting_wse_diff_threshold_ft` (default 0.5) |
| FW_SW_02M1 | WARNING | FW_SW_02 with Method 1 detected |
| FW_SW_02M4 | WARNING | FW_SW_02 with Method 4 detected; review trial results and boundary assumptions |
| FW_SW_02M5 | WARNING | FW_SW_02 with Method 5 detected; review both targets and boundary assumptions |
| FW_SW_03 | ERROR | Floodway WSE below the section minimum channel elevation |
| FW_SW_03M1 | ERROR | FW_SW_03 with Method 1 detected |
| FW_SW_03M4 | ERROR | FW_SW_03 with Method 4 detected |
| FW_SW_04 | INFO | Floodway WSE above the higher sampled bank elevation |
| FW_SW_04M1 | INFO | FW_SW_04 with Method 1 detected |
| FW_SW_04M4 | INFO | FW_SW_04 with Method 4 detected |
| FW_SW_05 | WARNING | Other profiles differ from floodway WSE beyond the starting-WSE threshold at the same section |
| FW_SW_05M1 | WARNING | FW_SW_05 with Method 1 detected |
| FW_SW_05M4 | INFO | FW_SW_05 with Method 4 detected |
| FW_SW_06 | WARNING | Computed Froude number is at least 1.0 at the inferred downstream section |
| FW_SW_07 | ERROR | Reported depth or WSE minus channel minimum is negative |
| FW_SW_08 | WARNING | Difference between base and floodway WSE drops over the first two sorted sections exceeds `starting_wse_computed_diff_ft` (default 1.0); does not compare against a specified boundary value |
| FW_LW_01 | WARNING | Lateral weir present; activity requires result review |
| FW_LW_02 | WARNING | Available lateral-weir flow exceeds 5% of main-channel flow |

The checker also delegates permanent ineffective-flow screening to the structure
checker (`ST_IF_05`). Additional `FW_ST_*` templates exist in `messages.py`, but the
separate extended structure helper is not called by this public entry point.
`FW_DC_*` and the formerly described asymmetric-width/discontinuity IDs were
incorrect documentation, not emitted messages from this implementation.

## Interpreting diagnostics

A negative surcharge can involve changes in losses, flow regime, boundary
conditions, or numerical behavior; it is not automatic permission to narrow the
floodway. Near-zero surcharge is likewise not a certificate of a conservative
or acceptable result. Review the matched profiles and diagnostics together.

A higher floodway downstream WSE can be intentional. USACE Example 6 uses a
one-foot higher floodway starting WSE to represent downstream encroachment.
Therefore, a starting-WSE difference is a review flag; enforcing identical values
would not reproduce that example. Review reach extent, downstream assumptions,
structures, transitions, and the computed energy/WSE profiles.

## Running the available checks

```python
from pathlib import Path
from ras_commander.check import RasCheck, create_custom_thresholds

# Replace with your HDFs and exact computed profile names.
plan_hdf = Path("working/model.p01.hdf")
geom_hdf = Path("working/model.g01.hdf")
review_limit_ft = 1.0  # Example configuration; establish the study criterion first.
thresholds = create_custom_thresholds({
    "floodway.starting_wse_diff_threshold_ft": 0.5,
})
results = RasCheck.check_floodways(
    plan_hdf, geom_hdf,
    base_profile="PF#1",
    floodway_profile="PF#2",
    surcharge=review_limit_ft,
    thresholds=thresholds,
)
if results.floodway_summary.empty:
    raise RuntimeError("No matched profile evidence; floodway review is incomplete")
print(results.floodway_summary)
for message in results.messages:
    print(message.message_id, message.severity.value, message.message)
# Independently compare expected section identities with the summary.
# Messages and populated rows do not establish complete check coverage.
```

The public `RasCheck` wrapper accepts **`surcharge`**. The lower-level
`CheckFloodways.check_floodways()` and `RasFloodway.check_floodways()` accept
**`surcharge_limit`**; use the keyword belonging to the called API.
