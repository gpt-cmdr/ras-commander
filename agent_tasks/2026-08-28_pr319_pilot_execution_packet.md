# PR 319 Representative Local-Engine Pilot Packet

## Authority

This packet is the exact HEC-RAS execution scope approved by the maintainer on
2026-08-28 under the parent task
`2026-08-28_pr319_structured_execution_qualification.md`.

Every calculation runs on a fresh disposable staged copy. Source projects are
read-only inputs. Engine launch, process inspection, result cleanup, and
execution-evidence inspection go exclusively through ras-commander APIs.

## Destinations

- Disposable lane root:
  `C:\Users\billk_clb\AppData\Local\ras-commander\pr319_execution_qualification_2026-08-28\pilot\lanes`
- Durable audit root:
  `H:\CLB-Repos\ras-commander\working\pr319_execution_qualification_2026-08-28\pilot`

Each lane receives its own leaf directory named by `lane_id`. No lane may reuse
another lane's writable directory.

## Approved lanes

| Lane ID | Source key / plan | Selected engine | Executable SHA-256 | ras-commander API | Expected terminal result family |
|---|---|---|---|---|---|
| `steady_1d__4_0__pilot` | `steady_1d` / `01` | HEC-RAS 4.0 | `29f22cd3330ca14e7b92a5e8ca0293cb46a582156ae2bd03bbb1b83f1701300b` | `RasControl.run_plan` with exact 4.0 Controller | legacy `.O01`; plan HDF absent |
| `unsteady_1d__4_1_0__pilot` | `unsteady_1d` / `06` | HEC-RAS 4.1.0 | `b9b1cb9376ccfe63dcca8969c518e095059ea7aba7340b04eabb7a5dd2c9dc17` | `RasControl.run_plan` with exact 4.1 Controller | legacy `.O06`; plan HDF absent |
| `steady_1d__6_1__pilot` | `steady_1d` / `01` | HEC-RAS 6.1 | `58423df21f7115340a9d41f5d93039a786c91f0ffc944f7b23c77846bcc9e330` | `RasCmdr.compute_plan` with explicit executable | plan `.p01.hdf`; `.O01` absent after finalization |
| `unsteady_1d__6_6__pilot` | `unsteady_1d` / `06` | HEC-RAS 6.6 | `a34e56a172ba06cde2d546f4d7282801c2b67040969d4ed23b41dfc755772134` | `RasCmdr.compute_plan` with explicit executable | plan `.p06.hdf`; `.O06` absent after finalization |
| `unsteady_2d__7_0__pilot` | `unsteady_2d` / `18` | HEC-RAS 7.0 | `9990c10531221469bf51a9a62ae91f36ec01e651bed83aadf632e678130ae797` | `RasCmdr.compute_plan` with explicit executable | plan `.p18.hdf`; `.O18` absent after finalization |

## Exact executables

- `C:\Program Files (x86)\HEC\HEC-RAS\4.0\Ras.exe`
- `C:\Program Files (x86)\HEC\HEC-RAS\4.1.0\Ras.exe`
- `C:\Program Files (x86)\HEC\HEC-RAS\6.1\Ras.exe`
- `C:\Program Files (x86)\HEC\HEC-RAS\6.6\Ras.exe`
- `C:\Program Files (x86)\HEC\HEC-RAS\7.0\Ras.exe`

The supervisor must recompute and compare each executable hash immediately
before dispatch. A mismatch blocks that lane.

## Expected per-lane sequence

1. Confirm the source-bundle hash and selected executable hash.
2. Confirm ras-commander reports no active HEC-RAS process that could interfere.
3. Stage the source bundle into the exact disposable lane directory.
4. Record the initially staged artifact inventory and timestamps.
5. Seed only the packet-defined mixed-format state needed to observe cleanup;
   label any seeded artifact `generated_edge_case` or `captured_real` accurately.
6. Initialize with the exact selected executable/controller.
7. Run the selected plan once through the listed ras-commander API.
8. Verify process termination, current-family freshness, opposing-family
   absence, message-sidecar handling, and structured execution evidence.
9. Persist typed PyArrow observations and read them back.
10. Rehash the source bundle.

## Required observations

At minimum, every lane record includes:

- repository commit and dirty-state indicator;
- source project path, source bundle hash, staged project path, and staged hash;
- project key, plan number, plan title, and parsed plan type;
- plan-declared Program Version before and after execution;
- requested and resolved executable/controller identity and hashes;
- worker PID, owned RAS PIDs, start/end UTC timestamps, monotonic duration,
  timeout, and terminal status;
- artifact path, family, origin, existence, size, SHA-256, and `mtime_ns` at
  `staged`, `prepared`, `computed`, and `finalized` checkpoints;
- execution API result, compute messages, warning/error classification, and
  structured evidence completion/freshness/version fields;
- cleanup removals and misses at preparation and finalization;
- source immutability and Parquet readback assertions.

## Pilot acceptance

A lane passes only when:

- the selected current-family result exists and is fresh relative to lane
  dispatch;
- the opposing result family is absent after successful finalization;
- the selected result opens or parses through ras-commander's appropriate
  result reader;
- structured evidence selects the expected family and does not combine
  conflicting families;
- no cleanup escapes the staged plan scope;
- no owned process survives;
- its source bundle remains unchanged;
- the typed audit record validates after Parquet readback.

A genuine solver failure is not converted into a passing lane. The harness may
record it as a contained expected/observed failure, but the pilot cannot qualify
that project/version behavior until its intended acceptance condition is
demonstrated or the maintainer approves a version-specific limitation.

## Verification after the five lanes

- Query the Parquet tables with PyArrow and assert five unique terminal lane
  rows and no duplicate artifact checkpoint keys.
- Compare selected evidence to actual staged filesystem artifacts.
- Re-run read-only inspection in a fresh process for every lane.
- Run deterministic tests for the exact before/after artifact states observed.
- Produce `summary.md` with discrepancies, process leaks, cleanup actions,
  warnings, errors, runtime, and source-hash verification.
- Do not expand to the full installed-version matrix until all hard-stop issues
  are resolved.
