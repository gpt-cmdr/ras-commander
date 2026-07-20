# HEC-RAS 7.0.1 Windows-under-Wine qualification research and implementation

Date: 2026-07-16

## Decision status

**The full Windows-under-Wine lane remains unqualified, but three bounded RAS
Mapper slices now pass exact native-Windows/Wine content parity.** Actual
HEC-RAS 7.0.1 binaries pass the cumulative Bald Eagle mesh sequence, the Muncie
projection/multi-source-terrain sequence on one logical CPU, and WSE/depth/
velocity Mapper layer/export compatibility on a legacy result fixture. The
unpinned terrain path remains nondeterministic and is not accepted.
The product's first-run Terms and Conditions for Use dialog was an execution
gate at the time of this record. This statement is superseded by the 2026-07-18
black-box acceptance-state record: user authority has since been recorded and
the exact 7.0.1 target has passed reversible and persistent Wine controls.
HEC still documents no supported headless state-transfer interface.
Geometry-property-table generation remains a separate bounded failure. Fresh
7.0.1 preprocessing/solve parity, restart/recovery, and the full production
zero-skip gate remain unproven. The current canonical slice report is
[`2026-07-18_headless_linux_execution/ras_mapper_701_native_wine_parity.md`](2026-07-18_headless_linux_execution/ras_mapper_701_native_wine_parity.md).

The private runner now uses an isolated Debian 13 task host, a prepared Wine
11.0 prefix, Windows Python 3.11.9, .NET Framework 4.8, and one cloned prefix
and project copy per run. Native Windows and Wine inspection resolve HEC-RAS
7.0.1 and the same SHA-256 identities for all five required components. Project
open/save/clone and spaces/long-path cases pass under Wine. RAS Mapper mesh is
isolated in an x86 managed host with ordered product-dependency loading and
native Linux process supervision. The host avoids Wine's non-returning
`RASD2FlowArea.Save()` path by extracting exact in-memory seed centers and
transactionally persisting the product-generated seed block; product HDF
features are reloaded and checked before acceptance.

The official release notes identify 7.0.1 as a 64-bit Windows release dated
June 2, 2026. The supported-product claim therefore stops at Windows; Wine is
a compatibility layer and needs independent parity evidence:

- [HEC-RAS 7.0.1 release notes](https://www.hec.usace.army.mil/confluence/rasdocs/rasrn/latest)
- [Wine documentation](https://www.winehq.org/?page=documentation)

HEC-RAS 2025 is a separate next-generation beta/work-in-progress and is not a
production substitute for this qualification:

- [HEC-RAS 2025 beta](https://www.hec.usace.army.mil/software/hec-ras/2025/)

## Implemented qualification surface

`RasQualification` is the evidence API for the two execution lanes. It adds:

- exact PE product/file-version inspection without launching the executable;
- SHA-256 identities for `Ras.exe`, `RasProcess.exe`, `RasMapperLib.dll`, the
  geometry preprocessor, and the unsteady solver;
- isolated 64-bit Wine-prefix creation with a unique task identifier and a
  retained diagnostic marker;
- immutable project staging for normal, space-containing, and long paths;
- deterministic project and canonical HDF content fingerprints;
- exact 2D cell/face counts, boundary assignments, property-table coverage,
  breakline/refinement counts, and cell/face quality distributions;
- unsteady status, compute-message, and volume-accounting evidence;
- produced-terrain receipts that hash the GeoTIFFs referenced by the HEC-RAS
  terrain HDF plus canonical pyramid/TIN content, while retaining source DEM
  receipts separately;
- explicit profile-line hydrograph and fixed mesh-cell WSE extraction, followed
  by keyed comparison with maximum-absolute, RMSE, and peak-error limits;
- depth-grid comparison after mapping the Wine result to the native grid,
  including wet-area overlap and raster-value error;
- receipt scaffolding in which every requirement begins as `not_run` and a
  passed operation cannot be recorded without evidence; and
- strict receipt/parity validation that rejects missing, failed, or skipped
  critical operations.

`RasQualificationRunner` and `RasQualificationActions` make that contract
executable:

- every operation runs in a fresh worker process with a hard timeout and
  process-tree termination;
- the runner checkpoints its context and receipt after every operation and
  retains hashed stdout/stderr tails, before/after project fingerprints, and
  failed-operation content evidence;
- the Wine profile creates or clones one prefix per task, stages the project
  inside that prefix by default, converts host/Windows payload paths with
  `winepath`, and requires an explicit Wine-hosted Windows Python worker so the
  Windows ras-commander code and pythonnet/RasMapperLib are actually exercised;
- built-in actions cover project open/save/clone, projection and terrain,
  geometry/mesh mutations, boundaries, Manning's n/land-cover/infiltration,
  property tables, preprocessing/solve, Mapper layers/export, restart,
  expected failure diagnostics, and prefix-concurrency isolation; and
- a geometry-backed boundary-location API validates the authored BC line and
  2D-area association, creates the correctly padded 8/9-field unsteady record
  idempotently, and then permits type/value conversion with content verification;
- land-cover and infiltration actions require RAS Mapper registration plus an
  exact persisted geometry association, map export requires every requested
  map and georeferenced/value-bearing raster content, and restart recovery is
  compared to a distinct continuous baseline for flow, WSE, and volume; and
- refinement and breakline actions are transactional. If RasMapperLib rejects
  the mutation, the geometry HDF—and for breaklines the text geometry and
  sidecar backup—are restored exactly while the failed attempt remains in the
  receipt.

`locking.project` is a built-in cross-process action. It verifies atomic lock
creation, owner/token checked release, deterministic contention rejection,
reacquisition with a different token, source-project immutability, and zero
residual lock files under the private Wine runner.

Version discovery was also corrected. The previous compact alias `66` selected
HEC-RAS 7.0, installed 6.6 folders were omitted from one discovery list, and
7.0.1 had no exact identity path. Discovery now normalizes plan, folder, and PE
forms such as `6.60`, `7.01`, `7.0.1.0`, `6.4.0.1`, and `5.0.0.7` while keeping
beta labels distinct.

## Required-operation and evidence contract

All operations below are critical. `not_applicable` is allowed only for Wine
prefix operations on the native-Windows profile. A private runner may not use
pytest skip, receipt `skipped`, or an empty evidence object to pass the gate.

| Area | Required receipt operations | Minimum content evidence |
|---|---|---|
| Installation/isolation | `installation.detect`, `wine_prefix.create`, `concurrency.prefix_isolation` | exact 7.0.1 PE version, component hashes, Wine/image version, unique prefixes and node-local workspaces |
| Project lifecycle | `project.open`, `project.save`, `project.clone`, `path.spaces`, `path.long` | pre/post project fingerprints, clone independence, successful reopen, source immutability |
| Terrain | `projection.select`, `terrain.import`, `terrain.build_pyramids`, `terrain.associate` | CRS WKT, fingerprints of HEC-RAS-produced terrain GeoTIFFs and canonical pyramid/TIN HDF content, source DEM receipts, geometry-to-terrain association |
| RAS Mapper mesh | `geometry.2d_area_create`, `geometry.perimeter_edit`, `mesh.generate_initial`, `mesh.regenerate`, `mesh.refinement_region`, `mesh.breakline` | exact area names, cells/faces after each mutation, perimeter and HDF fingerprints, quality distributions, refinement/breakline counts |
| Boundaries/properties | `boundary.associate`, `boundary.conflict_repair`, `properties.mannings`, `properties.infiltration`, `properties.land_cover`, `properties.geometry_tables` | exact boundary assignments and conflict resolution; source-layer hashes; complete per-cell and per-face tables |
| Solve | `plan.preprocess`, `plan.compute_unsteady` | plan/geometry identities, preprocessor outputs, successful HDF content, diagnostics, volume accounting, named profile-line flow and explicit mesh-cell WSE records |
| Mapping/export | `mapper.result_layers`, `mapper.export_geotiff` | required result-layer inventory and a readable, georeferenced GeoTIFF value receipt |
| Recovery/contention | `recovery.restart`, `diagnostics.failed_run`, `locking.project` | restart equivalence, expected failure signature and retained artifacts, deterministic lock contention outcome |

Mesh creation and regeneration evidence must come from RAS Mapper or
`RasMapperLib` behavior, not a synthetic HDF writer. USACE describes the mesh
workflow as initial cell-point generation followed by terrain-based hydraulic
property tables, with breaklines and refinement regions controlling the mesh:

- [HEC-RAS 2D mesh guidance](https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/latest/development-of-a-2d-or-combined-1d-2d-model/development-of-the-2d-computational-mesh)

## Fixture hierarchy

Use immutable source packages and record a `RasQualification.project_tree_fingerprint`
before staging. Do not place generated results back into an example-project
source directory.

1. **Weise_2D** — fast, small 2D lifecycle fixture. Use for open/save/clone,
   projection, terrain, initial mesh, mutation/regeneration, boundary, property
   table, preprocessing, solve, and map-export iterations.
2. **BaldEagleCrkMulti2D** — larger multi-2D and boundary/connection fixture.
   Use for performance, multiple boundary assignments, breaklines/refinement,
   restart, failure diagnostics, locking, and concurrency. The active checked
   geometry has 18,066 cells and 37,594 faces with complete existing cell/face
   property tables. Qualification still requires the generation command itself
   to return and reproduce exact content when that operation is in scope.
3. **Muncie plus Davis** — mixed 1D/2D structures and pipe-network regression.
   Use to prevent the BLE-focused lane from weakening high-value structure,
   plan-cloning, unsteady-flow, and result-extraction APIs used by ras-agent.
4. **Spring Creek representative BLE** — promotion fixture only after the
   study-domain, terrain, hydrology, and structure gates in the adversarial
   review are accepted. This is the required final Windows-golden versus Wine
   promotion comparison, not the first automation fixture.

The example catalog and notebooks are the fixture source of record, especially
`100_using_ras_examples.ipynb`, `101_project_initialization.ipynb`,
`102_multiple_project_operations.ipynb`, and the mesh-sensitivity workflow in
`_test_230.py` / `_test_230_meshonly.py`.

## Private-runner execution

Copy `tests/qualification/manifests/hecras-701-native.template.json` outside the
repository, fill every engineering-fixture placeholder, and run it with:

```text
python -m ras_commander.RasQualificationRunner run native-701.json
```

For Wine, change the profile to `linux_wine_windows_ras`, use Linux host paths
for the manifest's installation/project/workspace values, and configure:

```json
{
  "executor": {
    "worker_command": ["wine", "C:\\Python311\\python.exe"],
    "payload_path_mode": "wine"
  },
  "wine": {
    "wine_executable": "wine",
    "template_prefix": "/qualified-templates/hecras-701-python",
    "prefix_root": "/node-local/rasq-prefixes",
    "stage_inside_prefix": true,
    "initialize": false,
    "dll_overrides": "winemenubuilder.exe=d;winedbg.exe=d",
    "python_site_packages": "drive_c/Python311/Lib/site-packages",
    "runtime_packages": {
      "pythonnet": "3.0.5",
      "clr_loader": "0.2.10"
    }
  }
}
```

The prepared template prefix must contain the approved HEC-RAS installation,
Windows Python, and the pinned ras-commander dependencies. The runner clones
that template without rerunning `wineboot --update`, which attempted a modal
WOW64 `wine.inf` reinstall on the prepared prefix. It records the template and
task-prefix fingerprints, verifies the cloned HEC-RAS component hashes and
runtime-package metadata, and uses only the task-local clone and project copy.
The first ordinary Wine process may initialize services in the clone; no shared
writable prefix is used.

The native and Wine receipts must have the same fixture object, including the
same immutable source fingerprint. Engineering must approve the tolerance JSON;
the repository deliberately contains no invented pass thresholds.

Terrain creation is currently a qualified single-CPU preprocessing operation.
On a scheduler, allocate one logical CPU to that worker or prefix the Wine
worker command with `taskset -c <allowed-cpu>`. Derive the CPU from the task's
assigned cpuset; do not copy the private runner's CPU number into a portable
manifest. Multicore terrain creation is fail-closed until the Wine CLR/native
race is understood and independently retested.

Enable the gate only on the configured private runner:

```text
RAS_COMMANDER_RUN_HECRAS_QUALIFICATION=1
RAS_COMMANDER_NATIVE_701_RECEIPT=/receipts/native-receipt.json
RAS_COMMANDER_WINE_701_RECEIPT=/receipts/wine-receipt.json
RAS_COMMANDER_701_PARITY_TOLERANCES=/receipts/approved-tolerances.json
pytest -m "hecras_qualification and qualification_critical" tests/qualification
```

When enabled, absent files produce test errors and any receipt skip fails. On a
normal developer machine the three real-product acceptance tests are cleanly
skipped; this does not constitute qualification.

## Verification performed in this session

### 2026-07-17 HEC-RAS 7.0.1 execution update

- Installed the official HEC-RAS 7.0.1 package on the native Windows runner and
  in a prepared Wine 11.0 prefix. The official setup executable SHA-256 is
  `1fe76297076aa7a13e43191ecc76c3ba152fdc4bbd606fa2c349eec7db3cee73`.
- Native Windows and Wine report the same normalized version, `7.0.1`, and the
  same five component hashes. `RasGeomPreprocess.exe` and `RasUnsteady.exe` are
  x64; the GUI/managed components are PE i386/AnyCPU as expected for this mixed
  installation.
- The immutable `BaldEagleCrkMulti2D` fixture fingerprint is
  `3871280ea71ad266287f2aa2d3ee6271791caf751b0022f988df10fcb84b8658` on both
  lanes.
- The native-Windows receipt passes installation detection, project
  open/save/clone, 280-character path handling, and all four RAS Mapper mesh
  goldens: initial `4,362/9,500`, regenerate `4,362/9,500`, refinement
  `4,426/9,661`, and breakline `4,431/9,656` (cells/faces). Each result matches
  the persisted HDF and records a geometry fingerprint.
- The Wine receipt passes installation and cloned-prefix identity, exact
  Python.NET 3.0.5 / CLR-loader 0.2.10 metadata, project open/save/clone, spaces,
  and long paths without modal initialization dialogs.
- Python.NET 3.1.0 crashes under Wine in
  `Python.Runtime.ExtensionType.AllocObject` with
  `System.AccessViolationException`. Pinning 3.0.5 allows a minimal CLR import
  and sometimes reaches RasMapperLib, but repeated real workers remain
  nondeterministic: one fails during reflected method formatting while another
  reaches the 537-point perimeter and then makes no HDF progress in either
  `RegenerateMeshPoints` or the explicit `PointGenerator.GeneratePoints`
  diagnostic path.
- Headless workers now disable Wine's modal debugger, so a CLR failure exits
  and retains its managed stack instead of blocking an HPC task. Prepared
  template clones also skip the unnecessary `wineboot --update` operation.
- The GDAL bridge now detects Wine PowerShell's false-success junction result
  and falls back to a verified directory symlink. Runtime-package versions are
  read from hashed `dist-info/METADATA` files and are part of the prefix gate.
- A diagnostic `seed_generation_mode` distinguishes the normal
  `RegenerateMeshPoints` workflow from `PointGenerator.GeneratePoints`; this is
  evidence isolation only and does not weaken the required native/Wine parity
  path.
- The native receipt and Wine failure archives are retained in the controlled
  private qualification evidence store. At this historical point the Wine lane
  remained failed overall because exact mesh content, terrain, solve, result,
  and parity evidence were absent; later sections supersede that slice status.
- After the final fail-fast prefix change, the qualification-focused private
  Linux suite passes **156 tests with 1 platform-specific skip and 17 warnings
  in 9.73 seconds**. The exact staged native-Windows source previously passed
  **154 tests with 2 platform-specific skips in 63.79 seconds**. Enabling the
  three private real-product acceptance tests against the partial native and
  failed Wine receipts produces **2 failures and 0 skips**, as required by the
  fail-closed gate.
- A broader copied-source Linux run produced **823 passed, 68 skipped, and 25
  failed**. The retained failures identify omitted example/research fixtures,
  two omitted notebooks, and Windows/path-selection assumptions in that copied
  tree. They are not counted as qualification passes and remain general-suite
  cleanup work.

- The maintained ras-commander suite passed with the headless Matplotlib
  backend pinned (`MPLBACKEND=Agg`): **863 passed, 32 skipped, 25 warnings in
  217.68 seconds**. The three qualification-gate tests are among
  the expected local skips because `RAS_COMMANDER_RUN_HECRAS_QUALIFICATION`
  was not enabled. Repository-wide pytest discovery also finds a pre-existing
  feature-development Spring Creek script that calls `sys.exit(1)` at import
  time when its external organized model is absent; the maintained `tests/`
  target is clean.
- Enabling that variable without a native receipt produced a pytest setup
  error, confirming that the private-runner path fails instead of skipping or
  silently weakening the gate.
- The actual local `Ras.exe` PE resource reports `7.0.0.0`; installation
  inspection found and hashed all five required HEC-RAS components. This is a
  valid 7.0 baseline check, not a 7.0.1 golden.
- After installing the declared `pythonnet` dependency in the disposable test
  environment, the existing RasMapperLib profile-line and land-cover/
  infiltration tests passed against that real local installation.
- The geometry receipt was exercised on an existing Bald Eagle 2D geometry:
  89,879 cells, 177,301 faces, two boundary assignments, and mesh-quality
  distributions were read from HEC-RAS HDF content. Its absent hydraulic
  property tables were reported as incomplete rather than accepted.
- The process-isolated runner was exercised end-to-end against the actual local
  Windows HEC-RAS 7.0/RasMapperLib installation and a cloned
  `BaldEagleCrkMulti2D` fixture. This deliberately partial smoke receipt is
  retained privately as `bald-eagle-runner-smoke-receipt.json`.
  It passed installation identity, project open/save/clone, a path containing
  spaces, a 282-character long path, initial mesh generation, and regeneration.
- Initial generation and regeneration independently produced **4,362 cells and
  9,500 faces**, and each result matched the HDF's declared counts exactly.
  Evidence also retained three exact boundary assignments, four text/HDF
  feature breaklines, 4,362 mesh-quality polygons, zero invalid cells, and
  cell-area/aspect-ratio/face-length distributions.
- This real run exposed a subtle HDF issue: `Cells Center Coordinate` contained
  5,120 allocated rows while the authoritative 2D area `Cell Count` and quality
  polygon count were 4,362. Receipts now use the declared count and separately
  report capacity padding instead of over-counting the mesh.
- Long-path staging now uses Windows extended-length paths only for Python I/O
  while preserving the ordinary drive-letter path in evidence and for vendor
  operations. Project inventory reopened successfully at 282 characters with
  11 plans, 10 geometries, 10 unsteady files, and 51 boundary conditions.
- A refinement-region reader was incorrectly decorated as a plan-HDF reader;
  it now reads geometry HDF files and the regression suite verifies the actual
  group. The writer retains complete nine-field/XYM HDF schema support for
  synthetic fixtures, but product geometry now uses
  `MeshRegions.AddFeature(...)`, the feature-layer `Save()`, and an immediate
  RasMapperLib reload. Qualification explicitly refuses the synthetic writer.
- The post-regeneration perimeter failure was isolated and fixed. Saving a
  computed `MeshFV2D` through `RASGeometry.Save()` wrote the per-area perimeter
  but emptied the global `Geometry/2D Flow Areas/Polygon Points` table; the next
  worker therefore saw a zero-point perimeter. Mesh persistence now uses the
  owning `RASD2FlowArea.Save()` path and regression tests prohibit the unsafe
  geometry-level save.
- Seed regeneration had also passed an explicitly empty active-region list to
  RAS Mapper. It now supplies every loaded `MeshRegions` FID. A separate-process
  product probe reloaded the new region and generated 4,426 seeds while
  reporting one active refinement region.
- The final local 7.0 smoke passes all four mesh operations with exact goldens:
  initial **4,362/9,500**, regeneration **4,362/9,500**, refinement
  **4,426/9,661** (a measured +64-cell effect), and breakline mutation
  **4,431/9,656** (cells/faces). Each action result matches the persisted HDF.
  The refinement receipt additionally proves exact raw-HDF/RasMapperLib feature
  count agreement plus name, spacing, and polygon-point content after reload.
- Production receipt validation now fails unless exact expected cell and face
  counts are supplied and matched for initial generation, regeneration,
  refinement, and breakline mutation. The native manifest template marks all
  eight values, plus the refinement delta, as engineering-golden inputs.
- Terrain evidence no longer re-labels an input DEM fingerprint as the terrain
  result. An extracted `Weise_2D` regression proves that modifying the actual
  GeoTIFF referenced by the terrain HDF changes the combined terrain
  fingerprint while the canonical pyramid-HDF fingerprint stays constant.
- `plan.compute_unsteady` now requires named series specifications and records
  both a RAS Mapper profile-line flow hydrograph and WSE from explicit mesh
  cell IDs. Receipt validation requires both series types, and parity fails
  unless the engineering tolerance file covers each one.
- A new `GeomBcLines.get_bc_lines()` reader and
  `RasUnsteady.ensure_2d_boundary_location()` close the create-if-missing gap
  in boundary association. An extracted `Chippewa_2D` regression authors a BC
  line, creates its unsteady location, verifies idempotency, converts it to
  Normal Depth, and confirms the exact area/name/type/slope in
  `boundaries_df`.
- Land-cover and infiltration qualification can no longer pass on a nonempty
  sidecar HDF alone: both the RAS Mapper layer inventory and the geometry HDF
  association must resolve exactly to that artifact before property-table
  generation. Requested WSE/depth/velocity exports are likewise checked
  individually, and all output rasters must carry CRS, dimensions, and valid
  values.
- Restart/recovery can no longer pass merely because the restarted solver
  exits successfully. The action requires a different continuous baseline
  plan, an engineering-defined common time window, flow and WSE series with
  explicit tolerances, and an approved maximum volume-accounting difference.
- Failed operations now retain their partial content receipts, before/after
  project fingerprints, process-log hash/tail, and rollback proof. Earlier
  runner behavior retained only diagnostics for failures, which was inadequate
  for adversarial qualification.
- Two precipitation tests were corrected to the format present in real
  HEC-RAS examples: `Precipitation Hydrograph` stores interval-indexed depth
  values, while the preceding `Interval=` record defines the time axis.

The earlier version-7.0 partial smoke receipt correctly fails overall: it has
no qualified terrain or result artifacts, has incomplete hydraulic property
tables, and leaves fixture-specific/full-workflow actions unconfigured. Its
mesh exact-count gate passes, but this does not elevate it to qualification.
The private Linux host is now accessible and ran the 7.0.1 Wine attempts
described above. No fresh HEC-RAS 7.0.1 Wine solve or computation-result parity
comparison is yet available; later evidence does establish exact Mapper export
parity from a legacy result fixture. The earlier claim that authorization was absent is
superseded by the separately retained 2026-07-18 acceptance-state evidence;
that evidence removes only the TCU blocker, not the solve/parity requirements.

### 2026-07-18 Wine mesh, TCU, locking, and concurrency update

- Wine initial generation and regeneration both match the exact
  **4,362-cell / 9,500-face** golden. The isolated breakline fixture produces
  **4,367 / 9,495**, and the refinement fixture produces **4,426 / 9,661**,
  including the exact measured +64-cell effect and a RasMapperLib reload of the
  region name, spacing, and polygon.
- The first-run TCU modal is now a structured failure rather than a generic
  timeout. A real Wine action detected it in 0.53 seconds, preserved the exact
  18,066-cell / 37,594-face source-fixture content checks, did not click any
  assent control, and left no surviving Wine or HEC-RAS process.
- Every qualification worker now holds an atomic project lock with an owner,
  random token, content hash, and explicit release receipt. The built-in
  `locking.project` action proves cross-process contention rejection under
  Wine, owner-checked release, different-token reacquisition, and restoration
  of the original project fingerprint. The v22 path receipts also prove that a
  transient source lock is excluded from space/long-path clones, and a separate
  filesystem scan found zero residual locks.
- The two-task Wine isolation action now uses prepared clones without rerunning
  `wineboot`, verifies exact HEC-RAS component and Python.NET/CLR identities,
  creates disjoint task-local write markers, and proves both the template and
  source project are immutable. The live v21 receipt passed every configured
  lifecycle/locking/isolation operation and an independent filesystem scan
  found zero residual project locks.
- The qualification-focused regression passes **179 tests with 5 expected
  platform/private-gate skips**. These local skips are not production
  qualification; the configured private acceptance run must still have zero
  critical skips.

### 2026-07-18 Mapper data, property-table, and terrain update

- Projection selection passed with exact EPSG:2271 content. Existing Bald Eagle
  terrain pyramids were inspected as levels 0–6 and 0–5, and all 16 Manning
  classes round-tripped exactly.
- Managed x86 RasMapper hosts now cover geometry-to-terrain association,
  land-cover association, infiltration association, and geometry-property-table
  commands. Wine passed exact terrain association on the 18,066-cell /
  37,594-face geometry, exact 16-class land cover, and all 136 infiltration
  parameter rows.
- Property-table generation remains failed, not skipped. On both Bald Eagle and
  the smaller 5,391-cell / 11,164-face Muncie geometry,
  `CompleteGeometryCommand` opened the geometry and then did not return. Direct
  `ComputePropertyTablesCommand` accumulated heavy CPU for 1,800 seconds and
  then timed out; its isolated retry became a low-utilization non-return. Exact
  cell/face counts and complete-table gates remained enforced.
- Terrain creation previously launched a quoted command through `cmd.exe`.
  When the child failed, inherited output pipes could leave Python blocked after
  the shell timeout. `RasTerrain.create_terrain_hdf()` now launches
  `RasProcess.exe` directly with an argument vector, propagates a configurable
  product timeout, and rejects every nonzero exit even if a partial HDF exists.
- Direct multicore Muncie terrain creation exposed CLR exit code 3762504530
  (`0xE0434352`) with `System.EntryPointNotFoundException`; other isolated runs
  hung or raised `System.AccessViolationException`. Restricting the worker to
  one allowed CPU eliminated the failure without CLR or GDAL tuning.
- The v35 real qualification action passed in the Windows Python/Wine worker:
  one layer, pyramid levels 0–5, 7,892 × 4,538 cells, 35,588,572 valid values,
  source and output raster data fingerprint
  `560aa16f981c83840858e5feac0917a8a5a1e8b293b9dd31daf8efaad154b3ac`,
  and repeatable semantic terrain HDF fingerprint
  `c87a7037852b11686e58234f6b25650371931ec206fa2e507ac8df042b024ddb`.
  The combined semantic HDF/raster fingerprint is
  `a47b513bb4486929a42df9788b9d6404ff0b1f80a452fea5e8bde4fec56efcc0`.
  No `RasProcess.exe` survived the run.
- Two independent passing terrain HDFs have all 29 `/Terrain` paths and every
  dataset checksum identical. Their raw fingerprints differ only because of a
  generated GUID, last-access time, and a 3.7e-12 summary-statistic rounding
  difference. Receipts now retain raw SHA/fingerprints for audit and use a
  separate semantic fingerprint that excludes those fields and rounds scalar
  HDF attributes to nine decimal places. The live v36 receipt also proves the
  Windows process saw exactly CPU ID 2, process mask `0x4`, and one CPU.
- Failure and pass evidence archives are retained in the controlled private
  evidence store. The important archive SHA-256 values are v30
  `9bfd2385d8ecebf18cb36e65590391e63ca83efb96edc4010161fb451eeb55c6`,
  v31 `35a7c8343d630aa35387358d7f1c1a5856adba4ee51bd97c946b9e84698a1607`,
  v32 `ada4d28b14b00440505b37a7d5983016b9ef9af72ee15e20e72e2b72adc576c1`,
  v33 `9b5a3992797f9be85b46cdb5594beb3e37f615be5cd4c4c1cda2a2eaea3c3e7e`,
  and the v35 passing artifact bundle
  `4f6f43a05d4fbc06564740a003cf80a90895954c0860221734dc0cf269eb1da8`.
  The v36 passing bundle with explicit affinity evidence is
  `bc07e2a200114c770187535685895033bae521a0295360be74319c8cad6ffddc`.
  The v37 passing bundle with affinity plus semantic/raw fingerprints is
  `8228633d16a052958a2f29bdd655fc77000aeb689838e7f530040a05e35977c5`.
- The focused regression suite now passes **177 tests with 2 expected
  platform/private-gate skips**; Python compilation checks also pass. These
  local skips remain outside the production zero-skip acceptance gate.

### 2026-07-19 exact native/Wine Mapper parity update

The cumulative mesh sequence, projection/multi-source terrain, and legacy-result
Mapper layer/GeoTIFF export slices now pass exact content parity. Mesh acceptance
includes ordered topology and fresh reopen; terrain acceptance includes exact
projection, layer order, pyramids, TIN/stitch content, raster data, association,
and unchanged geometry; export acceptance includes exact semantic CRS/grid,
dtype, valid mask, and WSE/depth/velocity values with zero error. The export
fixture contains an existing pre-7.0 result and therefore does not prove a fresh
7.0.1 computation.

The full function/evidence matrix, archive hashes, staging regression, and
remaining gates are in
[`2026-07-18_headless_linux_execution/ras_mapper_701_native_wine_parity.md`](2026-07-18_headless_linux_execution/ras_mapper_701_native_wine_parity.md).
The focused consolidated regression is **252 passed, 5 skipped, 1 warning**.
Those local skips are not the required private zero-skip acceptance gate.

## HPC isolation model

Pin the Wine version, base operating-system packages, and Windows HEC-RAS
component hashes in the Apptainer build receipt. Do not redistribute HEC-RAS in
source control; stage approved installation media according to the license,
cluster, and organizational policy.

Each scheduler task gets:

- one unique `WINEPREFIX` on node-local storage;
- one node-local writable copy of the immutable project fixture;
- no shared writable geometry, plan HDF, terrain HDF, or active result file;
- a separate output/receipt directory; and
- a retained failed workspace until diagnostics are collected.

Use a read-only SIF and per-task temporary writable layer. Apptainer documents
that SIF images are immutable and warns that shared writable overlays/directories
need locking; the same writable overlay is not safe for parallel tasks:

- [Apptainer Docker/OCI and writable-layer guidance](https://apptainer.org/docs/user/latest/docker_and_oci.html)
- [Apptainer persistent overlays](https://apptainer.org/docs/user/latest/persistent_overlays.html)

Keep geometry/terrain/mesh preprocessing separate from scenario solves. Cache
only a fully qualified immutable geometry package keyed by the source project,
terrain, inputs, HEC-RAS component hashes, Wine/image identity, and geometry HDF
fingerprint. Continue with CPU-only job arrays until representative BLE parity
passes; perform result extraction with native Linux Python/GDAL only after each
Windows-under-Wine solve has closed its files.

Until further Wine parity evidence exists, run terrain import on one logical
CPU. This is narrower than the solve policy: scenario solves may use more CPUs
only after their own native-Windows parity qualification. Record CPU affinity
in the operation receipt because it is currently part of the qualified terrain
execution environment.

## Remaining qualification work

1. Keep the recorded user authority separate from the technical state and
   compliance decision. HEC documents no headless acceptance-state interface
   and prohibits reverse engineering. Use only opaque exact-version state and
   black-box controls; do not publish or operationalize derived internals.
2. Exercise boundary conflict repair, property-table alternatives, fresh 7.0.1
   preprocessing/solve, restart, and failed-run diagnostics. Repeat the now-
   qualified Mapper export after that fresh solve. Fill every manifest
   engineering input/expected value; extend fixture-specific handlers only where
   the installed product requires GUI/HITL behavior.
3. Package the proven per-task prefix/lock model in a pinned Apptainer image and
   record its immutable image digest. The current LXC is qualification
   infrastructure, not the final redistributable artifact.
4. Execute the fixture hierarchy, review failures, and get engineering approval
   for volume, hydrograph, WSE, wet-overlap, and depth-value tolerances.
5. Run the critical gate with zero pytest skips and archive native, Wine, and
   comparison receipts plus the immutable input packages.
6. Only then mark the Wine/HPC BLE lane qualified or promote Spring Creek output.
