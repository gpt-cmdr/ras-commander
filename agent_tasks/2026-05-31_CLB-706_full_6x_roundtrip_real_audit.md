# CLB-706 Corrected Audit: `codex/full-6x-roundtrip`

Date: 2026-05-31
Auditor: Codex, CLB Symphony runner on CLB08
Issue: CLB-706

## Executive Decision

The reviewer was correct: the prior audit was based on the wrong checkout and missed a real local branch/worktree. I inspected the actual CLB08 branch and worktree, preserved the full branch in persistent artifacts, salvaged one small `RasUtils.discover_ras_versions()` fix, and removed the stale worktree and local branch.

I did **not** merge or cherry-pick the branch wholesale. The branch was 27 commits ahead and 309 commits behind `origin/main`, and most branch topic families are already present on main through newer, better-integrated implementations.

## Baseline Evidence

- Source checkout used for stale ref inspection: `G:/GH/ras-commander`
- Symphony workspace used for tracked changes: `G:/GH/symphony-workspaces/ras-commander/CLB-706`
- Stale branch before removal: `codex/full-6x-roundtrip`
- Stale branch tip before removal: `2a4ff38fe2ceb0b2d4b385bbaa51e0c91e9f6067`
- Current `origin/main` at audit time: `945226f3fbfeea381084f5a08d2d7770f2f52be3`
- Ahead/behind before removal: `309 27` from `git rev-list --left-right --count origin/main...codex/full-6x-roundtrip`
- Worktree before removal: `C:/Users/bill/.config/superpowers/worktrees/ras-commander/full-6x-roundtrip`

Branch payload diff (`git diff --stat --summary origin/main...codex/full-6x-roundtrip`) showed:

```text
29 files changed, 11856 insertions(+), 264 deletions(-)
create mode 100644 examples/122_ras2025_muncie_geometry_roundtrip.ipynb
create mode 100644 ras_commander/Ras2025Roundtrip.py
create mode 100644 tests/test_ras2025_roundtrip.py
create mode 100644 tests/test_query_vs_raster_validation.py
```

Persistent evidence saved under `H:/Symphony/ras-commander/CLB-706/`:

- `codex-full-6x-roundtrip.bundle` - verified complete Git bundle for the removed branch
- `diffs/branch_payload_full.diff` - full branch-payload patch
- `diffs/branch_payload_name_status.txt`
- `diffs/branch_payload_numstat.txt`
- `diffs/current_main_vs_branch_stat.txt`
- `diffs/current_main_vs_branch_name_status.txt`
- `diffs/overlap_current_diff_stat.txt`
- `diffs/ras2025_current_diff_stat.txt`
- `diffs/unique_commits_on_branch.txt`
- `terminal-logs/` - recorded fetch, diff, bundle, removal, and test commands

## Salvaged Work

### `RasUtils.discover_ras_versions()` HEC-RAS 6.6 discovery

Current main already had `RasPrj.get_ras_exe("66")` mapped to HEC-RAS `6.6`, but `RasUtils.discover_ras_versions()` had drifted:

- It scanned `7.0` twice and did not scan the standard `6.6` folder.
- It normalized compact folder/version token `"66"` to `"7.0"` instead of `"6.6"`.

I salvaged the branch's correct behavior as a focused current-main patch:

- `ras_commander/RasUtils.py`
  - restore `6.6` in `discover_ras_versions()` known folder scan
  - normalize `"66"` to `"6.6"`
  - correct the docstring example
- `tests/test_legacy_plan_execution_helpers.py`
  - add simulated Windows install-folder tests for standard `6.6/Ras.exe`
  - add simulated compact `66/Ras.exe` normalization coverage

## Documented But Not Cherry-Picked

### RAS2025 roundtrip family

Files:

- `ras_commander/Ras2025Roundtrip.py`
- `examples/122_ras2025_muncie_geometry_roundtrip.ipynb`
- `tests/test_ras2025_roundtrip.py`

Decision: **documented/deferred, not cherry-picked.**

Reasoning:

- This is real unsalvaged concept work, and it is the largest missed topic from the prior audit.
- It depends on a sibling `RASAlphaCLI`/HEC-RAS 2025 workflow and environment variables that are not current ras-commander API surface.
- The module is 1,626 lines of new public API/orchestration and HDF mutation logic. It needs a dedicated design/review issue before becoming package API.
- The tests are mostly synthetic/mocked orchestration tests; they do not validate the full Muncie/RASAlphaCLI/HEC-RAS 2025/6.x roundtrip against real software in this runner.
- The notebook number conflicts with current main's existing `examples/122_rasmapper_spatial_review.ipynb`.
- The notebook was previously executed on the stale branch with outputs and no stored error outputs, but it was not re-executed in this audit because it requires HEC-RAS 2025/RASAlphaCLI setup and this task was a salvage audit, not a new RAS2025 integration.

Future salvage path: open a dedicated issue to re-design this feature on current main using the saved bundle/patch as source material. Do not resurrect the stale branch directly.

### `HdfResultsQuery`

Decision: **discard branch version.**

Current main already has `HdfResultsQuery` plus newer profile-line/transverse query functionality. The stale branch implementation would remove current-main improvements. The branch's `tests/test_query_vs_raster_validation.py` is a script-style validator guarded by `if __name__ == "__main__"` rather than a pytest test function, and it requires HEC-RAS/raster export/rasterio execution. It should be rebuilt as a current-main validation test only if that exact raster-vs-query proof is still desired.

### `HdfLandCover`

Decision: **discard branch version.**

Current main already includes `set_landcover_raster_map()` and additional depth-varying roughness/conveyance-related work. The branch copy is older and would regress current-main behavior.

### `RasPermutation`

Decision: **discard branch version.**

Current main already contains the parameter sweep framework and associated example coverage through newer merged work. No unique branch hunk was worth applying.

### `GeomReferenceFeatures`, `HdfBndry`, `HdfMesh`, `Decorators`

Decision: **discard branch versions.**

Current main already has plain-text reference feature tooling, HDF result/query consumers, and later HDF decorator corrections. The stale branch would either duplicate or regress current implementations.

### eBFE model organization

Decision: **discard branch version.**

Current main has a newer eBFE model registry/organizer implementation, Tickfaw validation, and later eBFE delivery fixes. The stale branch's eBFE deltas are older and conflict heavily with current main.

## Removed Stale Ref

After preserving and verifying `H:/Symphony/ras-commander/CLB-706/codex-full-6x-roundtrip.bundle`, I removed:

- Worktree: `C:/Users/bill/.config/superpowers/worktrees/ras-commander/full-6x-roundtrip`
- Local branch: `codex/full-6x-roundtrip`

Post-removal checks showed no remaining `codex/full-6x-roundtrip` branch and no `full-6x-roundtrip` worktree entry.

## Validation

Recorded commands:

- `git fetch origin` in both the Symphony workspace and `G:/GH/ras-commander`
- `git diff --stat --summary origin/main...codex/full-6x-roundtrip`
- `git bundle create ... codex/full-6x-roundtrip`
- `git bundle verify H:/Symphony/ras-commander/CLB-706/codex-full-6x-roundtrip.bundle`
- stale worktree status and branch inventory before removal
- `git worktree remove .../full-6x-roundtrip`
- `git branch -D codex/full-6x-roundtrip`

Test validation:

```text
C:/Users/bill/anaconda3/envs/symphony-dev/python.exe -m pytest tests/test_legacy_plan_execution_helpers.py -q
7 passed in 9.14s
```

One earlier recorded pytest wrapper attempt failed before pytest due to runner PATH/PowerShell quoting around `conda`; the rerun used the direct `symphony-dev` Python interpreter and passed.
