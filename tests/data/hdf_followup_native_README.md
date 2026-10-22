# Native follow-up controls

`hdf_followup_native_manifest.json` pins eight externally retained HEC-RAS
result files and their source plan, flow, geometry-text and project snapshots.
The public repository contains hashes and tests; it does not contain model data.

Set `RAS_HDF_FOLLOWUP_FIXTURE_ROOT` to the directory containing the case folders,
then run:

```sh
python -m pytest tests/test_hdf_followup_native_contract.py -q
```

Without that variable, the tests skip explicitly. A configured missing or changed
fixture fails. CI collection without fixtures is not native qualification.
All tests open retained files read-only and never execute HEC-RAS.

## Native generation and observations

The controls were computed on 2026-10-22 from public Ether Hollow and Bald Eagle
Creek examples with HEC-RAS 6.6 and 7.0.1. Each run used an isolated project copy,
an explicit runtime, two requested cores, `RasCmdr.compute_plan()` and a six-minute
wall-clock limit. Native execution receipts and complete projects are retained
with the external corpus. Source projects were preserved.

| Control, per version | Configuration | Observed result |
|---|---|---|
| Ether Hollow off-cadence | 17 minutes; five-minute output | Native completion; output at minutes 0, 5, 10 and 15 |
| Ether Hollow aligned | 20 minutes; five-minute output | Native completion; output includes minute 20 |
| Bald Eagle zero control | Two hours; five-minute output | 25 computed zero-flow samples; distinct observed constant series |
| Bald Eagle active control | Five hours; five-minute output | 61 computed samples including negative discharge; distinct observed constant series |

The Ether Hollow controls use Bingham settings with user viscosity 100 and yield
strength 700. Both versions store `Face Mixture Dynamic Viscosity` with
`Location=Faces`, `Columns=Faces` and units `lb/ft^2*s`, but its width is 10,647
stored cells rather than 20,797 faces. Both store the constant raw value
4788.02490234375. These observations establish a contradiction; they establish
neither a corrected physical domain nor a unit conversion. The tests require
typed eager, lazy and streamed reads to reject the contradiction. Yield and
viscous stress retain independent exact-array comparisons in all three modes.

The Bald Eagle controls use the existing native reference line `RL_Mid` and
observed constant discharge 12,345 cfs. `RasFlowOptimization.set_settings()`
authors the observed series in the unsteady file; `disable_plan()` then removes
optimization controls while preserving that series. Regular `RasCmdr` execution
produces both observed Event Conditions and computed Reference Lines/Flow.
The tests compare the public reader directly against the computed matrix, its
own output clock and units. They separately verify the observed two-point clock,
identity and values. Signed/absolute and truncated/untruncated reads are covered.
An all-zero profile-flow series remains intact with `truncate=False` and becomes
empty with `truncate=True`, following the existing profile-flow contract.

## Interpretation limits

`HdfCompletion.inspect_time_coverage()` reports literal stored-clock coverage.
It correctly reports `not_covered` for these completed off-cadence runs. Such a
result alone must not be promoted to an execution-failure decision. General
cadence-aware completion policy, irregular schedules and other versions remain
separate qualification work.

These are reader and file-format controls. Native completion does not establish
hydraulic convergence, calibration or engineering acceptance. Viscosity remains
unsupported pending independent physical-domain and unit evidence; the tests do
not reinterpret it or change production completion policy.
