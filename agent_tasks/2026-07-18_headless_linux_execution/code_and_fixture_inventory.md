# Code, notebook, fixture, and test inventory

This inventory describes the code as inspected on 2026-07-18. It is not a claim
that every path is qualified.

## ras-commander execution paths

### Native Linux solve

`ras_commander/RasCmdr.py:1430-1726` implements
`RasCmdr.compute_plan_linux()` and invokes native `RasUnsteady` with a prepared
plan HDF and an `x##` geometry token. It requires `.p##.tmp.hdf`, `.b##`, and
`.x##` files (`RasCmdr.py:1548-1566`). Its Linux execution is real, but its
test coverage is presently mocked at the ras-commander level.

The public API does not invoke native `RasGeomPreprocess` first. There is no
exported native-preprocessor class in `ras_commander/__init__.py` or
`ras_commander/geom/__init__.py`.

### Existing Windows preparation

`ras_commander/RasPreprocess.py:71-289` implements
`RasPreprocess.preprocess_plan()`. It launches Windows `Ras.exe -c`, waits for
the detailed-compute signal that unsteady computation is starting, terminates
the process tree, and verifies `.tmp.hdf`, `.b##`, and `.x##`. It has an exact
TCU modal detector and does not click assent.

Its module-level claim that Windows preprocessing is required for all Linux
versions (`RasPreprocess.py:13-15`) is too broad. Windows preparation is still
needed for the artifacts the native distribution cannot create, but native
`RasGeomPreprocess` existed before 7.0.

`ras_commander/geom/GeomPreprocessor.py:78-360` is a second Windows
`Ras.exe -c` validation path. It deliberately does not call the standalone
preprocessor. At inventory time, its `geometry_only=True` implementation
omitted `Run UNet=0` even though the documentation said unsteady flow was
disabled. The current worktree fixes that defect and tests that the launch-time
plan contains `Run UNet=0` and that the original plan text is restored.

### Native preprocessor hidden in remote scripting

`ras_commander/remote/docker/scripts/run_ras.sh:114-130` invokes
`RasGeomPreprocess`, but only after an existing plan HDF is staged. It skips the
preprocessor if an `.x##` exists and can continue to `RasUnsteady` after a
preprocessor failure. It is not an acceptable fail-closed library API.

`ras_commander/remote/DockerWorker.py:473-483` normally performs the Windows
`RasPreprocess` step before remote execution, so the native preprocessor branch
is rarely exercised.

### RAS Mapper and 2D preparation

`ras_commander/geom/GeomMesh.py` contains the high-value RAS Mapper APIs:

- `GeomMesh.generate()` creates/regenerates a mesh through RasMapperLib. It
  requires a compiled geometry HDF and cannot compile raw `.g##` text.
- `GeomMesh.compute_property_tables()` routes Wine through the isolated managed
  geometry host and native Windows through `CompleteGeometryCommand` plus
  `ComputePropertyTablesCommand`.
- mesh generation under Wine now uses an isolated x86 managed host and exact
  cell/face content checks.

`ras_commander/RasProcess.py:917-1049` wraps Windows
`RasProcess.exe CompleteGeometry`. This full RAS Mapper completion pipeline is
not the same operation as native Linux `RasGeomPreprocess`.

`ras_commander/RasGeometryCompute.py:354-464` is the in-process native-Windows
equivalent using `RASGeometry.CompleteForComputations()`.

No official native Linux equivalent for RAS Mapper mesh authoring or full 2D
property-table completion is exposed in ras-commander.

### Qualification runner routing

The current qualification actions route both plan stages through Windows HEC-RAS:

- `plan.preprocess` calls `RasPreprocess.preprocess_plan()` in
  `ras_commander/RasQualificationActions.py:1780-1877`.
- `plan.compute_unsteady` calls Windows `RasCmdr.compute_plan()` in
  `RasQualificationActions.py:1880-1942`.

The runner needs stage-specific backend routing. Native Linux computation must
be tested as the production solve path; Wine should retain only unsupported
preparation actions.

## Critical dialog-watchdog finding

`ras_commander/RasDialogWatchdog.py:245-270` selects a known OK/Yes/Close
button and otherwise falls back to the first button. `_dismiss()` then clicks
it (`:281-304`). The watchdog is on by default in:

- `RasCmdr.compute_plan()` (`RasCmdr.py:332-351`, `:637-653`); and
- `GeomPreprocessor.run_geometry_preprocessor()`
  (`GeomPreprocessor.py:78-89`, `:249-263`).

At the time of inventory, no denylist for the TCU or another legal-assent modal
existed. The current worktree now adds a shared legal-dialog classifier,
blocked-dialog receipts, scoped process-tree termination, and removes the
first-button and generic Yes fallbacks. `RasCmdr.compute_plan()` and
`GeomPreprocessor.run_geometry_preprocessor()` now check the structured block.
This remediation now has unit/control-flow coverage plus real Wine preflight
evidence and stable-version native controls. Broader unknown RAS Mapper dialogs
still need to be inventoried rather than generically dismissed.

## ras-agent execution paths

The ras-agent inventory used a separate local checkout. Its imported dependency
path and revision were recorded in the test evidence but are intentionally not
embedded as machine-specific paths in this repository note.

### What is real

- `pipeline/runner.py` has local native-Linux subprocess execution for
  `RasUnsteady` and `RasGeomPreprocess`.
- `scripts/extract_hecras_linux.sh` extracts the special 7.0.1 installer and
  expects `RasGeomPreprocess`, `RasUnsteady`, and `RasSteady` in the staged
  artifact. The proprietary files are intentionally not committed.
- `tests/test_linux_engine_e2e.py` contains a gated real-engine solve using a
  Windows-preprocessed Spring Creek fixture. It proves that the x-token
  contract reaches a real `RasUnsteady` and writes a nondegenerate 2D result.

### What is overstated or disconnected

- `preprocess_mode='linux'` copies an existing plan HDF, strips Results, and
  then invokes `RasGeomPreprocess`. That does not establish a greenfield 2D
  property-table build from raw geometry and terrain.
- The native-preprocessor branch warns and continues to the solver if
  `RasGeomPreprocess` is missing. Production routing must fail closed.
- `pipeline/hecras_readiness.py` tries ras-commander Windows/RAS Mapper APIs to
  regenerate missing terrain and 2D property tables. That cannot be considered
  a native-Linux readiness path.
- The strongest real native solve test disables the readiness gate because its
  Windows-preprocessed fixture already contains compiled artifacts.
- `pipeline/geom_preprocess_python.py` attempts a portable Voronoi/terrain-table
  implementation but labels itself screening-quality and not FFRD compliant.
  It must not be promoted as an engineering substitute for HEC's property
  tables without a separate validation program.

Additional routing defects found during inspection:

- The orchestrator can recognize the legacy `bin_ras/rasUnsteady64` layout,
  but the runner later invokes only a root-level `RasUnsteady`; that detected
  path is broken.
- `_run_ras_commander_linux()` exists but the orchestrator does not select its
  documented execution-mode name.
- SLURM submission does not forward the job's preprocessing mode, so the SLURM
  builder silently uses its Windows/precompiled default.
- `RasSteady` is extracted and staged, but no ras-agent Python execution path or
  test invokes it.
- `WindowsAgent._generate_local()` ignores several requested geometry inputs,
  calls preprocessing twice, and reports success without proving the expected
  geometry HDF exists. No production caller was found; it should not be used as
  the Wine integration layer.

The ras-agent concepts should be split into explicit stages rather than one
`preprocess_mode`:

1. project/pre-compute artifact preparation;
2. RAS Mapper 2D property-table preparation;
3. native 1D `RasGeomPreprocess`; and
4. native flow computation.

## Current real Wine status

These results come from the retained 7.0.1 qualification evidence, not from
mocked tests.

| Operation | Current Wine status |
|---|---|
| Installation/version/component identity | Passed |
| Project open/save/clone | Passed |
| Spaces and long paths | Passed |
| Prefix isolation, project locking, two-task isolation | Passed |
| Projection selection | Passed; older EPSG:2271 control plus exact native/Wine EPSG:2965 and PRJ fingerprint on the Muncie parity fixture |
| Terrain creation/import | Passed exact native/Wine multi-source parity with one allowed logical CPU |
| Terrain pyramids and semantic content | Passed exact native/Wine per-layer pyramid, TIN/stitch, raster-data, and semantic-HDF parity |
| Terrain association | Passed exact native/Wine association; Muncie g02 topology unchanged at 5,391 / 11,164 |
| 2D initial mesh | Passed; exact 4,362 cells / 9,500 faces |
| 2D mesh regeneration | Passed; exact 4,362 / 9,500 |
| Breakline mutation | Passed; isolated control 4,367 / 9,495 and qualified post-refinement sequence 4,431 / 9,656 |
| Refinement region | Passed; exact 4,426 / 9,661 and +64 cells |
| Boundary association | Passed; exact Normal Depth type/location/slope |
| Land-cover association and class table | Passed; 16 classes |
| Infiltration association | Passed; 136 parameter rows |
| TCU detection/termination in `RasPreprocess` | Passed; structured blocker, no click |
| Generic watchdog TCU safety | Remediated and live-qualified natively across the 15 installed stable 4.x–7.x builds plus four reversible Wine 7.0.1 clones; the persistent candidate is retained only as a diagnostic |
| 2D geometry property tables | Failed; product calls did not return/timed out |
| Boundary conflict repair | Not yet proven |
| Plan preprocessing | Not yet proven after TCU provisioning |
| Unsteady solve under Wine | Intentionally no longer the preferred production path; unproven |
| Native Linux solve parity | Not yet qualified in ras-commander |
| Mapper result layers/GeoTIFF export | Passed exact native/Wine WSE, depth, and velocity layer/export content on a legacy result fixture; fresh 7.0.1 solve parity remains open |
| Restart equivalence and failed-run diagnostics | Not yet proven |
| Native Windows versus Wine preparation parity | Exact for the qualified mesh, projection/multi-source-terrain, and result-export slices; incomplete overall |

## High-value examples and fixtures

Use example projects as immutable source fixtures and copy them per test.

1. **Weise_2D** — fastest lifecycle/preprocess/solve iteration after explicit
   CRS and terrain are supplied.
2. **Muncie** — official mixed 1D/2D fixture for native engine contracts,
   `CompleteGeometry`, and 2D property-table investigation.
3. **BaldEagleCrkMulti2D** — mesh, breakline, refinement, concurrency, and
   restart fixture.
4. **Bald Eagle 1D unsteady** — fast native `RasGeomPreprocess` and
   `RasUnsteady` baseline.
5. **Chippewa_2D** — boundary-association and mesh-sensitivity regression.
6. **Spring Creek** — final representative BLE promotion/parity fixture, not
   the first debugging target.

Relevant notebooks/scripts:

- `examples/510_linux_execution.ipynb` documents the prepared-input/native
  solve handoff, but uses stale 6.7-beta assumptions and manual SSH/direct
  engine commands. It needs replacement by library APIs and content checks.
- `examples/225_rasmapper_geometry_completion.ipynb` exercises native-Windows
  completion/validation but not Wine.
- `examples/_test_230_meshonly.py` is the strongest concise Bald Eagle mesh
  fixture.
- `examples/230_mesh_sensitivity_analysis.ipynb` provides useful cell-size
  sweep logic.
- `examples/211_final_mannings_and_infiltration.ipynb` contains robust readers
  and content assertions for preprocessed Manning/infiltration data.
- `examples/212_landcover_mannings_n_write.ipynb` authors, associates, and
  validates a real land-cover layer.
- `examples/920_terrain_creation.ipynb` is the terrain creation source.
- `examples/110_single_plan_execution.ipynb` and
  `examples/113_parallel_execution.ipynb` provide Windows solve baselines.
- `examples/950_ebfe_spring_creek.ipynb` is the representative project workflow
  but should remain the final promotion test.

## Existing test coverage and gaps

| Surface | Existing evidence | Gap |
|---|---|---|
| TCU/legal-dialog handling | Shared classifier, focused tests, 65-case native 4.x–6.x/beta diagnostic receipt, 7-case native 7.x receipt, four reversible fresh-prefix Wine controls, and an exact-version user-visible session API with two restarts | Complete the zero-skip user-session receipts for all 15 stable installed builds; keep 6.7 betas separately authorized; inventory broader unknown RAS Mapper dialogs |
| `compute_plan_linux()` | Mocked WSL helper/control flow | No maintained real ras-commander native-engine fixture |
| Native `RasGeomPreprocess` | Shell path only | No public API, fail-closed result object, or real integration test |
| Managed Wine mesh | Unit/mocked routing plus retained real qualification receipts | Promote real action to private zero-skip gate |
| Projection/multi-source terrain parity | Native v54/v55 repeat plus Wine v56 exact semantic/data comparison | Multicore Wine path remains rejected; promote the one-CPU action to the full zero-skip gate |
| Wine 2D property tables | Mocked routing plus real failed attempts | Need bounded alternatives and native-Windows/Wine content comparison |
| Mapper result layers/export | Native v57 and Wine v59 exact WSE/depth/velocity content parity plus all-band comparator tests | Repeat after a fresh 7.0.1 solve; integrate into the full zero-skip gate |
| `RasProcess.compute_geometry()` | Conditional native-Windows Muncie test | No maintained real Wine assertion |
| Native Linux ras-agent solve | Gated real Spring Creek test | Checks only broad result presence/nondegenerate size, not engineering parity |
| Pure-Python preprocessing | Extensive unit/synthetic tests | Screening only; no production acceptance |

The original fail-closed watchdog/preprocess/compute-control regression passes
44 tests, including registered-launcher termination, verified survivor checks,
dependency-unavailable and scan-thread failure paths, opt-in-only global
process discovery, process-scoped TCU detection, pre-termination diagnostic
publication, structured single/parallel errors, and the geometry-only
`Run UNet=0`/exact-restoration test. No HEC-RAS process is launched by those
tests. The acceptance-state/watchdog suite adds focused user-session,
fail-closed supervision, and prefix-fingerprint tests plus content-based private
receipt gates. The retained diagnostic receipts validate embedded report
hashes, executable identity, exact restoration, zero interactions, verified
termination, and no survivors; publishable template promotion additionally
requires the new user-visible exact-version receipt and whole-prefix evidence.

### ras-agent focused test result

The inventory agent ran the focused runner/model-builder/Linux-engine suite:

```text
196 passed, 8 skipped, 432 warnings in 138.43 seconds
```

The eight skips included both real Linux-engine tests, missing geometry-first
basin/DEM prerequisites, three unconditionally skipped real HEC DLL mesh tests,
and a missing pure-Python reference fixture. No HEC-RAS operation executed
under Wine. The warnings were `numpy.trapz` deprecations in the vendored
screening preprocessor.

That run was also not hermetic: the checkout pins one ras-commander revision,
while Python resolved a different local ras-commander checkout/version. Future
private integration runs must record the imported module path and exact git
revision and fail when they differ from the pinned dependency.

### Qualification-framework regression result

A consolidated qualification/mesh/terrain/Mapper regression run produced:

```text
252 passed, 5 skipped, 1 warning in 37.06 seconds
```

The warning is the expected Rasterio `NotGeoreferencedWarning` in a synthetic
georeferencing-rewrite test. The five skips are local platform/private-product
gates and do not satisfy the required private-runner zero-skip acceptance gate.
The former compact-version-alias regression is no longer present in this run.
