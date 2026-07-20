# Qualification and implementation plan

## 0. Make every Windows/Wine launch legally fail-closed

Code status: implemented, covered by focused tests, and live-qualified against
the actual product TCU. The implementation:

- remove the first-button fallback from `DialogWatchdog`;
- add shared TCU/legal-modal classification and structured blocking records;
- terminate only the affected process tree when blocked;
- fail before launch when pywin32 or psutil modal supervision is unavailable;
- verify termination rather than treating access-denied or surviving children
  as success;
- make scan-thread failures structured blockers and preserve per-plan errors in
  parallel results;
- fix `GeomPreprocessor.geometry_only` so `Run UNet=0` matches its documented
  behavior; and
- add unit tests for TCU, unknown dialogs, safe known informational dialogs,
  process termination, and restoration of plan flags.

Suggested tests:

- `tests/test_ras_dialog_watchdog.py`
- additions to `tests/test_rascmdr_compute_plan_control_flow.py`
- additions to `tests/test_geom_preprocessor.py`
- a qualification action that proves zero assent clicks and zero surviving
  processes.

The original focused watchdog, preprocessing, compute-control, and plan-number
regressions pass 44 tests. The acceptance-state/watchdog set passes 68 focused
tests plus seven private receipt-content tests. Live evidence includes the 15
installed stable native 4.x–7.x builds and four reversible Wine 7.0.1 prefix
clones plus one persistent disposable diagnostic. The installed 6.7 beta builds
are separate optional evidence and require distinct beta authorization. All
probe cases used zero interactions, terminated their tracked process trees, and
left no survivors; the reversible cases restored state. The earlier persistent
candidate is not template-promotion evidence. This closes TCU detection safety
for those exact builds, but not a vendor-supported headless acceptance
interface, stable cross-version Wine qualification, or the operation-specific
unknown-dialog inventory for all Mapper workflows. The supported compatibility
workflow now uses an exact-version, user-visible TCU session with zero automated
UI input and exactly two post-session restart probes.

## 1. Add a first-class native Linux engine API

Add a ras-commander API that owns discovery, identity, staging, execution,
timeouts, logs, cleanup, and content verification for the official engines.
The name can be decided during implementation; the API must expose distinct
operations rather than one ambiguous preprocess call:

- inspect/stage an official engine installation;
- prepare a Results-free `.p##.tmp.hdf` without destroying the source;
- run native `RasGeomPreprocess` with the exact `x##` token;
- run native `RasUnsteady`;
- run native `RasSteady`; and
- return structured result objects with executable hashes, arguments, timing,
  logs, produced-file hashes, and semantic content checks.

Required behavior:

- fail if a requested engine is absent; never warn and continue;
- one node-local project copy per job;
- no shared writable HDF or `io.*` namespace;
- bounded process-tree termination;
- exact version/component identity;
- explicit input contract by version;
- no acceptance based only on return code; and
- no proprietary binaries committed to the repository.

Then route `RasCmdr.compute_plan_linux()` through that lower-level API instead
of maintaining a separate partial implementation.

## 2. Separate preparation capabilities

Represent these capabilities independently in code and receipts:

| Capability | Expected backend |
|---|---|
| Project/plan artifact preparation (`.b##`, `.x##`, `.tmp.hdf`) | Version-dependent; native where proven, otherwise native Windows/Wine fallback |
| 1D cross-section/structure HTAB update | Official native `RasGeomPreprocess` |
| 2D mesh topology authoring | RAS Mapper on Windows; Wine fallback under qualification |
| 2D terrain-derived cell/face tables | RAS Mapper on Windows; Wine gap investigation |
| Flow solve | Official native Linux engine |

Do not label all five operations *geometry preprocessing*.

In ras-agent, replace or decompose the current `preprocess_mode` model. A mode
called `linux` must not imply raw 2D preparation if it only copies an existing
plan HDF and runs the 1D preprocessor. Rename `windows` to something like
`precompiled` when its runtime meaning is simply “compiled tables already
exist.” Keep `pure_python` explicitly screening-only.

## 3. Build the fixture ladder

All real-product tests use immutable source fixtures, disposable per-test
copies, exact engine hashes, and retained failure bundles.

### Fixture A: official Muncie engine contract

Test the documented 6.6 input contract, then empirically verify the installed
7.0.1 engine artifacts against the same staged-file contract:

- stage `.b##`, `.x##`, and Results-free plan HDF;
- run native `RasGeomPreprocess`;
- inspect the exact HDF paths/datasets it changes;
- prove which changes are 1D HTAB versus any 2D tables;
- run native `RasUnsteady`; and
- compare to a native-Windows golden using volume error, selected hydrographs,
  WSE, and result-HDF semantic fingerprints.

### Fixture B: fast 1D Bald Eagle

Use this as the primary native `RasGeomPreprocess` regression. Mutate a known
cross section/HTAB input, run the engine, and check exact table dimensions,
station order, structures, and selected numerical values before solving.

### Fixture C: Weise_2D minimal gap probe

Start from a raw/disposable project and record exactly which artifacts each
stage produces. This is the quickest way to prove that native
`RasGeomPreprocess` does or does not populate missing 2D cell/face property
tables for the installed 7.0.1 artifact.

### Fixture D: BaldEagleCrkMulti2D

Exercise mesh regeneration, breaklines, refinement regions, terrain and land
cover, table completeness, solve, restart, locking, and concurrency.

### Fixture E: Spring Creek promotion

Only after A-D pass, run the representative BLE model and compare the official
native Linux solve to the native-Windows golden. This is the promotion gate for
HPC ensembles.

## 4. Close the Wine 2D property-table gap

Keep this work bounded and evidence driven:

1. Establish a native-Windows content golden for the smallest 2D fixture.
2. Capture process/thread/module and dependency evidence for
   `ComputePropertyTablesCommand` on native Windows and pinned single-CPU Wine.
3. Test the narrowest official Windows component capable of the operation;
   avoid the full `CompleteGeometry` pipeline when a narrower product command
   exists.
4. Supervise the call out of process with a hard timeout and a transactional
   HDF copy.
5. Accept only complete cell **and** face tables with exact dimensions,
   terrain/geometry fingerprints, monotonic curves, finite values, and native
   Windows comparison.
6. If the Windows component cannot be made deterministic under Wine, keep 2D
   preparation on the Windows workstation and distribute only qualified,
   immutable geometry packages to Linux/HPC.

Do not substitute the ras-agent pure-Python tables for the production tables.
They may support a separately labeled screening experiment.

## 5. Update the qualification runner

Split the current plan actions into backend-aware stages:

- `plan.prepare_inputs`
- `geometry.preprocess_1d_linux`
- `geometry.property_tables_2d_windows_or_wine`
- `plan.compute_unsteady_linux`
- `plan.compute_steady_linux`

The native Windows and Wine receipts should compare preparation content. The
native Windows and native Linux receipts should compare solve content. A single
Windows-versus-Wine whole-run comparison is no longer the correct production
architecture.

Every critical private-run test must fail, not skip, when its engine, fixture,
golden, or tolerance file is missing.

## 6. Acceptance metrics

### Preparation

- exact cells, faces, and boundary assignments;
- exact breakline/refinement counts and parameters;
- complete cell and face property-table coverage;
- monotonic/finite property curves;
- geometry, terrain, land-cover, infiltration, and plan fingerprints; and
- no unexplained HDF dataset or attribute differences from the golden.

### Computation

- successful completion messages and no fatal diagnostics;
- volume-accounting error within engineering-approved limits;
- selected profile-line flow hydrographs: keyed maximum absolute error, RMSE,
  peak relative error, and timing;
- selected cell WSE series: keyed maximum absolute error and RMSE;
- depth-grid wet-area overlap and raster-value tolerances; and
- restart versus continuous-run equivalence over an approved common window.

### Isolation and recovery

- unique prefix/project/output paths per scheduler task;
- no surviving engine/Wine processes;
- no residual locks or `io.*` links;
- immutable source fixture and template fingerprints;
- failed-run log and partial-content receipt; and
- safe rerun after interruption.

## 7. Documentation gate

Only after the representative tests pass should normal repository documentation
be updated to say:

- which versions have verified native engines;
- which preparation artifacts remain Windows/RAS Mapper dependent;
- which Wine operations are qualified and under what CPU/runtime pinning;
- that native Linux compute is the production solve path; and
- that HEC-RAS 2025 is a separate beta/new-product path.
